<#
.SYNOPSIS
    The monitor of the scheduled credits runs (report section 4.4). The task \{{PROJECT_NAME_TITLE}}\Credits\Monitor
    starts it at logon and every 5 minutes; one start runs one pass (two when a rescan is asked for).

.DESCRIPTION
    One pass:
      1. takes the monitor lease (store verb lease). A live holder keeps it: the pass writes
         rescan.request next to the store and ends with outcome lease_held. A dead holder (pid plus
         creation time, or another boot) is taken over;
      2. ends each pending request older than ORPHAN_REQUEST_S (scan_requests) and logs one
         credits_limit_tripped WARN for each;
      3. proves each accepted or admitted attempt whose launcher is dead (scan_attempts, MX-3, MX-4);
      4. proves each open segment whose supervisor (the launcher, or the manual wrapper) is dead.
         A live supervisor marks the segment alive. A live job with a dead launcher is terminated
         by name; a later pass finalizes it (P-8b f). A job-less manual segment gets the manual
         proof (MX-35). The proofs go to scan_segments;
      5. classifies each finalizing run from the signals of report section 5.1, in their order,
         into one class of section 5.2, and files the stop notice in the same transaction
         (classify). Done needs the completion evidence: tools/completion_preflight.py --json and,
         for an exec run, the product capture and the closeout seal (MX-25);
      6. starts each ready chain run (chain_candidates, report section 4.4 step 4): a run with a
         chain block, no segment and no open request, whose depends_on predicates hold at HEAD,
         with no halted predecessor and room in the chain cap. The start goes through
         -ChainStarter, which files a monitor-chain start request; the request ends the
         candidacy (AC-G.4);
      7. scans the transcript of each attached orchestrator session (scan_transcript, report
         section 4.4 step 3 and section 4.6.3): the new bytes move the session's mark; a changed
         prefix sets the session broken and files one transcript_discontinuity notice (MX-28);
      8. turns the outbox events into notices (outbox_scan, MX-13), sends every notice that is due
         through -Notifier (notice_sent or notice_failed, MX-22) and runs the due effects
         (scan_effects).
    The monitor never resumes a run, never sends a message to a run and never writes a review
    verdict (AC-E.4). It starts only a first start of a chain run. Every result goes to the store;
    the monitor keeps no state of its own.

    It prints one JSON line: outcome pass, lease_held or error. Exit 0 for pass and lease_held, 1
    for error. Log records go to <store folder>/logs/monitor.jsonl.

.PARAMETER StateDb
    The store. Default: the launcher's default (Start-CreditsRun.ps1).
.PARAMETER OutputDir
    The dispatch folder: <OutputDir>/<dispatch id>/{status.json, output.json, stderr.txt, final.md}.
    Default: the launcher's default.
.PARAMETER NowUtc
    The store clock for every verb of the pass. Tests only.
.PARAMETER Observations
    Segment id → a Get-CreditsJobProof -Observation hashtable. Tests only.
.PARAMETER Notifier
    A script block that sends one notice; a throw is a failed send. Default: tools/agent_notify.py send.
.PARAMETER HostEvents
    The host events (Id, ProviderName, TimeCreated) to use in place of the System log. Tests only.
.PARAMETER ChainStarter
    A script block that starts one chain run: param($Candidate), one chain_candidates entry
    (run_id, chain_id, holds, halted, ready). A throw is a failed start, logged; the run stays a
    candidate. Default: Start-CreditsRunTask.ps1 -RunId <run> -StartedBy monitor-chain
    -ChainId <chain id>.
.PARAMETER RunParametersTool
    tools/run_parameters.py, run with the manifest's launch.python_exe in the project root, for a
    run whose manifest names phases (report section 4.4): `stop --reason no_record` for a run
    that died with no Status, and `final --plan <plan> --seal` for a verified DONE. Default: the
    repository's tools/run_parameters.py. A legacy run (no phases) never calls it.
.PARAMETER PhaseTool
    tools/credits_msg.py, run like RunParametersTool, for a run whose manifest names phases
    (EA-21, EA-23): `phase E13 --by monitor` after a sealed DONE and `phase E6 --by monitor` after
    a budget_cap class. Each call has CREDITS_RUN_ID, CREDITS_SEGMENT (the last segment) and
    CREDITS_STATE_DB. A failed call writes one phase_call_failed WARN record and leaves the class.
    Default: the repository's tools/credits_msg.py. A legacy run never calls it.

.EXAMPLE
    pwsh -NoProfile -File .agent/skills/claude-credits/Watch-CreditsRuns.ps1
#>
[CmdletBinding()]
param(
    [string]$StateDb,
    [string]$OutputDir,
    [Nullable[datetime]]$NowUtc,
    [hashtable]$Observations = @{},
    [scriptblock]$Notifier,
    [object[]]$HostEvents = @(),
    [scriptblock]$ChainStarter,
    [string]$RunParametersTool,
    [string]$PhaseTool
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

if (-not (Get-Module -Name CreditsRun)) {
    Import-Module -Name (Join-Path $PSScriptRoot 'CreditsRun.psm1') -DisableNameChecking -ErrorAction Stop
}

$script:RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot '../../..')).Path
$script:PreflightTool = Join-Path $script:RepoRoot 'tools/completion_preflight.py'
$script:NotifyTool = Join-Path $script:RepoRoot 'tools/agent_notify.py'
$script:HostEventsGiven = $PSBoundParameters.ContainsKey('HostEvents')
$script:ChildTimeoutMs = 120000
$script:TaskStarter = Join-Path $PSScriptRoot 'Start-CreditsRunTask.ps1'
# Start-CreditsRunTask.ps1 waits up to REQUEST_ACCEPT_TIMEOUT_S (120 s) for accepted; the default
# chain starter gives it that wait and a margin.
$script:ChainChildTimeoutMs = 150000
$script:RpTool = if ($RunParametersTool) { $RunParametersTool } else { Join-Path $script:RepoRoot 'tools/run_parameters.py' }
$script:PhaseTool = if ($PhaseTool) { $PhaseTool } else { Join-Path $script:RepoRoot 'tools/credits_msg.py' }

# R§5.2: the gate that each STOPPED:<class> Status needs in task.md. budget is the save-state
# hand-back; human_stop, no_record and ambiguous are phase-machine stops for the human (R§4.4).
$script:StoppedGates = @{
    decision             = 'released:human-gate'
    handback             = 'released:handback'
    base_moved           = 'released:handback'
    round_cap            = 'released:round-cap'
    reviewer_unavailable = 'released:reviewer-unavailable'
    budget               = 'released:handback'
    human_stop           = 'released:human-gate'
    no_record            = 'released:human-gate'
    ambiguous            = 'released:human-gate'
}
$script:BillingPattern = '(?i)credit balance is too low|billing_error'
$script:TransientPattern = '(?i)rate_limit_error|overloaded_error|\bapi_error\b|server_error|API Error: (429|5\d\d)\b|stream (error|ended|closed)|ECONNRESET|ETIMEDOUT|socket hang up'
$script:AuthPattern = '(?i)authentication_error|permission_error|invalid_request_error|not_found_error|model_not_found|invalid (x-)?api[ -]key'
$script:WaitPattern = '(?i)run_in_background|background (task|job|agent|process|shell)|waiting (for|on)\b|wait for\b'

# --- helpers --------------------------------------------------------------------------------

