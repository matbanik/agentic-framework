<#
.SYNOPSIS
    Check a credits run, or settle a crash exposure in the credits store.

.DESCRIPTION
    The agent's check command for credits runs (report section 4.5). The check is read only: the
    store opens with mode=ro, so the store file and its transitions stay the same.

    With no run id: one line per run (state, class, segments, spend, heartbeat age, pending
    messages). With a run id: the full view of that run (segments with their dispatch signals,
    requests, attempts, messages and their deliveries, the open gate, exposures, cost, the
    task.md stop gate and open rows, the final status, and the resume readiness).

    -Export also writes the JSON view of the run to <store folder>/runs/<run-id>/view.json.

    A resume is never started here. It starts only through Start-CreditsRunTask.ps1 -Resume
    (report section 5.3).

    -RunId <run> -AttachSession <session> -UserMessageUuid <uuid> adds an IDE session to the
    run's orchestrator sessions (report sections 4.5 and 4.6.3). The human types
    `attach <run id>` in that session, and the agent passes the session id and the uuid of that
    entry. The store finds the transcript from the manifest's project root and the session id
    (never from a path argument), checks the whole parent chain from the first record and writes
    the first mark, checks the entry (a typed human turn, not from the queue, later than the
    run's registration and its last attach), needs `attach <run id>` in its text, and uses the
    uuid and the promptId once. Rulings of that session count only from entries after the
    attach. It prints the store's JSON line: exit 0 with result changed, or exit 3 with the
    reason in `error`.

    -Settle <segment> closes the open crash exposure of one segment (report section 4.1):
      -Source console -AmountUsd <n>                 the cost read from the Console usage page;
      -Source human -AmountUsd <n> -Note "<text>"    a human adjustment, with the reason.
    The transcript sum is a lower bound and never settles an exposure (transcript_not_evidence).
    The agent runs -Settle only when the human asks for it, and passes the human's words as
    -StartedBy agent-on-user-chat -Quote "<words>". The store records the source, the OS user
    and, for an agent, the quote.

    -RunId <successor> -AcceptDrift <predecessor> -Quote "<words>" records the human's acceptance
    of the predecessor's drift (report sections 4.5 and 5.4; MX-15). The store resolves the
    successor project's HEAD once to the commit B and writes one drift_accepts row with B, the
    drifted paths and the words. It replaces only the blob comparison of the committed predicate
    at B; the clean-path check stays. The words are needed: no -Quote is a usage error. No drift
    at B is refused no_drift. The same acceptance again is no_change. It prints the store's JSON
    line.

    Exit codes: the store's codes. 0 ok (also no_change), 1 check failed, 2 usage (also: no store
    file, -Export with no run id, or -AcceptDrift with no -Quote), 3 refused (the error names the
    reason, for example unknown_run, no_exposure, no_drift, session_not_listed or
    transcript_discontinuity), 9 crash, 75 busy.

.EXAMPLE
    pwsh -File .agent/skills/claude-credits/Get-CreditsRun.ps1

.EXAMPLE
    pwsh -File .agent/skills/claude-credits/Get-CreditsRun.ps1 my-plan-exec -Export

.EXAMPLE
    pwsh -File .agent/skills/claude-credits/Get-CreditsRun.ps1 -Settle seg-my-plan-exec -Source console -AmountUsd 3.5

.EXAMPLE
    pwsh -File .agent/skills/claude-credits/Get-CreditsRun.ps1 -RunId next-plan-exec -AcceptDrift my-plan-exec -Quote "keep the old a.py"

.EXAMPLE
    pwsh -File .agent/skills/claude-credits/Get-CreditsRun.ps1 -RunId it8-16-exec -AttachSession <session id> -UserMessageUuid <uuid of the "attach it8-16-exec" entry>
