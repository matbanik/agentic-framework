# R1-F2 (execution review round 1) of docs/execution/plans/2026-10-15-scheduled-credits-runs.
# project_root and launch.working_directory name one project (report section 4.1: the working
# directory is always the main tree). Register-CreditsRun.ps1 refuses a manifest whose two paths
# are different directories (project_mismatch), and Start-CreditsRun.ps1 refuses one again before
# it takes the request, so a mismatched run that reached the store some other way starts nothing
# and holds no lane. One directory written another way (a junction, another case, a trailing
# separator) is the same project.
#
# Every store, receipt, key and project is a temp file. The key file holds a fake key. The mock
# claude writes its argv to a log; the scheduler adapter is a fake.

BeforeAll {
    $script:Repo = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
    $script:Skill = Join-Path $script:Repo '.agent/skills/claude-credits'
    $script:Register = Join-Path $script:Skill 'Register-CreditsRun.ps1'
    $script:Launcher = Join-Path $script:Skill 'Start-CreditsRun.ps1'
    $script:StateTool = Join-Path $script:Repo 'tools/credits_state.py'
    $script:Root = "{{RECEIPTS_DIR}}/credits-r1-project-tests/$([guid]::NewGuid().ToString('N'))"
    $script:Project = "$script:Root/project-a"
    $script:Other = "$script:Root/project-b"
    $script:Link = "$script:Root/project-a-link"
    $script:Out = "$script:Root/dispatch"
    New-Item -ItemType Directory -Force -Path $script:Project, $script:Other, $script:Out | Out-Null
    New-Item -ItemType Junction -Path $script:Link -Target $script:Project | Out-Null
    $script:EffectLog = "$script:Root/effects.jsonl"
    $script:SavedEffectLog = $env:CREDITS_TEST_EFFECT_LOG
    $env:CREDITS_TEST_EFFECT_LOG = $script:EffectLog

    $venvPy = Join-Path $script:Repo '.venv/Scripts/python.exe'
    $script:Py = if (Test-Path -LiteralPath $venvPy) { $venvPy } else { (Get-Command python -ErrorAction Stop).Source }
    $script:BasePython = (& $script:Py -c 'import sys; print(sys._base_executable)' | Out-String).Trim()

    $script:KeyFile = "$script:Root/fake.key"
    Set-Content -LiteralPath $script:KeyFile -Value ('sk-' + 'ant-api03-' + ('A' * 40)) -Encoding utf8NoBOM
    $script:Brief = "$script:Root/brief.md"
    Set-Content -LiteralPath $script:Brief -Value 'credits r1 project test brief' -Encoding utf8NoBOM

    # The mock CLI: --version for registration; a session call is logged and answers one result.
    $mockPy = "$script:Root/mock_claude.py"
    Set-Content -LiteralPath $mockPy -Encoding utf8NoBOM -Value @'
import json
import os
import sys

args = sys.argv[1:]
if "--version" in args:
    print("2.1.296 (Claude Code)")
    sys.exit(0)
sys.stdin.read()
log = os.environ.get("MOCK_CALL_LOG")
if log:
    with open(log, "a", encoding="utf-8") as f:
        f.write(json.dumps({"argv": args, "cwd": os.getcwd()}) + "\n")
out = {"type": "result", "result": "MOCK_RESULT_OK", "is_error": False, "total_cost_usd": 0.0123}
if "--session-id" in args:
    out["session_id"] = args[args.index("--session-id") + 1]
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

    $script:Config = "$script:Root/config.json"
    Set-Content -LiteralPath $script:Config -Encoding utf8NoBOM -Value '{"ruling_enabled": false, "gate_wait_max_min": 0, "cache_ttl": "5m", "credits_start_policy": "human-only"}'
    $script:Record = "$script:Root/record.md"
    Set-Content -LiteralPath $script:Record -Encoding utf8NoBOM -Value "# Probe Record fixture`n`n``````yaml`nprobe_record:`n  p7_decision: run`n``````"

    function New-Id([string]$Prefix) { "$Prefix-$([guid]::NewGuid().ToString('N').Substring(0, 10))" }

    function New-ManifestDoc([string]$RunId, [string]$ProjectRoot, [string]$WorkingDirectory) {
        [ordered]@{
            schema = 'credits-run.v1'; run_id = $RunId; kind = 'exec'
            project_root = $ProjectRoot; plan_folder = 'docs/execution/plans/2026-10-15-fixture/'
            brief = $script:Brief
            launch = [ordered]@{
                working_directory = $WorkingDirectory; claude_exe = $script:Mock; python_exe = $script:Py
                permission_mode = 'bypassPermissions'; effort = 'low'; segment_cap_usd = 20.0; timeout_sec = 3600
            }
            budget = [ordered]@{ run_cap_usd = 50.0 }
            messaging = [ordered]@{ orchestrator_sessions = @('00000000-0000-4000-8000-0000000000aa'); ruling_enabled = $false; gate_wait_max_min = 0 }
            depends_on = @(); lane = "tree:$script:Project/$RunId"
        }
    }

    function Save-Manifest($Doc) {
        $path = "$script:Root/manifest-$($Doc.run_id).json"
        Set-Content -LiteralPath $path -Value ($Doc | ConvertTo-Json -Depth 8) -Encoding utf8NoBOM
        $path
    }

    function New-FakeScheduler {
        $state = @{ Tasks = @{}; Calls = [System.Collections.Generic.List[string]]::new() }
        @{
            State    = $state
            Register = { param($Definition) $key = "$($Definition.TaskPath)$($Definition.TaskName)"; $state.Calls.Add("Register:$key"); $state.Tasks[$key] = $Definition }.GetNewClosure()
            Get      = { param($TaskPath, $TaskName) $state.Calls.Add("Get:$TaskPath$TaskName"); $state.Tasks["$TaskPath$TaskName"] }.GetNewClosure()
            Start    = { param($TaskPath, $TaskName) $state.Calls.Add("Start:$TaskPath$TaskName") }.GetNewClosure()
        }
    }

    # Run Register-CreditsRun.ps1 in this process. Returns Code, Payload (the last JSON line), Thrown.
    function Invoke-Register([string]$Manifest, [hashtable]$Scheduler) {
        $params = @{
            Manifest = $Manifest; Receipt = $script:Receipt; StateDb = $script:RegDb; ConfigPath = $script:Config
            ProbeRecord = $script:Record; Scheduler = $Scheduler; RunGate = $script:GatePy; KeyFile = $script:KeyFile
        }
        $global:LASTEXITCODE = 0
        $lines = @(); $thrown = $null
        try { $lines = @(& $script:Register @params 2>$null) } catch { $thrown = $_.Exception.Message }
        $code = $global:LASTEXITCODE
        $payload = $null
        $last = @($lines | ForEach-Object { "$_" } | Where-Object { $_.TrimStart().StartsWith('{') }) | Select-Object -Last 1
        if ($last) { try { $payload = $last | ConvertFrom-Json -ErrorAction Stop } catch { $payload = $null } }
        [pscustomobject]@{ Code = $code; Payload = $payload; Thrown = $thrown }
    }

    # One credits_state.py call (setup only) with the test effect log.
    function Invoke-Store([string]$Db, [string]$Verb, [string[]]$Arguments = @()) {
        $psi = [System.Diagnostics.ProcessStartInfo]::new($script:Py)
        foreach ($a in @('-X', 'utf8', $script:StateTool, '--db', $Db, $Verb) + $Arguments) { $psi.ArgumentList.Add([string]$a) }
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

    function Get-Rows([string]$Db, [string]$Sql, [string[]]$Params = @()) {
        $code = 'import json, sqlite3, sys; c = sqlite3.connect("file:" + sys.argv[1] + "?mode=ro", uri=True); c.row_factory = sqlite3.Row; print(json.dumps([dict(r) for r in c.execute(sys.argv[2], sys.argv[3:])]))'
        @((& $script:Py -X utf8 -c $code $Db $Sql @Params | Out-String) | ConvertFrom-Json)
    }

    # Start the launcher in a child pwsh with no CLAUDECODE, CLAUDE_CODE_ENTRYPOINT, CREDITS_* or
    # MOCK_* names from this process, plus the effect log and $Env.
    function Start-Launcher([string]$RunId, [hashtable]$Env = @{}) {
        $psi = [System.Diagnostics.ProcessStartInfo]::new('pwsh')
        $arguments = @('-NoProfile', '-File', $script:Launcher, '-RunId', $RunId, '-StateDb', $script:LaunchDb, '-OutputDir', $script:Out,
            '-KeyFile', $script:KeyFile, '-RunGate', $script:GatePy, '-Receipt', $script:Receipt,
            '-LaunchWaitMs', '60000', '-TerminateWaitMs', '5000', '-CancelPollMs', '1000')
        foreach ($a in $arguments) { $psi.ArgumentList.Add([string]$a) }
        $psi.UseShellExecute = $false
        $psi.RedirectStandardOutput = $true
        $psi.RedirectStandardError = $true
        foreach ($name in @($psi.Environment.Keys)) {
            if ($name -in @('CLAUDECODE', 'CLAUDE_CODE_ENTRYPOINT') -or $name -like 'CREDITS_*' -or $name -like 'MOCK_*') { $null = $psi.Environment.Remove($name) }
        }
        $psi.Environment['CREDITS_TEST_EFFECT_LOG'] = $script:EffectLog
        foreach ($k in $Env.Keys) { $psi.Environment[$k] = [string]$Env[$k] }
        $p = [System.Diagnostics.Process]::Start($psi)
        $so = $p.StandardOutput.ReadToEndAsync(); $se = $p.StandardError.ReadToEndAsync()
        if (-not $p.WaitForExit(240000)) { & taskkill.exe /PID $p.Id /T /F *> $null; throw "launcher timed out: $RunId" }
        $p.WaitForExit()
        $last = @("$($so.Result)" -split "`r?`n" | Where-Object { $_.TrimStart().StartsWith('{') }) | Select-Object -Last 1
        $payload = $null
        if ($last) { try { $payload = $last | ConvertFrom-Json -ErrorAction Stop } catch { $payload = $null } }
        [pscustomobject]@{ Code = $p.ExitCode; Payload = $payload; Out = $so.Result; Err = $se.Result }
    }

    function Get-LauncherLog([string]$RunId) {
        $path = Join-Path (Split-Path -Parent $script:LaunchDb) "logs/launcher-$RunId.jsonl"
        if (-not (Test-Path -LiteralPath $path)) { return @() }
        @([System.IO.File]::ReadAllLines($path) | Where-Object { $_.Trim() } | ForEach-Object { $_ | ConvertFrom-Json })
    }

    # A run imported straight into the launcher store (no Register checks), with one pending request.
    function New-StoreRun([string]$RunId, [string]$ProjectRoot, [string]$WorkingDirectory) {
        $manifest = Save-Manifest (New-ManifestDoc $RunId $ProjectRoot $WorkingDirectory)
        Invoke-Store $script:LaunchDb 'register' @('--run-id', $RunId, '--manifest', $manifest, '--cli-version', '2.1.296', '--kit-revision', 'kitrev-fixture') | Out-Null
        Invoke-Store $script:LaunchDb 'registered' @('--run-id', $RunId, '--task-hash', "taskhash-$RunId") | Out-Null
        Invoke-Store $script:LaunchDb 'request' @('--run-id', $RunId, '--started-by', 'human-command', '--request-id', "req-$RunId") | Out-Null
    }

    $script:RegDb = "$script:Root/register/state.db"
    $script:LaunchDb = "$script:Root/launch/state.db"
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $script:RegDb), (Split-Path -Parent $script:LaunchDb) | Out-Null
    Invoke-Store $script:RegDb 'init' | Out-Null
    Invoke-Store $script:LaunchDb 'init' | Out-Null
}

