<#
.SYNOPSIS
  Validation test suite for the CLI Dispatch skill.
  Tests dispatch routes plus a deterministic Invoke-CodexDispatch.ps1 contract suite
  (wrapper-contract) that does not require a live Codex session.

.DESCRIPTION
  Each test dispatches a minimal task to the target CLI agent, captures the output,
  and validates that the expected result was produced. Tests are independent and
  can be run individually or as a full suite.

.NOTES
  Prerequisites:
  - codex CLI in PATH (npm global)
  - claude CLI in PATH (npm global)
  - agy CLI at $env:LOCALAPPDATA\agy\bin\agy.exe (version ≥ 1.1.1; stdout capture verified on 1.1.5)
  - All CLIs authenticated
  - agy model set to the `surface_orchestrator` binding for `gemini-cli` via TUI
    /model (or --model); resolve it with
    `Resolve-AgentModel -Class surface_orchestrator -Harness gemini-cli`
  - Stuck/broken MCP servers disabled — they block agy -p even for trivial prompts
#>

param(
    [ValidateSet('all', 'wrapper-contract', 'codex-validation', 'codex-image', 'agy-data', 'claude-writing')]
    [string]$Test = 'all',
    # No baked default on purpose. This used to default to the literal string
    # '{{RECEIPTS_DIR}}\dispatch-tests', which is only a path AFTER instantiate.py
    # substitutes it. Run in the packaged tree it created a real directory named
    # `{{RECEIPTS_DIR}}` inside core/ and wrote live CLI receipts into it -- and
    # those receipts carry raw model slugs, so the debris then failed the Tier-1
    # model-slug release gate. A test run must not be able to poison a release
    # check. Resolution order is -OutputDir, then $env:RECEIPTS_DIR; if neither is
    # usable, Get-OutputDir fails closed instead of inventing a location (V31,
    # ADOPTION-QUESTIONS.md F3).
    [string]$OutputDir,
    [switch]$Verbose
)

$ErrorActionPreference = 'Continue'
$script:PassCount = 0
$script:FailCount = 0
$script:SkipCount = 0
$script:Results = @()

# Model ids come from the live registry home (see .agent/INSTANTIATE.md), not
# from this script. A snapshot bump is one edit there; a test that named its
# own model would keep dispatching to a retired one and report the failure as
# a CLI defect.
$script:RegistryModule = $null
foreach ($candidate in @(
        $(if ($env:AGENT_MODEL_REGISTRY) {
            $override = $env:AGENT_MODEL_REGISTRY
            if ((Test-Path -LiteralPath $override) -and (Get-Item -LiteralPath $override).PSIsContainer) {
                Join-Path $override 'tools/ModelRegistry.psm1'
            } else {
                Join-Path (Split-Path -Parent $override) 'tools/ModelRegistry.psm1'
            }
        }),
        # Shared home from env, never a baked drive letter: a literal like
        # 'P:/.agent' is one machine's layout (see .agent/INSTANTIATE.md S2).
        $(if ($env:AGENT_MODEL_REGISTRY_HOME) {
            Join-Path $env:AGENT_MODEL_REGISTRY_HOME 'tools/ModelRegistry.psm1'
        }),
        $(if ($env:USERPROFILE) { Join-Path $env:USERPROFILE '.agent/tools/ModelRegistry.psm1' })
    )) {
    if ($candidate -and (Test-Path -LiteralPath $candidate)) {
        $script:RegistryModule = (Resolve-Path -LiteralPath $candidate).Path
        break
    }
}
if (-not $script:RegistryModule) {
    throw "registry_not_found: no ModelRegistry.psm1 at any S2 location"
}
Import-Module $script:RegistryModule -Force

function Get-ClassModel {
    param(
        [Parameter(Mandatory)][string]$Class,
        [Parameter(Mandatory)][string]$Harness
    )
    $resolved = Resolve-AgentModel -Class $Class -Harness $Harness
    if (-not $resolved -or -not $resolved.Slug) {
        throw "model registry could not resolve $Class on $Harness"
    }
    return $resolved.Slug
}

# --- Helpers ---

function Write-TestHeader($name) {
    Write-Host "`n$('=' * 60)" -ForegroundColor Cyan
    Write-Host "  TEST: $name" -ForegroundColor Cyan
    Write-Host "$('=' * 60)" -ForegroundColor Cyan
}

function Write-TestResult($name, $passed, $message, $duration) {
    $status = if ($passed) { "PASS" } else { "FAIL" }
    $color = if ($passed) { "Green" } else { "Red" }
    Write-Host "  [$status] $name ($([math]::Round($duration, 1))s) - $message" -ForegroundColor $color

    if ($passed) { $script:PassCount++ } else { $script:FailCount++ }
    $script:Results += [PSCustomObject]@{
        Test = $name
        Status = $status
        Message = $message
        Duration = [math]::Round($duration, 1)
    }
}

function Write-TestSkip($name, $reason) {
    Write-Host "  [SKIP] $name - $reason" -ForegroundColor Yellow
    $script:SkipCount++
    $script:Results += [PSCustomObject]@{
        Test = $name
        Status = "SKIP"
        Message = $reason
        Duration = 0
    }
}

function Ensure-Dir($path) {
    New-Item -ItemType Directory -Force -Path $path | Out-Null
}

function Clean-File($path) {
    if (Test-Path $path) { Remove-Item $path -Force }
}

# Resolved lazily, and only by the arms that actually write receipts.
# `wrapper-contract` writes nothing here, so it has to stay runnable on a machine
# with no RECEIPTS_DIR at all -- resolving eagerly before the switch is what made
# the old code create the directory unconditionally.
#
# Returns $null on failure and leaves the reason in $script:OutputDirError, rather
# than throwing: a throw here would abort the whole `-Test all` run at the first
# live arm, and the remaining arms would never report. Callers surface it as a
# FAIL, not a SKIP -- an unusable receipts path is a broken harness, and the one
# thing this package will not do is let "the check could not run" read as a pass.
$script:ResolvedOutputDir = $null
$script:OutputDirError = $null
function Get-OutputDir {
    if ($script:ResolvedOutputDir) { return $script:ResolvedOutputDir }

    $candidate = $OutputDir
    if ([string]::IsNullOrWhiteSpace($candidate) -and -not [string]::IsNullOrWhiteSpace($env:RECEIPTS_DIR)) {
        $candidate = Join-Path $env:RECEIPTS_DIR 'dispatch-tests'
    }
    if ([string]::IsNullOrWhiteSpace($candidate)) {
        $script:OutputDirError = "receipts_dir_required: no -OutputDir and no RECEIPTS_DIR. " +
            "Set RECEIPTS_DIR to an absolute directory outside the repo and outside any " +
            "cloud-sync tree (ADOPTION-QUESTIONS.md F3/F3b), or pass -OutputDir."
        return $null
    }
    # An uninstantiated placeholder is a path-shaped string that is not a path.
    # Creating it succeeds, which is exactly why this has to be checked: the
    # failure is silent and lands inside the package tree.
    if ($candidate -match '\{\{') {
        $script:OutputDirError = "uninstantiated_output_dir: '$candidate' still contains a " +
            "{{PLACEHOLDER}}. Creating it would put a literally-named directory in the " +
            "package tree. Run instantiate.py first, or pass a real -OutputDir."
        return $null
    }

    Ensure-Dir $candidate
    $script:ResolvedOutputDir = $candidate
    return $candidate
}

