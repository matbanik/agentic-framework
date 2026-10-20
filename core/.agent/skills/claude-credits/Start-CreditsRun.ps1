<#
.SYNOPSIS
    The launcher of one scheduled credits segment (report section 4.3). The run's Task Scheduler
    task starts this script with -RunId only; every other parameter has a default.

.DESCRIPTION
    The launcher:
      1. refuses to run inside a Claude Code session (CLAUDECODE or CLAUDE_CODE_ENTRYPOINT), and
         refuses a run whose launch.working_directory is not its project_root (project_mismatch);
      2. checks the M-1 receipt with run_gate.py when a pending request is younger than
         REQUEST_ACCEPT_TIMEOUT_S (the store has no receipt input, so the check comes first);
      3. accepts the request (store verb accept) and admits the attempt (admit), which claims the
         lane and the reservation and opens a segment. The first start of a manifest with phases
         is also an admission (report section 4.4): before accept, run_parameters.py inspect
         checks the run_parameters block of the brief's ## Authorization section; after admit,
         bind --pending binds the attempt's session as headless. A refusal starts nothing
         (admission_refused);
      4. creates the segment's kill-on-close job and starts Invoke-ClaudeCredits.ps1 -Scheduled
         suspended inside it, with the CLI environment of section 4.3 step 7;
      5. records the wrapper identity (launched) before the wrapper resumes, waits for its
         running.json, watches the job and the cancel mark, and finalizes the segment
         (Complete-CreditsSegment) when the job is empty.

    A descendant that outlives the terminate keeps the segment open: the launcher moves it to
    termination_pending and the monitor finalizes it from the job proof (MX-20).

    The script prints one JSON line with an outcome and exits:
      0  completed, cancelled, start_refused (a store refusal), not_started, rejected or
         admission_refused;
      1  launch_failed, termination_pending, receipt_rejected or project_mismatch;
      3  refused (a nested Claude Code session or a bad argument);
      9  an unexpected error.
    Log records go to <store folder>/logs/launcher-<run id>.jsonl.

.EXAMPLE
    pwsh -NoProfile -File .agent/skills/claude-credits/Start-CreditsRun.ps1 -RunId my-plan-exec
#>

# The script has no param block: pwsh -File refuses a named parameter that is given two times,
# and a caller can append an override to the arguments of the task (the last value is used).
# Read-LauncherArguments reads $args against this table: name → kind, default, range.
$script:ParameterTable = [ordered]@{
    RunId           = @{ Kind = 'string' }
    StateDb         = @{ Kind = 'string'; Default = '{{RECEIPTS_DIR}}/credits/state.db' }
    OutputDir       = @{ Kind = 'string'; Default = '{{RECEIPTS_DIR}}/dispatch' }
    # Default: CLAUDE_CREDITS_KEY_FILE, else ~/.anthropic/claude-credits.key (as Register-CreditsRun.ps1).
    KeyFile         = @{ Kind = 'string' }
    # Default: probes/run_gate.py next to this script.
    RunGate         = @{ Kind = 'string' }
    # Default: <store folder>/receipts/<run id>.gate-result.json, where Register-CreditsRun.ps1 copies it.
    Receipt         = @{ Kind = 'string' }
    # The time the wrapper has to write running.json.
    LaunchWaitMs    = @{ Kind = 'int'; Default = 60000; Min = 1000; Max = 3600000 }
    # The time the job has to become empty after a terminate.
    TerminateWaitMs = @{ Kind = 'int'; Default = 60000; Min = 0; Max = 3600000 }
    # How often the launcher reads the cancel mark of its segment.
    CancelPollMs    = @{ Kind = 'int'; Default = 10000; Min = 100; Max = 600000 }
    # After termination_pending: the time the launcher waits for the job to become empty before it
    # leaves the segment to the monitor.
    PendingWaitMs   = @{ Kind = 'int'; Default = 60000; Min = 0; Max = 3600000 }
    # The store clock for accept (yyyy-MM-ddTHH:mm:ssZ). Tests only.
    NowUtc          = @{ Kind = 'string' }
    # Default: Invoke-ClaudeCredits.ps1 next to this script.
    WrapperScript   = @{ Kind = 'string' }
    # The run-parameters tool of a manifest with phases. Default: tools/run_parameters.py of the project.
    RunParametersTool = @{ Kind = 'string' }
}

# Sets one script variable per table entry from $Tokens (-Name value or -Name:value).
# Returns $null, or the reason the arguments are not valid.
function Read-LauncherArguments([object[]]$Tokens) {
    foreach ($name in $script:ParameterTable.Keys) {
        $default = if ($script:ParameterTable[$name].ContainsKey('Default')) { $script:ParameterTable[$name].Default } else { $null }
        Set-Variable -Scope Script -Name $name -Value $default
    }
    $index = 0
    while ($index -lt $Tokens.Count) {
        $token = [string]$Tokens[$index]
        if ($token -notmatch '^-([A-Za-z]+)(?::(.*))?$') { return "unexpected argument '$token'" }
        $name = @($script:ParameterTable.Keys | Where-Object { $_ -eq $Matches[1] })
        if ($name.Count -ne 1) { return "unknown parameter -$($Matches[1])" }
        $name = [string]$name[0]
        if ($Matches.ContainsKey(2)) {
            $value = [string]$Matches[2]
            $index += 1
        } else {
            if ($index + 1 -ge $Tokens.Count) { return "-$name needs a value" }
            $value = [string]$Tokens[$index + 1]
            $index += 2
        }
        $spec = $script:ParameterTable[$name]
        if ($spec.Kind -eq 'int') {
            $number = 0
            if (-not [int]::TryParse($value, [System.Globalization.NumberStyles]::Integer, [System.Globalization.CultureInfo]::InvariantCulture, [ref]$number)) {
                return "-$name is not an integer: $value"
            }
            if ($number -lt $spec.Min -or $number -gt $spec.Max) { return "-$name must be from $($spec.Min) to $($spec.Max): $number" }
            Set-Variable -Scope Script -Name $name -Value $number
        } else {
            if ([string]::IsNullOrWhiteSpace($value)) { return "-$name is empty" }
            Set-Variable -Scope Script -Name $name -Value $value
        }
    }
    if (-not $script:RunId) { return '-RunId is mandatory' }
    if ($script:RunId -notmatch '^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$') {
        $bad = $script:RunId
        $script:RunId = $null
        return "-RunId is not a run id: $bad"
    }
    return $null
}

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$script:ArgumentError = Read-LauncherArguments $args

