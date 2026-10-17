# S6b rulings (Component I of docs/execution/plans/2026-10-15-scheduled-credits-runs).
# AC-I.2 Get-CreditsRun.ps1 -AttachSession <session> -UserMessageUuid <uuid> (report section 4.5)
# adds an IDE session to the run's orchestrator sessions after its own five steps: (1) the
# transcript is found from the manifest's project root and the session id, never from an argument
# path; (2) the history check of section 4.6.3 passes from the first record (a whole parent
# chain) and writes the first mark; (3) the uuid passes the entry and queue-chain checks, later than
# the run's registration and its last attach; (4) the normalized text holds `attach <run id>`;
# (5) the uuid and the promptId are used once. The monitor scans each attached transcript on each
# pass (report section 4.4 step 3); a transcript_discontinuity notifies once (MX-28).
# AC-I.3 Send-CreditsRunMessage.ps1 sends the ruling kind (report section 4.6.2).
# AC-I.6 Register-CreditsRun.ps1 allows ruling_enabled true or gate_wait_max_min > 0 only when the
# row-26 anchor lines (GOV_DIFFS: GUARDRAILS SIGN 3 (b), the AGENTS.md HARD STOP sentence and the
# human-decision-protocol §5 line) are in the tree (report section 7.7; section 11 S6b).
# AC-I.7 the shipped config is the template default: ruling_enabled false, gate_wait_max_min 0.
#
# Chosen names (the design gives none; the nearest section is in brackets):
# - `~` of the attach and of the monitor scan is USERPROFILE (HOME too), and the project slug is
#   the manifest project_root with each character outside [A-Za-z0-9] replaced by '-' [R§4.6.3 step 2].
# - The anchor lines are read from the manifest project_root, the tree the run works in
#   [R§7.7; AC-I.6 "in the tree"]. The refusal keeps the reason messaging_locked [AC-D.1].
# - The attach prints the store's JSON line: exit 0 with result changed, or exit 3 with the reason
#   in `error` [R§4.5; the exit codes of Get-CreditsRun.ps1].
# - The monitor notice of a broken history has kind transcript_discontinuity and the key
#   transcript_discontinuity:<session> [R§4.4 step 3; the kind:ref key form of the other notices].
#
# Every store, project, home and transcript is a temp file under {{RECEIPTS_DIR}}/credits-ruling-tests.
# No test touches the real store or a scheduled task: Register gets the fake scheduler adapter.

