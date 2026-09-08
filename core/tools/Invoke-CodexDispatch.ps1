[CmdletBinding()]
param(
    [Parameter(Mandatory = $false)]
    [ValidateSet('ReviewReadOnly', 'ReviewWorkspace', 'FullAccess')]
    [string]$Mode = 'ReviewReadOnly',

    [Parameter(Mandatory = $false)]
    [ValidateSet('medium', 'high', 'xhigh', 'max')]
    [string]$ReasoningEffort = 'high',

    [Parameter(Mandatory = $false)]
    [ValidateSet('Keep', 'CompressOnSuccess', 'DeleteOnSuccess')]
    [string]$Retention = 'CompressOnSuccess',

    # No default. Omitting -Model asks the registry which snapshot serves
    # -ModelClass; passing -Model '' is a caller who said "use this" and handed
    # over nothing, and stays the failure it always was. The two are told apart
    # by $PSBoundParameters.ContainsKey('Model'), not by emptiness.
    [Parameter(Mandatory = $false)]
    [string]$Model,

    # The capability class this dispatch needs. The live registry home
    # (see .agent/INSTANTIATE.md) is the only place a class is bound to a
    # concrete snapshot, so a model bump is one edit there and no edit here.
    [Parameter(Mandatory = $false)]
    [string]$ModelClass = 'independent_reviewer',

    # Vendor of the agent that authored the work under review. Required for any
    # class declaring `vendor_distinct_from: author`. Only the dispatching
    # session knows this, so the wrapper never guesses it — absence is the named
    # error `author_vendor_required`. A session may set
    # {{PROJECT_NAME_UPPER}}_AUTHOR_VENDOR once instead of passing it per call.
    [Parameter(Mandatory = $false)]
    [string]$AuthorVendor,

    [Parameter(Mandatory = $false)]
    [string]$PromptFile,

    [Parameter(Mandatory = $false)]
    [string]$PromptText,

    [Parameter(Mandatory = $false)]
    [string]$DispatchId,

    # The review loop this dispatch belongs to. Exactly one of -LoopId or
    # -NonReviewDispatch is required: a review dispatch with no loop is an
    # unbounded loop, and "the caller forgot" and "this is not a review" produce
    # identical behaviour unless the caller is made to say which (V4/V31).
    [Parameter(Mandatory = $false)]
    [string]$LoopId,

    # This dispatch is not an independent review, so no round is being consumed.
    # Recorded in status.json so the choice is auditable after the fact rather
    # than being an invisible bypass.
    [Parameter(Mandatory = $false)]
    [switch]$NonReviewDispatch,

    # Consult the ledger and exit without dispatching. For a caller that wants to
    # know whether a round is permitted before paying for one.
    [Parameter(Mandatory = $false)]
    [switch]$GateOnly,

    # Which kind of review this is. Optional, and an *assertion* rather than a source:
    # with -LoopId the wrapper takes the kind from the mode the ledger recorded at
    # `begin`, and a -Kind that disagrees is exit 1. The vocabulary is review_ledger.py's
    # ROUND_BUDGETS keys, not a second list of names, so the wrapper cannot recognise a
    # kind the ledger would reject or apply a plan budget to an execution review (V42).
    [Parameter(Mandatory = $false)]
    [ValidateSet('plan', 'execution', 'discovery', 'handoff', 'multi-handoff')]
    [string]$Kind,

    [Parameter(Mandatory = $false)]
    [string]$OutputDir = '{{RECEIPTS_DIR}}/dispatch',

    [Parameter(Mandatory = $false)]
    [string]$OutputSchema,

    [Parameter(Mandatory = $false)]
    [switch]$UseSearch,

    [Parameter(Mandatory = $false)]
    [switch]$Force,

    [Parameter(Mandatory = $false)]
    [string]$FullAccessJustification,

    [Parameter(Mandatory = $false)]
    [string]$ApiKeyEnvVar,

    [Parameter(Mandatory = $false)]
    [string]$WorkingDirectory = '{{PROJECT_ROOT}}',

    [Parameter(Mandatory = $false)]
    [string]$CodexExecutable = 'codex',

    [Parameter(Mandatory = $false)]
    [switch]$BenchmarkIsolation,

    [Parameter(Mandatory = $false)]
    [string]$BenchmarkContextReceipt,

    [Parameter(Mandatory = $false)]
    [string]$BenchmarkContextSha256,

    # 0 = derive from ReasoningEffort (medium=900, high=1800, xhigh=2700, max=3600).
    [Parameter(Mandatory = $false)]
    [ValidateRange(0, 86400)]
    [int]$TimeoutSec = 0,

    # Seconds to wait after a no-terminal timeout kill for late turn.completed/final.md.
    [Parameter(Mandatory = $false)]
    [ValidateRange(0, 600)]
    [int]$PostKillGraceSec = 90,

    # Tests may disable tree-kill to simulate cmd-only orphan completion.
    [Parameter(Mandatory = $false)]
    [switch]$NoProcessTreeKill,

    # Minimum allowed Codex CLI semver (x.y.z). Preflight fails closed below this.
    [Parameter(Mandatory = $false)]
    [ValidatePattern('^\d+\.\d+\.\d+$')]
    [string]$MinCodexCliVersion = '0.145.0',

    # Emergency/test escape hatch — do not use for production reviews.
    [Parameter(Mandatory = $false)]
    [switch]$SkipCodexVersionCheck
)

# Helper to write UTF-8 text without BOM
function Write-TextNoBom {
    param(
        [string]$Path,
        [string]$Content
    )
    $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($Path, $Content, $utf8NoBom)
}

function Get-Sha256File {
    param([Parameter(Mandatory = $true)][string]$Path)
    $stream = [System.IO.File]::OpenRead($Path)
    $sha = [System.Security.Cryptography.SHA256]::Create()
    try {
        $bytes = $sha.ComputeHash($stream)
        return ([System.BitConverter]::ToString($bytes)).Replace('-', '').ToLowerInvariant()
    } finally {
        $sha.Dispose()
        $stream.Dispose()
    }
}

function Get-PythonExe {
    <#
    .SYNOPSIS
        The interpreter this package's Python helpers are run with, or $null if there is none.
    .DESCRIPTION
        Prefers the project venv when a repo root is known, so the helpers see the same
        dependencies the rest of the toolchain does, then falls back to `python3` and
        `python` on PATH.

        Resolved in ONE place. This file previously resolved Python three separate ways --
        the ledger check walked PATH for python3-then-python, the schema post-validation
        looked only for the venv and otherwise assumed a bare `python` existed, and a third
        call site assumed the same. On a machine where `python` is absent but `python3` is
        present (the default on most Linux distributions and on Homebrew macOS) the ledger
        gate ran and the validator did not, so a verdict could be recorded having never
        been checked against its schema. Returning $null rather than a hopeful default is
        the point: a caller must decide what an absent interpreter means for it, and both
        callers here decide it means fail-closed.
    #>
    param([Parameter(Mandatory = $false)][string]$RepoRoot = "")
    if (-not [string]::IsNullOrEmpty($RepoRoot)) {
        $venvPython = Join-Path $RepoRoot ".venv/Scripts/python.exe"
        if (Test-Path -LiteralPath $venvPython) { return $venvPython }
    }
    foreach ($candidate in @('python3', 'python')) {
        $found = Get-Command $candidate -ErrorAction SilentlyContinue
        if ($found) { return $found.Source }
    }
    return $null
}

# The structured-output schema adaptation used to live here as three PowerShell functions
# (Remove-SchemaKeyword, Set-SchemaStrictRequired, Remove-NullProperty) with a second,
# much shorter implementation inside Invoke-CodexDispatch.sh. Duplicated logic drifts: the
# copy in this file learned to recurse, to widen optionals and to strip the resulting nulls
# back out, and the POSIX copy went on popping `allOf` from the root of the document and
# nothing else -- so every schema-constrained review on macOS or Linux died on a 400 naming
# a keyword nested under `properties.findings.items`, a defect invisible on the machine
# where this copy was correct. There is now one implementation, tools/adapt_output_schema.py,
# which both wrappers call and which carries the explanation of what the adaptation is, why
# each keyword is or is not in the rejected list, and its own selftest. Do not reintroduce a
# local copy: the second implementation is the defect, not the first one's shortcomings.