#>
[CmdletBinding(DefaultParameterSetName = 'View')]
param(
    # The run to show in full. Omitted: one line per run. With -AcceptDrift: the successor.
    [Parameter(ParameterSetName = 'View', Position = 0)]
    [Parameter(Mandatory = $true, ParameterSetName = 'AcceptDrift', Position = 0)]
    [Parameter(Mandatory = $true, ParameterSetName = 'Attach', Position = 0)]
    [ValidatePattern('^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$')]
    [string]$RunId,

    # Also write the JSON view to <store folder>/runs/<run-id>/view.json. Needs a run id.
    [Parameter(ParameterSetName = 'View')]
    [switch]$Export,

    # The dispatch folder of the launcher (Start-CreditsRun.ps1 -OutputDir default), where each
    # segment's status.json and final.md are read.
    [string]$OutputDir = '{{RECEIPTS_DIR}}/dispatch',

    # The credits store. Default: the store of Invoke-ClaudeCredits.ps1 -RunId with its default -OutputDir.
    [string]$StateDb = '{{RECEIPTS_DIR}}/credits/state.db',

    # The segment whose open exposure to settle.
    [Parameter(Mandatory = $true, ParameterSetName = 'Settle')]
    [ValidatePattern('^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$')]
    [string]$Settle,

    # console, human or transcript. The store refuses transcript with its own reason, so the
    # value is not limited here.
    [Parameter(Mandatory = $true, ParameterSetName = 'Settle')]
    [string]$Source,

    [Parameter(Mandatory = $true, ParameterSetName = 'Settle')]
    [ValidateRange(0, 1000000)]
    [double]$AmountUsd,

    [Parameter(ParameterSetName = 'Settle')]
    [string]$Note,

    [Parameter(ParameterSetName = 'Settle')]
    [ValidateSet('human-command', 'agent-on-user-chat')]
    [string]$StartedBy = 'human-command',

    # The human's words: for -Settle when an agent settles for them (-StartedBy
    # agent-on-user-chat); for -AcceptDrift always.
    [Parameter(ParameterSetName = 'Settle')]
    [Parameter(ParameterSetName = 'AcceptDrift')]
    [string]$Quote,

    # The predecessor whose drift the human accepts for -RunId (the successor).
    [Parameter(Mandatory = $true, ParameterSetName = 'AcceptDrift')]
    [ValidatePattern('^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$')]
    [string]$AcceptDrift,

    # The IDE session to add to the run's orchestrator sessions (report section 4.5).
    [Parameter(Mandatory = $true, ParameterSetName = 'Attach')]
    [ValidatePattern('^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$')]
    [string]$AttachSession,

    # The uuid of the typed `attach <run id>` entry in that session's transcript.
    [Parameter(Mandatory = $true, ParameterSetName = 'Attach')]
    [ValidatePattern('^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$')]
    [string]$UserMessageUuid
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

Import-Module -Name (Join-Path $PSScriptRoot 'CreditsRun.psm1') -Force -DisableNameChecking

$Invariant = [System.Globalization.CultureInfo]::InvariantCulture

# A property of a parsed JSON object, or $null when it is missing (StrictMode-safe).
function Get-Field($Object, [string]$Name) {
    if ($null -eq $Object) { return $null }
    $prop = $Object.PSObject.Properties[$Name]
    if ($null -eq $prop) { return $null }
    $prop.Value
}

function Format-Text($Value) {
    if ($null -eq $Value -or "$Value" -eq '') { return '-' }
    if ($Value -is [bool]) { return $(if ($Value) { 'yes' } else { 'no' }) }
    "$Value"
}

function Format-Usd($Value) {
    if ($null -eq $Value) { return '-' }
    '$' + ([double]$Value).ToString('0.00', $Invariant)
}

function Format-RunLine($Run) {
    $cost = Get-Field $Run 'cost'
    $age = Get-Field $Run 'heartbeat_age_s'
    $parts = @(
        [string](Get-Field $Run 'run_id'),
        (Format-Text (Get-Field $Run 'state')),
        "class=$(Format-Text (Get-Field $Run 'class'))",
        "segments=$(Get-Field $Run 'segments')",
        "spent=$(Format-Usd (Get-Field $cost 'known_spent_usd'))",
        "exposed=$(Format-Usd (Get-Field $cost 'open_exposures_usd'))",
        "reserved=$(Format-Usd (Get-Field $cost 'open_reservations_usd'))",
        "heartbeat=$(if ($null -eq $age) { '-' } else { "${age}s" })",
        "pending=$(Get-Field $Run 'pending_messages')"
    )
    $parts -join '  '
}

function Format-RunView($View) {
    $lines = [System.Collections.Generic.List[string]]::new()
    $lines.Add("Run $(Get-Field $View 'run_id'): $(Format-Text (Get-Field $View 'state')) (class $(Format-Text (Get-Field $View 'class')))" +
        ", kind $(Format-Text (Get-Field $View 'kind')), $(Format-Text (Get-Field $View 'supervision')), generation $(Get-Field $View 'generation')")
    $final = Get-Field $View 'final_status'
    $terminal = if (Get-Field $View 'final_status_terminal') { 'terminal' } else { 'not terminal' }
    $lines.Add("Final status: $(if ($final) { "$final ($terminal)" } else { '-' })")
    $task = Get-Field $View 'task'
    if ($null -eq $task) {
        $lines.Add('Task: -')
    } elseif (-not (Get-Field $task 'readable')) {
        $lines.Add("Task: $(Get-Field $task 'path') (not readable)")
    } else {
        $open = @(Get-Field $task 'open_rows')
        $lines.Add("Task: $(Get-Field $task 'path'), stop_gate $(Format-Text (Get-Field $task 'stop_gate')), open rows $($open.Count)$(if ($open.Count) { ': ' + ($open -join ', ') })")
    }
    $cost = Get-Field $View 'cost'
    $lines.Add("Cost: spent $(Format-Usd (Get-Field $cost 'known_spent_usd')), open exposures $(Format-Usd (Get-Field $cost 'open_exposures_usd'))" +
        ", settled $(Format-Usd (Get-Field $cost 'settled_usd')), reserved $(Format-Usd (Get-Field $cost 'open_reservations_usd'))" +
        "; caps: segment $(Format-Usd (Get-Field $cost 'segment_cap_usd')), run $(Format-Usd (Get-Field $cost 'run_cap_usd'))")

    $lines.Add('Segments:')
    foreach ($s in @(Get-Field $View 'segments')) {
        if ($null -eq $s) { continue }
        $dispatch = Get-Field $s 'dispatch'
        $status = if (Get-Field $dispatch 'status_json') { 'status.json' } else { 'no status.json' }
        $lines.Add("  $(Get-Field $s 'segment_id')  $(Format-Text (Get-Field $s 'state'))  resume=$(Format-Text (Get-Field $s 'resume'))" +
            "  class=$(Format-Text (Get-Field $s 'stop_class'))  by=$(Format-Text (Get-Field $s 'finalized_by'))  exit=$(Format-Text (Get-Field $s 'exit_code'))" +
            "  session_total=$(Format-Usd (Get-Field $s 'session_total_usd'))  dispatch=$(Format-Text (Get-Field $s 'dispatch_id')) ($status)")
        $lines.Add("    session=$(Format-Text (Get-Field $s 'expected_session_id'))  heartbeat=$(Format-Text (Get-Field $s 'last_alive_utc'))  brief=$(Format-Text (Get-Field $s 'brief'))")
    }
    $lines.Add('Requests:')
    foreach ($q in @(Get-Field $View 'requests')) {
        if ($null -eq $q) { continue }
        $mode = if ([int](Get-Field $q 'resume')) { "resume=$(Format-Text (Get-Field $q 'resume_mode'))" } else { 'first start' }
        $lines.Add("  $(Get-Field $q 'request_id')  $(Format-Text (Get-Field $q 'state'))  $mode  by=$(Format-Text (Get-Field $q 'started_by'))  reason=$(Format-Text (Get-Field $q 'reason'))")
    }
    $lines.Add('Attempts:')
    foreach ($a in @(Get-Field $View 'attempts')) {
        if ($null -eq $a) { continue }
        $lines.Add("  $(Get-Field $a 'attempt_id')  $(Format-Text (Get-Field $a 'state'))  dispatch=$(Format-Text (Get-Field $a 'dispatch_id'))  reason=$(Format-Text (Get-Field $a 'reason'))")
    }
    $lines.Add('Messages:')
    foreach ($m in @(Get-Field $View 'messages')) {
        if ($null -eq $m) { continue }
        $closed = Get-Field $m 'closed_reason'
        $tail = if ($closed) { "  closed: $closed" } elseif (Get-Field $m 'pending') { '  pending' } else { '' }
        $lines.Add("  $(Get-Field $m 'msg_id')  $(Get-Field $m 'kind')  $(Get-Field $m 'state')$tail")
    }
    $gate = Get-Field $View 'gate'
    $lines.Add("Gate: $(if ($null -eq $gate) { 'none open' } else { "$(Get-Field $gate 'gate_id') open, decision $(Format-Text (Get-Field $gate 'decision_id')), deadline $(Format-Text (Get-Field $gate 'deadline_utc'))" })")
    $lines.Add('Exposures:')
    foreach ($e in @(Get-Field $View 'exposures')) {
        if ($null -eq $e) { continue }
        $lines.Add("  $(Get-Field $e 'segment_id')  $(Format-Text (Get-Field $e 'state'))  exposed=$(Format-Usd (Get-Field $e 'exposed_usd'))  amount=$(Format-Usd (Get-Field $e 'amount_usd'))")
        $settleCommand = Get-Field $e 'settle_command'
        if ($settleCommand) { $lines.Add("    settle: $settleCommand") }
    }
    $lines.Add('Outbox (newest first):')
    foreach ($o in @(Get-Field $View 'outbox')) {
        if ($null -eq $o) { continue }
        $lines.Add("  $(Get-Field $o 'event_seq')  $(Get-Field $o 'kind')  $(Format-Text (Get-Field $o 'semantic_key'))  $(Format-Text (Get-Field $o 'created_utc'))")
    }
    $resume = Get-Field $View 'resume'
    $lines.Add('Resume:')
    $lines.Add("  source dispatch $(Format-Text (Get-Field $resume 'source_dispatch_id'))" +
        "; ruling pending $(Format-Text ([bool](Get-Field $resume 'ruling_pending')))" +
        "; session resume $(if (Get-Field $resume 'session_resume_possible') { 'possible' } else { 'not possible (no status.json)' })")
    if (Get-Field $resume 'recovery_status_needed') {
        $lines.Add("  recover the status first: $(Get-Field $resume 'recovery_command')")
    }
    $lines.Add("  start: $(Get-Field $resume 'command')")
    $lines -join [Environment]::NewLine
}

if (-not (Test-Path -LiteralPath $StateDb -PathType Leaf)) {
    [Console]::Error.WriteLine("Get-CreditsRun: no credits store at $StateDb")
    exit 2
}

if ($PSCmdlet.ParameterSetName -eq 'Settle') {
    $arguments = @(
        '--segment-id', $Settle,
        '--source', $Source,
        '--amount-usd', $AmountUsd.ToString($Invariant),
        '--started-by', $StartedBy
    )
    if ($Note) { $arguments += @('--note', $Note) }
    if ($Quote) { $arguments += @('--quote', $Quote) }

    $res = Invoke-CreditsState -StateDb $StateDb -Verb settle -Arguments $arguments
    if ($res.Out) { [Console]::Out.Write($res.Out) }
    if ($res.Err) { [Console]::Error.Write($res.Err) }
    exit $res.Code
}

if ($PSCmdlet.ParameterSetName -eq 'AcceptDrift') {
    if ([string]::IsNullOrWhiteSpace($Quote)) {
        [Console]::Error.WriteLine('Get-CreditsRun: -AcceptDrift needs -Quote "<the human''s words>"')
        exit 2
    }
    $arguments = @('--successor', $RunId, '--predecessor', $AcceptDrift, '--quote', $Quote)
    $res = Invoke-CreditsState -StateDb $StateDb -Verb accept_drift -Arguments $arguments
    if ($res.Out) { [Console]::Out.Write($res.Out) }
    if ($res.Err) { [Console]::Error.Write($res.Err) }
    exit $res.Code
}

if ($PSCmdlet.ParameterSetName -eq 'Attach') {
    $arguments = @('--run-id', $RunId, '--session', $AttachSession, '--uuid', $UserMessageUuid)
    $res = Invoke-CreditsState -StateDb $StateDb -Verb attach -Arguments $arguments
    if ($res.Out) { [Console]::Out.Write($res.Out) }
    if ($res.Err) { [Console]::Error.Write($res.Err) }
    exit $res.Code
}

if ($Export -and -not $RunId) {
    [Console]::Error.WriteLine('Get-CreditsRun: -Export needs a run id')
    exit 2
}

$arguments = @('--output-dir', $OutputDir)
if ($RunId) { $arguments += @('--run-id', $RunId) }
$res = Invoke-CreditsState -StateDb $StateDb -Verb view -Arguments $arguments
if ($res.Err) { [Console]::Error.Write($res.Err) }
if ($res.Code -ne 0 -or $null -eq $res.Payload) {
    $message = Get-Field $res.Payload 'message'
    [Console]::Error.WriteLine("Get-CreditsRun: the view failed (exit $($res.Code)): $(if ($message) { $message } else { $res.Out })")
    exit $(if ($res.Code -ne 0) { $res.Code } else { 1 })
}

if (-not $RunId) {
    $runs = @(Get-Field $res.Payload 'runs')
    [Console]::Out.WriteLine("$($runs.Count) run(s) in $StateDb")
    foreach ($run in $runs) {
        if ($null -ne $run) { [Console]::Out.WriteLine((Format-RunLine $run)) }
    }
    exit 0
}

[Console]::Out.WriteLine((Format-RunView $res.Payload))
if ($Export) {
    $folder = Join-Path (Split-Path -Parent ([System.IO.Path]::GetFullPath($StateDb))) "runs/$RunId"
    New-Item -ItemType Directory -Force -Path $folder | Out-Null
    $path = Join-Path $folder 'view.json'
    $json = @($res.Out -split "`r?`n" | Where-Object { -not [string]::IsNullOrWhiteSpace($_) }) | Select-Object -Last 1
    [System.IO.File]::WriteAllText($path, $json + "`n", [System.Text.UTF8Encoding]::new($false))
    [Console]::Out.WriteLine("Exported: $path")
}
exit 0
