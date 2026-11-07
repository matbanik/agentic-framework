# Read-only. Prints the member's log collector service (COLLECTOR names it) and firewall state, and what a
# keyless request to the hub gets.
$ErrorActionPreference = 'Stop'
$collector = Get-Service $COLLECTOR
$record = @{
    collector = [string]$collector.Status
    collector_start = [string]$collector.StartType
    profiles = @(Get-NetFirewallProfile | Sort-Object Name | ForEach-Object { "$($_.Name)=$($_.Enabled)" })
    inbound = @(Get-NetFirewallRule -Direction Inbound).Count
    probe = [string](curl.exe -k -s -o NUL -w '%{http_code}' --max-time 10 "$HUB_URL/v1/members")
}
'MEMBER-RECORD ' + ($record | ConvertTo-Json -Compress)
