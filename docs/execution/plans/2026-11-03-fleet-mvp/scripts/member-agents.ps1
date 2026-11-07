# Installs the Claude Code and Codex CLIs for this user with each vendor's official installer. No
# elevation, no sign-in and no credentials. Prints versions and where each one landed. Quick experiment.
$ErrorActionPreference = 'Continue'
$log = "$env:TEMP\agent-cli-install.log"
Remove-Item $log -ErrorAction SilentlyContinue

function Install-Cli($name, $url) {
    Write-Output "--- installing $name from $url"
    $script = Join-Path $env:TEMP "$name-install.ps1"
    curl.exe -sS -L -f -o $script $url
    if ($LASTEXITCODE -ne 0) { Write-Output "$name download failed: curl exit $LASTEXITCODE"; return }
    powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $script *>> $log
    Write-Output "$name installer exit $LASTEXITCODE"
    Remove-Item $script -ErrorAction SilentlyContinue
}

Install-Cli 'claude' 'https://claude.ai/install.ps1'
Install-Cli 'codex' 'https://chatgpt.com/codex/install.ps1'

$env:Path = [Environment]::GetEnvironmentVariable('Path', 'User') + ';' + [Environment]::GetEnvironmentVariable('Path', 'Machine')
foreach ($cli in 'claude', 'codex') {
    $found = Get-Command $cli -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($found) {
        Write-Output "$cli at $($found.Source): $(& $found.Source --version 2>&1 | Select-Object -First 1)"
    } else {
        Write-Output "$cli NOT FOUND on PATH"
    }
}
Write-Output '--- last lines of the installer log'
Get-Content $log -Tail 12 -ErrorAction SilentlyContinue
