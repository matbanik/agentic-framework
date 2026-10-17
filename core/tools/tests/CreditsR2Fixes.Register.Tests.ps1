# R2-F1 (execution review round 2) of docs/execution/plans/2026-10-15-scheduled-credits-runs.
# The runs of one chain share one cap (report sections 4.3 and 5.4.4). Register-CreditsRun.ps1
# refuses a manifest whose chain block differs from the block that a run of the same chain_id
# already holds (chain_conflict, exit 3): no run row and no scheduler call. An equal block
# registers.
#
# Every store, receipt, key and project is a temp file. The key file holds a fake key. The mock
# claude answers --version only; the scheduler adapter is a fake.

BeforeAll {
    $script:Repo = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
    $script:Register = Join-Path $script:Repo '.agent/skills/claude-credits/Register-CreditsRun.ps1'
    $script:StateTool = Join-Path $script:Repo 'tools/credits_state.py'
    $script:Root = "{{RECEIPTS_DIR}}/credits-r2-register-tests/$([guid]::NewGuid().ToString('N'))"
    $script:Project = "$script:Root/project"
    New-Item -ItemType Directory -Force -Path $script:Project | Out-Null
    $script:EffectLog = "$script:Root/effects.jsonl"
    $script:SavedEffectLog = $env:CREDITS_TEST_EFFECT_LOG
    $env:CREDITS_TEST_EFFECT_LOG = $script:EffectLog

    $venvPy = Join-Path $script:Repo '.venv/Scripts/python.exe'
    $script:Py = if (Test-Path -LiteralPath $venvPy) { $venvPy } else { (Get-Command python -ErrorAction Stop).Source }
    $script:BasePython = (& $script:Py -c 'import sys; print(sys._base_executable)' | Out-String).Trim()

    $script:KeyFile = "$script:Root/fake.key"
    Set-Content -LiteralPath $script:KeyFile -Value ('sk-' + 'ant-api03-' + ('A' * 40)) -Encoding utf8NoBOM
    $script:Brief = "$script:Root/brief.md"
    Set-Content -LiteralPath $script:Brief -Value 'credits r2 register test brief' -Encoding utf8NoBOM

    $mockPy = "$script:Root/mock_claude.py"
    Set-Content -LiteralPath $mockPy -Encoding utf8NoBOM -Value @'
import sys

if "--version" in sys.argv[1:]:
    print("2.1.296 (Claude Code)")
    sys.exit(0)
sys.exit(1)
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

    function New-Chain([string]$ChainId, [double]$Cap) {
        [ordered]@{ chain_id = $ChainId; quote = 'Run the r2 chain with a total cap of ten dollars.'; given_at = '2026-10-17T01:00:00Z'; chain_cap_usd = $Cap }
    }

    function Save-ChainManifest([string]$RunId, $Chain) {
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
            chain = $Chain
        }
        $path = "$script:Root/manifest-$RunId.json"
        Set-Content -LiteralPath $path -Value ($doc | ConvertTo-Json -Depth 8) -Encoding utf8NoBOM
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
            Manifest = $Manifest; Receipt = $script:Receipt; StateDb = $script:Db; ConfigPath = $script:Config
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

    function Invoke-Store([string]$Verb, [string[]]$Arguments = @()) {
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

    function Get-RunCount([string]$RunId) {
        $code = 'import sqlite3, sys; c = sqlite3.connect("file:" + sys.argv[1] + "?mode=ro", uri=True); print(c.execute("SELECT COUNT(*) FROM runs WHERE run_id = ?", (sys.argv[2],)).fetchone()[0])'
        [int]((& $script:Py -X utf8 -c $code $script:Db $RunId | Out-String).Trim())
    }

    $script:Db = "$script:Root/store/state.db"
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $script:Db) | Out-Null
    Invoke-Store 'init' | Out-Null

    $script:Chain = New-Id 'r2-chain'
    $script:First = New-Id 'r2-first'
    $script:FirstResult = Invoke-Register -Manifest (Save-ChainManifest $script:First (New-Chain $script:Chain 10.0)) -Scheduler (New-FakeScheduler)
}

AfterAll {
    $env:CREDITS_TEST_EFFECT_LOG = $script:SavedEffectLog
    if ($script:Root -and (Test-Path -LiteralPath $script:Root)) { Remove-Item -LiteralPath $script:Root -Recurse -Force -ErrorAction SilentlyContinue }
}

Describe 'R2-F1: registration keeps one cap per chain' {
    It 'R2-F1 setup: the first run of the chain registers' {
        $script:FirstResult.Thrown | Should -BeNullOrEmpty
        $script:FirstResult.Code | Should -Be 0
        $script:FirstResult.Payload.state | Should -Be 'registered'
    }

    It 'R2-F1: a second run of the chain with another cap → refused chain_conflict, nothing stored or scheduled' {
        $run = New-Id 'r2-other-cap'
        $fake = New-FakeScheduler
        $res = Invoke-Register -Manifest (Save-ChainManifest $run (New-Chain $script:Chain 20.0)) -Scheduler $fake
        $res.Thrown | Should -BeNullOrEmpty
        $res.Code | Should -Be 3
        $res.Payload.result | Should -Be 'refused'
        $res.Payload.reason | Should -Be 'chain_conflict'
        Get-RunCount $run | Should -Be 0
        @($fake.State.Calls | Where-Object { $_ -like 'Register:*' }).Count | Should -Be 0
    }

    It 'R2-F1 positive control: a second run with an equal chain block registers' {
        $run = New-Id 'r2-same'
        $res = Invoke-Register -Manifest (Save-ChainManifest $run (New-Chain $script:Chain 10.0)) -Scheduler (New-FakeScheduler)
        $res.Thrown | Should -BeNullOrEmpty
        $res.Code | Should -Be 0
        $res.Payload.state | Should -Be 'registered'
    }
}
