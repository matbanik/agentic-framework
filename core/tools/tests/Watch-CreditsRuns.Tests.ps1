# S3 monitor (Component E of docs/execution/plans/2026-10-15-scheduled-credits-runs).
# AC-E.1 Watch-CreditsRuns.ps1 takes the monitor_lease, then runs the scans, the job proof,
#   complete_segment and the classification. Each finalized segment gets one class of STOP_CLASSES
#   (R§5.2) from the signals of R§5.1. Signals that match no class → unknown. A second monitor
#   while a live holder has the lease → lease_held, no store write, a rescan.request file.
# AC-E.2 the monitor marks done only when tools/completion_preflight.py --json reports ok (and an
#   exec run has its capture and its seal); else done_unverified with the missing items (MX-25).
#   The check itself is in tools/tests/test_completion_preflight.py.
# AC-E.3 the scans: orphan request (MX-16), a dead launcher at accepted (MX-4) or admitted (MX-3),
#   the outbox cursor (MX-13), an effect again after a crash (MX-22), job_proof_unknown (MX-30),
#   registration_incomplete (MX-34), manual segments (MX-35, MX-43). A pass on an unchanged store
#   adds no transition.
# AC-E.4 the monitor never resumes and never sends a ruling: a stopped run gets a notice only.
# AC-E.5 one notice per key, sent through the -Notifier seam; a failed send → retry, sent on a
#   later pass, never again after it is sent. The manual proof notifies manual_child_alive once.
# AC-E.6 P-8b again through the monitor: (b) the launcher is killed, (c) the tree is killed,
#   (f) the job is live on the first pass → the monitor terminates it and finalizes on a later
#   pass, (g) an access error → unknown (MX-30).
#
# The monitor contract that these tests fix:
#   Watch-CreditsRuns.ps1 -StateDb <path> -OutputDir <dispatch dir> [-NowUtc <datetime>]
#     [-Observations @{ <segment id> = <Get-CreditsJobProof -Observation> }]
#     [-Notifier { param($notice) }]   # $notice.subject holds the notice key; a throw = failed send
#     [-HostEvents @(<objects with Id, ProviderName, TimeCreated>)]   # the event-log seam
#   It runs one pass. It prints one JSON line: outcome pass, lease_held or error. Exit 0 for pass
#   and lease_held. Its log is <store dir>/logs/monitor.jsonl (JSON lines with level and event).
#   The store verb lease --pid --created --boot-id takes the monitor_lease.
#
# Each test has its own store. Process identities are real: a "dead" pid is a child that ended.

