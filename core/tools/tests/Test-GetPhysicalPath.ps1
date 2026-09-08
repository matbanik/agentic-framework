# Regression test for Invoke-CodexDispatch.ps1's Get-PhysicalPath.
#
# Why this exists
# ---------------
# On macOS, /tmp and /etc are reparse points whose targets are RELATIVE ('private/tmp',
# 'private/etc'). Get-PhysicalPath resolved the link's parent with `Split-Path -Parent`,
# which returns the EMPTY STRING for a first-level path like '/tmp' -- not '/'. Join-Path
# then threw a parameter-binding error, and the wrapper misreported the failure as
# something unrelated ("PromptFile does not exist") for a file that was plainly there.
# Any adopter whose receipts directory sits under /tmp had every .ps1 dispatch resolve
# its own output directory wrongly.
#
# The second arm covers the fail-closed rule (verification-principles V31): a non-empty
# target that resolves to '' must throw, never return a truncated path. A truncated path
# would silently pass downstream containment checks against something that is not the
# target -- a sandbox check succeeding for the wrong reason.
#
# Run:  pwsh -NoProfile -File tools/tests/Test-GetPhysicalPath.ps1
# Exit: 0 all measured arms passed; N = number of failures; 9 = harness could not run.
#
# Portability note: the packaged wrapper is cross-platform, so this test must be too.
# The macOS /tmp cases cannot run on Windows and the symlink cases need privileges that
# a stock Windows shell lacks. Unmeasurable arms are SKIPPED AND REPORTED, never silently
# passed -- an arm that did not run is not evidence, and a summary that hid the skip would
# report an unmeasured guard as measured (V5).
#
# The function is extracted rather than dot-sourced because Invoke-CodexDispatch.ps1 is a
# parameterised script that would execute a real dispatch on load.

param(
    [string]$ScriptPath = (Join-Path (Split-Path -Parent (Split-Path -Parent $PSCommandPath)) 'Invoke-CodexDispatch.ps1')
)

if (-not (Test-Path -LiteralPath $ScriptPath)) {
    Write-Output "HARNESS-FAIL: script not found at $ScriptPath"
    exit 9
}

$lines = Get-Content -LiteralPath $ScriptPath
$start = ($lines | Select-String -Pattern '^function Get-PhysicalPath \{' | Select-Object -First 1).LineNumber
if (-not $start) {
    Write-Output "HARNESS-FAIL: 'function Get-PhysicalPath {' not found in $ScriptPath"
    exit 9
}
$body = @()
for ($i = $start - 1; $i -lt $lines.Count; $i++) {
    $body += $lines[$i]
    if ($i -gt $start - 1 -and $lines[$i] -eq '}') { break }
}
Invoke-Expression ($body -join "`n")

$fail = 0
$arms = 0
$skips = @()

function Test-Case {
    param([string]$Label, [string]$In, [string]$Want)
    $script:arms++
    $got = $null; $err = $null
    try { $got = Get-PhysicalPath $In } catch { $err = $_.Exception.Message }
    if ($err) {
        Write-Output ("FAIL {0,-22} {1} threw: {2}" -f $Label, $In, $err); $script:fail++; return
    }
    if ($got -eq $Want) {
        Write-Output ("PASS {0,-22} {1} -> {2}" -f $Label, $In, $got)
    } else {
        Write-Output ("FAIL {0,-22} {1} -> '{2}'  want '{3}'" -f $Label, $In, $got, $Want); $script:fail++
    }
}

