<#
.SYNOPSIS
    Run a headless `claude -p` dispatch billed to the Console API key's credits.

.DESCRIPTION
    A thin front end over tools/Invoke-ClaudeDispatch.ps1. It passes -ApiKeyFile,
    so the child `claude` process gets the Console key as ANTHROPIC_API_KEY. The
    global login (cswap slot, ~/.claude/.credentials.json) is untouched, so other
    Claude Code sessions keep their subscription. Every run is an ordinary
    dispatch under {{RECEIPTS_DIR}}/dispatch/<id>/ (status.json, running.json,
    final.md, output.json), so tools/Get-ClaudeDispatch.ps1 lists it, peeks at a
    live session and prints its output.

    Anthropic bills `claude -p` run yourself with a Console key as Agent SDK usage,
    which the promotional / Max monthly API credits cover. Runs started from inside
    a Claude Code session (IDE extension, desktop app, interactive CLI) are billed
    as Claude Code and are NOT covered; the API answers "Credit balance is too low".
    This script does not alter CLAUDE_CODE_ENTRYPOINT. Inside a Claude Code session
    it exits 3 before spending a request and prints the command to run in a terminal.
    -ValidateOnly is the exception: it starts no process and spends nothing, so an
    agent can check a hand-over command from inside its own session.

    A -Resume, -Fork or -Continue with no -PermissionMode keeps the mode of the
    source run. A source with no recorded mode is refused (permission_mode_unknown).

    -RunId (with -SessionId) turns on messaging for a manual run (report section 7.2).
    The wrapper creates the kill-on-close job Local\{{PROJECT_NAME_UPPER}}Credits-seg-<run id>,
    stores a minimal run and its segment in the credits store (register_minimal),
    creates the CLI suspended inside the job, stores the child's identity
    (manual_identity), and resumes it with CREDITS_RUN_ID, CREDITS_STATE_DB and
    CREDITS_SEGMENT. When the CLI ends, the wrapper calls complete_segment. If the
    wrapper dies first, the job closes and Windows ends the CLI. When the job or the
    store is not available, the run goes on with messaging off: no CREDITS_* name
    and no store row.

    Exit codes: 0 ok, 2 bad arguments, brief or key file, 3 launched inside a Claude
    Code session, otherwise the dispatch wrapper's exit code.

.EXAMPLE
    pwsh -File .agent/skills/claude-credits/Invoke-ClaudeCredits.ps1 -PromptText "Summarize the open TODOs in packages/core"

.EXAMPLE
    pwsh -File .agent/skills/claude-credits/Invoke-ClaudeCredits.ps1 -Continue -PromptText "Now list the three riskiest ones"

.EXAMPLE
    pwsh -File .agent/skills/claude-credits/Invoke-ClaudeCredits.ps1 -PromptFile {{RECEIPTS_DIR}}/credits/task.md -PermissionMode acceptEdits -WorkingDirectory {{PROJECT_ROOT}} -MaxBudgetUsd 5