BeforeAll {
    $script:Repo = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
    $script:Skill = Join-Path $script:Repo '.agent/skills/claude-credits'
    $script:Register = Join-Path $script:Skill 'Register-CreditsRun.ps1'
    $script:GetRun = Join-Path $script:Skill 'Get-CreditsRun.ps1'
    $script:Send = Join-Path $script:Skill 'Send-CreditsRunMessage.ps1'
    $script:Watch = Join-Path $script:Skill 'Watch-CreditsRuns.ps1'
    $script:MsgSchema = Join-Path $script:Skill 'schemas/credits-msg.v1.json'
    $script:ShippedConfig = Join-Path $script:Repo '.agent/credits/config.json'
    $script:StateTool = Join-Path $script:Repo 'tools/credits_state.py'
    $script:Root = "{{RECEIPTS_DIR}}/credits-ruling-tests/$([guid]::NewGuid().ToString('N'))"
    $script:HomeDir = "$script:Root/home"
    $script:Out = "$script:Root/dispatch"
    New-Item -ItemType Directory -Force -Path $script:HomeDir, $script:Out | Out-Null
    $script:EffectLog = "$script:Root/effects.jsonl"
    $script:SavedEffectLog = $env:CREDITS_TEST_EFFECT_LOG
    $env:CREDITS_TEST_EFFECT_LOG = $script:EffectLog

    # The row-26 anchor files (GOV_DIFFS) and, for each, one line that the approved text added.
    $script:AnchorFiles = @('GUARDRAILS.md', 'AGENTS.md', '.agent/docs/human-decision-protocol.md')
    $script:AnchorVerifiedFrame = 'except the hook frame `ruling (verified: <session>/<uuid>)` that (b) names'
    $script:AnchorSignB = 'a credits-inbox `ruling` that the inbox hook matched to a user-typed entry'
    $script:AnchorHardStop = 'Under `end_turn_signal: gate-wait-then-exit`, a human-decision gate first runs that bounded wait'
    $script:AnchorHdp = '(`gate-wait-then-exit` is the one bounded wait, defined in `harness-profiles.md`)'

    # The R§4.1 / R§6 template default of the credits config.
    $script:TemplateDefault = [ordered]@{ ruling_enabled = $false; gate_wait_max_min = 0; cache_ttl = '5m'; credits_start_policy = 'human-only' }

    $venvPy = Join-Path $script:Repo '.venv/Scripts/python.exe'
    $script:Py = if (Test-Path -LiteralPath $venvPy) { $venvPy } else { (Get-Command python -ErrorAction Stop).Source }
    $script:BasePython = (& $script:Py -c 'import sys; print(sys._base_executable)' | Out-String).Trim()

    # A fake key file (a fixture string, never a real key) and a brief.
    $script:KeyFile = "$script:Root/fake.key"
    Set-Content -LiteralPath $script:KeyFile -Value ('sk-' + 'ant-api03-' + ('A' * 40)) -Encoding utf8NoBOM
    $script:Brief = "$script:Root/brief.md"
    Set-Content -LiteralPath $script:Brief -Value 'credits ruling test brief' -Encoding utf8NoBOM

    # The mock CLI answers --version only; no test starts a session.
    $mockPy = "$script:Root/mock_claude.py"
    Set-Content -LiteralPath $mockPy -Encoding utf8NoBOM -Value @'
import sys

if "--version" in sys.argv[1:]:
    print("2.1.296 (Claude Code)")
    sys.exit(0)
print("mock claude: the ruling tests never start a session", file=sys.stderr)
sys.exit(9)
'@
    $script:Mock = "$script:Root/mock_claude.bat"
    Set-Content -LiteralPath $script:Mock -Encoding ascii -Value "@echo off`r`n`"$script:BasePython`" -X utf8 `"$mockPy`" %*"

    # The mock M-1 gate: exit 0 only for a receipt whose fixture_verdict is "ok".
    $script:GatePy = "$script:Root/mock_run_gate.py"
    Set-Content -LiteralPath $script:GatePy -Encoding utf8NoBOM -Value @'
import json
import sys

args = sys.argv[1:]
receipt = args[args.index("--check-receipt") + 1]
try:
    with open(receipt, encoding="utf-8") as f:
        doc = json.load(f)
except (OSError, ValueError):
    print(f"RECEIPT REJECTED: {receipt}")
    sys.exit(1)
if doc.get("fixture_verdict") == "ok":
    print(f"RECEIPT OK: {receipt}")
    sys.exit(0)
print(f"RECEIPT REJECTED: {receipt}")
sys.exit(1)
'@
    $script:Receipt = "$script:Root/receipt/gate-result.json"
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $script:Receipt) | Out-Null
    Set-Content -LiteralPath $script:Receipt -Encoding utf8NoBOM -Value '{"fixture_verdict": "ok", "cli_version": "2.1.296", "identity": {"kit_revision": "kitrev-fixture"}}'

    $script:Record = "$script:Root/probe-record.md"
    Set-Content -LiteralPath $script:Record -Encoding utf8NoBOM -Value ((@('# Probe Record fixture', '', '```yaml', 'probe_record:', '  p7_decision: run', '  p8b_driver: pending', '```', '')) -join "`n")

    # The store clock of each run: registration 30 minutes ago, so every transcript entry of a test
    # lies after the registration and before the real time of the attach.
    $script:T0 = [datetime]::SpecifyKind([datetime]::UtcNow.AddMinutes(-30), [System.DateTimeKind]::Utc)
    $script:T0 = $script:T0.AddTicks(- ($script:T0.Ticks % [timespan]::TicksPerSecond))

    function New-Id([string]$Prefix) { "$Prefix-$([guid]::NewGuid().ToString('N').Substring(0, 10))" }
    function New-Uuid { [guid]::NewGuid().ToString().ToLowerInvariant() }
    function Get-UtcText([datetime]$Value) { $Value.ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ') }
    function Get-Stamp([double]$Seconds) { $script:T0.AddSeconds($Seconds).ToString('yyyy-MM-ddTHH:mm:ss.fffZ') }
    function Get-Slug([string]$ProjectRoot) { $ProjectRoot -replace '[^A-Za-z0-9]', '-' }

    # Start a child with no inherited CREDITS_* value, the test effect log, and the given values
    # ($null removes a name).
    function Start-Clean([string]$File, [string[]]$Arguments, [hashtable]$Env = @{}) {
        $psi = [System.Diagnostics.ProcessStartInfo]::new($File)
        foreach ($a in $Arguments) { $psi.ArgumentList.Add([string]$a) }
        $psi.UseShellExecute = $false
        $psi.RedirectStandardOutput = $true
        $psi.RedirectStandardError = $true
        $psi.StandardOutputEncoding = [System.Text.Encoding]::UTF8
        $psi.StandardErrorEncoding = [System.Text.Encoding]::UTF8
        foreach ($name in @($psi.Environment.Keys)) {
            if ($name -like 'CREDITS_*' -or $name -in @('CLAUDECODE', 'CLAUDE_CODE_ENTRYPOINT')) { $null = $psi.Environment.Remove($name) }
        }
        $psi.Environment['CREDITS_TEST_EFFECT_LOG'] = $script:EffectLog
        foreach ($k in $Env.Keys) {
            if ($null -eq $Env[$k]) { $null = $psi.Environment.Remove($k) } else { $psi.Environment[$k] = [string]$Env[$k] }
        }
        $p = [System.Diagnostics.Process]::Start($psi)
        $so = $p.StandardOutput.ReadToEndAsync(); $se = $p.StandardError.ReadToEndAsync()
        if (-not $p.WaitForExit(120000)) { & taskkill.exe /PID $p.Id /T /F *> $null; throw "timed out: $File" }
        $p.WaitForExit()
        [pscustomobject]@{ Code = $p.ExitCode; Out = $so.Result; Err = $se.Result }
    }

    function Get-LastJson([string]$Text) {
        $last = @("$Text" -split "`r?`n" | Where-Object { $_.TrimStart().StartsWith('{') }) | Select-Object -Last 1
        if (-not $last) { return $null }
        try { $last | ConvertFrom-Json -ErrorAction Stop } catch { $null }
    }

    # The env of a child that reads a transcript: `~` is the temp home.
    function Get-HomeEnv { @{ USERPROFILE = $script:HomeDir; HOME = $script:HomeDir; CLAUDE_CONFIG_DIR = $null } }

    function Invoke-Store([string]$Db, [string]$Verb, [string[]]$Arguments = @(), [Nullable[datetime]]$NowUtc = $null) {
        $head = @('-X', 'utf8', $script:StateTool, '--db', $Db)
        if ($null -ne $NowUtc) { $head += @('--now-utc', (Get-UtcText $NowUtc)) }
        $res = Start-Clean $script:Py ($head + @($Verb) + $Arguments) (Get-HomeEnv)
        if ($res.Code -ne 0) { throw "store $Verb failed: exit=$($res.Code) out=$($res.Out) err=$($res.Err)" }
        $res.Out
    }

    function Get-Rows([string]$Db, [string]$Sql, [string[]]$Params = @()) {
        if (-not (Test-Path -LiteralPath $Db)) { return @() }
        $code = 'import json, sqlite3, sys; c = sqlite3.connect("file:" + sys.argv[1] + "?mode=ro", uri=True); c.row_factory = sqlite3.Row; print(json.dumps([dict(r) for r in c.execute(sys.argv[2], sys.argv[3:])]))'
        @((& $script:Py -X utf8 -c $code $Db $Sql @Params | Out-String) | ConvertFrom-Json)
    }

    function New-Store {
        $dir = "$script:Root/store-$([guid]::NewGuid().ToString('N').Substring(0, 10))"
        New-Item -ItemType Directory -Force -Path $dir | Out-Null
        $db = "$dir/state.db"
        Invoke-Store $db 'init' | Out-Null
        $db
    }

    # A project folder; -Anchors copies the three row-26 anchor files of this tree into it, and
    # -Edit changes their text (a scriptblock that takes and returns the file text and its name).
    function New-Project([switch]$Anchors, [scriptblock]$Edit = $null) {
        $project = "$script:Root/project-$([guid]::NewGuid().ToString('N').Substring(0, 8))"
        New-Item -ItemType Directory -Force -Path $project | Out-Null
        if ($Anchors) {
            foreach ($rel in $script:AnchorFiles) {
                $text = [System.IO.File]::ReadAllText((Join-Path $script:Repo $rel), [System.Text.Encoding]::UTF8)
                if ($null -ne $Edit) { $text = & $Edit $text $rel }
                $target = Join-Path $project $rel
                New-Item -ItemType Directory -Force -Path (Split-Path -Parent $target) | Out-Null
                [System.IO.File]::WriteAllText($target, $text, [System.Text.UTF8Encoding]::new($false))
            }
        }
        $project
    }

    # Remove each line of a text that contains the needle (ordinal, no wildcards).
    function Remove-LineWith([string]$Text, [string]$Needle) {
        (@($Text -split "`n" | Where-Object { -not $_.Contains($Needle) })) -join "`n"
    }

    function New-ManifestDoc([string]$RunId, [string]$Project, [bool]$Ruling = $false, [int]$GateWait = 0, [string[]]$Sessions = @('00000000-0000-4000-8000-0000000000aa'), [string]$Lane = '') {
        if (-not $Lane) { $Lane = "tree:$Project" }
        [ordered]@{
            schema = 'credits-run.v1'; run_id = $RunId; kind = 'exec'
            project_root = $Project; plan_folder = 'docs/execution/plans/2026-10-15-fixture/'
            brief = $script:Brief
            launch = [ordered]@{
                working_directory = $Project; claude_exe = $script:Mock; python_exe = $script:Py
                permission_mode = 'bypassPermissions'; effort = 'low'; segment_cap_usd = 20.0; timeout_sec = 3600
            }
            budget = [ordered]@{ run_cap_usd = 50.0 }
            messaging = [ordered]@{ orchestrator_sessions = @($Sessions); ruling_enabled = $Ruling; gate_wait_max_min = $GateWait }
            depends_on = @(); lane = $Lane
        }
    }

    function Save-Manifest($Doc) {
        $path = "$script:Root/manifest-$($Doc.run_id)-$([guid]::NewGuid().ToString('N').Substring(0, 6)).json"
        Set-Content -LiteralPath $path -Value ($Doc | ConvertTo-Json -Depth 8) -Encoding utf8NoBOM
        $path
    }

    function New-Config([bool]$Ruling = $false, [int]$GateWait = 0) {
        $path = "$script:Root/config-$([guid]::NewGuid().ToString('N').Substring(0, 8)).json"
        $doc = [ordered]@{ ruling_enabled = $Ruling; gate_wait_max_min = $GateWait; cache_ttl = '5m'; credits_start_policy = 'human-only' }
        Set-Content -LiteralPath $path -Value ($doc | ConvertTo-Json) -Encoding utf8NoBOM
        $path
    }

    # The fake scheduler adapter of the Register tests (AC-D.6): no real task is registered.
    function New-FakeScheduler {
        $state = @{ Tasks = @{}; Calls = [System.Collections.Generic.List[string]]::new() }
        @{
            State    = $state
            Register = { param($Definition) $key = "$($Definition.TaskPath)$($Definition.TaskName)"; $state.Calls.Add("Register:$key"); $state.Tasks[$key] = $Definition }.GetNewClosure()
            Get      = { param($TaskPath, $TaskName) $state.Calls.Add("Get:$TaskPath$TaskName"); $state.Tasks["$TaskPath$TaskName"] }.GetNewClosure()
            Start    = { param($TaskPath, $TaskName) $state.Calls.Add("Start:$TaskPath$TaskName") }.GetNewClosure()
        }
    }

    # Register-CreditsRun.ps1 in this process; a throw fails the test, not the container.
    function Invoke-Register([string]$Db, [string]$Manifest, [string]$Config, [hashtable]$Scheduler) {
        $params = @{
            Manifest = $Manifest; Receipt = $script:Receipt; StateDb = $Db; ConfigPath = $Config
            ProbeRecord = $script:Record; Scheduler = $Scheduler; RunGate = $script:GatePy; KeyFile = $script:KeyFile
        }
        $global:LASTEXITCODE = 0
        $lines = @(); $thrown = $null
        try { $lines = @(& $script:Register @params 2>$null) } catch { $thrown = $_.Exception.Message }
        $code = $global:LASTEXITCODE
        [pscustomobject]@{ Code = $code; Payload = (Get-LastJson (($lines | ForEach-Object { "$_" }) -join "`n")); Thrown = $thrown }
    }

    # A job run registered in the store at T0 with ruling_enabled true (the store accepts it).
    function New-StoreRun([string]$Db, [string]$Project, [string[]]$Sessions, [string]$Prefix = 'i2') {
        $runId = New-Id $Prefix
        $doc = New-ManifestDoc $runId $Project $true 0 $Sessions "tree:$Project/$runId"
        $manifest = Save-Manifest $doc
        Invoke-Store $Db 'register' @('--run-id', $runId, '--manifest', $manifest, '--cli-version', '2.1.296', '--kit-revision', 'kitrev-fixture') $script:T0 | Out-Null
        Invoke-Store $Db 'registered' @('--run-id', $runId, '--task-hash', "taskhash-$runId") $script:T0 | Out-Null
        $runId
    }

    # --- transcripts (the record shapes of the M-6 fixture, R§10.2) ---------------------------

    function New-Transcript([string]$Project, [string]$Session) {
        $path = "$script:HomeDir/.claude/projects/$(Get-Slug $Project)/$Session.jsonl"
        New-Item -ItemType Directory -Force -Path (Split-Path -Parent $path) | Out-Null
        [pscustomobject]@{ Path = $path; Session = $Session; Lines = [System.Collections.Generic.List[string]]::new(); Last = $null }
    }

    function Save-Transcript($T) {
        $text = (@($T.Lines) | ForEach-Object { "$_`n" }) -join ''
        [System.IO.File]::WriteAllText($T.Path, $text, [System.Text.UTF8Encoding]::new($false))
    }

    function Add-Record($T, $Record, [bool]$Chained) {
        if ($Chained) { $T.Last = $Record['uuid'] }
        $T.Lines.Add(($Record | ConvertTo-Json -Compress -Depth 12))
        Save-Transcript $T
    }

    # A typed entry with every field of R§4.6.3 step 4. -Drop removes fields; -Parent replaces the link.
    function Add-User($T, [string]$Text, [double]$Seconds, [string]$PromptId = '', [string[]]$Drop = @(), [string]$Parent = '<last>') {
        $uid = New-Uuid
        if (-not $PromptId) { $PromptId = New-Uuid }
        $record = [ordered]@{
            parentUuid = $(if ($Parent -eq '<last>') { $T.Last } else { $Parent })
            isSidechain = $false; promptId = $PromptId; type = 'user'
            message = [ordered]@{ role = 'user'; content = @([ordered]@{ type = 'text'; text = $Text }) }
            uuid = $uid; timestamp = (Get-Stamp $Seconds); permissionMode = 'bypassPermissions'
            origin = [ordered]@{ kind = 'human' }; promptSource = 'sdk'; turnOrigin = 'human'
            turnPosition = [ordered]@{ promptIndex = 1; turnIndex = 1 }; userType = 'external'
            entrypoint = 'sdk-cli'; cwd = 'X:/s6b-fixture'; sessionId = $T.Session; version = '2.1.296'; gitBranch = 'main'
        }
        foreach ($key in $Drop) { $record.Remove($key) }
        Add-Record $T $record $true
        $uid
    }

    function Add-Assistant($T, [string]$Text, [double]$Seconds) {
        $uid = New-Uuid
        $record = [ordered]@{
            parentUuid = $T.Last; isSidechain = $false
            message = [ordered]@{ model = 'fixture-model'; id = "msg_$($uid.Substring(0, 8))"; type = 'message'; role = 'assistant'; content = @([ordered]@{ type = 'text'; text = $Text }) }
            type = 'assistant'; uuid = $uid; timestamp = (Get-Stamp $Seconds); sessionId = $T.Session; version = '2.1.296'
        }
        Add-Record $T $record $true
        $uid
    }

    function Add-QueueOp($T, [string]$Operation, [double]$Seconds, [hashtable]$Fields = @{}) {
        $record = [ordered]@{ type = 'queue-operation'; operation = $Operation; timestamp = (Get-Stamp $Seconds); sessionId = $T.Session }
        foreach ($k in $Fields.Keys) { $record[$k] = $Fields[$k] }
        Add-Record $T $record $false
    }

    function Add-QueuedCommand($T, [string]$Text, [double]$Seconds, [string]$DeliveryId) {
        $uid = New-Uuid
        $record = [ordered]@{
            parentUuid = $T.Last; isSidechain = $false
            attachment = [ordered]@{
                type = 'queued_command'; prompt = @([ordered]@{ type = 'text'; text = $Text }); source_uuid = (New-Uuid)
                commandMode = 'prompt'; origin = [ordered]@{ kind = 'human' }; timestamp = (Get-Stamp $Seconds); humanTurn = $true; delivery_id = $DeliveryId
            }
            type = 'attachment'; uuid = $uid; timestamp = (Get-Stamp $Seconds); sessionId = $T.Session; version = '2.1.296'
        }
        Add-Record $T $record $true
        $uid
    }

    function Get-FileLength([string]$Path) { (Get-Item -LiteralPath $Path).Length }

    # Get-CreditsRun.ps1 <run> -AttachSession <session> -UserMessageUuid <uuid> in a child pwsh.
    function Invoke-Attach([string]$Db, [string]$RunId, [string]$Session, [string]$Uuid) {
        $res = Start-Clean 'pwsh' @('-NoProfile', '-NonInteractive', '-File', $script:GetRun, $RunId, '-AttachSession', $Session, '-UserMessageUuid', $Uuid, '-StateDb', $Db, '-OutputDir', $script:Out) (Get-HomeEnv)
        [pscustomobject]@{ Code = $res.Code; Json = (Get-LastJson $res.Out); Out = $res.Out; Err = $res.Err }
    }

    function Get-Attached([string]$Db, [string]$RunId, [string]$Session) {
        @(Get-Rows $Db 'SELECT * FROM orchestrator_sessions WHERE run_id = ? AND session = ?' @($RunId, $Session)) | Select-Object -First 1
    }
    function Get-Attaches([string]$Db, [string]$RunId) { @(Get-Rows $Db 'SELECT * FROM attaches WHERE run_id = ?' @($RunId)) }
    function Get-Mark([string]$Db, [string]$Session) { @(Get-Rows $Db 'SELECT * FROM transcript_marks WHERE session = ?' @($Session)) | Select-Object -First 1 }

    # Assert a refused attach: exit 3, no attaches row and no ok session row for the run.
    function Assert-AttachRefused($Res, [string]$Db, [string]$RunId, [string]$Session, [string[]]$Reasons = @()) {
        $Res.Code | Should -Be 3 -Because "$($Res.Out) $($Res.Err)"
        $Res.Json | Should -Not -BeNullOrEmpty -Because "$($Res.Out) $($Res.Err)"
        $Res.Json.error | Should -Not -BeNullOrEmpty
        if ($Reasons.Count -gt 0) { $Res.Json.error | Should -BeIn $Reasons }
        @(Get-Attaches $Db $RunId).Count | Should -Be 0
        $row = Get-Attached $Db $RunId $Session
        if ($null -ne $row) { $row.history_state | Should -Not -Be 'ok' }
    }

    function Invoke-Send([string]$Db, [string[]]$Arguments) {
        $res = Start-Clean 'pwsh' (@('-NoProfile', '-NonInteractive', '-File', $script:Send, '-StateDb', $Db) + $Arguments)
        [pscustomobject]@{ Code = $res.Code; Out = $res.Out; Err = $res.Err; Json = (Get-LastJson $res.Out) }
    }

    # The canonical hash of a message's identity fields (R§4.6.2): sorted keys, no spaces, UTF-8.
    function Get-RulingHash([string]$RunId, [string]$Quote, [string]$Decision, [string]$GateId, [string]$Session, [string]$Uuid) {
        $code = 'import hashlib, json, sys; a = sys.argv[1:]; doc = {"run_id": a[0], "kind": "ruling", "human_quote": a[1], "decision_id": a[2], "gate_id": a[3], "orchestrator_session_id": a[4], "user_message_uuid": a[5]}; print(hashlib.sha256(json.dumps(doc, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")).hexdigest())'
        (& $script:Py -X utf8 -c $code $RunId $Quote $Decision $GateId $Session $Uuid | Out-String).Trim()
    }

    function New-Notifier {
        $sent = [System.Collections.Generic.List[object]]::new()
        $script:LastSent = $sent
        { param($notice) $sent.Add($notice) }.GetNewClosure()
    }
    function Get-SentFor($Sent, [string]$Key) { @($Sent | Where-Object { "$($_.subject)" -like "*$Key*" }) }

    # One monitor pass in this process. `~` of the pass (and of its children) is the temp home;
    # the real USERPROFILE and HOME come back after the pass.
    function Invoke-Watch([string]$Db, [scriptblock]$Notifier) {
        $names = @('USERPROFILE', 'HOME', 'CLAUDE_CONFIG_DIR')
        $saved = @{}
        foreach ($n in $names) { $saved[$n] = [Environment]::GetEnvironmentVariable($n) }
        $global:LASTEXITCODE = 0
        $lines = @(); $thrown = $null
        try {
            [Environment]::SetEnvironmentVariable('USERPROFILE', $script:HomeDir)
            [Environment]::SetEnvironmentVariable('HOME', $script:HomeDir)
            [Environment]::SetEnvironmentVariable('CLAUDE_CONFIG_DIR', $null)
            $lines = @(& $script:Watch -StateDb $Db -OutputDir $script:Out -Observations @{} -Notifier $Notifier -HostEvents @() 2>$null)
        } catch {
            $thrown = $_.Exception.Message
        } finally {
            foreach ($n in $names) { [Environment]::SetEnvironmentVariable($n, $saved[$n]) }
        }
        $code = $global:LASTEXITCODE
        [pscustomobject]@{ Code = $code; Payload = (Get-LastJson (($lines | ForEach-Object { "$_" }) -join "`n")); Thrown = $thrown }
    }
}

