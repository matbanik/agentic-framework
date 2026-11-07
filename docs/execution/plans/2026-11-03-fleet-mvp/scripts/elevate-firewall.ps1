# Runs hub-firewall.ps1 in its own elevated window, so the human accepts one UAC prompt and the IDE stays as
# it is. -Remove passes through, and so does -RemoteAddress, which defaults to FLEET_LAN. Declining the
# prompt ends this with an error and changes nothing.
param([switch]$Remove, [string]$RemoteAddress = $env:FLEET_LAN)
$ErrorActionPreference = 'Stop'
$script = Join-Path $PSScriptRoot 'hub-firewall.ps1'
$log = Join-Path $env:RECEIPTS_DIR 'fleet-firewall-script.txt'
$flag = if ($Remove) { ' -Remove' } elseif ($RemoteAddress) { " -RemoteAddress '$RemoteAddress'" } else { '' }
$inner = "& '$script'$flag *> '$log'; exit `$LASTEXITCODE"
$process = Start-Process powershell.exe -Verb RunAs -Wait -PassThru -ArgumentList '-NoProfile', '-Command', "`"$inner`""
Get-Content $log
exit $process.ExitCode
