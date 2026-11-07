# Sets up a Windows machine for the hub machine's admin connection: OpenSSH Server with the hub's key for the
# administrator account that runs it, then a record of the machine for fleet_usb.py import on the hub machine.
# Run it from the drive in an elevated Windows PowerShell, signed in as the account the agent will use:
#   powershell -NoProfile -ExecutionPolicy Bypass -File <drive>:\fleet-usb\setup-windows.ps1
# It holds no hosts or credentials, and repeating it changes nothing.
#Requires -RunAsAdministrator
$ErrorActionPreference = 'Stop'

$usb = $PSScriptRoot
$sshData = Join-Path $env:ProgramData 'ssh'
$changed = New-Object System.Collections.Generic.List[string]

$hubKey = ([IO.File]::ReadAllText((Join-Path $usb 'hub.pub'))).Trim()
if ($hubKey -notmatch '^ssh-ed25519 [A-Za-z0-9+/]+={0,2}( \S+)?$') { throw 'hub.pub is not one ed25519 public key' }

# Appends the key unless the file already holds its key body. Returns $true only when it wrote.
function Add-KeyLine([string]$Path, [string]$Key) {
    $body = ($Key -split ' ')[1]
    $raw = if (Test-Path -LiteralPath $Path) { [IO.File]::ReadAllText($Path) } else { '' }
    foreach ($line in ($raw -split "`r?`n")) { if (($line -split ' ')[1] -eq $body) { return $false } }
    $prefix = if ($raw -and -not $raw.EndsWith("`n")) { "`r`n" } else { '' }
    [IO.File]::AppendAllText($Path, "$prefix$Key`r`n", [Text.Encoding]::ASCII)
    return $true
}

# 1. The SSH server, started now and at each boot.
$capability = Get-WindowsCapability -Online -Name 'OpenSSH.Server*' | Select-Object -First 1
if (-not $capability) { throw 'this Windows offers no OpenSSH.Server capability' }
if ($capability.State -ne 'Installed') {
    Write-Host 'Installing OpenSSH Server from Windows Update. This can take 10 to 15 minutes.'
    try {
        Add-WindowsCapability -Online -Name $capability.Name | Out-Null
    } catch [System.Runtime.InteropServices.COMException] {
        # A WinRM or other network session gets this; an elevated console run does not.
        throw "OpenSSH Server could not be installed ($($_.Exception.Message)). Run this from an elevated console on the machine, not over a remote session."
    }
    $changed.Add('openssh-server')
}
if ((Get-Service sshd).StartType -ne 'Automatic') { Set-Service sshd -StartupType Automatic; $changed.Add('sshd-automatic') }
if ((Get-Service sshd).Status -ne 'Running') { Start-Service sshd; $changed.Add('sshd-started') }

# 2. Sessions start in Windows PowerShell rather than cmd.
$openSsh = 'HKLM:\SOFTWARE\OpenSSH'
$shell = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
if (-not (Test-Path $openSsh)) { New-Item $openSsh | Out-Null }
if ((Get-ItemProperty $openSsh -ErrorAction SilentlyContinue).DefaultShell -ne $shell) {
    Set-ItemProperty $openSsh -Name DefaultShell -Value $shell
    $changed.Add('default-shell')
}

# 3. Port 22 answers the local subnet only, on every network profile.
$ruleName = 'OpenSSH-Server-In-TCP'
$rule = Get-NetFirewallRule -Name $ruleName -ErrorAction SilentlyContinue
if (-not $rule) {
    New-NetFirewallRule -Name $ruleName -DisplayName 'OpenSSH SSH Server (sshd)' -Direction Inbound -Protocol TCP `
        -LocalPort 22 -Action Allow -RemoteAddress LocalSubnet -Profile Any | Out-Null
    $changed.Add('firewall-rule')
} else {
    $remote = @(($rule | Get-NetFirewallAddressFilter).RemoteAddress)
    if ($rule.Enabled -ne 'True' -or $rule.Profile -ne 'Any' -or ($remote -join ',') -ne 'LocalSubnet') {
        Set-NetFirewallRule -Name $ruleName -Enabled True -Profile Any -RemoteAddress LocalSubnet
        $changed.Add('firewall-rule')
    }
}

# 4. The hub's key. An administrator's key is read from the shared file, which only Administrators and SYSTEM
# may hold; the user's own file covers an sshd_config without that rule.
$adminKeys = Join-Path $sshData 'administrators_authorized_keys'
if (Add-KeyLine $adminKeys $hubKey) { $changed.Add('admin-key') }
& icacls.exe $adminKeys /inheritance:r /grant '*S-1-5-32-544:F' /grant '*S-1-5-18:F' | Out-Null
if ($LASTEXITCODE -ne 0) { throw "icacls exit $LASTEXITCODE on $adminKeys" }
$userSsh = Join-Path $env:USERPROFILE '.ssh'
if (-not (Test-Path $userSsh)) { New-Item -ItemType Directory $userSsh | Out-Null }
if (Add-KeyLine (Join-Path $userSsh 'authorized_keys') $hubKey) { $changed.Add('user-key') }

# 5. The record for the hub machine: the name, the account, the addresses and the host key to pin.
$hostKeyFile = Join-Path $sshData 'ssh_host_ed25519_key.pub'
for ($i = 0; $i -lt 20 -and -not (Test-Path $hostKeyFile); $i++) { Start-Sleep -Milliseconds 500 }
if (-not (Test-Path $hostKeyFile)) { throw "sshd made no host key at $hostKeyFile" }
$hostKey = (([IO.File]::ReadAllText($hostKeyFile)).Trim() -split ' ')[0..1] -join ' '
if (-not (Get-NetTCPConnection -LocalPort 22 -State Listen -ErrorAction SilentlyContinue)) { throw 'sshd is not listening on port 22' }
$addresses = [string[]]@(Get-NetIPAddress -AddressFamily IPv4 |
    Where-Object { $_.AddressState -eq 'Preferred' -and $_.IPAddress -notmatch '^(127|169\.254)\.' -and $_.InterfaceAlias -notmatch '^vEthernet' } |
    ForEach-Object IPAddress)

$name = $env:COMPUTERNAME.ToLowerInvariant()
$record = [ordered]@{
    v = 1
    name = $name
    os = 'windows'
    user = $env:USERNAME
    port = 22
    addresses = $addresses
    host_key = $hostKey
    changed = [string[]]$changed
    created = (Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ')
}
$members = Join-Path $usb 'members'
if (-not (Test-Path $members)) { New-Item -ItemType Directory $members | Out-Null }
$out = Join-Path $members "$name.json"
[IO.File]::WriteAllText($out, ($record | ConvertTo-Json), (New-Object Text.UTF8Encoding $false))

$fingerprint = & ssh-keygen.exe -lf (Join-Path $usb 'hub.pub') 2>$null
Write-Host "Hub key installed: $fingerprint"
Write-Host "Changed: $(if ($changed.Count) { $changed -join ', ' } else { 'nothing' })"
Write-Host "Wrote $out. Take the drive back to the hub machine and run the import there."