AfterAll {
    $env:CREDITS_TEST_EFFECT_LOG = $script:SavedEffectLog
    if ($script:Root -and (Test-Path -LiteralPath $script:Root)) { Remove-Item -LiteralPath $script:Root -Recurse -Force -ErrorAction SilentlyContinue }
}

Describe 'AC-I.2: Get-CreditsRun.ps1 -AttachSession (report section 4.5)' {
    It 'AC-I.2: the check takes -AttachSession and -UserMessageUuid' {
        $params = (Get-Command -Name $script:GetRun).Parameters.Keys
        $params | Should -Contain 'AttachSession'
        $params | Should -Contain 'UserMessageUuid'
    }

    It 'AC-I.2: a typed "attach RUN_ID" entry with a whole parent chain attaches the session (steps 1 to 5)' {
        $db = New-Store
        $project = New-Project
        $session = New-Uuid
        $run = New-StoreRun $db $project @($session)
        $t = New-Transcript $project $session
        Add-User $t 'start the fixture plan' 10 | Out-Null
        Add-Assistant $t 'the plan runs' 20 | Out-Null
        $pid_ = New-Uuid
        $uid = Add-User $t "attach $run" 30 -PromptId $pid_
        $res = Invoke-Attach $db $run $session $uid
        $res.Code | Should -Be 0 -Because "$($res.Out) $($res.Err)"
        $res.Json.result | Should -Be 'changed'
        $row = Get-Attached $db $run $session
        $row | Should -Not -BeNullOrEmpty
        $row.history_state | Should -Be 'ok'
        $attaches = @(Get-Attaches $db $run)
        $attaches.Count | Should -Be 1
        $attaches[0].orchestrator_session | Should -Be $session
        $attaches[0].user_message_uuid | Should -Be $uid
        $attaches[0].prompt_id | Should -Be $pid_
        # Step 2: the attach scan writes the session's first mark over the whole file.
        $mark = Get-Mark $db $session
        $mark | Should -Not -BeNullOrEmpty
        [int64]$mark.byte_length | Should -Be (Get-FileLength $t.Path)
        [int]$mark.line_count | Should -Be 3
    }

    It 'AC-I.2 step 1: a transcript under another project slug is not the run''s transcript → refused' {
        $db = New-Store
        $project = New-Project
        $session = New-Uuid
        $run = New-StoreRun $db $project @($session)
        $t = New-Transcript (New-Project) $session
        Add-User $t 'start the fixture plan' 10 | Out-Null
        $uid = Add-User $t "attach $run" 20
        Assert-AttachRefused (Invoke-Attach $db $run $session $uid) $db $run $session
    }

    It 'mx_28_ AC-I.2 step 2: a broken parent chain at attach → refused; the session is not attached' {
        $db = New-Store
        $project = New-Project
        $session = New-Uuid
        $run = New-StoreRun $db $project @($session)
        $t = New-Transcript $project $session
        Add-User $t 'start the fixture plan' 10 | Out-Null
        Add-Assistant $t 'the plan runs' 20 | Out-Null
        # A chained record whose parent does not resolve: a removed line.
        Add-User $t 'more context' 25 -Parent (New-Uuid) | Out-Null
        $uid = Add-User $t "attach $run" 30
        Assert-AttachRefused (Invoke-Attach $db $run $session $uid) $db $run $session @('transcript_discontinuity', 'transcript_unknown')
    }

    It 'AC-I.2 step 3: an entry with no <Field> → refused not_typed_turn' -ForEach @(
        @{ Field = 'turnOrigin' }
        @{ Field = 'promptSource' }
        @{ Field = 'promptId' }
    ) {
        $db = New-Store
        $project = New-Project
        $session = New-Uuid
        $run = New-StoreRun $db $project @($session)
        $t = New-Transcript $project $session
        Add-User $t 'start the fixture plan' 10 | Out-Null
        $uid = Add-User $t "attach $run" 20 -Drop @($Field)
        Assert-AttachRefused (Invoke-Attach $db $run $session $uid) $db $run $session @('not_typed_turn')
    }

    It 'AC-I.2 step 3: an entry earlier than the run''s registration → refused' {
        $db = New-Store
        $project = New-Project
        $session = New-Uuid
        $run = New-StoreRun $db $project @($session)
        $t = New-Transcript $project $session
        Add-User $t 'start the fixture plan' -120 | Out-Null
        $uid = Add-User $t "attach $run" -60
        Assert-AttachRefused (Invoke-Attach $db $run $session $uid) $db $run $session
    }

    It 'AC-I.2 step 4: the text "<Text>" has no attach token for the run → refused' -ForEach @(
        @{ Text = 'hello, please continue' }
        @{ Text = 'attach other-fixture-run' }
        @{ Text = '<run> please attach' }
    ) {
        $db = New-Store
        $project = New-Project
        $session = New-Uuid
        $run = New-StoreRun $db $project @($session)
        $t = New-Transcript $project $session
        Add-User $t 'start the fixture plan' 10 | Out-Null
        $uid = Add-User $t ($Text -replace '<run>', $run) 20
        Assert-AttachRefused (Invoke-Attach $db $run $session $uid) $db $run $session
    }

    It 'AC-I.2 step 5: a uuid is used once: the same entry for a second attach → refused' {
        $db = New-Store
        $project = New-Project
        $session = New-Uuid
        $runA = New-StoreRun $db $project @($session)
        $runB = New-StoreRun $db $project @($session)
        $t = New-Transcript $project $session
        Add-User $t 'start the fixture plan' 10 | Out-Null
        $uid = Add-User $t "attach $runA and attach $runB" 20
        $first = Invoke-Attach $db $runA $session $uid
        $first.Code | Should -Be 0 -Because "$($first.Out) $($first.Err)"
        Assert-AttachRefused (Invoke-Attach $db $runB $session $uid) $db $runB $session
        $again = Invoke-Attach $db $runA $session $uid
        $again.Code | Should -Be 3 -Because "$($again.Out) $($again.Err)"
        @(Get-Rows $db 'SELECT * FROM attaches WHERE user_message_uuid = ?' @($uid)).Count | Should -Be 1
    }

    It 'mx_29_ AC-I.2: an attach typed while busy is queued; its exact resend fails queued_origin; "attach RUN_ID again" passes' {
        $db = New-Store
        $project = New-Project
        $session = New-Uuid
        $run = New-StoreRun $db $project @($session)
        $t = New-Transcript $project $session
        $text = "attach $run"
        Add-User $t 'start the fixture plan' 10 | Out-Null
        Add-Assistant $t 'the plan runs' 20 | Out-Null
        $delivery = New-Uuid
        Add-QueueOp $t 'enqueue' 25 @{ content = $text }
        $queued = Add-QueuedCommand $t $text 26 $delivery
        Add-QueueOp $t 'remove' 27 @{ content = $text; reason = 'absorbed_mid_turn'; commandUuid = $queued; deliveryId = $delivery }
        Add-Assistant $t 'the turn ends' 30 | Out-Null
        $resend = Add-User $t $text 40
        $reworded = Add-User $t "$text again" 50
        # The queued attachment is not a typed entry (step 3).
        Assert-AttachRefused (Invoke-Attach $db $run $session $queued) $db $run $session
        # The exact resend equals the text of a queue chain (R§4.6.3 step 5).
        Assert-AttachRefused (Invoke-Attach $db $run $session $resend) $db $run $session @('queued_origin')
        $ok = Invoke-Attach $db $run $session $reworded
        $ok.Code | Should -Be 0 -Because "$($ok.Out) $($ok.Err)"
        (Get-Attached $db $run $session).history_state | Should -Be 'ok'
        @(Get-Attaches $db $run).Count | Should -Be 1
    }
}