# The default of one launcher parameter: the launcher's table is the one place that names it.
function Get-LauncherDefault([string]$Name) {
    $text = [System.IO.File]::ReadAllText((Join-Path $PSScriptRoot 'Start-CreditsRun.ps1'))
    $found = [regex]::Match($text, "(?m)^\s*$Name\s*=\s*@\{[^}]*Default\s*=\s*'([^']+)'")
    if (-not $found.Success) { throw "Start-CreditsRun.ps1 names no default for $Name" }
    return $found.Groups[1].Value
}

function Get-Prop($Object, [string]$Name) {
    if ($null -eq $Object) { return $null }
    if ($Object -is [System.Collections.IDictionary]) {
        if ($Object.Contains($Name)) { return $Object[$Name] }
        return $null
    }
    $prop = $Object.PSObject.Properties[$Name]
    if ($null -eq $prop) { return $null }
    return $prop.Value
}

function Write-MonitorLog([string]$Level, [string]$Name, [hashtable]$Fields = @{}) {
    $record = [ordered]@{ ts = [datetime]::UtcNow.ToString('yyyy-MM-ddTHH:mm:ss.fffZ'); level = $Level; event = $Name }
    foreach ($key in $Fields.Keys) { $record[$key] = $Fields[$key] }
    $folder = Split-Path -Parent $script:LogPath
    if (-not (Test-Path -LiteralPath $folder)) { New-Item -ItemType Directory -Force -Path $folder | Out-Null }
    [System.IO.File]::AppendAllText($script:LogPath, (($record | ConvertTo-Json -Compress -Depth 6) + "`n"), [System.Text.UTF8Encoding]::new($false))
}

# One store verb on the pass clock. Throws when the store refuses or fails.
function Invoke-Store([string]$Verb, [string[]]$Arguments = @()) {
    $res = Invoke-CreditsState -StateDb $script:Db -Verb $Verb -Arguments $Arguments -NowUtc $script:Clock
    if ($res.Code -ne 0 -or $null -eq $res.Payload) { throw "store $Verb failed: $(Format-CreditsStateError $res)" }
    return $res.Payload
}

# A store time (text, or the datetime that ConvertFrom-Json made of it) as a UTC datetime.
function ConvertTo-UtcTime($Value) {
    if ($null -eq $Value -or "$Value" -eq '') { return $null }
    if ($Value -is [datetime]) {
        if ($Value.Kind -eq [System.DateTimeKind]::Unspecified) { return [datetime]::SpecifyKind($Value, [System.DateTimeKind]::Utc) }
        return $Value.ToUniversalTime()
    }
    $styles = [System.Globalization.DateTimeStyles]::AssumeUniversal -bor [System.Globalization.DateTimeStyles]::AdjustToUniversal
    $parsed = [datetime]::MinValue
    if ([datetime]::TryParse([string]$Value, [System.Globalization.CultureInfo]::InvariantCulture, $styles, [ref]$parsed)) { return $parsed }
    return $null
}

# 'none' for an identity that was never recorded, else dead, alive or unknown.
function Get-IdentityState($ProcessId, $Created) {
    if ($null -eq $ProcessId -or "$ProcessId" -eq '') { return 'none' }
    return Get-CreditsProcessState -ProcessId ([int]$ProcessId) -Created $Created
}

function New-Identity($ProcessId, $Created) { @{ pid = $ProcessId; created = $Created } }

function Get-Observation([string]$SegmentId) {
    if ($null -ne $Observations -and $Observations.ContainsKey($SegmentId) -and $Observations[$SegmentId] -is [hashtable]) { return $Observations[$SegmentId] }
    return @{}
}

# The job proof of one segment. A live job whose supervisor is dead is terminated by name; the
# proof stays live, so a later pass reads the empty job and finalizes (report section 4.4).
function Resolve-JobProof([string]$SegmentId, $JobName, $Session, [string]$BootId, [object[]]$Processes) {
    if ($null -eq $Session -or "$Session" -eq '') { return 'unknown' }
    $name = if ($JobName) { [string]$JobName } else { Get-CreditsJobName -SegmentId $SegmentId }
    $proof = Get-CreditsJobProof -JobName $name -LauncherSession ([int]$Session) -BootId $BootId -Processes $Processes -Observation (Get-Observation $SegmentId)
    if ($proof.Result -eq 'live') {
        $code = Stop-CreditsJobByName -JobName $name
        Write-MonitorLog 'WARN' 'job_terminated' @{ segment_id = $SegmentId; job_name = $name; win32_error = $code }
    } elseif ($proof.Result -eq 'unknown') {
        Write-MonitorLog 'WARN' 'job_proof_unknown' @{ segment_id = $SegmentId; reason = $proof.Reason; open_error = $proof.OpenError }
    }
    return $proof.Result
}

# --- step 3: the attempts ---------------------------------------------------------------------

function Get-AttemptProof($Attempt) {
    if ([string](Get-Prop $Attempt 'boot_id') -ne $script:Boot) { return 'empty' }
    $launcher = Get-IdentityState (Get-Prop $Attempt 'launcher_pid') (Get-Prop $Attempt 'launcher_created')
    if ($launcher -eq 'alive') { return $null }
    $segmentId = Get-Prop $Attempt 'segment_id'
    if ([string](Get-Prop $Attempt 'state') -eq 'accepted' -or -not $segmentId) {
        if ($launcher -eq 'dead') { return 'gone' }
        return 'unknown'
    }
    $processes = @(
        (New-Identity (Get-Prop $Attempt 'launcher_pid') (Get-Prop $Attempt 'launcher_created')),
        (New-Identity (Get-Prop $Attempt 'wrapper_pid') (Get-Prop $Attempt 'wrapper_created'))
    )
    return Resolve-JobProof ([string]$segmentId) (Get-Prop $Attempt 'job_name') (Get-Prop $Attempt 'win_session') ([string](Get-Prop $Attempt 'boot_id')) $processes
}

# --- step 4: the segments ---------------------------------------------------------------------

function Get-SegmentProof($Segment) {
    $segmentId = [string](Get-Prop $Segment 'segment_id')
    $runId = [string](Get-Prop $Segment 'run_id')
    $bootId = [string](Get-Prop $Segment 'boot_id')
    $sameBoot = $bootId -eq $script:Boot
    $launcher = New-Identity (Get-Prop $Segment 'launcher_pid') (Get-Prop $Segment 'launcher_created')
    $wrapper = New-Identity (Get-Prop $Segment 'wrapper_pid') (Get-Prop $Segment 'wrapper_created')
    $cli = New-Identity (Get-Prop $Segment 'pid') (Get-Prop $Segment 'created')

    if ([int](Get-Prop $Segment 'job') -eq 0) {
        # The manual proof (MX-35): no job, so every recorded process must be dead.
        if (-not $sameBoot) { return 'gone' }
        $states = @(foreach ($identity in @($launcher, $wrapper, $cli)) { Get-IdentityState $identity.pid $identity.created })
        if ($states -contains 'alive') {
            $null = Invoke-Store 'notice' @('--kind', 'manual_child_alive', '--ref', $segmentId, '--run-id', $runId,
                '--body-json', (@{ segment_id = $segmentId } | ConvertTo-Json -Compress))
            $null = Invoke-Store 'alive' @('--segment-id', $segmentId)
            return $null
        }
        if ($states -contains 'unknown') { return 'unknown' }
        return 'gone'
    }

    $supervisor = if ([string](Get-Prop $Segment 'supervision') -eq 'manual') { $wrapper } else { $launcher }
    $supervisorState = if ($sameBoot) { Get-IdentityState $supervisor.pid $supervisor.created } else { 'dead' }
    if ($supervisorState -eq 'alive') {
        $null = Invoke-Store 'alive' @('--segment-id', $segmentId)
        return $null
    }
    return Resolve-JobProof $segmentId (Get-Prop $Segment 'job_name') (Get-Prop $Segment 'win_session') $bootId @($launcher, $wrapper, $cli)
}

