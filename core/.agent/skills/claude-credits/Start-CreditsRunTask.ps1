<#
.SYNOPSIS
    Start one registered credits run (report section 4.2). This script is the only start route:
    it files one single-use start request, starts the run's Task Scheduler task and follows the
    request until the launcher reports an outcome.

.DESCRIPTION
    The script:
      0. reads credits_start_policy from the credits config: human-only (the template
         default) refuses an agent-on-user-chat start; agent-on-user-chat allows it. A
         human-command start and a monitor-chain start are allowed under both values;
      1. reads the run's task back through the scheduler adapter (a missing task is refused);
      2. files the start request (store verb request), which moves the run to requested. A
         human-command start records the OS user and the host; an agent-on-user-chat start needs
         the user's quote; a resume needs a stopped run;
      3. starts the task (Start-ScheduledTask through the adapter);
      4. waits up to REQUEST_ACCEPT_TIMEOUT_S (120 s) for the launcher to accept the request. With
         no accept it marks the request not_started (caller_timeout) only when it is still pending
         (a compare-and-set in the store); a request that a launcher accepted meanwhile stays;
      5. waits up to 180 s more for launched, rejected or launch_failed and reports it. With no
         outcome it reports accepted_pending: the monitor reconciles the attempt.

    Only the request state counts: under IgnoreNew a task start can report success without a launch.

    The script prints one JSON line with an outcome and exits:
      0  launched (with the dispatch id);
      1  not_started, rejected or launch_failed;
      3  refused (the store refused the request, the run has no task, -ResumeMode or -Brief
         without -Resume, a -Brief file that does not exist, an unusable credits config
         (config_invalid), or the start policy (start_policy));
      4  accepted_pending (accepted, the outcome is not known yet);
      9  an unexpected error.

.EXAMPLE
    pwsh -NoProfile -File .agent/skills/claude-credits/Start-CreditsRunTask.ps1 -RunId my-plan-exec -StartedBy human-command
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][ValidatePattern('^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$')][string]$RunId,

    [Parameter(Mandatory = $true)][ValidateSet('human-command', 'agent-on-user-chat', 'monitor-chain')][string]$StartedBy,

    # The user's own chat words that name this run and say start (or resume). Needed for
    # agent-on-user-chat.
    [string]$StartQuote,

    # The chain of the run's manifest. Needed for monitor-chain.
    [string]$ChainId,

    # A resume of a stopped run (D-2: only on the human's explicit resume request).
    [switch]$Resume,

    # The resume mode (report section 5.3). session (the default, D-4 A) continues the source
    # session with claude --resume; fresh starts a new session with the brief alone.
    [ValidateSet('session', 'fresh')][string]$ResumeMode,

    # The resume brief (templates/resume-brief.md filled in for this run). A relative path is
    # taken from the current folder. The store keeps the absolute path.
    [string]$Brief,

    # The credits config that holds credits_start_policy. Default: $env:CREDITS_CONFIG, else
    # .agent/credits/config.json of this repository.
    [string]$ConfigPath,

    [string]$StateDb = '{{RECEIPTS_DIR}}/credits/state.db',

    # The Task Scheduler adapter: a hashtable of Register, Get and Start script blocks.
    # Default: New-CreditsSchedulerAdapter (the real Task Scheduler).
    [hashtable]$Scheduler,

    # The wait for accepted. The value can only lower REQUEST_ACCEPT_TIMEOUT_S: the script uses
    # min(value, 120000).
    [ValidateRange(1, 2147483647)][int]$AcceptTimeoutMs = 120000,

    # How often the script reads the request state.
    [ValidateRange(10, 60000)][int]$PollIntervalMs = 1000,

    # The wait for the outcome after accepted. The script uses min(value, 180000).
    [ValidateRange(1, 2147483647)][int]$OutcomeTimeoutMs = 180000
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

Import-Module -Name (Join-Path $PSScriptRoot 'CreditsRun.psm1') -Force -DisableNameChecking -ErrorAction Stop