Describe 'AC-I.3: Send-CreditsRunMessage.ps1 sends the ruling kind (report section 4.6.2)' {
    It 'AC-I.3: a ruling with the quote, the decision, the gate, the session and the uuid → one row with the identity hash' {
        $db = New-Store
        $project = New-Project
        $session = New-Uuid
        $run = New-StoreRun $db $project @($session) 'i3'
        $uid = New-Uuid
        $gate = "g-$run-1-1"
        $quote = "D-1: A — $run"
        $res = Invoke-Send $db @('-RunId', $run, '-Kind', 'ruling', '-Body', $quote, '-HumanQuote', $quote, '-Decision', 'D-1',
            '-GateId', $gate, '-OrchestratorSession', $session, '-UserMessageUuid', $uid)
        $res.Code | Should -Be 0 -Because "$($res.Out) $($res.Err)"
        $res.Json.result | Should -Be 'changed'
        $want = Get-RulingHash $run $quote 'D-1' $gate $session $uid
        $res.Json.payload_hash | Should -Be $want
        $rows = @(Get-Rows $db 'SELECT * FROM messages WHERE run_id = ?' @($run))
        $rows.Count | Should -Be 1
        $rows[0].kind | Should -Be 'ruling'
        [int]$rows[0].seq | Should -Be 1
        $rows[0].payload_hash | Should -Be $want
    }

    It 'AC-I.3: credits-msg.v1 accepts a full ruling message' {
        $doc = [ordered]@{
            schema = 'credits-msg.v1'; run_id = 'i3-fixture'; kind = 'ruling'; body = 'D-1: A'
            human_quote = 'D-1: A'; decision_id = 'D-1'; gate_id = 'g-i3-fixture-1-1'
            orchestrator_session_id = '00000000-0000-4000-8000-0000000000aa'; user_message_uuid = '00000000-0000-4000-8000-0000000000bb'
        }
        Test-Json -Json ($doc | ConvertTo-Json -Depth 4) -SchemaFile $script:MsgSchema -ErrorAction SilentlyContinue | Should -BeTrue
    }
}

