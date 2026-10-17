# S4 check and resume (Component F of docs/execution/plans/2026-10-15-scheduled-credits-runs).
# AC-F.1 Get-CreditsRun.ps1 is the read-only check (report section 4.5): with no id, one line per
# run; with an id, the full view of one run. It opens the store in mode=ro, so the store file and
# its transitions stay the same. -Export writes the JSON view to <store folder>/runs/<run-id>/.
# AC-F.2 a resume starts only through Start-CreditsRunTask.ps1 -Resume (report section 5.3), with
# the resume mode (session by default, D-4 A; or fresh) and the resume brief. The admission of the
# resumed segment closes an open stop-after-row as superseded_by_resume; every other open message
# is pending in the new delivery generation (report section 4.6.4 step 8, MX-19). The launcher sends
# the segment's brief, and continues the source session (session mode) or starts a new one (fresh).
#
# Every store is a temp file. No test starts a real task: Start-CreditsRunTask.ps1 gets the fake
# scheduler adapter, and the launcher runs a mock `claude` that writes its argv and its stdin.

BeforeAll {
    $script:Repo = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
    $script:Skill = Join-Path $script:Repo '.agent/skills/claude-credits'
    $script:GetRun = Join-Path $script:Skill 'Get-CreditsRun.ps1'
    $script:Caller = Join-Path $script:Skill 'Start-CreditsRunTask.ps1'
    $script:Launcher = Join-Path $script:Skill 'Start-CreditsRun.ps1'
    $script:Template = Join-Path $script:Skill 'templates/resume-brief.md'
    $script:StateTool = Join-Path $script:Repo 'tools/credits_state.py'
    $script:Root = "{{RECEIPTS_DIR}}/credits-check-tests/$([guid]::NewGuid().ToString('N'))"
    $script:Out = "$script:Root/dispatch"
    $script:Project = "$script:Root/project"
    New-Item -ItemType Directory -Force -Path $script:Out, $script:Project | Out-Null
    $script:EffectLog = "$script:Root/effects.jsonl"
    $script:SavedEffectLog = $env:CREDITS_TEST_EFFECT_LOG
    $env:CREDITS_TEST_EFFECT_LOG = $script:EffectLog
    $script:Db = "$script:Root/store/state.db"
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $script:Db) | Out-Null

    $script:KeyFile = "$script:Root/fake.key"
    Set-Content -LiteralPath $script:KeyFile -Value ('sk-' + 'ant-api03-' + ('A' * 40)) -Encoding utf8NoBOM
    $script:Brief = "$script:Root/brief.md"
    Set-Content -LiteralPath $script:Brief -Value 'credits check test base brief' -Encoding utf8NoBOM

    $venvPy = Join-Path $script:Repo '.venv/Scripts/python.exe'
    $script:Py = if (Test-Path -LiteralPath $venvPy) { $venvPy } else { (Get-Command python -ErrorAction Stop).Source }
    $script:BasePython = (& $script:Py -c 'import sys; print(sys._base_executable)' | Out-String).Trim()

    # The mock CLI: it writes its argv and its stdin (the brief) to files, and reports a result
    # with the session id it was given (--session-id for a new session, --resume for a resume).
    $mockPy = "$script:Root/mock_claude.py"
    Set-Content -LiteralPath $mockPy -Encoding utf8NoBOM -Value @'
import json
import os
import sys

args = sys.argv[1:]
if "--version" in args:
    print("2.1.296 (Claude Code)")
    sys.exit(0)
stdin_text = sys.stdin.read()
log = os.environ.get("MOCK_CALL_LOG")
if log:
    with open(log, "a", encoding="utf-8") as f:
        f.write(json.dumps({"argv": args, "stdin": stdin_text}) + "\n")
sid = None
if "--session-id" in args:
    sid = args[args.index("--session-id") + 1]
elif "--resume" in args:
    sid = args[args.index("--resume") + 1]
out = {"type": "result", "result": "MOCK_RESULT_OK", "is_error": False, "total_cost_usd": 0.0123}
if sid:
    out["session_id"] = sid