# ---------------------------------------------------------------------------
# Arm 1 -- STATIC. Runs everywhere, needs no privileges and no reparse points.
# Weaker than a behavioral arm (it reads the source, it does not observe the
# operation -- V2), so it is labelled static and never stands in for arm 2.
# It exists so a Windows adopter without symlink rights still fails loudly if
# someone deletes the guard.
# ---------------------------------------------------------------------------
$arms++
$src = ($body -join "`n")
$hasEmptyParentGuard = $src -match 'IsNullOrWhiteSpace\(\$linkParent\)'
$hasFailClosedGuard  = $src -match 'IsNullOrWhiteSpace\(\$resolved\)'
if ($hasEmptyParentGuard -and $hasFailClosedGuard) {
    Write-Output "PASS static-guards-present  empty-parent + fail-closed guards found in source"
} else {
    Write-Output ("FAIL static-guards-present  empty-parent={0} fail-closed={1}" -f `
        $hasEmptyParentGuard, $hasFailClosedGuard)
    $fail++
}

# ---------------------------------------------------------------------------
# Arm 2 -- BEHAVIORAL, macOS only. The original defect, on the host that has it.
# ---------------------------------------------------------------------------
if ($IsMacOS) {
    Test-Case 'macos-depth1'   '/tmp'       '/private/tmp'
    Test-Case 'macos-depth2'   '/tmp/x'     '/private/tmp/x'
    Test-Case 'macos-2nd-inst' '/etc'       '/private/etc'
    Test-Case 'macos-control'  '/usr/local' '/usr/local'
} else {
    $skips += 'macos-relative-reparse (needs macOS: /tmp -> private/tmp)'
    Write-Output "SKIP macos-relative-reparse  not macOS; the original defect cannot be reproduced here"
}

# ---------------------------------------------------------------------------
# Arm 3 -- BEHAVIORAL, any OS that grants symlink creation. A relative-target
# link the test builds itself, so the relative branch is exercised off macOS.
# ---------------------------------------------------------------------------
$tmpRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("gpp-" + [System.Guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $tmpRoot -Force | Out-Null
try {
    $realDir = Join-Path $tmpRoot 'real'
    New-Item -ItemType Directory -Path $realDir -Force | Out-Null
    $linkPath = Join-Path $tmpRoot 'link'
    # -Target 'real' (not the absolute path) is what makes this a RELATIVE target.
    New-Item -ItemType SymbolicLink -Path $linkPath -Target 'real' -ErrorAction Stop | Out-Null

    $arms++
    $wantReal = (Get-PhysicalPath $realDir)
    $got = $null; $err = $null
    try { $got = Get-PhysicalPath $linkPath } catch { $err = $_.Exception.Message }
    if ($err) {
        Write-Output "FAIL relative-target        threw: $err"; $fail++
    } elseif ($got -eq $wantReal) {
        Write-Output "PASS relative-target        relative symlink target resolved to '$got'"
    } else {
        Write-Output "FAIL relative-target        got '$got'  want '$wantReal'"; $fail++
    }
} catch {
    $skips += 'relative-target (symlink creation denied)'
    Write-Output "SKIP relative-target        could not create a symlink: $($_.Exception.Message)"
}

# ---------------------------------------------------------------------------
# Arm 4 -- BEHAVIORAL negative (V31). An empty/circular resolution must throw.
# This is the arm that proves the gate CAN fail, so a skip here matters most.
# ---------------------------------------------------------------------------
try {
    $a = Join-Path $tmpRoot 'loop'
    New-Item -ItemType SymbolicLink -Path $a -Target $a -ErrorAction Stop | Out-Null
    $arms++
    $threw = $false
    try { Get-PhysicalPath $a | Out-Null } catch { $threw = $true }
    if ($threw) {
        Write-Output "PASS fail-closed            circular reparse point threw rather than resolving"
    } else {
        Write-Output "FAIL fail-closed            circular reparse point did NOT throw"; $fail++
    }
} catch {
    $skips += 'fail-closed (circular symlink creation denied)'
    Write-Output "SKIP fail-closed            could not create a circular symlink: $($_.Exception.Message)"
} finally {
    Remove-Item -LiteralPath $tmpRoot -Recurse -Force -ErrorAction SilentlyContinue
}

# The RESULT line is what a preflight check greps, so it names every arm and every skip.
$note = if ($skips.Count -gt 0) { ", $($skips.Count) skipped (NOT measured): $($skips -join '; ')" } else { "" }
Write-Output "RESULT: $arms measured arm(s), $fail failure(s)$note"
exit $fail