#>
[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [string]$PromptText,

    # Sent on stdin, so long prompts avoid the Windows command-line length limit.
    [string]$PromptFile,

    # Default: $env:CLAUDE_CREDITS_KEY_FILE, else ~/.anthropic/claude-credits.key
    [string]$KeyFile,

    # Registry class the snapshot is checked against. architect (Fable) only on
    # explicit human direction; it has no claude-p binding yet, so the check refuses it.
    [ValidateSet('isolated_worker', 'architect')]
    [string]$ModelClass = 'isolated_worker',

    # Snapshot id; checked against the model registry for -ModelClass. When it is not
    # given, the dispatch wrapper uses the registry default for the class.
    [string]$Model,

    [ValidateSet('low', 'medium', 'high', 'xhigh', 'max')]
    [string]$Effort = 'high',

    # `plan` is read-only. Pass acceptEdits when the run should change files.
    # Default: `plan` for a fresh session, the source run's mode for a continuation.
    [ValidateSet('plan', 'acceptEdits', 'dontAsk', 'bypassPermissions')]
    [string]$PermissionMode = 'plan',

    # The CLI ends the run when it reaches this spend. 0 = no cap.
    [ValidateRange(0, 1000)]
    [double]$MaxBudgetUsd = 2,

    # Tools allowed without a prompt (a headless run denies prompts), e.g.
    # WebSearch,WebFetch. Passed to the wrapper's -AllowedTools.
    [string[]]$AllowedTools,

    # Where a fresh session runs. Default: the current directory. A resumed or
    # forked session runs where its source ran.
    [string]$WorkingDirectory,

    # Name for the run directory. Default: credits-<timestamp>.
    [string]$DispatchId,

    # Continue the session of an earlier dispatch with a new prompt.
    [string]$Resume,

    # Branch a new session from an earlier dispatch; the source is left as is.
    [string]$Fork,

    # Continue the newest dispatch this script started.
    [switch]$Continue,

    # 0 = the wrapper's effort-based default.
    [ValidateRange(0, 86400)]
    [int]$TimeoutSec = 0,

    [string]$OutputDir = '{{RECEIPTS_DIR}}/dispatch',

    # Tests point this at a mock CLI.
    [string]$ClaudeExecutable = 'claude',

    # What the segment is, recorded as status.json `kind`.
    [ValidateSet('plan', 'exec')]
    [string]$Kind,

    # The id for a new session (lowercase UUID), passed as --session-id. Not with
    # -Resume or -Continue, which keep the source session.
    [ValidatePattern('(?-i)^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\z')]
    [string]$SessionId,

    # A new run id for a manual run with messaging. Needs -SessionId: the inbox hook
    # delivers only to the segment's expected session.
    [ValidatePattern('^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$')]
    [string]$RunId,

    # The credits store for -RunId. Default: credits/state.db next to the -OutputDir folder.
    [string]$StateDb,

    # Set by Start-CreditsRun.ps1 (report section 4.3), which runs this script inside the job of
    # a scheduled segment. The CLI gets CREDITS_RUN_ID, CREDITS_STATE_DB and CREDITS_SEGMENT
    # from this process's environment; the launcher, not this script, finalizes the segment.
    [switch]$Scheduled,

    # Check the arguments, the brief, the key file (presence and ACL; its contents
    # are not read) and any continuation source, print dispatch_args_ok and exit 0. Starts no process and writes no run
    # directory. Allowed inside a Claude Code session.
    [switch]$ValidateOnly
)

$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '../../..')).Path
$wrapper = Join-Path $repoRoot 'tools/Invoke-ClaudeDispatch.ps1'

function Fail([int]$Code, [string]$Message) {
    [Console]::Error.WriteLine("claude-credits: $Message")
    exit $Code
}

function Read-Status([string]$Id) {
    $path = Join-Path (Join-Path $OutputDir $Id) 'status.json'
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { return $null }
    try { return [System.IO.File]::ReadAllText($path, [System.Text.Encoding]::UTF8) | ConvertFrom-Json } catch { return $null }
}