print(json.dumps(out))
sys.exit(0)
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

    function Get-UtcText([datetime]$Value) { $Value.ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ') }
    function New-Id([string]$Prefix) { "$Prefix-$([guid]::NewGuid().ToString('N').Substring(0, 10))" }
    function Read-Json([string]$Path) { [System.IO.File]::ReadAllText($Path, [System.Text.Encoding]::UTF8) | ConvertFrom-Json }

    # Start a process with no inherited CREDITS_*, MOCK_*, CLAUDECODE or CLAUDE_CODE_ENTRYPOINT
    # value, plus the test effect log and $Env (a $null value removes the name).
    function Start-Clean([string]$File, [string[]]$Arguments, [hashtable]$Env = @{}) {
        $psi = [System.Diagnostics.ProcessStartInfo]::new($File)
        foreach ($a in $Arguments) { $psi.ArgumentList.Add([string]$a) }
        $psi.UseShellExecute = $false
        $psi.RedirectStandardOutput = $true
        $psi.RedirectStandardError = $true
        foreach ($name in @($psi.Environment.Keys)) {
            if ($name -like 'CREDITS_*' -or $name -like 'MOCK_*' -or $name -in @('CLAUDECODE', 'CLAUDE_CODE_ENTRYPOINT')) { $null = $psi.Environment.Remove($name) }
        }
        $psi.Environment['CREDITS_TEST_EFFECT_LOG'] = $script:EffectLog
        foreach ($k in $Env.Keys) {
            if ($null -eq $Env[$k]) { $null = $psi.Environment.Remove($k) } else { $psi.Environment[$k] = [string]$Env[$k] }
        }
        $p = [System.Diagnostics.Process]::Start($psi)
        $so = $p.StandardOutput.ReadToEndAsync(); $se = $p.StandardError.ReadToEndAsync()
        if (-not $p.WaitForExit(240000)) { & taskkill.exe /PID $p.Id /T /F *> $null; throw "timed out: $File" }
        $p.WaitForExit()
        [pscustomobject]@{ Code = $p.ExitCode; Out = $so.Result; Err = $se.Result }
    }

    # One credits_state.py call with the test effect log. Returns Code, Out and Err.
    function Invoke-StoreRaw([string]$Py, [string]$Tool, [string]$EffectLog, [string]$Db, [string]$Verb, [string[]]$Arguments) {
        $psi = [System.Diagnostics.ProcessStartInfo]::new($Py)
        foreach ($a in @('-X', 'utf8', $Tool, '--db', $Db, $Verb) + $Arguments) { $psi.ArgumentList.Add([string]$a) }
        $psi.UseShellExecute = $false
        $psi.RedirectStandardOutput = $true
        $psi.RedirectStandardError = $true
        foreach ($name in @($psi.Environment.Keys)) { if ($name -like 'CREDITS_*') { $null = $psi.Environment.Remove($name) } }
        $psi.Environment['CREDITS_TEST_EFFECT_LOG'] = $EffectLog
        $p = [System.Diagnostics.Process]::Start($psi)
        $so = $p.StandardOutput.ReadToEndAsync(); $se = $p.StandardError.ReadToEndAsync()
        $p.WaitForExit()
        [pscustomobject]@{ Code = $p.ExitCode; Out = $so.Result; Err = $se.Result }
    }

    function Assert-Store([string]$Verb, [string[]]$Arguments = @()) {
        $res = Invoke-StoreRaw $script:Py $script:StateTool $script:EffectLog $script:Db $Verb $Arguments
        if ($res.Code -ne 0) { throw "store $Verb failed: exit=$($res.Code) out=$($res.Out) err=$($res.Err)" }
        $res.Out
    }

    function Get-Rows([string]$Sql, [string[]]$Params = @()) {
        $code = 'import json, sqlite3, sys; c = sqlite3.connect("file:" + sys.argv[1] + "?mode=ro", uri=True); c.row_factory = sqlite3.Row; print(json.dumps([dict(r) for r in c.execute(sys.argv[2], sys.argv[3:])]))'
        @((& $script:Py -X utf8 -c $code $script:Db $Sql @Params | Out-String) | ConvertFrom-Json)
    }

    function Get-Run([string]$RunId) { @(Get-Rows 'SELECT * FROM runs WHERE run_id = ?' @($RunId)) | Select-Object -First 1 }
    function Get-Requests([string]$RunId) { @(Get-Rows 'SELECT * FROM requests WHERE run_id = ? ORDER BY created_utc, rowid' @($RunId)) }
    function Get-Segments([string]$RunId) { @(Get-Rows 'SELECT * FROM segments WHERE run_id = ? ORDER BY created_utc, rowid' @($RunId)) }
    function Get-Messages([string]$RunId) { @(Get-Rows 'SELECT * FROM messages WHERE run_id = ? ORDER BY seq' @($RunId)) }

    # The number of transitions, then the store file hash. A mode=ro read can leave WAL side
    # files, so only the main file is hashed, after the count read.
    function Get-StoreFingerprint {
        $count = (@(Get-Rows 'SELECT COUNT(*) AS n FROM transitions') | Select-Object -First 1).n
        "transitions=$count;sha256=$((Get-FileHash -LiteralPath $script:Db -Algorithm SHA256).Hash)"
    }

    # A registered run whose manifest launches the mock CLI.
    function New-RegisteredRun([string]$RunId) {
        $doc = [ordered]@{
            schema = 'credits-run.v1'; run_id = $RunId; kind = 'exec'
            project_root = $script:Project; plan_folder = 'docs/execution/plans/2026-10-15-fixture/'
            brief = $script:Brief
            launch = [ordered]@{
                working_directory = $script:Project; claude_exe = $script:Mock; python_exe = $script:Py
                permission_mode = 'bypassPermissions'; effort = 'low'; segment_cap_usd = 20.0; timeout_sec = 3600
            }
            budget = [ordered]@{ run_cap_usd = 50.0 }
            messaging = [ordered]@{ orchestrator_sessions = @('00000000-0000-4000-8000-0000000000aa'); ruling_enabled = $false; gate_wait_max_min = 0 }
            depends_on = @(); lane = "tree:$script:Project/$RunId"
        }
        $manifest = "$script:Root/manifest-$RunId.json"
        Set-Content -LiteralPath $manifest -Value ($doc | ConvertTo-Json -Depth 6) -Encoding utf8NoBOM
        Assert-Store 'register' @('--run-id', $RunId, '--manifest', $manifest, '--cli-version', '2.1.296', '--kit-revision', 'kitrev-fixture') | Out-Null
        Assert-Store 'registered' @('--run-id', $RunId, '--task-hash', "taskhash-$RunId") | Out-Null
    }

    # A stopped run with one store-only segment that the launcher finalized (no dispatch folder).
    function New-StoppedRun([string]$RunId) {
        New-RegisteredRun $RunId
        Assert-Store 'request' @('--run-id', $RunId, '--started-by', 'human-command', '--request-id', "req0-$RunId") | Out-Null
        Assert-Store 'accept' @('--run-id', $RunId, '--launcher-pid', '4242', '--launcher-created', (Get-UtcText (Get-Date).AddMinutes(-1)),
            '--boot-id', 'boot-fixture-1', '--win-session', '1', '--attempt-id', "att0-$RunId", '--dispatch-id', "disp0-$RunId") | Out-Null
        Assert-Store 'admit' @('--attempt-id', "att0-$RunId", '--segment-id', "seg0-$RunId") | Out-Null
        Assert-Store 'launched' @('--segment-id', "seg0-$RunId", '--pid', '5151', '--created', (Get-UtcText (Get-Date)), '--boot-id', 'boot-fixture-1') | Out-Null
        Assert-Store 'complete_segment' @('--segment-id', "seg0-$RunId", '--finalized-by', 'launcher', '--class', 'exited', '--session-total-usd', '1.5', '--exit-code', '0') | Out-Null
        Assert-Store 'classify' @('--run-id', $RunId, '--to', 'stopped', '--class', 'exited') | Out-Null
    }

    function Get-LauncherArgs([string]$RunId) {
        @('-NoProfile', '-File', $script:Launcher, '-RunId', $RunId, '-StateDb', $script:Db, '-OutputDir', $script:Out, '-KeyFile', $script:KeyFile,
            '-RunGate', $script:GatePy, '-Receipt', $script:Receipt,
            '-LaunchWaitMs', '60000', '-TerminateWaitMs', '5000', '-CancelPollMs', '1000')
    }

    # A stopped run whose first segment ran through the launcher and the mock CLI, so its
    # dispatch has a status.json. Returns the call log path.
    function New-LaunchedStoppedRun([string]$RunId) {
        New-RegisteredRun $RunId
        Assert-Store 'request' @('--run-id', $RunId, '--started-by', 'human-command', '--request-id', "req0-$RunId") | Out-Null
        $calls = "$script:Root/$RunId.calls.jsonl"
        $child = Start-Clean 'pwsh' (Get-LauncherArgs $RunId) @{ MOCK_CALL_LOG = $calls }
        if ($child.Code -ne 0) { throw "first launch failed: $($child.Out) $($child.Err)" }
        $state = (Get-Run $RunId).state
        if ($state -eq 'finalizing') { Assert-Store 'classify' @('--run-id', $RunId, '--to', 'stopped', '--class', 'exited') | Out-Null }
        elseif ($state -ne 'stopped') { throw "the first launch left run $RunId in state $state, not finalizing or stopped" }
        $calls
    }

    function Get-Calls([string]$Path) {
        if (-not (Test-Path -LiteralPath $Path)) { return @() }
        @([System.IO.File]::ReadAllLines($Path) | Where-Object { $_.Trim() } | ForEach-Object { $_ | ConvertFrom-Json })
    }

    # A fake scheduler adapter: Start plays the launcher steps on the store (accept, admit, launched).
    function New-FakeScheduler {
        $state = @{
            Calls = [System.Collections.Generic.List[string]]::new(); Count = 0
            Py = $script:Py; Tool = $script:StateTool; EffectLog = $script:EffectLog; Db = $script:Db
            Store = ${function:Invoke-StoreRaw}; Utc = ${function:Get-UtcText}
        }
        @{
            State    = $state
            Register = { param($Definition) $state.Calls.Add("Register:$($Definition.TaskPath)$($Definition.TaskName)") }.GetNewClosure()
            Get      = { param($TaskPath, $TaskName) $state.Calls.Add("Get:$TaskPath$TaskName"); [pscustomobject]@{ TaskPath = $TaskPath; TaskName = $TaskName } }.GetNewClosure()
            Start    = {
                param($TaskPath, $TaskName)
                $state.Calls.Add("Start:$TaskPath$TaskName")
                $state.Count++
                $tag = "$TaskName-$($state.Count)-$([guid]::NewGuid().ToString('N').Substring(0, 6))"
                $created = & $state.Utc ((Get-Date).AddMinutes(-1))
                $res = & $state.Store $state.Py $state.Tool $state.EffectLog $state.Db 'accept' @('--run-id', $TaskName, '--launcher-pid', '4242',
                    '--launcher-created', $created, '--boot-id', 'boot-fixture-1', '--win-session', '1', '--attempt-id', "att-$tag", '--dispatch-id', "disp-$tag")
                if ($res.Code -ne 0) { return }
                $res = & $state.Store $state.Py $state.Tool $state.EffectLog $state.Db 'admit' @('--attempt-id', "att-$tag", '--segment-id', "seg-$tag")
                if ($res.Code -ne 0 -or ($res.Out | ConvertFrom-Json).outcome -ne 'admitted') { return }
                $null = & $state.Store $state.Py $state.Tool $state.EffectLog $state.Db 'launched' @('--segment-id', "seg-$tag", '--pid', '5151',
                    '--created', (& $state.Utc (Get-Date)), '--boot-id', 'boot-fixture-1')
            }.GetNewClosure()
        }
    }

    # Run Start-CreditsRunTask.ps1 in this process. Returns Code, Payload (the last JSON line) and
    # Thrown; a parameter error or a throw fails the test, not the container.
    function Invoke-Caller {
        param([string]$RunId, [hashtable]$Extra = @{})
        $params = @{
            RunId = $RunId; StartedBy = 'human-command'; StateDb = $script:Db; Scheduler = (New-FakeScheduler)
            AcceptTimeoutMs = 300; PollIntervalMs = 50; OutcomeTimeoutMs = 1500
        }
        foreach ($k in $Extra.Keys) { $params[$k] = $Extra[$k] }
        $global:LASTEXITCODE = 0
        $lines = @(); $thrown = $null
        try { $lines = @(& $script:Caller @params 2>$null) } catch { $thrown = $_.Exception.Message }
        $code = $global:LASTEXITCODE
        $payload = $null
        $last = @($lines | ForEach-Object { "$_" } | Where-Object { $_.TrimStart().StartsWith('{') }) | Select-Object -Last 1
        if ($last) { try { $payload = $last | ConvertFrom-Json -ErrorAction Stop } catch { $payload = $null } }
        [pscustomobject]@{ Code = $code; Payload = $payload; Thrown = $thrown }
    }

    # Get-CreditsRun.ps1 as a child process, on the test store and dispatch folder. -NonInteractive
    # makes a missing mandatory parameter an error, not a prompt.
    function Invoke-Check([string[]]$Arguments = @()) {
        Start-Clean 'pwsh' (@('-NoProfile', '-NonInteractive', '-File', $script:GetRun) + $Arguments + @('-StateDb', $script:Db, '-OutputDir', $script:Out))
    }

    function Get-ExportPath([string]$RunId) { Join-Path (Split-Path -Parent $script:Db) "runs/$RunId/view.json" }

    # The exported JSON view of one run, or $null.
    function Get-View([string]$RunId) {
        $res = Invoke-Check @($RunId, '-Export')
        $path = Get-ExportPath $RunId
        if ($res.Code -ne 0 -or -not (Test-Path -LiteralPath $path)) { return $null }
        Read-Json $path
    }

    function New-ResumeBrief([string]$Name) {
        $path = "$script:Root/$Name-resume.md"
        Set-Content -LiteralPath $path -Value "resume brief $Name" -Encoding utf8NoBOM
        $path
    }

    Assert-Store 'init' | Out-Null
}