AfterAll {
    $env:CREDITS_TEST_EFFECT_LOG = $script:SavedEffectLog
    if ($script:Link -and (Test-Path -LiteralPath $script:Link)) { [System.IO.Directory]::Delete(([System.IO.Path]::GetFullPath($script:Link)), $false) }
    if ($script:Root -and (Test-Path -LiteralPath $script:Root)) { Remove-Item -LiteralPath $script:Root -Recurse -Force -ErrorAction SilentlyContinue }
}

Describe 'R1-F2: registration refuses a working directory in another project' {
    It 'R1-F2: project_root and launch.working_directory in two existing projects → refused project_mismatch, nothing stored or scheduled' {
        $run = New-Id 'f2-reg-mm'
        $fake = New-FakeScheduler
        $res = Invoke-Register -Manifest (Save-Manifest (New-ManifestDoc $run $script:Project $script:Other)) -Scheduler $fake
        $res.Thrown | Should -BeNullOrEmpty
        $res.Code | Should -Be 3
        $res.Payload.result | Should -Be 'refused'
        $res.Payload.reason | Should -Be 'project_mismatch'
        @(Get-Rows $script:RegDb 'SELECT * FROM runs WHERE run_id = ?' @($run)).Count | Should -Be 0
        $fake.State.Calls.Count | Should -Be 0
    }

    It 'R1-F2: the working directory under the project root (a subfolder) → refused project_mismatch' {
        $sub = "$script:Project/sub"
        New-Item -ItemType Directory -Force -Path $sub | Out-Null
        $run = New-Id 'f2-reg-sub'
        $fake = New-FakeScheduler
        $res = Invoke-Register -Manifest (Save-Manifest (New-ManifestDoc $run $script:Project $sub)) -Scheduler $fake
        $res.Code | Should -Be 3
        $res.Payload.reason | Should -Be 'project_mismatch'
        $fake.State.Calls.Count | Should -Be 0
    }

    It 'R1-F2: one directory written as <Name> → registered' -ForEach @(
        @{ Name = 'the same text'; Root = { $script:Project }; Cwd = { $script:Project } }
        @{ Name = 'a junction to the project'; Root = { $script:Project }; Cwd = { $script:Link } }
        @{ Name = 'a junction as the project root'; Root = { $script:Link }; Cwd = { $script:Project } }
        @{ Name = 'another case'; Root = { $script:Project }; Cwd = { $script:Project.ToUpperInvariant() } }
        @{ Name = 'a trailing separator'; Root = { $script:Project }; Cwd = { "$script:Project\" } }
        @{ Name = 'backslashes'; Root = { $script:Project.Replace('/', '\') }; Cwd = { $script:Project } }
    ) {
        $run = New-Id 'f2-reg-ok'
        $fake = New-FakeScheduler
        $res = Invoke-Register -Manifest (Save-Manifest (New-ManifestDoc $run (& $Root) (& $Cwd))) -Scheduler $fake
        $res.Thrown | Should -BeNullOrEmpty
        $res.Code | Should -Be 0
        $res.Payload.state | Should -Be 'registered'
    }
}

Describe 'R1-F2: the launcher refuses a mismatched run again, before it takes the request' {
    BeforeAll {
        $script:MmRun = New-Id 'f2-run-mm'
        New-StoreRun $script:MmRun $script:Project $script:Other
        $script:MmCalls = "$script:Root/$script:MmRun.calls.jsonl"
        $script:MmChild = Start-Launcher $script:MmRun @{ MOCK_CALL_LOG = $script:MmCalls }

        $script:OkRun = New-Id 'f2-run-ok'
        New-StoreRun $script:OkRun $script:Project $script:Link
        $script:OkCalls = "$script:Root/$script:OkRun.calls.jsonl"
        $script:OkChild = Start-Launcher $script:OkRun @{ MOCK_CALL_LOG = $script:OkCalls }
    }

    It 'R1-F2: the store took the mismatched manifest (the launcher is the last guard)' {
        @(Get-Rows $script:LaunchDb 'SELECT state FROM runs WHERE run_id = ?' @($script:MmRun)).Count | Should -Be 1
    }

    It 'R1-F2: the launcher answers start_refused project_mismatch and exits 1' {
        $script:MmChild.Code | Should -Be 1
        $script:MmChild.Payload.outcome | Should -Be 'start_refused'
        $script:MmChild.Payload.reason | Should -Be 'project_mismatch'
    }

    It 'R1-F2: nothing launched: the request still pending, no attempt, no segment, no CLI call' {
        (@(Get-Rows $script:LaunchDb 'SELECT state FROM requests WHERE request_id = ?' @("req-$script:MmRun")) | Select-Object -First 1).state | Should -Be 'pending'
        @(Get-Rows $script:LaunchDb 'SELECT * FROM attempts WHERE run_id = ?' @($script:MmRun)).Count | Should -Be 0
        @(Get-Rows $script:LaunchDb 'SELECT * FROM segments WHERE run_id = ?' @($script:MmRun)).Count | Should -Be 0
        Test-Path -LiteralPath $script:MmCalls | Should -BeFalse
    }

    # admit writes a lanes row on the first claim and only clears it on release.
    It 'R1-F2: the lane of the mismatched run was never claimed (no lanes row)' {
        @(Get-Rows $script:LaunchDb 'SELECT * FROM lanes WHERE lane = ?' @("tree:$script:Project/$script:MmRun")).Count | Should -Be 0
    }

    It 'R1-F2: the launcher log holds one ERROR credits_project_mismatch' {
        $records = @(Get-LauncherLog $script:MmRun | Where-Object { $_.event -eq 'credits_project_mismatch' })
        $records.Count | Should -Be 1
        $records[0].level | Should -Be 'ERROR'
    }

    It 'R1-F2 positive control: a working directory that is a junction to the project root launches once' {
        $script:OkChild.Code | Should -Be 0
        Test-Path -LiteralPath $script:OkCalls | Should -BeTrue
        @([System.IO.File]::ReadAllLines($script:OkCalls) | Where-Object { $_.Trim() }).Count | Should -Be 1
    }
}
