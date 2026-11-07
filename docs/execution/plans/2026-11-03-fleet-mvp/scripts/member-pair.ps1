# Fetches the fleet files from the hub, checks their hashes, runs pair as MEMBER, and prints only the approval code.
$ErrorActionPreference = 'Stop'
$FleetHome = "$HOME\.agent\fleet"
New-Item -ItemType Directory -Force $FleetHome | Out-Null

foreach ($file in @(@('fleet.py', $FLEET_SHA), @('bootstrap.md', $BOOT_SHA))) {
    $target = Join-Path $FleetHome $file[0]
    curl.exe -k -sS -f -o $target "$HUB_URL/bootstrap/$($file[0])"
    if ($LASTEXITCODE -ne 0) { throw "fetching $($file[0]) failed: curl exit $LASTEXITCODE" }
    if ((Get-FileHash $target -Algorithm SHA256).Hash.ToLower() -ne $file[1]) {
        Remove-Item $target
        throw "hash mismatch on $($file[0])"
    }
}

$py = Get-ChildItem "$env:LOCALAPPDATA\Programs\Python\Python3*\python.exe" |
    Sort-Object { [int]($_.Directory.Name -replace '\D') } -Descending | Select-Object -First 1 -ExpandProperty FullName
$out = & $py "$FleetHome\fleet.py" pair --hub $HUB_URL --pin $PIN --name $MEMBER
if ($LASTEXITCODE -ne 0) { throw "pair exited $LASTEXITCODE" }
'APPROVAL-CODE ' + ($out | ConvertFrom-Json).code
