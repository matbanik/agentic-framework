# B-6 monitor phase calls (EA-21, EA-23; AC-F.3) of docs/execution/plans/2026-10-17-run-parameters.
# For a run whose manifest names `phases`, the monitor records two events through the run-side
# verb `credits_msg.py phase` (the new -PhaseTool parameter):
#   E13 after a verified DONE and a passed `final --plan <plan> --seal`:
#     phase E13 --by monitor --payload {"receipt": "final/<plan>/<generation>.json", "seal": "final/<plan>/<generation>.seal"}
#   E6 after a budget_cap class:
#     phase E6 --by monitor --payload {"tokens": <input + output + cache creation + cache read of output.json usage>}
# Each call has CREDITS_RUN_ID, CREDITS_SEGMENT (the last segment) and CREDITS_STATE_DB set. A
# failed call writes one WARN `phase_call_failed` record and does not change the class. A legacy
# run (no `phases`) makes no phase call. A refused seal (done_unverified) makes no E13 call.
#
# Each test has its own store. Process identities are real: a "dead" pid is a child that ended.

BeforeAll {
    $script:Repo = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
    $script:Skill = Join-Path $script:Repo '.agent/skills/claude-credits'
    $script:Watch = Join-Path $script:Skill 'Watch-CreditsRuns.ps1'
    $script:Module = Join-Path $script:Skill 'CreditsRun.psm1'
    $script:StateTool = Join-Path $script:Repo 'tools/credits_state.py'
    $script:Root = "{{RECEIPTS_DIR}}/credits-watch-phase-tests/$([guid]::NewGuid().ToString('N'))"
    $script:Out = "$script:Root/dispatch"
    New-Item -ItemType Directory -Force -Path $script:Out | Out-Null
    $script:EffectLog = "$script:Root/effects.jsonl"
    $script:SavedEffectLog = $env:CREDITS_TEST_EFFECT_LOG
    $env:CREDITS_TEST_EFFECT_LOG = $script:EffectLog
    $script:Db = $null
    $script:Plan = '2026-10-15-fixture'
    $script:PlanFolder = "docs/execution/plans/$script:Plan/"
    $script:Brief = "$script:Root/brief.md"
    Set-Content -LiteralPath $script:Brief -Value 'credits monitor phase test brief' -Encoding utf8NoBOM

    $venvPy = Join-Path $script:Repo '.venv/Scripts/python.exe'
    $script:Py = if (Test-Path -LiteralPath $venvPy) { $venvPy } else { (Get-Command python -ErrorAction Stop).Source }
    $script:BasePython = (& $script:Py -c 'import sys; print(sys._base_executable)' | Out-String).Trim()
    $script:Mock = "$script:Root/mock_claude.bat"
    Set-Content -LiteralPath $script:Mock -Encoding ascii -Value "@echo off`r`necho 2.1.296 (Claude Code)"

    # The run_parameters tool: argv to MOCK_RP_LOG; MOCK_RP_REFUSE=<verb>:<reason> refuses that verb.
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
if verb == "final":
    plan = args[args.index("--plan") + 1] if "--plan" in args else ""
    print(json.dumps({"result": "sealed", "plan": plan, "generation": 1, "store_seq": 7}))
    sys.exit(0)
done = {"inspect": "inspected", "bind": "bound", "stop": "stopped"}
print(json.dumps({"result": done.get(verb, "ok")}))
sys.exit(0)
'@

    # The phase tool: {argv, env} to MOCK_PHASE_LOG; MOCK_PHASE_REFUSE set → a refusal, exit 3.
    $script:PhaseTool = "$script:Root/mock_credits_msg.py"
    Set-Content -LiteralPath $script:PhaseTool -Encoding utf8NoBOM -Value @'
import json
import os
import sys

args = sys.argv[1:]
log = os.environ.get("MOCK_PHASE_LOG")
if log:
    env = {k: os.environ.get(k) for k in ("CREDITS_RUN_ID", "CREDITS_SEGMENT", "CREDITS_STATE_DB")}
    with open(log, "a", encoding="utf-8") as f:
        f.write(json.dumps({"argv": args, "env": env}) + "\n")
if os.environ.get("MOCK_PHASE_REFUSE"):
    print(json.dumps({"result": "refused", "error": os.environ["MOCK_PHASE_REFUSE"], "verb": "phase"}))
    sys.exit(3)
print(json.dumps({"result": "recorded", "verb": "phase", "records": [], "state": "DONE", "seq": 7}))
sys.exit(0)
'@

    if (-not (Get-Module -Name CreditsRun)) { Import-Module -Name $script:Module -Force -DisableNameChecking -ErrorAction Stop }
    $script:BootId = Get-CreditsBootId
    $script:WinSession = [string](Get-Process -Id $PID).SessionId

    function New-Id([string]$Prefix) { "$Prefix-$([guid]::NewGuid().ToString('N').Substring(0, 10))" }
    function Get-UtcText([datetime]$Value) { $Value.ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ') }

    function New-Store {
        $dir = "$script:Root/store-$([guid]::NewGuid().ToString('N').Substring(0, 10))"
        New-Item -ItemType Directory -Force -Path $dir | Out-Null
        $script:Db = "$dir/state.db"
        Assert-Store 'init' | Out-Null
        $dir
    }

    function Assert-Store([string]$Verb, [string[]]$Arguments = @()) {
        $psi = [System.Diagnostics.ProcessStartInfo]::new($script:Py)
        foreach ($a in @('-X', 'utf8', $script:StateTool, '--db', $script:Db, $Verb) + $Arguments) { $psi.ArgumentList.Add([string]$a) }
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

    function Invoke-Py([string]$Code, [string[]]$Arguments) {
        $psi = [System.Diagnostics.ProcessStartInfo]::new($script:Py)
        foreach ($a in @('-X', 'utf8', '-c', $Code) + $Arguments) { $psi.ArgumentList.Add([string]$a) }
        $psi.UseShellExecute = $false
        $psi.RedirectStandardOutput = $true
        $psi.RedirectStandardError = $true
        $p = [System.Diagnostics.Process]::Start($psi)
        $so = $p.StandardOutput.ReadToEndAsync(); $se = $p.StandardError.ReadToEndAsync()
        $p.WaitForExit()
        if ($p.ExitCode -ne 0) { throw "fixture python failed: exit=$($p.ExitCode) err=$($se.Result)" }
        $so.Result
    }

    function Get-Rows([string]$Sql, [string[]]$Params = @()) {
        $code = "import json, sqlite3, sys; c = sqlite3.connect('file:' + sys.argv[1] + '?mode=ro', uri=True); c.row_factory = sqlite3.Row; print(json.dumps([dict(r) for r in c.execute(sys.argv[2], sys.argv[3:])]))"
        @((Invoke-Py $code (@($script:Db, $Sql) + $Params)) | ConvertFrom-Json)
    }

    function Set-Rows([string]$Sql, [string[]]$Params = @()) {
        $code = 'import sqlite3, sys; c = sqlite3.connect(sys.argv[1]); c.execute(sys.argv[2], sys.argv[3:]); c.commit(); c.close()'
        Invoke-Py $code (@($script:Db, $Sql) + $Params) | Out-Null
    }

    function Get-Run([string]$RunId) { @(Get-Rows 'SELECT * FROM runs WHERE run_id = ?' @($RunId)) | Select-Object -First 1 }

    function Get-MonitorLog {
        $path = Join-Path (Split-Path -Parent $script:Db) 'logs/monitor.jsonl'
        if (-not (Test-Path -LiteralPath $path)) { return @() }
        @(Get-Content -LiteralPath $path | Where-Object { $_.Trim() } | ForEach-Object { $_ | ConvertFrom-Json })
    }

    function New-DeadIdentity {
        $p = Start-Process -FilePath $script:BasePython -ArgumentList '-c "import time; time.sleep(0.3)"' -PassThru -NoNewWindow
        $created = Get-UtcText $p.StartTime
        $p.WaitForExit()
        [pscustomobject]@{ Pid = $p.Id; Created = $created }
    }

    # A registered run (phased unless -Legacy), requested, accepted, admitted and launched with
    # dead identities; its one segment is seg-<run>.
    function New-Running([string]$RunId, [string]$Project, [switch]$Legacy) {
        New-Item -ItemType Directory -Force -Path $Project | Out-Null
        $doc = [ordered]@{
            schema = 'credits-run.v1'; run_id = $RunId; kind = 'exec'
            project_root = $Project; plan_folder = $script:PlanFolder
            brief = $script:Brief
            launch = [ordered]@{
                working_directory = $Project; claude_exe = $script:Mock; python_exe = $script:Py
                permission_mode = 'bypassPermissions'; effort = 'low'; segment_cap_usd = 20.0; timeout_sec = 3600
            }
            budget = [ordered]@{ run_cap_usd = 50.0 }
            messaging = [ordered]@{ orchestrator_sessions = @('00000000-0000-4000-8000-0000000000aa'); ruling_enabled = $false; gate_wait_max_min = 0 }
            depends_on = @(); lane = "tree:$Project/$RunId"
        }
        if (-not $Legacy) { $doc.phases = @('plan', 'exec') }
        $manifest = "$script:Root/manifest-$RunId.json"
        Set-Content -LiteralPath $manifest -Value ($doc | ConvertTo-Json -Depth 6) -Encoding utf8NoBOM
        Assert-Store 'register' @('--run-id', $RunId, '--manifest', $manifest, '--cli-version', '2.1.296', '--kit-revision', 'kitrev-fixture') | Out-Null
        Assert-Store 'registered' @('--run-id', $RunId, '--task-hash', "taskhash-$RunId") | Out-Null
        Assert-Store 'request' @('--run-id', $RunId, '--started-by', 'human-command', '--request-id', "req-$RunId") | Out-Null
        $launcher = New-DeadIdentity
        Assert-Store 'accept' @('--run-id', $RunId, '--launcher-pid', $launcher.Pid, '--launcher-created', $launcher.Created,
            '--boot-id', $script:BootId, '--win-session', $script:WinSession, '--attempt-id', "att-$RunId", '--dispatch-id', "disp-$RunId") | Out-Null
        Assert-Store 'admit' @('--attempt-id', "att-$RunId", '--segment-id', "seg-$RunId") | Out-Null
        $cli = New-DeadIdentity
        Assert-Store 'launched' @('--segment-id', "seg-$RunId", '--pid', $cli.Pid, '--created', $cli.Created, '--boot-id', $script:BootId) | Out-Null
    }

    function Write-Dispatch([string]$RunId, [hashtable]$Files) {
        $dir = "$script:Out/disp-$RunId"
        New-Item -ItemType Directory -Force -Path $dir | Out-Null
        foreach ($name in $Files.Keys) { Set-Content -LiteralPath (Join-Path $dir $name) -Value $Files[$name] -Encoding utf8NoBOM -NoNewline }
    }

    function Write-DoneDispatch([string]$RunId) {
        Write-Dispatch $RunId @{
            'status.json' = '{"exit_code": 0, "timed_out": false, "total_cost_usd": 1.0}'
            'output.json' = '{"type": "result", "subtype": "success", "is_error": false, "total_cost_usd": 1.0}'
            'final.md'    = "Closeout complete.`n`nStatus: DONE`n"
        }
    }

    function Write-BudgetDispatch([string]$RunId) {
        Write-Dispatch $RunId @{
            'status.json' = '{"exit_code": 1, "timed_out": false, "total_cost_usd": 4.01}'
            'output.json' = '{"type": "result", "subtype": "error_max_budget_usd", "is_error": true, "total_cost_usd": 4.01, "usage": {"input_tokens": 100, "output_tokens": 20}}'
        }
    }

    function Get-Payload([string]$Text) {
        $last = @("$Text" -split "`r?`n" | Where-Object { $_.TrimStart().StartsWith('{') }) | Select-Object -Last 1
        if (-not $last) { return $null }
        try { $last | ConvertFrom-Json -ErrorAction Stop } catch { $null }
    }

    function New-Notifier { { param($notice) $null = $notice } }

    # One monitor pass with -RunParametersTool, -PhaseTool and the mocks' environment.
    function Invoke-PhaseWatch([string]$RpLog, [string]$PhaseLog, [string]$RpRefuse = '', [string]$PhaseRefuse = '') {
        if (-not (Test-Path -LiteralPath $script:Watch)) { throw "the monitor is missing: $script:Watch" }
        $env:MOCK_RP_LOG = $RpLog
        $env:MOCK_PHASE_LOG = $PhaseLog
        if ($RpRefuse) { $env:MOCK_RP_REFUSE = $RpRefuse }
        if ($PhaseRefuse) { $env:MOCK_PHASE_REFUSE = $PhaseRefuse }
        try {
            $splat = @{
                StateDb = $script:Db; OutputDir = $script:Out; Observations = @{}; Notifier = (New-Notifier); HostEvents = @()
                RunParametersTool = $script:RpTool; PhaseTool = $script:PhaseTool
            }
            $global:LASTEXITCODE = 0
            $lines = @(); $thrown = $null
            try { $lines = @(& $script:Watch @splat 2>$null) } catch { $thrown = $_.Exception.Message }
            $code = $global:LASTEXITCODE
            [pscustomobject]@{ Code = $code; Payload = (Get-Payload (($lines | ForEach-Object { "$_" }) -join "`n")); Thrown = $thrown }
        } finally {
            foreach ($name in 'MOCK_RP_LOG', 'MOCK_PHASE_LOG', 'MOCK_RP_REFUSE', 'MOCK_PHASE_REFUSE') {
                Remove-Item "Env:$name" -ErrorAction SilentlyContinue
            }
        }
    }

    function Assert-Pass($Result) {
        $Result.Thrown | Should -BeNullOrEmpty
        $Result.Code | Should -Be 0
        $Result.Payload.outcome | Should -Be 'pass'
    }

    # Each logged phase call: Argv (string[]), Env, and the value after a flag.
    function Get-PhaseCalls([string]$Log) {
        if (-not (Test-Path -LiteralPath $Log)) { return @() }
        @([System.IO.File]::ReadAllLines($Log) | Where-Object { $_.Trim() } | ForEach-Object { $_ | ConvertFrom-Json })
    }
    function Get-Flag($Call, [string]$Flag) {
        $argv = @($Call.argv)
        $i = [array]::IndexOf($argv, $Flag)
        if ($i -lt 0 -or $i + 1 -ge $argv.Count) { return $null }
        $argv[$i + 1]
    }
    function Get-FullPath([string]$Path) { [System.IO.Path]::GetFullPath($Path) }

    # A plan tree whose closeout passes the completion-preflight check (R§5.2 done evidence).
    function New-DoneTree([string]$Tree) {
        $plan = Join-Path $Tree $script:PlanFolder
        $handoffs = Join-Path $Tree '.agent/context/handoffs'
        $reflections = Join-Path $Tree 'docs/execution/reflections'
        New-Item -ItemType Directory -Force -Path $plan, $handoffs, $reflections | Out-Null
        Set-Content -LiteralPath (Join-Path $plan 'task.md') -Encoding utf8NoBOM -Value (@(
                '---', "project: `"$script:Plan`"", 'status: "done"', 'stop_gate: "released:done"', 'meus: []', '---', '',
                '# Task', '', '| # | Task | Owner | Deliverable | Status |', '|---|------|-------|-------------|--------|',
                '| 1 | Write the tests | coder | tests | [x] |', '| 2 | Make them pass | coder | code | [x] |') -join "`n")
        Set-Content -LiteralPath (Join-Path $plan 'implementation-plan.md') -Encoding utf8NoBOM -Value "# Plan`n`nThe fixture plan."
        Set-Content -LiteralPath (Join-Path $handoffs "$script:Plan-implementation-critical-review.md") -Encoding utf8NoBOM -Value (@(
                '---', 'verdict: "approved"', 'findings_count: 0', '---', '', '# Implementation critical review', '',
                '| Finding | Severity |', '|---------|----------|', '| none | - |', '', 'verdict: approved', 'findings_count: 0') -join "`n")
        Set-Content -LiteralPath (Join-Path $handoffs "$script:Plan-handoff.md") -Encoding utf8NoBOM -Value (@(
                '# Handoff', '', '## Acceptance Criteria', '', 'AC-1 holds.', '', '<!-- CACHE BOUNDARY -->', '',
                '## Evidence', '', 'FAIL_TO_PASS: tests/unit/test_fixture.py', '', '## Changed Files', '', '- tools/fixture.py') -join "`n")
        Set-Content -LiteralPath (Join-Path $reflections "$script:Plan-reflection.md") -Encoding utf8NoBOM -Value (@(
                '# Reflection', '', '## Friction Log', '', '## Pattern Extraction', '', '## Decisions Log', '',
                '## Next Session Design Rules', '', 'RULE-1: none.', '', '## Efficiency Metrics', '', '## Rule Adherence', '',
                '## Instruction Coverage', '', '```yaml', 'schema: v1', 'sections:', '  - id: tdd', 'loaded:', '  - AGENTS.md',
                'decisive_rules:', '  - tests first', '```') -join "`n")
        Set-Content -LiteralPath (Join-Path $Tree 'docs/execution/metrics.md') -Encoding utf8NoBOM -Value (@(
                '# Metrics', '', '| Date | MEU(s) | Rounds | Notes |', '|------|--------|--------|-------|',
                "| 2026-10-15 | $script:Plan | 1 | fixture |") -join "`n")
    }

    # The exec-run capture and seal of R§5.4 (a landings row per part).
    function Set-Landings([string]$RunId) {
        Set-Rows 'INSERT INTO landings (run_id, part, path, blob, sealed_utc) VALUES (?, ?, ?, ?, NULL)' @($RunId, 'product', 'tools/fixture.py', 'blob-product')
        Set-Rows 'INSERT INTO landings (run_id, part, path, blob, sealed_utc) VALUES (?, ?, ?, ?, ?)' @($RunId, 'closeout', ".agent/context/handoffs/$script:Plan-handoff.md", 'blob-closeout', (Get-UtcText (Get-Date)))
    }

    # A done fixture: the tree, the run, the landings and the dispatch. Returns the run id.
    function New-DoneRun([string]$Prefix, [switch]$Legacy) {
        New-Store | Out-Null
        $run = New-Id $Prefix
        $tree = "$script:Root/tree-$run"
        New-DoneTree $tree
        New-Running $run $tree -Legacy:$Legacy
        Set-Landings $run
        Write-DoneDispatch $run
        $run
    }

    function New-BudgetRun([string]$Prefix, [switch]$Legacy) {
        New-Store | Out-Null
        $run = New-Id $Prefix
        New-Running $run "$script:Root/tree-$run" -Legacy:$Legacy
        Write-BudgetDispatch $run
        $run
    }
}

AfterAll {
    $env:CREDITS_TEST_EFFECT_LOG = $script:SavedEffectLog
    if ($script:Root -and (Test-Path -LiteralPath $script:Root)) { Remove-Item -LiteralPath $script:Root -Recurse -Force -ErrorAction SilentlyContinue }
}

Describe 'AC-F.3: the monitor records E13 and E6 through credits_msg.py phase (EA-21, EA-23)' {
    It 'AC-F.3: a verified, sealed DONE of a phases run → done and one phase E13 --by monitor with the seal paths and the run env' {
        $run = New-DoneRun 'pw-done'
        $rpLog = "$script:Root/$run.rp.jsonl"; $phaseLog = "$script:Root/$run.phase.jsonl"
        Assert-Pass (Invoke-PhaseWatch $rpLog $phaseLog)
        Assert-Pass (Invoke-PhaseWatch $rpLog $phaseLog)
        (Get-Run $run).state | Should -Be 'done'
        $calls = @(Get-PhaseCalls $phaseLog)
        $calls.Count | Should -Be 1
        $call = $calls[0]
        @($call.argv)[0] | Should -Be 'phase'
        @($call.argv)[1] | Should -Be 'E13'
        Get-Flag $call '--by' | Should -Be 'monitor'
        $payload = (Get-Flag $call '--payload') | ConvertFrom-Json
        $payload.receipt | Should -Be "final/$script:Plan/1.json"
        $payload.seal | Should -Be "final/$script:Plan/1.seal"
        @($payload.PSObject.Properties.Name).Count | Should -Be 2
        $call.env.CREDITS_RUN_ID | Should -Be $run
        $call.env.CREDITS_SEGMENT | Should -Be "seg-$run"
        Get-FullPath $call.env.CREDITS_STATE_DB | Should -Be (Get-FullPath $script:Db)
    }

    It 'AC-F.3: a budget_cap of a phases run → budget_cap and one phase E6 --by monitor with the usage tokens' {
        $run = New-BudgetRun 'pw-budget'
        $rpLog = "$script:Root/$run.rp.jsonl"; $phaseLog = "$script:Root/$run.phase.jsonl"
        Assert-Pass (Invoke-PhaseWatch $rpLog $phaseLog)
        Assert-Pass (Invoke-PhaseWatch $rpLog $phaseLog)
        (Get-Run $run).stop_class | Should -Be 'budget_cap'
        $calls = @(Get-PhaseCalls $phaseLog)
        $calls.Count | Should -Be 1
        @($calls[0].argv)[0] | Should -Be 'phase'
        @($calls[0].argv)[1] | Should -Be 'E6'
        Get-Flag $calls[0] '--by' | Should -Be 'monitor'
        ((Get-Flag $calls[0] '--payload') | ConvertFrom-Json).tokens | Should -Be 120
        $calls[0].env.CREDITS_RUN_ID | Should -Be $run
        $calls[0].env.CREDITS_SEGMENT | Should -Be "seg-$run"
    }

    It 'AC-F.3 negative: the phase tool refuses E13 → the class stays done and one phase_call_failed WARN record' {
        $run = New-DoneRun 'pw-refuse'
        $rpLog = "$script:Root/$run.rp.jsonl"; $phaseLog = "$script:Root/$run.phase.jsonl"
        Assert-Pass (Invoke-PhaseWatch $rpLog $phaseLog -PhaseRefuse 'stale_lock')
        Assert-Pass (Invoke-PhaseWatch $rpLog $phaseLog -PhaseRefuse 'stale_lock')
        (Get-Run $run).state | Should -Be 'done'
        @(Get-PhaseCalls $phaseLog).Count | Should -Be 1
        $warn = @(Get-MonitorLog | Where-Object { $_.event -eq 'phase_call_failed' -and $_.level -eq 'WARN' })
        $warn.Count | Should -Be 1
    }

    It 'AC-F.3 negative: the phase tool refuses E6 → the class stays budget_cap and one phase_call_failed WARN record' {
        $run = New-BudgetRun 'pw-budget-refuse'
        $rpLog = "$script:Root/$run.rp.jsonl"; $phaseLog = "$script:Root/$run.phase.jsonl"
        Assert-Pass (Invoke-PhaseWatch $rpLog $phaseLog -PhaseRefuse 'stale_lock')
        (Get-Run $run).stop_class | Should -Be 'budget_cap'
        @(Get-PhaseCalls $phaseLog).Count | Should -Be 1
        @(Get-MonitorLog | Where-Object { $_.event -eq 'phase_call_failed' -and $_.level -eq 'WARN' }).Count | Should -Be 1
    }

    It 'AC-F.3 negative: a refused seal → done_unverified and no phase call' {
        $run = New-DoneRun 'pw-seal'
        $rpLog = "$script:Root/$run.rp.jsonl"; $phaseLog = "$script:Root/$run.phase.jsonl"
        Assert-Pass (Invoke-PhaseWatch $rpLog $phaseLog -RpRefuse 'final:stale_lock')
        Assert-Pass (Invoke-PhaseWatch $rpLog $phaseLog -RpRefuse 'final:stale_lock')
        (Get-Run $run).state | Should -Be 'done_unverified'
        Test-Path -LiteralPath $phaseLog | Should -BeFalse
    }

    It 'AC-F.3 negative: a legacy run (no phases) that is done or budget_cap → no phase call' -ForEach @(
        @{ Kind = 'done' }, @{ Kind = 'budget' }
    ) {
        $run = if ($Kind -eq 'done') { New-DoneRun 'pw-legacy' -Legacy } else { New-BudgetRun 'pw-legacy-budget' -Legacy }
        $rpLog = "$script:Root/$run.rp.jsonl"; $phaseLog = "$script:Root/$run.phase.jsonl"
        Assert-Pass (Invoke-PhaseWatch $rpLog $phaseLog)
        Assert-Pass (Invoke-PhaseWatch $rpLog $phaseLog)
        if ($Kind -eq 'done') { (Get-Run $run).state | Should -Be 'done' } else { (Get-Run $run).stop_class | Should -Be 'budget_cap' }
        Test-Path -LiteralPath $phaseLog | Should -BeFalse
    }
}
