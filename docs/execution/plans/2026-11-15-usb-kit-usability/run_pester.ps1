<#
.SYNOPSIS
    Pester gate for this plan: passes only a run in which everything passed.

.DESCRIPTION
    FailedCount alone misses a failure outside a test. A container that fails discovery gives
    Result=Failed, FailedContainersCount=1 and FailedCount=0 (plan review round 3, F-008), and a
    failed AfterAll block gives Result=Failed with FailedCount=0 and FailedContainersCount=0
    (round 4, F-008). This gate passes only when Result is Passed, at least one test passed, and
    no test, block or container failed. No failure is excused: row 0 requires the unchanged
    tree to pass this same gate. Pester skips a path that does not exist and still
    passes the rest (round 5, F-013), so every requested path must exist and yield at least one
    discovered test file.

    Before the real run, the gate proves that it can fail. On temporary probe files it must pass
    a passing file and refuse an assertion failure, a discovery failure beside a passing file, a
    BeforeAll failure, an AfterAll failure after a passing test, a file with no test, a missing
    file beside a passing file, and a directory with no test file beside a passing file.

.EXAMPLE
    pwsh -NoProfile -File run_pester.ps1 C:/Temp/agentic-framework/rl-stage/tools/tests
#>
param(
    [Parameter(Mandatory, Position = 0, ValueFromRemainingArguments)]
    [string[]]$Path
)
$ErrorActionPreference = 'Stop'
Import-Module Pester -MinimumVersion 5.0

function Test-Gate([object]$Run) {
    $null -ne $Run -and $Run.Result -eq 'Passed' -and $Run.PassedCount -ge 1 -and
        $Run.FailedCount -eq 0 -and $Run.FailedBlocksCount -eq 0 -and $Run.FailedContainersCount -eq 0
}

function Get-UncoveredPath([string[]]$Paths, [object]$Run) {
    # A requested path counts only if it exists and a discovered test file is it or lies under it.
    $found = @($Run.Containers | ForEach-Object { [IO.Path]::GetFullPath([string]$_.Item) })
    foreach ($p in $Paths) {
        if (-not (Test-Path -LiteralPath $p)) { $p; continue }
        $full = [IO.Path]::GetFullPath((Resolve-Path -LiteralPath $p).ProviderPath).TrimEnd('\', '/')
        # Windows paths compare without case: Pester can report C:\temp for a requested C:\Temp.
        $hit = $found | Where-Object {
            $_ -eq $full -or $_.StartsWith($full + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)
        }
        if (-not $hit) { $p }
    }
}

function Invoke-Run([string[]]$Paths, [string]$Verbosity) {
    $cfg = New-PesterConfiguration
    $cfg.Run.Path = $Paths
    $cfg.Run.PassThru = $true
    $cfg.Output.Verbosity = $Verbosity
    Invoke-Pester -Configuration $cfg
}

function Test-Paths([string[]]$Paths) {
    $run = Invoke-Run $Paths 'None'
    (Test-Gate $run) -and @(Get-UncoveredPath $Paths $run).Count -eq 0
}

$probe = Join-Path ([IO.Path]::GetTempPath()) "rl-pester-probe-$PID"
New-Item -ItemType Directory -Path $probe -Force | Out-Null
try {
    $files = @{
        Pass      = "Describe 'p' { It 'passes' { 1 | Should -Be 1 } }"
        Fail      = "Describe 'f' { It 'fails' { 1 | Should -Be 2 } }"
        Broken    = "throw 'discovery failure'`nDescribe 'b' { It 'never runs' { 1 | Should -Be 1 } }"
        BeforeAll = "Describe 'ba' { BeforeAll { throw 'setup failure' }; It 'never runs' { 1 | Should -Be 1 } }"
        AfterAll  = "Describe 'aa' { It 'passes' { 1 | Should -Be 1 }; AfterAll { throw 'teardown failure' } }"
        Empty     = "Describe 'e' { }"
    }
    $p = @{}
    foreach ($name in $files.Keys) {
        $p[$name] = Join-Path $probe "$name.Tests.ps1"
        Set-Content -LiteralPath $p[$name] -Value $files[$name]
    }
    $bare = Join-Path $probe 'bare'
    New-Item -ItemType Directory -Path $bare -Force | Out-Null
    $okdir = Join-Path $probe 'okdir'
    New-Item -ItemType Directory -Path $okdir -Force | Out-Null
    Copy-Item -LiteralPath $p.Pass -Destination (Join-Path $okdir 'Pass.Tests.ps1')
    $cases = @(
        @{ Name = 'all passing'; Paths = @($p.Pass); Want = $true },
        @{ Name = 'assertion failure'; Paths = @($p.Pass, $p.Fail); Want = $false },
        @{ Name = 'discovery failure beside a passing file'; Paths = @($p.Pass, $p.Broken); Want = $false },
        @{ Name = 'BeforeAll failure beside a passing file'; Paths = @($p.Pass, $p.BeforeAll); Want = $false },
        @{ Name = 'AfterAll failure after a passing test'; Paths = @($p.AfterAll); Want = $false },
        @{ Name = 'no test'; Paths = @($p.Empty); Want = $false },
        @{ Name = 'missing file beside a passing file'; Paths = @($p.Pass, (Join-Path $probe 'Missing.Tests.ps1')); Want = $false },
        @{ Name = 'directory with no test file beside a passing file'; Paths = @($p.Pass, $bare); Want = $false },
        @{ Name = 'passing directory named in other letter case'; Paths = @($probe.ToUpperInvariant() + [IO.Path]::DirectorySeparatorChar + 'okdir'); Want = $true }
    )
    foreach ($case in $cases) {
        $got = Test-Paths $case.Paths
        if ($got -ne $case.Want) {
            Write-Output "SELF-CHECK FAILED: $($case.Name) gave $got, expected $($case.Want)"
            exit 1
        }
    }
    Write-Output 'self-check: the gate refuses an assertion, discovery, BeforeAll or AfterAll failure, a run with no test, and a requested path with no test file'
}
finally {
    Remove-Item -LiteralPath $probe -Recurse -Force -ErrorAction SilentlyContinue
}

$run = Invoke-Run $Path 'Normal'
$uncovered = @(Get-UncoveredPath $Path $run)
$uncovered | ForEach-Object { Write-Output "requested path has no discovered test file: $_" }
$ok = (Test-Gate $run) -and $uncovered.Count -eq 0
Write-Output ("Pester gate {0}: Result={1} Passed={2} Failed={3} FailedBlocks={4} FailedContainers={5} Skipped={6} Uncovered={7}" -f
    ($(if ($ok) { 'PASS' } else { 'FAIL' })), $run.Result, $run.PassedCount, $run.FailedCount,
    $run.FailedBlocksCount, $run.FailedContainersCount, $run.SkippedCount, $uncovered.Count)
exit $(if ($ok) { 0 } else { 1 })
