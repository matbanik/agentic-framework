# Creates the Fleet hub's inbound rule on the hub machine, for the LAN subnet in -RemoteAddress (CIDR, such
# as 192.0.2.0/24). Needs elevation: start it with elevate-firewall.ps1. -Remove reverses it.
param([switch]$Remove, [string]$RemoteAddress)
$ErrorActionPreference = 'Stop'
$Name = 'Fleet hub 8770'

$identity = [Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
if (-not $identity.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Output 'This needs elevation: start it with elevate-firewall.ps1.'
    exit 3
}

if ($Remove) {
    Remove-NetFirewallRule -DisplayName $Name
    Write-Output "Removed $Name"
    exit 0
}
if (Get-NetFirewallRule -DisplayName $Name -ErrorAction SilentlyContinue) {
    Write-Output "$Name already exists; nothing changed"
    exit 0
}
if (-not $RemoteAddress) {
    Write-Output 'Name the LAN subnet: -RemoteAddress <CIDR>.'
    exit 2
}
New-NetFirewallRule -DisplayName 'Fleet hub 8770' -Direction Inbound -Action Allow -Protocol TCP -LocalPort 8770 -RemoteAddress $RemoteAddress -Profile Private | Out-Null
Write-Output "Created $Name"
