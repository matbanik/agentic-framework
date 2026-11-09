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
      1  launch_failed, termination_pending, receipt_rejected, project_mismatch or token_missing;
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
    # The subscription token of a launch.auth subscription run. A fleet member's kit has its fleet
    # home as the project root, and its S4U task gets none of the member's environment.
    TokenFile       = @{ Kind = 'string'; Default = '{{PROJECT_ROOT}}/credentials/claude-oauth-token' }
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
# PE21-D2 (MEU-895 Constant Classification): the SHA-256 of templates/operator-policy.md. The
# launcher refuses a start when the file has another hash (policy_hash_mismatch), so a change
# of the policy text needs a change of this constant in the same commit.
$script:OperatorPolicySha256 = 'dec292f98dfe1a2c36cf9a1c5a980275e3c5bf3db04616cd16eb67ba479a0716'
# POLICY_MAX_CHARS (PE21-D2; R1-F7): the policy text is at most 4000 characters.
$script:PolicyMaxChars = 4000

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
    $gateProject = Get-Field $launch 'gate_project'
    if ($gateProject) { foreach ($a in @('--gate-project', $gateProject)) { $psi.ArgumentList.Add([string]$a) } }
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

# PE21-D2 (AC-895.1): the operator policy file as the launcher checks it before admit. Returns
# $null when the file is readable, its SHA-256 is $script:OperatorPolicySha256 and its text is LF
# text of at most $script:PolicyMaxChars characters; else the reason, which the caller refuses as
# policy_hash_mismatch.
function Test-OperatorPolicy([string]$PolicyFile) {
    if (-not (Test-Path -LiteralPath $PolicyFile -PathType Leaf)) { return "no policy file at '$PolicyFile'" }
    try {
        $bytes = [System.IO.File]::ReadAllBytes($PolicyFile)
    } catch {
        return "the policy file '$PolicyFile' is not readable: $($_.Exception.Message)"
    }
    $hash = [System.Convert]::ToHexString([System.Security.Cryptography.SHA256]::HashData($bytes)).ToLowerInvariant()
    if ($hash -cne $script:OperatorPolicySha256) { return "the policy file hash $hash is not the launcher's constant $($script:OperatorPolicySha256)" }
    $text = $script:Utf8.GetString($bytes)
    if ($text.Length -gt $script:PolicyMaxChars -or $text.Contains("`r")) {
        return "the policy file is not LF text of at most $($script:PolicyMaxChars) characters"
    }
    return $null
}

# PE21-D14: the prompt-cache TTL of the config (cache_ttl), from the file that
# Register-CreditsRun.ps1 reads: CREDITS_CONFIG, else .agent/credits/config.json. With no file
# or no cache_ttl the TTL is '5m'. A file that is not JSON, or a value other than '5m' or '1h',
# also gives '5m' with WARN credits_cache_ttl_default: the registration checked the value, so the
# config changed after it, and 5m is the cheaper TTL.
function Get-CacheTtl([string]$SegmentId) {
    $path = if ($env:CREDITS_CONFIG) { $env:CREDITS_CONFIG } else { Join-Path $PSScriptRoot '../../credits/config.json' }
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { return '5m' }
    try {
        $config = [System.IO.File]::ReadAllText($path, [System.Text.Encoding]::UTF8) | ConvertFrom-Json -ErrorAction Stop
    } catch {
        Write-LauncherLog 'WARN' 'credits_cache_ttl_default' @{ segment_id = $SegmentId; config = $path; message = "the config is not readable JSON: $($_.Exception.Message)" }
        return '5m'
    }
    $ttl = Get-Field $config 'cache_ttl'
    if ($null -eq $ttl) { return '5m' }
    if ($ttl -is [string] -and $ttl -cin @('5m', '1h')) { return $ttl }
    Write-LauncherLog 'WARN' 'credits_cache_ttl_default' @{ segment_id = $SegmentId; config = $path; message = "cache_ttl '$ttl' is not 5m or 1h" }
    return '5m'
}

