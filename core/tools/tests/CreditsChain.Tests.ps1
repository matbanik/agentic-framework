# S5 chaining, the PowerShell side (Component G of
# docs/execution/plans/2026-10-15-scheduled-credits-runs). The store verbs, the predicates and the
# helper binding are in tests/tooling/test_credits_chain.py and
# tests/tooling/test_executor_worktree_base.py; this file fixes the scripts around them.
# AC-G.1 Get-CreditsRun.ps1 <successor> -AcceptDrift <predecessor> -Quote "<words>" resolves the
#   successor project's HEAD once to B and records the human's words, the drifted paths and B in
#   one drift_accepts row (R§4.5, R§5.4; MX-15). No -Quote → exit 2, no row. No drift → refused
#   no_drift (exit 3), no row.
# AC-G.2 the launcher passes the base commit that admission recorded as CREDITS_BASE_COMMIT
#   (R§4.3 steps 3 and 4). A run with no executor worktree and no depends_on gets no base.
# AC-G.4 the monitor starts a chain run only when every predicate holds (R§4.4 step 4): it hands
#   the candidate to the start seam once; a filed request ends the candidacy; a predecessor that
#   is done_unverified (no seal, MX-25) or stopped starts nothing; a run with no chain block is
#   never started by the monitor.
# AC-G.5 Register-CreditsRun.ps1 takes the new manifest keys (executor_worktree, carry_allowed,
#   chain) and refuses plan_to_exec and predecessor_unknown with no store row and no task.
#
# The contract that these tests fix beyond the S2 to S4 scripts:
#   Watch-CreditsRuns.ps1 ... [-ChainStarter { param($Candidate) }]
#     $Candidate is one chain_candidates entry (run_id, chain_id, holds, halted, ready). The monitor
#     calls it for each ready candidate. Default: Start-CreditsRunTask.ps1 -RunId <run>
#     -StartedBy monitor-chain -ChainId <chain id>. No test here uses the default.
#   Get-CreditsRun.ps1 -RunId <successor> -AcceptDrift <predecessor> -Quote "<words>" [-StateDb]
#     prints the store's JSON line; exit 0 on changed or no_change, 3 on a refusal, 2 on a usage
#     error.
#
# Every store, project, manifest and receipt is a temp file. The projects are scratch git
# repositories. The CLI is a mock that dumps its CREDITS_* environment. The Task Scheduler is a
# fake adapter; the notifier and the chain starter record their calls.

