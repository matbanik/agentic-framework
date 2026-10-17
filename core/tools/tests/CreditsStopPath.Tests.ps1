# S2 stop path (Component D of docs/execution/plans/2026-10-15-scheduled-credits-runs).
# AC-D.4 Stop-CreditsRun.ps1 sets cancel_requested_utc (through the store cancel verb); the
# launcher terminates the job and writes cancelled (MX-7). A cancel of a run in a final state is
# no_change.
# AC-D.5 the P-8b cases (a) to (g) go through the S2a test driver: Get-CreditsJobProof (with an
# -Observation where the host cannot make the case) and then the store scan_segments verb:
#   (a) cancel                        → the launcher ends the tree and finalizes cancelled (MX-7)
#   (b) the launcher is killed        → the job closes, the tree dies; the driver finalizes (gone)
#   (c) the whole tree is killed      → the driver finalizes (empty)
#   (d) the job is refused            → launch_failed
#   (e) no running.json, a descendant survives the terminate → termination_pending (MX-20)
#   (f) the driver sees live, then empty → no finalize, then finalized by the monitor
#   (g) the job cannot be opened (access error) → unknown, lane held, job_proof_unknown (MX-30)
#
# The mock CLI, the fake key, the store, the receipt and the gate are temp files. Each child gets
# its own environment block without CLAUDECODE and CLAUDE_CODE_ENTRYPOINT.

BeforeAll {
    $script:Repo = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
    $script:Skill = Join-Path $script:Repo '.agent/skills/claude-credits'
    $script:Launcher = Join-Path $script:Skill 'Start-CreditsRun.ps1'
    $script:Stop = Join-Path $script:Skill 'Stop-CreditsRun.ps1'
    $script:Module = Join-Path $script:Skill 'CreditsRun.psm1'
    $script:StateTool = Join-Path $script:Repo 'tools/credits_state.py'
    $script:Root = "{{RECEIPTS_DIR}}/credits-stoppath-tests/$([guid]::NewGuid().ToString('N'))"
    $script:Out = "$script:Root/dispatch"
    $script:Project = "$script:Root/project"
    New-Item -ItemType Directory -Force -Path $script:Out, $script:Project | Out-Null
    $script:EffectLog = "$script:Root/effects.jsonl"
    $script:SavedEffectLog = $env:CREDITS_TEST_EFFECT_LOG
    $env:CREDITS_TEST_EFFECT_LOG = $script:EffectLog
    $script:Db = "$script:Root/store/state.db"
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $script:Db) | Out-Null
    $script:Kids = [System.Collections.Generic.List[int]]::new()

    $script:KeyFile = "$script:Root/fake.key"
    Set-Content -LiteralPath $script:KeyFile -Value ('sk-' + 'ant-api03-' + ('A' * 40)) -Encoding utf8NoBOM
    $script:Brief = "$script:Root/brief.md"
    Set-Content -LiteralPath $script:Brief -Value 'credits stop-path test brief' -Encoding utf8NoBOM

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
log = os.environ.get("MOCK_CALL_LOG")
if log:
    with open(log, "a", encoding="utf-8") as f:
        f.write(json.dumps(args) + "\n")
argv_file = os.environ.get("MOCK_ARGV_FILE")
if argv_file:
    with open(argv_file, "w", encoding="utf-8") as f:
        json.dump({"argv": args, "pid": os.getpid(), "ppid": os.getppid()}, f)
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

    # A wrapper stand-in for case (e): it starts a sleeper (a descendant in the job) and never
    # writes running.json, so the launcher never learns the CLI pid.
    $script:SleeperPid = "$script:Root/sleeper.pid"
    $script:FakeWrapper = "$script:Root/fake_wrapper.ps1"
    Set-Content -LiteralPath $script:FakeWrapper -Encoding utf8NoBOM -Value @"