# Report section 4.2: the caller waits 180 s for an outcome after the accept.
$OutcomeWaitCapMs = 180000
$TaskPath = '\{{PROJECT_NAME_TITLE}}\Credits\'
$FinalStates = @('launched', 'rejected', 'launch_failed', 'not_started')
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot '../../..')).Path
$StartPolicies = @('human-only', 'agent-on-user-chat')

function Write-Result([System.Collections.Specialized.OrderedDictionary]$Payload, [int]$Code) {
    Write-Output ($Payload | ConvertTo-Json -Compress -Depth 6)
    $global:LASTEXITCODE = $Code
}

function Get-Field($Object, [string]$Name) {
    if ($null -eq $Object) { return $null }
    $prop = $Object.PSObject.Properties[$Name]
    if ($null -eq $prop) { return $null }
    return $prop.Value
}

# The credits_start_policy of the credits config: Policy ($null when the config cannot be
# used), Path and Message. Register-CreditsRun.ps1 checks the whole config.
function Get-StartPolicy([string]$Path) {
    if (-not $Path) { $Path = if ($env:CREDITS_CONFIG) { $env:CREDITS_CONFIG } else { Join-Path $RepoRoot '.agent/credits/config.json' } }
    $result = [ordered]@{ Policy = $null; Path = $Path; Message = '' }
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { $result.Message = "the credits config does not exist: $Path"; return $result }
    try { $cfg = ConvertFrom-Json -InputObject ([System.IO.File]::ReadAllText($Path)) -AsHashtable -ErrorAction Stop }
    catch { $result.Message = "the credits config is not JSON: $($_.Exception.Message)"; return $result }
    if (-not ($cfg -is [System.Collections.IDictionary]) -or -not $cfg.ContainsKey('credits_start_policy')) {
        $result.Message = "the credits config has no credits_start_policy: $Path"; return $result
    }
    $value = $cfg['credits_start_policy']
    if (-not ($value -is [string]) -or $value -cnotin $StartPolicies) {
        $result.Message = "credits_start_policy must be human-only or agent-on-user-chat: $Path"; return $result
    }
    $result.Policy = $value
    return $result
}

# A store time as a UTC [datetime]. ConvertFrom-Json may give a [datetime] already; else parse.
function ConvertFrom-StoreUtc($Value) {
    if ($null -eq $Value) { return $null }
    if ($Value -is [datetime]) {
        if ($Value.Kind -eq [System.DateTimeKind]::Unspecified) { return [datetime]::SpecifyKind($Value, [System.DateTimeKind]::Utc) }
        return $Value.ToUniversalTime()
    }
    $styles = [System.Globalization.DateTimeStyles]::AssumeUniversal -bor [System.Globalization.DateTimeStyles]::AdjustToUniversal
    $parsed = [datetime]::MinValue
    if ([datetime]::TryParse([string]$Value, [System.Globalization.CultureInfo]::InvariantCulture, $styles, [ref]$parsed)) { return $parsed }
    return $null
}

# The request and its attempt from run_status. Throws when the store fails.
function Get-RequestView([string]$RequestId) {
    $res = Invoke-CreditsState -StateDb $StateDb -Verb run_status -Arguments @('--run-id', $RunId)
    if ($res.Code -ne 0 -or $null -eq $res.Payload) { throw "credits_state.py run_status failed: $(Format-CreditsStateError $res)" }
    $request = @(Get-Field $res.Payload 'requests') | Where-Object { $null -ne $_ -and [string]$_.request_id -eq $RequestId } | Select-Object -First 1
    if ($null -eq $request) { throw "request $RequestId is not in the store" }
    $attempt = @(Get-Field $res.Payload 'attempts') | Where-Object { $null -ne $_ -and [string]$_.request_id -eq $RequestId } | Select-Object -Last 1
    return [pscustomobject]@{ Request = $request; Attempt = $attempt }
}