# --- Refuse to run inside a Claude Code session (billed as Claude Code, not covered).
# -ValidateOnly starts no process, so it is billed nothing and may run there.
if (-not $ValidateOnly -and ($env:CLAUDECODE -eq '1' -or $env:CLAUDE_CODE_ENTRYPOINT)) {
    $hint = 'pwsh -File .agent/skills/claude-credits/Invoke-ClaudeCredits.ps1'
    if ($Resume) { $hint += " -Resume $Resume" }
    if ($Fork) { $hint += " -Fork $Fork" }
    if ($Continue) { $hint += ' -Continue' }
    if ($PromptFile) { $hint += " -PromptFile `"$PromptFile`"" } else { $hint += ' -PromptText "<prompt>"' }
    if ($ModelClass -ne 'isolated_worker') { $hint += " -ModelClass $ModelClass" }
    if ($PSBoundParameters.ContainsKey('Model')) { $hint += " -Model $Model" }
    if ($Effort -ne 'high') { $hint += " -Effort $Effort" }
    if ($PSBoundParameters.ContainsKey('PermissionMode')) { $hint += " -PermissionMode $PermissionMode" }
    if ($Kind) { $hint += " -Kind $Kind" }
    if ($SessionId) { $hint += " -SessionId $SessionId" }
    if ($RunId) { $hint += " -RunId $RunId" }
    if ($StateDb) { $hint += " -StateDb `"$StateDb`"" }
    if ($Scheduled) { $hint += ' -Scheduled' }
    if ($WorkingDirectory) { $hint += " -WorkingDirectory `"$WorkingDirectory`"" }
    if ($AllowedTools) { $hint += " -AllowedTools $($AllowedTools -join ',')" }
    Fail 3 ("launched inside a Claude Code session (entrypoint '$($env:CLAUDE_CODE_ENTRYPOINT)'). " +
        "Anthropic bills that as Claude Code, which the API credits do not cover. " +
        "Run it from your own terminal instead:`n  $hint")
}

# --- Arguments
if ($PromptText -and $PromptFile) { Fail 2 'pass -PromptText or -PromptFile, not both.' }
if (-not $PromptText -and -not $PromptFile) { Fail 2 'no prompt. Pass -PromptText or -PromptFile.' }
if (@(@($Resume, $Fork) | Where-Object { $_ }).Count + [int][bool]$Continue -gt 1) {
    Fail 2 'pass at most one of -Resume, -Fork, -Continue.'
}
if ($SessionId -and ($Resume -or $Continue)) {
    Fail 2 '-SessionId names a new session; -Resume and -Continue keep the source session.'
}
if ($RunId -and -not $SessionId) {
    Fail 2 '-RunId needs -SessionId: messages are delivered only to the expected session.'
}
if ($StateDb -and -not $RunId) { Fail 2 '-StateDb is used only with -RunId.' }
if ($Scheduled -and $RunId) { Fail 2 '-Scheduled and -RunId are two kinds of run; pass one.' }
$scheduledEnv = $null
if ($Scheduled -and -not $ValidateOnly) {
    $scheduledEnv = [ordered]@{}
    foreach ($name in @('CREDITS_RUN_ID', 'CREDITS_STATE_DB', 'CREDITS_SEGMENT')) {
        $value = [Environment]::GetEnvironmentVariable($name)
        if ([string]::IsNullOrEmpty($value)) { Fail 2 "-Scheduled needs $name in the environment (Start-CreditsRun.ps1 sets it)." }
        $scheduledEnv[$name] = $value
    }
    # The base commit B is optional: only a run with a bound base has it (report section 4.3 step 4).
    $baseCommit = [Environment]::GetEnvironmentVariable('CREDITS_BASE_COMMIT')
    if (-not [string]::IsNullOrEmpty($baseCommit)) { $scheduledEnv['CREDITS_BASE_COMMIT'] = $baseCommit }
}
if ($PromptFile -and -not (Test-Path -LiteralPath $PromptFile -PathType Leaf)) {
    Fail 2 "brief not found: $PromptFile"
}

if ($Continue) {
    # The newest finished dispatch that ran on a key file.
    if (Test-Path -LiteralPath $OutputDir -PathType Container) {
        $Resume = Get-ChildItem -LiteralPath $OutputDir -Directory |
            Sort-Object LastWriteTime -Descending |
            Where-Object { $s = Read-Status $_.Name; $s -and $s.cli -eq 'claude' -and $s.auth_mode -eq 'api_key_file' } |
            Select-Object -First 1 -ExpandProperty Name
    }
    if (-not $Resume) { Fail 2 "no earlier API-key dispatch in $OutputDir to continue." }
    [Console]::Error.WriteLine("claude-credits: continuing $Resume")
}

$source = if ($Resume) { $Resume } elseif ($Fork) { $Fork } else { $null }
if ($source) {
    $sourceStatus = Read-Status $source
    if ($null -eq $sourceStatus) { Fail 2 "no finished dispatch '$source' in $OutputDir (see Get-ClaudeDispatch.ps1)." }
    if (-not $WorkingDirectory) { $WorkingDirectory = $sourceStatus.working_directory }
    # A continuation keeps the source mode: a resumed exec run must not drop
    # back to the read-only `plan` default.
    if (-not $PSBoundParameters.ContainsKey('PermissionMode')) {
        $sourceMode = $null
        $modeProp = $sourceStatus.PSObject.Properties['permission_mode']
        if ($null -ne $modeProp) { $sourceMode = [string]$modeProp.Value }
        if ($sourceMode -notin @('plan', 'acceptEdits', 'dontAsk', 'bypassPermissions')) {
            Fail 2 ("permission_mode_unknown: dispatch '$source' records no permission mode. " +
                "Pass -PermissionMode to continue it.")
        }
        $PermissionMode = $sourceMode
    }
}
if (-not $WorkingDirectory) { $WorkingDirectory = (Get-Location).Path }

if (-not $KeyFile) {
    $KeyFile = if ($env:CLAUDE_CREDITS_KEY_FILE) { $env:CLAUDE_CREDITS_KEY_FILE }
               else { Join-Path $HOME '.anthropic/claude-credits.key' }
}
if (-not (Test-Path -LiteralPath $KeyFile -PathType Leaf)) {
    Fail 2 "key file not found: $KeyFile (see .agent/skills/claude-credits/SKILL.md, Setup)."
}
# Open for read and close at once: proves the ACL lets this user read the key
# without reading or printing it.
try {
    [System.IO.File]::Open((Resolve-Path -LiteralPath $KeyFile).ProviderPath, 'Open', 'Read', 'ReadWrite').Dispose()
} catch {
    Fail 2 "key file not readable: $KeyFile ($($_.Exception.GetType().Name))."
}

if (-not $DispatchId) {
    $DispatchId = 'credits-' + (Get-Date -Format 'yyyyMMdd-HHmmss')
}

$dispatchArgs = @{
    ModelClass       = $ModelClass
    AuthorVendor     = 'anthropic'
    ReasoningEffort  = $Effort
    PermissionMode   = $PermissionMode
    WorkingDirectory = $WorkingDirectory
    DispatchId       = $DispatchId
    OutputDir        = $OutputDir
    ApiKeyFile       = $KeyFile
    ClaudeExecutable = $ClaudeExecutable
}
if ($Model) { $dispatchArgs.Model = $Model }
if ($PromptFile) { $dispatchArgs.PromptFile = $PromptFile } else { $dispatchArgs.PromptText = $PromptText }
if ($MaxBudgetUsd -gt 0) { $dispatchArgs.MaxBudgetUsd = $MaxBudgetUsd }
if ($AllowedTools) { $dispatchArgs.AllowedTools = $AllowedTools }
if ($TimeoutSec -gt 0) { $dispatchArgs.TimeoutSec = $TimeoutSec }
if ($Resume) { $dispatchArgs.ResumeDispatchId = $Resume }
if ($Fork) { $dispatchArgs.ForkDispatchId = $Fork }
if ($Kind) { $dispatchArgs.Kind = $Kind }
if ($SessionId) { $dispatchArgs.SessionId = $SessionId }

if ($ValidateOnly) {
    # AC-A.7: presence and ACL only. The wrapper does not read the key; a launch does.
    $dispatchArgs.ValidateOnly = $true
    $dispatchArgs.KeyFileMetadataOnly = $true
    & $wrapper @dispatchArgs
    exit $LASTEXITCODE
}

# --- Messaging for a manual run (report section 7.2 steps 1 to 5)
$credits = $null
if ($RunId) {
    if (-not $StateDb) { $StateDb = Join-Path (Split-Path -Parent $OutputDir) 'credits/state.db' }
    $StateDb = [System.IO.Path]::GetFullPath($StateDb)
    $segmentId = "seg-$RunId"
    $job = $null
    try {
        Import-Module -Name (Join-Path $PSScriptRoot 'CreditsRun.psm1') -Force -DisableNameChecking -ErrorAction Stop
        # Test seam: CREDITS_TEST_JOB_FAIL=1 stands for a host that refuses the job (for
        # example a parent job that forbids nested jobs).
        if ($env:CREDITS_TEST_JOB_FAIL -eq '1') { throw 'the job was refused (CREDITS_TEST_JOB_FAIL=1)' }
        $job = New-CreditsJob -SegmentId $segmentId
        $bootId = Get-CreditsBootId
    } catch {
        if ($null -ne $job) { Close-CreditsJob -Job $job; $job = $null }
        [Console]::Error.WriteLine("claude-credits: messaging off for run ${RunId}: no job ($($_.Exception.Message)). The run goes on with no CREDITS_* variable and no store row.")
    }
    if ($null -ne $job) {
        $storeError = $null
        $refused = $false
        try {
            New-Item -ItemType Directory -Force -Path (Split-Path -Parent $StateDb) | Out-Null
            $res = Invoke-CreditsState -StateDb $StateDb -Verb init
            if ($res.Code -eq 0) {
                $res = Invoke-CreditsState -StateDb $StateDb -Verb register_minimal -Arguments @(
                    '--run-id', $RunId, '--segment-id', $segmentId,
                    '--wrapper-pid', [string]$PID, '--wrapper-created', (Format-CreditsUtc (Get-Process -Id $PID).StartTime),
                    '--boot-id', $bootId, '--win-session', [string][System.Diagnostics.Process]::GetCurrentProcess().SessionId,
                    '--job-name', $job.Name, '--expected-session-id', $SessionId, '--dispatch-id', $DispatchId)
            }
            if ($res.Code -ne 0) {
                $storeError = "$($res.Out) $($res.Err)".Trim()
                $refused = $res.Code -eq 3
            }
        } catch {
            $storeError = $_.Exception.Message
        }
        if ($null -ne $storeError) {
            Close-CreditsJob -Job $job
            # A refusal (the run id or the segment exists) is an argument error; any other
            # store failure leaves the run without messaging.
            if ($refused) { Fail 2 "run $RunId was not registered: $storeError" }
            [Console]::Error.WriteLine("claude-credits: messaging off for run ${RunId}: the store failed ($storeError). The run goes on with no CREDITS_* variable and no store row.")
        } else {
            $credits = @{ Job = $job; RunId = $RunId; StateDb = $StateDb; SegmentId = $segmentId; Resumed = $false }
            # The closure keeps the command and the context, so the hook works from the
            # dispatch script's scope.
            $creditsContext = $credits
            $startChild = Get-Command -Name Start-CreditsManualChild -CommandType Function
            $dispatchArgs.LaunchHook = { param($StartInfo) & $startChild -StartInfo $StartInfo -Context $creditsContext }.GetNewClosure()
            [Console]::Error.WriteLine("claude-credits: messaging on: run $RunId, segment $segmentId, store $StateDb")
        }
    }
}

# --- A scheduled segment (report section 4.3 step 7). This process is in the segment's job, so
# the CLI is too. The dispatch wrapper removes every CREDITS_* name from the CLI environment; the
# hook puts back the three that turn on the inbox hook (section 4.6), and CREDITS_BASE_COMMIT when
# the segment has a bound base.
if ($null -ne $scheduledEnv) {
    $scheduledContext = $scheduledEnv
    $dispatchArgs.LaunchHook = {
        param($StartInfo)
        foreach ($name in $scheduledContext.Keys) { $StartInfo.Environment[$name] = $scheduledContext[$name] }
        [System.Diagnostics.Process]::Start($StartInfo)
    }.GetNewClosure()
    [Console]::Error.WriteLine("claude-credits: scheduled segment $($scheduledEnv['CREDITS_SEGMENT']) of run $($scheduledEnv['CREDITS_RUN_ID'])")
}

[Console]::Error.WriteLine("claude-credits: dispatch $DispatchId started; check on it from another terminal with")
[Console]::Error.WriteLine("  pwsh -File tools/Get-ClaudeDispatch.ps1 $DispatchId -Peek")

& $wrapper @dispatchArgs
$exitCode = $LASTEXITCODE

# The wrapper is silent on success; show the result and the bookkeeping.
$status = Read-Status $DispatchId

# Finalize the manual segment once, then close the job (kill on close ends any process the CLI
# left behind). A failed call leaves the segment to the monitor, which finalizes it on the job proof.
if ($null -ne $credits) {
    $class = if (-not $credits.Resumed) { 'launch_failed' }
             elseif ($null -eq $status) { 'crashed' }
             elseif ($status.PSObject.Properties['timed_out'] -and $status.timed_out) { 'timeout' }
             else { 'exited' }
    $completeArgs = @{ StateDb = $credits.StateDb; SegmentId = $credits.SegmentId; FinalizedBy = 'wrapper'; Class = $class; ExitCode = $exitCode }
    if ($null -ne $status -and $status.PSObject.Properties['total_cost_usd'] -and $null -ne $status.total_cost_usd) {
        $completeArgs.SessionTotalUsd = [double]$status.total_cost_usd
    }
    try {
        $null = Complete-CreditsSegment @completeArgs
    } catch {
        [Console]::Error.WriteLine("claude-credits: complete_segment failed; the monitor finalizes the segment: $($_.Exception.Message)")
    }
    Close-CreditsJob -Job $credits.Job
}
if ($null -eq $status) { exit $exitCode }
$final = Join-Path (Join-Path $OutputDir $DispatchId) 'final.md'
if (Test-Path -LiteralPath $final -PathType Leaf) {
    [System.IO.File]::ReadAllText($final, [System.Text.Encoding]::UTF8).TrimEnd()
}
$cost = if ($null -ne $status.total_cost_usd) { '{0:N4}' -f [double]$status.total_cost_usd } else { '?' }
[Console]::Error.WriteLine("claude-credits: dispatch $DispatchId | cost `$$cost | $([math]::Round($status.elapsed_ms / 1000))s | session $($status.session_id)")
if ($status.error_summary) { [Console]::Error.WriteLine("claude-credits: $($status.error_summary)") }
[Console]::Error.WriteLine("claude-credits: follow up with -Continue (or -Resume $DispatchId) -PromptText `"...`"")
exit $exitCode