BeforeAll {
    $script:Repo = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
    $script:Skill = Join-Path $script:Repo '.agent/skills/claude-credits'
    $script:Watch = Join-Path $script:Skill 'Watch-CreditsRuns.ps1'
    $script:Launcher = Join-Path $script:Skill 'Start-CreditsRun.ps1'
    $script:Module = Join-Path $script:Skill 'CreditsRun.psm1'
    $script:StateTool = Join-Path $script:Repo 'tools/credits_state.py'
    $script:Root = "{{RECEIPTS_DIR}}/credits-watch-tests/$([guid]::NewGuid().ToString('N'))"
    $script:Out = "$script:Root/dispatch"
    $script:Project = "$script:Root/project"
    New-Item -ItemType Directory -Force -Path $script:Out, $script:Project | Out-Null
    $script:EffectLog = "$script:Root/effects.jsonl"
    $script:SavedEffectLog = $env:CREDITS_TEST_EFFECT_LOG
    $env:CREDITS_TEST_EFFECT_LOG = $script:EffectLog
    $script:Db = $null
    $script:Kids = [System.Collections.Generic.List[int]]::new()
    $script:Plan = '2026-10-15-fixture'
    $script:PlanFolder = "docs/execution/plans/$script:Plan/"

    # R§5.2: the stop classes.
    $script:StopClasses = @(
        'done', 'done_unverified', 'parked', 'decision', 'handback', 'round_cap', 'reviewer_unavailable',
        'reboot', 'sleep_death', 'death_unknown', 'background_wait_exit', 'transient_api', 'billing',
        'auth_config', 'budget_cap', 'timeout', 'launch_failed', 'base_moved', 'cancelled', 'unknown'
    )

    $script:KeyFile = "$script:Root/fake.key"
    Set-Content -LiteralPath $script:KeyFile -Value ('sk-' + 'ant-api03-' + ('A' * 40)) -Encoding utf8NoBOM
    $script:Brief = "$script:Root/brief.md"
    Set-Content -LiteralPath $script:Brief -Value 'credits monitor test brief' -Encoding utf8NoBOM

    $venvPy = Join-Path $script:Repo '.venv/Scripts/python.exe'
    $script:Py = if (Test-Path -LiteralPath $venvPy) { $venvPy } else { (Get-Command python -ErrorAction Stop).Source }
    $script:BasePython = (& $script:Py -c 'import sys; print(sys._base_executable)' | Out-String).Trim()
    $mockPy = "$script:Root/mock_claude.py"
    Set-Content -LiteralPath $mockPy -Encoding utf8NoBOM -Value @'
import json
import os
import sys
import time

args = sys.argv[1:]
if "--version" in args:
    print("2.1.296 (Claude Code)")
    sys.exit(0)
stdin_text = sys.stdin.read()
argv_file = os.environ.get("MOCK_ARGV_FILE")
if argv_file:
    with open(argv_file, "w", encoding="utf-8") as f:
        json.dump({"argv": args, "pid": os.getpid(), "ppid": os.getppid()}, f)
hang = os.environ.get("MOCK_HANG_SECONDS")
if hang:
    time.sleep(float(hang))
out = {"type": "result", "result": "MOCK_RESULT_OK", "is_error": False, "total_cost_usd": 0.0123}
print(json.dumps(out))
sys.exit(0)
'@
    $script:Mock = "$script:Root/mock_claude.bat"
    Set-Content -LiteralPath $script:Mock -Encoding ascii -Value "@echo off`r`n`"$script:BasePython`" -X utf8 `"$mockPy`" %*"

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

    if (-not (Get-Module -Name CreditsRun)) { Import-Module -Name $script:Module -Force -DisableNameChecking -ErrorAction Stop }
    $script:BootId = Get-CreditsBootId
    $script:WinSession = [string](Get-Process -Id $PID).SessionId

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
        $script:Kids.Add($p.Id)
        $so = $p.StandardOutput.ReadToEndAsync(); $se = $p.StandardError.ReadToEndAsync()
        if ($NoWait) { return [pscustomobject]@{ Process = $p; StdOut = $so; StdErr = $se } }
        if (-not $p.WaitForExit(240000)) { & taskkill.exe /PID $p.Id /T /F *> $null; throw "child timed out: $Script" }
        $p.WaitForExit()
        [pscustomobject]@{ Code = $p.ExitCode; Out = $so.Result; Err = $se.Result }
    }

    function New-Id([string]$Prefix) { "$Prefix-$([guid]::NewGuid().ToString('N').Substring(0, 10))" }
    function Get-UtcText([datetime]$Value) { $Value.ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ') }
    function Read-Json([string]$Path) { [System.IO.File]::ReadAllText($Path, [System.Text.Encoding]::UTF8) | ConvertFrom-Json }
    function Test-Alive([int]$ProcessId) { $null -ne (Get-Process -Id $ProcessId -ErrorAction SilentlyContinue) }

    function Wait-Until([scriptblock]$Condition, [int]$Seconds = 60) {
        $deadline = (Get-Date).AddSeconds($Seconds)
        while ((Get-Date) -lt $deadline) {
            if (& $Condition) { return $true }
            Start-Sleep -Milliseconds 250
        }
        [bool](& $Condition)
    }

    # A new store for one test. The monitor log and rescan.request go next to it.
    function New-Store {
        $dir = "$script:Root/store-$([guid]::NewGuid().ToString('N').Substring(0, 10))"
        New-Item -ItemType Directory -Force -Path $dir | Out-Null
        $script:Db = "$dir/state.db"
        Assert-Store 'init' | Out-Null
        $dir
    }

    function Assert-Store([string]$Verb, [string[]]$Arguments = @(), $NowUtc = $null) {
        $psi = [System.Diagnostics.ProcessStartInfo]::new($script:Py)
        $head = @('-X', 'utf8', $script:StateTool, '--db', $script:Db)
        if ($null -ne $NowUtc) { $head += @('--now-utc', (Get-UtcText $NowUtc)) }
        foreach ($a in $head + @($Verb) + $Arguments) { $psi.ArgumentList.Add([string]$a) }
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

    # python -c with an argument list: no shell quoting of the code, the SQL or the JSON values.
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

    # A fixture write that no store verb makes (an outbox event, a landing, a job-less manual segment).
    function Set-Rows([string]$Sql, [string[]]$Params = @()) {
        $code = 'import sqlite3, sys; c = sqlite3.connect(sys.argv[1]); c.execute(sys.argv[2], sys.argv[3:]); c.commit(); c.close()'
        Invoke-Py $code (@($script:Db, $Sql) + $Params) | Out-Null
    }

    function Get-Count([string]$Sql, [string[]]$Params = @()) { [int](@(Get-Rows $Sql $Params) | Select-Object -First 1).n }
    function Get-Run([string]$RunId) { @(Get-Rows 'SELECT * FROM runs WHERE run_id = ?' @($RunId)) | Select-Object -First 1 }
    function Get-Segment([string]$RunId) { @(Get-Rows 'SELECT * FROM segments WHERE run_id = ? ORDER BY created_utc, rowid' @($RunId)) | Select-Object -Last 1 }
    function Get-LaneHolder([string]$Lane) { (@(Get-Rows 'SELECT segment_id FROM lanes WHERE lane = ?' @($Lane)) | Select-Object -First 1).segment_id }
    function Get-Transitions { Get-Count 'SELECT COUNT(*) AS n FROM transitions' }
    function Get-Notices([string]$Key) { @(Get-Rows 'SELECT * FROM notices WHERE notice_key = ?' @($Key)) }

    function Get-MonitorLog {
        $path = Join-Path (Split-Path -Parent $script:Db) 'logs/monitor.jsonl'
        if (-not (Test-Path -LiteralPath $path)) { return @() }
        @(Get-Content -LiteralPath $path | Where-Object { $_.Trim() } | ForEach-Object { $_ | ConvertFrom-Json })
    }

    # A process that has ended: its pid and creation time are a dead identity.
    function New-DeadIdentity {
        $p = Start-Process -FilePath $script:BasePython -ArgumentList '-c "import time; time.sleep(0.3)"' -PassThru -NoNewWindow
        $created = Get-UtcText $p.StartTime
        $p.WaitForExit()
        [pscustomobject]@{ Pid = $p.Id; Created = $created }
    }

    # A live sleeper: a live identity.
    function New-LiveIdentity([int]$Seconds = 120) {
        $p = Start-Process -FilePath $script:BasePython -ArgumentList "-c `"import time; time.sleep($Seconds)`"" -PassThru -NoNewWindow
        $script:Kids.Add($p.Id)
        Start-Sleep -Milliseconds 300
        if ($p.HasExited) { throw "the live sleeper ended at once: exit=$($p.ExitCode)" }
        [pscustomobject]@{ Pid = $p.Id; Created = (Get-UtcText $p.StartTime); Process = $p }
    }

    function New-RegisteredRun([string]$RunId, [string]$Project = $script:Project, [switch]$NoRegistered) {
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
        $manifest = "$script:Root/manifest-$RunId.json"
        Set-Content -LiteralPath $manifest -Value ($doc | ConvertTo-Json -Depth 6) -Encoding utf8NoBOM
        Assert-Store 'register' @('--run-id', $RunId, '--manifest', $manifest, '--cli-version', '2.1.296', '--kit-revision', 'kitrev-fixture') | Out-Null
        if (-not $NoRegistered) { Assert-Store 'registered' @('--run-id', $RunId, '--task-hash', "taskhash-$RunId") | Out-Null }
        "tree:$Project/$RunId"
    }

    function New-RequestedRun([string]$RunId, [string]$Project = $script:Project) {
        $lane = New-RegisteredRun $RunId $Project
        Assert-Store 'request' @('--run-id', $RunId, '--started-by', 'human-command', '--request-id', "req-$RunId") | Out-Null
        $lane
    }

    # accept with a launcher identity (dead unless given), the real session, a dispatch id.
    function New-FixtureAccepted([string]$RunId, [string]$Project = $script:Project, $Launcher = $null, [string]$BootId = $script:BootId) {
        $lane = New-RequestedRun $RunId $Project
        if ($null -eq $Launcher) { $Launcher = New-DeadIdentity }
        Assert-Store 'accept' @('--run-id', $RunId, '--launcher-pid', $Launcher.Pid, '--launcher-created', $Launcher.Created,
            '--boot-id', $BootId, '--win-session', $script:WinSession, '--attempt-id', "att-$RunId", '--dispatch-id', "disp-$RunId") | Out-Null
        $lane
    }

    function New-FixtureAdmitted([string]$RunId, [string]$Project = $script:Project, $Launcher = $null, [string]$BootId = $script:BootId) {
        $lane = New-FixtureAccepted $RunId $Project $Launcher $BootId
        Assert-Store 'admit' @('--attempt-id', "att-$RunId", '--segment-id', "seg-$RunId") | Out-Null
        $lane
    }

    # A running segment with no process: the launcher and the CLI identities are dead unless given.
    function New-FixtureRunning([string]$RunId, [string]$Project = $script:Project, $Launcher = $null, $Cli = $null, [string]$BootId = $script:BootId) {
        $lane = New-FixtureAdmitted $RunId $Project $Launcher $BootId
        if ($null -eq $Cli) { $Cli = New-DeadIdentity }
        Assert-Store 'launched' @('--segment-id', "seg-$RunId", '--pid', $Cli.Pid, '--created', $Cli.Created, '--boot-id', $BootId) | Out-Null
        $lane
    }

    # The dispatch artifacts of a run: name → text under <OutputDir>/disp-<run>/.
    function Write-Dispatch([string]$RunId, [hashtable]$Files) {
        $dir = "$script:Out/disp-$RunId"
        New-Item -ItemType Directory -Force -Path $dir | Out-Null
        foreach ($name in $Files.Keys) { Set-Content -LiteralPath (Join-Path $dir $name) -Value $Files[$name] -Encoding utf8NoBOM -NoNewline }
    }

    function Get-Payload([string]$Text) {
        $last = @("$Text" -split "`r?`n" | Where-Object { $_.TrimStart().StartsWith('{') }) | Select-Object -Last 1
        if (-not $last) { return $null }
        try { $last | ConvertFrom-Json -ErrorAction Stop } catch { $null }
    }

    # A notifier that records each notice. Get-Sent reads what it recorded.
    function New-Notifier([switch]$Fail) {
        $sent = [System.Collections.Generic.List[object]]::new()
        $script:LastSent = $sent
        if ($Fail) { return { param($notice) $sent.Add($notice); throw 'the notice send failed' }.GetNewClosure() }
        { param($notice) $sent.Add($notice) }.GetNewClosure()
    }
    function Get-SentFor($Sent, [string]$Key) { @($Sent | Where-Object { "$($_.subject)" -like "*$Key*" }) }

    # One monitor pass in this process. Returns Code, Payload and Thrown.
    function Invoke-Watch {
        param([hashtable]$Observations = @{}, $NowUtc = $null, [scriptblock]$Notifier = $null, [object[]]$HostEvents = @())
        if (-not (Test-Path -LiteralPath $script:Watch)) { throw "the monitor is missing: $script:Watch" }
        if ($null -eq $Notifier) { $Notifier = New-Notifier }
        $splat = @{ StateDb = $script:Db; OutputDir = $script:Out; Observations = $Observations; Notifier = $Notifier; HostEvents = $HostEvents }
        if ($null -ne $NowUtc) { $splat.NowUtc = $NowUtc }
        $global:LASTEXITCODE = 0
        $lines = @(); $thrown = $null
        try { $lines = @(& $script:Watch @splat 2>$null) } catch { $thrown = $_.Exception.Message }
        $code = $global:LASTEXITCODE
        [pscustomobject]@{ Code = $code; Payload = (Get-Payload (($lines | ForEach-Object { "$_" }) -join "`n")); Thrown = $thrown }
    }

    function Assert-Pass($Result) {
        $Result.Thrown | Should -BeNullOrEmpty
        $Result.Code | Should -Be 0
        $Result.Payload.outcome | Should -Be 'pass'
    }

    # A plan tree whose closeout passes the completion-preflight check (R§5.2 done evidence).
    function New-DoneTree([string]$Tree, [switch]$NoReview) {
        $plan = Join-Path $Tree $script:PlanFolder
        $handoffs = Join-Path $Tree '.agent/context/handoffs'
        $reflections = Join-Path $Tree 'docs/execution/reflections'
        New-Item -ItemType Directory -Force -Path $plan, $handoffs, $reflections | Out-Null
        Set-Content -LiteralPath (Join-Path $plan 'task.md') -Encoding utf8NoBOM -Value (@(
                '---', "project: `"$script:Plan`"", 'status: "done"', 'stop_gate: "released:done"', 'meus: []', '---', '',
                '# Task', '', '| # | Task | Owner | Deliverable | Status |', '|---|------|-------|-------------|--------|',
                '| 1 | Write the tests | coder | tests | [x] |', '| 2 | Make them pass | coder | code | [x] |') -join "`n")
        Set-Content -LiteralPath (Join-Path $plan 'implementation-plan.md') -Encoding utf8NoBOM -Value "# Plan`n`nThe fixture plan."
        if (-not $NoReview) {
            Set-Content -LiteralPath (Join-Path $handoffs "$script:Plan-implementation-critical-review.md") -Encoding utf8NoBOM -Value (@(
                    '---', 'verdict: "approved"', 'findings_count: 0', '---', '', '# Implementation critical review', '',
                    '| Finding | Severity |', '|---------|----------|', '| none | - |', '', 'verdict: approved', 'findings_count: 0') -join "`n")
        }
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
    function Set-Landings([string]$RunId, [switch]$NoSeal) {
        Set-Rows 'INSERT INTO landings (run_id, part, path, blob, sealed_utc) VALUES (?, ?, ?, ?, NULL)' @($RunId, 'product', 'tools/fixture.py', 'blob-product')
        if (-not $NoSeal) {
            Set-Rows 'INSERT INTO landings (run_id, part, path, blob, sealed_utc) VALUES (?, ?, ?, ?, ?)' @($RunId, 'closeout', ".agent/context/handoffs/$script:Plan-handoff.md", 'blob-closeout', (Get-UtcText (Get-Date)))
        }
    }

    function Get-LauncherArgs([string]$RunId) {
        @('-RunId', $RunId, '-StateDb', $script:Db, '-OutputDir', $script:Out, '-KeyFile', $script:KeyFile,
            '-RunGate', $script:GatePy, '-Receipt', $script:Receipt,
            '-LaunchWaitMs', '60000', '-TerminateWaitMs', '5000', '-CancelPollMs', '1000')
    }
}

AfterAll {
    foreach ($id in $script:Kids) {
        if (Get-Process -Id $id -ErrorAction SilentlyContinue) { & taskkill.exe /PID $id /T /F *> $null }
    }
    $env:CREDITS_TEST_EFFECT_LOG = $script:SavedEffectLog
    if ($script:Root -and (Test-Path -LiteralPath $script:Root)) { Remove-Item -LiteralPath $script:Root -Recurse -Force -ErrorAction SilentlyContinue }
}

Describe 'AC-E.1: the monitor_lease' {
    It 'AC-E.1: a pass takes the lease and gives it back → two passes in a row both run' {
        New-Store | Out-Null
        Assert-Pass (Invoke-Watch)
        Assert-Pass (Invoke-Watch)
    }

    It 'AC-E.1 negative: a live holder has the lease → lease_held, exit 0, no store write, a rescan.request file' {
        $dir = New-Store
        $run = New-Id 'e1-held'
        New-RequestedRun $run | Out-Null
        $holder = New-LiveIdentity
        Assert-Store 'lease' @('--pid', $holder.Pid, '--created', $holder.Created, '--boot-id', $script:BootId) | Out-Null
        $before = Get-Transitions
        Test-Path -LiteralPath (Join-Path $dir 'rescan.request') | Should -BeFalse
        $res = Invoke-Watch -NowUtc (Get-Date).AddSeconds(200)
        $res.Thrown | Should -BeNullOrEmpty
        $res.Code | Should -Be 0
        $res.Payload.outcome | Should -Be 'lease_held'
        Get-Transitions | Should -Be $before
        (@(Get-Rows 'SELECT * FROM requests WHERE request_id = ?' @("req-$run")) | Select-Object -First 1).state | Should -Be 'pending'
        Get-Count 'SELECT COUNT(*) AS n FROM notices' | Should -Be 0
        Test-Path -LiteralPath (Join-Path $dir 'rescan.request') | Should -BeTrue
    }

    It 'AC-E.1: a dead holder → the pass takes the lease over and runs' {
        New-Store | Out-Null
        $run = New-Id 'e1-dead'
        New-RequestedRun $run | Out-Null
        $holder = New-DeadIdentity
        Assert-Store 'lease' @('--pid', $holder.Pid, '--created', $holder.Created, '--boot-id', $script:BootId) | Out-Null
        Assert-Pass (Invoke-Watch -NowUtc (Get-Date).AddSeconds(200))
        (@(Get-Rows 'SELECT * FROM requests WHERE request_id = ?' @("req-$run")) | Select-Object -First 1).state | Should -Be 'not_started'
    }
}

Describe 'AC-E.1: classification (R§5.1 signals, R§5.2 classes)' {
    It 'AC-E.1: a live launcher → the segment stays running and gets last_alive_utc; nothing is finalized' {
        New-Store | Out-Null
        $run = New-Id 'e1-live'
        $launcher = New-LiveIdentity
        $cli = New-LiveIdentity
        $lane = New-FixtureRunning $run -Launcher $launcher -Cli $cli
        Assert-Pass (Invoke-Watch)
        $seg = Get-Segment $run
        $seg.finalized_utc | Should -BeNullOrEmpty
        $seg.last_alive_utc | Should -Not -BeNullOrEmpty
        (Get-Run $run).state | Should -Be 'running'
        Get-LaneHolder $lane | Should -Be "seg-$run"
    }

    It 'AC-E.1: a dead launcher, the job gone → finalized by the monitor; no result and no host event → death_unknown, one notice' {
        New-Store | Out-Null
        $run = New-Id 'e1-death'
        $lane = New-FixtureRunning $run
        Assert-Pass (Invoke-Watch)
        Assert-Pass (Invoke-Watch)
        $seg = Get-Segment $run
        $seg.finalized_by | Should -Be 'monitor'
        Get-LaneHolder $lane | Should -BeNullOrEmpty
        $state = Get-Run $run
        $state.state | Should -Be 'stopped'
        $state.stop_class | Should -Be 'death_unknown'
        @(Get-Rows 'SELECT * FROM notices WHERE run_id = ? AND body_json LIKE ?' @($run, '%death_unknown%')).Count | Should -Be 1
    }

    It 'AC-E.1: output.json subtype error_max_budget_usd → budget_cap' {
        New-Store | Out-Null
        $run = New-Id 'e1-budget'
        New-FixtureRunning $run | Out-Null
        Write-Dispatch $run @{
            'status.json' = '{"exit_code": 1, "timed_out": false, "total_cost_usd": 4.01}'
            'output.json' = '{"type": "result", "subtype": "error_max_budget_usd", "is_error": true, "total_cost_usd": 4.01}'
        }
        Assert-Pass (Invoke-Watch)
        Assert-Pass (Invoke-Watch)
        $state = Get-Run $run
        $state.state | Should -Be 'stopped'
        $state.stop_class | Should -Be 'budget_cap'
        $state.stop_class | Should -BeIn $script:StopClasses
    }

    It 'AC-E.1: stderr "Credit balance is too low" → billing' {
        New-Store | Out-Null
        $run = New-Id 'e1-billing'
        New-FixtureRunning $run | Out-Null
        Write-Dispatch $run @{
            'status.json' = '{"exit_code": 1, "timed_out": false}'
            'stderr.txt'  = 'Credit balance is too low'
        }
        Assert-Pass (Invoke-Watch)
        Assert-Pass (Invoke-Watch)
        (Get-Run $run).stop_class | Should -Be 'billing'
    }

    It 'AC-E.1: the segment boot id is not this boot → reboot' {
        New-Store | Out-Null
        $run = New-Id 'e1-reboot'
        $lane = New-FixtureRunning $run -BootId 'bootid:fixture-old'
        Assert-Pass (Invoke-Watch)
        Assert-Pass (Invoke-Watch)
        (Get-Segment $run).finalized_by | Should -Be 'monitor'
        Get-LaneHolder $lane | Should -BeNullOrEmpty
        $state = Get-Run $run
        $state.state | Should -Be 'stopped'
        $state.stop_class | Should -Be 'reboot'
    }

    It 'AC-E.1: Kernel-Power 42 inside the interval and a dead pid → sleep_death' {
        New-Store | Out-Null
        $run = New-Id 'e1-sleep'
        New-FixtureRunning $run | Out-Null
        $now = (Get-Date).AddSeconds(60)
        $events = @([pscustomobject]@{ Id = 42; ProviderName = 'Microsoft-Windows-Kernel-Power'; TimeCreated = (Get-Date).AddSeconds(30) })
        Assert-Pass (Invoke-Watch -NowUtc $now -HostEvents $events)
        Assert-Pass (Invoke-Watch -NowUtc $now.AddSeconds(30) -HostEvents $events)
        (Get-Run $run).stop_class | Should -Be 'sleep_death'
    }

    It 'AC-E.1 negative: a host event outside the interval is not used → death_unknown' {
        New-Store | Out-Null
        $run = New-Id 'e1-outside'
        New-FixtureRunning $run | Out-Null
        $events = @([pscustomobject]@{ Id = 42; ProviderName = 'Microsoft-Windows-Kernel-Power'; TimeCreated = (Get-Date).AddHours(-1) })
        Assert-Pass (Invoke-Watch -HostEvents $events)
        Assert-Pass (Invoke-Watch -HostEvents $events)
        (Get-Run $run).stop_class | Should -Be 'death_unknown'
    }

    It 'AC-E.1 negative: signals that match no class (exit 0, a Status that is not R§7.3 grammar, no armed task.md) → unknown' {
        New-Store | Out-Null
        $run = New-Id 'e1-unknown'
        New-FixtureRunning $run | Out-Null
        Write-Dispatch $run @{
            'status.json' = '{"exit_code": 0, "timed_out": false, "total_cost_usd": 0.5}'
            'output.json' = '{"type": "result", "subtype": "success", "is_error": false, "total_cost_usd": 0.5}'
            'final.md'    = "All rows closed.`n`nStatus: done (all rows)`n"
        }
        Assert-Pass (Invoke-Watch)
        Assert-Pass (Invoke-Watch)
        $state = Get-Run $run
        $state.state | Should -Be 'stopped'
        $state.stop_class | Should -Be 'unknown'
    }

    It 'AC-E.3 negative: a third pass on the classified store adds no transition and no notice' {
        New-Store | Out-Null
        $run = New-Id 'e3-idem'
        New-FixtureRunning $run | Out-Null
        Assert-Pass (Invoke-Watch)
        Assert-Pass (Invoke-Watch)
        $transitions = Get-Transitions
        $notices = Get-Count 'SELECT COUNT(*) AS n FROM notices'
        Assert-Pass (Invoke-Watch)
        Get-Transitions | Should -Be $transitions
        Get-Count 'SELECT COUNT(*) AS n FROM notices' | Should -Be $notices
    }
}

Describe 'AC-E.2: done only on the completion evidence (MX-25)' {
    It 'AC-E.2: Status DONE, the preflight passes, the capture and the seal → done' {
        New-Store | Out-Null
        $run = New-Id 'e2-done'
        $tree = "$script:Root/tree-$run"
        New-DoneTree $tree
        New-FixtureRunning $run $tree | Out-Null
        Set-Landings $run
        Write-Dispatch $run @{
            'status.json' = '{"exit_code": 0, "timed_out": false, "total_cost_usd": 1.0}'
            'output.json' = '{"type": "result", "subtype": "success", "is_error": false, "total_cost_usd": 1.0}'
            'final.md'    = "Closeout complete.`n`nStatus: DONE`n"
        }
        Assert-Pass (Invoke-Watch)
        Assert-Pass (Invoke-Watch)
        (Get-Run $run).state | Should -Be 'done'
    }

    It 'mx_25_ AC-E.2 negative: Status DONE with no approved review → done_unverified; the notice names approved_verdict' {
        New-Store | Out-Null
        $run = New-Id 'e2-noreview'
        $tree = "$script:Root/tree-$run"
        New-DoneTree $tree -NoReview
        New-FixtureRunning $run $tree | Out-Null
        Set-Landings $run
        Write-Dispatch $run @{
            'status.json' = '{"exit_code": 0, "timed_out": false, "total_cost_usd": 1.0}'
            'final.md'    = "Closeout complete.`n`nStatus: DONE`n"
        }
        Assert-Pass (Invoke-Watch)
        Assert-Pass (Invoke-Watch)
        (Get-Run $run).state | Should -Be 'done_unverified'
        @(Get-Rows 'SELECT * FROM notices WHERE run_id = ? AND body_json LIKE ?' @($run, '%approved_verdict%')).Count | Should -Be 1
    }

    It 'mx_25_ AC-E.2 negative: an exec run with Status DONE and no closeout seal → done_unverified' {
        New-Store | Out-Null
        $run = New-Id 'e2-noseal'
        $tree = "$script:Root/tree-$run"
        New-DoneTree $tree
        New-FixtureRunning $run $tree | Out-Null
        Set-Landings $run -NoSeal
        Write-Dispatch $run @{
            'status.json' = '{"exit_code": 0, "timed_out": false, "total_cost_usd": 1.0}'
            'final.md'    = "Closeout complete.`n`nStatus: DONE`n"
        }
        Assert-Pass (Invoke-Watch)
        Assert-Pass (Invoke-Watch)
        (Get-Run $run).state | Should -Be 'done_unverified'
    }
}

Describe 'AC-E.3: the scans' {
    It 'mx_16_ AC-E.3: a request older than ORPHAN_REQUEST_S → not_started (orphan), the run back to registered, one notice, one credits_limit_tripped WARN, nothing started' {
        New-Store | Out-Null
        $run = New-Id 'mx16'
        New-RequestedRun $run | Out-Null
        Assert-Pass (Invoke-Watch -NowUtc (Get-Date).AddSeconds(200))
        $request = @(Get-Rows 'SELECT * FROM requests WHERE request_id = ?' @("req-$run")) | Select-Object -First 1
        $request.state | Should -Be 'not_started'
        $request.reason | Should -Be 'orphan'
        (Get-Run $run).state | Should -Be 'registered'
        @(Get-Notices "request_not_started:req-$run").Count | Should -Be 1
        @(Get-MonitorLog | Where-Object { $_.level -eq 'WARN' -and $_.event -eq 'credits_limit_tripped' }).Count | Should -Be 1
        Get-Count 'SELECT COUNT(*) AS n FROM attempts WHERE run_id = ?' @($run) | Should -Be 0
        $transitions = Get-Transitions
        Assert-Pass (Invoke-Watch -NowUtc (Get-Date).AddSeconds(260))
        Get-Transitions | Should -Be $transitions
        @(Get-MonitorLog | Where-Object { $_.level -eq 'WARN' -and $_.event -eq 'credits_limit_tripped' }).Count | Should -Be 1
    }

    It 'mx_16_ AC-E.3 negative: a request younger than ORPHAN_REQUEST_S stays pending' {
        New-Store | Out-Null
        $run = New-Id 'mx16-young'
        New-RequestedRun $run | Out-Null
        Assert-Pass (Invoke-Watch -NowUtc (Get-Date).AddSeconds(100))
        (@(Get-Rows 'SELECT * FROM requests WHERE request_id = ?' @("req-$run")) | Select-Object -First 1).state | Should -Be 'pending'
    }

    It 'mx_4_ AC-E.3: an accepted attempt with a dead launcher → the attempt and the request launch_failed, no segment' {
        New-Store | Out-Null
        $run = New-Id 'mx4'
        New-FixtureAccepted $run | Out-Null
        Assert-Pass (Invoke-Watch)
        (@(Get-Rows 'SELECT * FROM attempts WHERE attempt_id = ?' @("att-$run")) | Select-Object -First 1).state | Should -Be 'launch_failed'
        (@(Get-Rows 'SELECT * FROM requests WHERE request_id = ?' @("req-$run")) | Select-Object -First 1).state | Should -Be 'launch_failed'
        Get-Count 'SELECT COUNT(*) AS n FROM segments WHERE run_id = ?' @($run) | Should -Be 0
        (Get-Run $run).stop_class | Should -Be 'launch_failed'
        $transitions = Get-Transitions
        Assert-Pass (Invoke-Watch)
        Get-Transitions | Should -Be $transitions
    }

    It 'mx_4_ AC-E.3 negative: an accepted attempt with a live launcher stays accepted' {
        New-Store | Out-Null
        $run = New-Id 'mx4-live'
        New-FixtureAccepted $run -Launcher (New-LiveIdentity) | Out-Null
        Assert-Pass (Invoke-Watch)
        (@(Get-Rows 'SELECT * FROM attempts WHERE attempt_id = ?' @("att-$run")) | Select-Object -First 1).state | Should -Be 'accepted'
    }

    It 'mx_3_ AC-E.3: an admitted attempt with a dead launcher → the job proof, launch_failed; the reservation and the lane released once' {
        New-Store | Out-Null
        $run = New-Id 'mx3'
        $lane = New-FixtureAdmitted $run
        Assert-Pass (Invoke-Watch)
        Assert-Pass (Invoke-Watch)
        $seg = Get-Segment $run
        $seg.stop_class | Should -Be 'launch_failed'
        $seg.finalized_by | Should -Be 'monitor'
        $seg.reservation_released_utc | Should -Not -BeNullOrEmpty
        Get-LaneHolder $lane | Should -BeNullOrEmpty
        Get-Count "SELECT COUNT(*) AS n FROM transitions WHERE entity = 'segment' AND entity_id = ? AND to_state = 'finalized'" @("seg-$run") | Should -Be 1
        (Get-Run $run).stop_class | Should -Be 'launch_failed'
    }

    It 'mx_30_ AC-E.3: an access error on the job (P-8b g) → unknown: not finalized, the lane held, one job_proof_unknown notice sent once over two passes' {
        New-Store | Out-Null
        $run = New-Id 'mx30'
        $lane = New-FixtureRunning $run
        $notifier = New-Notifier
        $sent = $script:LastSent
        $obs = @{ "seg-$run" = @{ open_error = 5 } }
        Assert-Pass (Invoke-Watch -Observations $obs -Notifier $notifier)
        Assert-Pass (Invoke-Watch -Observations $obs -Notifier $notifier)
        $seg = Get-Segment $run
        $seg.finalized_utc | Should -BeNullOrEmpty
        Get-LaneHolder $lane | Should -Be "seg-$run"
        @(Get-Notices "job_proof_unknown:seg-$run").Count | Should -Be 1
        @(Get-SentFor $sent "job_proof_unknown:seg-$run").Count | Should -Be 1
        (Get-Run $run).state | Should -Be 'running'
    }

    It 'mx_34_ AC-E.3: a run in registering for more than 10 min → one registration_incomplete notice over two passes' {
        New-Store | Out-Null
        $run = New-Id 'mx34'
        New-RegisteredRun $run -NoRegistered | Out-Null
        Assert-Pass (Invoke-Watch -NowUtc (Get-Date).AddMinutes(11))
        Assert-Pass (Invoke-Watch -NowUtc (Get-Date).AddMinutes(12))
        @(Get-Notices "registration_incomplete:$run").Count | Should -Be 1
        (Get-Run $run).state | Should -Be 'registering'
    }

    It 'mx_43_ AC-E.3: the wrapper dies after register_minimal → the next pass reads gone with the wrapper identity and finalizes' {
        New-Store | Out-Null
        $run = New-Id 'mx43'
        $seg = "seg-$run"
        $wrapper = New-DeadIdentity
        Assert-Store 'register_minimal' @('--run-id', $run, '--segment-id', $seg, '--wrapper-pid', $wrapper.Pid, '--wrapper-created', $wrapper.Created,
            '--boot-id', $script:BootId, '--win-session', $script:WinSession, '--job-name', (Get-CreditsJobName -SegmentId $seg),
            '--expected-session-id', '00000000-0000-4000-8000-0000000000bb') | Out-Null
        Assert-Pass (Invoke-Watch)
        $row = Get-Segment $run
        $row.finalized_by | Should -Be 'monitor'
        $row.finalized_utc | Should -Not -BeNullOrEmpty
    }

    It 'mx_35_ AC-E.3: a message-enabled manual wrapper dies after manual_identity → finalized on the job proof' {
        New-Store | Out-Null
        $run = New-Id 'mx35'
        $seg = "seg-$run"
        $wrapper = New-DeadIdentity
        $child = New-DeadIdentity
        Assert-Store 'register_minimal' @('--run-id', $run, '--segment-id', $seg, '--wrapper-pid', $wrapper.Pid, '--wrapper-created', $wrapper.Created,
            '--boot-id', $script:BootId, '--win-session', $script:WinSession, '--job-name', (Get-CreditsJobName -SegmentId $seg),
            '--expected-session-id', '00000000-0000-4000-8000-0000000000cc') | Out-Null
        Assert-Store 'manual_identity' @('--segment-id', $seg, '--pid', $child.Pid, '--created', $child.Created) | Out-Null
        Assert-Pass (Invoke-Watch)
        (Get-Segment $run).finalized_by | Should -Be 'monitor'
    }

    It 'mx_35_ AC-E.5: a manual segment without a job → the manual proof: a live child → held, manual_child_alive once; the child ends → finalized' {
        New-Store | Out-Null
        $run = New-Id 'mx35-nojob'
        $seg = "seg-$run"
        $child = New-LiveIdentity
        $now = Get-UtcText (Get-Date)
        Set-Rows "INSERT INTO runs (run_id, state, kind, supervision, created_utc, updated_utc) VALUES (?, 'running', 'manual', 'manual', ?, ?)" @($run, $now, $now)
        Set-Rows ("INSERT INTO segments (segment_id, run_id, supervision, job, reservation_usd, state, wrapper_pid, wrapper_created, pid, created," +
            " boot_id, win_session, created_utc, updated_utc) VALUES (?, ?, 'manual', 0, 0, 'running', ?, ?, ?, ?, ?, ?, ?, ?)") @(
            $seg, $run, $child.Pid, $child.Created, $child.Pid, $child.Created, $script:BootId, $script:WinSession, $now, $now)
        $notifier = New-Notifier
        $sent = $script:LastSent
        Assert-Pass (Invoke-Watch -Notifier $notifier)
        Assert-Pass (Invoke-Watch -Notifier $notifier)
        (Get-Segment $run).finalized_utc | Should -BeNullOrEmpty
        @(Get-Notices "manual_child_alive:$seg").Count | Should -Be 1
        @(Get-SentFor $sent "manual_child_alive:$seg").Count | Should -Be 1
        Stop-Process -Id $child.Pid -Force
        Wait-Until { -not (Test-Alive $child.Pid) } 30 | Should -BeTrue
        Assert-Pass (Invoke-Watch -Notifier $notifier)
        (Get-Segment $run).finalized_by | Should -Be 'monitor'
    }

    It 'mx_13_ AC-E.3: the outbox cursor: a decision event → one notice; a report event → no notice; the cursor moves; no repeat' {
        New-Store | Out-Null
        $run = New-Id 'mx13'
        New-RegisteredRun $run | Out-Null
        $now = Get-UtcText (Get-Date)
        Set-Rows "INSERT INTO outbox_events (run_id, kind, semantic_key, payload_json, created_utc) VALUES (?, 'decision', ?, ?, ?)" @(
            $run, "decision:$run:D-1", '{"decision_id": "D-1", "question": "Pick A or B?"}', $now)
        $notifier = New-Notifier
        $sent = $script:LastSent
        Assert-Pass (Invoke-Watch -Notifier $notifier)
        Get-Count 'SELECT COUNT(*) AS n FROM notices WHERE run_id = ?' @($run) | Should -Be 1
        $sent.Count | Should -Be 1
        $seq1 = Get-Count 'SELECT MAX(event_seq) AS n FROM outbox_events'
        Get-Count "SELECT CAST(value AS INTEGER) AS n FROM cursors WHERE name LIKE 'outbox%'" | Should -Be $seq1
        Set-Rows "INSERT INTO outbox_events (run_id, kind, semantic_key, payload_json, created_utc) VALUES (?, 'report', ?, ?, ?)" @(
            $run, "report:$run:1", '{"text": "row 3 done"}', $now)
        Assert-Pass (Invoke-Watch -Notifier $notifier)
        Assert-Pass (Invoke-Watch -Notifier $notifier)
        Get-Count 'SELECT COUNT(*) AS n FROM notices WHERE run_id = ?' @($run) | Should -Be 1
        $sent.Count | Should -Be 1
        $seq2 = Get-Count 'SELECT MAX(event_seq) AS n FROM outbox_events'
        Get-Count "SELECT CAST(value AS INTEGER) AS n FROM cursors WHERE name LIKE 'outbox%'" | Should -Be $seq2
    }
}

Describe 'AC-E.4: the monitor never resumes' {
    It 'AC-E.4 negative: a stopped run that meets every resume precondition → a notice only; no request, no message' {
        New-Store | Out-Null
        $run = New-Id 'e4-stopped'
        $lane = New-FixtureRunning $run
        Write-Dispatch $run @{
            'status.json' = '{"exit_code": 1, "timed_out": false}'
            'stderr.txt'  = 'API Error: 529 {"type":"error","error":{"type":"overloaded_error","message":"Overloaded"}}'
        }
        Assert-Pass (Invoke-Watch)
        Assert-Pass (Invoke-Watch)
        $state = Get-Run $run
        $state.state | Should -Be 'stopped'
        $state.stop_class | Should -Be 'transient_api'
        Get-LaneHolder $lane | Should -BeNullOrEmpty
        Assert-Pass (Invoke-Watch -NowUtc (Get-Date).AddHours(2))
        Get-Count 'SELECT COUNT(*) AS n FROM requests WHERE run_id = ?' @($run) | Should -Be 1
        Get-Count 'SELECT COUNT(*) AS n FROM messages' | Should -Be 0
        (Get-Run $run).state | Should -Be 'stopped'
        Get-Count 'SELECT COUNT(*) AS n FROM notices WHERE run_id = ?' @($run) | Should -BeGreaterOrEqual 1
    }
}

Describe 'AC-E.5: notices through the effects with retry (MX-22)' {
    It 'mx_22_ AC-E.5: a failed send → retry; the next pass sends it with the key in the subject; never again after it is sent' {
        New-Store | Out-Null
        $run = New-Id 'mx22'
        New-RequestedRun $run | Out-Null
        $key = "request_not_started:req-$run"
        $bad = New-Notifier -Fail
        $badSent = $script:LastSent
        Assert-Pass (Invoke-Watch -NowUtc (Get-Date).AddSeconds(200) -Notifier $bad)
        @(Get-SentFor $badSent $key).Count | Should -Be 1
        (Get-Notices $key | Select-Object -First 1).state | Should -Be 'retry'
        $good = New-Notifier
        $goodSent = $script:LastSent
        Assert-Pass (Invoke-Watch -NowUtc (Get-Date).AddSeconds(800) -Notifier $good)
        @(Get-SentFor $goodSent $key).Count | Should -Be 1
        (Get-Notices $key | Select-Object -First 1).state | Should -Be 'sent'
        Assert-Pass (Invoke-Watch -NowUtc (Get-Date).AddSeconds(1400) -Notifier $good)
        @(Get-SentFor $goodSent $key).Count | Should -Be 1
        @(Get-Notices $key).Count | Should -Be 1
    }
}

Describe 'AC-E.6: P-8b again through the monitor' {
    It 'AC-E.6 (b): the launcher alone is killed → the job closes and the CLI dies; the monitor finalizes (gone) and classifies' {
        New-Store | Out-Null
        $run = New-Id 'e6-b'
        $lane = New-RequestedRun $run
        $argv = "$script:Root/$run.argv.json"
        $child = Start-Child $script:Launcher (Get-LauncherArgs $run) -Env @{ MOCK_ARGV_FILE = $argv; MOCK_HANG_SECONDS = '120' } -NoWait
        Wait-Until { (Test-Path -LiteralPath $argv) -or $child.Process.HasExited } 90 | Should -BeTrue
        Test-Path -LiteralPath $argv | Should -BeTrue
        Start-Sleep -Milliseconds 300
        $mock = (Read-Json $argv).pid
        Stop-Process -Id $child.Process.Id -Force
        Wait-Until { -not (Test-Alive $mock) } 30 | Should -BeTrue
        Assert-Pass (Invoke-Watch)
        Assert-Pass (Invoke-Watch)
        $seg = Get-Segment $run
        $seg.finalized_by | Should -Be 'monitor'
        $seg.stop_class | Should -Be 'job_gone'
        Get-LaneHolder $lane | Should -BeNullOrEmpty
        (Get-Run $run).stop_class | Should -BeIn $script:StopClasses
    }

    It 'AC-E.6 (c): the whole tree is killed → the monitor finalizes and classifies' {
        New-Store | Out-Null
        $run = New-Id 'e6-c'
        $lane = New-RequestedRun $run
        $argv = "$script:Root/$run.argv.json"
        $child = Start-Child $script:Launcher (Get-LauncherArgs $run) -Env @{ MOCK_ARGV_FILE = $argv; MOCK_HANG_SECONDS = '120' } -NoWait
        Wait-Until { (Test-Path -LiteralPath $argv) -or $child.Process.HasExited } 90 | Should -BeTrue
        Test-Path -LiteralPath $argv | Should -BeTrue
        Start-Sleep -Milliseconds 300
        $mock = (Read-Json $argv).pid
        & taskkill.exe /PID $child.Process.Id /T /F *> $null
        Wait-Until { -not (Test-Alive $mock) } 30 | Should -BeTrue
        Assert-Pass (Invoke-Watch)
        Assert-Pass (Invoke-Watch)
        $seg = Get-Segment $run
        $seg.finalized_by | Should -Be 'monitor'
        Get-LaneHolder $lane | Should -BeNullOrEmpty
        $state = Get-Run $run
        $state.state | Should -Be 'stopped'
        $state.stop_class | Should -BeIn $script:StopClasses
    }

    It 'AC-E.6 (f) negative: the launcher is dead and the job is live → the first pass terminates the job and does not finalize; a later pass finalizes' {
        New-Store | Out-Null
        $run = New-Id 'e6-f'
        $seg = "seg-$run"
        $lane = New-FixtureRunning $run
        $job = New-CreditsJob -SegmentId $seg
        try {
            $member = Start-CreditsJobProcess -Job $job -FilePath $script:BasePython -CommandLine '-c "import time; time.sleep(120)"' -WorkingDirectory $script:Root
            $script:Kids.Add([int]$member.ProcessId)
            Resume-CreditsJobProcess -Child $member
            # The job holds the sleeper and, for a console child, its conhost.
            Get-CreditsJobActiveCount -Job $job | Should -BeGreaterOrEqual 1
            Assert-Pass (Invoke-Watch)
            (Get-Segment $run).finalized_utc | Should -BeNullOrEmpty
            Get-LaneHolder $lane | Should -Be $seg
            Wait-Until { -not (Test-Alive ([int]$member.ProcessId)) } 30 | Should -BeTrue -Because 'the monitor terminates the live job'
            Assert-Pass (Invoke-Watch)
            $after = Get-Segment $run
            $after.finalized_by | Should -Be 'monitor'
            $after.stop_class | Should -Be 'job_empty'
            Get-LaneHolder $lane | Should -BeNullOrEmpty
        } finally {
            Close-CreditsJob -Job $job
        }
    }
}