$script:Utf8 = [System.Text.UTF8Encoding]::new($false)
$script:LogPath = $null
$script:Job = $null
$script:KeepAwake = $null
$script:WrapperProcess = $null

function New-Result([string]$Outcome, [int]$Code, [hashtable]$Fields = @{}) {
    $payload = [ordered]@{ outcome = $Outcome; run_id = $RunId }
    foreach ($key in $Fields.Keys) { $payload[$key] = $Fields[$key] }
    return [pscustomobject]@{ Payload = $payload; Code = $Code }
}

function Write-LauncherLog([string]$Level, [string]$EventName, [hashtable]$Fields = @{}) {
    if (-not $script:LogPath) { return }
    $record = [ordered]@{
        ts     = [datetime]::UtcNow.ToString('yyyy-MM-ddTHH:mm:ss.fffZ', [System.Globalization.CultureInfo]::InvariantCulture)
        level  = $Level
        event  = $EventName
        run_id = $RunId
    }
    foreach ($key in $Fields.Keys) { $record[$key] = $Fields[$key] }
    try {
        $folder = Split-Path -Parent $script:LogPath
        if (-not (Test-Path -LiteralPath $folder)) { New-Item -ItemType Directory -Force -Path $folder | Out-Null }
        [System.IO.File]::AppendAllText($script:LogPath, ($record | ConvertTo-Json -Compress -Depth 6) + "`n", $script:Utf8)
    } catch {
        [Console]::Error.WriteLine("credits launcher: log write failed: $($_.Exception.Message)")
    }
}

