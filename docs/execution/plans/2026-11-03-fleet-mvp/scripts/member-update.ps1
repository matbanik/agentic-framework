# Fetches the hub's current fleet.py and checks its hash before replacing the old file. The member is
# stopped first and restarted after, with member-task.ps1.
$ErrorActionPreference = 'Stop'
$FleetHome = "$HOME\.agent\fleet"
$new = "$FleetHome\fleet.py.new"
curl.exe -k -sS -f -o $new "$HUB_URL/bootstrap/fleet.py"
if ($LASTEXITCODE -ne 0) { throw "fetching fleet.py failed: curl exit $LASTEXITCODE" }
if ((Get-FileHash $new -Algorithm SHA256).Hash.ToLower() -ne $FLEET_SHA) {
    Remove-Item $new
    throw 'hash mismatch on fleet.py'
}
Move-Item -Force $new "$FleetHome\fleet.py"
Write-Output "fleet.py updated to $FLEET_SHA"