# `Start-Process` has no `-TimeoutSec` parameter. Both live codex arms passed one,
# so PowerShell threw a parameter-binding error before codex was ever spawned and
# each reported `Exception: A parameter cannot be found that matches parameter name
# 'TimeoutSec'` -- a FAIL that read as a codex problem and was in fact a test that
# had never once run (V4). It also means neither arm's assertions have ever been
# exercised; treat their first real green as new information, not a regression fix.
#
# `-Wait` on its own is not the repair either: an unbounded wait on a hung CLI hangs
# the suite instead of failing it, which is how a 5-minute suite becomes an overnight
# one. So start detached and bound the wait explicitly.
function Start-CliWithTimeout {
    param(
        [Parameter(Mandatory)][string]$FilePath,
        [Parameter(Mandatory)][string[]]$ArgumentList,
        [Parameter(Mandatory)][string]$StdOut,
        [Parameter(Mandatory)][string]$StdErr,
        [int]$TimeoutSec = 300
    )

    $proc = Start-Process -FilePath $FilePath -ArgumentList $ArgumentList `
        -NoNewWindow -PassThru -RedirectStandardInput "NUL" `
        -RedirectStandardOutput $StdOut -RedirectStandardError $StdErr

    # WaitForExit(ms) rather than Wait-Process: it returns a bool instead of writing
    # an error record on expiry, and once it returns $true the ExitCode below is
    # guaranteed populated.
    if (-not $proc.WaitForExit($TimeoutSec * 1000)) {
        # Kill the tree, not just the parent. codex spawns children that inherit the
        # redirected handles, and a survivor keeps the log files locked -- the next
        # arm then fails inside Clean-File for a reason that looks nothing like a
        # timeout.
        & taskkill /PID $proc.Id /T /F 2>&1 | Out-Null
        return [pscustomobject]@{ TimedOut = $true; ExitCode = $null }
    }
    return [pscustomobject]@{ TimedOut = $false; ExitCode = $proc.ExitCode }
}

# --- Test 0: Invoke-CodexDispatch.ps1 contract (no live Codex required) ---

function Resolve-WrapperPath {
    param([string]$Name = 'Invoke-CodexDispatch.ps1')
    $here = $PSScriptRoot
    $candidates = @(
        (Join-Path $here "..\..\..\..\tools\$Name"),
        (Join-Path (Get-Location) "tools\$Name"),
        (Join-Path (Get-Location) "core\tools\$Name")
    )
    foreach ($c in $candidates) {
        $resolved = [IO.Path]::GetFullPath($c)
        if (Test-Path -LiteralPath $resolved) { return $resolved }
    }
    return $null
}

