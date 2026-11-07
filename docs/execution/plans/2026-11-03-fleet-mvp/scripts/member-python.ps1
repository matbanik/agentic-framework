# Installs Python for this user from python.org if 3.11 or later is absent. No elevation.
$ErrorActionPreference = 'Stop'
$Version = '3.14.7'

function Find-Python {
    Get-ChildItem "$env:LOCALAPPDATA\Programs\Python\Python3*\python.exe" -ErrorAction SilentlyContinue |
        Sort-Object { [int]($_.Directory.Name -replace '\D') } -Descending | Select-Object -First 1 -ExpandProperty FullName
}

$py = Find-Python
if ($py) {
    & $py -c "import sys; sys.exit(sys.version_info < (3, 11))"
    if ($LASTEXITCODE -eq 0) {
        Write-Output "already installed: $(& $py --version) at $py"
        exit 0
    }
}

$installer = Join-Path $env:TEMP "python-$Version-amd64.exe"
curl.exe -sS -L -f -o $installer "https://www.python.org/ftp/python/$Version/python-$Version-amd64.exe"
if ($LASTEXITCODE -ne 0) { throw "download failed: curl exit $LASTEXITCODE" }
$signature = Get-AuthenticodeSignature $installer
if ($signature.Status -ne 'Valid' -or $signature.SignerCertificate.Subject -notlike '*Python Software Foundation*') {
    Remove-Item $installer
    throw "the installer's signature is not valid: $($signature.Status)"
}
$process = Start-Process $installer -ArgumentList 'InstallAllUsers=0', 'PrependPath=1', 'Include_test=0', '/quiet' -Wait -PassThru
Remove-Item $installer
if ($process.ExitCode -ne 0) { throw "the installer exited $($process.ExitCode)" }
$py = Find-Python
if (-not $py) { throw 'python.exe not found after the install' }
Write-Output "installed: $(& $py --version) at $py"
