#Requires -Version 7
# Writes an OS installer image (a hybrid ISO such as Ubuntu's) to one USB drive and reads it back to verify.
# Without -Serial it only lists the USB drives. With -Serial it erases that drive, so run it as administrator.
param(
    [Parameter(Mandatory)][string]$Iso,
    [string]$Serial,
    [switch]$VerifyOnly,  # skip the erase and write; only compare the drive with the image
    [string]$Log = (Join-Path (Split-Path $Iso) 'write-installer-usb.log')
)
$ErrorActionPreference = 'Stop'

if (-not $Serial) {
    Get-Disk | Where-Object BusType -eq 'USB' |
        Format-Table Number, FriendlyName, SerialNumber, @{ n = 'GB'; e = { [math]::Round($_.Size / 1GB, 1) } }, PartitionStyle -AutoSize
    return
}
$admin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $admin) { throw 'Run this as administrator. Nothing was changed.' }

Start-Transcript -Path $Log -Force | Out-Null
try {
    $disk = @(Get-Disk | Where-Object { $_.SerialNumber -eq $Serial -and $_.BusType -eq 'USB' })
    if ($disk.Count -ne 1) { throw "No single USB disk with serial $Serial. Nothing was changed." }
    $disk = $disk[0]
    $n = $disk.Number
    Write-Host ("Target: disk {0}, {1}, {2:N1} GB" -f $n, $disk.FriendlyName.Trim(), ($disk.Size / 1GB))

    # The image must be listed in the SHA256SUMS file beside it, the one whose signature you checked.
    $sums = Join-Path (Split-Path $Iso) 'SHA256SUMS'
    $name = Split-Path $Iso -Leaf
    $expected = ((Get-Content $sums | Where-Object { $_ -like "* *$name" }) -split ' ')[0]
    if (-not $expected) { throw "$name is not listed in $sums. Nothing was changed." }
    $size = (Get-Item $Iso).Length
    if ($size -gt $disk.Size) { throw 'The image is larger than the drive. Nothing was changed.' }
    Write-Host 'Checking the image checksum...'
    if ((Get-FileHash $Iso -Algorithm SHA256).Hash.ToLower() -ne $expected) {
        throw 'The image checksum does not match SHA256SUMS. Nothing was changed.'
    }

    $buf = [byte[]]::new(4MB)
    if (-not $VerifyOnly) {
        Write-Host "Erasing disk $n..."
        if ($disk.PartitionStyle -ne 'RAW') { Clear-Disk -Number $n -RemoveData -RemoveOEM -Confirm:$false }
        Update-HostStorageCache

        $src = [IO.File]::OpenRead($Iso)
        $dst = [IO.FileStream]::new("\\.\PhysicalDrive$n", [IO.FileMode]::Open, [IO.FileAccess]::ReadWrite,
            [IO.FileShare]::ReadWrite, 4MB, [IO.FileOptions]::WriteThrough)
        # The partition table goes on last, so Windows can't find and mount it while the rest is being written.
        $head = [byte[]]::new(4MB)
        $headLen = $src.Read($head, 0, $head.Length)
        [void]$dst.Seek($headLen, [IO.SeekOrigin]::Begin)
        $done = [long]$headLen
        try {
            while (($r = $src.Read($buf, 0, $buf.Length)) -gt 0) {
                $len = [int]([math]::Ceiling($r / 512) * 512)  # raw disk writes must be whole sectors
                if ($len -gt $r) { [Array]::Clear($buf, $r, $len - $r) }
                $dst.Write($buf, 0, $len)
                $done += $r
                Write-Progress -Activity 'Writing the installer to the USB drive' -PercentComplete ($done * 100 / $size) `
                    -Status ("{0:N2} of {1:N2} GB" -f ($done / 1GB), ($size / 1GB))
            }
            [void]$dst.Seek(0, [IO.SeekOrigin]::Begin)
            $dst.Write($head, 0, $headLen)
            $dst.Flush($true)
        } finally { $src.Close(); $dst.Close() }
        Write-Progress -Activity 'Writing the installer to the USB drive' -Completed
    }

    Write-Host 'Reading the drive back to verify...'
    $sha = [Security.Cryptography.SHA256]::Create()
    $rd = [IO.FileStream]::new("\\.\PhysicalDrive$n", [IO.FileMode]::Open, [IO.FileAccess]::Read,
        [IO.FileShare]::ReadWrite, 4MB, [IO.FileOptions]::None)
    $left = [long]$size
    try {
        while ($left -gt 0) {
            $r = $rd.Read($buf, 0, $buf.Length)
            if ($r -le 0) { throw 'The drive ended before the image did.' }
            $use = [int][math]::Min([long]$r, $left)
            [void]$sha.TransformBlock($buf, 0, $use, $null, 0)
            $left -= $use
        }
        [void]$sha.TransformFinalBlock([byte[]]::new(0), 0, 0)
    } finally { $rd.Close() }
    $got = -join ($sha.Hash | ForEach-Object { $_.ToString('x2') })
    Update-HostStorageCache
    if ($got -ne $expected) { throw "The drive reads back $got, not the image's checksum." }
    Write-Host 'The drive matches the image. If Windows offers to format it, click Cancel.'
    'RESULT=OK'
} catch {
    "RESULT=FAILED $($_.Exception.Message)"
} finally {
    Stop-Transcript | Out-Null
}