function ConvertFrom-UtcText($Value) {
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

function Get-Field($Object, [string]$Name) {
    if ($null -eq $Object) { return $null }
    if ($Object -is [System.Collections.IDictionary]) { return $Object[$Name] }
    $prop = $Object.PSObject.Properties[$Name]
    if ($null -eq $prop) { return $null }
    return $prop.Value
}

# One argument as the Windows command-line parser (CommandLineToArgvW) reads it back.
function ConvertTo-WindowsArgument([string]$Value) {
    if ($Value.Length -gt 0 -and $Value -notmatch '[\s"]') { return $Value }
    $slash = [char]92
    $text = [System.Text.StringBuilder]::new()
    [void]$text.Append('"')
    $slashes = 0
    foreach ($ch in $Value.ToCharArray()) {
        if ($ch -eq $slash) { $slashes++; continue }
        if ($ch -eq '"') {
            [void]$text.Append($slash, 2 * $slashes + 1)
        } elseif ($slashes -gt 0) {
            [void]$text.Append($slash, $slashes)
        }
        [void]$text.Append($ch)
        $slashes = 0
    }
    if ($slashes -gt 0) { [void]$text.Append($slash, 2 * $slashes) }
    [void]$text.Append('"')
    return $text.ToString()
}

function Read-JsonFile([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { return $null }
    try { return ([System.IO.File]::ReadAllText($Path, [System.Text.Encoding]::UTF8) | ConvertFrom-Json -ErrorAction Stop) }
    catch { return $null }  # The wrapper can be in the middle of the write; the next poll reads it again.
}

function Get-RunStatus {
    $res = Invoke-CreditsState -StateDb $StateDb -Verb run_status -Arguments @('--run-id', $RunId)
    if ($res.Code -ne 0 -or $null -eq $res.Payload) { throw "credits_state.py run_status failed: $(Format-CreditsStateError $res)" }
    return $res.Payload
}

function Get-StoreRefusal($Result) {
    if ($Result.Code -ne 3 -or $null -eq $Result.Payload) { return $null }
    $code = Get-Field $Result.Payload 'error'
    if ($null -eq $code) { return $null }
    return [pscustomobject]@{ Error = [string]$code; Message = [string](Get-Field $Result.Payload 'message') }
}

# The M-1 receipt check (report section 4.3 step 2). Returns $null when the receipt is good, else the reason.
function Test-RunReceipt($Manifest) {
    if (-not (Test-Path -LiteralPath $Receipt -PathType Leaf)) { return "no M-1 receipt at '$Receipt'" }
    if (-not (Test-Path -LiteralPath $RunGate -PathType Leaf)) { throw "run_gate.py not found: $RunGate" }
    $launch = Get-Field $Manifest 'launch'
    $psi = [System.Diagnostics.ProcessStartInfo]::new((Get-CreditsPython))
    foreach ($a in @('-X', 'utf8', $RunGate, '--check-receipt', $Receipt, '--project', (Get-Field $Manifest 'project_root'),
            '--python', (Get-Field $launch 'python_exe'), '--claude', (Get-Field $launch 'claude_exe'))) { $psi.ArgumentList.Add([string]$a) }
    $psi.UseShellExecute = $false
    $psi.CreateNoWindow = $true
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true
    $proc = [System.Diagnostics.Process]::Start($psi)
    try {
        $outTask = $proc.StandardOutput.ReadToEndAsync()
        $errTask = $proc.StandardError.ReadToEndAsync()
        if (-not $proc.WaitForExit(300000)) {
            try { $proc.Kill($true) } catch { [Console]::Error.WriteLine("run_gate.py kill failed: $($_.Exception.Message)") }
            return 'run_gate.py did not end in 300 s'
        }
        $proc.WaitForExit()
        if ($proc.ExitCode -ne 0) {
            $last = @(($outTask.Result + "`n" + $errTask.Result) -split "`r?`n" | Where-Object { $_.Trim() }) | Select-Object -Last 3
            return "run_gate.py exit $($proc.ExitCode): $($last -join ' | ')"
        }
        return $null
    } finally {
        $proc.Dispose()
    }
}

# The run_parameters block of the brief's ## Authorization section (report section 4.4) as the
# text of a block file ("run_parameters:" and its lines), or $null when the brief has none.
function Read-AuthorizationBlock([string]$BriefPath) {
    if (-not $BriefPath -or -not (Test-Path -LiteralPath $BriefPath -PathType Leaf)) { return $null }
    $text = [System.IO.File]::ReadAllText($BriefPath, [System.Text.Encoding]::UTF8)
    $section = [regex]::Match($text, '(?ms)^## Authorization[ \t]*\r?\n(.*?)(?=^## |\z)')
    if (-not $section.Success) { return $null }
    $fence = [regex]::Match($section.Groups[1].Value, '(?ms)^```yaml[ \t]*\r?\n(run_parameters:[ \t]*\r?\n.*?)^```[ \t]*\r?$')
    if (-not $fence.Success) { return $null }
    return $fence.Groups[1].Value -replace '\r\n', "`n"
}

# Runs one run_parameters.py verb with the manifest's python_exe in the project (the tool's
# --repo default). Returns Code, Result (the last JSON line of stdout, or $null) and Output.
function Invoke-RunParametersTool($Launch, [string]$ProjectRoot, [string[]]$Arguments) {
    $python = [string](Get-Field $Launch 'python_exe')
    if (-not $python) { $python = Get-CreditsPython }
    $psi = [System.Diagnostics.ProcessStartInfo]::new($python)
    foreach ($a in @('-X', 'utf8', $RunParametersTool) + $Arguments) { $psi.ArgumentList.Add([string]$a) }
    $psi.WorkingDirectory = $ProjectRoot
    $psi.UseShellExecute = $false
    $psi.CreateNoWindow = $true
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true
    $proc = [System.Diagnostics.Process]::Start($psi)
    try {
        $outTask = $proc.StandardOutput.ReadToEndAsync()
        $errTask = $proc.StandardError.ReadToEndAsync()
        if (-not $proc.WaitForExit(300000)) {
            try { $proc.Kill($true) } catch { [Console]::Error.WriteLine("run_parameters.py kill failed: $($_.Exception.Message)") }
            throw "run_parameters.py $($Arguments[0]) did not end in 300 s"
        }
        $proc.WaitForExit()
        $parsed = $null
        $last = @($outTask.Result -split "`r?`n" | Where-Object { $_.Trim() }) | Select-Object -Last 1
        if ($last) {
            try { $parsed = $last | ConvertFrom-Json -ErrorAction Stop } catch { $parsed = $null }
        }
        return [pscustomobject]@{ Code = $proc.ExitCode; Result = $parsed; Output = ($outTask.Result + $errTask.Result).Trim() }
    } finally {
        $proc.Dispose()
    }
}

# The reason a run_parameters.py call refused: the tool's reason, else its exit code.
function Get-RunParametersReason($Call) {
    $reason = if ($null -ne $Call.Result) { [string](Get-Field $Call.Result 'reason') } else { '' }
    if ($reason) { return $reason }
    return "exit_$($Call.Code)"
}

# The environment block of the wrapper (report section 4.3 step 7). It starts from this process's
# environment; the dispatch wrapper later removes CREDITS_* from the CLI and the -Scheduled hook
# puts back the names below. CREDITS_BASE_COMMIT is set only when admission recorded a base
# commit B (report section 4.3 step 4; section 5.4).
function New-ChildEnvironment($Launch, [string]$SegmentId, [string]$BaseCommit) {
    $environment = [System.Collections.Generic.Dictionary[string, string]]::new([System.StringComparer]::OrdinalIgnoreCase)
    foreach ($entry in [Environment]::GetEnvironmentVariables().GetEnumerator()) {
        $name = [string]$entry.Key
        if ($name -in @('CLAUDECODE', 'CLAUDE_CODE_ENTRYPOINT', 'ELECTRON_RUN_AS_NODE', 'CLAUDE_CODE_CHILD_SESSION')) { continue }
        if ($name -match '^(?i)(DISABLE_PROMPT_CACHING|CREDITS_)') { continue }
        $environment[$name] = [string]$entry.Value
    }
    $environment['DISABLE_AUTOUPDATER'] = '1'
    $environment['CLAUDE_CODE_RETRY_WATCHDOG'] = '1'
    $environment['BASH_DEFAULT_TIMEOUT_MS'] = '600000'
    $environment['BASH_MAX_TIMEOUT_MS'] = '600000'
    # The launcher environment file of the store folder, filled at adoption (EA-88). The names the
    # launcher sets below come after it; Read-CreditsLauncherEnv refuses them in the file.
    $launcherEnv = Read-CreditsLauncherEnv -Path (Join-Path (Split-Path -Parent $StateDb) 'launcher.env.json')
    foreach ($name in $launcherEnv.Env.Keys) { $environment[$name] = $launcherEnv.Env[$name] }
    if ($launcherEnv.PathPrepend.Count -gt 0) {
        $path = if ($environment.ContainsKey('PATH')) { $environment['PATH'] } else { '' }
        $first = $launcherEnv.PathPrepend -join ';'
        $environment['PATH'] = if ($path) { "$first;$path" } else { $first }
    }
    $environment['CREDITS_RUN_ID'] = $RunId
    $environment['CREDITS_STATE_DB'] = $StateDb
    $environment['CREDITS_SEGMENT'] = $SegmentId
    if ($BaseCommit) { $environment['CREDITS_BASE_COMMIT'] = $BaseCommit }
    $claudeExe = [string](Get-Field $Launch 'claude_exe')
    if ($claudeExe -and [System.IO.Path]::IsPathRooted($claudeExe)) {
        $folder = Split-Path -Parent $claudeExe
        $path = if ($environment.ContainsKey('PATH')) { $environment['PATH'] } else { '' }
        $environment['PATH'] = if ($path) { "$folder;$path" } else { $folder }
    }
    return $environment
}

# The dispatch that a resume continues: the newest earlier attempt with a status.json.
function Find-ResumeSource($Status, [string]$CurrentDispatchId) {
    $earlier = @(Get-Field $Status 'attempts') | Where-Object {
        $null -ne $_ -and $_.dispatch_id -and [string]$_.dispatch_id -ne $CurrentDispatchId
    }
    $list = @($earlier)
    for ($i = $list.Count - 1; $i -ge 0; $i--) {
        $id = [string]$list[$i].dispatch_id
        if (Test-Path -LiteralPath (Join-Path $OutputDir "$id/status.json") -PathType Leaf) { return $id }
    }
    return $null
}

# Record the wrapper identity (store verb launched) while the wrapper is still suspended, before
# it can start the CLI: a segment whose CLI ran is never left in launching, so a launcher that
# dies after the resume cannot cause a launch_failed class. The wrapper is the root member of the
# job and lives as long as the CLI. Throws when the store refuses.
function Register-Launched([string]$SegmentId, [string]$BootId, $Wrapper) {
    $created = ConvertFrom-UtcText $Wrapper.CreationUtc
    if ($null -eq $created) { throw "the wrapper creation time is not a UTC time: $($Wrapper.CreationUtc)" }
    $res = Invoke-CreditsState -StateDb $StateDb -Verb launched -Arguments @(
        '--segment-id', $SegmentId, '--pid', [string][int]$Wrapper.ProcessId, '--created', (Format-CreditsUtc $created), '--boot-id', $BootId)
    if ($res.Code -ne 0) { throw "credits_state.py launched failed: $(Format-CreditsStateError $res)" }
    Write-LauncherLog 'INFO' 'credits_segment_launched' @{ segment_id = $SegmentId; pid = [int]$Wrapper.ProcessId }
}

# Returns $true when the wrapper wrote running.json, and logs the CLI identity from it once.
function Test-RunningJson([string]$SegmentId, [string]$RunningPath) {
    $running = Read-JsonFile $RunningPath
    if ($null -eq $running) { return $false }
    Write-LauncherLog 'INFO' 'credits_cli_identity' @{
        segment_id = $SegmentId; claude_pid = (Get-Field $running 'claude_pid'); claude_creation_utc = (Get-Field $running 'claude_creation_utc')
    }
    return $true
}

function Test-CancelRequested([string]$SegmentId) {
    $status = Get-RunStatus
    $segment = @(Get-Field $status 'segments') | Where-Object { $null -ne $_ -and [string]$_.segment_id -eq $SegmentId } | Select-Object -First 1
    return ($null -ne $segment -and $null -ne (Get-Field $segment 'cancel_requested_utc'))
}

# The live members of the job. After a terminate, CREDITS_TEST_ACTIVE_PROCESSES stands for a
# descendant that outlives it (a test seam for MX-20).
function Get-ActiveCount([bool]$AfterTerminate) {
    if ($AfterTerminate -and $env:CREDITS_TEST_ACTIVE_PROCESSES) { return [int]$env:CREDITS_TEST_ACTIVE_PROCESSES }
    return Get-CreditsJobActiveCount -Job $script:Job
}

# Terminate the job and wait up to TerminateWaitMs. Returns the members that remain.
function Stop-SegmentJob([string]$SegmentId) {
    try {
        Stop-CreditsJob -Job $script:Job -TimeoutSec ([math]::Max(1, [int][math]::Ceiling($TerminateWaitMs / 1000.0)))
    } catch {
        Write-LauncherLog 'WARN' 'credits_terminate_incomplete' @{ segment_id = $SegmentId; message = $_.Exception.Message }
    }
    return Get-ActiveCount $true
}

# Members outlived the terminate: termination_pending, then wait PendingWaitMs for an empty job.
# Returns $true when the job became empty (the caller finalizes), $false when the monitor must.
function Wait-PendingTermination([string]$SegmentId, [int]$Remaining) {
    $res = Invoke-CreditsState -StateDb $StateDb -Verb termination_pending -Arguments @('--segment-id', $SegmentId)
    if ($res.Code -ne 0) { throw "credits_state.py termination_pending failed: $(Format-CreditsStateError $res)" }
    Write-LauncherLog 'WARN' 'credits_termination_pending' @{ segment_id = $SegmentId; active_processes = $Remaining }
    $clock = [System.Diagnostics.Stopwatch]::StartNew()
    while ($clock.ElapsedMilliseconds -lt $PendingWaitMs) {
        if ((Get-ActiveCount $true) -eq 0) { return $true }
        Start-Sleep -Milliseconds 500
    }
    return ((Get-ActiveCount $true) -eq 0)
}

function Invoke-Launcher {
    # --- step 1: never inside a Claude Code session (report section 4.3, MX-2)
    if ($env:CLAUDECODE -or $env:CLAUDE_CODE_ENTRYPOINT) {
        return New-Result 'refused' 3 @{ reason = 'nested_session'; message = 'CLAUDECODE or CLAUDE_CODE_ENTRYPOINT is set; the launcher runs only from Task Scheduler or a plain terminal.' }
    }
    $clockNow = $null
    if ($NowUtc) {
        $clockNow = ConvertFrom-UtcText $NowUtc
        if ($null -eq $clockNow) { return New-Result 'refused' 3 @{ reason = 'bad_argument'; message = "-NowUtc is not a UTC time: $NowUtc" } }
    }

    Import-Module -Name (Join-Path $PSScriptRoot 'CreditsRun.psm1') -Force -DisableNameChecking -ErrorAction Stop
    $limit = (Get-CreditsConstants).REQUEST_ACCEPT_TIMEOUT_S

    $status = Get-RunStatus
    if (-not (Get-Field $status 'exists')) { return New-Result 'start_refused' 0 @{ reason = 'unknown_run' } }
    $manifest = Get-Field $status 'manifest'
    if ($null -eq $manifest) { throw "run $RunId has no manifest in the store" }
    $launch = Get-Field $manifest 'launch'

    # Registration refuses a working directory outside the project; check again here, before the
    # request is taken, so a run that reached the store another way starts nothing and holds no lane.
    $projectRoot = [string](Get-Field $manifest 'project_root')
    $workDir = [string](Get-Field $launch 'working_directory')
    if (-not (Test-CreditsSameDirectory -Left $projectRoot -Right $workDir)) {
        $message = "launch.working_directory '$workDir' is not the project_root '$projectRoot'; both must be the same directory"
        Write-LauncherLog 'ERROR' 'credits_project_mismatch' @{ project_root = $projectRoot; working_directory = $workDir; message = $message }
        return New-Result 'start_refused' 1 @{ reason = 'project_mismatch'; message = $message }
    }

    # --- step 2: the M-1 receipt, before the request is taken
    $now = if ($null -ne $clockNow) { $clockNow } else { [datetime]::UtcNow }
    $fresh = @(@(Get-Field $status 'requests') | Where-Object { $null -ne $_ -and $_.state -eq 'pending' } | ForEach-Object {
            $created = ConvertFrom-UtcText $_.created_utc
            $age = if ($null -ne $created) { ($now - $created).TotalSeconds } else { [double]::MaxValue }
            [pscustomobject]@{ RequestId = [string]$_.request_id; Age = $age }
        } | Where-Object { $_.Age -lt $limit })
    if ($fresh.Count -gt 0) {
        foreach ($request in $fresh) {
            if ($request.Age -ge 0.8 * $limit) {
                Write-LauncherLog 'DEBUG' 'credits_limit_near' @{ limit_name = 'REQUEST_ACCEPT_TIMEOUT_S'; configured_value = $limit; observed_value = [int][math]::Floor($request.Age); window = 'request_accept'; request_id = $request.RequestId }
            }
        }
        $rejection = Test-RunReceipt $manifest
        if ($null -ne $rejection) {
            Write-LauncherLog 'ERROR' 'credits_receipt_rejected' @{ receipt = $Receipt; message = $rejection }
            return New-Result 'start_refused' 1 @{ reason = 'receipt_rejected'; message = $rejection }
        }
    }

    # --- step 2b: the first-start admission of a manifest with phases (report section 4.4, D-17).
    # A resume is checked by its own brief (credits_msg.py tree), not here. A refused request
    # stays pending and ages out to not_started, as a request that no launcher took.
    $pending = @(@(Get-Field $status 'requests') | Where-Object { $null -ne $_ -and $_.state -eq 'pending' })
    $admission = @(@(Get-Field $manifest 'phases') | Where-Object { $_ }).Count -gt 0 -and
        $pending.Count -eq 1 -and -not [bool](Get-Field $pending[0] 'resume')
    $planSlug = $null
    if ($admission) {
        if (-not $script:RunParametersTool) { $script:RunParametersTool = Join-Path $projectRoot 'tools/run_parameters.py' }
        $planSlug = Split-Path -Leaf ([string](Get-Field $manifest 'plan_folder')).TrimEnd('/', '\')
        $briefPath = [string](Get-Field $manifest 'brief')
        if ($briefPath -and -not [System.IO.Path]::IsPathRooted($briefPath)) { $briefPath = Join-Path $projectRoot $briefPath }
        $block = Read-AuthorizationBlock $briefPath
        if ($null -eq $block) {
            $message = "the brief '$briefPath' has no ## Authorization section with a run_parameters block"
            Write-LauncherLog 'INFO' 'credits_admission_refused' @{ step = 'brief'; reason = 'no_authorization'; message = $message }
            return New-Result 'admission_refused' 0 @{ reason = 'no_authorization'; step = 'brief'; message = $message }
        }
        $blockFile = Join-Path (Split-Path -Parent $StateDb) "admission/$RunId.block.yaml"
        New-Item -ItemType Directory -Force -Path (Split-Path -Parent $blockFile) | Out-Null
        [System.IO.File]::WriteAllText($blockFile, $block, $script:Utf8)
        $call = Invoke-RunParametersTool $launch $projectRoot @('inspect', '--block', $blockFile)
        if ($call.Code -ne 0 -or [string](Get-Field $call.Result 'result') -ne 'inspected') {
            $reason = Get-RunParametersReason $call
            Write-LauncherLog 'INFO' 'credits_admission_refused' @{ step = 'inspect'; reason = $reason; exit_code = $call.Code; output = $call.Output }
            return New-Result 'admission_refused' 0 @{ reason = $reason; step = 'inspect' }
        }
        Write-LauncherLog 'INFO' 'credits_admission_inspected' @{ plan = $planSlug; block = $blockFile }
    }

    # --- step 3: accept the request
    $launcher = [System.Diagnostics.Process]::GetCurrentProcess()
    $bootId = Get-CreditsBootId
    $acceptArgs = @{
        StateDb   = $StateDb
        Verb      = 'accept'
        Arguments = @('--run-id', $RunId, '--launcher-pid', [string]$PID, '--launcher-created', (Format-CreditsUtc $launcher.StartTime),
            '--boot-id', $bootId, '--win-session', [string]$launcher.SessionId)
    }
    if ($null -ne $clockNow) { $acceptArgs.NowUtc = $clockNow }
    $res = Invoke-CreditsState @acceptArgs
    $refusal = Get-StoreRefusal $res
    if ($null -ne $refusal) {
        Write-LauncherLog 'INFO' 'credits_start_refused' @{ reason = $refusal.Error; message = $refusal.Message }
        return New-Result 'start_refused' 0 @{ reason = $refusal.Error; message = $refusal.Message }
    }
    if ($res.Code -ne 0 -or $null -eq $res.Payload) { throw "credits_state.py accept failed: $(Format-CreditsStateError $res)" }
    $accepted = $res.Payload
    if ([string](Get-Field $accepted 'outcome') -eq 'stale_at_launcher') {
        Write-LauncherLog 'WARN' 'credits_limit_tripped' @{
            limit_name = 'REQUEST_ACCEPT_TIMEOUT_S'; configured_value = (Get-Field $accepted 'limit_s')
            observed_value = (Get-Field $accepted 'age_s'); window = 'request_accept'; request_id = (Get-Field $accepted 'request_id')
        }
        return New-Result 'not_started' 0 @{ reason = 'stale_at_launcher'; request_id = (Get-Field $accepted 'request_id') }
    }
    $attemptId = [string](Get-Field $accepted 'attempt_id')
    $dispatchId = [string](Get-Field $accepted 'dispatch_id')
    $sessionId = [string](Get-Field $accepted 'expected_session_id')
    $isResume = [bool](Get-Field $accepted 'resume')

    # --- step 4: admit (lane, run, budget)
    $res = Invoke-CreditsState -StateDb $StateDb -Verb admit -Arguments @('--attempt-id', $attemptId)
    if ($res.Code -ne 0 -or $null -eq $res.Payload) { throw "credits_state.py admit failed: $(Format-CreditsStateError $res)" }
    $admitted = $res.Payload
    if ([string](Get-Field $admitted 'outcome') -eq 'rejected') {
        $reason = [string](Get-Field $admitted 'reason')
        Write-LauncherLog 'INFO' 'credits_admit_rejected' @{ attempt_id = $attemptId; reason = $reason; resume = $isResume }
        return New-Result 'rejected' 0 @{ reason = $reason; attempt_id = $attemptId }
    }
    $segmentId = [string](Get-Field $admitted 'segment_id')
    $reservation = [double](Get-Field $admitted 'reservation_usd')
    $baseCommit = [string](Get-Field $admitted 'base_commit')
    # A resume runs on its own brief when the request named one (report section 5.3); a fresh
    # resume (admit resume=fresh) starts the new session that accept chose, with no --resume.
    $promptFile = [string](Get-Field $admitted 'brief')
    if (-not $promptFile) { $promptFile = [string](Get-Field $manifest 'brief') }
    $isFresh = [string](Get-Field $admitted 'resume') -eq 'fresh'
    Write-LauncherLog 'INFO' 'credits_segment_admitted' @{ attempt_id = $attemptId; segment_id = $segmentId; reservation_usd = $reservation; base_commit = $baseCommit }

    # The admission binds the attempt's session to the plan as headless (AC-F.4) before the CLI
    # starts. A refusal closes the open segment as launch_failed and starts nothing.
    if ($admission) {
        $bindFailure = $null
        try {
            $call = Invoke-RunParametersTool $launch $projectRoot @('bind', '--pending', $planSlug, '--session', $sessionId, '--context', 'headless')
            if ($call.Code -ne 0 -or [string](Get-Field $call.Result 'result') -ne 'bound') { $bindFailure = Get-RunParametersReason $call }
        } catch {
            $bindFailure = $_.Exception.Message
        }
        if ($null -ne $bindFailure) {
            Write-LauncherLog 'INFO' 'credits_admission_refused' @{ step = 'bind'; reason = $bindFailure; segment_id = $segmentId }
            $null = Complete-CreditsSegment -StateDb $StateDb -SegmentId $segmentId -FinalizedBy launcher -Class launch_failed
            return New-Result 'admission_refused' 0 @{ reason = $bindFailure; step = 'bind'; segment_id = $segmentId }
        }
        Write-LauncherLog 'INFO' 'credits_admission_bound' @{ plan = $planSlug; session_id = $sessionId }
    }

    # From here the segment is open; every path finalizes it or leaves it to the monitor.
    try {
        $script:KeepAwake = Enter-CreditsKeepAwake -Reason "{{PROJECT_NAME_TITLE}} credits run $RunId"
    } catch {
        Write-LauncherLog 'WARN' 'credits_keep_awake_failed' @{ segment_id = $segmentId; message = $_.Exception.Message }
    }

    $failure = $null
    try {
        # Test seam: CREDITS_TEST_JOB_FAIL=1 stands for a host that refuses the job.
        if ($env:CREDITS_TEST_JOB_FAIL -eq '1') { throw 'the job was refused (CREDITS_TEST_JOB_FAIL=1)' }
        $script:Job = New-CreditsJob -SegmentId $segmentId
    } catch {
        $failure = "no job: $($_.Exception.Message)"
    }

    $continuation = @()
    if ($null -eq $failure) {
        if ($isResume -and $isFresh) {
            $continuation = @('-SessionId', $sessionId)
        } elseif ($isResume) {
            $source = Find-ResumeSource $status $dispatchId
            if ($source) { $continuation = @('-Resume', $source) }
            elseif (@(Get-Field $status 'segments').Count -eq 0) { $continuation = @('-SessionId', $sessionId) }
            else { $failure = "no earlier dispatch with a status.json in $OutputDir to resume session $sessionId" }
        } else {
            $continuation = @('-SessionId', $sessionId)
        }
    }

    if ($null -ne $failure) {
        Write-LauncherLog 'ERROR' 'credits_launch_failed' @{ segment_id = $segmentId; message = $failure }
        $null = Complete-CreditsSegment -StateDb $StateDb -SegmentId $segmentId -FinalizedBy launcher -Class launch_failed
        return New-Result 'launch_failed' 1 @{ segment_id = $segmentId; message = $failure }
    }

    # --- step 5: the wrapper inside the job
    $wrapperArgs = @('-NoProfile', '-NonInteractive', '-File', $WrapperScript, '-Scheduled',
        '-PromptFile', $promptFile, '-KeyFile', $KeyFile,
        '-ClaudeExecutable', [string](Get-Field $launch 'claude_exe'),
        '-MaxBudgetUsd', $reservation.ToString('R', [System.Globalization.CultureInfo]::InvariantCulture),
        '-DispatchId', $dispatchId, '-OutputDir', $OutputDir,
        '-WorkingDirectory', [string](Get-Field $launch 'working_directory'),
        '-TimeoutSec', [string][int](Get-Field $launch 'timeout_sec'),
        '-Kind', [string](Get-Field $manifest 'kind'),
        '-PermissionMode', [string](Get-Field $launch 'permission_mode'),
        '-Effort', [string](Get-Field $launch 'effort'))
    $model = Get-Field $launch 'model'
    if ($model) { $wrapperArgs += @('-Model', [string]$model) }
    $wrapperArgs += $continuation
    $commandLine = ($wrapperArgs | ForEach-Object { ConvertTo-WindowsArgument ([string]$_) }) -join ' '
    try {
        $environment = New-ChildEnvironment $launch $segmentId $baseCommit
    } catch {
        $message = $_.Exception.Message
        Write-LauncherLog 'ERROR' 'credits_launcher_env_invalid' @{ segment_id = $segmentId; message = $message }
        $null = Complete-CreditsSegment -StateDb $StateDb -SegmentId $segmentId -FinalizedBy launcher -Class launch_failed
        return New-Result 'launch_failed' 1 @{ segment_id = $segmentId; message = $message }
    }
    $pwsh = Join-Path $PSHOME 'pwsh.exe'
    $child = $null
    try {
        $child = Start-CreditsJobProcess -Job $script:Job -FilePath $pwsh -CommandLine $commandLine `
            -WorkingDirectory ([string](Get-Field $launch 'working_directory')) -Environment $environment
        # Open the Process while the child is suspended, so its exit code stays readable.
        $script:WrapperProcess = [System.Diagnostics.Process]::GetProcessById($child.ProcessId)
        $null = $script:WrapperProcess.Handle
        Register-Launched $segmentId $bootId $child
        Resume-CreditsJobProcess -Child $child
    } catch {
        $message = "the wrapper did not start: $($_.Exception.Message)"
        if ($null -ne $child) { [ClaudeCredits.JobNative]::Abandon($child) }
        Write-LauncherLog 'ERROR' 'credits_launch_failed' @{ segment_id = $segmentId; message = $message }
        $null = Complete-CreditsSegment -StateDb $StateDb -SegmentId $segmentId -FinalizedBy launcher -Class launch_failed
        return New-Result 'launch_failed' 1 @{ segment_id = $segmentId; message = $message }
    }
    Write-LauncherLog 'INFO' 'credits_wrapper_started' @{ segment_id = $segmentId; dispatch_id = $dispatchId; wrapper_pid = $child.ProcessId }

    # --- step 6: watch the job, the CLI identity and the cancel mark
    $runningPath = Join-Path $OutputDir "$dispatchId/running.json"
    $runningSeen = $false
    $clock = [System.Diagnostics.Stopwatch]::StartNew()
    $nextCancelPoll = 0
    while ((Get-ActiveCount $false) -gt 0) {
        if (-not $runningSeen) { $runningSeen = Test-RunningJson $segmentId $runningPath }
        if ($clock.ElapsedMilliseconds -ge $nextCancelPoll) {
            $nextCancelPoll = $clock.ElapsedMilliseconds + $CancelPollMs
            if (Test-CancelRequested $segmentId) {
                Write-LauncherLog 'INFO' 'credits_cancel_seen' @{ segment_id = $segmentId }
                $remaining = Stop-SegmentJob $segmentId
                if ($remaining -gt 0 -and -not (Wait-PendingTermination $segmentId $remaining)) {
                    return New-Result 'termination_pending' 1 @{ segment_id = $segmentId; active_processes = $remaining }
                }
                $null = Complete-CreditsSegment -StateDb $StateDb -SegmentId $segmentId -FinalizedBy launcher -Class cancelled
                return New-Result 'cancelled' 0 @{ segment_id = $segmentId; class = 'cancelled' }
            }
        }
        if (-not $runningSeen -and $clock.ElapsedMilliseconds -ge $LaunchWaitMs) {
            Write-LauncherLog 'ERROR' 'credits_no_running_json' @{ segment_id = $segmentId; launch_wait_ms = $LaunchWaitMs }
            $remaining = Stop-SegmentJob $segmentId
            if ($remaining -gt 0 -and -not (Wait-PendingTermination $segmentId $remaining)) {
                return New-Result 'termination_pending' 1 @{ segment_id = $segmentId; active_processes = $remaining }
            }
            $null = Complete-CreditsSegment -StateDb $StateDb -SegmentId $segmentId -FinalizedBy launcher -Class launch_failed
            return New-Result 'launch_failed' 1 @{ segment_id = $segmentId; message = "no running.json in $LaunchWaitMs ms" }
        }
        Start-Sleep -Milliseconds 200
    }

    # --- step 7: the job is empty; finalize from status.json
    if (-not $runningSeen) { $runningSeen = Test-RunningJson $segmentId $runningPath }
    $exitCode = $null
    if ($null -ne $script:WrapperProcess) {
        $script:WrapperProcess.WaitForExit()
        $exitCode = $script:WrapperProcess.ExitCode
    }
    $dispatchStatus = Read-JsonFile (Join-Path $OutputDir "$dispatchId/status.json")
    $class = 'exited'
    $total = $null
    if ($null -ne $dispatchStatus) {
        if ([bool](Get-Field $dispatchStatus 'timed_out')) { $class = 'timeout' }
        $value = Get-Field $dispatchStatus 'session_total_usd'
        if ($null -eq $value) { $value = Get-Field $dispatchStatus 'total_cost_usd' }
        if ($null -ne $value) { $total = [double]$value }
    } else {
        Write-LauncherLog 'WARN' 'credits_status_missing' @{ segment_id = $segmentId; dispatch_id = $dispatchId }
    }
    if (-not $runningSeen) { $class = 'launch_failed' }
    $done = Complete-CreditsSegment -StateDb $StateDb -SegmentId $segmentId -FinalizedBy launcher -Class $class -SessionTotalUsd $total -ExitCode $exitCode
    $finalClass = [string](Get-Field $done 'stop_class')
    if (-not $finalClass) { $finalClass = $class }
    Write-LauncherLog 'INFO' 'credits_segment_finalized' @{ segment_id = $segmentId; class = $finalClass; exit_code = $exitCode; session_total_usd = $total }
    return New-Result 'completed' 0 @{ segment_id = $segmentId; class = $finalClass; exit_code = $exitCode }
}

$result = $null
try {
    if ($null -ne $script:ArgumentError) {
        $result = New-Result 'refused' 3 @{ reason = 'bad_argument'; message = $script:ArgumentError }
        [Console]::Out.WriteLine(($result.Payload | ConvertTo-Json -Compress -Depth 6))
        [Console]::Out.Flush()
        exit $result.Code
    }
    $StateDb = [System.IO.Path]::GetFullPath($StateDb)
    $OutputDir = [System.IO.Path]::GetFullPath($OutputDir)
    $storeFolder = Split-Path -Parent $StateDb
    $script:LogPath = Join-Path $storeFolder "logs/launcher-$RunId.jsonl"
    if (-not $KeyFile) {
        $KeyFile = if ($env:CLAUDE_CREDITS_KEY_FILE) { $env:CLAUDE_CREDITS_KEY_FILE } else { Join-Path $HOME '.anthropic/claude-credits.key' }
    }
    if (-not $RunGate) { $RunGate = Join-Path $PSScriptRoot 'probes/run_gate.py' }
    if (-not $Receipt) { $Receipt = Join-Path $storeFolder "receipts/$RunId.gate-result.json" }
    if (-not $WrapperScript) { $WrapperScript = Join-Path $PSScriptRoot 'Invoke-ClaudeCredits.ps1' }
    $result = Invoke-Launcher
} catch {
    $message = $_.Exception.Message
    Write-LauncherLog 'ERROR' 'credits_launcher_error' @{ message = $message }
    $result = New-Result 'error' 9 @{ message = $message }
} finally {
    if ($null -ne $script:Job) {
        try { Close-CreditsJob -Job $script:Job } catch { [Console]::Error.WriteLine("credits launcher: job close failed: $($_.Exception.Message)") }
    }
    if ($null -ne $script:KeepAwake) {
        try { Exit-CreditsKeepAwake -KeepAwake $script:KeepAwake } catch { [Console]::Error.WriteLine("credits launcher: keep-awake release failed: $($_.Exception.Message)") }
    }
    if ($null -ne $script:WrapperProcess) { $script:WrapperProcess.Dispose() }
}

[Console]::Out.WriteLine(($result.Payload | ConvertTo-Json -Compress -Depth 6))
[Console]::Out.Flush()
exit $result.Code
