[CmdletBinding()]
param(
    # Omitted: list the most recent dispatches. Given: show that dispatch.
    [Parameter(Mandatory = $false, Position = 0)]
    [string]$DispatchId,

    [Parameter(Mandatory = $false)]
    [string]$OutputDir = '{{RECEIPTS_DIR}}/dispatch',

    # List mode: how many dispatches to show, newest first.
    [Parameter(Mandatory = $false)]
    [ValidateRange(1, 500)]
    [int]$Last = 15,

    # List mode: include Codex runs, which share the dispatch directory.
    [Parameter(Mandatory = $false)]
    [switch]$All,

    # Show mode: print the tail of the session transcript. It is written while
    # the run is live, so this is how a running dispatch is checked on.
    [Parameter(Mandatory = $false)]
    [switch]$Peek,

    # Peek: how many transcript entries (assistant text, tool calls, results).
    [Parameter(Mandatory = $false)]
    [ValidateRange(1, 500)]
    [int]$Tail = 12,

    # Emit the record as JSON instead of text (list or show).
    [Parameter(Mandatory = $false)]
    [switch]$Json,

    # Show mode: write status.json for a run that died before its wrapper wrote
    # one, from running.json and the transcript, marked `recovered: true`, so
    # the session can be resumed. A run that is still live is refused (run_alive).
    [Parameter(Mandatory = $false)]
    [switch]$RecoverStatus
)

# Reads the run directories that tools/Invoke-ClaudeDispatch.ps1 writes:
# status.json (written when the run ends), running.json (written at launch),
# final.md and output.json. It never starts or stops a run. The only write is
# -RecoverStatus, which adds the missing status.json of a dead run.

$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)

function Read-JsonFile {
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { return $null }
    try {
        return (Get-Content -LiteralPath $Path -Raw -Encoding UTF8 | ConvertFrom-Json -ErrorAction Stop)
    } catch {
        return $null
    }
}

function Get-Prop {
    param($Object, [string]$Name)
    if ($null -eq $Object) { return $null }
    $prop = $Object.PSObject.Properties[$Name]
    if ($null -eq $prop) { return $null }
    return $prop.Value
}

# pwsh 7 turns an ISO timestamp in JSON into a DateTime; Windows PowerShell
# keeps the string. Never round-trip a DateTime through a culture string: that
# drops its Kind, so the time is read as local and shifted by the UTC offset.
function ConvertTo-UtcDate {
    param($Value)
    if ($null -eq $Value -or '' -eq $Value) { return $null }
    if ($Value -is [datetime]) {
        if ($Value.Kind -eq [System.DateTimeKind]::Unspecified) {
            return [datetime]::SpecifyKind($Value, [System.DateTimeKind]::Utc)
        }
        return $Value.ToUniversalTime()
    }
    if ($Value -is [datetimeoffset]) { return $Value.UtcDateTime }
    $parsed = [datetimeoffset]::MinValue
    if ([datetimeoffset]::TryParse([string]$Value, [System.Globalization.CultureInfo]::InvariantCulture,
            [System.Globalization.DateTimeStyles]::AssumeUniversal, [ref]$parsed)) {
        return $parsed.UtcDateTime
    }
    return $null
}

# The Windows boot counter, as Invoke-ClaudeDispatch.ps1 records it in
# running.json `boot_id`. $null when it cannot be read.
function Get-CurrentBootId {
    $key = 'HKLM:\SYSTEM\CurrentControlSet\Control\Session Manager\Memory Management\PrefetchParameters'
    try {
        $value = (Get-ItemProperty -LiteralPath $key -Name BootId -ErrorAction Stop).BootId
        if ($null -eq $value) { return $null }
        return "bootid:$value"
    } catch {
        return $null
    }
}

# True when a process with this id exists and started at the recorded UTC time,
# within 1 s. Windows reuses process ids, so an id alone proves nothing.
function Test-RecordedProcess {
    param($ProcessId, $CreationUtc)
    $id = 0
    if (-not [int]::TryParse([string]$ProcessId, [ref]$id) -or $id -le 0) { return $false }
    $recorded = ConvertTo-UtcDate $CreationUtc
    if ($null -eq $recorded) { return $false }
    $proc = Get-Process -Id $id -ErrorAction SilentlyContinue
    if ($null -eq $proc) { return $false }
    try {
        $actual = $proc.StartTime.ToUniversalTime()
    } catch {
        return $false
    }
    return [math]::Abs(($actual - $recorded).TotalSeconds) -le 1
}