# PE21-D12 (CLI_START_MARKER): 'present' when the scheduled hook of the wrapper wrote
# <OutputDir>/<dispatch>/cli-start.json. The hook writes it through to the disk immediately
# before Process.Start, so 'absent' proves that no CLI started. Read only on a launch_failed path
# with an empty job.
function Get-CliStartFact([string]$DispatchId) {
    if (Test-Path -LiteralPath (Join-Path $OutputDir "$DispatchId/cli-start.json") -PathType Leaf) { return 'present' }
    return 'absent'
}

# PE21-D4 (AC-895.3): credits_msg.py authority for the segment, with the stored quote. Returns
# Code, Payload and Output. A tool that does not start or does not end in time is Code -1 with
# the error authority_failed, so the caller closes the segment as for a refusal.
function Invoke-AuthorityCheck([string]$SegmentId, [string]$Quote) {
    try {
        $res = Invoke-CreditsAuthority -StateDb $StateDb -RunId $RunId -SegmentId $SegmentId -Quote $Quote
    } catch {
        $message = $_.Exception.Message
        return [pscustomobject]@{ Code = -1; Payload = [pscustomobject]@{ error = 'authority_failed'; message = $message }; Output = $message }
    }
    return [pscustomobject]@{ Code = $res.Code; Payload = $res.Payload; Output = ([string]$res.Out + [string]$res.Err).Trim() }
}

# PE21-D4 (AC-895.3): the Start record that goes above the brief (implementation plan, Design 2).
# $Request is the admitted request row of run_status, $Authority the payload of the passed
# authority check. The fixed lines are exact: the tests and the resume-brief template name them.
# Throws when the request names a starter or a source check that the record has no line for.
function New-StartRecord($Request, $Authority, $Manifest, [string]$SegmentId, [string]$Kind) {
    if ($null -eq $Request) { throw "no admitted request for segment $SegmentId" }
    $quote = [string](Get-Field $Authority 'quote')
    $chain = Get-Field $Authority 'chain'
    $starter = [string](Get-Field $Request 'started_by')
    $startedBy = switch ($starter) {
        'human-command' { 'the human at the console' }
        'agent-on-user-chat' { "the agent, on the user's chat message" }
        'monitor-chain' { "the monitor, on the chain set up in the user's chat message" }
        default { throw "the admitted request of segment $SegmentId has the unknown started_by '$starter'" }
    }
    $sourceCheck = [string](Get-Field $Request 'source_check')
    $source = switch ($sourceCheck) {
        'console_attested' { "console_attested at $(Get-Field $Request 'attested_utc')" }
        'transcript_verified' { "transcript_verified: session ``$(Get-Field $Request 'start_session')``, message ``$(Get-Field $Request 'start_message')``" }
        'chain_verified' {
            $manifestChain = Get-Field $Manifest 'chain'
            "chain_verified: chain ``$(Get-Field $chain 'chain_id')``, session ``$(Get-Field $manifestChain 'session')``, message ``$(Get-Field $manifestChain 'message_uuid')``"
        }
        default { throw "the admitted request of segment $SegmentId has the unknown source_check '$sourceCheck'" }
    }
    # A console start has no words of the user; the record says so in place of a quote.
    # A chain start records no quote of its own: its words are the quote of the chain (R1-F1).
    if ($sourceCheck -eq 'console_attested') { $quote = '' }
    elseif (-not $quote -and $sourceCheck -eq 'chain_verified') { $quote = [string](Get-Field $chain 'quote') }
    $words = if ($quote) { """$quote""" } else { 'none, a console start' }
    # R1-F2: words that a shell or a code span can change go in as base64 of their UTF-8 bytes,
    # so the command runs as written in PowerShell and in bash.
    $check = if (-not $quote) { 'uv run python tools/credits_msg.py authority' }
    elseif ($quote -match '["$`\\!\u2018-\u201E\p{Cc}]') {
        "uv run python tools/credits_msg.py authority --quote-b64 $([System.Convert]::ToBase64String([System.Text.UTF8Encoding]::new($false).GetBytes($quote)))"
    } else { "uv run python tools/credits_msg.py authority --quote ""$quote""" }
    $cap = ([double](Get-Field (Get-Field $Manifest 'budget') 'run_cap_usd')).ToString('R', [System.Globalization.CultureInfo]::InvariantCulture)
    $lines = @(
        '## Start record (launcher)', '',
        'I am the {{PROJECT_NAME_TITLE}} credits launcher. I started this session. Before I started it, I ran',
        '`tools/credits_msg.py authority` for this segment, and it exited 0.', '',
        "- Run ``$RunId``, segment ``$SegmentId``, a $Kind.",
        "- Started by: $startedBy.",
        "- Source check: $source.",
        "- The user's words: $words.",
        "- Scope: the brief below, inside the manifest of this run (plan folder ``$(Get-Field $Manifest 'plan_folder')``, run cap USD $cap).", '',
        "To check this record again (it only reads the store): ``$check``."
    )
    return ($lines -join "`n")
}

