# S2 launcher (Component D of docs/execution/plans/2026-10-15-scheduled-credits-runs).
# AC-D.3 Start-CreditsRun.ps1 (the task action) does accept → admit → job → Invoke-ClaudeCredits
# → Complete-CreditsSegment (report section 4.3). It sets CREDITS_ENV, BASH_DEFAULT_TIMEOUT_MS and
# BASH_MAX_TIMEOUT_MS = 600000 and DISABLE_AUTOUPDATER=1, and removes ELECTRON_RUN_AS_NODE,
# DISABLE_PROMPT_CACHING and CLAUDE_CODE_CHILD_SESSION. With no pending request it starts nothing.
# A request REQUEST_ACCEPT_TIMEOUT_S (120 s) old is not_started stale_at_launcher, with one
# credits_limit_tripped WARN record (MX-31). A refused resume stops the run (MX-5).
#
# Every launch goes to a mock `claude` that writes its argv and its environment (the names the
# launcher sets or removes, never a key) to a file. The key file holds a fake key; the store, the
# M-1 receipt and the gate are temp files. The launcher clock is the store clock (-NowUtc), so a
# request age is seeded with no sleep. Each child gets its own environment block without
# CLAUDECODE and CLAUDE_CODE_ENTRYPOINT; this process's environment is never changed.
#
# AC-21 (f) of docs/execution/plans/2026-10-20-review-limits-parameters: an uncapped admission
# (the project's .agent/review-limits.json has token_budgets "off" and the manifest no cap)
# passes -MaxBudgetUsd 0, so the CLI argv has no --max-budget-usd.

BeforeAll {
    $script:Repo = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
    $script:Skill = Join-Path $script:Repo '.agent/skills/claude-credits'
    $script:Launcher = Join-Path $script:Skill 'Start-CreditsRun.ps1'
    $script:StateTool = Join-Path $script:Repo 'tools/credits_state.py'
    $script:Root = "{{RECEIPTS_DIR}}/credits-launcher-tests/$([guid]::NewGuid().ToString('N'))"
    $script:Out = "$script:Root/dispatch"
    $script:Project = "$script:Root/project"
    New-Item -ItemType Directory -Force -Path $script:Out, $script:Project | Out-Null
    $script:EffectLog = "$script:Root/effects.jsonl"
    $script:Db = "$script:Root/store/state.db"
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $script:Db) | Out-Null

    $script:KeyFile = "$script:Root/fake.key"
    Set-Content -LiteralPath $script:KeyFile -Value ('sk-' + 'ant-api03-' + ('A' * 40)) -Encoding utf8NoBOM
    $script:Brief = "$script:Root/brief.md"
    Set-Content -LiteralPath $script:Brief -Value 'credits launcher test brief' -Encoding utf8NoBOM

    $venvPy = Join-Path $script:Repo '.venv/Scripts/python.exe'
    $script:Py = if (Test-Path -LiteralPath $venvPy) { $venvPy } else { (Get-Command python -ErrorAction Stop).Source }
    $script:BasePython = (& $script:Py -c 'import sys; print(sys._base_executable)' | Out-String).Trim()
    $mockPy = "$script:Root/mock_claude.py"
    Set-Content -LiteralPath $mockPy -Encoding utf8NoBOM -Value @'
import json
import os
import sys
import time

DUMPED = {
    "BASH_DEFAULT_TIMEOUT_MS",
    "BASH_MAX_TIMEOUT_MS",
    "DISABLE_AUTOUPDATER",
    "ELECTRON_RUN_AS_NODE",
    "DISABLE_PROMPT_CACHING",
    "CLAUDE_CODE_CHILD_SESSION",
}

args = sys.argv[1:]
if "--version" in args:
    print("2.1.296 (Claude Code)")
    sys.exit(0)
stdin_text = sys.stdin.read()
log = os.environ.get("MOCK_CALL_LOG")
if log:
    with open(log, "a", encoding="utf-8") as f:
        f.write(json.dumps(args) + "\n")
argv_file = os.environ.get("MOCK_ARGV_FILE")
if argv_file:
    env = {
        k.upper(): v
        for k, v in os.environ.items()
        if k.upper().startswith("CREDITS_") or k.upper() in DUMPED
    }
    with open(argv_file, "w", encoding="utf-8") as f:
        json.dump({"argv": args, "pid": os.getpid(), "ppid": os.getppid(), "env": env}, f)
hang = os.environ.get("MOCK_HANG_SECONDS")
if hang:
    time.sleep(float(hang))
