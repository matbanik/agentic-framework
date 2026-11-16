# Sets up a Windows machine for the hub machine's admin connection: Git, Python and PowerShell (winget), OpenSSH
# Server with the hub's key for the account that runs it, uv, Claude Code and Codex for that account, RustDesk from
# the MSI on the drive (rustdesk.txt holds the hub's server and key; without it the step is skipped), then a record
# of the machine on the drive for fleet_usb.py import on the hub machine.
# Run it from the drive: double-click "Setup Windows.cmd", or in Windows PowerShell, signed in as the account the
# agent will use (the script asks for administrator rights itself):
#   powershell -NoProfile -ExecutionPolicy Bypass -File <drive>:\fleet-usb\setup-windows.ps1
# It holds no hosts or credentials, and repeating it changes nothing.
#
# The record, members\<name>.json, is written as soon as the name is known and again after each step, so the drive
# holds the steps done so far at every moment. A step that fails ends "failed" and the script goes on; only a step
# that needs a failed step is "skipped". The last write sets "final", also when a step threw, when the UAC prompt
# was cancelled and on Ctrl+C. A forced kill leaves the last checkpoint.
#
# After the final write the script sends the record to the hub: hub.txt on the drive holds the hub's url lines and
# the token line, and curl.exe posts the record to each url in turn until one answers 200. The drive copy's delivery
# is pending while the send runs, then sent or failed; the result of the run comes from ok only, never from the send.
#
# -LibraryOnly defines the functions and returns, so the tests can load the script without running it.
param(
    [switch]$LibraryOnly,
    [string]$RunId = '',
    [string]$ForUser = ''
)

# ---------------------------------------------------------------------------------------------------- wrappers
# Each command family that a test must replace goes through one function here.

# Runs a native command, shows its output and returns its exit code. An installer's stderr is shown, not raised.
function Invoke-Native([string]$File, [string[]]$Arguments = @()) {
    $previous = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        & $File @Arguments 2>&1 | Out-Host
        return $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $previous
    }
}

# The path of curl.exe (it ships in System32 on Windows 10 and later), or $null.
function Get-CurlPath {
    $found = Get-Command 'curl.exe' -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($found) { return [string]$found.Source }
    return $null
}

# Runs curl.exe and returns its exit code and what it printed on stdout. Its stderr is dropped: the arguments hold
# the token, and an error line must not be able to show it.
function Invoke-Curl([string]$Curl, [string[]]$Arguments) {
    $previous = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        $output = & $Curl @Arguments 2>$null
        $exit = $LASTEXITCODE
        return [pscustomobject]@{ Exit = $exit; Output = ((@($output) -join '').Trim()) }
    } finally {
        $ErrorActionPreference = $previous
    }
}

# The program of RustDesk. The MSI installs it under Program Files and registers the "RustDesk" service.
function Get-RustDeskExe { return (Join-Path (Join-Path $env:ProgramFiles 'RustDesk') 'rustdesk.exe') }

# The two folders that hold RustDesk2.toml: the service's (the LocalService profile) and the account's own.
function Get-RustDeskConfigDirs {
    return [pscustomobject]@{
        Service = (Join-Path $env:SystemRoot 'ServiceProfiles\LocalService\AppData\Roaming\RustDesk\config')
        Account = (Join-Path $env:APPDATA 'RustDesk\config')
    }
}

# Runs rustdesk.exe and returns its exit code and what it printed. The program is a GUI program: PowerShell waits
# for it, and keeps what it prints, only when the output goes down a pipeline.
function Invoke-RustDesk([string[]]$Arguments) {
    $previous = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        $output = & (Get-RustDeskExe) @Arguments 2>&1 | Out-String
        $exit = $LASTEXITCODE
        return [pscustomobject]@{ Exit = $exit; Output = ([string]$output).Trim() }
    } finally {
        $ErrorActionPreference = $previous
    }
}

# The installed version of RustDesk (x.y.z) from the program file, or $null when it is not installed.
function Get-RustDeskVersion {
    $exe = Get-RustDeskExe
    if (-not (Test-Path -LiteralPath $exe -PathType Leaf)) { return $null }
    $info = (Get-Item -LiteralPath $exe).VersionInfo
    foreach ($text in @($info.ProductVersion, $info.FileVersion)) {
        if ([string]$text -match '([0-9]+\.[0-9]+\.[0-9]+)') { return $Matches[1] }
    }
    return $null
}