# The environment block of the wrapper (report section 4.3 step 7). It starts from this process's
# environment; the dispatch wrapper later removes CREDITS_* from the CLI and the -Scheduled hook
# puts back the names below. CREDITS_BASE_COMMIT is set only when admission recorded a base
# commit B (report section 4.3 step 4; section 5.4). Throws when launch.env fails its check.
function New-ChildEnvironment($Launch, [string]$SegmentId, [string]$BaseCommit) {
    # PE21-D15: Register-CreditsRun.ps1 checked launch.env; the stored manifest is checked again
    # here, so that a store row that changed after registration sets nothing.
    $launchEnv = Get-Field $Launch 'env'
    $envRefusal = Get-CreditsLaunchEnvRefusal $launchEnv
    if ($null -ne $envRefusal) { throw "$($envRefusal.Reason): $($envRefusal.Message)" }
    $cacheTtl = Get-CacheTtl $SegmentId
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
    # PE21-D14: the CLI changelog names of the two TTLs; the dispatch wrapper keeps both names.
    if ($cacheTtl -eq '1h') {
        $environment['ENABLE_PROMPT_CACHING_1H'] = '1'
        $null = $environment.Remove('FORCE_PROMPT_CACHING_5M')
    } else {
        $environment['FORCE_PROMPT_CACHING_5M'] = '1'
        $null = $environment.Remove('ENABLE_PROMPT_CACHING_1H')
    }
    # PE21-D15: launch.env goes after the strip lines and before the CREDITS_* lines, so it cannot
    # replace them. The log records the names only, never the values.
    if ($null -ne $launchEnv) {
        $names = [System.Collections.Generic.List[string]]::new()
        if ($launchEnv -is [System.Collections.IDictionary]) {
            foreach ($key in $launchEnv.Keys) { $names.Add([string]$key) }
        } else {
            foreach ($prop in $launchEnv.PSObject.Properties) { $names.Add($prop.Name) }
        }
        foreach ($name in $names) { $environment[$name] = [string](Get-Field $launchEnv $name) }
        Write-LauncherLog 'INFO' 'credits_launch_env' @{ segment_id = $SegmentId; names = @($names) }
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
        '--segment-id', $SegmentId, '--pid', [string][int]$Wrapper.ProcessId, '--created', (Format-CreditsUtc $created), '--boot-id', $BootId, '--policy-sha256', $script:OperatorPolicySha256)
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

    $policyFile = Join-Path $PSScriptRoot 'templates/operator-policy.md'
    $policyProblem = Test-OperatorPolicy $policyFile
    if ($null -ne $policyProblem) {
        Write-LauncherLog 'ERROR' 'policy_hash_mismatch' @{ message = $policyProblem }
        return New-Result 'start_refused' 1 @{ reason = 'policy_hash_mismatch'; message = $policyProblem }
    }
    $envRefusal = Get-CreditsLaunchEnvRefusal (Get-Field $launch 'env')
    if ($null -ne $envRefusal) {
        Write-LauncherLog 'ERROR' $envRefusal.Reason @{ message = $envRefusal.Message }
        return New-Result 'start_refused' 1 @{ reason = $envRefusal.Reason; message = $envRefusal.Message }
    }

    # --- step 2: the M-1 receipt, before the request is taken
    $now = if ($null -ne $clockNow) { $clockNow } else { [datetime]::UtcNow }
    $fresh = @(@(Get-Field $status 'requests') | Where-Object { $null -ne $_ -and $_.state -eq 'pending' } | ForEach-Object {
            $created = ConvertFrom-UtcText $_.created_utc
            $age = if ($null -ne $created) { ($now - $created).TotalSeconds } else { [double]::MaxValue }
            [pscustomobject]@{ RequestId = [string]$_.request_id; Age = $age }
        } | Where-Object { $_.Age -lt $limit })
    $subscription = [string](Get-Field $launch 'auth') -ceq 'subscription'
    if ($fresh.Count -gt 0) {
        foreach ($request in $fresh) {
            if ($request.Age -ge 0.8 * $limit) {
                Write-LauncherLog 'DEBUG' 'credits_limit_near' @{ limit_name = 'REQUEST_ACCEPT_TIMEOUT_S'; configured_value = $limit; observed_value = [int][math]::Floor($request.Age); window = 'request_accept'; request_id = $request.RequestId }
            }
        }
        # The size only: the wrapper's hook is the one reader of the token.
        if ($subscription) {
            $tokenInfo = Get-Item -LiteralPath $TokenFile -ErrorAction SilentlyContinue
            if ($null -eq $tokenInfo -or $tokenInfo.PSIsContainer -or $tokenInfo.Length -eq 0) {
                $message = "no subscription token at '$TokenFile'"
                Write-LauncherLog 'ERROR' 'credits_token_missing' @{ token_file = $TokenFile; message = $message }
                return New-Result 'start_refused' 1 @{ reason = 'token_missing'; message = $message }
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
    # An uncapped admission (token_budgets "off", no cap in the manifest) runs with no
    # --max-budget-usd: -MaxBudgetUsd 0 means no cap to the wrapper, and an omitted value
    # would mean its $2 default.
    $uncapped = (Get-Field $admitted 'uncapped') -eq $true
    $maxBudget = if ($uncapped) { 0.0 } else { $reservation }
    $baseCommit = [string](Get-Field $admitted 'base_commit')
    # A resume runs on its own brief when the request named one (report section 5.3); a fresh
    # resume (admit resume=fresh) starts the new session that accept chose, with no --resume.
    $promptFile = [string](Get-Field $admitted 'brief')
    if (-not $promptFile) { $promptFile = [string](Get-Field $manifest 'brief') }
    $isFresh = [string](Get-Field $admitted 'resume') -eq 'fresh'
    Write-LauncherLog 'INFO' 'credits_segment_admitted' @{ attempt_id = $attemptId; segment_id = $segmentId; reservation_usd = $reservation; uncapped = $uncapped; base_commit = $baseCommit }

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

    # PE21-D4 (AC-895.3): the authority check, then the prompt file = the Start record, a blank
    # line and the brief, in the launcher's own folder next to the store (never in the dispatch
    # folder, which the dispatcher must make itself, R1-F1). No CLI has started yet, so a refusal
    # or a failure here closes the segment launch_failed with --cli-start absent (0 USD).
    $afterAdmit = $null
    $authority = $null
    $promptPath = $null
    $startFailure = $null
    try {
        $afterAdmit = Get-RunStatus
        $requestRow = @(Get-Field $afterAdmit 'requests') | Where-Object { $null -ne $_ -and $_.state -eq 'admitted' } | Select-Object -Last 1
        if ($null -eq $requestRow) { throw "run_status shows no admitted request for segment $segmentId" }
        $authority = Invoke-AuthorityCheck $segmentId ([string](Get-Field $requestRow 'start_quote'))
        if ($authority.Code -eq 0) {
            $startKind = if (-not $isResume) { 'first start' } elseif ($isFresh) { 'fresh resume' } else { 'session resume' }
            $record = New-StartRecord $requestRow $authority.Payload $manifest $segmentId $startKind
            $briefSource = $promptFile
            if (-not [System.IO.Path]::IsPathRooted($briefSource)) { $briefSource = Join-Path $workDir $briefSource }
            if (-not (Test-Path -LiteralPath $briefSource -PathType Leaf)) { throw "the brief '$briefSource' does not exist" }
            $briefText = [System.IO.File]::ReadAllText($briefSource, [System.Text.Encoding]::UTF8)
            $promptPath = Join-Path $storeFolder "prompts/$RunId/$segmentId.md"
            New-Item -ItemType Directory -Force -Path (Split-Path -Parent $promptPath) | Out-Null
            [System.IO.File]::WriteAllText($promptPath, $record + "`n`n" + $briefText, $script:Utf8)
            $promptFile = $promptPath
        }
    } catch {
        $startFailure = $_.Exception.Message
    }
    if ($null -ne $startFailure) {
        Write-LauncherLog 'ERROR' 'credits_start_record_failed' @{ segment_id = $segmentId; message = $startFailure }
        if ($promptPath -and (Test-Path -LiteralPath $promptPath -PathType Leaf)) {
            try { Remove-Item -LiteralPath $promptPath -Force -ErrorAction Stop }
            catch { Write-LauncherLog 'WARN' 'credits_prompt_remove_failed' @{ segment_id = $segmentId; prompt = $promptPath; message = $_.Exception.Message } }
        }
        $null = Complete-CreditsSegment -StateDb $StateDb -SegmentId $segmentId -FinalizedBy launcher -Class launch_failed -CliStart absent
        return New-Result 'launch_failed' 1 @{ segment_id = $segmentId; reason = 'start_record_failed'; message = $startFailure }
    }
    if ($authority.Code -ne 0) {
        $authorityReason = [string](Get-Field $authority.Payload 'error')
        if (-not $authorityReason) { $authorityReason = 'authority_failed' }
        Write-LauncherLog 'ERROR' 'credits_authority_refused' @{ segment_id = $segmentId; reason = $authorityReason; output = $authority.Output }
        $null = Complete-CreditsSegment -StateDb $StateDb -SegmentId $segmentId -FinalizedBy launcher -Class launch_failed -CliStart absent
        return New-Result 'launch_failed' 1 @{ segment_id = $segmentId; reason = $authorityReason }
    }

    # PE21-D3 (AC-895.4): a session resume keeps the prompt that the CLI recorded when the session
    # opened. A policy of another hash, or none (a run from before the policy), is a WARN only.
    if ($isResume -and -not $isFresh) {
        $opener = @(Get-Field $afterAdmit 'segments') | Where-Object {
            $null -ne $_ -and [string]$_.segment_id -ne $segmentId -and [string]$_.expected_session_id -eq $sessionId
        } | Select-Object -First 1
        if ($null -ne $opener) {
            $openerHash = [string](Get-Field $opener 'policy_sha256')
            if (-not $openerHash) { Write-LauncherLog 'WARN' 'policy_snapshot_absent' @{ segment_id = $segmentId; session_id = $sessionId } }
            elseif ($openerHash -cne $script:OperatorPolicySha256) { Write-LauncherLog 'WARN' 'policy_snapshot_differs' @{ segment_id = $segmentId; session_id = $sessionId } }
        }
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

    # PE21-D12 names the three marker paths (the step-5 catch, the no-running.json path and
    # step 7); a refused job or resume source is not one of them, so it keeps the failed path.
    if ($null -ne $failure) {
        Write-LauncherLog 'ERROR' 'credits_launch_failed' @{ segment_id = $segmentId; message = $failure }
        $null = Complete-CreditsSegment -StateDb $StateDb -SegmentId $segmentId -FinalizedBy launcher -Class launch_failed
        return New-Result 'launch_failed' 1 @{ segment_id = $segmentId; message = $failure }
    }

    # --- step 5: the wrapper inside the job
    $authArgs = if ($subscription) { @('-Subscription', '-TokenFile', $TokenFile) } else { @('-KeyFile', $KeyFile) }
    # PE21-D9 (AC-895.13): the CLI's own budget stop is min(reservation, launch.max_budget_usd).
    # The reservation and the store cap rules stay; the field only lowers the CLI stop. An
    # uncapped admission has no reservation, so there the field is the one CLI stop.
    $cliBudget = $maxBudget
    $budgetLimit = Get-Field $launch 'max_budget_usd'
    if ($null -ne $budgetLimit -and ($uncapped -or [double]$budgetLimit -lt $cliBudget)) { $cliBudget = [double]$budgetLimit }
    $wrapperArgs = @('-NoProfile', '-NonInteractive', '-File', $WrapperScript, '-Scheduled',
        '-PromptFile', $promptFile,
        '-SystemPromptFile', $policyFile, '-SystemPromptSha256', $script:OperatorPolicySha256) + $authArgs + @(
        '-ClaudeExecutable', [string](Get-Field $launch 'claude_exe'),
        '-MaxBudgetUsd', $cliBudget.ToString('R', [System.Globalization.CultureInfo]::InvariantCulture),
        '-DispatchId', $dispatchId, '-OutputDir', $OutputDir,
        '-WorkingDirectory', [string](Get-Field $launch 'working_directory'),
        '-TimeoutSec', [string][int](Get-Field $launch 'timeout_sec'),
        '-Kind', [string](Get-Field $manifest 'kind'),
        '-PermissionMode', [string](Get-Field $launch 'permission_mode'),
        '-Effort', [string](Get-Field $launch 'effort'))
    $model = Get-Field $launch 'model'
    if ($model) { $wrapperArgs += @('-Model', [string]$model) }
    # One comma-joined text: pwsh -File passes each argument as a string, and the dispatch wrapper
    # splits on commas.
    $allowedTools = @(Get-Field $launch 'allowed_tools' | Where-Object { $_ })
    if ($allowedTools.Count -gt 0) { $wrapperArgs += @('-AllowedTools', ($allowedTools -join ',')) }
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
        # Inside the try: a launch.env that fails its second check closes the segment launch_failed.
        $environment = New-ChildEnvironment $launch $segmentId $baseCommit
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
        $null = Complete-CreditsSegment -StateDb $StateDb -SegmentId $segmentId -FinalizedBy launcher -Class launch_failed -CliStart (Get-CliStartFact $dispatchId)
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
            $null = Complete-CreditsSegment -StateDb $StateDb -SegmentId $segmentId -FinalizedBy launcher -Class launch_failed -CliStart (Get-CliStartFact $dispatchId)
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
    $completeArgs = @{}
    if ($class -eq 'launch_failed') { $completeArgs.CliStart = Get-CliStartFact $dispatchId }
    $done = Complete-CreditsSegment -StateDb $StateDb -SegmentId $segmentId -FinalizedBy launcher -Class $class -SessionTotalUsd $total -ExitCode $exitCode @completeArgs
    $finalClass = [string](Get-Field $done 'stop_class')
    if (-not $finalClass) { $finalClass = $class }
    $finalized = @{ segment_id = $segmentId; class = $finalClass; exit_code = $exitCode; session_total_usd = $total }
    if ($null -ne $done -and -not [bool](Get-Field $done 'cost_known')) {
        # PE21-D11: no trusted total. The log names the transcript estimate in place of 0 USD; the
        # exposure stays open at the full reservation until Get-CreditsRun.ps1 -Settle.
        try {
            $transcript = Get-CreditsTranscriptPath -ProjectRoot ([string](Get-Field $manifest 'project_root')) -SessionId $sessionId
            if ($transcript) {
                $estimate = Update-CreditsCostEstimate -StateDb $StateDb -SegmentId $segmentId -Transcript $transcript
                $finalized.cost_estimate_usd = Get-Field $estimate 'cost_estimate_usd'
            }
        } catch {
            Write-LauncherLog 'WARN' 'credits_cost_estimate_failed' @{ segment_id = $segmentId; message = $_.Exception.Message }
        }
    }
    Write-LauncherLog 'INFO' 'credits_segment_finalized' $finalized
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