# A run is live when its CLI process or its wrapper process is live, each
# matched by id and creation time, in the boot that running.json names. A
# running.json from before these fields falls back to the cmd.exe id alone.
function Test-DispatchAlive {
    param($Running)
    if ($null -eq $Running) { return $false }
    $recordedBoot = Get-Prop $Running 'boot_id'
    if ($recordedBoot) {
        $currentBoot = Get-CurrentBootId
        if ($currentBoot -and $currentBoot -ne $recordedBoot) { return $false }
    }
    $checked = $false
    foreach ($pair in @(@('claude_pid', 'claude_creation_utc'), @('launcher_pid', 'launcher_creation_utc'))) {
        $procId = Get-Prop $Running $pair[0]
        if ($null -eq $procId) { continue }
        $checked = $true
        if (Test-RecordedProcess $procId (Get-Prop $Running $pair[1])) { return $true }
    }
    if ($checked) { return $false }
    $legacyId = Get-Prop $Running 'pid'
    if ($legacyId) { return $null -ne (Get-Process -Id $legacyId -ErrorAction SilentlyContinue) }
    return $false
}

# One record per run directory. state: ok | failed | timed_out | running |
# died (running.json and no status.json with the process gone, or a status.json
# that -RecoverStatus wrote) | unknown.
function Get-DispatchRecord {
    param([System.IO.DirectoryInfo]$Dir)
    $status = Read-JsonFile (Join-Path $Dir.FullName 'status.json')
    $running = Read-JsonFile (Join-Path $Dir.FullName 'running.json')
    $state = 'unknown'
    if ($null -ne $status) {
        if (Get-Prop $status 'recovered') { $state = 'died' }
        elseif (Get-Prop $status 'timed_out') { $state = 'timed_out' }
        elseif ((Get-Prop $status 'exit_code') -eq 0) { $state = 'ok' }
        else { $state = 'failed' }
    } elseif ($null -ne $running) {
        $state = if (Test-DispatchAlive $running) { 'running' } else { 'died' }
    }
    $src = if ($null -ne $status) { $status } else { $running }
    # Only the Claude wrapper writes running.json.
    $cli = Get-Prop $status 'cli'
    if ($null -eq $cli -and $null -ne $running) { $cli = 'claude' }
    $cost = Get-Prop $status 'total_cost_usd'
    if ($null -eq $cost) {
        $cost = Get-Prop (Read-JsonFile (Join-Path $Dir.FullName 'output.json')) 'total_cost_usd'
    }
    $elapsedMs = Get-Prop $status 'elapsed_ms'
    $startRaw = Get-Prop $src 'start_utc'
    $startDate = ConvertTo-UtcDate $startRaw
    $startUtc = if ($null -ne $startDate) {
        $startDate.ToString("yyyy-MM-dd'T'HH:mm:ss'Z'", [System.Globalization.CultureInfo]::InvariantCulture)
    } else { $startRaw }
    if ($null -eq $elapsedMs -and $state -eq 'running' -and $null -ne $startDate) {
        $elapsedMs = [math]::Round(((Get-Date).ToUniversalTime() - $startDate).TotalMilliseconds)
    }
    return [pscustomobject][ordered]@{
        dispatch_id = $Dir.Name
        state = $state
        cli = $cli
        model = Get-Prop $src 'model'
        model_class = Get-Prop $status 'model_class'
        reasoning_effort = Get-Prop $status 'reasoning_effort'
        auth_mode = Get-Prop $src 'auth_mode'
        cost_usd = $cost
        elapsed_s = if ($null -ne $elapsedMs) { [math]::Round($elapsedMs / 1000) } else { $null }
        start_utc = $startUtc
        session_id = Get-Prop $src 'session_id'
        session_mode = Get-Prop $src 'session_mode'
        source_dispatch_id = Get-Prop $status 'source_dispatch_id'
        working_directory = Get-Prop $src 'working_directory'
        error_summary = Get-Prop $status 'error_summary'
        recovered = [bool](Get-Prop $status 'recovered')
        run_dir = $Dir.FullName.Replace('\', '/')
    }
}

# The CLI writes ~/.claude/projects/<project-slug>/<session-id>.jsonl.
function Find-Transcript {
    param([string]$SessionId)
    if ([string]::IsNullOrEmpty($SessionId)) { return $null }
    $configDir = if ($env:CLAUDE_CONFIG_DIR) { $env:CLAUDE_CONFIG_DIR } else { Join-Path $HOME '.claude' }
    $projects = Join-Path $configDir 'projects'
    if (-not (Test-Path -LiteralPath $projects)) { return $null }
    return Get-ChildItem -LiteralPath $projects -Directory |
        ForEach-Object { Join-Path $_.FullName "$SessionId.jsonl" } |
        Where-Object { Test-Path -LiteralPath $_ -PathType Leaf } |
        Select-Object -First 1
}

function Format-Short {
    param([string]$Text, [int]$Max = 300)
    if ($null -eq $Text) { return '' }
    $one = ($Text -replace '\s+', ' ').Trim()
    if ($one.Length -gt $Max) { $one = $one.Substring(0, $Max) + '...' }
    return $one
}

# One pass over the transcript: the readable entries for -Peek and the prompt
# cache use. The CLI writes one line per content block, each carrying the
# message's usage, so usage is counted once per message id.
function Read-Transcript {
    param([string]$Path, [int]$Count)
    $entries = New-Object System.Collections.Generic.List[string]
    $seen = New-Object System.Collections.Generic.HashSet[string]
    $fresh = [long]0; $written = [long]0; $read = [long]0
    $last = $null
    foreach ($line in [System.IO.File]::ReadAllLines($Path, [System.Text.Encoding]::UTF8)) {
        if ([string]::IsNullOrWhiteSpace($line)) { continue }
        try { $rec = $line | ConvertFrom-Json -ErrorAction Stop } catch { continue }
        $type = Get-Prop $rec 'type'
        if ($type -ne 'assistant' -and $type -ne 'user') { continue }
        $message = Get-Prop $rec 'message'
        $usage = Get-Prop $message 'usage'
        $messageId = [string](Get-Prop $message 'id')
        if ($type -eq 'assistant' -and $null -ne $usage -and $messageId -and $seen.Add($messageId)) {
            $last = [ordered]@{
                input_tokens = [long](Get-Prop $usage 'input_tokens')
                cache_write_tokens = [long](Get-Prop $usage 'cache_creation_input_tokens')
                cache_read_tokens = [long](Get-Prop $usage 'cache_read_input_tokens')
            }
            $fresh += $last.input_tokens; $written += $last.cache_write_tokens; $read += $last.cache_read_tokens
        }
        $content = Get-Prop $message 'content'
        if ($content -is [string]) {
            if ($type -eq 'user') { $entries.Add("[prompt] $(Format-Short $content)") }
            continue
        }
        foreach ($block in @($content)) {
            switch (Get-Prop $block 'type') {
                'text' {
                    $tag = if ($type -eq 'assistant') { 'claude' } else { 'prompt' }
                    $entries.Add("[$tag] $(Format-Short (Get-Prop $block 'text'))")
                }
                'tool_use' {
                    $toolInput = Get-Prop $block 'input'
                    $arg = ''
                    foreach ($k in 'command', 'file_path', 'pattern', 'path', 'url', 'description') {
                        $v = Get-Prop $toolInput $k
                        if ($v) { $arg = Format-Short ([string]$v) 120; break }
                    }
                    $entries.Add("[tool] $(Get-Prop $block 'name')($arg)")
                }
                'tool_result' {
                    $c = Get-Prop $block 'content'
                    $text = if ($c -is [string]) { $c } else { (@($c) | ForEach-Object { Get-Prop $_ 'text' }) -join ' ' }
                    $mark = if (Get-Prop $block 'is_error') { 'error' } else { 'result' }
                    $entries.Add("[$mark] $(Format-Short $text 160)")
                }
            }
        }
    }
    $skip = [math]::Max(0, $entries.Count - $Count)
    $allInput = $fresh + $written + $read
    $cache = [ordered]@{
        calls = $seen.Count
        input_tokens = $fresh
        cache_write_tokens = $written
        cache_read_tokens = $read
        cache_read_share = if ($allInput -gt 0) { [math]::Round($read / $allInput, 3) } else { 0 }
        # Three calls is enough: a cached session reads its prefix from the second call on.
        caching_off = ($seen.Count -ge 3 -and $read -eq 0)
        last_call = $last
    }
    return @{ Total = $entries.Count; Lines = @($entries | Select-Object -Skip $skip); Cache = $cache }
}

if (-not (Test-Path -LiteralPath $OutputDir -PathType Container)) {
    [Console]::Error.WriteLine("no dispatch directory: $OutputDir")
    exit 1
}

# --- List
if ([string]::IsNullOrEmpty($DispatchId)) {
    if ($RecoverStatus) {
        [Console]::Error.WriteLine("-RecoverStatus needs a dispatch ID")
        exit 1
    }
    $records = @(Get-ChildItem -LiteralPath $OutputDir -Directory |
        Where-Object { (Test-Path (Join-Path $_.FullName 'status.json')) -or (Test-Path (Join-Path $_.FullName 'running.json')) } |
        Sort-Object LastWriteTime -Descending |
        ForEach-Object { Get-DispatchRecord $_ } |
        Where-Object { $All -or $_.cli -eq 'claude' } | Select-Object -First $Last)
    if ($Json) { ConvertTo-Json -InputObject $records -Depth 3; exit 0 }
    if ($records.Count -eq 0) { "no Claude dispatches in $OutputDir (-All includes Codex runs)"; exit 0 }
    ($records | Format-Table -AutoSize dispatch_id, state, cli, model, auth_mode,
        @{ n = 'cost'; e = { if ($null -ne $_.cost_usd) { '{0:N4}' -f [double]$_.cost_usd } } },
        @{ n = 'secs'; e = { $_.elapsed_s } }, session_mode, start_utc | Out-String -Width 220).Trim()
    exit 0
}

# --- Show
$runDir = Join-Path $OutputDir $DispatchId
if (-not (Test-Path -LiteralPath $runDir -PathType Container)) {
    [Console]::Error.WriteLine("dispatch not found: $runDir")
    exit 1
}

# --- Recover: status.json for a run that died before its wrapper wrote one.
if ($RecoverStatus) {
    $runningPath = Join-Path $runDir 'running.json'
    $statusPath = Join-Path $runDir 'status.json'
    $running = Read-JsonFile $runningPath
    if ($null -eq $running) {
        [Console]::Error.WriteLine("recover_no_running_manifest: no readable running.json in $runDir")
        exit 1
    }
    if (Test-Path -LiteralPath $statusPath) {
        [Console]::Error.WriteLine("recover_status_exists: $statusPath already exists")
        exit 1
    }
    if (Test-DispatchAlive $running) {
        [Console]::Error.WriteLine("run_alive: dispatch '$DispatchId' is still running; no status.json written")
        exit 1
    }
    $invariant = [System.Globalization.CultureInfo]::InvariantCulture
    $isoFormat = "yyyy-MM-dd'T'HH:mm:ss'Z'"
    $sessionId = Get-Prop $running 'session_id'
    $transcript = Find-Transcript ([string]$sessionId)
    $startDate = ConvertTo-UtcDate (Get-Prop $running 'start_utc')
    $endDate = if ($transcript) { (Get-Item -LiteralPath $transcript).LastWriteTimeUtc } else { $null }
    $elapsed = if ($null -ne $startDate -and $null -ne $endDate) {
        [math]::Max(0, [math]::Round(($endDate - $startDate).TotalMilliseconds))
    } else { $null }
    # The fields a resume or fork reads (cli, kind, model_class, session_id,
    # working_directory, permission_mode) come from running.json. The result
    # and the cost are unknown: the run never wrote output.json.
    $recoveredManifest = [ordered]@{
        schema_version = 'dispatch-status.v1'
        dispatch_id = $DispatchId
        model = Get-Prop $running 'model'
        model_class = Get-Prop $running 'model_class'
        cli = 'claude'
        kind = Get-Prop $running 'kind'
        session_id = $sessionId
        session_id_source = 'running_manifest'
        session_mode = Get-Prop $running 'session_mode'
        source_dispatch_id = Get-Prop $running 'source_dispatch_id'
        permission_mode = Get-Prop $running 'permission_mode'
        start_utc = if ($null -ne $startDate) { $startDate.ToString($isoFormat, $invariant) } else { $null }
        end_utc = if ($null -ne $endDate) { $endDate.ToString($isoFormat, $invariant) } else { $null }
        elapsed_ms = $elapsed
        timed_out = $false
        exit_code = $null
        child_exit_code = $null
        is_error = $null
        error_summary = 'recovered: the run ended before its wrapper wrote status.json; the result and the cost are unknown'
        auth_mode = Get-Prop $running 'auth_mode'
        total_cost_usd = $null
        session_total_usd = $null
        segment_delta_usd = $null
        cost_untrusted = $true
        working_directory = Get-Prop $running 'working_directory'
        transcript = if ($transcript) { ([string]$transcript).Replace('\', '/') } else { $null }
        recovered = $true
        recovered_utc = (Get-Date).ToUniversalTime().ToString($isoFormat, $invariant)
    }
    $statusTmp = "$statusPath.tmp"
    [System.IO.File]::WriteAllText($statusTmp, ($recoveredManifest | ConvertTo-Json -Depth 3),
        (New-Object System.Text.UTF8Encoding($false)))
    Move-Item -LiteralPath $statusTmp -Destination $statusPath -Force
    [Console]::Out.WriteLine("recovered_status_written $($statusPath.Replace('\', '/'))")
    exit 0
}

$record = Get-DispatchRecord (Get-Item -LiteralPath $runDir)
$finalPath = Join-Path $runDir 'final.md'
$final = if (Test-Path -LiteralPath $finalPath -PathType Leaf) { [System.IO.File]::ReadAllText($finalPath, [System.Text.Encoding]::UTF8) } else { $null }
$transcript = Find-Transcript $record.session_id
$tailInfo = if ($transcript) { Read-Transcript $transcript $Tail } else { $null }

if ($Json) {
    $out = [ordered]@{}
    foreach ($p in $record.PSObject.Properties) { $out[$p.Name] = $p.Value }
    $out['transcript'] = $transcript
    $out['final'] = $final
    $out['cache'] = if ($tailInfo) { $tailInfo.Cache } else { $null }
    if ($Peek -and $tailInfo) { $out['transcript_tail'] = $tailInfo.Lines }
    ConvertTo-Json -InputObject $out -Depth 4
    exit 0
}

($record | Format-List dispatch_id, state, cli, model, reasoning_effort, model_class, auth_mode, cost_usd, elapsed_s,
    start_utc, session_id, session_mode, source_dispatch_id, working_directory, error_summary, run_dir | Out-String -Width 220).Trim()
''

if ($tailInfo -and $tailInfo.Cache.calls -gt 0) {
    $c = $tailInfo.Cache
    $line = "--- prompt cache: $($c.calls) calls | cache_read_share $($c.cache_read_share) | input $($c.input_tokens), cache write $($c.cache_write_tokens), cache read $($c.cache_read_tokens)"
    if ($c.last_call) { $line += " | last call: input $($c.last_call.input_tokens), write $($c.last_call.cache_write_tokens), read $($c.last_call.cache_read_tokens)" }
    $line
    if ($c.caching_off) {
        "    CACHING OFF: no cache reads in $($c.calls) calls, so every call resends the whole context at the full input price."
        '    Look for DISABLE_PROMPT_CACHING* in the launching process and in the env block of settings.json.'
    }
    ''
}

if ($Peek) {
    if ($tailInfo) {
        $age = [math]::Round(((Get-Date) - (Get-Item -LiteralPath $transcript).LastWriteTime).TotalSeconds)
        "--- transcript: last $($tailInfo.Lines.Count) of $($tailInfo.Total) entries (last write ${age}s ago)"
        $tailInfo.Lines
        ''
    } else {
        "--- no transcript found for session $($record.session_id)"
        ''
    }
}

if ($null -ne $final) {
    '--- final.md'
    $final
} elseif ($record.state -eq 'running') {
    '--- still running; final.md is written when it ends. Use -Peek to follow the transcript.'
}

if ($record.cli -eq 'claude' -and ($record.state -in 'ok', 'failed', 'timed_out' -or $record.recovered) -and $record.model_class) {
    ''
    '--- continue this session:'
    "tools/Invoke-ClaudeDispatch.ps1 -ResumeDispatchId $($record.dispatch_id) -DispatchId <new-id> -ModelClass $($record.model_class) -WorkingDirectory `"$($record.working_directory)`" -PromptText `"...`""
}
exit 0