# The text of a config file, or $null when there is none.
function Read-ConfigFile([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { return $null }
    return [IO.File]::ReadAllText($Path)
}

# UTF-8 without a BOM, through a temp file and a rename in the same folder. The folder is made when it is missing.
function Write-ConfigFile([string]$Path, [string]$Text) {
    $folder = Split-Path -Parent $Path
    if (-not (Test-Path -LiteralPath $folder)) { New-Item -ItemType Directory -Path $folder -Force | Out-Null }
    $tmp = "$Path.tmp"
    [IO.File]::WriteAllText($tmp, $Text, (New-Object Text.UTF8Encoding $false))
    Move-Item -LiteralPath $tmp -Destination $Path -Force
}

function Test-Administrator {
    $principal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

# The python.exe and python3.exe in WindowsApps are the Microsoft Store's stubs: they open the Store and are no
# Python, so they do not count.
function Test-OnPath([string]$Name) {
    $stub = '\\Microsoft\\WindowsApps\\python3?(\.\d+)?\.exe$'
    $found = @(Get-Command $Name -All -ErrorAction SilentlyContinue |
        Where-Object { -not ($_.CommandType -eq 'Application' -and $_.Source -match $stub) })
    return ($found.Count -gt 0)
}

# The raw Path value of one scope, with its %variables% left as they are.
function Get-PathValue([string]$Scope) {
    $key = if ($Scope -eq 'User') {
        [Microsoft.Win32.Registry]::CurrentUser.OpenSubKey('Environment')
    } else {
        [Microsoft.Win32.Registry]::LocalMachine.OpenSubKey('SYSTEM\CurrentControlSet\Control\Session Manager\Environment')
    }
    try {
        return [string]$key.GetValue('Path', '', [Microsoft.Win32.RegistryValueOptions]::DoNotExpandEnvironmentNames)
    } finally {
        $key.Close()
    }
}

# Writes the User Path as an expandable string, then touches a variable so that running programs hear the change.
function Set-UserPathValue([string]$Value) {
    $key = [Microsoft.Win32.Registry]::CurrentUser.OpenSubKey('Environment', $true)
    try {
        $key.SetValue('Path', $Value, [Microsoft.Win32.RegistryValueKind]::ExpandString)
    } finally {
        $key.Close()
    }
    try {
        [Environment]::SetEnvironmentVariable('FLEET_USB_TOUCH', '1', 'User')
        [Environment]::SetEnvironmentVariable('FLEET_USB_TOUCH', $null, 'User')
    } catch {
        Write-Host "The User Path changed, but the change was not announced: $($_.Exception.Message)"
    }
}

# Rebuilds this process's Path from the Machine and User values, as an SSH session of the account reads it at logon.
function Update-SessionPath {
    $env:Path = [Environment]::ExpandEnvironmentVariables((Get-PathValue 'Machine') + ';' + (Get-PathValue 'User'))
}

# Adds a folder to the User Path unless it is there. Returns $true only when it wrote.
function Add-UserPathEntry([string]$Entry) {
    $parts = @((Get-PathValue 'User') -split ';' | Where-Object { $_ })
    $want = $Entry.TrimEnd('\')
    foreach ($part in $parts) {
        if ([Environment]::ExpandEnvironmentVariables($part).TrimEnd('\') -ieq $want) { return $false }
    }
    Set-UserPathValue -Value ((@($parts) + $Entry) -join ';')
    return $true
}

# ---------------------------------------------------------------------------------------------------- name, ids
# The same patterns as USER and RUN_ID in fleet_usb.py.
function Test-AccountName([string]$Name) { return ($Name -match '^[A-Za-z0-9_][A-Za-z0-9_. -]{0,63}$') }

function Test-RunId([string]$Id) { return ($Id -match '^[a-z0-9]{8,32}$') }

function ConvertTo-MemberName([string]$Raw) {
    $name = ($Raw.ToLowerInvariant() -replace '[^a-z0-9-]', '-') -replace '-{2,}', '-'
    $name = $name.Trim('-')
    if ($name.Length -gt 63) { $name = $name.Substring(0, 63).TrimEnd('-') }
    if (-not $name) { return 'member' }
    return $name
}

function New-RunId {
    $letters = 'abcdefghijklmnopqrstuvwxyz0123456789'
    return -join (1..16 | ForEach-Object { $letters[(Get-Random -Maximum $letters.Length)] })
}

# One string, so that a drive folder or an account name with a space reaches the elevated child whole.
# Start-Process joins an array with spaces and does not quote its elements.
function Get-ElevatedArgs([string]$Self, [string]$RunId, [string]$User) {
    if (-not (Test-RunId $RunId)) { throw "the run id is not valid: $RunId" }
    if (-not (Test-AccountName $User)) { throw "the account name is not valid: $User" }
    return "-NoProfile -ExecutionPolicy Bypass -File `"$Self`" -RunId $RunId -ForUser `"$User`""
}

# ---------------------------------------------------------------------------------------------------- the record
function Format-Detail([string]$Text) {
    $one = ($Text -replace '\s+', ' ').Trim()
    if ($one.Length -gt 300) { return $one.Substring(0, 300) }
    return $one
}

function Get-RecordPath([string]$Usb, [string]$Name) {
    return (Join-Path (Join-Path $Usb 'members') "$Name.json")
}

# The record that Record v2 describes. $Ctx holds the run so far.
function New-Record($Ctx, [bool]$Final) {
    $failed = @($Ctx.Steps | Where-Object { $_.status -eq 'failed' })
    $user = if (Test-AccountName $Ctx.Account) { $Ctx.Account } else { 'unknown' }
    return [ordered]@{
        v            = 2
        run_id       = $Ctx.RunId
        final        = $Final
        name         = $Ctx.Name
        os           = 'windows'
        user         = $user
        ok           = ($Final -and $failed.Count -eq 0)
        steps        = @($Ctx.Steps | ForEach-Object { [ordered]@{ step = $_.step; status = $_.status; detail = $_.detail } })
        tools        = $Ctx.Tools
        gui          = $true
        session_type = 'windows'
        rustdesk_id  = $Ctx.RustDeskId
        port         = $Ctx.Port
        host_key     = $Ctx.HostKey
        addresses    = [string[]]@($Ctx.Addresses)
        delivery     = $Ctx.Delivery
    }
}

# UTF-8 without a BOM, through a temp file and a rename in the same folder.
function Write-RecordFile([string]$Path, $Record) {
    $folder = Split-Path -Parent $Path
    if (-not (Test-Path -LiteralPath $folder)) { New-Item -ItemType Directory -Path $folder -Force | Out-Null }
    $tmp = "$Path.tmp"
    [IO.File]::WriteAllText($tmp, ($Record | ConvertTo-Json -Depth 6), (New-Object Text.UTF8Encoding $false))
    Move-Item -LiteralPath $tmp -Destination $Path -Force
}

# A drive that cannot be written (a write-protected stick) must not stop the run: the steps still work.
function Save-Record([string]$Path, $Record) {
    try {
        Write-RecordFile $Path $Record
        return $true
    } catch {
        Write-Host "The record could not be written to $Path : $($_.Exception.Message)"
        return $false
    }
}

function Read-RecordFile([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path)) { return $null }
    try { return [IO.File]::ReadAllText($Path) | ConvertFrom-Json } catch { return $null }
}

function Add-Step($Ctx, [string]$Id, [string]$Status, [string]$Detail) {
    $Ctx.Steps.Add([pscustomobject]@{ step = $Id; status = $Status; detail = (Format-Detail $Detail) })
}

function Test-StepOk($Ctx, [string]$Id) {
    return [bool]($Ctx.Steps | Where-Object { $_.step -eq $Id -and $_.status -eq 'ok' })
}

function New-Context([string]$Usb, [string]$RunId, [string]$Account, [string]$ComputerName) {
    return @{
        Usb       = $Usb
        RunId     = $RunId
        Account   = $Account
        Name      = (ConvertTo-MemberName $ComputerName)
        Steps     = New-Object System.Collections.Generic.List[object]
        Tools     = [ordered]@{}
        Port       = $null
        HostKey    = $null
        Addresses  = @()
        RustDeskId = $null
        Delivery   = $null
    }
}

# ---------------------------------------------------------------------------------------------------- the steps
# The Step list in order. A step runs only when every step it needs ended ok; otherwise it ends skipped.
function Get-SetupSteps {
    return @(
        [pscustomobject]@{ Id = 'elevate'; Fn = 'Step-Elevate'; Needs = @() }
        [pscustomobject]@{ Id = 'account'; Fn = 'Step-Account'; Needs = @() }
        [pscustomobject]@{ Id = 'packages'; Fn = 'Step-Packages'; Needs = @('elevate') }
        [pscustomobject]@{ Id = 'ssh_server'; Fn = 'Step-SshServer'; Needs = @('elevate') }
        [pscustomobject]@{ Id = 'firewall'; Fn = 'Step-Firewall'; Needs = @('elevate') }
        [pscustomobject]@{ Id = 'hub_key'; Fn = 'Step-HubKey'; Needs = @('elevate', 'account', 'ssh_server') }
        [pscustomobject]@{ Id = 'admin_rights'; Fn = 'Step-AdminRights'; Needs = @('elevate', 'account', 'ssh_server') }
        [pscustomobject]@{ Id = 'pwsh'; Fn = 'Step-Pwsh'; Needs = @('account') }
        [pscustomobject]@{ Id = 'uv'; Fn = 'Step-Uv'; Needs = @('account') }
        [pscustomobject]@{ Id = 'claude'; Fn = 'Step-Claude'; Needs = @('account') }
        [pscustomobject]@{ Id = 'codex'; Fn = 'Step-Codex'; Needs = @('account') }
        [pscustomobject]@{ Id = 'rustdesk'; Fn = 'Step-RustDesk'; Needs = @('elevate') }
        [pscustomobject]@{ Id = 'host_key'; Fn = 'Step-HostKey'; Needs = @('elevate', 'ssh_server') }
    )
}

function Step-Elevate {
    if (-not (Test-Administrator)) { throw 'this script has no administrator rights' }
    return 'administrator'
}

# The tool installs and the key files belong to the session's own profile, so the session must be the Account.
function Step-Account {
    $account = $ctx.Account
    if (-not (Test-AccountName $account)) { throw "the account name is not valid: $account" }
    if ($env:USERNAME -ne $account) {
        throw "this session is $env:USERNAME, not $account. Run the setup from the $account account's own administrator session."
    }
    return $account
}

# The SSH server, started now and at each boot, with sessions in Windows PowerShell rather than cmd.
function Step-SshServer {
    $changes = New-Object System.Collections.Generic.List[string]
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
        $changes.Add('openssh-server')
    }
    if ((Get-Service sshd).StartType -ne 'Automatic') { Set-Service sshd -StartupType Automatic; $changes.Add('sshd-automatic') }
    if ((Get-Service sshd).Status -ne 'Running') { Start-Service sshd; $changes.Add('sshd-started') }

    $openSsh = 'HKLM:\SOFTWARE\OpenSSH'
    $shell = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
    if (-not (Test-Path $openSsh)) { New-Item $openSsh | Out-Null }
    if ((Get-ItemProperty $openSsh -ErrorAction SilentlyContinue).DefaultShell -ne $shell) {
        Set-ItemProperty $openSsh -Name DefaultShell -Value $shell
        $changes.Add('default-shell')
    }
    if ($changes.Count) { return ($changes -join ', ') }
    return 'already set'
}

# Port 22 answers the local subnet only, on every network profile.
function Step-Firewall {
    $ruleName = 'OpenSSH-Server-In-TCP'
    $rule = Get-NetFirewallRule -Name $ruleName -ErrorAction SilentlyContinue
    if (-not $rule) {
        New-NetFirewallRule -Name $ruleName -DisplayName 'OpenSSH SSH Server (sshd)' -Direction Inbound -Protocol TCP `
            -LocalPort 22 -Action Allow -RemoteAddress LocalSubnet -Profile Any | Out-Null
        return 'rule made'
    }
    $remote = @(($rule | Get-NetFirewallAddressFilter).RemoteAddress)
    if ($rule.Enabled -ne 'True' -or $rule.Profile -ne 'Any' -or ($remote -join ',') -ne 'LocalSubnet') {
        Set-NetFirewallRule -Name $ruleName -Enabled True -Profile Any -RemoteAddress LocalSubnet
        return 'rule corrected'
    }
    return 'already set'
}

# Appends the key unless the file already holds its key body. Returns $true only when it wrote.
function Add-KeyLine([string]$Path, [string]$Key) {
    $body = ($Key -split ' ')[1]
    $raw = if (Test-Path -LiteralPath $Path) { [IO.File]::ReadAllText($Path) } else { '' }
    foreach ($line in ($raw -split "`r?`n")) { if (($line -split ' ')[1] -eq $body) { return $false } }
    $prefix = if ($raw -and -not $raw.EndsWith("`n")) { "`r`n" } else { '' }
    [IO.File]::AppendAllText($Path, "$prefix$Key`r`n", [Text.Encoding]::ASCII)
    return $true
}

function Get-AdminKeyFile { return (Join-Path (Join-Path $env:ProgramData 'ssh') 'administrators_authorized_keys') }

# The hub's key, for an administrator (the shared file) and for the account's own file, which covers an
# sshd_config without the administrators rule.
function Step-HubKey {
    $hubKey = ([IO.File]::ReadAllText((Join-Path $ctx.Usb 'hub.pub'))).Trim()
    if ($hubKey -notmatch '^ssh-ed25519 [A-Za-z0-9+/]+={0,2}( \S+)?$') { throw 'hub.pub is not one ed25519 public key' }
    $changes = New-Object System.Collections.Generic.List[string]
    if (Add-KeyLine (Get-AdminKeyFile) $hubKey) { $changes.Add('admin-key') }
    $userSsh = Join-Path $env:USERPROFILE '.ssh'
    if (-not (Test-Path $userSsh)) { New-Item -ItemType Directory $userSsh | Out-Null }
    if (Add-KeyLine (Join-Path $userSsh 'authorized_keys') $hubKey) { $changes.Add('user-key') }
    if ($changes.Count) { return ($changes -join ', ') }
    return 'already set'
}

# Only Administrators and SYSTEM may hold the shared key file, or sshd refuses it.
function Step-AdminRights {
    $file = Get-AdminKeyFile
    if (-not (Test-Path -LiteralPath $file)) { throw "$file does not exist" }
    $code = Invoke-Native 'icacls.exe' @($file, '/inheritance:r', '/grant', '*S-1-5-32-544:F', '/grant', '*S-1-5-18:F')
    if ($code -ne 0) { throw "icacls exit $code on $file" }
    return 'key file locked to Administrators and SYSTEM'
}

# Runs a tool's official installer unless the tool is on PATH already. The Path is rebuilt from the registry after
# the install, and %USERPROFILE%\.local\bin is in the User Path once. A tool that is still missing fails its step.
function Install-Tool([string]$Name, [string]$Url) {
    Update-SessionPath
    $installed = $false
    if (-not (Test-OnPath $Name)) {
        Write-Host "Installing $Name..."
        $installer = Join-Path $env:TEMP "$Name-install.ps1"
        $code = Invoke-Native 'curl.exe' @('-sS', '-L', '-f', '-o', $installer, $Url)
        if ($code -ne 0) { throw "the $Name installer did not download (curl exit $code). Check the network, then run this again." }
        $code = Invoke-Native 'powershell.exe' @('-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-File', $installer)
        Remove-Item $installer -ErrorAction SilentlyContinue
        if ($code -ne 0) { throw "the $Name installer failed (exit $code)" }
        $installed = $true
    }
    Add-UserPathEntry (Join-Path $env:USERPROFILE '.local\bin') | Out-Null
    Update-SessionPath
    if (-not (Test-OnPath $Name)) { throw "$Name is not on PATH after install" }
    if ($installed) { return 'installed' }
    return 'already installed'
}

# winget answers "nothing to do" with 0x8A15002B (no applicable update) or 0x8A150061 (already installed). A process
# exit code reads as signed or unsigned, so the test is on the low 32 bits.
function Test-WingetAlreadyInstalled([long]$Code) {
    $unsigned = $Code -band 0xFFFFFFFFL
    return ($unsigned -eq 2316632107L -or $unsigned -eq 2316632161L)
}

function Install-WingetPackage([string]$Id) {
    $code = Invoke-Native 'winget' @('install', '--id', $Id, '-e', '--silent', '--accept-package-agreements', '--accept-source-agreements')
    if ($code -eq 0) { return 'installed' }
    if (Test-WingetAlreadyInstalled $code) { return 'already installed' }
    $shown = if ($code -lt 0 -or $code -gt 65535) { '0x{0:X8}' -f ([long]$code -band 0xFFFFFFFFL) } else { "$code" }
    throw "winget install $Id failed (exit $shown)"
}

# Installs each package, one failing does not stop the next, then rebuilds the Path so that a tool whose installer
# wrote only the User Path value is found. Without winget (Windows Server, a machine without App Installer) the step
# fails with the instruction and nothing throws past the step.
function Install-WingetSet([string[]]$Ids) {
    if (-not (Test-OnPath 'winget')) { throw 'install App Installer from the Microsoft Store' }
    $done = New-Object System.Collections.Generic.List[string]
    $failed = New-Object System.Collections.Generic.List[string]
    foreach ($id in $Ids) {
        try { $done.Add("$id $(Install-WingetPackage $id)") } catch { $failed.Add($_.Exception.Message) }
    }
    Update-SessionPath
    if ($failed.Count) { throw ($failed -join '; ') }
    return ($done -join ', ')
}

# Git and Python for the whole machine.
function Step-Packages {
    $detail = Install-WingetSet @('Git.Git', 'Python.Python.3.14')
    if (-not (Test-OnPath 'git')) { throw 'git is not on PATH after install' }
    if (-not ((Test-OnPath 'python') -or (Test-OnPath 'py'))) { throw 'python is not on PATH after install' }
    return $detail
}

function Step-Pwsh {
    $detail = Install-WingetSet @('Microsoft.PowerShell')
    if (-not (Test-OnPath 'pwsh')) { throw 'pwsh is not on PATH after install' }
    return $detail
}

# The official installer of uv puts it in %USERPROFILE%\.local\bin, like the two installers below.
function Step-Uv { return (Install-Tool 'uv' 'https://astral.sh/uv/install.ps1') }

# The first line of "<command> --version", cut to 200 characters. $null when the command is not on PATH or does not
# answer with exit code 0.
function Get-ToolVersion([string]$Command) {
    if (-not (Test-OnPath $Command)) { return $null }
    $previous = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        $lines = @(& $Command --version 2>&1)
        $code = $LASTEXITCODE
    } catch {
        return $null
    } finally {
        $ErrorActionPreference = $previous
    }
    if ($code -ne 0) { return $null }
    $first = @($lines | ForEach-Object { "$_".Trim() } | Where-Object { $_ }) | Select-Object -First 1
    if (-not $first) { return $null }
    if ($first.Length -gt 200) { return $first.Substring(0, 200) }
    return $first
}

# The versions of the tools that the account finds after the Path is rebuilt, so that a tool installed earlier in the
# run counts. A tool that is missing has no key. The Path of this process is put back afterwards.
function Get-ToolVersions {
    $saved = $env:Path
    $tools = [ordered]@{}
    try {
        Update-SessionPath
        $wanted = @(
            @{ Key = 'git'; Commands = @('git') }
            @{ Key = 'python'; Commands = @('python', 'py') }
            @{ Key = 'pwsh'; Commands = @('pwsh') }
            @{ Key = 'uv'; Commands = @('uv') }
            @{ Key = 'claude'; Commands = @('claude') }
            @{ Key = 'codex'; Commands = @('codex') }
        )
        foreach ($tool in $wanted) {
            foreach ($command in $tool.Commands) {
                $version = Get-ToolVersion $command
                if ($version) { $tools[$tool.Key] = $version; break }
            }
        }
        # RustDesk is a GUI program that is on no Path: its version comes from its file.
        $rustdesk = Get-RustDeskVersion
        if ($rustdesk) { $tools['rustdesk'] = [string]$rustdesk }
    } finally {
        $env:Path = $saved
    }
    return , $tools
}

# Neither tool is signed in here.
function Step-Claude { return (Install-Tool 'claude' 'https://claude.ai/install.ps1') }

function Step-Codex {
    $env:CODEX_NON_INTERACTIVE = '1'
    return (Install-Tool 'codex' 'https://chatgpt.com/codex/install.ps1')
}

# ---------------------------------------------------------------------------------------------------- RustDesk
# Reads rustdesk.txt as data: the version, the host and the key (the first valid line of each), and every
# "file=<name> <sha256>" line whose name is a plain file name. Any other line changes nothing, and ReadAllLines takes
# CR LF and LF alike. The same patterns as RUSTDESK_HOST, RUSTDESK_KEY and the file lines in fleet_usb.py.
function Read-RustDeskSettings([string]$Path) {
    $versionPattern = '^[0-9]+\.[0-9]+\.[0-9]+\z'
    $hostPattern = '^[A-Za-z0-9][A-Za-z0-9._-]{0,252}(:[0-9]{1,5})?\z'
    $keyPattern = '^[A-Za-z0-9+/=]{40,64}\z'
    $filePattern = '^([A-Za-z0-9._-]+) ([0-9a-f]{64})\z'
    $found = @{ Version = ''; HostName = ''; Key = '' }
    $files = New-Object System.Collections.Generic.List[object]
    foreach ($line in [IO.File]::ReadAllLines($Path)) {
        if ($line.StartsWith('version=', [StringComparison]::Ordinal)) {
            $value = $line.Substring(8)
            if (-not $found.Version -and $value -cmatch $versionPattern) { $found.Version = $value }
        } elseif ($line.StartsWith('host=', [StringComparison]::Ordinal)) {
            $value = $line.Substring(5)
            if (-not $found.HostName -and $value -cmatch $hostPattern) { $found.HostName = $value }
        } elseif ($line.StartsWith('key=', [StringComparison]::Ordinal)) {
            $value = $line.Substring(4)
            if (-not $found.Key -and $value -cmatch $keyPattern) { $found.Key = $value }
        } elseif ($line.StartsWith('file=', [StringComparison]::Ordinal)) {
            $value = $line.Substring(5)
            if ($value -cmatch $filePattern) { $files.Add([pscustomobject]@{ Name = $Matches[1]; Sha = $Matches[2] }) }
        }
    }
    return [pscustomobject]@{ Version = $found.Version; HostName = $found.HostName; Key = $found.Key; Files = $files.ToArray() }
}

# The sha256 of a file in lowercase hex.
function Get-FileSha256([string]$Path) {
    $sha = [Security.Cryptography.SHA256]::Create()
    $stream = [IO.File]::OpenRead($Path)
    try {
        return (-join ($sha.ComputeHash($stream) | ForEach-Object { $_.ToString('x2') }))
    } finally {
        $stream.Dispose()
        $sha.Dispose()
    }
}

# The id that "rustdesk --get-id" prints: the first line of 6 to 12 digits, else $null.
function Get-RustDeskId {
    $call = Invoke-RustDesk @('--get-id')
    foreach ($line in (([string]$call.Output) -split "`r?`n")) {
        $text = ($line -replace '\s', '')
        if ($text -cmatch '^[0-9]{6,12}\z') { return $text }
    }
    return $null
}

# Waits until "--get-id" prints an id: every 2 seconds, up to FLEET_RUSTDESK_WAIT_S seconds (60 when not set).
function Wait-RustDeskReady {
    $limit = 60
    $given = [string]$env:FLEET_RUSTDESK_WAIT_S
    if ($given -cmatch '^[0-9]{1,4}\z') { $limit = [int]$given }
    $waited = 0
    while ($true) {
        if (Get-RustDeskId) { return }
        if ($waited -ge $limit) { throw 'service not ready' }
        Start-Sleep -Seconds 2
        $waited += 2
    }
}

# The value of "<name> = '<value>'" (single or double quotes) in a TOML text: its first line of that name, or $null.
function Get-TomlValue([string]$Text, [string]$Name) {
    $pattern = "^\s*$([regex]::Escape($Name))\s*=\s*[`"']([^`"']*)[`"']"
    foreach ($line in ($Text -split "`r?`n")) {
        if ($line -cmatch $pattern) { return $Matches[1] }
    }
    return $null
}

# The TOML text with the server and the key in its [options] table: the old custom-rendezvous-server and key lines of
# that table go, and every other line stays. A text with no [options] table gets one at the end.
function Merge-RustDeskToml([string]$Text, [string]$HostName, [string]$Key) {
    $out = New-Object System.Collections.Generic.List[string]
    $section = ''
    $seen = $false
    if ($Text) {
        $lines = @($Text -split "`r?`n")
        if ($lines[$lines.Count - 1] -eq '') { $lines = @($lines | Select-Object -SkipLast 1) }
        foreach ($line in $lines) {
            if ($line -match '^\s*\[([^\]]*)\]\s*$') {
                $section = $Matches[1]
                $out.Add($line)
                if ($section -ceq 'options') {
                    $seen = $true
                    $out.Add("custom-rendezvous-server = '$HostName'")
                    $out.Add("key = '$Key'")
                }
                continue
            }
            if ($section -ceq 'options' -and $line -cmatch '^\s*(custom-rendezvous-server|key)\s*=') { continue }
            $out.Add($line)
        }
    }
    if (-not $seen) {
        $out.Add('[options]')
        $out.Add("custom-rendezvous-server = '$HostName'")
        $out.Add("key = '$Key'")
    }
    return (($out -join "`n") + "`n")
}

# Writes the server and the key into the RustDesk2.toml of one folder, and keeps its other settings.
function Set-RustDeskToml([string]$Path, [string]$HostName, [string]$Key) {
    try {
        Write-ConfigFile $Path (Merge-RustDeskToml (Read-ConfigFile $Path) $HostName $Key)
    } catch {
        throw "could not write ${Path}: $($_.Exception.Message)"
    }
}

# Installs RustDesk from the MSI on the drive, once its sha256 matches rustdesk.txt, then gives the service the hub's
# server and key. The first --get-id that prints an id is the sign that the service is up; --config runs once after
# it. When the service did not keep the server, both RustDesk2.toml files get it and the service restarts.
function Step-RustDesk {
    $file = Join-Path $ctx.Usb 'rustdesk.txt'
    if (-not (Test-Path -LiteralPath $file -PathType Leaf)) { return @{ status = 'skipped'; detail = 'no server configured' } }
    try {
        $settings = Read-RustDeskSettings $file
    } catch {
        throw "rustdesk.txt cannot be read: $($_.Exception.Message)"
    }
    if (-not $settings.Version) { throw 'rustdesk.txt holds no valid version line' }
    if (-not $settings.HostName) { throw 'rustdesk.txt holds no valid host line' }
    if (-not $settings.Key) { throw 'rustdesk.txt holds no valid key line' }
    $asset = @($settings.Files | Where-Object { $_.Name -cmatch '^rustdesk-[0-9.]+-x86_64\.msi\z' }) | Select-Object -First 1
    if (-not $asset) { return @{ status = 'skipped'; detail = 'no asset for windows' } }
    $msi = Join-Path (Join-Path $ctx.Usb 'rustdesk') $asset.Name
    if (-not (Test-Path -LiteralPath $msi -PathType Leaf)) {
        throw "$($asset.Name) is missing from the drive: run fleet_usb.py prepare on the hub"
    }
    if ((Get-FileSha256 $msi) -ne $asset.Sha) {
        throw "$($asset.Name) does not match its sha256 in rustdesk.txt: run fleet_usb.py prepare on the hub"
    }

    $have = Get-RustDeskVersion
    if ($have -eq $settings.Version) {
        Write-Host "RustDesk $have is already installed"
    } else {
        Write-Host "Installing RustDesk $($settings.Version)..."
        $code = Invoke-Native 'msiexec.exe' @('/i', $msi, '/qn', '/norestart')
        if ($code -ne 0 -and $code -ne 3010) { throw "msiexec exited $code" }
    }
    Wait-RustDeskReady

    $config = "host=$($settings.HostName),key=$($settings.Key)"
    $call = Invoke-RustDesk @('--config', $config)
    if ($call.Exit -ne 0) { Write-Host "rustdesk --config exited $($call.Exit); the config file decides" }
    $dirs = Get-RustDeskConfigDirs
    $serviceToml = Join-Path $dirs.Service 'RustDesk2.toml'
    if ((Get-TomlValue ([string](Read-ConfigFile $serviceToml)) 'custom-rendezvous-server') -cne $settings.HostName) {
        Write-Host 'RustDesk did not keep the server in its service folder: writing the config files'
        Set-RustDeskToml $serviceToml $settings.HostName $settings.Key
        Set-RustDeskToml (Join-Path $dirs.Account 'RustDesk2.toml') $settings.HostName $settings.Key
        Restart-Service -Name 'RustDesk' -Force
        Wait-RustDeskReady
    }

    $id = Get-RustDeskId
    if (-not $id) { $id = Get-TomlValue ([string](Read-ConfigFile (Join-Path $dirs.Service 'RustDesk.toml'))) 'id' }
    if (-not $id -or $id -cnotmatch '^[0-9]{6,12}\z') { throw 'no RustDesk id: --get-id printed none and RustDesk.toml holds none' }
    return @{ detail = "RustDesk $($settings.Version), server set"; data = @{ RustDeskId = [string]$id } }
}

# The host key to pin and the addresses, once sshd answers on port 22.
function Step-HostKey {
    $hostKeyFile = Join-Path (Join-Path $env:ProgramData 'ssh') 'ssh_host_ed25519_key.pub'
    for ($i = 0; $i -lt 20 -and -not (Test-Path $hostKeyFile); $i++) { Start-Sleep -Milliseconds 500 }
    if (-not (Test-Path $hostKeyFile)) { throw "sshd made no host key at $hostKeyFile" }
    $hostKey = (([IO.File]::ReadAllText($hostKeyFile)).Trim() -split ' ')[0..1] -join ' '
    if (-not (Get-NetTCPConnection -LocalPort 22 -State Listen -ErrorAction SilentlyContinue)) { throw 'sshd is not listening on port 22' }
    $addresses = [string[]]@(Get-NetIPAddress -AddressFamily IPv4 |
        Where-Object { $_.AddressState -eq 'Preferred' -and $_.IPAddress -notmatch '^(127|169\.254)\.' -and $_.InterfaceAlias -notmatch '^vEthernet' } |
        ForEach-Object IPAddress)
    if (-not $addresses.Count) { throw 'this machine has no IPv4 address on a physical network' }
    return @{ detail = 'pinned'; data = @{ Port = 22; HostKey = $hostKey; Addresses = $addresses } }
}

# ---------------------------------------------------------------------------------------------------- the send
function New-Delivery([string]$Status, [string]$Detail) {
    return [ordered]@{ status = $Status; detail = (Format-Detail $Detail) }
}

# The url lines of hub.txt that are a plain http or https address with a host and an optional port, and its first
# token line that fits. The file is read line by line and never evaluated; a line of any other kind changes
# nothing, and ReadAllLines takes CR LF and LF alike.
function Read-HubFile([string]$Path) {
    # The same patterns as HUB_URL and TOKEN in fleet_usb.py. \z, because $ also matches before a final line feed.
    $urlPattern = '^https?://[A-Za-z0-9.-]+(:[0-9]{1,5})?\z'
    $tokenPattern = '^[A-Za-z0-9_-]{32,64}\z'
    $urls = New-Object System.Collections.Generic.List[string]
    $token = ''
    foreach ($line in [IO.File]::ReadAllLines($Path)) {
        if ($line.StartsWith('url=', [StringComparison]::Ordinal)) {
            $value = $line.Substring(4)
            if ($value -cmatch $urlPattern) { $urls.Add($value) }
        } elseif ($line.StartsWith('token=', [StringComparison]::Ordinal) -and -not $token) {
            $value = $line.Substring(6)
            if ($value -cmatch $tokenPattern) { $token = $value }
        }
    }
    return [pscustomobject]@{ Urls = @($urls); Token = $token }
}

# What the final write holds for delivery, and what the send needs. A record that cannot be sent is failed at once,
# with the reason, so that the drive copy is written once; one that can be sent is pending until the send ends.
function Get-DeliveryPlan([string]$Usb) {
    $plan = @{ Delivery = $null; Curl = ''; Urls = @(); Token = '' }
    $file = Join-Path $Usb 'hub.txt'
    if (-not (Test-Path -LiteralPath $file -PathType Leaf)) {
        $plan.Delivery = New-Delivery 'failed' 'no hub.txt'
        return $plan
    }
    $curl = Get-CurlPath
    if (-not $curl) {
        $plan.Delivery = New-Delivery 'failed' 'no curl'
        return $plan
    }
    try {
        $hub = Read-HubFile $file
    } catch {
        $plan.Delivery = New-Delivery 'failed' "hub.txt cannot be read: $($_.Exception.Message)"
        return $plan
    }
    if (-not $hub.Token) {
        $plan.Delivery = New-Delivery 'failed' 'no valid token line in hub.txt'
    } elseif (-not $hub.Urls.Count) {
        $plan.Delivery = New-Delivery 'failed' 'no url line in hub.txt'
    } else {
        $plan.Delivery = New-Delivery 'pending' ''
        $plan.Curl = $curl
        $plan.Urls = $hub.Urls
        $plan.Token = $hub.Token
    }
    return $plan
}

# Posts the final record, with delivery null, to each url in turn and stops at the first 200. Returns the delivery:
# sent with the url, or failed with the result of each url. A stop during the send (PipelineStoppedException) goes
# up through here and leaves the drive copy as it is, pending.
function Send-Record($Ctx, $Plan) {
    $bodyCtx = $Ctx.Clone()
    $bodyCtx.Delivery = $null
    $body = Join-Path ([IO.Path]::GetTempPath()) ("fleet-usb-$([guid]::NewGuid().ToString('N')).json")
    $results = New-Object System.Collections.Generic.List[string]
    try {
        Write-RecordFile $body (New-Record $bodyCtx $true)
        foreach ($url in $Plan.Urls) {
            Write-Host "sending the record to $url"
            $arguments = @('-s', '-o', 'NUL', '-w', '%{http_code}', '-X', 'POST', '--connect-timeout', '5', '--max-time', '20',
                '-H', "X-Fleet-Token: $($Plan.Token)", '-H', 'Content-Type: application/json', '--data-binary', "@$body",
                "$url/v1/usb-record")
            try {
                $call = Invoke-Curl $Plan.Curl $arguments
            } catch [System.Management.Automation.PipelineStoppedException] {
                throw
            } catch {
                $results.Add("$url curl failed: $($_.Exception.Message)")
                continue
            }
            $code = if ($call.Output) { [string]$call.Output } else { '000' }
            if ($call.Exit -eq 0 -and $code -eq '200') { return (New-Delivery 'sent' $url) }
            if ($call.Exit -ne 0) { $results.Add("$url curl exit $($call.Exit)") } else { $results.Add("$url HTTP $code") }
        }
    } catch [System.Management.Automation.PipelineStoppedException] {
        throw
    } catch {
        $results.Add("the record could not be sent: $($_.Exception.Message)")
    } finally {
        Remove-Item -LiteralPath $body -Force -ErrorAction SilentlyContinue
    }
    return (New-Delivery 'failed' ($results -join '; '))
}

# The final write, the send and the write that holds its result. $Ctx.Delivery ends sent or failed, or pending when
# the run was stopped during the send.
function Complete-Record($Ctx, [string]$Path) {
    $plan = Get-DeliveryPlan $Ctx.Usb
    $Ctx.Delivery = $plan.Delivery
    Save-Record $Path (New-Record $Ctx $true) | Out-Null
    if ($plan.Delivery.status -eq 'pending') {
        $Ctx.Delivery = Send-Record $Ctx $plan
        Save-Record $Path (New-Record $Ctx $true) | Out-Null
    }
}

# ---------------------------------------------------------------------------------------------------- the run
# Runs every step in order, writes a checkpoint after each and the final record at the end, on every exit path that
# a script can catch. A step that throws ends failed; PipelineStoppedException (Ctrl+C) cannot be caught, so the
# step's finally block ends it failed with detail "interrupted".
function Invoke-Setup {
    param(
        [Parameter(Mandatory)][string]$Usb,
        [Parameter(Mandatory)][string]$RunId,
        [Parameter(Mandatory)][string]$Account,
        [Parameter(Mandatory)][string]$ComputerName
    )
    $ErrorActionPreference = 'Stop'
    $ctx = New-Context $Usb $RunId $Account $ComputerName
    $path = Get-RecordPath $Usb $ctx.Name
    Save-Record $path (New-Record $ctx $false) | Out-Null
    try {
        foreach ($step in Get-SetupSteps) {
            $unmet = @($step.Needs | Where-Object { -not (Test-StepOk $ctx $_) }) | Select-Object -First 1
            if ($unmet) {
                Add-Step $ctx $step.Id 'skipped' "needs $unmet"
            } else {
                $finished = $false
                try {
                    $result = @(& $step.Fn) | Select-Object -Last 1
                    $detail = if ($result -is [hashtable]) { [string]$result.detail } else { [string]$result }
                    # A step hands back only the data it owns, so each key is copied only when it is there.
                    if ($result -is [hashtable] -and $result.data) {
                        $keys = @($result.data.Keys)
                        if ($keys -contains 'Port') { $ctx.Port = $result.data.Port }
                        if ($keys -contains 'HostKey') { $ctx.HostKey = $result.data.HostKey }
                        if ($keys -contains 'Addresses') { $ctx.Addresses = @($result.data.Addresses) }
                        if ($keys -contains 'RustDeskId') { $ctx.RustDeskId = [string]$result.data.RustDeskId }
                    }
                    $status = if ($result -is [hashtable] -and $result.status -eq 'skipped') { 'skipped' } else { 'ok' }
                    Add-Step $ctx $step.Id $status $detail
                    $finished = $true
                } catch {
                    Add-Step $ctx $step.Id 'failed' $_.Exception.Message
                    $finished = $true
                } finally {
                    if (-not $finished) { Add-Step $ctx $step.Id 'failed' 'interrupted' }
                }
            }
            Save-Record $path (New-Record $ctx $false) | Out-Null
        }
        try {
            $ctx.Tools = Get-ToolVersions
        } catch {
            Write-Host "The tool versions could not be read: $($_.Exception.Message)"
        }
    } finally {
        Complete-Record $ctx $path
    }
    $record = New-Record $ctx $true
    return [pscustomobject]@{ ok = [bool]$record.ok; path = $path; record = $record }
}

function Write-Summary($Record, [string]$Path) {
    foreach ($step in @($Record.steps)) {
        $line = '{0,-8} {1}' -f $step.status, $step.step
        if ($step.detail) { $line += ": $($step.detail)" }
        Write-Host $line
    }
    $sent = [bool]($Record.delivery -and $Record.delivery.status -eq 'sent')
    $detail = if ($Record.delivery) { [string]$Record.delivery.detail } else { 'no result' }
    if ($Record.ok -and $sent) {
        Write-Host "Set up. Sent the record to the hub: $detail. A copy is in $Path."
    } elseif ($Record.ok) {
        Write-Host "Set up. Wrote $Path. The hub did not get the record ($detail); take the drive back to the hub machine and run the import there."
    } elseif ($sent) {
        Write-Host "Not every step worked. Sent the record to the hub: $detail. A copy is in $Path."
    } else {
        Write-Host "Not every step worked. The record is in $Path; the hub's agent reads it. The hub did not get it ($detail)."
    }
}

# The entry point. With administrator rights it runs the steps; without them it makes the run id, writes the first
# checkpoint and starts this script again elevated. A cancelled UAC prompt, or an elevated run that died before its
# final write, leaves the parent to finalize the record: it holds the reason, so the record still comes back.
function Start-Setup {
    param(
        [Parameter(Mandatory)][string]$Usb,
        [string]$RunId = '',
        [string]$ForUser = '',
        [Parameter(Mandatory)][string]$ComputerName,
        [string]$Self = ''
    )
    if (-not $ForUser) { $ForUser = $env:USERNAME }
    if (-not $RunId) { $RunId = New-RunId }
    if (Test-Administrator) {
        $result = Invoke-Setup -Usb $Usb -RunId $RunId -Account $ForUser -ComputerName $ComputerName
        Write-Summary $result.record $result.path
        return $result
    }

    $ctx = New-Context $Usb $RunId $ForUser $ComputerName
    $path = Get-RecordPath $Usb $ctx.Name
    Save-Record $path (New-Record $ctx $false) | Out-Null
    Write-Host 'Asking for administrator rights...'
    $reason = ''
    try {
        $process = Start-Process -FilePath 'powershell' -Verb RunAs -Wait -PassThru -ErrorAction Stop `
            -ArgumentList (Get-ElevatedArgs $Self $RunId $ForUser)
        if ($process -and $process.ExitCode -ne 0) { $reason = "the elevated run exited $($process.ExitCode)" }
    } catch {
        $reason = $_.Exception.Message
    }

    $existing = Read-RecordFile $path
    if ($existing -and $existing.run_id -eq $RunId -and $existing.final -eq $true) {
        Write-Summary $existing $path
        return [pscustomobject]@{ ok = [bool]$existing.ok; path = $path; record = $existing }
    }
    if (-not $reason) { $reason = 'the elevated run ended without a final record' }
    if ($existing -and $existing.run_id -eq $RunId) {
        foreach ($step in @($existing.steps)) { Add-Step $ctx $step.step $step.status ([string]$step.detail) }
        if ($existing.port) { $ctx.Port = $existing.port }
        if ($existing.host_key) { $ctx.HostKey = $existing.host_key }
        $ctx.Addresses = @($existing.addresses)
        if ($existing.rustdesk_id) { $ctx.RustDeskId = [string]$existing.rustdesk_id }
    }
    $steps = @(Get-SetupSteps)
    if ($ctx.Steps.Count -eq 0) {
        Add-Step $ctx 'elevate' 'failed' "elevation cancelled or failed: $reason"
        foreach ($step in ($steps | Where-Object { $_.Needs -contains 'elevate' })) { Add-Step $ctx $step.Id 'skipped' 'needs elevate' }
    } else {
        $last = $ctx.Steps[$ctx.Steps.Count - 1].step
        $at = [array]::IndexOf(@($steps | ForEach-Object Id), $last)
        if ($at -ge 0 -and $at + 1 -lt $steps.Count) {
            Add-Step $ctx $steps[$at + 1].Id 'failed' "the elevated run ended before this step finished: $reason"
        } elseif (-not (@($ctx.Steps | Where-Object { $_.status -eq 'failed' }).Count)) {
            # The child checkpointed every step and died before its final record. The hub accepts
            # one entry per step, so mark the existing elevate entry failed instead of adding one.
            $elevate = @($ctx.Steps | Where-Object { $_.step -eq 'elevate' }) | Select-Object -First 1
            if ($elevate) {
                $elevate.status = 'failed'
                $elevate.detail = Format-Detail "the elevated run ended without a final record: $reason"
            } else {
                Add-Step $ctx 'elevate' 'failed' "elevation cancelled or failed: $reason"
            }
        }
    }
    Complete-Record $ctx $path
    $record = New-Record $ctx $true
    Write-Summary $record $path
    return [pscustomobject]@{ ok = [bool]$record.ok; path = $path; record = $record }
}

if ($LibraryOnly) { return }

$ErrorActionPreference = 'Stop'
$result = Start-Setup -Usb $PSScriptRoot -RunId $RunId -ForUser $ForUser -ComputerName $env:COMPUTERNAME -Self $PSCommandPath
exit $(if ($result.ok) { 0 } else { 1 })