function Get-DefaultDispatchTimeoutSec {
    param([string]$Effort)
    switch ($Effort) {
        'medium' { return 900 }
        'high' { return 1800 }
        'xhigh' { return 2700 }
        'max' { return 3600 }
        default { return 900 }
    }
}

function Get-KindTimeoutFloorSec {
    param([string]$Kind)
    # A floor, not a default: the effort tier says how hard the model thinks, which is a
    # different question from how much material it has to read. An execution review reads
    # the whole change plus its receipts and is the largest of the kinds, so a `medium`
    # execution review inherits 900s and dies mid-verdict -- and the round is spent
    # either way, because the ledger counts a dispatch that was permitted.
    # 0 means "this kind has nothing to say about the timeout"; the effort default stands.
    switch ($Kind) {
        'execution' { return 2700 }
        'multi-handoff' { return 2700 }
        default { return 0 }
    }
}

function Get-CodexCliVersionString {
    param(
        [Parameter(Mandatory = $true)][string]$ResolvedExecutable,
        [Parameter(Mandatory = $true)][string]$Extension
    )
    $versionFilePath = $ResolvedExecutable
    $versionArgsList = @('--version')
    if ($Extension -eq '.ps1') {
        $parentDir = [System.IO.Path]::GetDirectoryName($ResolvedExecutable)
        $jsPath = "$parentDir/node_modules/@openai/codex/bin/codex.js"
        if (Test-Path $jsPath) {
            $versionFilePath = 'node'
            $versionArgsList = @($jsPath, '--version')
        } else {
            $versionFilePath = 'powershell'
            $versionArgsList = @('-NoProfile', '-File', $ResolvedExecutable, '--version')
        }
    } elseif ($Extension -match '^\.(cmd|bat)$') {
        $versionFilePath = 'cmd.exe'
        $versionArgsList = @('/c', $ResolvedExecutable, '--version')
    }

    $versionPsi = New-Object System.Diagnostics.ProcessStartInfo
    $versionPsi.FileName = $versionFilePath
    $escapedVersionArgs = @()
    foreach ($arg in $versionArgsList) {
        $escaped = $arg -replace '"', '\"'
        $escapedVersionArgs += "`"$escaped`""
    }
    $versionPsi.Arguments = $escapedVersionArgs -join " "
    $versionPsi.UseShellExecute = $false
    $versionPsi.RedirectStandardOutput = $true
    $versionPsi.RedirectStandardError = $true
    $versionPsi.CreateNoWindow = $true

    $versionProc = [System.Diagnostics.Process]::Start($versionPsi)
    $versionOut = $versionProc.StandardOutput.ReadToEnd()
    $versionErr = $versionProc.StandardError.ReadToEnd()
    $null = $versionProc.WaitForExit(5000)
    $combined = (($versionOut + "`n" + $versionErr)).Trim()
    if ([string]::IsNullOrWhiteSpace($combined)) {
        return 'unknown'
    }
    return ($combined -split "`r?`n" | Where-Object { -not [string]::IsNullOrWhiteSpace($_) } | Select-Object -First 1).Trim()
}

function Get-CodexCliSemVer {
    param([Parameter(Mandatory = $true)][string]$VersionText)
    if ($VersionText -match '(\d+\.\d+\.\d+)') {
        try {
            return [version]$Matches[1]
        } catch {
            return $null
        }
    }
    return $null
}

function Stop-DispatchProcessTree {
    param(
        [Parameter(Mandatory = $true)][System.Diagnostics.Process]$Process,
        [switch]$NoTreeKill
    )
    $Process.Refresh()
    if ($Process.HasExited) { return }

    if (-not $NoTreeKill) {
        try {
            # Kill the whole tree — cmd.exe Kill() leaves orphaned Codex/node children.
            $null = & taskkill.exe /PID $Process.Id /T /F 2>$null
        } catch {}
    }

    $Process.Refresh()
    if (-not $Process.HasExited) {
        try { $Process.Kill() } catch {}
    }
}

function Test-DispatchTerminalAndFinal {
    param(
        [Parameter(Mandatory = $true)][string]$EventsPath,
        [Parameter(Mandatory = $true)][string]$FinalPath
    )
    $hasTerminal = $false
    if (Test-Path -LiteralPath $EventsPath) {
        try {
            foreach ($line in Get-Content -LiteralPath $EventsPath -ErrorAction SilentlyContinue) {
                if ($line -match '"type"\s*:\s*"(turn\.completed|turn\.failed)"') {
                    $hasTerminal = $true
                    break
                }
            }
        } catch {}
    }
    $hasFinal = (Test-Path -LiteralPath $FinalPath) -and ((Get-Item -LiteralPath $FinalPath).Length -gt 0)
    return ($hasTerminal -and $hasFinal)
}

function Get-PhysicalPath {
    param(
        [string]$path,
        [System.Collections.Generic.HashSet[string]]$seen = $null
    )
    if ([string]::IsNullOrEmpty($path)) { return "" }
    if ($seen -eq $null) {
        $seen = New-Object System.Collections.Generic.HashSet[string]([System.StringComparer]::OrdinalIgnoreCase)
    }

    $cleanPath = $path.Replace('\', '/')
    $absPath = [System.IO.Path]::GetFullPath($cleanPath).Replace('\', '/')

    if (-not $seen.Add($absPath)) {
        throw "Circular reparse-point path detected: $absPath"
    }

    # Split the path into components
    $components = $absPath.Split('/')
    $resolved = $components[0]
    if ([string]::IsNullOrEmpty($resolved)) {
        $resolved = "/"
    }

    for ($i = 1; $i -lt $components.Count; $i++) {
        $name = $components[$i]
        if ([string]::IsNullOrEmpty($name)) { continue }

        $resolved = Join-Path $resolved $name
        if (Test-Path -LiteralPath $resolved) {
            $item = Get-Item -LiteralPath $resolved -Force
            $isReparsePoint = (($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0)
            if ($isReparsePoint) {
                $targets = @($item.Target)
                if ($targets.Count -ne 1 -or [string]::IsNullOrWhiteSpace([string]$targets[0])) {
                    throw "Unsupported or unresolved reparse point: $resolved"
                }
                $firstTarget = [string]$targets[0]
                $currentTarget = $firstTarget -replace '^\\\?\?\\', ''
                $currentTarget = $currentTarget -replace '^\\\\\?\\', ''
                if (-not [System.IO.Path]::IsPathRooted($currentTarget)) {
                    # Split-Path -Parent returns the EMPTY STRING for a first-level path such as
                    # '/tmp', not '/'. On macOS, /tmp and /etc are reparse points whose targets are
                    # RELATIVE ('private/tmp', 'private/etc'), so this branch is the common case
                    # there, and Join-Path with an empty -Path throws a parameter-binding error.
                    # Symptom when this was unguarded: the wrapper reported "PromptFile does not
                    # exist" for a file that was plainly there. Treat an empty parent as the
                    # filesystem root explicitly.
                    $linkParent = Split-Path -Parent $resolved
                    if ([string]::IsNullOrWhiteSpace($linkParent)) {
                        $linkParent = [System.IO.Path]::DirectorySeparatorChar.ToString()
                    }
                    $currentTarget = Join-Path $linkParent $currentTarget
                }
                $resolved = Get-PhysicalPath $currentTarget $seen
                # Resolving an identity to nothing must fail closed (verification-principles V31).
                # A non-empty target that resolves to '' would silently truncate the rest of the
                # path, and every downstream containment check would then compare against a path
                # that is not the target — a sandbox check that passes for the wrong reason.
                if ([string]::IsNullOrWhiteSpace($resolved)) {
                    throw "Reparse point '$name' resolved to an empty path (target '$currentTarget')"
                }
            }
        }
    }
    return [System.IO.Path]::GetFullPath($resolved).Replace('\', '/')
}

# 1. Parameter Validation
if ([string]::IsNullOrEmpty($PromptText) -and [string]::IsNullOrEmpty($PromptFile)) {
    [Console]::Error.WriteLine("Either -PromptText or -PromptFile must be specified.")
    exit 1
}
if (-not [string]::IsNullOrEmpty($PromptText) -and -not [string]::IsNullOrEmpty($PromptFile)) {
    [Console]::Error.WriteLine("Cannot specify both -PromptText and -PromptFile.")
    exit 1
}

# Review-loop bound (see tools/review_ledger.py and
# .agent/docs/verification-principles.md V41/V43).
#
# This runs BEFORE the version preflight and long exec on purpose: the cheapest
# moment to refuse a round is before it costs anything. It is placed after
# DispatchId so a refusal can be correlated with the caller's own logs.
$loopIdWasGiven = -not [string]::IsNullOrWhiteSpace($LoopId)
if ($loopIdWasGiven -and $NonReviewDispatch) {
    [Console]::Error.WriteLine("Specify -LoopId or -NonReviewDispatch, not both. A dispatch is either bound to a review loop or declared not to be one.")
    exit 1
}
if (-not $loopIdWasGiven -and -not $NonReviewDispatch) {
    [Console]::Error.WriteLine("loop_id_required: pass -LoopId <id> to bind this dispatch to a review loop, or -NonReviewDispatch if it is not an independent review. There is no default: an unbound review dispatch is an unbounded review loop, and a forgotten flag would be indistinguishable from a deliberate one.")
    exit 1
}
if ($loopIdWasGiven -and $LoopId -notmatch '^[a-z0-9][a-z0-9._-]{0,127}$') {
    [Console]::Error.WriteLine("Invalid LoopId format. Must match ^[a-z0-9][a-z0-9._-]{0,127}$ — the same pattern review_ledger.py and review-verdict.schema.v2.json enforce, so an id accepted here is accepted there.")
    exit 1
}
$kindWasGiven = -not [string]::IsNullOrWhiteSpace($Kind)
if ($kindWasGiven -and $NonReviewDispatch) {
    [Console]::Error.WriteLine("kind_not_applicable: -Kind names the kind of *review* this is, and -NonReviewDispatch says this is not a review. Drop one. Ignoring the flag instead would leave a receipt claiming a review kind for a dispatch that consumed no round.")
    exit 1
}

$ledgerGateResult = 'not-applicable'
$ledgerMode = $null
if ($loopIdWasGiven) {
    $ledgerScript = Join-Path $PSScriptRoot 'review_ledger.py'
    if (-not (Test-Path -LiteralPath $ledgerScript -PathType Leaf)) {
        [Console]::Error.WriteLine("ledger_unavailable: -LoopId was given but review_ledger.py is not present at $ledgerScript, so the round budget could not be checked. This is exit 3, not a pass: 'could not check' is not 'checked and permitted' (V5/V31). Restore the tool, or pass -NonReviewDispatch if this dispatch is genuinely not a review.")
        exit 3
    }
    # No repo root yet at this point in the script, so this is the PATH lookup only.
    $pythonExe = Get-PythonExe
    if (-not $pythonExe) {
        [Console]::Error.WriteLine("ledger_unavailable: neither python3 nor python is on PATH, so review_ledger.py could not run and the round budget was not checked. Exit 3, not a pass. Install Python 3, or pass -NonReviewDispatch.")
        exit 3
    }

    $ledgerOutput = & $pythonExe $ledgerScript evaluate --loop-id $LoopId 2>&1
    $ledgerExit = $LASTEXITCODE
    $ledgerText = ($ledgerOutput | Out-String).TrimEnd()

    switch ($ledgerExit) {
        0 {
            $ledgerGateResult = 'permitted'
            Write-Host "[ledger] $ledgerText"
            if ($ledgerText -match 'mode=([a-z0-9][a-z0-9-]*)') { $ledgerMode = $Matches[1] }
            if (-not $ledgerMode) {
                # 3, not a shrug: the mode is where the dispatch kind comes from, and the
                # kind is what raises the timeout floor. Guessing 'plan' here would hand an
                # execution review the 15-minute default — the exact silent failure the
                # floor exists to prevent — and nothing in the receipt would say so.
                [Console]::Error.WriteLine("ledger_mode_unavailable: review_ledger.py permitted the round but its output did not name the loop's mode (expected 'mode=<plan|execution|discovery|handoff|multi-handoff>' on the OK line). The wrapper and the ledger ship as a pair; a ledger old enough to omit it is a mismatched pair, not a pass. Update tools/review_ledger.py.")
                exit 3
            }
        }
        1 {
            # A decision, not a crash. Exit 9 keeps it distinguishable from a
            # dispatch that failed (3) and from bad arguments (1): "the loop is
            # over" and "the tool broke" call for opposite responses.
            [Console]::Error.WriteLine($ledgerText)
            [Console]::Error.WriteLine("[ledger] refused loop '$LoopId'. Not dispatching. Escalate to a human, or apply the specific relief the message names — do not re-run with -NonReviewDispatch to get past this.")
            exit 9
        }
        default {
            [Console]::Error.WriteLine($ledgerText)
            [Console]::Error.WriteLine("[ledger] could not evaluate loop '$LoopId' (review_ledger.py exit $ledgerExit). Failing closed.")
            exit 3
        }
    }
} else {
    $ledgerGateResult = 'bypassed-non-review'
    Write-Host "[ledger] -NonReviewDispatch: no round consumed, no loop bound."
}

# Dispatch kind and the timeout floor it implies.
#
# Resolved here, before -GateOnly returns, for two reasons: the floor is then visible
# without paying for a dispatch, and a caller can be told its -Kind disagrees with the
# ledger for free. Kept ahead of the version preflight for the same reason the gate is.
if ($loopIdWasGiven) {
    $dispatchKind = $ledgerMode
    if ($kindWasGiven -and $Kind -ne $dispatchKind) {
        [Console]::Error.WriteLine("kind_mismatch: -Kind '$Kind' but loop '$LoopId' was opened with mode '$dispatchKind'. The ledger wins, and the disagreement is exit 1 rather than a silent correction: it usually means this dispatch is aimed at the wrong loop, and that loop's budget is the one being spent.")
        exit 1
    }
} else {
    $dispatchKind = 'non-review'
}

$timeoutWasGiven = $PSBoundParameters.ContainsKey('TimeoutSec') -and $TimeoutSec -gt 0
$kindFloorSec = Get-KindTimeoutFloorSec -Kind $dispatchKind
$timeoutFloorApplied = $false
if (-not $timeoutWasGiven) {
    $TimeoutSec = Get-DefaultDispatchTimeoutSec -Effort $ReasoningEffort
    if ($kindFloorSec -gt $TimeoutSec) {
        Write-Host "[kind] $dispatchKind review: raising the derived -TimeoutSec from $TimeoutSec to the ${kindFloorSec}s floor for this kind."
        $TimeoutSec = $kindFloorSec
        $timeoutFloorApplied = $true
    }
} elseif ($kindFloorSec -gt $TimeoutSec) {
    # An explicit -TimeoutSec is the caller's decision and is honoured; there are small
    # execution reviews. But it is said out loud, because a truncated verdict looks
    # identical to a reviewer that found nothing.
    Write-Host "[kind] $dispatchKind review with explicit -TimeoutSec $TimeoutSec, below the ${kindFloorSec}s floor for this kind. Honouring the caller. A no-terminal timeout here still spends the round."
}
Write-Host "[kind] dispatch kind '$dispatchKind', timeout ${TimeoutSec}s."

if ($GateOnly) {
    Write-Host "[ledger] -GateOnly: gate result '$ledgerGateResult'. Exiting without dispatching."
    exit 0
}

# Validate Model
$modelWasGiven = $PSBoundParameters.ContainsKey('Model')
if ($modelWasGiven -and [string]::IsNullOrEmpty($Model)) {
    [Console]::Error.WriteLine("Model must be specified.")
    exit 1
}
if ($modelWasGiven -and $Model -notmatch '^[a-zA-Z0-9.-]+$') {
    [Console]::Error.WriteLine("Invalid Model format.")
    exit 1
}

if ([string]::IsNullOrWhiteSpace($AuthorVendor) -and $env:{{PROJECT_NAME_UPPER}}_AUTHOR_VENDOR) {
    $AuthorVendor = $env:{{PROJECT_NAME_UPPER}}_AUTHOR_VENDOR
}

$registryModulePath = $null
$moduleCandidates = [System.Collections.Generic.List[string]]::new()
if ($env:AGENT_MODEL_REGISTRY) {
    $override = $env:AGENT_MODEL_REGISTRY
    if ((Test-Path -LiteralPath $override) -and (Get-Item -LiteralPath $override).PSIsContainer) {
        $moduleCandidates.Add((Join-Path $override 'tools/ModelRegistry.psm1'))
    } else {
        $overrideHome = Split-Path -Parent $override
        $moduleCandidates.Add((Join-Path $overrideHome 'tools/ModelRegistry.psm1'))
    }
}
# Shared / "drive-root" home: one registry serving several projects on a machine.
# Configured by env, never a baked drive letter -- a literal like 'P:/.agent' is one
# machine's layout, is meaningless on macOS/Linux, and on another Windows box with a P:
# drive it would silently read someone else's registry. See .agent/INSTANTIATE.md S2.
if ($env:AGENT_MODEL_REGISTRY_HOME) {
    $moduleCandidates.Add((Join-Path $env:AGENT_MODEL_REGISTRY_HOME 'tools/ModelRegistry.psm1'))
}
if ($env:USERPROFILE) {
    $moduleCandidates.Add((Join-Path $env:USERPROFILE '.agent/tools/ModelRegistry.psm1'))
}
foreach ($candidate in $moduleCandidates) {
    if (Test-Path -LiteralPath $candidate) {
        $registryModulePath = (Resolve-Path -LiteralPath $candidate).Path
        break
    }
}
if (-not $registryModulePath) {
    [Console]::Error.WriteLine(
        "registry_not_found: no ModelRegistry.psm1 at any S2 location: $($moduleCandidates -join ', ')")
    exit 1
}
Import-Module $registryModulePath -Force -ErrorAction Stop

$modelClassApplied = $ModelClass
$effortClamped = $false
$registryVersion = $null
$registrySha256 = $null
$overlaySha256 = $null
$overlayPath = $null
$pin = $null

# The project whose overlay governs this dispatch. A project overlay is the only
# place an adopter can tighten a shared class, and it binds nothing unless the
# resolution names the project. The wrapper knows which repo it was instantiated
# into, so nothing has to be passed in and no caller can forget to.
$dispatchProjectRoot = '{{PROJECT_ROOT}}'

if ($BenchmarkIsolation) {
    try {
        $pin = Get-AgentModelPin -Name 'benchmark_headroom_baseline'
    }
    catch {
        [Console]::Error.WriteLine($_.Exception.Message)
        exit 1
    }
    $modelClassApplied = 'pin:benchmark_headroom_baseline'
    $registryVersion = $pin.registry_version
    $registrySha256 = $pin.registry_sha256
    $modelResolution = if ($modelWasGiven) { 'explicit_override' } else { 'pin' }
    if (-not $modelWasGiven) {
        $Model = $pin.slug
    }
}
else {
    $resolveArgs = @{
        Class   = $ModelClass
        Harness = 'codex-cli'
        Project = $dispatchProjectRoot
    }
    if (-not [string]::IsNullOrWhiteSpace($AuthorVendor)) {
        $resolveArgs['AuthorVendor'] = $AuthorVendor
    }
    if ($modelWasGiven) {
        $resolveArgs['Slug'] = $Model
    }
    if ($ReasoningEffort) {
        $resolveArgs['Effort'] = $ReasoningEffort
    }

    try {
        $resolved = Resolve-AgentModel @resolveArgs
    }
    catch {
        [Console]::Error.WriteLine($_.Exception.Message)
        exit 1
    }

    $Model = $resolved.slug
    $ReasoningEffort = $resolved.effort
    $effortClamped = [bool]$resolved.effort_clamped
    $modelResolution = $resolved.resolution
    $registryVersion = $resolved.registry_version
    $registrySha256 = $resolved.registry_sha256
    $overlaySha256 = $resolved.overlay_sha256
    $overlayPath = $resolved.overlay_path
}

# Benchmark-specific scalar and lexical path checks run before generic
# filesystem validation because the transient provider root is created only by
# the standalone runner.
if ($BenchmarkIsolation) {
    if ($Mode -ne 'ReviewReadOnly') {
        [Console]::Error.WriteLine("BenchmarkIsolation requires Mode ReviewReadOnly.")
        exit 1
    }
    if ($ReasoningEffort -ne 'medium') {
        [Console]::Error.WriteLine("BenchmarkIsolation requires ReasoningEffort medium.")
        exit 1
    }
    if ($Model -ne $pin.slug) {
        [Console]::Error.WriteLine(
            "BenchmarkIsolation requires Model $($pin.slug).")
        exit 1
    }
    if ($UseSearch) {
        [Console]::Error.WriteLine("BenchmarkIsolation forbids search.")
        exit 1
    }
    $benchmarkRootLexical = [System.IO.Path]::GetFullPath(
        "{{PROJECT_ROOT}}/.benchmark-work/context-provider/provider-root"
    ).Replace('\', '/')
    $workDirLexical = [System.IO.Path]::GetFullPath($WorkingDirectory).Replace('\', '/')
    if ($workDirLexical -ne $benchmarkRootLexical) {
        [Console]::Error.WriteLine("BenchmarkIsolation requires the exact provider-root working directory.")
        exit 1
    }
    $benchmarkSchemaLexical = [System.IO.Path]::GetFullPath(
        "{{PROJECT_ROOT}}/.agent/schemas/headroom-standalone-answer.schema.json"
    ).Replace('\', '/')
    $schemaLexical = if ([string]::IsNullOrEmpty($OutputSchema)) {
        ""
    } else {
        [System.IO.Path]::GetFullPath($OutputSchema).Replace('\', '/')
    }
    if ($schemaLexical -ne $benchmarkSchemaLexical) {
        [Console]::Error.WriteLine("BenchmarkIsolation requires the exact standalone answer schema.")
        exit 1
    }
    if ([string]::IsNullOrWhiteSpace($BenchmarkContextReceipt)) {
        [Console]::Error.WriteLine("BenchmarkIsolation requires BenchmarkContextReceipt.")
        exit 1
    }
    if ($BenchmarkContextSha256 -notmatch '^[0-9a-f]{64}$') {
        [Console]::Error.WriteLine("BenchmarkIsolation requires a lowercase SHA-256 context hash.")
        exit 1
    }
    $benchmarkContextCanonical = [System.IO.Path]::GetFullPath(
        $BenchmarkContextReceipt
    ).Replace('\', '/')
    if (-not (Test-Path -LiteralPath $benchmarkContextCanonical -PathType Leaf)) {
        [Console]::Error.WriteLine("BenchmarkIsolation context receipt does not exist.")
        exit 1
    }
    $actualContextSha = Get-Sha256File -Path $benchmarkContextCanonical
    if ($actualContextSha -ne $BenchmarkContextSha256) {
        [Console]::Error.WriteLine("BenchmarkIsolation context receipt hash mismatch.")
        exit 1
    }
}

# Validate DispatchId
if (-not [string]::IsNullOrEmpty($DispatchId)) {
    if ($DispatchId -notmatch '^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$') {
        [Console]::Error.WriteLine("Invalid DispatchId format.")
        exit 1
    }
} else {
    $randomSuffix = Get-Random -Minimum 1000 -Maximum 9999
    $DispatchId = "dispatch-" + (Get-Date -Format 'yyyyMMddHHmmss') + "-$randomSuffix"
}


# Validate OutputDir
if ([System.Management.Automation.WildcardPattern]::ContainsWildcardCharacters($OutputDir)) {
    [Console]::Error.WriteLine("OutputDir must not contain wildcard characters.")
    exit 1
}
$canonicalOutputDir = Get-PhysicalPath $OutputDir
$parentOutputDir = Get-PhysicalPath "{{RECEIPTS_DIR}}"
if (-not ($canonicalOutputDir -eq $parentOutputDir -or $canonicalOutputDir.StartsWith($parentOutputDir + "/", [System.StringComparison]::OrdinalIgnoreCase))) {
    [Console]::Error.WriteLine("OutputDir must be under {{RECEIPTS_DIR}}")
    exit 1
}

# Validate FullAccess
if ($Mode -eq 'FullAccess') {
    if ([string]::IsNullOrEmpty($FullAccessJustification)) {
        [Console]::Error.WriteLine("FullAccessJustification is required when Mode is FullAccess.")
        exit 1
    }
    $nonWs = $FullAccessJustification -replace '\s', ''
    if ($nonWs.Length -lt 20) {
        [Console]::Error.WriteLine("FullAccessJustification must be at least 20 non-whitespace characters.")
        exit 1
    }
}

# Validate ApiKeyEnvVar
if (-not [string]::IsNullOrEmpty($ApiKeyEnvVar)) {
    if ($ApiKeyEnvVar -notmatch '^[A-Z_][A-Z0-9_]*$') {
        [Console]::Error.WriteLine("Invalid ApiKeyEnvVar format.")
        exit 1
    }
    if (-not (Test-Path "Env:\$ApiKeyEnvVar")) {
        [Console]::Error.WriteLine("ApiKeyEnvVar '$ApiKeyEnvVar' not found in environment.")
        exit 1
    }
}

# Validate WorkingDirectory
$canonicalWorkDir = Get-PhysicalPath $WorkingDirectory
if (-not (Test-Path $canonicalWorkDir)) {
    [Console]::Error.WriteLine("WorkingDirectory does not exist.")
    exit 1
}
$canonicalRepoRoot = Get-PhysicalPath "{{PROJECT_ROOT}}"
if (-not ($canonicalWorkDir -eq $canonicalRepoRoot -or $canonicalWorkDir.StartsWith($canonicalRepoRoot + "/", [System.StringComparison]::OrdinalIgnoreCase))) {
    [Console]::Error.WriteLine("WorkingDirectory must be under the repository root.")
    exit 1
}

# Validate OutputSchema
if (-not [string]::IsNullOrEmpty($OutputSchema)) {
    $canonicalSchema = Get-PhysicalPath $OutputSchema
    if (-not (Test-Path $canonicalSchema -PathType Leaf)) {
        [Console]::Error.WriteLine("OutputSchema file does not exist.")
        exit 1
    }
    if (-not ($canonicalSchema -eq $canonicalRepoRoot -or $canonicalSchema.StartsWith($canonicalRepoRoot + "/", [System.StringComparison]::OrdinalIgnoreCase))) {
        [Console]::Error.WriteLine("OutputSchema must be under the repository root.")
        exit 1
    }
}

# Validate PromptFile
if (-not [string]::IsNullOrEmpty($PromptFile)) {
    $canonicalPromptFile = Get-PhysicalPath $PromptFile
    if (-not (Test-Path $canonicalPromptFile -PathType Leaf)) {
        [Console]::Error.WriteLine("PromptFile does not exist.")
        exit 1
    }
    $inRepo = ($canonicalPromptFile -eq $canonicalRepoRoot -or $canonicalPromptFile.StartsWith($canonicalRepoRoot + "/", [System.StringComparison]::OrdinalIgnoreCase))
    $inTemp = ($canonicalPromptFile -eq $parentOutputDir -or $canonicalPromptFile.StartsWith($parentOutputDir + "/", [System.StringComparison]::OrdinalIgnoreCase))
    if (-not ($inRepo -or $inTemp)) {
        [Console]::Error.WriteLine("PromptFile must be under the repository root or {{RECEIPTS_DIR}}.")
        exit 1
    }
}

# Validate the opt-in standalone benchmark contract after all paths have been
# physically resolved. This mode is intentionally exact so normal dispatches
# remain backward compatible.
if ($BenchmarkIsolation) {
    $benchmarkRoot = Get-PhysicalPath "{{PROJECT_ROOT}}/.benchmark-work/context-provider/provider-root"
    $benchmarkSchema = Get-PhysicalPath "{{PROJECT_ROOT}}/.agent/schemas/headroom-standalone-answer.schema.json"
    if ($canonicalWorkDir -ne $benchmarkRoot) {
        [Console]::Error.WriteLine("BenchmarkIsolation requires the exact provider-root working directory.")
        exit 1
    }
    if ([string]::IsNullOrEmpty($OutputSchema) -or $canonicalSchema -ne $benchmarkSchema) {
        [Console]::Error.WriteLine("BenchmarkIsolation requires the exact standalone answer schema.")
        exit 1
    }
}

# Resolve CodexExecutable
$resolvedExecutable = ""
if ($CodexExecutable -match '[\\/]') {
    $resolvedExecutable = [System.IO.Path]::GetFullPath($CodexExecutable)
    if (-not (Test-Path $resolvedExecutable)) {
        [Console]::Error.WriteLine("Executable not found: $CodexExecutable")
        exit 1
    }
    $ext = [System.IO.Path]::GetExtension($resolvedExecutable)
    if ($ext -notmatch '^\.(exe|cmd|bat|ps1)$') {
        [Console]::Error.WriteLine("Invalid executable extension: $ext")
        exit 1
    }
} else {
    try {
        $cmdObj = @(Get-Command -Name $CodexExecutable -CommandType Application,ExternalScript -ErrorAction Stop)[0]
        $resolvedExecutable = $cmdObj.Source
    } catch {
        [Console]::Error.WriteLine("Executable not found: $CodexExecutable")
        exit 1
    }
}

# Codex CLI version preflight (fail closed before long exec)
$ext = [System.IO.Path]::GetExtension($resolvedExecutable)
$cliVersion = 'unknown'
try {
    $cliVersion = Get-CodexCliVersionString -ResolvedExecutable $resolvedExecutable -Extension $ext
} catch {
    $cliVersion = 'unknown'
}
if (-not $SkipCodexVersionCheck) {
    $parsedCli = Get-CodexCliSemVer -VersionText $cliVersion
    $parsedMin = Get-CodexCliSemVer -VersionText $MinCodexCliVersion
    if ($null -eq $parsedMin) {
        [Console]::Error.WriteLine("Invalid MinCodexCliVersion '$MinCodexCliVersion' (expected x.y.z).")
        exit 1
    }
    if ($null -eq $parsedCli) {
        [Console]::Error.WriteLine("Unable to parse Codex CLI version from '$cliVersion'. Upgrade Codex or pass -SkipCodexVersionCheck only for emergency/test use. Minimum required: $MinCodexCliVersion")
        exit 1
    }
    if ($parsedCli -lt $parsedMin) {
        [Console]::Error.WriteLine("Codex CLI version $parsedCli is below MinCodexCliVersion $MinCodexCliVersion (raw: '$cliVersion'). Upgrade with: npm install -g @openai/codex")
        exit 1
    }
}

# Sandbox Mapping
# ReviewReadOnly/ReviewWorkspace map to workspace-write + writable_roots={{RECEIPTS_DIR}}
# (Codex pure read-only blocks ALL writes including P0 Temp). On Windows the sandbox
# helper often fails entirely (helper_unknown_error), so review dispatches that need
# shell + Temp receipts should use FullAccess (danger-full-access) instead — see
# cli-dispatch/SKILL.md. Product/plan edits stay forbidden by the review prompt.
$sandboxLevel = switch ($Mode) {
    'ReviewReadOnly' { 'workspace-write' }
    'ReviewWorkspace' { 'workspace-write' }
    'FullAccess' { 'danger-full-access' }
}
$tempWritableRoot = '{{RECEIPTS_DIR}}'

# 2. Directory Setup & Collision Handling
$runDir = [System.IO.Path]::GetFullPath((Join-Path $canonicalOutputDir $DispatchId)).Replace('\', '/')
$physicalRunDir = Get-PhysicalPath $runDir
$runDirContained = $physicalRunDir.StartsWith($canonicalOutputDir + "/", [System.StringComparison]::OrdinalIgnoreCase)
if (-not $runDirContained) {
    [Console]::Error.WriteLine("Run directory must remain physically contained under OutputDir.")
    exit 1
}
if (Test-Path -LiteralPath $runDir) {
    if ($Force) {
        # Resolve the complete existing leaf immediately before deletion so a
        # reparse point cannot redirect -Force outside the authorized root.
        $physicalRunDir = Get-PhysicalPath $runDir
        $runDirContained = $physicalRunDir.StartsWith($canonicalOutputDir + "/", [System.StringComparison]::OrdinalIgnoreCase)
        if (-not $runDirContained) {
            [Console]::Error.WriteLine("Run directory must remain physically contained under OutputDir before deletion.")
            exit 1
        }
        Remove-Item -LiteralPath $runDir -Recurse -Force
    } else {
        [Console]::Error.WriteLine("Collision error: Directory $runDir already exists. Use -Force to overwrite.")
        exit 1
    }
}
[System.IO.Directory]::CreateDirectory($runDir) | Out-Null

# 3. Create Files & Prepare Stdin Prompt
$promptTempFile = "$runDir/prompt_temp.txt"
if (-not [string]::IsNullOrEmpty($PromptText)) {
    Write-TextNoBom $promptTempFile $PromptText
} else {
    Copy-Item -LiteralPath $canonicalPromptFile -Destination $promptTempFile -Force
}

# Build arguments list for Codex CLI. --search is a base-command flag and must
# precede the exec subcommand for installed CLI versions that reject it later.
$argsList = @()
if ($UseSearch) {
    $argsList += @("--search")
}
$argsList += @("exec")
if ($BenchmarkIsolation) {
    $argsList += @(
        "--ephemeral",
        "--ignore-user-config",
        "--ignore-rules",
        "--strict-config"
    )
}
$argsList += @("-C", $canonicalWorkDir)
$argsList += @("-m", $Model)
$argsList += @("-s", $sandboxLevel)
$argsList += @("-c", "model_reasoning_effort=$ReasoningEffort")
if ($Mode -ne 'FullAccess') {
    # Extend workspace-write so P0 redirects to {{RECEIPTS_DIR}}/ succeed (Windows
    # TMPDIR is usually under %LOCALAPPDATA%\Temp, not C:/Temp).
    $argsList += @("-c", "sandbox_workspace_write.writable_roots=[`"$tempWritableRoot`"]")
}
$finalOutputFileName = if (-not [string]::IsNullOrEmpty($OutputSchema)) { "final.json" } else { "final.md" }
$finalOutputPath = "$runDir/$finalOutputFileName"

# Resolved against this wrapper's own directory, not the working directory: the working
# directory is the tree under review, which for a read-only review is not the tree this
# tool was installed into.
$schemaAdapter = Join-Path $PSScriptRoot "adapt_output_schema.py"
$schemaAdaptError = $null
if (-not [string]::IsNullOrEmpty($OutputSchema)) {
    $apiSchemaPath = $canonicalSchema
    if (-not (Test-Path -LiteralPath $schemaAdapter)) {
        $schemaAdaptError = "schema adapter not found at $schemaAdapter, so the shipped schema was sent unadapted"
    } else {
        $adaptOutput = (& (Get-PythonExe -RepoRoot $canonicalRepoRoot) $schemaAdapter adapt $canonicalSchema "$runDir/api-schema.json" 2>&1) -join " "
        if ($LASTEXITCODE -eq 0) {
            $apiSchemaPath = "$runDir/api-schema.json"
        } else {
            $schemaAdaptError = "schema adaptation failed: $($adaptOutput.Trim())"
        }
    }
    if ($null -ne $schemaAdaptError) {
        # Dispatch with the unmodified schema and SAY SO. The endpoint will reject it with
        # a 400, which is loud and recoverable. What must not happen is a silent fallback:
        # the previous `catch { $apiSchemaPath = $canonicalSchema }` swallowed the reason,
        # so the 400 that followed read as the model's fault rather than this step's.
        [Console]::Error.WriteLine("WARNING: $schemaAdaptError")
    }
    $argsList += @("--output-schema", $apiSchemaPath)
    $argsList += @("-o", $finalOutputPath)
} else {
    $argsList += @("-o", $finalOutputPath)
}
$argsList += @("--json")
# Read prompt from stdin
$argsList += @("-")

# Sanitized argv for metadata
$sanitizedArgs = @()
foreach ($arg in $argsList) {
    $sanitizedArgs += $arg
}

# 4. Process execution
$start = Get-Date
$startUtc = $start.ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")

# Determine the direct launcher based on file extension to avoid Win32 execution failures
$processFilePath = $resolvedExecutable
$processArgsList = $argsList
$ext = [System.IO.Path]::GetExtension($resolvedExecutable)

if ($ext -eq '.ps1') {
    $parentDir = [System.IO.Path]::GetDirectoryName($resolvedExecutable)
    $jsPath = "$parentDir/node_modules/@openai/codex/bin/codex.js"
    if (Test-Path $jsPath) {
        $processFilePath = 'node'
        $processArgsList = @($jsPath) + $argsList
    } else {
        $processFilePath = 'powershell'
        $processArgsList = @('-NoProfile', '-File', $resolvedExecutable) + $argsList
    }
} elseif ($ext -match '^\.(cmd|bat)$') {
    $processFilePath = 'cmd.exe'
    $processArgsList = @('/c', $resolvedExecutable) + $argsList
}

# Escape all arguments for cmd.exe shell execution by double-quoting them and escaping inner quotes
$escapedArgs = @()
foreach ($arg in $processArgsList) {
    $escaped = $arg -replace '"', '\"'
    $escapedArgs += "`"$escaped`""
}
$cmdArgsStr = $escapedArgs -join " "

# Build cmd.exe redirect command line using /s /c and safe concatenation to avoid quote nesting syntax issues
$cmdLine = "/s /c `"`"" + $processFilePath + "`" " + $cmdArgsStr + " < `"" + $promptTempFile + "`" > `"" + $runDir + "/events.jsonl`" 2> `"" + $runDir + "/stderr.txt`"`""

$psi = New-Object System.Diagnostics.ProcessStartInfo
$psi.FileName = "cmd.exe"
$psi.Arguments = $cmdLine
$psi.UseShellExecute = $false
$psi.CreateNoWindow = $true

# Log the command line for debugging
Write-TextNoBom "$runDir/cmd_line.txt" $cmdLine

$proc = [System.Diagnostics.Process]::Start($psi)

# Poll for terminal event or process exit or timeout. $TimeoutSec was resolved next to
# the ledger gate (effort default, then the kind floor) so -GateOnly can report it and a
# review cannot reach this point still holding a 0.
$elapsedSec = 0
$hasTerminalEvent = $false
$sawTerminalBeforeTimeout = $false
$killed = $false
$salvagedAfterTimeout = $false
$eventsFile = "$runDir/events.jsonl"

while ($elapsedSec -lt $TimeoutSec) {
    $proc.Refresh()
    if ($proc.HasExited) {
        break
    }

    Start-Sleep -Seconds 1
    $elapsedSec++

    if (Test-Path $eventsFile) {
        try {
            $lines = Get-Content $eventsFile -ErrorAction SilentlyContinue
            foreach ($line in $lines) {
                if ($line -match '"type"\s*:\s*"(turn\.completed|turn\.failed)"') {
                    $hasTerminalEvent = $true
                    $sawTerminalBeforeTimeout = $true
                    break
                }
            }
        } catch {}
    }

    if ($hasTerminalEvent) {
        # Check if the final output file has also been written and is non-empty
        if (Test-Path $finalOutputPath) {
            if ((Get-Item $finalOutputPath).Length -gt 0) {
                # Allow a small grace period (up to 5 seconds) for natural exit
                $graceSec = 5
                while ($graceSec -gt 0 -and -not $proc.HasExited) {
                    Start-Sleep -Milliseconds 500
                    $graceSec -= 0.5
                    $proc.Refresh()
                }
                break
            }
        }
    }
}

$timedOutWithoutTerminal = (-not $proc.HasExited) -and (-not $sawTerminalBeforeTimeout)

$proc.Refresh()
if (-not $proc.HasExited) {
    # Terminate hanging CLI processes once terminal event is recorded or we time out.
    $killed = $true
    Stop-DispatchProcessTree -Process $proc -NoTreeKill:$NoProcessTreeKill
}

# Late-completion salvage: when we timed out before any terminal event, wait briefly
# for buffered/orphan flush of turn.completed + final.md (historical cmd-only Kill bug).
if ($timedOutWithoutTerminal -and $PostKillGraceSec -gt 0) {
    $graceLeft = $PostKillGraceSec
    while ($graceLeft -gt 0) {
        if (Test-DispatchTerminalAndFinal -EventsPath $eventsFile -FinalPath $finalOutputPath) {
            $salvagedAfterTimeout = $true
            break
        }
        Start-Sleep -Seconds 1
        $graceLeft--
    }
}

$end = Get-Date
$endUtc = $end.ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
$elapsedMs = [math]::Round(($end - $start).TotalMilliseconds)

try {
    $proc.WaitForExit(1000) | Out-Null
} catch {}

$proc.Refresh()
$exitCode = $proc.ExitCode
$exitValue = if ($exitCode -eq $null) { 0 } else { $exitCode }
Remove-Item -Path $promptTempFile -ErrorAction SilentlyContinue

# 5. CLI version already captured in preflight ($cliVersion)

# 6. Parse terminal events and counts
$terminalEventCount = 0
$terminalEventType = ""
$errorSummary = ""
$hasMalformedLine = $false
$eventsFile = "$runDir/events.jsonl"
if (Test-Path $eventsFile) {
    $lines = Get-Content $eventsFile
    foreach ($line in $lines) {
        if ([string]::IsNullOrWhiteSpace($line)) { continue }
        try {
            $evt = $line | ConvertFrom-Json
            if ($evt.type -eq "turn.completed" -or $evt.type -eq "turn.failed") {
                $terminalEventCount++
                $terminalEventType = $evt.type
                if ($evt.type -eq "turn.failed" -and $evt.error) {
                    $errorSummary = $evt.error.message
                }
            }
        } catch {
            $hasMalformedLine = $true
            $errorSummary = "Malformed JSONL event line parsed."
        }
    }
}

# (Token/usage parsing retired 2026-07-21 — token tracking eliminated.)

# Undo the nullable widening the API schema needed (see adapt_output_schema.py) before
# anything validates this file against the unmodified shipped schema. The pre-strip
# document is kept as final.raw.json rather than overwritten: a governance package must
# not rewrite a reviewer's output with no auditable copy of what it actually said.
$nullStripError = $null
if (-not [string]::IsNullOrEmpty($OutputSchema) -and (Test-Path $finalOutputPath)) {
    $stripPython = Get-PythonExe -RepoRoot $canonicalRepoRoot
    if (-not (Test-Path -LiteralPath $schemaAdapter)) {
        $nullStripError = "null-strip skipped: adapter not found at $schemaAdapter"
    } elseif (-not $stripPython) {
        $nullStripError = "null-strip skipped: no python3/python interpreter found"
    } else {
        $stripOutput = (& $stripPython $schemaAdapter strip-nulls $finalOutputPath --raw-copy "$runDir/final.raw.json" 2>&1) -join " "
        if ($LASTEXITCODE -ne 0) {
            # Do not fail the dispatch on this: the model's output is on disk either way,
            # and the post-validation below is the thing that decides whether it is usable.
            # Record what happened so a downstream refusal is traceable to this step.
            $nullStripError = "null-strip of $finalOutputFileName failed: $($stripOutput.Trim())"
        }
    }
}

# Perform structured schema post-validation if OutputSchema is provided
$schemaValidationError = $null
if (-not [string]::IsNullOrEmpty($OutputSchema) -and (Test-Path $finalOutputPath)) {
    try {
        $pythonExe = Get-PythonExe -RepoRoot $canonicalRepoRoot

        # Resolved against the wrapper's own directory, not the working directory. The
        # working directory is the tree under review, which need not be -- and for a
        # read-only review usually is not -- the tree this tool was installed into.
        $validatorScript = Join-Path $PSScriptRoot "validate_json_schema.py"
        if (-not $pythonExe) {
            # Named explicitly rather than left to `& $null` throwing into the catch below:
            # "no interpreter" and "the validator crashed" are different problems with
            # different fixes, and one message for both sends the reader to the wrong one.
            $schemaValidationError = "no python3/python interpreter found, so $finalOutputFileName was NOT validated. This is the absence of a check, not a failed one."
            $exitValue = 3
            $errorSummary = "FAIL-CLOSED: $schemaValidationError"
        } elseif (-not (Test-Path -LiteralPath $validatorScript)) {
            # 3, not 1: the document was never checked. Reporting an unrun check as a
            # validation failure is how a clean output gets blamed for a missing file --
            # the original message was `python: can't open file '.../validate_json_schema.py'`
            # under the heading "JSON Schema validation failed".
            $schemaValidationError = "validator not found at $validatorScript, so $finalOutputFileName was NOT validated. This is the absence of a check, not a failed one."
            $exitValue = 3
            $errorSummary = "FAIL-CLOSED: $schemaValidationError"
        } else {
            $validationOutput = (& $pythonExe $validatorScript $finalOutputPath $canonicalSchema 2>&1) -join "`n"
            $validationExitCode = $LASTEXITCODE

            if ($validationExitCode -ne 0) {
                $schemaValidationError = $validationOutput.Trim()
                # Propagate the validator's own 3 rather than flattening it to 1: it means
                # jsonschema is not installed, which is an environment problem to fix, not
                # a verdict to reject.
                $exitValue = if ($validationExitCode -eq 3) { 3 } else { 1 }
                $errorSummary = if ($validationExitCode -eq 3) {
                    "JSON Schema validation could not run: $schemaValidationError"
                } else {
                    "JSON Schema validation failed: $schemaValidationError"
                }
            }
        }
    } catch {
        $schemaValidationError = "Failed to run Python schema validation: $_"
        $exitValue = 3
        $errorSummary = "JSON Schema validation could not run: $schemaValidationError"
    }
}

# 8. Retention handling
# Output file name and path are already defined above

# Salvage: timed out with no terminal yet, then turn.completed + final.md arrived
# during post-kill grace. Do not salvage hung-after-completed kills (existing contract).
$lateCompletionOk = (
    $salvagedAfterTimeout -and
    $terminalEventCount -eq 1 -and
    $terminalEventType -eq "turn.completed" -and
    -not $hasMalformedLine -and
    [string]::IsNullOrEmpty($schemaValidationError) -and
    (Test-Path -LiteralPath $finalOutputPath) -and
    ((Get-Item -LiteralPath $finalOutputPath).Length -gt 0)
)

$isSuccess = (
    (
        (-not $killed -and $exitValue -eq 0) -or
        $lateCompletionOk
    ) -and
    $terminalEventCount -eq 1 -and
    $terminalEventType -eq "turn.completed" -and
    -not $hasMalformedLine -and
    [string]::IsNullOrEmpty($schemaValidationError)
)
$wrapperExitCode = if ($isSuccess) { 0 } else { if ($exitValue -ne 0) { $exitValue } else { 3 } }

if ($isSuccess -and $lateCompletionOk) {
    $errorSummary = ""
} elseif (-not $isSuccess -and [string]::IsNullOrEmpty($errorSummary)) {
    $errorSummary = "Terminal event validation failed (Count: $terminalEventCount, Type: $terminalEventType)"
}

function Compress-GzipFile {
    param([string]$src, [string]$dest)
    $srcFile = [System.IO.File]::OpenRead($src)
    $destFile = [System.IO.File]::Create($dest)
    $gzip = New-Object System.IO.Compression.GZipStream($destFile, [System.IO.Compression.CompressionMode]::Compress)
    $srcFile.CopyTo($gzip)
    $gzip.Close()
    $destFile.Close()
    $srcFile.Close()
}

if ($isSuccess) {
    if ($Retention -eq 'CompressOnSuccess') {
        if (Test-Path $eventsFile) {
            Compress-GzipFile $eventsFile "$eventsFile.gz"
            Remove-Item -Path $eventsFile -Force
        }
    } elseif ($Retention -eq 'DeleteOnSuccess') {
        Remove-Item -Path $eventsFile -ErrorAction SilentlyContinue
        Remove-Item -Path "$runDir/stderr.txt" -ErrorAction SilentlyContinue
    }
}

# 9. Get sizes
$artifactSizes = @{}
if (Test-Path $finalOutputPath) { $artifactSizes[$finalOutputFileName] = (Get-Item $finalOutputPath).Length }
if (Test-Path "$eventsFile.gz") { $artifactSizes["events.jsonl.gz"] = (Get-Item "$eventsFile.gz").Length }
if (Test-Path $eventsFile) { $artifactSizes["events.jsonl"] = (Get-Item $eventsFile).Length }
if (Test-Path "$runDir/stderr.txt") { $artifactSizes["stderr.txt"] = (Get-Item "$runDir/stderr.txt").Length }

# Build status manifest
$wrapperSha256 = Get-Sha256File -Path $PSCommandPath
$outputSchemaSha256 = if (
    -not [string]::IsNullOrWhiteSpace($canonicalSchema) -and
    (Test-Path -LiteralPath $canonicalSchema -PathType Leaf)
) {
    Get-Sha256File -Path $canonicalSchema
} else {
    $null
}
$workingAgentsPath = Join-Path $canonicalWorkDir "AGENTS.md"
$workingAgentsSha256 = if (Test-Path -LiteralPath $workingAgentsPath -PathType Leaf) {
    Get-Sha256File -Path $workingAgentsPath
} else {
    $null
}
$statusManifest = [ordered]@{
    schema_version = "dispatch-status.v1"
    dispatch_id = $DispatchId
    # `model` keeps recording the concrete slug: a receipt has to stay readable
    # years later without a registry lookup. The fields below record *how* that
    # slug was chosen, so a past dispatch can still be explained after the
    # registry has moved on.
    model = $Model
    model_class = $modelClassApplied
    author_vendor = if ([string]::IsNullOrWhiteSpace($AuthorVendor)) { $null } else { $AuthorVendor }
    registry_version = $registryVersion
    registry_sha256 = $registrySha256
    overlay_sha256 = $overlaySha256
    # Which project's policy governed the resolution. Without the path a reader
    # cannot tell a dispatch bound by this repo's overlay from one bound only by
    # whatever the global registry said that day.
    overlay_path = $overlayPath
    resolution = $modelResolution
    effort_clamped = $effortClamped
    # The review-loop bound, recorded so a bypass leaves a trace. `bypassed-non-review`
    # in a receipt whose prompt was plainly a review is the audit signal.
    loop_id = if ([string]::IsNullOrWhiteSpace($LoopId)) { $null } else { $LoopId }
    ledger_gate = $ledgerGateResult
    # The kind the ledger recorded for this loop, not the flag the caller typed, plus
    # whether it moved the timeout. A truncated execution review whose receipt says
    # `timeout_floor_applied: false` is a wrapper/ledger pairing problem; one that says
    # true is a genuinely long review.
    dispatch_kind = $dispatchKind
    timeout_floor_applied = [bool]$timeoutFloorApplied
    mode = $Mode
    sandbox = $sandboxLevel
    reasoning_effort = $ReasoningEffort
    retention = $Retention
    output_paths = @{
        final_output = $finalOutputPath
    }
    sanitized_argv = $sanitizedArgs
    start_utc = $startUtc
    end_utc = $endUtc
    elapsed_ms = $elapsedMs
    timeout_sec = $TimeoutSec
    post_kill_grace_sec = $PostKillGraceSec
    process_tree_kill = (-not [bool]$NoProcessTreeKill)
    salvaged_after_timeout = [bool]$salvagedAfterTimeout
    cli_version = $cliVersion
    exit_code = $wrapperExitCode
    child_exit_code = $exitCode
    artifact_sizes = $artifactSizes
    terminal_event_count = $terminalEventCount
    terminal_event_type = $terminalEventType
    error_summary = $errorSummary
    # Null-strip outcome. Recorded even on success (as $null) so its absence from an old
    # status.json is distinguishable from "it ran and had nothing to say".
    null_strip_error = $nullStripError
    null_strip_raw_kept = (Test-Path -LiteralPath "$runDir/final.raw.json")
    # Non-null means the schema handed to the endpoint was NOT the adapted one, which is
    # the difference between a 400 this wrapper caused and one the model's answer caused.
    schema_adapt_error = $schemaAdaptError
    benchmark_isolation = [bool]$BenchmarkIsolation
    benchmark_context_receipt = if ($BenchmarkIsolation) { $benchmarkContextCanonical } else { $null }
    benchmark_context_sha256 = if ($BenchmarkIsolation) { $BenchmarkContextSha256 } else { $null }
    wrapper_sha256 = $wrapperSha256
    output_schema_sha256 = $outputSchemaSha256
    working_directory_agents_sha256 = $workingAgentsSha256
    working_directory = $canonicalWorkDir
    sanitized_environment = [ordered]@{
        effective_codex_home = if ([string]::IsNullOrWhiteSpace($env:CODEX_HOME)) {
            [System.IO.Path]::GetFullPath((Join-Path $HOME ".codex")).Replace('\', '/')
        } else {
            [System.IO.Path]::GetFullPath($env:CODEX_HOME).Replace('\', '/')
        }
        allowlisted_keys = @("CODEX_HOME", "HOME", "PATH", "USERPROFILE")
    }
}

if ($Mode -eq 'FullAccess') {
    $len = $FullAccessJustification.Length
    $bucket = if ($len -le 79) { "20-79" } elseif ($len -le 199) { "80-199" } else { "200-plus" }
    $statusManifest["full_access_justification_supplied"] = $true
    $statusManifest["full_access_justification_redacted"] = "[REDACTED]"
    $statusManifest["full_access_justification_length_bucket"] = $bucket
}

$statusFile = "$runDir/status.json"
$statusTmp = "$statusFile.tmp"
$statusJson = $statusManifest | ConvertTo-Json -Depth 4
Write-TextNoBom $statusTmp $statusJson
if (Test-Path $statusTmp) {
    Move-Item -Path $statusTmp -Destination $statusFile -Force
}

# Write receipt.txt
$receiptText = @"
Dispatch ID: $DispatchId
Model: $Model
Mode: $Mode
Sandbox: $sandboxLevel
Exit Code: $wrapperExitCode
Child Exit Code: $exitCode
Start: $startUtc
End: $endUtc
Elapsed: $elapsedMs ms
CLI Version: $cliVersion
"@
Write-TextNoBom "$runDir/receipt.txt" $receiptText

# 10. Propagate exit code
exit $wrapperExitCode