Describe 'AC-I.6: Register-CreditsRun.ps1 needs the row-26 anchor lines for the switches (report section 7.7)' {
    It 'AC-I.6: <Name> with every anchor line in the project tree → registered' -ForEach @(
        @{ Name = 'ruling_enabled true'; Ruling = $true; GateWait = 0 }
        @{ Name = 'ruling_enabled true and gate_wait_max_min 30'; Ruling = $true; GateWait = 30 }
    ) {
        $db = New-Store
        $project = New-Project -Anchors
        $run = New-Id 'i6-ok'
        $fake = New-FakeScheduler
        $res = Invoke-Register $db (Save-Manifest (New-ManifestDoc $run $project $Ruling $GateWait)) (New-Config $Ruling $GateWait) $fake
        $res.Thrown | Should -BeNullOrEmpty
        $res.Code | Should -Be 0
        $res.Payload.state | Should -Be 'registered'
        (@(Get-Rows $db 'SELECT state FROM runs WHERE run_id = ?' @($run)) | Select-Object -First 1).state | Should -Be 'registered'
    }

    It 'AC-I.6 negative: <Name> → refused messaging_locked, no run, no task' -ForEach @(
        @{ Name = 'no anchor file in the tree'; Anchors = $false; Edit = $null }
        @{ Name = 'the GUARDRAILS verified-frame line removed'; Anchors = $true; Edit = { param($text, $rel) if ($rel -eq 'GUARDRAILS.md') { Remove-LineWith $text $script:AnchorVerifiedFrame } else { $text } } }
        @{ Name = 'the GUARDRAILS SIGN 3 (b) ruling line removed'; Anchors = $true; Edit = { param($text, $rel) if ($rel -eq 'GUARDRAILS.md') { Remove-LineWith $text $script:AnchorSignB } else { $text } } }
        @{ Name = 'the AGENTS.md HARD STOP gate-wait sentence removed'; Anchors = $true; Edit = { param($text, $rel) if ($rel -eq 'AGENTS.md') { Remove-LineWith $text $script:AnchorHardStop } else { $text } } }
        @{ Name = 'the human-decision-protocol bounded-wait line removed'; Anchors = $true; Edit = { param($text, $rel) if ($rel -like '*human-decision-protocol.md') { Remove-LineWith $text $script:AnchorHdp } else { $text } } }
        @{ Name = 'one character of the verified-frame line changed'; Anchors = $true; Edit = { param($text, $rel) if ($rel -eq 'GUARDRAILS.md') { $text.Replace('ruling (verified: <session>/<uuid>)', 'ruling (verified: <session>/<uid>)') } else { $text } } }
    ) {
        $db = New-Store
        $project = if ($Anchors) { New-Project -Anchors -Edit $Edit } else { New-Project }
        if ($Anchors) {
            # The edit took effect: the fixture tree differs from this tree.
            $changed = $false
            foreach ($rel in $script:AnchorFiles) {
                $a = [System.IO.File]::ReadAllText((Join-Path $script:Repo $rel), [System.Text.Encoding]::UTF8)
                $b = [System.IO.File]::ReadAllText((Join-Path $project $rel), [System.Text.Encoding]::UTF8)
                if ($a -ne $b) { $changed = $true }
            }
            $changed | Should -BeTrue
        }
        $run = New-Id 'i6-no'
        $fake = New-FakeScheduler
        $res = Invoke-Register $db (Save-Manifest (New-ManifestDoc $run $project $true 30)) (New-Config $true 30) $fake
        $res.Code | Should -Be 3
        $res.Payload.reason | Should -Be 'messaging_locked'
        @(Get-Rows $db 'SELECT * FROM runs WHERE run_id = ?' @($run)).Count | Should -Be 0
        $fake.State.Calls.Count | Should -Be 0
    }

    It 'AC-I.6: the defaults off with no anchor line in the tree → registered' {
        $db = New-Store
        $project = New-Project
        $run = New-Id 'i6-off'
        $fake = New-FakeScheduler
        $res = Invoke-Register $db (Save-Manifest (New-ManifestDoc $run $project $false 0)) (New-Config $false 0) $fake
        $res.Thrown | Should -BeNullOrEmpty
        $res.Code | Should -Be 0
        $res.Payload.state | Should -Be 'registered'
    }
}