# --- step 5: the classification (R§5.1 signals, R§5.2 classes) --------------------------------

function Read-TextFile([string]$Path) {
    if (-not $Path -or -not (Test-Path -LiteralPath $Path -PathType Leaf)) { return $null }
    return [System.IO.File]::ReadAllText($Path, [System.Text.Encoding]::UTF8)
}

# A JSON file, or the last JSON line of it. Returns Present and Value ($null when unreadable).
function Read-JsonSignal([string]$Path) {
    $text = Read-TextFile $Path
    if ($null -eq $text) { return [pscustomobject]@{ Present = $false; Value = $null } }
    $value = $null
    try { $value = $text | ConvertFrom-Json -ErrorAction Stop } catch {
        $last = @($text -split "`r?`n" | Where-Object { $_.TrimStart().StartsWith('{') }) | Select-Object -Last 1
        if ($last) { try { $value = $last | ConvertFrom-Json -ErrorAction Stop } catch { $value = $null } }
    }
    return [pscustomobject]@{ Present = $true; Value = $value }
}

# The last "Status:" line of final.md (report section 7.3), or $null.
function Get-StatusLine([string]$Final) {
    if (-not $Final) { return $null }
    $found = [regex]::Matches($Final, '(?m)^\s*Status:[ \t]*(.*?)[ \t]*\r?$')
    if ($found.Count -eq 0) { return $null }
    return $found[$found.Count - 1].Groups[1].Value
}

# task.md of the plan: the frontmatter status and stop_gate, and the rows that are not closed.
function Read-TaskState($Root, $PlanFolder) {
    $none = [pscustomobject]@{ Exists = $false; Status = $null; StopGate = $null; OpenRows = 0 }
    if (-not $Root -or -not $PlanFolder) { return $none }
    $text = Read-TextFile (Join-Path (Join-Path ([string]$Root) ([string]$PlanFolder)) 'task.md')
    if ($null -eq $text) { return $none }
    $front = [regex]::Match($text, '(?s)\A---\r?\n(.*?)\r?\n---')
    $head = if ($front.Success) { $front.Groups[1].Value } else { '' }
    $status = [regex]::Match($head, '(?m)^status:\s*"?([^"\r\n]*?)"?\s*$')
    $gate = [regex]::Match($head, '(?m)^stop_gate:\s*"?([^"\r\n]*?)"?\s*$')
    $open = @([regex]::Matches($text, '(?m)^\|.*(\[ \]|\[~\]).*\|\s*$')).Count
    return [pscustomobject]@{
        Exists   = $true
        Status   = if ($status.Success) { $status.Groups[1].Value } else { $null }
        StopGate = if ($gate.Success) { $gate.Groups[1].Value } else { $null }
        OpenRows = $open
    }
}