# Poll until the request state is in $States or the wait ends. Returns the last view.
function Wait-RequestState([string]$RequestId, [string[]]$States, [int]$WaitMs) {
    $clock = [System.Diagnostics.Stopwatch]::StartNew()
    while ($true) {
        $view = Get-RequestView $RequestId
        if ([string]$view.Request.state -in $States) { return $view }
        if ($clock.ElapsedMilliseconds -ge $WaitMs) { return $view }
        Start-Sleep -Milliseconds ([math]::Min($PollIntervalMs, [math]::Max(1, $WaitMs - $clock.ElapsedMilliseconds)))
    }
}

# The payload and exit code for a request in a final state.
function Get-FinalResult([string]$RequestId, $View) {
    $state = [string]$View.Request.state
    $payload = [ordered]@{ outcome = $state; run_id = $RunId; request_id = $RequestId }
    if ($state -eq 'launched') {
        $payload.dispatch_id = Get-Field $View.Attempt 'dispatch_id'
        return [pscustomobject]@{ Payload = $payload; Code = 0 }
    }
    $reason = Get-Field $View.Request 'reason'
    if ($null -eq $reason) { $reason = Get-Field $View.Attempt 'reason' }
    $payload.reason = $reason
    return [pscustomobject]@{ Payload = $payload; Code = 1 }
}