AfterAll {
    $env:CREDITS_TEST_EFFECT_LOG = $script:SavedEffectLog
    if ($script:Root -and (Test-Path -LiteralPath $script:Root)) {
        Get-ChildItem -LiteralPath $script:Root -Recurse -File -ErrorAction SilentlyContinue | ForEach-Object { $_.IsReadOnly = $false }
        Remove-Item -LiteralPath $script:Root -Recurse -Force -ErrorAction SilentlyContinue
    }
}

Describe 'AC-F.1: the check is read-only (report section 4.5)' {
    It 'AC-F.1: with no id → one line per run, each with the run id and its state' {
        $a = New-Id 'f1-list-a'; New-StoppedRun $a
        $b = New-Id 'f1-list-b'; New-RegisteredRun $b
        $res = Invoke-Check
        $res.Code | Should -Be 0 -Because "$($res.Out) $($res.Err)"
        $lines = @("$($res.Out)" -split "`r?`n")
        $lineA = @($lines | Where-Object { $_ -match [regex]::Escape($a) })
        $lineB = @($lines | Where-Object { $_ -match [regex]::Escape($b) })
        $lineA.Count | Should -Be 1
        $lineB.Count | Should -Be 1
        $lineA[0] | Should -Match '\bstopped\b'
        $lineB[0] | Should -Match '\bregistered\b'
    }

    It 'AC-F.1: with an id (positional) → the view of that run, exit 0' {
        $run = New-Id 'f1-one'; New-StoppedRun $run
        $res = Invoke-Check @($run)
        $res.Code | Should -Be 0 -Because "$($res.Out) $($res.Err)"
        "$($res.Out)" | Should -Match ([regex]::Escape($run))
        "$($res.Out)" | Should -Match '\bstopped\b'
        "$($res.Out)" | Should -Match '\bexited\b'
        "$($res.Out)" | Should -Match ([regex]::Escape("seg0-$run"))
    }

    It 'AC-F.1: a check with no id, with an id and with -Export leaves the store file and its transitions unchanged' {
        $run = New-Id 'f1-hash'; New-StoppedRun $run
        Assert-Store 'send' @('--run-id', $run, '--kind', 'info', '--body', 'fixture note') | Out-Null
        $before = Get-StoreFingerprint
        (Invoke-Check).Code | Should -Be 0
        (Invoke-Check @($run)).Code | Should -Be 0
        (Invoke-Check @($run, '-Export')).Code | Should -Be 0
        Get-StoreFingerprint | Should -Be $before
    }

    It 'AC-F.1: the check works on a store file marked read-only (mode=ro)' {
        $run = New-Id 'f1-ro'; New-StoppedRun $run
        $file = Get-Item -LiteralPath $script:Db
        $file.IsReadOnly = $true
        try {
            $res = Invoke-Check @($run)
        } finally {
            $file.IsReadOnly = $false
        }
        $res.Code | Should -Be 0 -Because "$($res.Out) $($res.Err)"
        "$($res.Out)" | Should -Match ([regex]::Escape($run))
    }

    It 'AC-F.1: -Export writes the JSON view to runs/(run id)/view.json in the store folder' {
        $run = New-Id 'f1-export'; New-StoppedRun $run
        $res = Invoke-Check @($run, '-Export')
        $res.Code | Should -Be 0 -Because "$($res.Out) $($res.Err)"
        $path = Get-ExportPath $run
        Test-Path -LiteralPath $path | Should -BeTrue
        $view = Read-Json $path
        $view.run_id | Should -Be $run
        $view.state | Should -Be 'stopped'
        $view.class | Should -Be 'exited'
        @($view.segments).Count | Should -Be 1
        @($view.segments)[0].segment_id | Should -Be "seg0-$run"
        @($view.requests).Count | Should -Be 1
        @($view.attempts).Count | Should -Be 1
        $view.PSObject.Properties.Name | Should -Contain 'messages'
        $view.PSObject.Properties.Name | Should -Contain 'outbox'
        $view.PSObject.Properties.Name | Should -Contain 'exposures'
        $view.PSObject.Properties.Name | Should -Contain 'cost'
        $view.PSObject.Properties.Name | Should -Contain 'resume'
    }

    It 'AC-F.1: the view shows an open stop-after-row before the resume, so the human sees it' {
        $run = New-Id 'f1-sar'; New-StoppedRun $run
        $sent = Assert-Store 'send' @('--run-id', $run, '--kind', 'stop-after-row', '--body', 'stop after row 3') | ConvertFrom-Json
        $res = Invoke-Check @($run)
        $res.Code | Should -Be 0
        "$($res.Out)" | Should -Match ([regex]::Escape($sent.msg_id))
        "$($res.Out)" | Should -Match 'stop-after-row'
        $view = Get-View $run
        $view | Should -Not -BeNullOrEmpty
        $msg = @($view.messages | Where-Object { $_.msg_id -eq $sent.msg_id })
        $msg.Count | Should -Be 1
        $msg[0].state | Should -Be 'open'
        $msg[0].kind | Should -Be 'stop-after-row'
    }

    It 'AC-F.1: resume readiness → a recovery status is needed while the source dispatch has no status.json' {
        $run = New-Id 'f1-ready'; New-StoppedRun $run
        $view = Get-View $run
        $view | Should -Not -BeNullOrEmpty
        $view.resume.source_dispatch_id | Should -Be "disp0-$run"
        $view.resume.recovery_status_needed | Should -BeTrue
        $view.resume.ruling_pending | Should -BeFalse
    }

    It 'AC-F.1: resume readiness → a source dispatch with a status.json needs no recovery and allows the session resume' {
        $run = New-Id 'f1-ready2'
        New-LaunchedStoppedRun $run | Out-Null
        $seg = Get-Segments $run | Select-Object -First 1
        Test-Path -LiteralPath (Join-Path $script:Out "$($seg.dispatch_id)/status.json") | Should -BeTrue
        $view = Get-View $run
        $view | Should -Not -BeNullOrEmpty
        $view.resume.source_dispatch_id | Should -Be $seg.dispatch_id
        $view.resume.recovery_status_needed | Should -BeFalse
        $view.resume.session_resume_possible | Should -BeTrue
    }

    It 'AC-F.1 negative: an unknown run id → exit not 0, and the store stays the same' {
        $before = Get-StoreFingerprint
        $res = Invoke-Check @('f1-no-such-run')
        $res.Code | Should -Not -Be 0
        "$($res.Out) $($res.Err)" | Should -Match 'f1-no-such-run'
        Get-StoreFingerprint | Should -Be $before
    }

    It 'AC-F.1 negative: -Settle still needs -Source and -AmountUsd; a view with no id never asks for them' {
        $res = Invoke-Check
        $res.Code | Should -Be 0 -Because "$($res.Out) $($res.Err)"
        $settle = Invoke-Check @('-Settle', 'seg-none')
        $settle.Code | Should -Not -Be 0
    }
}