`$p = Start-Process -FilePath '$script:BasePython' -ArgumentList @('-c', 'import time; time.sleep(120)') -PassThru -NoNewWindow
Set-Content -LiteralPath '$script:SleeperPid' -Value `$p.Id
Start-Sleep -Seconds 120
"@

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

    function Get-Rows([string]$Sql, [string[]]$Params = @()) {
        $code = 'import json, sqlite3, sys; c = sqlite3.connect("file:" + sys.argv[1] + "?mode=ro", uri=True); c.row_factory = sqlite3.Row; print(json.dumps([dict(r) for r in c.execute(sys.argv[2], sys.argv[3:])]))'
        @((& $script:Py -X utf8 -c $code $script:Db $Sql @Params | Out-String) | ConvertFrom-Json)
    }

    function Get-Run([string]$RunId) { @(Get-Rows 'SELECT * FROM runs WHERE run_id = ?' @($RunId)) | Select-Object -First 1 }
    function Get-Segment([string]$RunId) { @(Get-Rows 'SELECT * FROM segments WHERE run_id = ? ORDER BY created_utc, rowid' @($RunId)) | Select-Object -Last 1 }
    function Get-LaneHolder([string]$Lane) { (@(Get-Rows 'SELECT segment_id FROM lanes WHERE lane = ?' @($Lane)) | Select-Object -First 1).segment_id }

    function Import-CreditsRun {
        if (-not (Get-Module -Name CreditsRun)) { Import-Module -Name $script:Module -Force -DisableNameChecking -ErrorAction Stop }
    }

    function New-RegisteredRun([string]$RunId, [double]$SegmentCap = 20.0, [double]$RunCap = 50.0) {
        $doc = [ordered]@{
            schema = 'credits-run.v1'; run_id = $RunId; kind = 'exec'
            project_root = $script:Project; plan_folder = 'docs/execution/plans/2026-10-15-fixture/'
            brief = $script:Brief
            launch = [ordered]@{
                working_directory = $script:Project; claude_exe = $script:Mock; python_exe = $script:Py
                permission_mode = 'bypassPermissions'; effort = 'low'; segment_cap_usd = $SegmentCap; timeout_sec = 3600
            }
            budget = [ordered]@{ run_cap_usd = $RunCap }
            messaging = [ordered]@{ orchestrator_sessions = @('00000000-0000-4000-8000-0000000000aa'); ruling_enabled = $false; gate_wait_max_min = 0 }
            depends_on = @(); lane = "tree:$script:Project/$RunId"
        }
        $manifest = "$script:Root/manifest-$RunId.json"
        Set-Content -LiteralPath $manifest -Value ($doc | ConvertTo-Json -Depth 6) -Encoding utf8NoBOM
        Assert-Store 'register' @('--run-id', $RunId, '--manifest', $manifest, '--cli-version', '2.1.296', '--kit-revision', 'kitrev-fixture') | Out-Null
        Assert-Store 'registered' @('--run-id', $RunId, '--task-hash', "taskhash-$RunId") | Out-Null
        "tree:$script:Project/$RunId"
    }

    # A requested run, ready for the launcher. Returns the lane.
    function New-RequestedRun([string]$RunId) {
        $lane = New-RegisteredRun $RunId
        Assert-Store 'request' @('--run-id', $RunId, '--started-by', 'human-command', '--request-id', "req-$RunId") | Out-Null
        $lane
    }

    # A store-only running segment (no process): accept, admit, launched with a fixture pid.
    function New-FixtureRunning([string]$RunId) {
        $lane = New-RequestedRun $RunId
        Assert-Store 'accept' @('--run-id', $RunId, '--launcher-pid', '4242', '--launcher-created', (Get-UtcText (Get-Date).AddMinutes(-1)),
            '--boot-id', 'boot-fixture-1', '--win-session', '1', '--attempt-id', "att-$RunId") | Out-Null
        Assert-Store 'admit' @('--attempt-id', "att-$RunId", '--segment-id', "seg-$RunId") | Out-Null
        Assert-Store 'launched' @('--segment-id', "seg-$RunId", '--pid', '5151', '--created', (Get-UtcText (Get-Date)), '--boot-id', 'boot-fixture-1') | Out-Null
        $lane
    }

    function Get-LauncherArgs([string]$RunId, [string[]]$Extra = @()) {
        @('-RunId', $RunId, '-StateDb', $script:Db, '-OutputDir', $script:Out, '-KeyFile', $script:KeyFile,
            '-RunGate', $script:GatePy, '-Receipt', $script:Receipt,
            '-LaunchWaitMs', '60000', '-TerminateWaitMs', '5000', '-CancelPollMs', '1000') + $Extra
    }

    function Get-Payload([string]$Text) {
        $last = @("$Text" -split "`r?`n" | Where-Object { $_.TrimStart().StartsWith('{') }) | Select-Object -Last 1
        if (-not $last) { return $null }
        try { $last | ConvertFrom-Json -ErrorAction Stop } catch { $null }
    }

    # Run Stop-CreditsRun.ps1 in this process. Returns Code, Payload and Thrown.
    function Invoke-Stop([string]$RunId) {
        $global:LASTEXITCODE = 0
        $lines = @(); $thrown = $null
        try { $lines = @(& $script:Stop -RunId $RunId -StateDb $script:Db 2>$null) } catch { $thrown = $_.Exception.Message }
        $code = $global:LASTEXITCODE
        [pscustomobject]@{ Code = $code; Payload = (Get-Payload (($lines | ForEach-Object { "$_" }) -join "`n")); Thrown = $thrown }
    }

    # The S2a test driver: the job proof of one segment, then scan_segments with that proof.
    function Invoke-ProofDriver([string]$SegmentId, [hashtable]$Observation = @{}) {
        Import-CreditsRun
        $seg = @(Get-Rows 'SELECT * FROM segments WHERE segment_id = ?' @($SegmentId)) | Select-Object -First 1
        if ($null -eq $seg) { throw "no segment $SegmentId" }
        $procs = @(
            @{ pid = $seg.pid; created = $seg.created }
            @{ pid = $seg.launcher_pid; created = $seg.launcher_created }
        ) | Where-Object { $null -ne $_.pid }
        $proof = Get-CreditsJobProof -JobName (Get-CreditsJobName -SegmentId $SegmentId) -LauncherSession ([int]$seg.win_session) `
            -BootId ([string]$seg.boot_id) -Processes @($procs) -Observation $Observation
        $proofs = @{ $SegmentId = $proof.Result } | ConvertTo-Json -Compress
        Assert-Store 'scan_segments' @('--proofs-json', $proofs) | Out-Null
        $proof.Result
    }

    Assert-Store 'init' | Out-Null
}

AfterAll {
    foreach ($id in $script:Kids) {
        if (Get-Process -Id $id -ErrorAction SilentlyContinue) { & taskkill.exe /PID $id /T /F *> $null }
    }
    $env:CREDITS_TEST_EFFECT_LOG = $script:SavedEffectLog
    if ($script:Root -and (Test-Path -LiteralPath $script:Root)) { Remove-Item -LiteralPath $script:Root -Recurse -Force -ErrorAction SilentlyContinue }
}

Describe 'AC-D.4: Stop-CreditsRun marks the cancel through the store' {
    It 'AC-D.4: a requested run → changed, the run cancelled, the pending request not_started (cancelled), exit 0' {
        $run = New-Id 'd4-requested'
        New-RequestedRun $run | Out-Null
        $res = Invoke-Stop $run
        $res.Thrown | Should -BeNullOrEmpty
        $res.Code | Should -Be 0
        $res.Payload.result | Should -Be 'changed'
        (Get-Run $run).state | Should -Be 'cancelled'
        $request = @(Get-Rows 'SELECT * FROM requests WHERE request_id = ?' @("req-$run")) | Select-Object -First 1
        $request.state | Should -Be 'not_started'
        $request.reason | Should -Be 'cancelled'
    }

    It 'AC-D.4: a running segment gets cancel_requested_utc; the segment stays open for its launcher' {
        $run = New-Id 'd4-running'
        New-FixtureRunning $run | Out-Null
        $res = Invoke-Stop $run
        $res.Code | Should -Be 0
        $seg = Get-Segment $run
        $seg.cancel_requested_utc | Should -Not -BeNullOrEmpty
        $seg.finalized_utc | Should -BeNullOrEmpty
        (Get-Run $run).state | Should -Be 'cancelled'
    }

    It 'AC-D.4: a cancelled run → no_change, exit 0' {
        $run = New-Id 'd4-twice'
        New-RequestedRun $run | Out-Null
        (Invoke-Stop $run).Code | Should -Be 0
        $res = Invoke-Stop $run
        $res.Code | Should -Be 0
        $res.Payload.result | Should -Be 'no_change'
    }

    It 'AC-D.4: a run in another final state (failed) → no_change, exit 0, the state stays' {
        $run = New-Id 'd4-failed'
        New-RegisteredRun $run -SegmentCap 4.0 -RunCap 4.0 | Out-Null
        Assert-Store 'request' @('--run-id', $run, '--started-by', 'human-command') | Out-Null
        Assert-Store 'accept' @('--run-id', $run, '--launcher-pid', '4242', '--launcher-created', (Get-UtcText (Get-Date).AddMinutes(-1)),
            '--boot-id', 'boot-fixture-1', '--win-session', '1', '--attempt-id', "att-$run") | Out-Null
        Assert-Store 'admit' @('--attempt-id', "att-$run") | Out-Null
        (Get-Run $run).state | Should -Be 'failed'
        $res = Invoke-Stop $run
        $res.Code | Should -Be 0
        $res.Payload.result | Should -Be 'no_change'
        (Get-Run $run).state | Should -Be 'failed'
    }
}

Describe 'AC-D.5 P-8b (a): cancel ends the tree (MX-7)' {
    BeforeAll {
        $script:RunA = New-Id 'p8b-a'
        $script:LaneA = New-RequestedRun $script:RunA
        $script:ArgvA = "$script:Root/$script:RunA.argv.json"
        $script:ChildA = Start-Child $script:Launcher (Get-LauncherArgs $script:RunA) -Env @{ MOCK_ARGV_FILE = $script:ArgvA; MOCK_HANG_SECONDS = '120' } -NoWait
        $null = Wait-Until { (Test-Path -LiteralPath $script:ArgvA) -or $script:ChildA.Process.HasExited } 90
        $script:MockA = if (Test-Path -LiteralPath $script:ArgvA) { Start-Sleep -Milliseconds 300; (Read-Json $script:ArgvA).pid } else { $null }
    }

    It 'mx_7_ AC-D.5 (a): Stop-CreditsRun → the launcher ends the CLI and exits within 60 s' {
        $script:MockA | Should -Not -BeNullOrEmpty
        Test-Alive $script:MockA | Should -BeTrue
        (Invoke-Stop $script:RunA).Code | Should -Be 0
        $script:ChildA.Process.WaitForExit(60000) | Should -BeTrue
        Wait-Until { -not (Test-Alive $script:MockA) } 30 | Should -BeTrue
    }

    It 'mx_7_ AC-D.5 (a): the launcher finalized the segment cancelled; the run is cancelled; the lane is free' {
        $seg = Get-Segment $script:RunA
        $seg.finalized_by | Should -Be 'launcher'
        $seg.stop_class | Should -Be 'cancelled'
        $seg.reservation_released_utc | Should -Not -BeNullOrEmpty
        (Get-Run $script:RunA).state | Should -Be 'cancelled'
        Get-LaneHolder $script:LaneA | Should -BeNullOrEmpty
    }
}

Describe 'AC-D.5 P-8b (b) and (c): the launcher dies; the driver finalizes' {
    It 'AC-D.5 (b): the launcher alone is killed → the job closes and the CLI dies; the driver proof is gone → finalized by the monitor' {
        $run = New-Id 'p8b-b'
        $lane = New-RequestedRun $run
        $argv = "$script:Root/$run.argv.json"
        $child = Start-Child $script:Launcher (Get-LauncherArgs $run) -Env @{ MOCK_ARGV_FILE = $argv; MOCK_HANG_SECONDS = '120' } -NoWait
        Wait-Until { (Test-Path -LiteralPath $argv) -or $child.Process.HasExited } 90 | Should -BeTrue
        Test-Path -LiteralPath $argv | Should -BeTrue
        Start-Sleep -Milliseconds 300
        $mock = (Read-Json $argv).pid
        Stop-Process -Id $child.Process.Id -Force
        Wait-Until { -not (Test-Alive $mock) } 30 | Should -BeTrue -Because 'kill on close ends the tree when the launcher handle closes'
        $seg = Get-Segment $run
        $seg.finalized_utc | Should -BeNullOrEmpty
        Invoke-ProofDriver $seg.segment_id | Should -Be 'gone'
        $after = Get-Segment $run
        $after.finalized_by | Should -Be 'monitor'
        $after.stop_class | Should -Be 'job_gone'
        Get-LaneHolder $lane | Should -BeNullOrEmpty
    }

    It 'AC-D.5 (c): the whole tree is killed → the driver proof is empty → finalized by the monitor' {
        $run = New-Id 'p8b-c'
        $lane = New-RequestedRun $run
        $argv = "$script:Root/$run.argv.json"
        $child = Start-Child $script:Launcher (Get-LauncherArgs $run) -Env @{ MOCK_ARGV_FILE = $argv; MOCK_HANG_SECONDS = '120' } -NoWait
        Wait-Until { (Test-Path -LiteralPath $argv) -or $child.Process.HasExited } 90 | Should -BeTrue
        Test-Path -LiteralPath $argv | Should -BeTrue
        Start-Sleep -Milliseconds 300
        $mock = (Read-Json $argv).pid
        & taskkill.exe /PID $child.Process.Id /T /F *> $null
        Wait-Until { -not (Test-Alive $mock) } 30 | Should -BeTrue
        $seg = Get-Segment $run
        Invoke-ProofDriver $seg.segment_id @{ open_error = 0; active_processes = 0 } | Should -Be 'empty'
        $after = Get-Segment $run
        $after.finalized_by | Should -Be 'monitor'
        $after.stop_class | Should -Be 'job_empty'
        Get-LaneHolder $lane | Should -BeNullOrEmpty
    }
}

Describe 'AC-D.5 P-8b (d): the job is refused → launch_failed' {
    It 'AC-D.5 (d): CREDITS_TEST_JOB_FAIL=1 → the segment launch_failed by the launcher, the run failed, the lane free, no CLI call' {
        $run = New-Id 'p8b-d'
        $lane = New-RequestedRun $run
        $calls = "$script:Root/$run.calls.jsonl"
        $child = Start-Child $script:Launcher (Get-LauncherArgs $run) -Env @{ MOCK_CALL_LOG = $calls; CREDITS_TEST_JOB_FAIL = '1' }
        (Get-Payload $child.Out).outcome | Should -Be 'launch_failed'
        $seg = Get-Segment $run
        $seg | Should -Not -BeNullOrEmpty
        $seg.stop_class | Should -Be 'launch_failed'
        $seg.finalized_by | Should -Be 'launcher'
        (Get-Run $run).state | Should -Be 'failed'
        Get-LaneHolder $lane | Should -BeNullOrEmpty
        Test-Path -LiteralPath $calls | Should -BeFalse
    }
}

Describe 'AC-D.5 P-8b (e), (g) and (f): termination_pending, then the driver' {
    BeforeAll {
        $script:RunE = New-Id 'p8b-e'
        $script:LaneE = New-RequestedRun $script:RunE
        $script:ChildE = Start-Child $script:Launcher (Get-LauncherArgs $script:RunE @('-WrapperScript', $script:FakeWrapper, '-LaunchWaitMs', '3000')) `
            -Env @{ CREDITS_TEST_ACTIVE_PROCESSES = '1' }
    }

    It 'mx_20_ AC-D.5 (e): no running.json and a descendant after the terminate → termination_pending; the lane and the reservation are held' {
        (Get-Payload $script:ChildE.Out).outcome | Should -Be 'termination_pending'
        $seg = Get-Segment $script:RunE
        $seg | Should -Not -BeNullOrEmpty
        $seg.state | Should -Be 'termination_pending'
        $seg.finalized_utc | Should -BeNullOrEmpty
        $seg.reservation_released_utc | Should -BeNullOrEmpty
        Get-LaneHolder $script:LaneE | Should -Be $seg.segment_id
    }

    It 'mx_20_ AC-D.5 (e): the terminate ended the real descendant' {
        Test-Path -LiteralPath $script:SleeperPid | Should -BeTrue
        $sleeper = [int]([System.IO.File]::ReadAllText($script:SleeperPid).Trim())
        Wait-Until { -not (Test-Alive $sleeper) } 30 | Should -BeTrue
    }

    It 'mx_30_ AC-D.5 (g): an access error on the job → unknown; no finalize, the lane held, one job_proof_unknown notice' {
        $seg = Get-Segment $script:RunE
        Invoke-ProofDriver $seg.segment_id @{ open_error = 5 } | Should -Be 'unknown'
        $after = Get-Segment $script:RunE
        $after.finalized_utc | Should -BeNullOrEmpty
        Get-LaneHolder $script:LaneE | Should -Be $seg.segment_id
        @(Get-Rows "SELECT * FROM notices WHERE kind = 'job_proof_unknown' AND ref = ?" @($seg.segment_id)).Count | Should -Be 1
    }

    It 'AC-D.5 (f): the first driver pass sees live → no finalize; a later pass sees empty → finalized by the monitor, the lane free' {
        $seg = Get-Segment $script:RunE
        Invoke-ProofDriver $seg.segment_id @{ open_error = 0; active_processes = 1 } | Should -Be 'live'
        (Get-Segment $script:RunE).finalized_utc | Should -BeNullOrEmpty
        Get-LaneHolder $script:LaneE | Should -Be $seg.segment_id
        Invoke-ProofDriver $seg.segment_id @{ open_error = 0; active_processes = 0 } | Should -Be 'empty'
        $after = Get-Segment $script:RunE
        $after.finalized_by | Should -Be 'monitor'
        $after.stop_class | Should -Be 'job_empty'
        $after.reservation_released_utc | Should -Not -BeNullOrEmpty
        Get-LaneHolder $script:LaneE | Should -BeNullOrEmpty
    }
}