try {
    if ($null -eq $Scheduler) { $Scheduler = New-CreditsSchedulerAdapter }
    $StateDb = [System.IO.Path]::GetFullPath($StateDb)
    $acceptWaitMs = [math]::Min($AcceptTimeoutMs, (Get-CreditsConstants).REQUEST_ACCEPT_TIMEOUT_S * 1000)
    $outcomeWaitMs = [math]::Min($OutcomeTimeoutMs, $OutcomeWaitCapMs)

    # --- step 0: the resume arguments; nothing is filed for a call that cannot be a resume
    if (-not $Resume -and ($ResumeMode -or $Brief)) {
        Write-Result ([ordered]@{ outcome = 'refused'; run_id = $RunId; reason = 'resume_only'; message = '-ResumeMode and -Brief belong to a resume (-Resume)' }) 3
        exit 3
    }
    $briefPath = $null
    if ($Brief) {
        $briefPath = if ([System.IO.Path]::IsPathRooted($Brief)) { $Brief } else { Join-Path (Get-Location).ProviderPath $Brief }
        if (-not (Test-Path -LiteralPath $briefPath -PathType Leaf)) {
            Write-Result ([ordered]@{ outcome = 'refused'; run_id = $RunId; reason = 'brief_missing'; message = "no resume brief at $briefPath" }) 3
            exit 3
        }
    }

    # --- step 0b: the start policy; nothing is read from the scheduler or the store first
    $policy = Get-StartPolicy $ConfigPath
    if ($null -eq $policy.Policy) {
        Write-Result ([ordered]@{ outcome = 'refused'; run_id = $RunId; reason = 'config_invalid'; message = $policy.Message }) 3
        exit 3
    }
    if ($StartedBy -eq 'agent-on-user-chat' -and $policy.Policy -cne 'agent-on-user-chat') {
        $text = "credits_start_policy is $($policy.Policy) in $($policy.Path): an agent-on-user-chat start needs agent-on-user-chat; " +
            'a human starts the run with -StartedBy human-command'
        Write-Result ([ordered]@{ outcome = 'refused'; run_id = $RunId; reason = 'start_policy'; message = $text }) 3
        exit 3
    }

    # --- step 1: the run's task must exist; nothing is filed for a run that cannot start
    if ($null -eq (& $Scheduler['Get'] $TaskPath $RunId)) {
        Write-Result ([ordered]@{ outcome = 'refused'; run_id = $RunId; reason = 'task_missing'; message = "no task $TaskPath$RunId; run Register-CreditsRun.ps1" }) 3
        exit 3
    }

    # --- step 2: the single-use start request
    $requestArgs = @('--run-id', $RunId, '--started-by', $StartedBy, '--request-id', [guid]::NewGuid().ToString())
    if ($StartQuote) { $requestArgs += @('--quote', $StartQuote) }
    if ($ChainId) { $requestArgs += @('--chain-id', $ChainId) }
    if ($Resume) { $requestArgs += @('--resume', '--resume-mode', $(if ($ResumeMode) { $ResumeMode } else { 'session' })) }
    if ($briefPath) { $requestArgs += @('--brief', $briefPath) }
    if ($StartedBy -eq 'human-command') { $requestArgs += @('--requested-by', "$([Environment]::UserName)@$([Environment]::MachineName)") }
    $res = Invoke-CreditsState -StateDb $StateDb -Verb request -Arguments $requestArgs
    if ($res.Code -eq 3) {
        $errorCode = [string](Get-Field $res.Payload 'error')
        $message = [string](Get-Field $res.Payload 'message')
        Write-Result ([ordered]@{ outcome = 'refused'; run_id = $RunId; reason = $errorCode; message = $message }) 3
        exit 3
    }
    if ($res.Code -ne 0 -or $null -eq $res.Payload) { throw "credits_state.py request failed: $(Format-CreditsStateError $res)" }
    $requestId = [string](Get-Field $res.Payload 'request_id')

    # --- step 3: start the task. A failed start leaves the request pending; the monitor ends it
    # as an orphan (ORPHAN_REQUEST_S).
    try {
        $null = & $Scheduler['Start'] $TaskPath $RunId
    } catch {
        Write-Result ([ordered]@{ outcome = 'error'; run_id = $RunId; request_id = $requestId; message = "the task did not start: $($_.Exception.Message)" }) 9
        exit 9
    }

    # --- step 4: wait for accepted
    $view = Wait-RequestState $requestId (@('accepted', 'admitted') + $FinalStates) $acceptWaitMs
    if ([string]$view.Request.state -eq 'pending') {
        $created = ConvertFrom-StoreUtc $view.Request.created_utc
        $notStartedArgs = @{ StateDb = $StateDb; Verb = 'not_started'; Arguments = @('--request-id', $requestId, '--reason', 'caller_timeout') }
        # A wait lowered by -AcceptTimeoutMs (tests) runs the compare-and-set on the store clock of
        # a full REQUEST_ACCEPT_TIMEOUT_S, which the store requires for caller_timeout.
        if ($acceptWaitMs -lt (Get-CreditsConstants).REQUEST_ACCEPT_TIMEOUT_S * 1000 -and $null -ne $created) {
            $notStartedArgs.NowUtc = $created.AddSeconds((Get-CreditsConstants).REQUEST_ACCEPT_TIMEOUT_S)
        }
        $res = Invoke-CreditsState @notStartedArgs
        $errorCode = [string](Get-Field $res.Payload 'error')
        if ($res.Code -eq 0) {
            Write-Result ([ordered]@{ outcome = 'not_started'; run_id = $RunId; request_id = $requestId; reason = 'caller_timeout' }) 1
            exit 1
        }
        # MX-6: a launcher accepted the request meanwhile; the compare-and-set changed nothing.
        if ($errorCode -ne 'conflict') { throw "credits_state.py not_started failed: $(Format-CreditsStateError $res)" }
        $view = Get-RequestView $requestId
    }

    # --- step 5: wait for the outcome
    if ([string]$view.Request.state -notin $FinalStates) {
        $view = Wait-RequestState $requestId $FinalStates $outcomeWaitMs
    }
    if ([string]$view.Request.state -in $FinalStates) {
        $final = Get-FinalResult $requestId $view
        Write-Result $final.Payload $final.Code
        exit $final.Code
    }
    Write-Result ([ordered]@{
            outcome = 'accepted_pending'; run_id = $RunId; request_id = $requestId; state = [string]$view.Request.state
            dispatch_id = (Get-Field $view.Attempt 'dispatch_id')
            message = 'the launcher accepted the request; check the run with Get-CreditsRun.ps1'
        }) 4
    exit 4
} catch {
    Write-Result ([ordered]@{ outcome = 'error'; run_id = $RunId; message = $_.Exception.Message }) 9
    exit 9
}