Describe 'AC-F.2: the resume through Start-CreditsRunTask.ps1 -Resume (report section 5.3)' {
    It 'AC-F.2: -Resume with no -ResumeMode → session mode (D-4 A): the segment keeps the source session and gets the brief' {
        $run = New-Id 'f2-session'; New-StoppedRun $run
        $first = Get-Segments $run | Select-Object -First 1
        $brief = New-ResumeBrief $run
        $res = Invoke-Caller -RunId $run -Extra @{ Resume = $true; Brief = $brief }
        $res.Thrown | Should -BeNullOrEmpty
        $res.Code | Should -Be 0 -Because "$($res.Payload | ConvertTo-Json -Compress)"
        $request = Get-Requests $run | Select-Object -Last 1
        $request.resume | Should -Be 1
        $request.resume_mode | Should -Be 'session'
        $request.brief | Should -Be $brief
        $segments = Get-Segments $run
        $segments.Count | Should -Be 2
        $segments[1].resume | Should -Be 'session'
        $segments[1].brief | Should -Be $brief
        $segments[1].expected_session_id | Should -Be $first.expected_session_id
    }

    It 'AC-F.2: -ResumeMode fresh → a new session id on the new segment' {
        $run = New-Id 'f2-fresh'; New-StoppedRun $run
        $first = Get-Segments $run | Select-Object -First 1
        $brief = New-ResumeBrief $run
        $res = Invoke-Caller -RunId $run -Extra @{ Resume = $true; ResumeMode = 'fresh'; Brief = $brief }
        $res.Thrown | Should -BeNullOrEmpty
        $res.Code | Should -Be 0
        (Get-Requests $run | Select-Object -Last 1).resume_mode | Should -Be 'fresh'
        $segments = Get-Segments $run
        $segments.Count | Should -Be 2
        $segments[1].resume | Should -Be 'fresh'
        $segments[1].brief | Should -Be $brief
        $segments[1].expected_session_id | Should -Not -Be $first.expected_session_id
        $segments[1].expected_session_id | Should -Match '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
    }

    It 'mx_19_ AC-F.2: a session resume with an open stop-after-row → closed superseded_by_resume; the other open message is pending in the new generation' {
        $run = New-Id 'mx19-session'; New-StoppedRun $run
        $stop = Assert-Store 'send' @('--run-id', $run, '--kind', 'stop-after-row', '--body', 'stop after row 3') | ConvertFrom-Json
        $info = Assert-Store 'send' @('--run-id', $run, '--kind', 'info', '--body', 'the base moved') | ConvertFrom-Json
        $res = Invoke-Caller -RunId $run -Extra @{ Resume = $true; Brief = (New-ResumeBrief $run) }
        $res.Thrown | Should -BeNullOrEmpty
        $res.Code | Should -Be 0
        $messages = Get-Messages $run
        $closed = @($messages | Where-Object { $_.msg_id -eq $stop.msg_id })[0]
        $closed.state | Should -Be 'closed'
        $closed.closed_reason | Should -Be 'superseded_by_resume'
        $open = @($messages | Where-Object { $_.msg_id -eq $info.msg_id })[0]
        $open.state | Should -Be 'open'
        $newSeg = (Get-Segments $run)[1].segment_id
        @(Get-Rows 'SELECT * FROM deliveries WHERE msg_id = ? AND segment_id = ?' @($info.msg_id, $newSeg)).Count | Should -Be 0
        $view = Get-View $run
        $view | Should -Not -BeNullOrEmpty
        $view.generation | Should -Be 2
        @($view.messages | Where-Object { $_.msg_id -eq $info.msg_id })[0].pending | Should -BeTrue
        @($view.messages | Where-Object { $_.msg_id -eq $stop.msg_id })[0].closed_reason | Should -Be 'superseded_by_resume'
        "$((Invoke-Check @($run)).Out)" | Should -Match 'superseded_by_resume'
    }

    It 'mx_19_ AC-F.2: a fresh resume with an open stop-after-row → closed superseded_by_resume; the other open message is pending in the new generation' {
        $run = New-Id 'mx19-fresh'; New-StoppedRun $run
        $stop = Assert-Store 'send' @('--run-id', $run, '--kind', 'stop-after-row', '--body', 'stop after row 3') | ConvertFrom-Json
        $query = Assert-Store 'send' @('--run-id', $run, '--kind', 'query', '--body', 'which row is open?') | ConvertFrom-Json
        $res = Invoke-Caller -RunId $run -Extra @{ Resume = $true; ResumeMode = 'fresh'; Brief = (New-ResumeBrief $run) }
        $res.Thrown | Should -BeNullOrEmpty
        $res.Code | Should -Be 0
        $messages = Get-Messages $run
        @($messages | Where-Object { $_.msg_id -eq $stop.msg_id })[0].closed_reason | Should -Be 'superseded_by_resume'
        @($messages | Where-Object { $_.msg_id -eq $query.msg_id })[0].state | Should -Be 'open'
        $view = Get-View $run
        $view | Should -Not -BeNullOrEmpty
        @($view.messages | Where-Object { $_.msg_id -eq $query.msg_id })[0].pending | Should -BeTrue
    }

    It 'AC-F.2: the launcher sends the resume brief and continues the source session (session mode)' {
        $run = New-Id 'f2-launch-session'
        $calls = New-LaunchedStoppedRun $run
        $first = Get-Segments $run | Select-Object -First 1
        $brief = New-ResumeBrief $run
        Assert-Store 'request' @('--run-id', $run, '--started-by', 'human-command', '--resume', '--resume-mode', 'session', '--brief', $brief, '--request-id', "req1-$run") | Out-Null
        $child = Start-Clean 'pwsh' (Get-LauncherArgs $run) @{ MOCK_CALL_LOG = $calls }
        $child.Code | Should -Be 0 -Because "$($child.Out) $($child.Err)"
        $call = @(Get-Calls $calls) | Select-Object -Last 1
        @(Get-Calls $calls).Count | Should -Be 2
        $argv = @($call.argv)
        $argv | Should -Contain '--resume'
        $argv[[array]::IndexOf($argv, '--resume') + 1] | Should -Be $first.expected_session_id
        $call.stdin | Should -Match 'resume brief'
    }

    It 'AC-F.2: the launcher starts a new session for a fresh resume, with the resume brief and no --resume' {
        $run = New-Id 'f2-launch-fresh'
        $calls = New-LaunchedStoppedRun $run
        $first = Get-Segments $run | Select-Object -First 1
        $brief = New-ResumeBrief $run
        Assert-Store 'request' @('--run-id', $run, '--started-by', 'human-command', '--resume', '--resume-mode', 'fresh', '--brief', $brief, '--request-id', "req1-$run") | Out-Null
        $child = Start-Clean 'pwsh' (Get-LauncherArgs $run) @{ MOCK_CALL_LOG = $calls }
        $child.Code | Should -Be 0 -Because "$($child.Out) $($child.Err)"
        @(Get-Calls $calls).Count | Should -Be 2
        $call = @(Get-Calls $calls) | Select-Object -Last 1
        $argv = @($call.argv)
        $argv | Should -Not -Contain '--resume'
        $argv | Should -Contain '--session-id'
        $sid = $argv[[array]::IndexOf($argv, '--session-id') + 1]
        $sid | Should -Not -Be $first.expected_session_id
        $sid | Should -Be (Get-Segments $run)[1].expected_session_id
        $call.stdin | Should -Match 'resume brief'
    }

    It 'AC-F.2: the resume-brief template has the sections of report section 5.3 and the foreground rule' {
        Test-Path -LiteralPath $script:Template | Should -BeTrue
        $text = [System.IO.File]::ReadAllText($script:Template, [System.Text.Encoding]::UTF8)
        foreach ($heading in @('Base briefs', 'What happened', 'The ruling', 'Messages', 'What to do', 'The foreground rule', 'Blocked rows')) {
            $text | Should -Match ('(?m)^#{1,4}\s+' + [regex]::Escape($heading)) -Because "the template needs the section $heading"
        }
        $text | Should -Match ([regex]::Escape('Never end a turn to wait. That ends the run.'))
        $text | Should -Match 'superseded_by_resume'
        $text | Should -Match ([regex]::Escape('-pre-<class>'))
        $text | Should -Match 'Never reset git'
    }

    It 'AC-F.2 negative: a resume of a run that is not stopped → refused, exit 3, no request' {
        $run = New-Id 'f2-notstopped'; New-RegisteredRun $run
        $res = Invoke-Caller -RunId $run -Extra @{ Resume = $true; Brief = (New-ResumeBrief $run) }
        $res.Code | Should -Be 3
        $res.Payload.outcome | Should -Be 'refused'
        (Get-Requests $run).Count | Should -Be 0
        (Get-Run $run).state | Should -Be 'registered'
    }

    It 'AC-F.2 negative: -ResumeMode or -Brief without -Resume → refused, exit 3, no request' {
        $run = New-Id 'f2-noresume'; New-StoppedRun $run
        $count = (Get-Requests $run).Count
        $mode = Invoke-Caller -RunId $run -Extra @{ ResumeMode = 'fresh' }
        $mode.Thrown | Should -BeNullOrEmpty
        $mode.Code | Should -Be 3
        $brief = Invoke-Caller -RunId $run -Extra @{ Brief = (New-ResumeBrief $run) }
        $brief.Thrown | Should -BeNullOrEmpty
        $brief.Code | Should -Be 3
        (Get-Requests $run).Count | Should -Be $count
        (Get-Run $run).state | Should -Be 'stopped'
    }

    It 'AC-F.2 negative: a -Brief file that does not exist → refused, exit 3, no request' {
        $run = New-Id 'f2-nobrief'; New-StoppedRun $run
        $count = (Get-Requests $run).Count
        $res = Invoke-Caller -RunId $run -Extra @{ Resume = $true; Brief = "$script:Root/no-such-brief.md" }
        $res.Thrown | Should -BeNullOrEmpty
        $res.Code | Should -Be 3
        (Get-Requests $run).Count | Should -Be $count
        (Get-Run $run).state | Should -Be 'stopped'
    }

    It 'AC-F.2 negative: -ResumeMode accepts only session and fresh' {
        $run = New-Id 'f2-badmode'; New-StoppedRun $run
        $count = (Get-Requests $run).Count
        $res = Invoke-Caller -RunId $run -Extra @{ Resume = $true; ResumeMode = 'attach' }
        $res.Thrown | Should -Not -BeNullOrEmpty
        $res.Thrown | Should -Match 'ResumeMode'
        $res.Thrown | Should -Match 'does not belong to the set'
        (Get-Requests $run).Count | Should -Be $count
    }

    It 'AC-F.2 negative: the check has no resume parameter; a resume starts only through Start-CreditsRunTask.ps1' {
        $params = (Get-Command -Name $script:GetRun).Parameters.Keys
        $params | Should -Not -Contain 'Resume'
        $params | Should -Not -Contain 'ResumeMode'
        (Get-Command -Name $script:Caller).Parameters.Keys | Should -Contain 'ResumeMode'
    }
}