function Test-CodexWrapperContract {
    Write-TestHeader "Invoke-CodexDispatch.ps1 — contract smoke (no live Codex)"

    $sw = [System.Diagnostics.Stopwatch]::StartNew()
    $wrapper = Resolve-WrapperPath
    if (-not $wrapper) {
        $sw.Stop()
        Write-TestResult "Wrapper path resolve" $false "Invoke-CodexDispatch.ps1 not found from test location" $sw.Elapsed.TotalSeconds
        return
    }
    Write-TestResult "Wrapper path resolve" $true $wrapper $sw.Elapsed.TotalSeconds

    $text = Get-Content -LiteralPath $wrapper -Raw

    # The packaged wrapper deliberately contains `$env:{{PROJECT_NAME_UPPER}}_...`, which
    # is NOT valid PowerShell until instantiate.py substitutes it. Parsing the packaged
    # file therefore always failed, and the old code `return`ed on that failure — so
    # every execution arm below was unreachable in the packaged tree while the suite
    # still reported a tidy pass/fail tally. A test that cannot run is not a test (V4).
    #
    # So: substitute the tokens into a temp copy and exercise THAT, which is what an
    # adopter's tree actually looks like post-instantiation. In an already-instantiated
    # tree there are no tokens and the real file is used directly.
    $sw.Restart()
    $testRoot = Join-Path ([IO.Path]::GetTempPath()) ("cli-dispatch-contract-" + [Guid]::NewGuid().ToString('N').Substring(0, 8))
    $testReceipts = Join-Path $testRoot 'receipts'
    $null = New-Item -ItemType Directory -Force -Path $testReceipts
    $script:ContractTempRoot = $testRoot
    # Whatever the wrapper under test will resolve `{{PROJECT_ROOT}}` to. The -OutputSchema
    # arms need it because the wrapper refuses a schema outside its own repository root.
    $script:ContractRepoRoot = $testRoot

    $wasTokenized = $text -match '\{\{'
    if ($wasTokenized) {
        # The temp tree MIRRORS the real layout — wrapper and ledger under tools/,
        # schemas under .agent/schemas/ — because both resolve siblings by relative
        # path: the wrapper looks for $PSScriptRoot/review_ledger.py, and the ledger
        # resolves its schema as <its dir>/../.agent/schemas/. A flat temp dir would
        # break the second one and every gate arm would fail closed at exit 3 for a
        # reason that has nothing to do with the gate.
        $testTools = Join-Path $testRoot 'tools'
        $null = New-Item -ItemType Directory -Force -Path $testTools
        $null = New-Item -ItemType Directory -Force -Path (Join-Path $testRoot '.agent\schemas')

        $runnable = Join-Path $testTools 'Invoke-CodexDispatch.ps1'
        $instantiated = $text.
            Replace('{{RECEIPTS_DIR}}', ($testReceipts -replace '\\', '/')).
            Replace('{{PROJECT_ROOT}}', ($testRoot -replace '\\', '/')).
            Replace('{{PROJECT_NAME_UPPER}}', 'CLIDISPATCHTEST').
            Replace('{{PROJECT_NAME_TITLE}}', 'CliDispatchTest').
            Replace('{{PROJECT_NAME}}', 'clidispatchtest')
        [IO.File]::WriteAllText($runnable, $instantiated, (New-Object System.Text.UTF8Encoding($false)))

        # Every sibling helper the wrapper resolves through $PSScriptRoot, not just the
        # ledger. adapt_output_schema.py and validate_json_schema.py were absent here, so
        # the -OutputSchema arms could only ever exercise the wrapper's "helper missing"
        # branches -- the fail-closed paths -- and never the adaptation itself.
        foreach ($helper in @('review_ledger.py', 'adapt_output_schema.py', 'validate_json_schema.py')) {
            $helperSrc = Join-Path (Split-Path $wrapper -Parent) $helper
            if (Test-Path -LiteralPath $helperSrc) { Copy-Item $helperSrc (Join-Path $testTools $helper) }
        }
        $schemaSrcDir = Join-Path (Split-Path (Split-Path $wrapper -Parent) -Parent) '.agent\schemas'
        if (Test-Path $schemaSrcDir) {
            Copy-Item (Join-Path $schemaSrcDir '*.json') (Join-Path $testRoot '.agent\schemas') -ErrorAction SilentlyContinue
        }
    } else {
        $runnable = $wrapper
        # An already-instantiated tree: the wrapper's own repo root is two levels up from
        # tools/, and it is that root the -OutputSchema arms must stay inside. The temp tree
        # is still where captured artifacts go, so ContractTempRoot is left alone.
        $script:ContractRepoRoot = Split-Path (Split-Path $wrapper -Parent) -Parent
    }

    try {
        $null = [scriptblock]::Create((Get-Content -LiteralPath $runnable -Raw))
        $how = if ($wasTokenized) { 'PARSE-OK (after test-local instantiation)' } else { 'PARSE-OK (tree already instantiated)' }
        Write-TestResult "Wrapper parses as PowerShell" $true $how $sw.Elapsed.TotalSeconds
    } catch {
        Write-TestResult "Wrapper parses as PowerShell" $false "$_" $sw.Elapsed.TotalSeconds
        return
    }

    # RECEIPTS_DIR must be set for review_ledger.py; without it the gate arms would all
    # fail closed at exit 3 and prove nothing about the gate itself.
    $priorReceipts = $env:RECEIPTS_DIR
    $env:RECEIPTS_DIR = $testReceipts

    $sw.Restart()
    # Packaged wrapper MUST keep instantiate tokens; live {{PROJECT_NAME_TITLE}} paths are forbidden.
    $hasPlaceholderTemp = $text -match '\{\{RECEIPTS_DIR\}\}'
    $hasPlaceholderRoot = $text -match '\{\{PROJECT_ROOT\}\}'
    $hasLiveTemp = $text -match '(?i)C:[/\\]Temp[/\\]{{PROJECT_NAME}}'
    $hasLiveRoot = $text -match '(?i)P:[/\\]{{PROJECT_NAME}}'
    $tokenOk = $hasPlaceholderTemp -and $hasPlaceholderRoot -and (-not $hasLiveTemp) -and (-not $hasLiveRoot)
    Write-TestResult "Wrapper tokens (placeholders required, no live paths)" $tokenOk "PH_TEMP=$hasPlaceholderTemp PH_ROOT=$hasPlaceholderRoot LIVE_TEMP=$hasLiveTemp LIVE_ROOT=$hasLiveRoot" $sw.Elapsed.TotalSeconds

    $sw.Restart()
    $out = & pwsh -NoProfile -File $runnable -Mode NotARealMode 2>&1
    $code = $LASTEXITCODE
    # ValidateSet should reject before exec; non-zero or ParameterBinding exception text
    $rejected = ($code -ne 0) -or ("$out" -match 'ValidateSet|Cannot validate|ParameterBinding')
    Write-TestResult "Invalid -Mode rejected" $rejected "exit=$code" $sw.Elapsed.TotalSeconds

    # Both -NonReviewDispatch and -AuthorVendor are REQUIRED here, and the assertion is
    # on the message rather than merely on non-zero. Two *earlier* clauses reject this
    # invocation otherwise — the review-loop gate (loop_id_required) and
    # author_vendor_required — so without them the arm exits 1 without ever reaching the
    # justification check. It passed that way for a long time. That is the V3 failure
    # verbatim: a decoy rejected by an unrelated earlier validation looks exactly like
    # one caught by the rule under test, and only asserting on the message tells them
    # apart. If this arm starts failing, read the message before changing the assertion:
    # it most likely means a new clause moved in front of the one under test.
    $sw.Restart()
    $out2 = & pwsh -NoProfile -File $runnable -NonReviewDispatch -AuthorVendor 'contract-test-vendor' -Mode FullAccess -ReasoningEffort medium -PromptText "noop" 2>&1
    $code2 = $LASTEXITCODE
    $needsJust = ($code2 -ne 0) -and ("$out2" -match 'FullAccessJustification|justification')
    $out2Tail = (("$out2" -split "`r?`n" | Where-Object { $_.Trim() } | Select-Object -Last 1) -replace '\s+', ' ')
    Write-TestResult "FullAccess without justification fails closed" $needsJust "exit=$code2 $($out2Tail.Substring(0, [Math]::Min(70, $out2Tail.Length)))" $sw.Elapsed.TotalSeconds

    # --- review-loop bound (tools/review_ledger.py; V41/V43) ------------------
    # Each arm names the clause it expects, so an arm that trips a different check
    # is a failure rather than a silent pass.
    $sw.Restart()
    $outNoLoop = & pwsh -NoProfile -File $runnable -Mode ReviewReadOnly -PromptText "noop" 2>&1
    $codeNoLoop = $LASTEXITCODE
    $loopRequired = ($codeNoLoop -eq 1) -and ("$outNoLoop" -match 'loop_id_required')
    Write-TestResult "Neither -LoopId nor -NonReviewDispatch fails closed" $loopRequired "exit=$codeNoLoop" $sw.Elapsed.TotalSeconds

    $sw.Restart()
    $outBoth = & pwsh -NoProfile -File $runnable -LoopId 'smoke-loop' -NonReviewDispatch -Mode ReviewReadOnly -PromptText "noop" 2>&1
    $codeBoth = $LASTEXITCODE
    $bothRejected = ($codeBoth -eq 1) -and ("$outBoth" -match 'not both')
    Write-TestResult "-LoopId + -NonReviewDispatch rejected" $bothRejected "exit=$codeBoth" $sw.Elapsed.TotalSeconds

    $sw.Restart()
    $outBadLoop = & pwsh -NoProfile -File $runnable -LoopId 'Not A Loop Id' -Mode ReviewReadOnly -PromptText "noop" 2>&1
    $codeBadLoop = $LASTEXITCODE
    $badLoopRejected = ($codeBadLoop -eq 1) -and ("$outBadLoop" -match 'Invalid LoopId')
    Write-TestResult "Malformed -LoopId rejected" $badLoopRejected "exit=$codeBadLoop" $sw.Elapsed.TotalSeconds

    # An unknown loop must be exit 3 (could not check), never 0. This is the arm that
    # distinguishes a gate from a decoration: if the gate were skipped when the ledger
    # has no such loop, every "review" would sail through unbounded.
    $sw.Restart()
    $outNoLedger = & pwsh -NoProfile -File $runnable -LoopId 'loop-that-does-not-exist' -GateOnly -Mode ReviewReadOnly -PromptText "noop" 2>&1
    $codeNoLedger = $LASTEXITCODE
    $ledgerFailsClosed = ($codeNoLedger -eq 3)
    $noLedgerTail = (("$outNoLedger" -split "`r?`n" | Where-Object { $_.Trim() } | Select-Object -Last 1) -replace '\s+', ' ')
    Write-TestResult "Unknown -LoopId fails closed (exit 3, not 0)" $ledgerFailsClosed "exit=$codeNoLedger $($noLedgerTail.Substring(0, [Math]::Min(80, $noLedgerTail.Length)))" $sw.Elapsed.TotalSeconds

    # The must-PASS half: a gate that refuses every invocation satisfies all four arms
    # above and is completely broken (V3). -GateOnly + -NonReviewDispatch must reach 0.
    $sw.Restart()
    $outGateOk = & pwsh -NoProfile -File $runnable -NonReviewDispatch -GateOnly -Mode ReviewReadOnly -PromptText "noop" 2>&1
    $codeGateOk = $LASTEXITCODE
    $gatePasses = ($codeGateOk -eq 0) -and ("$outGateOk" -match 'bypassed-non-review')
    Write-TestResult "-GateOnly -NonReviewDispatch permitted (gate can pass)" $gatePasses "exit=$codeGateOk" $sw.Elapsed.TotalSeconds

    # --- dispatch kind + the execution-review timeout floor -------------------
    # The kind comes from the mode the ledger recorded at `begin`, so these arms open real
    # loops rather than asserting against a flag. -GateOnly is enough to observe the
    # resolved timeout: the wrapper resolves it before the gate returns precisely so this
    # is checkable without a live Codex (V2 — observe the real entry point).
    $pyForKind = $null
    foreach ($candidate in @('python3', 'python')) {
        $found = Get-Command $candidate -ErrorAction SilentlyContinue
        if ($found) { $pyForKind = $found.Source; break }
    }
    $ledgerForKind = Join-Path (Split-Path $runnable -Parent) 'review_ledger.py'
    if (-not $pyForKind -or -not (Test-Path -LiteralPath $ledgerForKind)) {
        # Not a pass and not a silent skip: name what was missing (V5/V31).
        Write-TestResult "dispatch-kind arms" $false "SKIPPED — python=$pyForKind ledger=$ledgerForKind; this is not a pass" 0
    } else {
        $sw.Restart()
        $execLoop = 'kind-exec-loop'
        $planLoop = 'kind-plan-loop'
        $null = & $pyForKind $ledgerForKind begin --loop-id $execLoop --review-mode execution --producer 'builder-x' 2>&1
        $beganExec = ($LASTEXITCODE -eq 0)
        $null = & $pyForKind $ledgerForKind begin --loop-id $planLoop --review-mode plan --producer 'builder-x' 2>&1
        $beganPlan = ($beganExec -and $LASTEXITCODE -eq 0)
        Write-TestResult "kind fixtures: two loops opened" $beganPlan "exec=$beganExec plan=$($LASTEXITCODE -eq 0)" $sw.Elapsed.TotalSeconds

        # Must-PASS, and the one that proves the floor does something: a `medium`
        # execution review would otherwise inherit 900s.
        $sw.Restart()
        $outFloor = & pwsh -NoProfile -File $runnable -LoopId $execLoop -Kind execution -GateOnly -Mode ReviewReadOnly -ReasoningEffort medium -PromptText "noop" 2>&1
        $codeFloor = $LASTEXITCODE
        $floorOk = ($codeFloor -eq 0) -and ("$outFloor" -match 'raising the derived -TimeoutSec from 900 to the 2700s floor') -and ("$outFloor" -match "dispatch kind 'execution', timeout 2700s")
        Write-TestResult "execution kind raises the timeout floor" $floorOk "exit=$codeFloor" $sw.Elapsed.TotalSeconds

        # The discriminating half: a floor that fired for every kind would satisfy the arm
        # above and quietly quadruple every plan review's timeout.
        $sw.Restart()
        $outPlan = & pwsh -NoProfile -File $runnable -LoopId $planLoop -GateOnly -Mode ReviewReadOnly -ReasoningEffort medium -PromptText "noop" 2>&1
        $codePlan = $LASTEXITCODE
        $planOk = ($codePlan -eq 0) -and ("$outPlan" -match "dispatch kind 'plan', timeout 900s") -and ("$outPlan" -notmatch 'raising the derived')
        Write-TestResult "plan kind keeps the effort default" $planOk "exit=$codePlan" $sw.Elapsed.TotalSeconds

        # -Kind disagreeing with the loop it was pointed at. This is the aimed-at-the-
        # wrong-loop case, which spends the wrong budget, so it must not be corrected
        # silently in either direction.
        $sw.Restart()
        $outMismatch = & pwsh -NoProfile -File $runnable -LoopId $planLoop -Kind execution -GateOnly -Mode ReviewReadOnly -PromptText "noop" 2>&1
        $codeMismatch = $LASTEXITCODE
        $mismatchOk = ($codeMismatch -eq 1) -and ("$outMismatch" -match 'kind_mismatch')
        Write-TestResult "-Kind disagreeing with the ledger rejected" $mismatchOk "exit=$codeMismatch" $sw.Elapsed.TotalSeconds

        $sw.Restart()
        $outNonRev = & pwsh -NoProfile -File $runnable -NonReviewDispatch -Kind execution -GateOnly -Mode ReviewReadOnly -PromptText "noop" 2>&1
        $codeNonRev = $LASTEXITCODE
        $nonRevOk = ($codeNonRev -eq 1) -and ("$outNonRev" -match 'kind_not_applicable')
        Write-TestResult "-Kind with -NonReviewDispatch rejected" $nonRevOk "exit=$codeNonRev" $sw.Elapsed.TotalSeconds

        $sw.Restart()
        $outBadKind = & pwsh -NoProfile -File $runnable -LoopId $execLoop -Kind 'not-a-kind' -GateOnly -Mode ReviewReadOnly -PromptText "noop" 2>&1
        $codeBadKind = $LASTEXITCODE
        $badKindOk = ($codeBadKind -ne 0) -and ("$outBadKind" -match 'ValidateSet|Cannot validate|ParameterBinding')
        Write-TestResult "Invalid -Kind rejected by ValidateSet" $badKindOk "exit=$codeBadKind" $sw.Elapsed.TotalSeconds

        # A ledger too old to print `mode=` must fail closed at 3, not fall back to a
        # guessed kind. Only runnable against the temp copy — overwriting the real
        # tools/review_ledger.py in an instantiated tree is not something a test may do.
        $sw.Restart()
        if (-not $wasTokenized) {
            Write-TestSkip "ledger without mode= fails closed" "tree is already instantiated; this arm would overwrite the real tools/review_ledger.py"
        } else {
            $ledgerBackup = "$ledgerForKind.bak"
            Copy-Item -LiteralPath $ledgerForKind -Destination $ledgerBackup -Force
            try {
                $stub = @'
import sys
print("OK: round 1 permitted (0/6 used, no stop active)")
sys.exit(0)
'@
                [IO.File]::WriteAllText($ledgerForKind, $stub, (New-Object System.Text.UTF8Encoding($false)))
                $outNoMode = & pwsh -NoProfile -File $runnable -LoopId $execLoop -GateOnly -Mode ReviewReadOnly -PromptText "noop" 2>&1
                $codeNoMode = $LASTEXITCODE
                $noModeOk = ($codeNoMode -eq 3) -and ("$outNoMode" -match 'ledger_mode_unavailable')
                Write-TestResult "ledger without mode= fails closed (exit 3)" $noModeOk "exit=$codeNoMode" $sw.Elapsed.TotalSeconds
            } finally {
                Move-Item -LiteralPath $ledgerBackup -Destination $ledgerForKind -Force
            }
        }
    }

    $sw.Restart()
    $schema = Join-Path (Split-Path $wrapper -Parent) '..\.agent\schemas\review-verdict.schema.json'
    if (-not (Test-Path $schema)) {
        $schema = Join-Path (Get-Location) 'core\.agent\schemas\review-verdict.schema.json'
    }
    if (-not (Test-Path $schema)) {
        $schema = Join-Path (Get-Location) '.agent\schemas\review-verdict.schema.json'
    }
    $schemaOk = Test-Path $schema
    Write-TestResult "review-verdict.schema.json resolvable" $schemaOk $(if ($schemaOk) { $schema } else { 'missing' }) $sw.Elapsed.TotalSeconds

    # v2 is what new loops register against, and review_ledger.py refuses a v1 document
    # submitted to a v2 loop — so its absence must be a failure, not a shrug.
    $sw.Restart()
    $schema2 = $null
    foreach ($candidate in @(
        (Join-Path (Split-Path $wrapper -Parent) '..\.agent\schemas\review-verdict.schema.v2.json'),
        (Join-Path (Get-Location) 'core\.agent\schemas\review-verdict.schema.v2.json'),
        (Join-Path (Get-Location) '.agent\schemas\review-verdict.schema.v2.json')
    )) {
        if (Test-Path $candidate) { $schema2 = $candidate; break }
    }
    $schema2Ok = [bool]$schema2
    Write-TestResult "review-verdict.schema.v2.json resolvable" $schema2Ok $(if ($schema2Ok) { $schema2 } else { 'missing' }) $sw.Elapsed.TotalSeconds

    # review_ledger.py must be present AND its own stops must be demonstrably able to
    # fire. Shelling out to its selftest rather than re-asserting the rules here keeps
    # one definition of the stops (V42) and makes this arm fail if the ledger regresses.
    $sw.Restart()
    $ledgerScript = Join-Path (Split-Path $wrapper -Parent) 'review_ledger.py'
    if (-not (Test-Path $ledgerScript)) {
        Write-TestResult "review_ledger.py present" $false 'missing' $sw.Elapsed.TotalSeconds
    } else {
        $py = $null
        foreach ($candidate in @('python3', 'python')) {
            $found = Get-Command $candidate -ErrorAction SilentlyContinue
            if ($found) { $py = $found.Source; break }
        }
        if (-not $py) {
            # Not a pass and not a silent skip: say which tool was missing (V5/V31).
            Write-TestResult "review_ledger.py selftest" $false 'SKIPPED — no python3/python on PATH; this is not a pass' $sw.Elapsed.TotalSeconds
        } else {
            $ledgerOut = & $py $ledgerScript selftest 2>&1
            $ledgerCode = $LASTEXITCODE
            # Filter the output array directly. `"$ledgerOut" -split "\r?\n"` looks
            # right but joins the array with spaces first, so the newlines are gone
            # before the split and nothing ever matches — an empty summary that reads
            # as "the ledger said nothing" rather than "the extraction is broken".
            $summary = ($ledgerOut | Where-Object { "$_" -match '^RESULT:' } | Select-Object -First 1)
            Write-TestResult "review_ledger.py selftest" ($ledgerCode -eq 0) "exit=$ledgerCode $summary" $sw.Elapsed.TotalSeconds
        }
    }

    # --- Receipts-path resolution (deterministic; no live CLI) ---
    # These belong in the contract suite because the bug they guard against is silent.
    # The old literal '{{RECEIPTS_DIR}}\dispatch-tests' default created a real directory
    # of that literal name inside core/ and wrote live CLI receipts into it; the raw
    # model slugs in those receipts then failed the Tier-1 release gate. Nothing
    # complained at the time — the only symptom was a release check failing later, in a
    # different tool, about a file nobody remembered writing.
    $sw.Restart()
    if ($OutputDir) {
        # Say why rather than reporting a hollow pass: with -OutputDir supplied,
        # Get-OutputDir resolves from it and these RECEIPTS_DIR arms assert nothing.
        Write-TestSkip "receipts-path resolution" "-OutputDir was supplied; these arms vary RECEIPTS_DIR"
    } else {
        $priorRcpt = $env:RECEIPTS_DIR
        try {
            # 1. Nothing set at all — refuse, and name the variable that fixes it.
            $script:ResolvedOutputDir = $null; $script:OutputDirError = $null
            Remove-Item Env:\RECEIPTS_DIR -ErrorAction SilentlyContinue
            $r1 = Get-OutputDir
            $ok1 = ($null -eq $r1) -and ($script:OutputDirError -match 'receipts_dir_required')
            Write-TestResult "receipts dir unset refused" $ok1 "returned='$r1' err='$($script:OutputDirError)'" $sw.Elapsed.TotalSeconds

            # 2. An uninstantiated placeholder. Rooted under the real temp dir on
            #    purpose: creating it would genuinely SUCCEED, so this arm proves the
            #    guard fired rather than that the OS happened to reject the path.
            $sw.Restart()
            $script:ResolvedOutputDir = $null; $script:OutputDirError = $null
            $phBase = Join-Path ([System.IO.Path]::GetTempPath()) '{{PROJECT_NAME}}'
            $env:RECEIPTS_DIR = Join-Path $phBase 'receipts'
            $r2 = Get-OutputDir
            $ok2 = ($null -eq $r2) -and ($script:OutputDirError -match 'uninstantiated_output_dir')
            Write-TestResult "placeholder receipts dir refused" $ok2 "returned='$r2' err='$($script:OutputDirError)'" $sw.Elapsed.TotalSeconds
            $sw.Restart()
            Write-TestResult "refusal created no placeholder dir" (-not (Test-Path -LiteralPath $phBase)) $phBase $sw.Elapsed.TotalSeconds

            # 3. The must-PASS half. Without it, arms 1 and 2 are equally satisfied by a
            #    Get-OutputDir that refuses everything (V5).
            $sw.Restart()
            $script:ResolvedOutputDir = $null; $script:OutputDirError = $null
            $tmpRcpt = Join-Path ([System.IO.Path]::GetTempPath()) ("cli-dispatch-rcpt-" + [guid]::NewGuid().ToString('N').Substring(0, 8))
            $env:RECEIPTS_DIR = $tmpRcpt
            $r3 = Get-OutputDir
            $ok3 = [bool]($r3 -and (Test-Path -LiteralPath $r3) -and ($r3 -notmatch '\{\{'))
            Write-TestResult "real receipts dir resolves and is created" $ok3 "returned='$r3'" $sw.Elapsed.TotalSeconds
            if (Test-Path -LiteralPath $tmpRcpt) { Remove-Item -LiteralPath $tmpRcpt -Recurse -Force -ErrorAction SilentlyContinue }
        } finally {
            # Clear the memo as well as the variable. Leaving the temp path cached would
            # redirect the receipts of every live arm that runs after this one under
            # `-Test all` — into a directory this block just deleted.
            $script:ResolvedOutputDir = $null
            $script:OutputDirError = $null
            if ($null -eq $priorRcpt) {
                Remove-Item Env:\RECEIPTS_DIR -ErrorAction SilentlyContinue
            } else {
                $env:RECEIPTS_DIR = $priorRcpt
            }
        }
    }

    # --- -OutputSchema adaptation ------------------------------------------------------
    # The structured-output endpoint returns 400 `invalid_json_schema` for JSON Schema's
    # composition/conditional keywords and for any optional property, so the wrapper writes
    # an adapted api-schema.json before dispatch.
    #
    # The adaptation now has exactly ONE implementation -- tools/adapt_output_schema.py --
    # which both wrappers call. It used to be three PowerShell functions in this .ps1 plus a
    # four-line heredoc in the .sh, and the two drifted: the .ps1 learned to recurse, to
    # widen optionals and to strip the resulting nulls back out, while the .sh went on
    # popping `allOf` from the document ROOT and nothing else. Every schema-constrained
    # review on macOS or Linux then died on a 400 naming a keyword nested under
    # `properties.findings.items` -- invisible on the machine where this copy was correct.
    #
    # So these arms check three separable facts, not one: that no local copy has reappeared
    # in either wrapper (the drift), that the shared tool is correct over the real shipped
    # schema (the behaviour), and that the file the CLI is actually handed is the adapted one
    # (the wiring). The third is the only one that can see a wrapper falling back to the
    # unadapted schema, which is exactly what the old `catch { $apiSchemaPath =
    # $canonicalSchema }` did, silently, on any error.
    $sw.Restart()
    $toolsSrcDir = Split-Path $wrapper -Parent
    $adapterSrc = Join-Path $toolsSrcDir 'adapt_output_schema.py'
    $shWrapperForDup = Resolve-WrapperPath -Name 'Invoke-CodexDispatch.sh'
    $shTextForDup = if ($shWrapperForDup) { Get-Content -LiteralPath $shWrapperForDup -Raw } else { '' }

    $localCopies = @()
    foreach ($marker in @('function Remove-SchemaKeyword', 'function Set-SchemaStrictRequired', 'function Remove-NullProperty')) {
        if ($text -like "*$marker*") { $localCopies += ".ps1: $marker" }
    }
    if ($shTextForDup -like '*data.pop("allOf"*') { $localCopies += '.sh: inline data.pop("allOf")' }
    $bothDelegate = ($text -like '*adapt_output_schema.py*') -and ($shTextForDup -like '*adapt_output_schema.py*')
    $noLocalCopy = ($localCopies.Count -eq 0) -and $bothDelegate
    Write-TestResult "Schema adaptation has one implementation" $noLocalCopy "local copies: $(if ($localCopies.Count) { $localCopies -join '; ' } else { 'none' }); both wrappers call adapt_output_schema.py: $bothDelegate" $sw.Elapsed.TotalSeconds

    # Delegate the semantics to the shared tool's own suite rather than restating them here:
    # a second set of assertions about stripping and widening is a second implementation of
    # the spec, which is the failure mode this consolidation exists to end. The arm tally is
    # asserted alongside the exit code because a suite that ran zero arms also exits 0.
    $sw.Restart()
    $pyForAdapter = @('python3', 'python') | ForEach-Object { Get-Command $_ -ErrorAction SilentlyContinue } | Where-Object { $_ } | Select-Object -First 1
    if (-not (Test-Path -LiteralPath $adapterSrc)) {
        Write-TestResult "Shared schema adapter selftest" $false "adapt_output_schema.py not found at $adapterSrc — the -OutputSchema path has no implementation to check" $sw.Elapsed.TotalSeconds
    } elseif (-not $pyForAdapter) {
        Write-TestSkip "Shared schema adapter selftest" "neither python3 nor python is on PATH"
    } else {
        $adaptOut = (& $pyForAdapter.Source $adapterSrc selftest 2>&1) -join "`n"
        $adaptCode = $LASTEXITCODE
        $resultLine = ($adaptOut -split "`r?`n" | Where-Object { $_ -match '^RESULT:' } | Select-Object -First 1)
        $adaptArms = 0
        if ($resultLine -match 'RESULT: (\d+) arm') { $adaptArms = [int]$Matches[1] }
        Write-TestResult "Shared schema adapter selftest" (($adaptCode -eq 0) -and ($resultLine -match '0 failure') -and ($adaptArms -ge 20)) "exit=$adaptCode; $resultLine" $sw.Elapsed.TotalSeconds
    }

    # V2: what the CLI is handed, observed through the real entry point with a fake `codex`
    # that records its arguments. `.cmd` because that is the extension the wrapper launches
    # through cmd.exe, the same path a real npm-installed codex shim takes.
    $sw.Restart()
    $e2eTools = Split-Path $runnable -Parent
    $e2eSchema = Join-Path $script:ContractRepoRoot '.agent\schemas\review-verdict.schema.v2.json'
    $e2eAdapter = Join-Path $e2eTools 'adapt_output_schema.py'
    if (-not (Test-Path -LiteralPath $e2eSchema)) {
        Write-TestResult "Wrapper dispatches the ADAPTED schema" $false "review-verdict.schema.v2.json not present at $e2eSchema, so the -OutputSchema path cannot be driven" $sw.Elapsed.TotalSeconds
    } elseif (-not (Test-Path -LiteralPath $e2eAdapter)) {
        Write-TestResult "Wrapper dispatches the ADAPTED schema" $false "adapt_output_schema.py not present next to the wrapper at $e2eAdapter" $sw.Elapsed.TotalSeconds
    } elseif (-not $pyForAdapter) {
        Write-TestSkip "Wrapper dispatches the ADAPTED schema" "neither python3 nor python is on PATH"
    } else {
        $capturedSchema = Join-Path $script:ContractTempRoot 'captured-api-schema.json'
        $capturedArgs = Join-Path $script:ContractTempRoot 'captured-args.txt'
        # Where the run directory is, taken from the wrapper rather than recomputed: the
        # default -OutputDir is baked in at instantiation, so path arithmetic here would be
        # right in the packaged tree and wrong in an adopter's.
        $capturedOutPath = Join-Path $script:ContractTempRoot 'captured-out-path.txt'
        $fakePs1 = Join-Path $script:ContractTempRoot 'fake-codex.ps1'
        $fakeCmd = Join-Path $script:ContractTempRoot 'fake-codex.cmd'

        # The fake writes a verdict containing explicit nulls, because that is what the
        # widened schema forces a real model to emit. The wrapper's null-strip is then
        # observable on disk instead of being taken on trust.
        $fakePs1Body = @'
$argv = $args
Set-Content -LiteralPath '__ARGS__' -Value ($argv -join "`n") -Encoding utf8
for ($i = 0; $i -lt $argv.Count; $i++) {
    if ($argv[$i] -eq '--output-schema' -and ($i + 1) -lt $argv.Count) {
        Copy-Item -LiteralPath $argv[$i + 1] -Destination '__CAPTURED__' -Force
    }
    if ($argv[$i] -eq '-o' -and ($i + 1) -lt $argv.Count) {
        Set-Content -LiteralPath '__OUTPATH__' -Value $argv[$i + 1] -Encoding utf8
        Set-Content -LiteralPath $argv[$i + 1] -Encoding utf8 -Value '{"verdict":"approved","mechanism":null,"findings":[{"id":"F1","mechanism":null}]}'
    }
}
Write-Output '{"type":"turn.completed"}'
exit 0
'@
        $fakePs1Body = $fakePs1Body.Replace('__ARGS__', $capturedArgs).Replace('__CAPTURED__', $capturedSchema).Replace('__OUTPATH__', $capturedOutPath)
        [IO.File]::WriteAllText($fakePs1, $fakePs1Body, (New-Object System.Text.UTF8Encoding($false)))

        $fakeCmdBody = "@echo off`r`nif `"%~1`"==`"--version`" (`r`n  echo codex-cli 9.9.9`r`n  exit /b 0`r`n)`r`npwsh -NoProfile -ExecutionPolicy Bypass -File `"%~dp0fake-codex.ps1`" %*`r`nexit /b %ERRORLEVEL%`r`n"
        [IO.File]::WriteAllText($fakeCmd, $fakeCmdBody, (New-Object System.Text.UTF8Encoding($false)))

        # -AuthorVendor is supplied because the default class is `independent_reviewer`,
        # which declares `vendor_distinct_from: author` and refuses to guess. That refusal is
        # its own arm elsewhere; here it would only stop the dispatch short of the schema.
        $e2eOut = & pwsh -NoProfile -File $runnable -NonReviewDispatch -Mode ReviewReadOnly `
            -ReasoningEffort medium -Retention Keep -DispatchId 'schema-e2e' `
            -AuthorVendor 'anthropic' `
            -PromptText 'noop' -OutputSchema $e2eSchema -CodexExecutable $fakeCmd 2>&1
        $e2eExit = $LASTEXITCODE
        $e2eRunDir = if (Test-Path -LiteralPath $capturedOutPath) {
            Split-Path (Get-Content -LiteralPath $capturedOutPath -Raw).Trim() -Parent
        } else { '' }

        if (-not (Test-Path -LiteralPath $capturedSchema)) {
            Write-TestResult "Wrapper dispatches the ADAPTED schema" $false "the fake codex never received --output-schema (wrapper exit=$e2eExit). Output: $((($e2eOut | Out-String).Trim() -split "`r?`n" | Select-Object -Last 4) -join ' | ')" $sw.Elapsed.TotalSeconds
        } else {
            $capturedJson = Get-Content -LiteralPath $capturedSchema -Raw
            $captured = $capturedJson | ConvertFrom-Json
            # Keyword-position count, done here rather than by reusing the tool's own
            # traversal: an assertion made with the code under test proves nothing (V5).
            $rejectRe = '"(allOf|oneOf|not|if|then|else)"\s*:'
            $shippedRaw = Get-Content -LiteralPath $e2eSchema -Raw
            $before = ([regex]::Matches($shippedRaw, $rejectRe)).Count
            $after = ([regex]::Matches($capturedJson, $rejectRe)).Count
            $mechType = @($captured.properties.findings.items.properties.mechanism.type)
            $mechRequired = @($captured.properties.findings.items.required) -contains 'mechanism'
            $adapted = ($before -gt 0) -and ($after -eq 0) -and $mechRequired -and ($mechType -contains 'null')
            Write-TestResult "Wrapper dispatches the ADAPTED schema" $adapted "rejected keywords shipped=$before dispatched=$after; mechanism required=$mechRequired type=[$($mechType -join ',')]" $sw.Elapsed.TotalSeconds
        }

        # The return leg. The shipped schema is strict and would refuse `"mechanism": null`,
        # so the wrapper must strip nulls before post-validation -- and must keep the
        # pre-strip text, because a governance package does not rewrite a reviewer's output
        # with no auditable copy of what it said.
        $sw.Restart()
        $finalJson = if ($e2eRunDir) { Join-Path $e2eRunDir 'final.json' } else { '' }
        $rawJson = if ($e2eRunDir) { Join-Path $e2eRunDir 'final.raw.json' } else { '' }
        if (-not $e2eRunDir) {
            Write-TestResult "Wrapper strips nulls from the CLI's output" $false "the fake codex was never given -o, so the wrapper produced no output file to strip (wrapper exit=$e2eExit)" $sw.Elapsed.TotalSeconds
        } elseif (-not (Test-Path -LiteralPath $finalJson)) {
            Write-TestResult "Wrapper strips nulls from the CLI's output" $false "no final.json under $e2eRunDir (wrapper exit=$e2eExit)" $sw.Elapsed.TotalSeconds
        } else {
            $finalText = Get-Content -LiteralPath $finalJson -Raw
            $rawExists = Test-Path -LiteralPath $rawJson
            $rawHadNull = $rawExists -and ((Get-Content -LiteralPath $rawJson -Raw) -match ':\s*null')
            $finalHasNull = $finalText -match ':\s*null'
            $verdictKept = ($finalText | ConvertFrom-Json).verdict -eq 'approved'
            # rawHadNull is asserted, not assumed: "no nulls in final.json" means nothing
            # unless there were nulls to remove (V5).
            Write-TestResult "Wrapper strips nulls from the CLI's output" ($rawHadNull -and (-not $finalHasNull) -and $verdictKept) "pre-strip copy kept=$rawExists with nulls=$rawHadNull; final.json nulls=$finalHasNull; verdict preserved=$verdictKept" $sw.Elapsed.TotalSeconds
        }
    }

    # POSIX companion (macOS/Linux) — presence + placeholder + bash -n when bash exists
    $sw.Restart()
    $shWrapper = Resolve-WrapperPath -Name 'Invoke-CodexDispatch.sh'
    if (-not $shWrapper) {
        Write-TestResult "POSIX wrapper path resolve" $false "Invoke-CodexDispatch.sh not found" $sw.Elapsed.TotalSeconds
    } else {
        Write-TestResult "POSIX wrapper path resolve" $true $shWrapper $sw.Elapsed.TotalSeconds
        $sw.Restart()
        $shText = Get-Content -LiteralPath $shWrapper -Raw
        $shPhTemp = $shText -match '\{\{RECEIPTS_DIR\}\}'
        $shPhRoot = $shText -match '\{\{PROJECT_ROOT\}\}'
        $shLiveTemp = $shText -match '(?i)C:[/\\]Temp[/\\]{{PROJECT_NAME}}'
        $shLiveRoot = $shText -match '(?i)P:[/\\]{{PROJECT_NAME}}'
        $shTok = $shPhTemp -and $shPhRoot -and (-not $shLiveTemp) -and (-not $shLiveRoot)
        Write-TestResult "POSIX wrapper tokens" $shTok "PH_TEMP=$shPhTemp PH_ROOT=$shPhRoot LIVE_TEMP=$shLiveTemp LIVE_ROOT=$shLiveRoot" $sw.Elapsed.TotalSeconds

        $sw.Restart()
        # Prefer real Git Bash; WindowsApps bash.exe is often a Store stub (exit 127).
        $bashCandidates = @(
            (Join-Path ${env:ProgramFiles} 'Git\bin\bash.exe'),
            (Join-Path ${env:ProgramFiles(x86)} 'Git\bin\bash.exe'),
            (Get-Command bash -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source)
        ) | Where-Object { $_ -and (Test-Path -LiteralPath $_) }
        $bashExe = $bashCandidates | Select-Object -First 1
        if ($bashExe) {
            $bashOut = & $bashExe -n $shWrapper 2>&1
            $bashCode = $LASTEXITCODE
            if ($bashCode -eq 127 -and "$bashOut" -match 'No such file|WindowsApps|not found') {
                Write-TestSkip "POSIX wrapper bash -n" "bash on PATH is a non-functional stub ($bashExe)"
            } elseif ($bashCode -eq 0) {
                Write-TestResult "POSIX wrapper bash -n" $true "exit=0 ($bashExe)" $sw.Elapsed.TotalSeconds
            } else {
                Write-TestResult "POSIX wrapper bash -n" $false "exit=$bashCode ($bashExe) $bashOut" $sw.Elapsed.TotalSeconds
            }
        } else {
            Write-TestSkip "POSIX wrapper bash -n" "bash not on PATH (syntax check deferred to macOS/Linux)"
        }
    }

    # Restore the caller's environment and drop the temp tree. RECEIPTS_DIR is restored
    # rather than cleared: this suite may run inside a session that had a real one set,
    # and leaving a temp path behind would silently redirect that session's receipts.
    if ($null -eq $priorReceipts) {
        Remove-Item Env:\RECEIPTS_DIR -ErrorAction SilentlyContinue
    } else {
        $env:RECEIPTS_DIR = $priorReceipts
    }
    if ($wasTokenized -and $testRoot -and (Test-Path -LiteralPath $testRoot)) {
        Remove-Item -LiteralPath $testRoot -Recurse -Force -ErrorAction SilentlyContinue
    }
}

# --- Test 1: Codex Validation (live; opt-in; no length false-pass) ---

function Test-CodexValidation {
    Write-TestHeader "Codex CLI — Validation (GPT-5.5, reasoning=high)"

    $dir = Get-OutputDir
    if (-not $dir) { Write-TestResult "Codex Validation" $false $script:OutputDirError 0; return }

    $outputFile = "$dir\codex-val-output.md"
    $logFile = "$dir\codex-val-log.txt"
    Clean-File $outputFile
    Clean-File $logFile

    $prompt = @"
You are a validation agent. Evaluate the following Python function for correctness:

```python
def fibonacci(n):
    if n <= 0:
        return []
    elif n == 1:
        return [0]
    elif n == 2:
        return [0, 1]
    fib = [0, 1]
    for i in range(2, n):
        fib.append(fib[i-1] + fib[i-2])
    return fib
```

Report: VERDICT (PASS or CHANGES_REQUIRED), then a 1-line SUMMARY.
"@

    $sw = [System.Diagnostics.Stopwatch]::StartNew()

    try {
        $run = Start-CliWithTimeout -FilePath "codex" -ArgumentList @(
            "exec",
            "-C", "{{PROJECT_ROOT}}",
            "-s", "danger-full-access",
            "-c", "model_reasoning_effort=high",
            "-o", $outputFile,
            $prompt
        ) -StdOut "$logFile.stdout" -StdErr "$logFile.stderr" -TimeoutSec 300

        $sw.Stop()

        # Reported before the content checks, and separately from them: a timeout that
        # left a partial -o file behind would otherwise be judged on that partial
        # content and could report PASS on a run that was killed.
        if ($run.TimedOut) {
            Write-TestResult "Codex Validation" $false "codex did not exit within 300s; process tree killed" $sw.Elapsed.TotalSeconds
            return
        }
        if ($run.ExitCode -ne 0) {
            Write-TestResult "Codex Validation" $false "codex exited $($run.ExitCode) — see $logFile.stderr" $sw.Elapsed.TotalSeconds
            return
        }

        if (Test-Path $outputFile) {
            $content = Get-Content $outputFile -Raw
            if ($content -match "VERDICT.*PASS" -or $content -match "(?m)^VERDICT:\s*PASS") {
                Write-TestResult "Codex Validation" $true "VERDICT PASS found ($($content.Length) chars)" $sw.Elapsed.TotalSeconds
            } else {
                Write-TestResult "Codex Validation" $false "No VERDICT PASS in output ($($content.Length) chars) — length alone is not a pass" $sw.Elapsed.TotalSeconds
            }
        } else {
            Write-TestResult "Codex Validation" $false "Output file not created" $sw.Elapsed.TotalSeconds
        }
    } catch {
        $sw.Stop()
        Write-TestResult "Codex Validation" $false "Exception: $_" $sw.Elapsed.TotalSeconds
    }
}

# --- Test 2: Codex Image Generation ---

function Test-CodexImageGen {
    Write-TestHeader "Codex CLI — Image Generation (GPT-5.5, image_gen)"

    $dir = Get-OutputDir
    if (-not $dir) { Write-TestResult "Codex Image Gen" $false $script:OutputDirError 0; return }

    $imgTarget = "$dir\test-generated-image.png"
    $outputFile = "$dir\codex-img-output.md"
    $logFile = "$dir\codex-img-log.txt"
    Clean-File $imgTarget
    Clean-File $outputFile
    Clean-File $logFile

    $prompt = "Use the built-in image_gen tool to generate: a simple red square on white background, 256x256. Save the result to $imgTarget"

    $sw = [System.Diagnostics.Stopwatch]::StartNew()

    try {
        $run = Start-CliWithTimeout -FilePath "codex" -ArgumentList @(
            "exec",
            "-C", "{{PROJECT_ROOT}}",
            "-s", "danger-full-access",
            "--enable", "image_generation",
            "-c", "model_reasoning_effort=medium",
            "-o", $outputFile,
            $prompt
        ) -StdOut "$logFile.stdout" -StdErr "$logFile.stderr" -TimeoutSec 300

        $sw.Stop()

        if ($run.TimedOut) {
            Write-TestResult "Codex Image Gen" $false "codex did not exit within 300s; process tree killed" $sw.Elapsed.TotalSeconds
            return
        }

        # Check if image was generated (either at target path or in .codex/generated_images/)
        $imageExists = Test-Path $imgTarget
        if (-not $imageExists) {
            # Check default location
            $defaultImages = Get-ChildItem "$env:USERPROFILE\.codex\generated_images" -Recurse -Filter "*.png" -ErrorAction SilentlyContinue |
                Where-Object { $_.LastWriteTime -gt (Get-Date).AddMinutes(-5) }
            $imageExists = $null -ne $defaultImages -and $defaultImages.Count -gt 0
        }

        if ($imageExists) {
            Write-TestResult "Codex Image Gen" $true "Image generated successfully" $sw.Elapsed.TotalSeconds
        } elseif ((Test-Path $outputFile) -and (Get-Content $outputFile -Raw).Length -gt 10) {
            Write-TestResult "Codex Image Gen" $true "Output file has content (image may be at default path)" $sw.Elapsed.TotalSeconds
        } else {
            Write-TestResult "Codex Image Gen" $false "No image found" $sw.Elapsed.TotalSeconds
        }
    } catch {
        $sw.Stop()
        Write-TestResult "Codex Image Gen" $false "Exception: $_" $sw.Elapsed.TotalSeconds
    }
}

# --- Test 3: agy Data Processing ---

function Test-AgyDataProcessing {
    Write-TestHeader "agy CLI — Data Processing (Gemini 3.5 Flash High)"

    $agyPath = "$env:LOCALAPPDATA\agy\bin\agy.exe"
    if (-not (Test-Path $agyPath)) {
        Write-TestSkip "agy Data Processing" "agy.exe not found at $agyPath"
        return
    }

    $version = (& $agyPath --version 2>$null | Out-String).Trim()
    if (-not $version) {
        Write-TestSkip "agy Data Processing" "agy --version returned empty"
        return
    }

    # After the agy presence checks, not before: an absent agy is a legitimate SKIP,
    # and reporting a receipts-path problem to someone who simply does not have the
    # CLI installed points them at the wrong thing.
    $dir = Get-OutputDir
    if (-not $dir) { Write-TestResult "agy Data Processing" $false $script:OutputDirError 0; return }

    $outputFile = "$dir\agy-data-output.txt"
    Clean-File $outputFile

    # Create a test data file for processing
    $testDataFile = "$dir\test-data.csv"
    @"
Name,Age,City,Score
Alice,30,New York,85
Bob,25,San Francisco,92
Carol,35,Chicago,78
Dave,28,Boston,95
Eve,32,Seattle,88
"@ | Set-Content $testDataFile -Encoding UTF8

    $prompt = @"
Read the CSV file at $testDataFile and produce a summary report with:
1. Total number of records
2. Average age
3. Average score
4. Person with highest score
5. List all cities mentioned

Return the complete report as markdown on stdout.
"@

    $sw = [System.Diagnostics.Stopwatch]::StartNew()

    try {
        # Flags BEFORE -p; prompt in a variable (see cli-dispatch SKILL.md agy rules).
        & $agyPath --print-timeout 5m0s --effort high --add-dir "{{PROJECT_ROOT}}" -p $prompt *> $outputFile
        $code = $LASTEXITCODE
        $sw.Stop()

        if ($code -ne 0) {
            Write-TestResult "agy Data Processing" $false "agy exited $code (version=$version)" $sw.Elapsed.TotalSeconds
            return
        }

        if (Test-Path $outputFile) {
            $content = Get-Content $outputFile -Raw -ErrorAction SilentlyContinue
            if ($null -ne $content -and $content.Length -gt 20) {
                Write-TestResult "agy Data Processing" $true "Stdout capture OK ($($content.Length) chars, version=$version)" $sw.Elapsed.TotalSeconds
            } else {
                Write-TestResult "agy Data Processing" $false "Stdout empty/short — check ~/.gemini/antigravity-cli/log for MCP stalls" $sw.Elapsed.TotalSeconds
            }
        } else {
            Write-TestResult "agy Data Processing" $false "Output receipt not created" $sw.Elapsed.TotalSeconds
        }
    } catch {
        $sw.Stop()
        Write-TestResult "agy Data Processing" $false "Exception: $_" $sw.Elapsed.TotalSeconds
    }
}

# --- Test 4: Claude Creative Writing ---

function Test-ClaudeCreativeWriting {
    $model = Get-ClassModel -Class 'creative_prose' -Harness 'claude-p'
    Write-TestHeader "Claude Code — Creative Writing ($model)"

    $dir = Get-OutputDir
    if (-not $dir) { Write-TestResult "Claude Creative Writing" $false $script:OutputDirError 0; return }

    $outputFile = "$dir\claude-writing-output.txt"
    $logFile = "$dir\claude-writing-log.txt"
    Clean-File $outputFile
    Clean-File $logFile

    $prompt = @"
Write in a natural, human-like tone. Avoid bullet points, numbered lists,
and AI-typical phrasing like 'certainly' or 'I'd be happy to'.

Write a short paragraph (50-80 words) describing a sunrise over a mountain lake.
Focus on sensory details — what you see, hear, and feel. Write as a skilled human
nature writer would.
"@

    $sw = [System.Diagnostics.Stopwatch]::StartNew()

    try {
        # Use cmd to pipe NUL to stdin
        $cmdLine = "echo. | claude -p --model $model --permission-mode plan --output-format json --max-turns 5 --max-budget-usd 2 `"$($prompt -replace '"', '\"')`""

        $null | claude -p `
            --model $model `
            --permission-mode plan `
            --output-format json `
            --max-turns 5 `
            --max-budget-usd 2 `
            $prompt `
            *> $outputFile

        $sw.Stop()

        if (Test-Path $outputFile) {
            $raw = Get-Content $outputFile -Raw -Encoding Unicode
            if ($null -eq $raw -or $raw.Length -lt 10) {
                $raw = Get-Content $outputFile -Raw
            }

            if ($null -ne $raw -and $raw.Length -gt 20) {
                try {
                    $json = $raw | ConvertFrom-Json
                    $result = $json.result
                    if ([string]::IsNullOrWhiteSpace([string]$result)) {
                        Write-TestResult "Claude Creative Writing" $false "JSON missing non-empty result field" $sw.Elapsed.TotalSeconds
                    } else {
                        Write-TestResult "Claude Creative Writing" $true "Output: $($result.Substring(0, [Math]::Min(80, $result.Length)))..." $sw.Elapsed.TotalSeconds
                    }
                } catch {
                    Write-TestResult "Claude Creative Writing" $false "Output not valid JSON ($($raw.Length) chars)" $sw.Elapsed.TotalSeconds
                }
            } else {
                Write-TestResult "Claude Creative Writing" $false "Output too short ($($raw.Length) chars)" $sw.Elapsed.TotalSeconds
            }
        } else {
            Write-TestResult "Claude Creative Writing" $false "Output file not created" $sw.Elapsed.TotalSeconds
        }
    } catch {
        $sw.Stop()
        Write-TestResult "Claude Creative Writing" $false "Exception: $_" $sw.Elapsed.TotalSeconds
    }
}

# --- Main ---

Write-Host "`n" -NoNewline
Write-Host "╔══════════════════════════════════════════════════════════╗" -ForegroundColor Magenta
Write-Host "║      CLI DISPATCH SKILL — VALIDATION TEST SUITE        ║" -ForegroundColor Magenta
Write-Host "╚══════════════════════════════════════════════════════════╝" -ForegroundColor Magenta
Write-Host ""
Write-Host "  Output dir: $(if ($OutputDir) { $OutputDir } elseif ($env:RECEIPTS_DIR) { Join-Path $env:RECEIPTS_DIR 'dispatch-tests' } else { '<unset — live arms will fail closed>' })"
Write-Host "  Test scope: $Test"
Write-Host ""

# Deliberately NOT created here. See Get-OutputDir: creating the dir before the
# switch is what let `-Test wrapper-contract` -- which writes no receipts at all --
# materialise a directory named after an unsubstituted placeholder.

switch ($Test) {
    'all' {
        Test-CodexWrapperContract
        Test-CodexValidation
        Test-CodexImageGen
        Test-AgyDataProcessing
        Test-ClaudeCreativeWriting
    }
    'wrapper-contract'   { Test-CodexWrapperContract }
    'codex-validation'   { Test-CodexValidation }
    'codex-image'        { Test-CodexImageGen }
    'agy-data'           { Test-AgyDataProcessing }
    'claude-writing'     { Test-ClaudeCreativeWriting }
}

# --- Summary ---

Write-Host "`n$('=' * 60)" -ForegroundColor Magenta
Write-Host "  SUMMARY" -ForegroundColor Magenta
Write-Host "$('=' * 60)" -ForegroundColor Magenta
Write-Host ""
$script:Results | Format-Table -AutoSize
Write-Host "  Total: $($script:PassCount + $script:FailCount + $script:SkipCount) | " -NoNewline
Write-Host "PASS: $script:PassCount " -ForegroundColor Green -NoNewline
Write-Host "FAIL: $script:FailCount " -ForegroundColor Red -NoNewline
Write-Host "SKIP: $script:SkipCount" -ForegroundColor Yellow
Write-Host ""

# Exit with failure code if any test failed
if ($script:FailCount -gt 0) { exit 1 }