Describe 'AC-I.7: the shipped credits config is the template default (report sections 4.1 and 6)' {
    It 'AC-I.7: .agent/credits/config.json holds exactly ruling_enabled false, gate_wait_max_min 0 and cache_ttl 5m' {
        Test-Path -LiteralPath $script:ShippedConfig -PathType Leaf | Should -BeTrue
        $cfg = [System.IO.File]::ReadAllText($script:ShippedConfig, [System.Text.Encoding]::UTF8) | ConvertFrom-Json -AsHashtable
        @($cfg.Keys | Sort-Object) | Should -Be @($script:TemplateDefault.Keys | Sort-Object)
        $cfg['ruling_enabled'] | Should -BeOfType [bool]
        $cfg['ruling_enabled'] | Should -Be $script:TemplateDefault.ruling_enabled
        [int]$cfg['gate_wait_max_min'] | Should -Be $script:TemplateDefault.gate_wait_max_min
        $cfg['cache_ttl'] | Should -Be $script:TemplateDefault.cache_ttl
    }
}

Describe 'AC-I.2: the monitor scans each attached transcript on each pass (report section 4.4 step 3)' {
    It 'AC-I.2: a pass reads the new bytes of an attached transcript and moves its mark' {
        $db = New-Store
        $project = New-Project
        $session = New-Uuid
        $run = New-StoreRun $db $project @($session) 'i2w'
        $t = New-Transcript $project $session
        Add-User $t 'start the fixture plan' 10 | Out-Null
        $uid = Add-User $t "attach $run" 20
        $attach = Invoke-Attach $db $run $session $uid
        $attach.Code | Should -Be 0 -Because "$($attach.Out) $($attach.Err)"
        Add-Assistant $t 'the plan runs' 30 | Out-Null
        Add-User $t 'carry on' 40 | Out-Null
        $pass = Invoke-Watch $db (New-Notifier)
        $pass.Thrown | Should -BeNullOrEmpty
        $pass.Code | Should -Be 0
        $mark = Get-Mark $db $session
        [int64]$mark.byte_length | Should -Be (Get-FileLength $t.Path)
        [int]$mark.line_count | Should -Be 4
    }

    It 'mx_28_ AC-I.2: lines removed from a scanned prefix → one transcript_discontinuity notice and history_state broken; the next pass sends no second notice' {
        $db = New-Store
        $project = New-Project
        $session = New-Uuid
        $run = New-StoreRun $db $project @($session) 'i2d'
        $t = New-Transcript $project $session
        Add-User $t 'start the fixture plan' 10 | Out-Null
        Add-Assistant $t 'the plan runs' 20 | Out-Null
        $uid = Add-User $t "attach $run" 30
        $attach = Invoke-Attach $db $run $session $uid
        $attach.Code | Should -Be 0 -Because "$($attach.Out) $($attach.Err)"

        $first = Invoke-Watch $db (New-Notifier)
        $first.Thrown | Should -BeNullOrEmpty
        @(Get-Rows $db "SELECT * FROM notices WHERE kind = 'transcript_discontinuity'").Count | Should -Be 0
        (Get-Attached $db $run $session).history_state | Should -Be 'ok'

        # Remove the assistant line from the scanned prefix.
        $t.Lines.RemoveAt(1)
        Save-Transcript $t

        $second = Invoke-Watch $db (New-Notifier)
        $sent = $script:LastSent
        $second.Thrown | Should -BeNullOrEmpty
        $notices = @(Get-Rows $db "SELECT * FROM notices WHERE kind = 'transcript_discontinuity'")
        $notices.Count | Should -Be 1
        $notices[0].notice_key | Should -Be "transcript_discontinuity:$session"
        $notices[0].run_id | Should -Be $run
        @(Get-SentFor $sent 'transcript_discontinuity').Count | Should -Be 1
        (Get-Attached $db $run $session).history_state | Should -Be 'broken'

        $third = Invoke-Watch $db (New-Notifier)
        $third.Thrown | Should -BeNullOrEmpty
        @(Get-SentFor $script:LastSent 'transcript_discontinuity').Count | Should -Be 0
        @(Get-Rows $db "SELECT * FROM notices WHERE kind = 'transcript_discontinuity'").Count | Should -Be 1
        (Get-Attached $db $run $session).history_state | Should -Be 'broken'
    }
}