# tools/completion_preflight.py --json for one plan: ExitCode and Result (its JSON line), or $null
# when it gives no JSON.
function Invoke-Preflight([string]$Tree, [string]$PlanFolder) {
    $psi = [System.Diagnostics.ProcessStartInfo]::new((Get-CreditsPython))
    foreach ($a in @('-X', 'utf8', $script:PreflightTool, '--plan', $PlanFolder.TrimEnd('/', '\'), '--tree', $Tree, '--json')) { $psi.ArgumentList.Add([string]$a) }
    $psi.UseShellExecute = $false
    $psi.CreateNoWindow = $true
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true
    $proc = [System.Diagnostics.Process]::Start($psi)
    try {
        $outTask = $proc.StandardOutput.ReadToEndAsync()
        $errTask = $proc.StandardError.ReadToEndAsync()
        if (-not $proc.WaitForExit($script:ChildTimeoutMs)) {
            try { $proc.Kill($true) } catch { Write-MonitorLog 'WARN' 'preflight_kill_failed' @{ error = $_.Exception.Message } }
            throw "completion_preflight.py did not end in $($script:ChildTimeoutMs / 1000) s"
        }
        $proc.WaitForExit()
        $last = @($outTask.Result -split "`r?`n" | Where-Object { $_.TrimStart().StartsWith('{') }) | Select-Object -Last 1
        if (-not $last) {
            Write-MonitorLog 'WARN' 'preflight_no_json' @{ exit_code = $proc.ExitCode; stderr = ([string]$errTask.Result).Trim() }
            return $null
        }
        return [pscustomobject]@{ ExitCode = $proc.ExitCode; Result = ($last | ConvertFrom-Json -ErrorAction Stop) }
    } finally {
        $proc.Dispose()
    }
}

# The host events (R§5.1 step 8): the given list, else the System log since $StartUtc.
function Get-HostEventList([datetime]$StartUtc) {
    if ($script:HostEventsGiven) { return @($HostEvents) }
    $since = $StartUtc.ToLocalTime().AddMinutes(-1)
    $found = [System.Collections.Generic.List[object]]::new()
    $filters = @(
        @{ LogName = 'System'; Id = @(41, 42, 1074, 6006, 6008); StartTime = $since },
        @{ LogName = 'System'; ProviderName = 'Microsoft-Windows-Power-Troubleshooter'; Id = 1; StartTime = $since }
    )
    foreach ($filter in $filters) {
        try {
            foreach ($item in @(Get-WinEvent -FilterHashtable $filter -ErrorAction SilentlyContinue)) { $found.Add($item) }
        } catch {
            Write-MonitorLog 'WARN' 'host_events_unreadable' @{ error = $_.Exception.Message }
        }
    }
    return $found.ToArray()
}

# sleep, crash, windows_update, planned, or $null for an event that no rule reads.
function Get-HostEventKind($HostEvent) {
    $id = [int](Get-Prop $HostEvent 'Id')
    $provider = [string](Get-Prop $HostEvent 'ProviderName')
    if ($id -eq 42 -and $provider -like '*Kernel-Power') { return 'sleep' }
    if ($id -eq 1 -and $provider -like '*Power-Troubleshooter') { return 'sleep' }
    if ($id -eq 41 -or $id -eq 6008) { return 'crash' }
    if ($id -eq 6006) { return 'planned' }
    if ($id -eq 1074) {
        $text = [string](Get-Prop $HostEvent 'Message')
        foreach ($item in @(Get-Prop $HostEvent 'Properties')) { $text += ' ' + [string](Get-Prop $item 'Value') }
        if ($text -match '(?i)MoUsoCoreWorker\.exe|TrustedInstaller\.exe') { return 'windows_update' }
        return 'planned'
    }
    return $null
}

# The kinds of the host events inside [last alive (else segment start) .. finalized].
function Get-IntervalEventKinds($Segment) {
    $start = ConvertTo-UtcTime (Get-Prop $Segment 'last_alive_utc')
    if ($null -eq $start) { $start = ConvertTo-UtcTime (Get-Prop $Segment 'created_utc') }
    $end = ConvertTo-UtcTime (Get-Prop $Segment 'finalized_utc')
    if ($null -eq $end) { $end = $script:NowTime }
    if ($null -eq $start) { return @() }
    $kinds = foreach ($item in @(Get-HostEventList $start)) {
        $at = ConvertTo-UtcTime (Get-Prop $item 'TimeCreated')
        if ($null -eq $at -or $at -lt $start -or $at -gt $end) { continue }
        $kind = Get-HostEventKind $item
        if ($kind) { $kind }
    }
    return @($kinds)
}

function Test-PlanReviewApproved($Root, $PlanFolder) {
    if (-not $Root -or -not $PlanFolder) { return $false }
    $plan = Split-Path -Leaf ([string]$PlanFolder).TrimEnd('/', '\')
    $text = Read-TextFile (Join-Path ([string]$Root) ".agent/context/handoffs/$plan-plan-critical-review.md")
    if ($null -eq $text) { return $false }
    return $text -match '(?im)^\s*verdict:\s*"?approved"?\s*$'
}

# One run-side tool call for a phased run, in its project root with the manifest's python_exe,
# with $Environment added to the child's environment only. Returns Code, Result (its last JSON
# line, or $null) and Stderr. Throws on a start failure or a timeout.
function Invoke-RunTool($Run, [string]$Tool, [string[]]$Arguments, [hashtable]$Environment = @{}) {
    $python = [string](Get-Prop $Run 'python_exe')
    if (-not $python) { $python = Get-CreditsPython }
    $psi = [System.Diagnostics.ProcessStartInfo]::new($python)
    foreach ($a in @('-X', 'utf8', $Tool) + $Arguments) { $psi.ArgumentList.Add([string]$a) }
    $root = [string](Get-Prop (Get-Prop $Run 'manifest') 'project_root')
    if ($root -and (Test-Path -LiteralPath $root -PathType Container)) { $psi.WorkingDirectory = $root }
    foreach ($name in $Environment.Keys) { $psi.Environment[[string]$name] = [string]$Environment[$name] }
    $psi.UseShellExecute = $false
    $psi.CreateNoWindow = $true
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true
    $leaf = Split-Path -Leaf $Tool
    $proc = [System.Diagnostics.Process]::Start($psi)
    try {
        $outTask = $proc.StandardOutput.ReadToEndAsync()
        $errTask = $proc.StandardError.ReadToEndAsync()
        if (-not $proc.WaitForExit($script:ChildTimeoutMs)) {
            try { $proc.Kill($true) } catch { Write-MonitorLog 'WARN' 'run_tool_kill_failed' @{ tool = $leaf; error = $_.Exception.Message } }
            throw "$leaf did not end in $($script:ChildTimeoutMs / 1000) s"
        }
        $proc.WaitForExit()
        $last = @($outTask.Result -split "`r?`n" | Where-Object { $_.TrimStart().StartsWith('{') }) | Select-Object -Last 1
        $result = $null
        if ($last) { try { $result = $last | ConvertFrom-Json -ErrorAction Stop } catch { $result = $null } }
        return [pscustomobject]@{ Code = $proc.ExitCode; Result = $result; Stderr = ([string]$errTask.Result).Trim() }
    } finally {
        $proc.Dispose()
    }
}

# One tools/run_parameters.py call for a phased run (Invoke-RunTool).
function Invoke-RunParameters($Run, [string[]]$Arguments) {
    return Invoke-RunTool $Run $script:RpTool $Arguments
}

# EA-21, EA-23: one `credits_msg.py phase <event> --by monitor` call for a phased run, with the
# run's CREDITS_RUN_ID, its last segment and this store. True when the tool recorded it; a start
# failure, a timeout or a nonzero exit writes one phase_call_failed WARN record and returns false.
# The caller's class does not depend on the answer.
function Invoke-PhaseCall($Run, [string]$PhaseEvent, [System.Collections.IDictionary]$Payload) {
    $runId = [string](Get-Prop $Run 'run_id')
    $segmentId = [string](Get-Prop (Get-Prop $Run 'segment') 'segment_id')
    $fields = @{ run_id = $runId; phase_event = $PhaseEvent }
    if (-not $segmentId) {
        Write-MonitorLog 'WARN' 'phase_call_failed' ($fields + @{ reason = 'segment_missing' })
        return $false
    }
    $environment = @{ CREDITS_RUN_ID = $runId; CREDITS_SEGMENT = $segmentId; CREDITS_STATE_DB = $script:Db }
    $arguments = @('phase', $PhaseEvent, '--by', 'monitor', '--payload', ($Payload | ConvertTo-Json -Compress -Depth 4))
    try {
        $res = Invoke-RunTool $Run $script:PhaseTool $arguments $environment
    } catch {
        Write-MonitorLog 'WARN' 'phase_call_failed' ($fields + @{ reason = 'tool_failed'; error = $_.Exception.Message })
        return $false
    }
    if ($res.Code -ne 0 -or [string](Get-Prop $res.Result 'result') -ne 'recorded') {
        Write-MonitorLog 'WARN' 'phase_call_failed' ($fields + @{
                exit_code = $res.Code; reason = [string](Get-Prop $res.Result 'error'); stderr = $res.Stderr })
        return $false
    }
    Write-MonitorLog 'INFO' 'phase_recorded' ($fields + @{ state = [string](Get-Prop $res.Result 'state'); seq = Get-Prop $res.Result 'seq' })
    return $true
}

# The E6 tokens of a budget cap: input + output + cache creation + cache read of the output.json
# usage; a missing or non-numeric count is 0.
function Get-UsageTokens($Output) {
    $usage = Get-Prop $Output 'usage'
    $total = [long]0
    foreach ($name in 'input_tokens', 'output_tokens', 'cache_creation_input_tokens', 'cache_read_input_tokens') {
        $value = Get-Prop $usage $name
        if ($value -is [int] -or $value -is [long] -or $value -is [double] -or $value -is [decimal]) { $total += [long]$value }
    }
    return $total
}

# The plan slug of a run: the leaf of its plan folder.
function Get-PlanSlug($Run) {
    $folder = [string](Get-Prop (Get-Prop $Run 'manifest') 'plan_folder')
    if (-not $folder) { return $null }
    return Split-Path -Leaf $folder.TrimEnd('/', '\')
}

# The CLI transcript of a segment's session (credits_state.py transcript_path, R§4.6.3 step 2).
function Get-SegmentTranscript($Run, $Segment) {
    $root = [string](Get-Prop (Get-Prop $Run 'manifest') 'project_root')
    $session = [string](Get-Prop $Segment 'expected_session_id')
    if (-not $root -or -not $session) { return $null }
    $base = if ($env:CLAUDE_CONFIG_DIR) { $env:CLAUDE_CONFIG_DIR } else {
        $homeDir = if ($env:USERPROFILE) { $env:USERPROFILE } else { $env:HOME }
        Join-Path $homeDir '.claude'
    }
    return Join-Path (Join-Path (Join-Path $base 'projects') ($root -replace '[^A-Za-z0-9]', '-')) "$session.jsonl"
}

# R§4.4 V6-049: the authoritative E9 record of a phased run that died with no Status. The tool
# re-checks the four conditions under the lock (dead process, idle transcript, the seq, a
# nonterminal state) and writes the record; the monitor then syncs the derived view. Returns the
# stop class when the record says the run stopped, else $null: a refusal (a stale lock, a pending
# transaction, a condition not met) writes nothing and leaves a no_record_pending WARN record, and
# a later pass tries again.
function Invoke-NoRecordStop($Run, $Segment) {
    $runId = [string](Get-Prop $Run 'run_id')
    $viewState = [string](Get-Prop $Run 'phase_state')
    if ($viewState -cmatch '^STOPPED:([a-z_]+)$') { return $Matches[1] }
    $plan = Get-PlanSlug $Run
    $processId = Get-Prop $Segment 'pid'
    $created = ConvertTo-UtcTime (Get-Prop $Segment 'created')
    $transcript = Get-SegmentTranscript $Run $Segment
    if (-not $plan -or $null -eq $processId -or $null -eq $created -or -not $transcript) {
        Write-MonitorLog 'WARN' 'no_record_pending' @{ run_id = $runId; reason = 'identity_missing' }
        return $null
    }
    $seq = Get-Prop $Run 'phase_seq'
    if ($null -eq $seq) { $seq = 0 }
    $pidStart = ([DateTimeOffset]::new($created).ToUnixTimeMilliseconds() / 1000.0).ToString('F3', [System.Globalization.CultureInfo]::InvariantCulture)
    $arguments = @('stop', '--plan', $plan, '--run', $runId, '--reason', 'no_record', '--expect-seq', [string]$seq,
        '--pid', [string]$processId, '--pid-start', $pidStart, '--transcript', $transcript)
    try {
        $res = Invoke-RunParameters $Run $arguments
    } catch {
        Write-MonitorLog 'WARN' 'no_record_pending' @{ run_id = $runId; reason = 'tool_failed'; error = $_.Exception.Message }
        return $null
    }
    if ($res.Code -ne 0 -or [string](Get-Prop $res.Result 'result') -ne 'stopped') {
        Write-MonitorLog 'WARN' 'no_record_pending' @{ run_id = $runId; exit_code = $res.Code; reason = [string](Get-Prop $res.Result 'reason'); stderr = $res.Stderr }
        return $null
    }
    $recorded = Get-Prop $res.Result 'seq'
    if ($null -ne $recorded) {
        $sync = Invoke-CreditsState -StateDb $script:Db -Verb phase_sync -Arguments @('--run-id', $runId, '--state', 'STOPPED:no_record', '--seq', [string]$recorded) -NowUtc $script:Clock
        if ($sync.Code -ne 0) { Write-MonitorLog 'WARN' 'phase_view_sync_failed' @{ run_id = $runId; error = (Format-CreditsStateError $sync) } }
    }
    Write-MonitorLog 'INFO' 'no_record_stopped' @{ run_id = $runId; plan = $plan; expect_seq = $seq }
    return 'no_record'
}

# R§4.4 V6-050 (D-17): seal the exec phase of a verified DONE. Returns Plan and Generation (the
# sealed generation, or $null when the tool named none) when the tool sealed it, else $null.
function Invoke-FinalSeal($Run) {
    $runId = [string](Get-Prop $Run 'run_id')
    $plan = Get-PlanSlug $Run
    if (-not $plan) { return $null }
    try {
        $res = Invoke-RunParameters $Run @('final', '--plan', $plan, '--seal')
    } catch {
        Write-MonitorLog 'WARN' 'final_seal_failed' @{ run_id = $runId; error = $_.Exception.Message }
        return $null
    }
    if ($res.Code -ne 0) {
        Write-MonitorLog 'WARN' 'final_seal_failed' @{ run_id = $runId; exit_code = $res.Code; reason = [string](Get-Prop $res.Result 'reason'); stderr = $res.Stderr }
        return $null
    }
    $generation = Get-Prop $res.Result 'generation'
    Write-MonitorLog 'INFO' 'final_sealed' @{ run_id = $runId; plan = $plan; generation = $generation }
    return [pscustomobject]@{ Plan = $plan; Generation = $generation }
}

# EA-21, EA-23: the phase event that the monitor records for one class of a phased run, as
# Event and Payload, or $null. E13 needs the sealed generation; E6 counts the usage tokens.
function Get-ClassPhaseEvent([string]$Class, $Seal, $Output) {
    if ($Class -eq 'done' -and $Seal) {
        $generation = $Seal.Generation
        if ($generation -isnot [int] -and $generation -isnot [long]) { return [pscustomobject]@{ Event = 'E13'; Payload = $null } }
        $stem = "final/$($Seal.Plan)/$generation"
        return [pscustomobject]@{ Event = 'E13'; Payload = [ordered]@{ receipt = "$stem.json"; seal = "$stem.seal" } }
    }
    if ($Class -eq 'budget_cap') {
        return [pscustomobject]@{ Event = 'E6'; Payload = [ordered]@{ tokens = Get-UsageTokens $Output } }
    }
    return $null
}

# The R§5.2 class of one finalizing run. Returns Class, Missing (done evidence) and Signals.
function Get-RunClass($Run) {
    $segment = Get-Prop $Run 'segment'
    $manifest = Get-Prop $Run 'manifest'
    $root = Get-Prop $manifest 'project_root'
    $planFolder = Get-Prop $manifest 'plan_folder'
    $signals = [ordered]@{}
    $missing = [System.Collections.Generic.List[string]]::new()
    $phased = @(Get-Prop $Run 'phases' | Where-Object { $_ }).Count -gt 0
    $seal = $null
    $output = $null
    $verdict = {
        param([string]$Class)
        $phaseEvent = if ($phased) { Get-ClassPhaseEvent $Class $seal $output } else { $null }
        [pscustomobject]@{ Class = $Class; Missing = @($missing); Signals = $signals; Phase = $phaseEvent }
    }
    if ($phased) { $signals.phase_state = Get-Prop $Run 'phase_state' }

    # 1. the launcher record.
    $segmentClass = [string](Get-Prop $segment 'stop_class')
    $signals.segment_class = $segmentClass
    if ($segmentClass -eq 'launch_failed') { return & $verdict 'launch_failed' }
    if ($segmentClass -eq 'cancelled' -or (Get-Prop $segment 'cancel_requested_utc')) { return & $verdict 'cancelled' }

    # 2-4. the dispatch artifacts.
    $dispatchId = Get-Prop $segment 'dispatch_id'
    $folder = if ($dispatchId) { Join-Path $script:OutDir ([string]$dispatchId) } else { $null }
    $statusFile = if ($folder) { Read-JsonSignal (Join-Path $folder 'status.json') } else { Read-JsonSignal $null }
    $outputFile = if ($folder) { Read-JsonSignal (Join-Path $folder 'output.json') } else { Read-JsonSignal $null }
    $stderr = if ($folder) { Read-TextFile (Join-Path $folder 'stderr.txt') } else { $null }
    $final = if ($folder) { Read-TextFile (Join-Path $folder 'final.md') } else { $null }
    $status = $statusFile.Value
    $output = $outputFile.Value

    $exitCode = Get-Prop $status 'exit_code'
    if ($null -eq $exitCode) { $exitCode = Get-Prop $segment 'exit_code' }
    $subtype = [string](Get-Prop $output 'subtype')
    $isError = (Get-Prop $output 'is_error') -eq $true
    $signals.exit_code = $exitCode
    $signals.subtype = $subtype
    $signals.result_files = @(@('status.json', 'output.json') | Where-Object { ($_ -eq 'status.json' -and $statusFile.Present) -or ($_ -eq 'output.json' -and $outputFile.Present) })

    if ((Get-Prop $status 'timed_out') -eq $true) { return & $verdict 'timeout' }
    if ($subtype -eq 'error_max_budget_usd') { return & $verdict 'budget_cap' }
    $failed = ($null -ne $exitCode -and [int]$exitCode -ne 0) -or $isError -or $subtype -like 'error*'
    if ($failed) {
        $errorText = [string]$stderr
        if ($isError) { $errorText += "`n" + [string](Get-Prop $output 'result') }
        if ($errorText -match $script:BillingPattern) { return & $verdict 'billing' }
        if ($errorText -match $script:TransientPattern) { return & $verdict 'transient_api' }
        if ($errorText -match $script:AuthPattern) { return & $verdict 'auth_config' }
    }

    # 4-6. the Status grammar, task.md and the completion evidence.
    $statusLine = Get-StatusLine $final
    $signals.status_line = $statusLine
    $task = Read-TaskState $root $planFolder
    $signals.stop_gate = $task.StopGate
    $signals.open_rows = $task.OpenRows
    if ($statusLine -ceq 'DONE') {
        if (-not $root -or -not $planFolder) { $missing.Add('manifest') }
        else {
            $preflight = Invoke-Preflight ([string]$root) ([string]$planFolder)
            if ($null -eq $preflight) { $missing.Add('preflight') }
            else {
                # Completion evidence is exit 0 AND ok=true. Any other answer (a usage error with
                # missing=[], a nonzero exit, ok=false or no ok) is no evidence (AC-E.2). When the
                # answer names no missing check, the missing item is the preflight itself.
                $result = $preflight.Result
                $named = 0
                foreach ($item in @(Get-Prop $result 'missing')) { if ($item) { $missing.Add([string]$item); $named++ } }
                $accepted = $preflight.ExitCode -eq 0 -and (Get-Prop $result 'ok') -eq $true
                if (-not $accepted -and $named -eq 0) {
                    $signals.preflight = [ordered]@{ exit_code = $preflight.ExitCode; ok = Get-Prop $result 'ok'; error = Get-Prop $result 'error' }
                    $missing.Add('preflight')
                }
            }
        }
        $isExec = [string](Get-Prop $manifest 'kind') -eq 'exec' -or [string](Get-Prop $Run 'kind') -eq 'exec'
        if ($isExec) {
            $landings = @(Get-Prop $Run 'landings')
            if (-not @($landings | Where-Object { [string](Get-Prop $_ 'part') -eq 'product' }).Count) { $missing.Add('capture') }
            if (-not @($landings | Where-Object { [string](Get-Prop $_ 'part') -eq 'closeout' -and (Get-Prop $_ 'sealed_utc') }).Count) { $missing.Add('seal') }
        }
        # A phased run's exec phase is sealed only on the verified evidence (V6-050, D-17).
        if ($missing.Count -eq 0 -and $phased) {
            $seal = Invoke-FinalSeal $Run
            if (-not $seal) { $missing.Add('final_seal') }
        }
        if ($missing.Count -eq 0) { return & $verdict 'done' }
        return & $verdict 'done_unverified'
    }
    if ($statusLine -ceq 'PARKED:approved') {
        if (Test-PlanReviewApproved $root $planFolder) { return & $verdict 'parked' }
        $missing.Add('plan_review_approved')
        return & $verdict 'unknown'
    }
    if ($statusLine -cmatch '^STOPPED:([a-z_]+)$') {
        $stopped = $Matches[1]
        if ($script:StoppedGates.ContainsKey($stopped) -and $task.StopGate -eq $script:StoppedGates[$stopped]) { return & $verdict $stopped }
        $missing.Add("stop_gate:$($script:StoppedGates[$stopped])")
        return & $verdict 'unknown'
    }

    # A phased run with no Status has no terminal record: the tool writes E9 (V6-049). A refusal
    # leaves the run finalizing for a later pass (class $null).
    if ($phased -and $null -eq $statusLine) {
        $stoppedAs = Invoke-NoRecordStop $Run $segment
        $signals.no_record = if ($stoppedAs) { 'stopped' } else { 'pending' }
        return & $verdict $stoppedAs
    }

    # The background-wait shape (S1 2026-10-14): a clean exit, no terminal Status, an armed task.md.
    $cleanExit = ($null -ne $exitCode -and [int]$exitCode -eq 0) -or $subtype -eq 'success'
    $duringExecution = $subtype -eq 'error_during_execution' -and $null -eq (Get-Prop $output 'stop_reason')
    if (($cleanExit -or $duringExecution) -and $task.Exists -and $task.StopGate -eq 'armed' -and $task.OpenRows -gt 0) {
        $said = [string]$final + "`n" + [string](Get-Prop $output 'result')
        if ($said -match $script:WaitPattern) { return & $verdict 'background_wait_exit' }
        $missing.Add('wait_evidence')
        return & $verdict 'unknown'
    }

    # 8. no result at all: the host events of the interval.
    if (-not $statusFile.Present -and -not $outputFile.Present) {
        $kinds = @(Get-IntervalEventKinds $segment)
        $signals.host_events = $kinds
        if ([string](Get-Prop $segment 'boot_id') -ne $script:Boot) { return & $verdict 'reboot' }
        if ($kinds -contains 'sleep') { return & $verdict 'sleep_death' }
        return & $verdict 'death_unknown'
    }
    return & $verdict 'unknown'
}

function Set-RunClass($Run) {
    $runId = [string](Get-Prop $Run 'run_id')
    $segment = Get-Prop $Run 'segment'
    $verdict = Get-RunClass $Run
    if (-not $verdict.Class) { return $false }
    $target = switch ($verdict.Class) {
        'done' { 'done' }
        'done_unverified' { 'done_unverified' }
        'parked' { 'parked' }
        default { 'stopped' }
    }
    $ref = if ($segment -and (Get-Prop $segment 'segment_id')) { [string](Get-Prop $segment 'segment_id') } else { $runId }
    $body = [ordered]@{
        class    = $verdict.Class
        missing  = @($verdict.Missing)
        signals  = $verdict.Signals
        cost_usd = Get-Prop $segment 'session_total_usd'
    }
    $null = Invoke-Store 'classify' @('--run-id', $runId, '--to', $target, '--class', $verdict.Class,
        '--notice-ref', $ref, '--notice-json', ($body | ConvertTo-Json -Compress -Depth 6))
    Write-MonitorLog 'INFO' 'run_classified' @{ run_id = $runId; state = $target; class = $verdict.Class; missing = @($verdict.Missing) }
    # EA-21, EA-23: the phase event of the class, after the class is stored; a failed call leaves it.
    $phaseEvent = $verdict.Phase
    if ($phaseEvent) {
        if ($null -eq $phaseEvent.Payload) {
            Write-MonitorLog 'WARN' 'phase_call_failed' @{ run_id = $runId; phase_event = $phaseEvent.Event; reason = 'generation_missing' }
        } else {
            $null = Invoke-PhaseCall $Run $phaseEvent.Event $phaseEvent.Payload
        }
    }
    return $true
}

# --- step 6: the notices ----------------------------------------------------------------------

# The agent_notify.py class of one notice.
function Get-NotifyClass($Notice) {
    $kind = [string](Get-Prop $Notice 'kind')
    if ($kind -eq 'stop') {
        switch ([string](Get-Prop (Get-Prop $Notice 'body') 'class')) {
            'done' { return 'done' }
            'parked' { return 'approval' }
            'decision' { return 'decision' }
            { $_ -in @('done_unverified', 'handback', 'round_cap', 'reviewer_unavailable', 'base_moved') } { return 'blocked' }
            default { return 'error' }
        }
    }
    if ($kind -eq 'decision') { return 'decision' }
    if ($kind -eq 'decision_resolved') { return 'waiting' }
    return 'blocked'
}

# The default notifier: one mail through tools/agent_notify.py send. A non-zero exit throws.
function Send-NoticeMail($Notice) {
    $text = "$($Notice.subject)`n`n$(($Notice.body | ConvertTo-Json -Depth 6))"
    $psi = [System.Diagnostics.ProcessStartInfo]::new((Get-CreditsPython))
    foreach ($a in @('-X', 'utf8', $script:NotifyTool, 'send', '--class', (Get-NotifyClass $Notice), '--text', $text)) { $psi.ArgumentList.Add([string]$a) }
    $psi.UseShellExecute = $false
    $psi.CreateNoWindow = $true
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true
    $proc = [System.Diagnostics.Process]::Start($psi)
    try {
        $outTask = $proc.StandardOutput.ReadToEndAsync()
        $errTask = $proc.StandardError.ReadToEndAsync()
        if (-not $proc.WaitForExit($script:ChildTimeoutMs)) {
            try { $proc.Kill($true) } catch { Write-MonitorLog 'WARN' 'notify_kill_failed' @{ error = $_.Exception.Message } }
            throw "agent_notify.py send did not end in $($script:ChildTimeoutMs / 1000) s"
        }
        $proc.WaitForExit()
        $null = $outTask.Result
        if ($proc.ExitCode -ne 0) { throw "agent_notify.py send exit $($proc.ExitCode): $(([string]$errTask.Result).Trim())" }
    } finally {
        $proc.Dispose()
    }
}

function Send-DueNotices {
    $due = Invoke-Store 'notices_due'
    $sent = 0
    foreach ($item in @(Get-Prop $due 'notices')) {
        if ($null -eq $item) { continue }
        $key = [string](Get-Prop $item 'notice_key')
        $notice = [pscustomobject]@{
            subject    = [string](Get-Prop $item 'subject')
            notice_key = $key
            kind       = [string](Get-Prop $item 'kind')
            run_id     = Get-Prop $item 'run_id'
            ref        = Get-Prop $item 'ref'
            body       = Get-Prop $item 'body'
            attempts   = Get-Prop $item 'attempts'
        }
        try {
            $null = & $script:Send $notice
        } catch {
            $message = [string]$_.Exception.Message
            if (-not $message.Trim()) { $message = 'the send failed' }
            if ($message.Length -gt 1000) { $message = $message.Substring(0, 1000) }
            $null = Invoke-Store 'notice_failed' @('--key', $key, '--error', $message)
            Write-MonitorLog 'WARN' 'notice_send_failed' @{ notice_key = $key; error = $message }
            continue
        }
        $null = Invoke-Store 'notice_sent' @('--key', $key)
        $sent += 1
    }
    return $sent
}

# The default chain starter: Start-CreditsRunTask.ps1 -StartedBy monitor-chain in a child pwsh.
# It files the start request, starts the task and waits for accepted, not for the run's outcome:
# exit 0 (an outcome) and exit 4 (accepted_pending) are a start. Any other exit throws.
function Start-ChainRun($Candidate) {
    $psi = [System.Diagnostics.ProcessStartInfo]::new((Join-Path $PSHOME 'pwsh.exe'))
    $taskArgs = @('-NoProfile', '-NonInteractive', '-File', $script:TaskStarter,
        '-RunId', [string](Get-Prop $Candidate 'run_id'), '-StartedBy', 'monitor-chain',
        '-ChainId', [string](Get-Prop $Candidate 'chain_id'), '-StateDb', $script:Db,
        '-OutcomeTimeoutMs', '1')
    foreach ($a in $taskArgs) { $psi.ArgumentList.Add([string]$a) }
    $psi.UseShellExecute = $false
    $psi.CreateNoWindow = $true
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true
    $proc = [System.Diagnostics.Process]::Start($psi)
    try {
        $outTask = $proc.StandardOutput.ReadToEndAsync()
        $errTask = $proc.StandardError.ReadToEndAsync()
        if (-not $proc.WaitForExit($script:ChainChildTimeoutMs)) {
            try { $proc.Kill($true) } catch { Write-MonitorLog 'WARN' 'chain_start_kill_failed' @{ error = $_.Exception.Message } }
            throw "Start-CreditsRunTask.ps1 did not end in $($script:ChainChildTimeoutMs / 1000) s"
        }
        $proc.WaitForExit()
        $line = ([string]$outTask.Result).Trim()
        if ($proc.ExitCode -notin @(0, 4)) { throw "Start-CreditsRunTask.ps1 exit $($proc.ExitCode): $line $(([string]$errTask.Result).Trim())" }
        return $line
    } finally {
        $proc.Dispose()
    }
}

# Step 6: one start for each ready chain run. A failed start is logged and the run stays a
# candidate for the next pass.
function Start-ReadyChains {
    $started = 0
    $view = Invoke-Store 'chain_candidates'
    foreach ($candidate in @(Get-Prop $view 'candidates')) {
        if ($null -eq $candidate) { continue }
        $runId = [string](Get-Prop $candidate 'run_id')
        $chainId = [string](Get-Prop $candidate 'chain_id')
        $candidateError = Get-Prop $candidate 'error'
        if ($candidateError) { Write-MonitorLog 'WARN' 'chain_candidate_error' @{ run_id = $runId; chain_id = $chainId; error = [string]$candidateError } }
        if (-not [bool](Get-Prop $candidate 'ready')) { continue }
        try {
            $null = & $script:StartChain $candidate
            $started += 1
            Write-MonitorLog 'INFO' 'chain_started' @{ run_id = $runId; chain_id = $chainId; base_commit = [string](Get-Prop $candidate 'base_commit') }
        } catch {
            Write-MonitorLog 'ERROR' 'chain_start_failed' @{ run_id = $runId; chain_id = $chainId; error = $_.Exception.Message }
        }
    }
    return $started
}

# Scan each attached orchestrator session (report section 4.4 step 3; section 4.6.3). A broken
# session is skipped: only a new attach makes it ok again. A refusal (exit 3) is the store's
# record of a broken history or a missing transcript; it never ends the pass.
function Invoke-TranscriptScans {
    $listed = Invoke-Store 'orchestrator_sessions'
    $scanned = 0
    foreach ($row in @(Get-Prop $listed 'sessions')) {
        if ($null -eq $row) { continue }
        if ([string](Get-Prop $row 'history_state') -ne 'ok') { continue }
        $runId = [string](Get-Prop $row 'run_id')
        $session = [string](Get-Prop $row 'session')
        $res = Invoke-CreditsState -StateDb $script:Db -Verb scan_transcript -Arguments @('--run-id', $runId, '--session', $session) -NowUtc $script:Clock
        if ($res.Code -eq 0) {
            $scanned += 1
            continue
        }
        $level = if ($res.Code -eq 3) { 'WARN' } else { 'ERROR' }
        Write-MonitorLog $level 'transcript_scan_refused' @{ run_id = $runId; session = $session; error = (Format-CreditsStateError $res) }
    }
    return $scanned
}

# --- one pass ---------------------------------------------------------------------------------

function Invoke-MonitorPass {
    $limit = (Get-CreditsConstants).ORPHAN_REQUEST_S
    $requests = Invoke-Store 'scan_requests'
    foreach ($requestId in @(Get-Prop $requests 'orphaned')) {
        if (-not $requestId) { continue }
        Write-MonitorLog 'WARN' 'credits_limit_tripped' @{ limit_name = 'ORPHAN_REQUEST_S'; configured_value = $limit; window = 'orphan_request'; request_id = [string]$requestId }
    }

    $view = Invoke-Store 'monitor_view'
    $covered = [System.Collections.Generic.HashSet[string]]::new()
    $attemptProofs = [ordered]@{}
    foreach ($attempt in @(Get-Prop $view 'attempts')) {
        if ($null -eq $attempt) { continue }
        $segmentId = Get-Prop $attempt 'segment_id'
        if ($segmentId) { [void]$covered.Add([string]$segmentId) }
        $proof = Get-AttemptProof $attempt
        if ($proof) { $attemptProofs[[string](Get-Prop $attempt 'attempt_id')] = $proof }
    }
    if ($attemptProofs.Count -gt 0) { $null = Invoke-Store 'scan_attempts' @('--proofs-json', ($attemptProofs | ConvertTo-Json -Compress)) }

    $view = Invoke-Store 'monitor_view'
    $segmentProofs = [ordered]@{}
    foreach ($segment in @(Get-Prop $view 'segments')) {
        if ($null -eq $segment) { continue }
        $segmentId = [string](Get-Prop $segment 'segment_id')
        if ($covered.Contains($segmentId)) { continue }
        $proof = Get-SegmentProof $segment
        if ($proof) { $segmentProofs[$segmentId] = $proof }
    }
    if ($segmentProofs.Count -gt 0) { $null = Invoke-Store 'scan_segments' @('--proofs-json', ($segmentProofs | ConvertTo-Json -Compress)) }

    $view = Invoke-Store 'monitor_view'
    $classified = 0
    foreach ($run in @(Get-Prop $view 'runs')) {
        if ($null -eq $run) { continue }
        try {
            if (Set-RunClass $run) { $classified += 1 }
        } catch {
            Write-MonitorLog 'ERROR' 'classify_failed' @{ run_id = [string](Get-Prop $run 'run_id'); error = $_.Exception.Message }
        }
    }

    $chains = Start-ReadyChains

    $transcripts = Invoke-TranscriptScans

    $null = Invoke-Store 'outbox_scan'
    $sent = Send-DueNotices
    $null = Invoke-Store 'scan_effects'
    return [pscustomobject]@{ Attempts = $attemptProofs.Count; Segments = $segmentProofs.Count; Classified = $classified; Chains = $chains; Transcripts = $transcripts; Sent = $sent }
}

# --- main -------------------------------------------------------------------------------------

$result = $null
$code = 0
$leaseArgs = $null
$leaseTaken = $false
try {
    $script:Db = [System.IO.Path]::GetFullPath($(if ($StateDb) { $StateDb } else { Get-LauncherDefault 'StateDb' }))
    $script:OutDir = [System.IO.Path]::GetFullPath($(if ($OutputDir) { $OutputDir } else { Get-LauncherDefault 'OutputDir' }))
    $storeFolder = Split-Path -Parent $script:Db
    $script:LogPath = Join-Path $storeFolder 'logs/monitor.jsonl'
    $rescan = Join-Path $storeFolder 'rescan.request'
    $script:Clock = $NowUtc
    $script:NowTime = if ($null -ne $NowUtc) { ConvertTo-UtcTime ([datetime]$NowUtc) } else { [datetime]::UtcNow }
    $script:Boot = Get-CreditsBootId
    $script:Send = if ($Notifier) { $Notifier } else { { param($notice) Send-NoticeMail $notice } }
    $script:StartChain = if ($ChainStarter) { $ChainStarter } else { { param($candidate) Start-ChainRun $candidate } }

    # 1. the lease.
    $self = Get-Process -Id $PID
    $leaseArgs = @('--pid', [string]$PID, '--created', (Format-CreditsUtc $self.StartTime), '--boot-id', $script:Boot)
    $lease = Invoke-Store 'lease' $leaseArgs
    if ([string](Get-Prop $lease 'outcome') -eq 'held') {
        $holderState = if ([string](Get-Prop $lease 'boot_id') -ne $script:Boot) { 'dead' } else { Get-IdentityState (Get-Prop $lease 'pid') (Get-Prop $lease 'created') }
        if ($holderState -eq 'dead') {
            $lease = Invoke-Store 'lease' ($leaseArgs + @('--takeover', [string](Get-Prop $lease 'holder')))
        }
    }
    if ([string](Get-Prop $lease 'outcome') -ne 'taken') {
        $note = [ordered]@{ key = 'lease_held'; at_utc = $script:NowTime.ToString('yyyy-MM-ddTHH:mm:ssZ') } | ConvertTo-Json -Compress
        [System.IO.File]::WriteAllText($rescan, $note + "`n", [System.Text.UTF8Encoding]::new($false))
        Write-MonitorLog 'INFO' 'lease_held' @{ holder = [string](Get-Prop $lease 'holder') }
        $result = [ordered]@{ outcome = 'lease_held'; holder = [string](Get-Prop $lease 'holder') }
    } else {
        $leaseTaken = $true
        if (Get-Prop $lease 'previous') { Write-MonitorLog 'WARN' 'lease_taken_over' @{ previous = [string](Get-Prop $lease 'previous') } }
        # 2-6. the passes: a second one when a rescan was asked for during the first.
        $passes = [System.Collections.Generic.List[object]]::new()
        do {
            if (Test-Path -LiteralPath $rescan) { Remove-Item -LiteralPath $rescan -Force }
            $passes.Add((Invoke-MonitorPass))
        } while ($passes.Count -lt 2 -and (Test-Path -LiteralPath $rescan))
        $summary = [ordered]@{
            passes     = $passes.Count
            classified = ($passes | Measure-Object -Property Classified -Sum).Sum
            chains     = ($passes | Measure-Object -Property Chains -Sum).Sum
            sent       = ($passes | Measure-Object -Property Sent -Sum).Sum
        }
        Write-MonitorLog 'INFO' 'pass_done' $summary
        $result = [ordered]@{ outcome = 'pass' } + $summary
    }
} catch {
    $code = 1
    $message = $_.Exception.Message
    try { Write-MonitorLog 'ERROR' 'monitor_failed' @{ error = $message } } catch { [Console]::Error.WriteLine("monitor log failed: $($_.Exception.Message)") }
    $result = [ordered]@{ outcome = 'error'; error = $message }
} finally {
    if ($leaseTaken) {
        try { $null = Invoke-Store 'lease_release' $leaseArgs } catch {
            $code = 1
            [Console]::Error.WriteLine("lease_release failed: $($_.Exception.Message)")
        }
    }
}
Write-Output ($result | ConvertTo-Json -Compress -Depth 4)
exit $code