BeforeAll {
    $script:Repo = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
    $script:Skill = Join-Path $script:Repo '.agent/skills/claude-credits'
    $script:Register = Join-Path $script:Skill 'Register-CreditsRun.ps1'
    $script:Launcher = Join-Path $script:Skill 'Start-CreditsRun.ps1'
    $script:Watch = Join-Path $script:Skill 'Watch-CreditsRuns.ps1'
    $script:Check = Join-Path $script:Skill 'Get-CreditsRun.ps1'
    $script:Module = Join-Path $script:Skill 'CreditsRun.psm1'
    $script:StateTool = Join-Path $script:Repo 'tools/credits_state.py'
    $script:Root = "{{RECEIPTS_DIR}}/credits-chain-tests/$([guid]::NewGuid().ToString('N'))"
    $script:Out = "$script:Root/dispatch"
    New-Item -ItemType Directory -Force -Path $script:Out | Out-Null
    $script:EffectLog = "$script:Root/effects.jsonl"
    $script:SavedEffectLog = $env:CREDITS_TEST_EFFECT_LOG
    $env:CREDITS_TEST_EFFECT_LOG = $script:EffectLog
    $script:Db = $null
    $script:Kids = [System.Collections.Generic.List[int]]::new()
    $script:PlanFolder = 'docs/execution/plans/2026-10-16-fixture/'

    $script:KeyFile = "$script:Root/fake.key"
    Set-Content -LiteralPath $script:KeyFile -Value ('sk-' + 'ant-api03-' + ('A' * 40)) -Encoding utf8NoBOM
    $script:Brief = "$script:Root/brief.md"
    Set-Content -LiteralPath $script:Brief -Value 'credits chain test brief' -Encoding utf8NoBOM

    $venvPy = Join-Path $script:Repo '.venv/Scripts/python.exe'
    $script:Py = if (Test-Path -LiteralPath $venvPy) { $venvPy } else { (Get-Command python -ErrorAction Stop).Source }
    $script:BasePython = (& $script:Py -c 'import sys; print(sys._base_executable)' | Out-String).Trim()

    # The mock CLI: --version for the receipt check; otherwise it dumps argv and every CREDITS_*
    # name to MOCK_ARGV_FILE and prints one result line.
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
argv_file = os.environ.get("MOCK_ARGV_FILE")
if argv_file:
    env = {k.upper(): v for k, v in os.environ.items() if k.upper().startswith("CREDITS_")}
    with open(argv_file, "w", encoding="utf-8") as f:
        json.dump({"argv": args, "pid": os.getpid(), "env": env}, f)
out = {"type": "result", "result": "MOCK_RESULT_OK", "is_error": False, "total_cost_usd": 0.0123}
sid = args[args.index("--session-id") + 1] if "--session-id" in args else None
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

    $script:Config = "$script:Root/config.json"
    Set-Content -LiteralPath $script:Config -Encoding utf8NoBOM -Value '{"ruling_enabled": false, "gate_wait_max_min": 0, "cache_ttl": "5m", "credits_start_policy": "human-only"}'
    $script:Record = "$script:Root/record.md"
    Set-Content -LiteralPath $script:Record -Encoding utf8NoBOM -Value (@('# Probe Record fixture', '', '```yaml', 'probe_record:', '  p7_decision: run', '```', '') -join "`n")

    $script:Strip = @('CLAUDECODE', 'CLAUDE_CODE_ENTRYPOINT')

    if (-not (Get-Module -Name CreditsRun)) { Import-Module -Name $script:Module -Force -DisableNameChecking -ErrorAction Stop }
    $script:BootId = Get-CreditsBootId
    $script:WinSession = [string](Get-Process -Id $PID).SessionId

    function New-Id([string]$Prefix) { "$Prefix-$([guid]::NewGuid().ToString('N').Substring(0, 10))" }
    function Get-UtcText([datetime]$Value) { $Value.ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ') }
    function Read-Json([string]$Path) { [System.IO.File]::ReadAllText($Path, [System.Text.Encoding]::UTF8) | ConvertFrom-Json }

    # pwsh -File <Script> <Arguments> with no inherited CREDITS_*, MOCK_*, CLAUDECODE or
    # CLAUDE_CODE_ENTRYPOINT, plus the test effect log and $Env.
    function Start-Child([string]$Script, [string[]]$Arguments, [hashtable]$Env = @{}) {
        $psi = [System.Diagnostics.ProcessStartInfo]::new('pwsh')
        foreach ($a in @('-NoProfile', '-NonInteractive', '-File', $Script) + $Arguments) { $psi.ArgumentList.Add([string]$a) }
        $psi.UseShellExecute = $false
        $psi.RedirectStandardInput = $true
        $psi.RedirectStandardOutput = $true
        $psi.RedirectStandardError = $true
        foreach ($name in @($psi.Environment.Keys)) {
            if ($name -in $script:Strip -or $name -like 'CREDITS_*' -or $name -like 'MOCK_*') { $null = $psi.Environment.Remove($name) }
        }
        $psi.Environment['CREDITS_TEST_EFFECT_LOG'] = $script:EffectLog
        foreach ($k in $Env.Keys) { $psi.Environment[$k] = [string]$Env[$k] }
        $p = [System.Diagnostics.Process]::Start($psi)
        $script:Kids.Add($p.Id)
        $p.StandardInput.Close()
        $so = $p.StandardOutput.ReadToEndAsync(); $se = $p.StandardError.ReadToEndAsync()
        if (-not $p.WaitForExit(240000)) { & taskkill.exe /PID $p.Id /T /F *> $null; throw "child timed out: $Script" }
        $p.WaitForExit()
        [pscustomobject]@{ Code = $p.ExitCode; Out = $so.Result; Err = $se.Result }
    }

    # python -c with an argument list: no shell quoting of the code, the SQL or the values.
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

    # One credits_state.py call (setup only) with the test effect log; a refusal throws.
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
        $code = "import json, sqlite3, sys; c = sqlite3.connect('file:' + sys.argv[1] + '?mode=ro', uri=True); c.row_factory = sqlite3.Row; print(json.dumps([dict(r) for r in c.execute(sys.argv[2], sys.argv[3:])]))"
        @((Invoke-Py $code (@($script:Db, $Sql) + $Params)) | ConvertFrom-Json)
    }

    # A fixture write that no store verb makes here: a landings row of the R§5.4 capture or seal.
    function Set-Rows([string]$Sql, [string[]]$Params = @()) {
        $code = 'import sqlite3, sys; c = sqlite3.connect(sys.argv[1]); c.execute(sys.argv[2], sys.argv[3:]); c.commit(); c.close()'
        Invoke-Py $code (@($script:Db, $Sql) + $Params) | Out-Null
    }

    function Get-Run([string]$RunId) { @(Get-Rows 'SELECT * FROM runs WHERE run_id = ?' @($RunId)) | Select-Object -First 1 }

    # A new store for one test.
    function New-Store {
        $dir = "$script:Root/store-$([guid]::NewGuid().ToString('N').Substring(0, 10))"
        New-Item -ItemType Directory -Force -Path $dir | Out-Null
        $script:Db = "$dir/state.db"
        Assert-Store 'init' | Out-Null
        $dir
    }

    function Invoke-Git([string]$Dir, [string[]]$Arguments) {
        $out = & git -C $Dir @Arguments 2>&1
        if ($LASTEXITCODE -ne 0) { throw "git $($Arguments -join ' ') failed: $($out | Out-String)" }
        ($out | Out-String).Trim()
    }

    # A scratch git repository with one commit that holds src/a.py ("A = 1").
    function New-GitProject {
        $dir = "$script:Root/project-$([guid]::NewGuid().ToString('N').Substring(0, 8))"
        New-Item -ItemType Directory -Force -Path "$dir/src" | Out-Null
        Invoke-Git $dir @('init', '-q', '-b', 'main') | Out-Null
        Invoke-Git $dir @('config', 'user.email', 'fixture@example.invalid') | Out-Null
        Invoke-Git $dir @('config', 'user.name', 'Fixture') | Out-Null
        Invoke-Git $dir @('config', 'core.autocrlf', 'false') | Out-Null
        [System.IO.File]::WriteAllText("$dir/src/a.py", "A = 1`n")
        Invoke-Git $dir @('add', '-A') | Out-Null
        Invoke-Git $dir @('commit', '-q', '-m', 'the fixture base') | Out-Null
        $dir
    }

    function Get-Head([string]$Dir) { Invoke-Git $Dir @('rev-parse', 'HEAD') }

    # The git blob id of $Text, hashed with no filters.
    function Get-BlobId([string]$Dir, [string]$Text) {
        $file = "$script:Root/blob-$([guid]::NewGuid().ToString('N').Substring(0, 8)).txt"
        [System.IO.File]::WriteAllText($file, $Text)
        Invoke-Git $Dir @('hash-object', '--no-filters', $file)
    }

    function New-Chain([double]$CapUsd = 30.0) {
        [ordered]@{ chain_id = 'chain-1'; quote = 'run p, then s, for 30 dollars at most'; given_at = '2026-10-16T09:00:00Z'; chain_cap_usd = $CapUsd }
    }

    function New-ManifestDoc([string]$RunId, [string]$Project, [string]$Kind = 'exec') {
        New-Item -ItemType Directory -Force -Path $Project | Out-Null
        [ordered]@{
            schema = 'credits-run.v1'; run_id = $RunId; kind = $Kind
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
    }

    function Save-Manifest($Doc) {
        $path = "$script:Root/manifest-$($Doc.run_id)-$([guid]::NewGuid().ToString('N').Substring(0, 6)).json"
        Set-Content -LiteralPath $path -Value ($Doc | ConvertTo-Json -Depth 8) -Encoding utf8NoBOM
        $path
    }

    # register + registered through the store (the setup path of the S1 to S4 rigs).
    function Register-Fixture($Doc) {
        $manifest = Save-Manifest $Doc
        Assert-Store 'register' @('--run-id', $Doc.run_id, '--manifest', $manifest, '--cli-version', '2.1.296', '--kit-revision', 'kitrev-fixture') | Out-Null
        Assert-Store 'registered' @('--run-id', $Doc.run_id, '--task-hash', "taskhash-$($Doc.run_id)") | Out-Null
    }

    # A process that has ended: its pid and creation time are a dead identity.
    function New-DeadIdentity {
        $p = Start-Process -FilePath $script:BasePython -ArgumentList '-c "import time; time.sleep(0.3)"' -PassThru -NoNewWindow
        $created = Get-UtcText $p.StartTime
        $p.WaitForExit()
        [pscustomobject]@{ Pid = $p.Id; Created = $created }
    }

    # A registered run driven through one finalized segment to the final class $To.
    function Complete-Fixture([string]$RunId, [string]$To = 'done', [string]$Class = 'done') {
        $launcher = New-DeadIdentity
        $cli = New-DeadIdentity
        Assert-Store 'request' @('--run-id', $RunId, '--started-by', 'human-command', '--request-id', "req0-$RunId") | Out-Null
        Assert-Store 'accept' @('--run-id', $RunId, '--launcher-pid', $launcher.Pid, '--launcher-created', $launcher.Created,
            '--boot-id', $script:BootId, '--win-session', $script:WinSession, '--attempt-id', "att0-$RunId", '--dispatch-id', "disp0-$RunId") | Out-Null
        Assert-Store 'admit' @('--attempt-id', "att0-$RunId", '--segment-id', "seg0-$RunId") | Out-Null
        Assert-Store 'launched' @('--segment-id', "seg0-$RunId", '--pid', $cli.Pid, '--created', $cli.Created, '--boot-id', $script:BootId) | Out-Null
        Assert-Store 'complete_segment' @('--segment-id', "seg0-$RunId", '--finalized-by', 'launcher', '--class', 'exited', '--session-total-usd', '1.5', '--exit-code', '0') | Out-Null
        Assert-Store 'classify' @('--run-id', $RunId, '--to', $To, '--class', $Class) | Out-Null
    }

    # One landings row; -Sealed sets sealed_utc (the closeout seal of R§5.4).
    function Add-Landing([string]$RunId, [string]$Part, [string]$Path, [string]$Blob, [switch]$Sealed) {
        if ($Sealed) {
            Set-Rows 'INSERT INTO landings (run_id, part, path, blob, sealed_utc) VALUES (?, ?, ?, ?, ?)' @($RunId, $Part, $Path, $Blob, (Get-UtcText (Get-Date)))
        } else {
            Set-Rows 'INSERT INTO landings (run_id, part, path, blob, sealed_utc) VALUES (?, ?, ?, ?, NULL)' @($RunId, $Part, $Path, $Blob)
        }
    }

    # A predecessor done and sealed: done_verified holds for it.
    function New-SealedPredecessor([string]$RunId, [string]$Project) {
        Register-Fixture (New-ManifestDoc $RunId $Project)
        Complete-Fixture $RunId
        Add-Landing $RunId 'product' 'src/a.py' 'blob-product'
        Add-Landing $RunId 'closeout' ".agent/context/handoffs/$RunId-handoff.md" 'blob-closeout' -Sealed
    }

    # A fake scheduler adapter: Register, Get and Start record their calls; no real task.
    function New-FakeScheduler {
        $state = @{ Tasks = @{}; Calls = [System.Collections.Generic.List[string]]::new() }
        @{
            State    = $state
            Register = { param($Definition) $state.Calls.Add("Register:$($Definition.TaskPath)$($Definition.TaskName)"); $state.Tasks["$($Definition.TaskPath)$($Definition.TaskName)"] = $Definition }.GetNewClosure()
            Get      = { param($TaskPath, $TaskName) $state.Calls.Add("Get:$TaskPath$TaskName"); $state.Tasks["$TaskPath$TaskName"] }.GetNewClosure()
            Start    = { param($TaskPath, $TaskName) $state.Calls.Add("Start:$TaskPath$TaskName") }.GetNewClosure()
        }
    }

    function Get-Payload([string]$Text) {
        $last = @("$Text" -split "`r?`n" | Where-Object { $_.TrimStart().StartsWith('{') }) | Select-Object -Last 1
        if (-not $last) { return $null }
        try { $last | ConvertFrom-Json -ErrorAction Stop } catch { $null }
    }

    # Register-CreditsRun.ps1 in this process. Returns Code, Payload and Thrown.
    function Invoke-Register([string]$Manifest, [hashtable]$Scheduler) {
        $params = @{
            Manifest = $Manifest; Receipt = $script:Receipt; StateDb = $script:Db; ConfigPath = $script:Config
            ProbeRecord = $script:Record; Scheduler = $Scheduler; RunGate = $script:GatePy; KeyFile = $script:KeyFile
        }
        $global:LASTEXITCODE = 0
        $lines = @(); $thrown = $null
        try { $lines = @(& $script:Register @params 2>$null) } catch { $thrown = $_.Exception.Message }
        $code = $global:LASTEXITCODE
        [pscustomobject]@{ Code = $code; Payload = (Get-Payload (($lines | ForEach-Object { "$_" }) -join "`n")); Thrown = $thrown }
    }

    function New-Notifier {
        $sent = [System.Collections.Generic.List[object]]::new()
        { param($notice) $sent.Add($notice) }.GetNewClosure()
    }

    # A chain starter that records each candidate it gets. $script:Started reads them.
    function New-Starter {
        $started = [System.Collections.Generic.List[object]]::new()
        $script:Started = $started
        { param($Candidate) $started.Add($Candidate) }.GetNewClosure()
    }
    function Get-StartedFor([string]$RunId) { @($script:Started | Where-Object { "$($_.run_id)" -eq $RunId }) }

    # One monitor pass in this process with a recording notifier and the given chain starter.
    function Invoke-Watch([scriptblock]$ChainStarter) {
        $splat = @{ StateDb = $script:Db; OutputDir = $script:Out; Observations = @{}; Notifier = (New-Notifier); HostEvents = @(); ChainStarter = $ChainStarter }
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

    function Get-LauncherArgs([string]$RunId) {
        @('-RunId', $RunId, '-StateDb', $script:Db, '-OutputDir', $script:Out, '-KeyFile', $script:KeyFile,
            '-RunGate', $script:GatePy, '-Receipt', $script:Receipt,
            '-LaunchWaitMs', '60000', '-TerminateWaitMs', '5000', '-CancelPollMs', '1000')
    }

    function Test-SamePath([string]$A, [string]$B) {
        [System.IO.Path]::GetFullPath($A).TrimEnd('\', '/') -eq [System.IO.Path]::GetFullPath($B).TrimEnd('\', '/')
    }
}

AfterAll {
    foreach ($id in $script:Kids) {
        if (Get-Process -Id $id -ErrorAction SilentlyContinue) { & taskkill.exe /PID $id /T /F *> $null }
    }
    $env:CREDITS_TEST_EFFECT_LOG = $script:SavedEffectLog
    if ($script:Root -and (Test-Path -LiteralPath $script:Root)) { Remove-Item -LiteralPath $script:Root -Recurse -Force -ErrorAction SilentlyContinue }
}

Describe 'AC-G.5: Register-CreditsRun.ps1 and the chain keys (R§4.1, R§5.4)' {
    It 'AC-G.5: a manifest with executor_worktree, carry_allowed, depends_on and a chain block → registered' {
        New-Store | Out-Null
        $proj = New-GitProject
        $p = New-Id 'g5-p'; $s = New-Id 'g5-s'
        Register-Fixture (New-ManifestDoc $p $proj)
        $doc = New-ManifestDoc $s $proj
        $doc['executor_worktree'] = $true
        $doc['carry_allowed'] = @('docs/notes/input.md')
        $doc.depends_on = @([ordered]@{ run_id = $p; require = @('done_verified', 'landed', 'committed') })
        $doc['chain'] = New-Chain
        $fake = New-FakeScheduler
        $res = Invoke-Register (Save-Manifest $doc) $fake
        $res.Thrown | Should -BeNullOrEmpty
        $res.Code | Should -Be 0
        $res.Payload.state | Should -Be 'registered'
        (Get-Run $s).state | Should -Be 'registered'
    }

    It 'AC-G.5 negative: an exec run that needs a plan run parked_verified → refused plan_to_exec, no store row, no task' {
        New-Store | Out-Null
        $proj = New-GitProject
        $p = New-Id 'g5-plan'; $s = New-Id 'g5-exec'
        Register-Fixture (New-ManifestDoc $p $proj 'plan')
        $doc = New-ManifestDoc $s $proj
        $doc.depends_on = @([ordered]@{ run_id = $p; require = @('parked_verified') })
        $fake = New-FakeScheduler
        $res = Invoke-Register (Save-Manifest $doc) $fake
        $res.Code | Should -Be 3
        $res.Payload.result | Should -Be 'refused'
        $res.Payload.reason | Should -Be 'plan_to_exec'
        Get-Run $s | Should -BeNullOrEmpty
        $fake.State.Calls.Count | Should -Be 0
    }

    It 'AC-G.5 negative: an unknown predecessor → refused predecessor_unknown, no store row, no task' {
        New-Store | Out-Null
        $proj = New-GitProject
        $s = New-Id 'g5-orphan'
        $doc = New-ManifestDoc $s $proj
        $doc.depends_on = @([ordered]@{ run_id = 'g5-ghost'; require = @('done_verified') })
        $fake = New-FakeScheduler
        $res = Invoke-Register (Save-Manifest $doc) $fake
        $res.Code | Should -Be 3
        $res.Payload.reason | Should -Be 'predecessor_unknown'
        Get-Run $s | Should -BeNullOrEmpty
        $fake.State.Calls.Count | Should -Be 0
    }

    It 'AC-G.5 negative: <Name> → refused manifest_invalid, no store row, no task' -ForEach @(
        @{ Name = 'carry_allowed without executor_worktree'; Edit = { param($d) $d['carry_allowed'] = @('docs/notes/input.md') } }
        @{ Name = 'executor_worktree as text'; Edit = { param($d) $d['executor_worktree'] = 'yes' } }
        @{ Name = 'a chain block with no quote'; Edit = { param($d) $c = New-Chain; $c.Remove('quote'); $d['chain'] = $c } }
        @{ Name = 'a chain block with an extra key'; Edit = { param($d) $c = New-Chain; $c['auto'] = $true; $d['chain'] = $c } }
    ) {
        New-Store | Out-Null
        $proj = New-GitProject
        $s = New-Id 'g5-bad'
        $doc = New-ManifestDoc $s $proj
        & $Edit $doc
        $fake = New-FakeScheduler
        $res = Invoke-Register (Save-Manifest $doc) $fake
        $res.Code | Should -Be 3
        $res.Payload.reason | Should -Be 'manifest_invalid'
        Get-Run $s | Should -BeNullOrEmpty
        $fake.State.Calls.Count | Should -Be 0
    }
}

Describe 'AC-G.2: the launcher passes the admitted base as CREDITS_BASE_COMMIT (R§4.3 steps 3 and 4)' {
    It 'AC-G.2: a worktree run → the segment base_commit is HEAD and the CLI gets CREDITS_BASE_COMMIT = HEAD' {
        New-Store | Out-Null
        $proj = New-GitProject
        $head = Get-Head $proj
        $w = New-Id 'g2-wt'
        $doc = New-ManifestDoc $w $proj
        $doc['executor_worktree'] = $true
        Register-Fixture $doc
        Assert-Store 'request' @('--run-id', $w, '--started-by', 'human-command', '--request-id', "req-$w") | Out-Null
        $argv = "$script:Root/$w.argv.json"
        $child = Start-Child $script:Launcher (Get-LauncherArgs $w) -Env @{ MOCK_ARGV_FILE = $argv }
        $child.Code | Should -Be 0 -Because "$($child.Out) $($child.Err)"
        $seg = @(Get-Rows 'SELECT base_commit FROM segments WHERE run_id = ?' @($w)) | Select-Object -First 1
        $seg.base_commit | Should -Be $head
        Test-Path -LiteralPath $argv | Should -BeTrue
        $dump = Read-Json $argv
        $dump.env.CREDITS_BASE_COMMIT | Should -Be $head
        $dump.env.CREDITS_RUN_ID | Should -Be $w
    }

    It 'AC-G.2: a run with no executor worktree and no depends_on → no base_commit and no CREDITS_BASE_COMMIT' {
        New-Store | Out-Null
        $proj = New-GitProject
        $r = New-Id 'g2-plain'
        Register-Fixture (New-ManifestDoc $r $proj)
        Assert-Store 'request' @('--run-id', $r, '--started-by', 'human-command', '--request-id', "req-$r") | Out-Null
        $argv = "$script:Root/$r.argv.json"
        $child = Start-Child $script:Launcher (Get-LauncherArgs $r) -Env @{ MOCK_ARGV_FILE = $argv }
        $child.Code | Should -Be 0 -Because "$($child.Out) $($child.Err)"
        $seg = @(Get-Rows 'SELECT base_commit FROM segments WHERE run_id = ?' @($r)) | Select-Object -First 1
        $seg.base_commit | Should -BeNullOrEmpty
        $dump = Read-Json $argv
        @($dump.env.PSObject.Properties.Name) | Should -Not -Contain 'CREDITS_BASE_COMMIT'
        $dump.env.CREDITS_RUN_ID | Should -Be $r
    }
}

Describe 'AC-G.4: the monitor starts a chain run only when every predicate holds (R§4.4 step 4)' {
    It 'AC-G.4: a sealed done predecessor → one start through -ChainStarter with the run and its chain id' {
        New-Store | Out-Null
        $proj = New-GitProject
        $p = New-Id 'g4-p'; $s = New-Id 'g4-s'
        New-SealedPredecessor $p $proj
        $doc = New-ManifestDoc $s $proj
        $doc.depends_on = @([ordered]@{ run_id = $p; require = @('done_verified') })
        $doc['chain'] = New-Chain
        Register-Fixture $doc
        $starter = New-Starter
        Assert-Pass (Invoke-Watch -ChainStarter $starter)
        $calls = Get-StartedFor $s
        $calls.Count | Should -Be 1
        $calls[0].chain_id | Should -Be 'chain-1'
        $calls[0].ready | Should -BeTrue
        @(Get-StartedFor $p).Count | Should -Be 0
    }

    It 'AC-G.4: a filed monitor-chain request ends the candidacy → the next pass starts nothing' {
        New-Store | Out-Null
        $proj = New-GitProject
        $p = New-Id 'g4-p'; $s = New-Id 'g4-s'
        New-SealedPredecessor $p $proj
        $doc = New-ManifestDoc $s $proj
        $doc.depends_on = @([ordered]@{ run_id = $p; require = @('done_verified') })
        $doc['chain'] = New-Chain
        Register-Fixture $doc
        $starter = New-Starter
        Assert-Pass (Invoke-Watch -ChainStarter $starter)
        @(Get-StartedFor $s).Count | Should -Be 1
        # What Start-CreditsRunTask.ps1 -StartedBy monitor-chain files.
        Assert-Store 'request' @('--run-id', $s, '--started-by', 'monitor-chain', '--chain-id', 'chain-1', '--request-id', "req-$s") | Out-Null
        Assert-Pass (Invoke-Watch -ChainStarter $starter)
        @(Get-StartedFor $s).Count | Should -Be 1
    }

    It 'mx_25_ AC-G.4: a predecessor done_unverified (no seal) → no start' {
        New-Store | Out-Null
        $proj = New-GitProject
        $p = New-Id 'g4-unv'; $s = New-Id 'g4-s'
        Register-Fixture (New-ManifestDoc $p $proj)
        Complete-Fixture $p 'done_unverified' 'done_unverified'
        Add-Landing $p 'product' 'src/a.py' 'blob-product'
        $doc = New-ManifestDoc $s $proj
        $doc.depends_on = @([ordered]@{ run_id = $p; require = @('done_verified') })
        $doc['chain'] = New-Chain
        Register-Fixture $doc
        $starter = New-Starter
        Assert-Pass (Invoke-Watch -ChainStarter $starter)
        @(Get-StartedFor $s).Count | Should -Be 0
        (Get-Run $s).state | Should -Be 'registered'
    }

    It 'AC-G.4: a stopped predecessor halts the chain → no start' {
        New-Store | Out-Null
        $proj = New-GitProject
        $p = New-Id 'g4-stop'; $s = New-Id 'g4-s'
        Register-Fixture (New-ManifestDoc $p $proj)
        Complete-Fixture $p 'stopped' 'exited'
        $doc = New-ManifestDoc $s $proj
        $doc.depends_on = @([ordered]@{ run_id = $p; require = @('done_verified') })
        $doc['chain'] = New-Chain
        Register-Fixture $doc
        $starter = New-Starter
        Assert-Pass (Invoke-Watch -ChainStarter $starter)
        @(Get-StartedFor $s).Count | Should -Be 0
    }

    It 'AC-G.4: a run with no chain block is never started by the monitor, even when its predicates hold' {
        New-Store | Out-Null
        $proj = New-GitProject
        $p = New-Id 'g4-p'; $s = New-Id 'g4-nochain'
        New-SealedPredecessor $p $proj
        $doc = New-ManifestDoc $s $proj
        $doc.depends_on = @([ordered]@{ run_id = $p; require = @('done_verified') })
        Register-Fixture $doc
        $starter = New-Starter
        Assert-Pass (Invoke-Watch -ChainStarter $starter)
        @(Get-StartedFor $s).Count | Should -Be 0
    }
}

Describe 'AC-G.1: Get-CreditsRun.ps1 -AcceptDrift (R§4.5, R§5.4; MX-15)' {
    BeforeAll {
        # P landed a.py as "A = 2"; the human's commit holds "A = 1". The sealed closeout row is
        # ABSENT and the file stays absent, so src/a.py is the one drifted path.
        function New-DriftFixture {
            New-Store | Out-Null
            $proj = New-GitProject
            $p = New-Id 'g1-p'; $s = New-Id 'g1-s'
            Register-Fixture (New-ManifestDoc $p $proj)
            Complete-Fixture $p
            Add-Landing $p 'product' 'src/a.py' (Get-BlobId $proj "A = 2`n")
            Add-Landing $p 'closeout' ".agent/context/handoffs/$p-handoff.md" 'ABSENT' -Sealed
            $doc = New-ManifestDoc $s $proj
            $doc['executor_worktree'] = $true
            $doc.depends_on = @([ordered]@{ run_id = $p; require = @('committed') })
            Register-Fixture $doc
            [pscustomobject]@{ Project = $proj; P = $p; S = $s }
        }
    }

    It 'mx_15_ AC-G.1: -AcceptDrift <P> -Quote → one drift_accepts row for HEAD with the words and the drifted path' {
        $fx = New-DriftFixture
        $head = Get-Head $fx.Project
        $res = Start-Child $script:Check @('-RunId', $fx.S, '-AcceptDrift', $fx.P, '-Quote', 'keep the old a.py', '-StateDb', $script:Db)
        $res.Code | Should -Be 0 -Because "$($res.Out) $($res.Err)"
        (Get-Payload $res.Out).result | Should -Be 'changed'
        $rows = @(Get-Rows 'SELECT commit_id, words, paths_json FROM drift_accepts')
        $rows.Count | Should -Be 1
        $rows[0].commit_id | Should -Be $head
        $rows[0].words | Should -Be 'keep the old a.py'
        $rows[0].paths_json | Should -Be '["src/a.py"]'
    }

    It 'mx_15_ AC-G.1: the same -AcceptDrift again → no_change, exit 0, still one row' {
        $fx = New-DriftFixture
        $args1 = @('-RunId', $fx.S, '-AcceptDrift', $fx.P, '-Quote', 'keep the old a.py', '-StateDb', $script:Db)
        (Start-Child $script:Check $args1).Code | Should -Be 0
        $again = Start-Child $script:Check $args1
        $again.Code | Should -Be 0 -Because "$($again.Out) $($again.Err)"
        (Get-Payload $again.Out).result | Should -Be 'no_change'
        @(Get-Rows 'SELECT commit_id FROM drift_accepts').Count | Should -Be 1
    }

    It 'AC-G.1 negative: -AcceptDrift without -Quote → exit 2, no row' {
        $fx = New-DriftFixture
        $res = Start-Child $script:Check @('-RunId', $fx.S, '-AcceptDrift', $fx.P, '-StateDb', $script:Db)
        $res.Code | Should -Be 2 -Because "$($res.Out) $($res.Err)"
        @(Get-Rows "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'drift_accepts'").Count | Should -Be 1
        @(Get-Rows 'SELECT commit_id FROM drift_accepts').Count | Should -Be 0
    }

    It 'AC-G.1 negative: no drift at HEAD → refused no_drift (exit 3), no row' {
        $fx = New-DriftFixture
        [System.IO.File]::WriteAllText("$($fx.Project)/src/a.py", "A = 2`n")
        Invoke-Git $fx.Project @('commit', '-q', '-am', 'the human commits the landed a.py') | Out-Null
        $res = Start-Child $script:Check @('-RunId', $fx.S, '-AcceptDrift', $fx.P, '-Quote', 'keep it', '-StateDb', $script:Db)
        $res.Code | Should -Be 3 -Because "$($res.Out) $($res.Err)"
        (Get-Payload $res.Out).error | Should -Be 'no_drift'
        @(Get-Rows "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'drift_accepts'").Count | Should -Be 1
        @(Get-Rows 'SELECT commit_id FROM drift_accepts').Count | Should -Be 0
    }
}
