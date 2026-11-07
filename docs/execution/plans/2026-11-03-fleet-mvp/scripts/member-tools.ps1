# Installs for this user whatever `check --project` reports missing, then checks again. PROJECT defaults
# to av-kit. It knows uv, node and npm; any other missing tool stops it, for a human to decide.
$ErrorActionPreference = 'Stop'
$FleetHome = "$HOME\.agent\fleet"
if (-not $PROJECT) { $PROJECT = 'av-kit' }
$py = Get-ChildItem "$env:LOCALAPPDATA\Programs\Python\Python3*\python.exe" |
    Sort-Object { [int]($_.Directory.Name -replace '\D') } -Descending | Select-Object -First 1 -ExpandProperty FullName

function Install-Uv {
    $script = Join-Path $env:TEMP 'uv-install.ps1'
    curl.exe -sS -L -f -o $script 'https://astral.sh/uv/install.ps1'
    if ($LASTEXITCODE -ne 0) { throw "fetching the uv installer failed: curl exit $LASTEXITCODE" }
    powershell.exe -NoProfile -ExecutionPolicy Bypass -File $script
    if ($LASTEXITCODE -ne 0) { throw "the uv installer exited $LASTEXITCODE" }
    Remove-Item $script
}

function Install-Node {
    $release = (curl.exe -sS -f 'https://nodejs.org/dist/index.json' | ConvertFrom-Json) | Where-Object { $_.lts } | Select-Object -First 1
    $name = "node-$($release.version)-win-x64"
    $zip = Join-Path $env:TEMP "$name.zip"
    curl.exe -sS -L -f -o $zip "https://nodejs.org/dist/$($release.version)/$name.zip"
    if ($LASTEXITCODE -ne 0) { throw "fetching node failed: curl exit $LASTEXITCODE" }
    $target = "$env:LOCALAPPDATA\Programs"
    Expand-Archive $zip $target -Force
    Remove-Item $zip
    $userPath = [Environment]::GetEnvironmentVariable('Path', 'User')
    [Environment]::SetEnvironmentVariable('Path', "$target\$name;$userPath", 'User')
}

$report = & $py "$FleetHome\fleet.py" check --project $PROJECT | ConvertFrom-Json
if ($LASTEXITCODE -notin 0, 6) { throw "check exited $LASTEXITCODE" }
foreach ($tool in $report.missing) {
    switch ($tool) {
        'uv' { Install-Uv }
        'node' { Install-Node }
        'npm' { if ($report.missing -notcontains 'node') { Install-Node } }
        default { throw "no installer here for $tool" }
    }
}
$env:Path = [Environment]::GetEnvironmentVariable('Path', 'User') + ';' + [Environment]::GetEnvironmentVariable('Path', 'Machine')
& $py "$FleetHome\fleet.py" check --project $PROJECT
exit $LASTEXITCODE