sid = None
if "--session-id" in args:
    sid = args[args.index("--session-id") + 1]
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

    $script:Strip = @('CLAUDECODE', 'CLAUDE_CODE_ENTRYPOINT')

    # Start pwsh -File <Script> <Arguments> with this process's environment minus CLAUDECODE,
    # CLAUDE_CODE_ENTRYPOINT, CREDITS_* and MOCK_*, plus the test effect log and $Env (a $null
    # value removes the name). -NoWait returns the running process.
    function Start-Child {
        param([string]$Script, [string[]]$Arguments, [hashtable]$Env = @{}, [switch]$NoWait)
        $psi = [System.Diagnostics.ProcessStartInfo]::new('pwsh')
        foreach ($a in @('-NoProfile', '-File', $Script) + $Arguments) { $psi.ArgumentList.Add([string]$a) }
        $psi.UseShellExecute = $false
        $psi.RedirectStandardOutput = $true
        $psi.RedirectStandardError = $true
        foreach ($name in @($psi.Environment.Keys)) {
            if ($name -in $script:Strip -or $name -like 'CREDITS_*' -or $name -like 'MOCK_*') { $null = $psi.Environment.Remove($name) }
        }
        $psi.Environment['CREDITS_TEST_EFFECT_LOG'] = $script:EffectLog
        foreach ($k in $Env.Keys) {
            if ($null -eq $Env[$k]) { $null = $psi.Environment.Remove($k) } else { $psi.Environment[$k] = [string]$Env[$k] }
        }
        $p = [System.Diagnostics.Process]::Start($psi)
        $so = $p.StandardOutput.ReadToEndAsync(); $se = $p.StandardError.ReadToEndAsync()
        if ($NoWait) { return [pscustomobject]@{ Process = $p; StdOut = $so; StdErr = $se } }
        if (-not $p.WaitForExit(240000)) { & taskkill.exe /PID $p.Id /T /F *> $null; throw "child timed out: $Script" }
        $p.WaitForExit()
        [pscustomobject]@{ Code = $p.ExitCode; Out = $so.Result; Err = $se.Result }
    }

    function New-Id([string]$Prefix) { "$Prefix-$([guid]::NewGuid().ToString('N').Substring(0, 10))" }
    function Get-UtcText([datetime]$Value) { $Value.ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ') }
    function Read-Json([string]$Path) { [System.IO.File]::ReadAllText($Path, [System.Text.Encoding]::UTF8) | ConvertFrom-Json }

    # One credits_state.py call (setup only) with the test effect log and an optional store clock.
    function Assert-Store([string]$Verb, [string[]]$Arguments = @(), [string]$NowUtc = '') {
        $psi = [System.Diagnostics.ProcessStartInfo]::new($script:Py)
        $all = @('-X', 'utf8', $script:StateTool, '--db', $script:Db)
        if ($NowUtc) { $all += @('--now-utc', $NowUtc) }
        foreach ($a in $all + @($Verb) + $Arguments) { $psi.ArgumentList.Add([string]$a) }
        $psi.UseShellExecute = $false
        $psi.RedirectStandardOutput = $true
        $psi.RedirectStandardError = $true
        foreach ($name in @($psi.Environment.Keys)) { if ($name -like 'CREDITS_*') { $null = $psi.Environment.Remove($name) } }
        $psi.Environment['CREDITS_TEST_EFFECT_LOG'] = $script:EffectLog
        $p = [System.Diagnostics.Process]::Start($psi)
        $so = $p.StandardOutput.ReadToEndAsync(); $se = $p.StandardError.ReadToEndAsync()
        $p.WaitForExit()
        if ($p.ExitCode -ne 0) { throw "store $Verb failed: exit=$($p.ExitCode) out=$($so.Result) err=$($se.Result)" }
        $so.Result
    }

    function Get-Rows([string]$Sql, [string[]]$Params = @()) {
        $code = 'import json, sqlite3, sys; c = sqlite3.connect("file:" + sys.argv[1] + "?mode=ro", uri=True); c.row_factory = sqlite3.Row; print(json.dumps([dict(r) for r in c.execute(sys.argv[2], sys.argv[3:])]))'
        @((& $script:Py -X utf8 -c $code $script:Db $Sql @Params | Out-String) | ConvertFrom-Json)
    }

    function Get-Run([string]$RunId) { @(Get-Rows 'SELECT * FROM runs WHERE run_id = ?' @($RunId)) | Select-Object -First 1 }
    function Get-Segments([string]$RunId) { @(Get-Rows 'SELECT * FROM segments WHERE run_id = ? ORDER BY created_utc, rowid' @($RunId)) }

    function Test-SamePath([string]$A, [string]$B) {
        [System.IO.Path]::GetFullPath($A).TrimEnd('\', '/') -eq [System.IO.Path]::GetFullPath($B).TrimEnd('\', '/')
    }

    # A registered run whose manifest launches the mock CLI with the real Python. -Uncapped
    # roots it at a project whose review-limits file says token_budgets "off" and drops both caps.
    function New-RegisteredRun([string]$RunId, [string]$Lane = '', [switch]$Uncapped) {
        if (-not $Lane) { $Lane = "tree:$script:Project/$RunId" }
        $project = $script:Project
        if ($Uncapped) {
            $project = "$script:Root/project-uncapped"
            New-Item -ItemType Directory -Force -Path "$project/.agent" | Out-Null
            $limits = Read-Json (Join-Path $script:Repo '.agent/review-limits.json')
            $limits.token_budgets = 'off'
            Set-Content -LiteralPath "$project/.agent/review-limits.json" -Value ($limits | ConvertTo-Json -Depth 4) -Encoding utf8NoBOM
        }
        $doc = [ordered]@{
            schema = 'credits-run.v1'; run_id = $RunId; kind = 'exec'
            project_root = $project; plan_folder = 'docs/execution/plans/2026-10-15-fixture/'
            brief = $script:Brief
            launch = [ordered]@{
                working_directory = $project; claude_exe = $script:Mock; python_exe = $script:Py
                permission_mode = 'bypassPermissions'; effort = 'low'; segment_cap_usd = 20.0; timeout_sec = 3600
            }
            budget = [ordered]@{ run_cap_usd = 50.0 }
            messaging = [ordered]@{ orchestrator_sessions = @('00000000-0000-4000-8000-0000000000aa'); ruling_enabled = $false; gate_wait_max_min = 0 }
            depends_on = @(); lane = $Lane
        }
        if ($Uncapped) {
            $doc.launch.Remove('segment_cap_usd')
            $doc.budget.Remove('run_cap_usd')
        }
        $manifest = "$script:Root/manifest-$RunId.json"
        Set-Content -LiteralPath $manifest -Value ($doc | ConvertTo-Json -Depth 6) -Encoding utf8NoBOM
        Assert-Store 'register' @('--run-id', $RunId, '--manifest', $manifest, '--cli-version', '2.1.296', '--kit-revision', 'kitrev-fixture') | Out-Null
        Assert-Store 'registered' @('--run-id', $RunId, '--task-hash', "taskhash-$RunId") | Out-Null
    }

    # A stopped run: one store-only segment that the launcher finalized, classified stopped.
    function New-StoppedRun([string]$RunId, [string]$Lane) {
        New-RegisteredRun $RunId $Lane
        Assert-Store 'request' @('--run-id', $RunId, '--started-by', 'human-command') | Out-Null
        Assert-Store 'accept' @('--run-id', $RunId, '--launcher-pid', '4242', '--launcher-created', (Get-UtcText (Get-Date).AddMinutes(-1)),
            '--boot-id', 'boot-fixture-1', '--win-session', '1', '--attempt-id', "att0-$RunId") | Out-Null
        Assert-Store 'admit' @('--attempt-id', "att0-$RunId", '--segment-id', "seg0-$RunId") | Out-Null
        Assert-Store 'launched' @('--segment-id', "seg0-$RunId", '--pid', '5151', '--created', (Get-UtcText (Get-Date)), '--boot-id', 'boot-fixture-1') | Out-Null
        Assert-Store 'complete_segment' @('--segment-id', "seg0-$RunId", '--finalized-by', 'launcher', '--class', 'exited', '--session-total-usd', '1.5', '--exit-code', '0') | Out-Null
        Assert-Store 'classify' @('--run-id', $RunId, '--to', 'stopped', '--class', 'exited') | Out-Null
    }

    function Get-LauncherArgs([string]$RunId, [string[]]$Extra = @()) {
        @('-RunId', $RunId, '-StateDb', $script:Db, '-OutputDir', $script:Out, '-KeyFile', $script:KeyFile,
            '-RunGate', $script:GatePy, '-Receipt', $script:Receipt,
            '-LaunchWaitMs', '60000', '-TerminateWaitMs', '5000', '-CancelPollMs', '1000') + $Extra
    }

    # The launcher's last JSON line on stdout, or $null.
    function Get-Payload($Child) {
        $last = @("$($Child.Out)" -split "`r?`n" | Where-Object { $_.TrimStart().StartsWith('{') }) | Select-Object -Last 1
        if (-not $last) { return $null }
        try { $last | ConvertFrom-Json -ErrorAction Stop } catch { $null }
    }

    function Get-LauncherLog([string]$RunId) {
        $path = Join-Path (Split-Path -Parent $script:Db) "logs/launcher-$RunId.jsonl"
        if (-not (Test-Path -LiteralPath $path)) { return @() }
        @([System.IO.File]::ReadAllLines($path) | Where-Object { $_.Trim() } | ForEach-Object { $_ | ConvertFrom-Json })
    }

    Assert-Store 'init' | Out-Null
}

AfterAll {
    if ($script:Root -and (Test-Path -LiteralPath $script:Root)) { Remove-Item -LiteralPath $script:Root -Recurse -Force -ErrorAction SilentlyContinue }
}

Describe 'AC-D.3: a pending request → accept, admit, job, wrapper, complete (R§4.3)' {
    BeforeAll {
        $script:RunA = New-Id 'd3-run'
        New-RegisteredRun $script:RunA
        Assert-Store 'request' @('--run-id', $script:RunA, '--started-by', 'human-command', '--request-id', "req-$script:RunA") | Out-Null
        $script:ArgvA = "$script:Root/$script:RunA.argv.json"
        $script:CallsA = "$script:Root/$script:RunA.calls.jsonl"
        $script:ChildA = Start-Child $script:Launcher (Get-LauncherArgs $script:RunA) -Env @{
            MOCK_ARGV_FILE = $script:ArgvA; MOCK_CALL_LOG = $script:CallsA
            ELECTRON_RUN_AS_NODE = '1'; DISABLE_PROMPT_CACHING = '1'; CLAUDE_CODE_CHILD_SESSION = '1'
            BASH_DEFAULT_TIMEOUT_MS = '5000'; DISABLE_AUTOUPDATER = '0'
        }
        $script:DumpA = if (Test-Path -LiteralPath $script:ArgvA) { Read-Json $script:ArgvA } else { $null }
        $script:AttemptA = @(Get-Rows 'SELECT * FROM attempts WHERE run_id = ?' @($script:RunA)) | Select-Object -First 1
        $script:SegA = Get-Segments $script:RunA | Select-Object -First 1
    }

    It 'AC-D.3: the launcher exits 0 and the mock CLI ran once' {
        $script:ChildA.Code | Should -Be 0
        Test-Path -LiteralPath $script:CallsA | Should -BeTrue
        @([System.IO.File]::ReadAllLines($script:CallsA) | Where-Object { $_.Trim() }).Count | Should -Be 1
    }

    It 'AC-D.3: the request and the attempt moved to launched; one job segment' {
        (@(Get-Rows 'SELECT state FROM requests WHERE request_id = ?' @("req-$script:RunA")) | Select-Object -First 1).state | Should -Be 'launched'
        $script:AttemptA.state | Should -Be 'launched'
        @(Get-Segments $script:RunA).Count | Should -Be 1
        $script:SegA.supervision | Should -Be 'job'
        $script:SegA.attempt_id | Should -Be $script:AttemptA.attempt_id
    }

    It 'AC-D.3: the CLI got CREDITS_RUN_ID, CREDITS_STATE_DB and CREDITS_SEGMENT of this segment' {
        $script:DumpA | Should -Not -BeNullOrEmpty
        $script:DumpA.env.CREDITS_RUN_ID | Should -Be $script:RunA
        Test-SamePath $script:DumpA.env.CREDITS_STATE_DB $script:Db | Should -BeTrue
        $script:DumpA.env.CREDITS_SEGMENT | Should -Be $script:SegA.segment_id
        $script:DumpA.env.PSObject.Properties.Name | Should -Not -Contain 'CREDITS_TEST_EFFECT_LOG'
    }

    It 'AC-D.3: BASH_DEFAULT_TIMEOUT_MS and BASH_MAX_TIMEOUT_MS are 600000 and DISABLE_AUTOUPDATER is 1' {
        $script:DumpA | Should -Not -BeNullOrEmpty
        $script:DumpA.env.BASH_DEFAULT_TIMEOUT_MS | Should -Be '600000'
        $script:DumpA.env.BASH_MAX_TIMEOUT_MS | Should -Be '600000'
        $script:DumpA.env.DISABLE_AUTOUPDATER | Should -Be '1'
    }

    It 'AC-D.3: ELECTRON_RUN_AS_NODE, DISABLE_PROMPT_CACHING and CLAUDE_CODE_CHILD_SESSION do not reach the CLI' {
        $script:DumpA | Should -Not -BeNullOrEmpty
        $names = @($script:DumpA.env.PSObject.Properties.Name)
        $names | Should -Not -Contain 'ELECTRON_RUN_AS_NODE'
        $names | Should -Not -Contain 'DISABLE_PROMPT_CACHING'
        $names | Should -Not -Contain 'CLAUDE_CODE_CHILD_SESSION'
    }

    It 'AC-D.3: the CLI got --session-id of the attempt and --max-budget-usd of the reservation' {
        $script:DumpA | Should -Not -BeNullOrEmpty
        $argv = @($script:DumpA.argv)
        $argv[[array]::IndexOf($argv, '--session-id') + 1] | Should -Be $script:AttemptA.expected_session_id
        [double]$argv[[array]::IndexOf($argv, '--max-budget-usd') + 1] | Should -Be ([double]$script:SegA.reservation_usd)
        [double]$script:SegA.reservation_usd | Should -Be 20.0
    }

    It 'AC-D.3: the dispatch ran under the attempt dispatch id in -OutputDir' {
        Test-Path -LiteralPath (Join-Path $script:Out "$($script:AttemptA.dispatch_id)/status.json") | Should -BeTrue
    }

    It 'AC-D.3: the launcher finalized the segment: exited, the cost known, the lane released' {
        $seg = Get-Segments $script:RunA | Select-Object -First 1
        $seg.finalized_by | Should -Be 'launcher'
        $seg.stop_class | Should -Be 'exited'
        [double]$seg.session_total_usd | Should -Be 0.0123
        $seg.reservation_released_utc | Should -Not -BeNullOrEmpty
        @(Get-Rows 'SELECT * FROM lanes WHERE segment_id = ?' @($seg.segment_id)).Count | Should -Be 0
        (Get-Run $script:RunA).state | Should -BeIn @('finalizing', 'stopped', 'done', 'done_unverified')
    }

    It 'AC-D.3: a second launch of the same task with no new request starts nothing' {
        $calls = @([System.IO.File]::ReadAllLines($script:CallsA)).Count
        $child = Start-Child $script:Launcher (Get-LauncherArgs $script:RunA) -Env @{ MOCK_CALL_LOG = $script:CallsA }
        (Get-Payload $child).outcome | Should -Be 'start_refused'
        @([System.IO.File]::ReadAllLines($script:CallsA)).Count | Should -Be $calls
        @(Get-Segments $script:RunA).Count | Should -Be 1
    }
}

Describe 'AC-D.3 negative: the launcher starts nothing' {
    It 'AC-D.3 negative: no pending request → start_refused no_request, no attempt, no CLI call' {
        $run = New-Id 'd3-noreq'
        New-RegisteredRun $run
        $calls = "$script:Root/$run.calls.jsonl"
        $child = Start-Child $script:Launcher (Get-LauncherArgs $run) -Env @{ MOCK_CALL_LOG = $calls }
        $payload = Get-Payload $child
        $payload.outcome | Should -Be 'start_refused'
        $payload.reason | Should -Be 'no_request'
        Test-Path -LiteralPath $calls | Should -BeFalse
        @(Get-Rows 'SELECT * FROM attempts WHERE run_id = ?' @($run)).Count | Should -Be 0
        (Get-Run $run).state | Should -Be 'registered'
    }

    It 'AC-D.3 negative: CLAUDECODE in the launcher environment → refused, the request stays pending, no CLI call' {
        $run = New-Id 'd3-nested'
        New-RegisteredRun $run
        Assert-Store 'request' @('--run-id', $run, '--started-by', 'human-command', '--request-id', "req-$run") | Out-Null
        $calls = "$script:Root/$run.calls.jsonl"
        $child = Start-Child $script:Launcher (Get-LauncherArgs $run) -Env @{ MOCK_CALL_LOG = $calls; CLAUDECODE = '1' }
        $child.Code | Should -Not -Be 0
        (Get-Payload $child).outcome | Should -Be 'refused'
        Test-Path -LiteralPath $calls | Should -BeFalse
        (@(Get-Rows 'SELECT state FROM requests WHERE request_id = ?' @("req-$run")) | Select-Object -First 1).state | Should -Be 'pending'
    }
}

Describe 'AC-D.3: the request age at the launcher (MX-31)' {
    BeforeAll {
        $script:T0 = (Get-Date).ToUniversalTime().AddMinutes(-30)
        $script:T0Text = Get-UtcText $script:T0
    }

    It 'mx_31_ AC-D.3: a request 120 s old → not_started stale_at_launcher, one credits_limit_tripped WARN, no CLI call' {
        $run = New-Id 'mx31-stale'
        New-RegisteredRun $run
        Assert-Store 'request' @('--run-id', $run, '--started-by', 'human-command', '--request-id', "req-$run") -NowUtc $script:T0Text | Out-Null
        $calls = "$script:Root/$run.calls.jsonl"
        $child = Start-Child $script:Launcher (Get-LauncherArgs $run @('-NowUtc', (Get-UtcText $script:T0.AddSeconds(120)))) -Env @{ MOCK_CALL_LOG = $calls }
        $payload = Get-Payload $child
        $payload.outcome | Should -Be 'not_started'
        $payload.reason | Should -Be 'stale_at_launcher'
        $request = @(Get-Rows 'SELECT * FROM requests WHERE request_id = ?' @("req-$run")) | Select-Object -First 1
        $request.state | Should -Be 'not_started'
        $request.reason | Should -Be 'stale_at_launcher'
        (Get-Run $run).state | Should -Be 'registered'
        Test-Path -LiteralPath $calls | Should -BeFalse
        $warn = @(Get-LauncherLog $run | Where-Object { $_.level -eq 'WARN' -and $_.event -eq 'credits_limit_tripped' })
        $warn.Count | Should -Be 1
        $warn[0].limit_name | Should -Be 'REQUEST_ACCEPT_TIMEOUT_S'
        [int]$warn[0].configured_value | Should -Be 120
        [int]$warn[0].observed_value | Should -Be 120
        $warn[0].window | Should -Be 'request_accept'
    }

    It 'mx_31_ AC-D.3: a request 119 s old → accepted and launched, no WARN' {
        $run = New-Id 'mx31-fresh'
        New-RegisteredRun $run
        Assert-Store 'request' @('--run-id', $run, '--started-by', 'human-command', '--request-id', "req-$run") -NowUtc $script:T0Text | Out-Null
        $calls = "$script:Root/$run.calls.jsonl"
        $child = Start-Child $script:Launcher (Get-LauncherArgs $run @('-NowUtc', (Get-UtcText $script:T0.AddSeconds(119)))) -Env @{ MOCK_CALL_LOG = $calls }
        $child.Code | Should -Be 0
        (@(Get-Rows 'SELECT state FROM requests WHERE request_id = ?' @("req-$run")) | Select-Object -First 1).state | Should -Be 'launched'
        Test-Path -LiteralPath $calls | Should -BeTrue
        @(Get-LauncherLog $run | Where-Object { $_.level -eq 'WARN' -and $_.event -eq 'credits_limit_tripped' }).Count | Should -Be 0
    }
}

Describe 'AC-D.3: a refused resume (MX-5)' {
    It 'mx_5_ AC-D.3: a resume rejected at admit (lane busy) → the run stopped, one resume_refused notice, exit 0, no CLI call; a new resume request works' {
        $lane = "tree:$script:Project/mx5-$([guid]::NewGuid().ToString('N').Substring(0, 6))"
        $run = New-Id 'mx5-stopped'
        New-StoppedRun $run $lane
        $holder = New-Id 'mx5-holder'
        New-RegisteredRun $holder $lane
        Assert-Store 'request' @('--run-id', $holder, '--started-by', 'human-command') | Out-Null
        Assert-Store 'accept' @('--run-id', $holder, '--launcher-pid', '4242', '--launcher-created', (Get-UtcText (Get-Date).AddMinutes(-1)),
            '--boot-id', 'boot-fixture-1', '--win-session', '1', '--attempt-id', "att-$holder") | Out-Null
        Assert-Store 'admit' @('--attempt-id', "att-$holder", '--segment-id', "seg-$holder") | Out-Null

        Assert-Store 'request' @('--run-id', $run, '--started-by', 'human-command', '--resume', '--request-id', "req-r1-$run") | Out-Null
        $calls = "$script:Root/$run.calls.jsonl"
        $child = Start-Child $script:Launcher (Get-LauncherArgs $run) -Env @{ MOCK_CALL_LOG = $calls }
        $child.Code | Should -Be 0
        $payload = Get-Payload $child
        $payload.outcome | Should -Be 'rejected'
        $payload.reason | Should -Be 'lane_busy'
        (Get-Run $run).state | Should -Be 'stopped'
        @(Get-Rows "SELECT * FROM notices WHERE run_id = ? AND kind = 'resume_refused'" @($run)).Count | Should -Be 1
        Test-Path -LiteralPath $calls | Should -BeFalse
        { Assert-Store 'request' @('--run-id', $run, '--started-by', 'human-command', '--resume', '--request-id', "req-r2-$run") } | Should -Not -Throw
        (Get-Run $run).state | Should -Be 'requested'
    }
}

# B-6 (docs/execution/plans/2026-10-17-run-parameters, WP-7, EA-19, EA-20). A manifest with `phases`
# makes the launcher's first start an admission (R§4.4 V6-047): it reads the `run_parameters` block
# from the brief's `## Authorization` section, runs `run_parameters.py inspect --block` on it, accepts,
# then binds the attempt's session as headless (`bind --pending <plan> --session <id> --context
# headless`), and only then launches. A refusal starts nothing. A legacy manifest calls no tool. The
# tool is a mock that logs its argv; the launcher runs it with the manifest's python_exe, given
# -RunParametersTool.
Describe 'AC-F.2: first-start admission (vec_v6_047_)' {
    BeforeAll {
        $script:RpTool = "$script:Root/mock_run_parameters.py"
        Set-Content -LiteralPath $script:RpTool -Encoding utf8NoBOM -Value @'
import json
import os
import sys

args = sys.argv[1:]
log = os.environ.get("MOCK_RP_LOG")
if log:
    with open(log, "a", encoding="utf-8") as f:
        f.write(json.dumps(args) + "\n")
verb = args[0] if args else ""
refuse = os.environ.get("MOCK_RP_REFUSE", "")
if refuse.partition(":")[0] == verb:
    print(json.dumps({"result": "refused", "reason": refuse.partition(":")[2], "authorized": False, "failure": True}))
    sys.exit(1)
done = {"inspect": "inspected", "bind": "bound", "stop": "stopped", "final": "finalized"}
print(json.dumps({"result": done.get(verb, "ok")}))
sys.exit(0)
'@
        $script:PhaseBrief = "$script:Root/brief-phases.md"
        Set-Content -LiteralPath $script:PhaseBrief -Encoding utf8NoBOM -Value @'
# Credits run brief: 2026-10-15-fixture

Plan the fixture project, then execute it in the executor worktree.

## Authorization

```yaml
run_parameters:
  schema: run-parameters/1
  decisions: hdp
  commit_plan: true
  exec_after_plan: true
  commit_exec: true
  push: never
```
'@

        # A registered run whose manifest names both phases (V6-044), with the brief given.
        function New-PhasedRun([string]$RunId, [string]$Brief) {
            $doc = [ordered]@{
                schema = 'credits-run.v1'; run_id = $RunId; kind = 'exec'
                project_root = $script:Project; plan_folder = 'docs/execution/plans/2026-10-15-fixture/'
                brief = $Brief; phases = @('plan', 'exec')
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
            Assert-Store 'request' @('--run-id', $RunId, '--started-by', 'human-command', '--request-id', "req-$RunId") | Out-Null
        }

        # Each logged tool call as one string: its argv joined by single spaces.
        function Get-RpCalls([string]$Log) {
            if (-not (Test-Path -LiteralPath $Log)) { return @() }
            @([System.IO.File]::ReadAllLines($Log) | Where-Object { $_.Trim() } | ForEach-Object { @($_ | ConvertFrom-Json) -join ' ' })
        }
    }

    It 'vec_v6_047_ AC-F.2: inspect, accept, then bind --pending as headless (AC-F.4), then one CLI launch' {
        $run = New-Id 'f2-admit'
        New-PhasedRun $run $script:PhaseBrief
        $rpLog = "$script:Root/$run.rp.jsonl"
        $calls = "$script:Root/$run.calls.jsonl"
        $argv = "$script:Root/$run.argv.json"
        $child = Start-Child $script:Launcher (Get-LauncherArgs $run @('-RunParametersTool', $script:RpTool)) -Env @{
            MOCK_RP_LOG = $rpLog; MOCK_CALL_LOG = $calls; MOCK_ARGV_FILE = $argv
        }
        $child.Code | Should -Be 0 -Because "$($child.Out) $($child.Err)"
        $rp = @(Get-RpCalls $rpLog)
        $rp.Count | Should -Be 2
        $rp[0] | Should -Match '^inspect '
        $rp[0] | Should -Match ' --block \S'
        $attempt = @(Get-Rows 'SELECT * FROM attempts WHERE run_id = ?' @($run)) | Select-Object -First 1
        $rp[1] | Should -Be "bind --pending 2026-10-15-fixture --session $($attempt.expected_session_id) --context headless"
        @([System.IO.File]::ReadAllLines($calls) | Where-Object { $_.Trim() }).Count | Should -Be 1
        $sent = @((Read-Json $argv).argv)
        $sent[[array]::IndexOf($sent, '--session-id') + 1] | Should -Be $attempt.expected_session_id
    }

    It 'vec_v6_047_ AC-F.2 negative: inspect refuses → admission_refused, no attempt, no bind, no CLI call' {
        $run = New-Id 'f2-refused'
        New-PhasedRun $run $script:PhaseBrief
        $rpLog = "$script:Root/$run.rp.jsonl"
        $calls = "$script:Root/$run.calls.jsonl"
        $child = Start-Child $script:Launcher (Get-LauncherArgs $run @('-RunParametersTool', $script:RpTool)) -Env @{
            MOCK_RP_LOG = $rpLog; MOCK_CALL_LOG = $calls; MOCK_RP_REFUSE = 'inspect:offer_digest'
        }
        (Get-Payload $child).outcome | Should -Be 'admission_refused'
        $rp = @(Get-RpCalls $rpLog)
        $rp.Count | Should -Be 1
        $rp[0] | Should -Match '^inspect '
        @(Get-Rows 'SELECT * FROM attempts WHERE run_id = ?' @($run)).Count | Should -Be 0
        Test-Path -LiteralPath $calls | Should -BeFalse
    }

    It 'vec_v6_047_ AC-F.2 negative: a phases manifest whose brief has no ## Authorization → admission_refused, no tool call, no CLI call' {
        $run = New-Id 'f2-noauth'
        New-PhasedRun $run $script:Brief
        $rpLog = "$script:Root/$run.rp.jsonl"
        $calls = "$script:Root/$run.calls.jsonl"
        $child = Start-Child $script:Launcher (Get-LauncherArgs $run @('-RunParametersTool', $script:RpTool)) -Env @{
            MOCK_RP_LOG = $rpLog; MOCK_CALL_LOG = $calls
        }
        (Get-Payload $child).outcome | Should -Be 'admission_refused'
        Test-Path -LiteralPath $rpLog | Should -BeFalse
        @(Get-Rows 'SELECT * FROM attempts WHERE run_id = ?' @($run)).Count | Should -Be 0
        Test-Path -LiteralPath $calls | Should -BeFalse
    }

    It 'AC-F.1 negative: a legacy manifest (no phases) launches as before and calls no run_parameters tool' {
        $run = New-Id 'f2-legacy'
        New-RegisteredRun $run
        Assert-Store 'request' @('--run-id', $run, '--started-by', 'human-command', '--request-id', "req-$run") | Out-Null
        $rpLog = "$script:Root/$run.rp.jsonl"
        $calls = "$script:Root/$run.calls.jsonl"
        $child = Start-Child $script:Launcher (Get-LauncherArgs $run @('-RunParametersTool', $script:RpTool)) -Env @{
            MOCK_RP_LOG = $rpLog; MOCK_CALL_LOG = $calls
        }
        $child.Code | Should -Be 0 -Because "$($child.Out) $($child.Err)"
        Test-Path -LiteralPath $rpLog | Should -BeFalse
        @([System.IO.File]::ReadAllLines($calls) | Where-Object { $_.Trim() }).Count | Should -Be 1
    }
}

Describe 'AC-21 (f): an uncapped admission runs with no --max-budget-usd' {
    BeforeAll {
        $script:RunU = New-Id 'u-run'
        New-RegisteredRun $script:RunU -Uncapped
        Assert-Store 'request' @('--run-id', $script:RunU, '--started-by', 'human-command', '--request-id', "req-$script:RunU") | Out-Null
        $script:ArgvU = "$script:Root/$script:RunU.argv.json"
        $script:ChildU = Start-Child $script:Launcher (Get-LauncherArgs $script:RunU) -Env @{ MOCK_ARGV_FILE = $script:ArgvU }
        $script:DumpU = if (Test-Path -LiteralPath $script:ArgvU) { Read-Json $script:ArgvU } else { $null }
        $script:SegU = Get-Segments $script:RunU | Select-Object -First 1
    }

    It 'AC-21 (f): the launcher exits 0 and the store holds no cap and no reservation' {
        $script:ChildU.Code | Should -Be 0 -Because "$($script:ChildU.Out) $($script:ChildU.Err)"
        $run = Get-Run $script:RunU
        $run.segment_cap_usd | Should -BeNullOrEmpty
        $run.run_cap_usd | Should -BeNullOrEmpty
        [double]$script:SegU.reservation_usd | Should -Be 0.0
    }

    It 'AC-21 (f): the CLI argv has no --max-budget-usd' {
        $script:DumpU | Should -Not -BeNullOrEmpty
        @($script:DumpU.argv) | Should -Not -Contain '--max-budget-usd'
        @($script:DumpU.argv) | Should -Contain '--session-id'
    }

    It 'AC-21 (f): the admitted log line says uncapped' {
        $line = @(Get-LauncherLog $script:RunU | Where-Object { $_.event -eq 'credits_segment_admitted' }) | Select-Object -First 1
        $line | Should -Not -BeNullOrEmpty
        $line.uncapped | Should -BeTrue
    }
}
