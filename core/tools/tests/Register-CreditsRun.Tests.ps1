# S2 registration (Component D of docs/execution/plans/2026-10-15-scheduled-credits-runs).
# AC-D.1 Register-CreditsRun.ps1 validates the manifest, the local-path rule, the messaging config
# and the M-1 receipt (`run_gate.py --check-receipt`), then moves the run through registering →
# registered, or registration_failed with repair (report section 4.2; MX-24, MX-33, MX-34).
# AC-0.5 a cache TTL other than the 5-minute default needs a P-7 result in the Probe Record.
# AC-D.6 no test registers a real task: the scheduler adapter is injected.
#
# Every store, config, Probe Record and receipt is a temp file. The M-1 gate is a mock Python
# script that reads a fixture verdict from the receipt and records its argv next to it. Store
# effects go to a test effect log, so no test writes the Application event log.

BeforeAll {
    $script:Repo = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
    $script:Skill = Join-Path $script:Repo '.agent/skills/claude-credits'
    $script:Register = Join-Path $script:Skill 'Register-CreditsRun.ps1'
    $script:Launcher = Join-Path $script:Skill 'Start-CreditsRun.ps1'
    $script:Schema = Join-Path $script:Skill 'schemas/credits-run.v1.json'
    $script:Module = Join-Path $script:Skill 'CreditsRun.psm1'
    $script:StateTool = Join-Path $script:Repo 'tools/credits_state.py'
    $script:Root = "{{RECEIPTS_DIR}}/credits-register-tests/$([guid]::NewGuid().ToString('N'))"
    $script:Project = "$script:Root/project"
    New-Item -ItemType Directory -Force -Path $script:Project | Out-Null
    $script:EffectLog = "$script:Root/effects.jsonl"
    $script:SavedEffectLog = $env:CREDITS_TEST_EFFECT_LOG
    $env:CREDITS_TEST_EFFECT_LOG = $script:EffectLog
    $script:RunIds = [System.Collections.Generic.List[string]]::new()

    $venvPy = Join-Path $script:Repo '.venv/Scripts/python.exe'
    $script:Py = if (Test-Path -LiteralPath $venvPy) { $venvPy } else { (Get-Command python -ErrorAction Stop).Source }
    $script:BasePython = (& $script:Py -c 'import sys; print(sys._base_executable)' | Out-String).Trim()

    $script:KeyFile = "$script:Root/fake.key"
    Set-Content -LiteralPath $script:KeyFile -Value ('sk-' + 'ant-api03-' + ('A' * 40)) -Encoding utf8NoBOM
    $script:Brief = "$script:Root/brief.md"
    Set-Content -LiteralPath $script:Brief -Value 'credits register test brief' -Encoding utf8NoBOM

    # The mock CLI answers --version only; registration never starts a session.
    $mockPy = "$script:Root/mock_claude.py"
    Set-Content -LiteralPath $mockPy -Encoding utf8NoBOM -Value @'
import sys

if "--version" in sys.argv[1:]:
    print("2.1.296 (Claude Code)")
    sys.exit(0)
print("mock claude: registration must not start a session", file=sys.stderr)
sys.exit(9)
'@
    $script:Mock = "$script:Root/mock_claude.bat"
    Set-Content -LiteralPath $script:Mock -Encoding ascii -Value "@echo off`r`n`"$script:BasePython`" -X utf8 `"$mockPy`" %*"

    # The mock M-1 gate: exit 0 only for a receipt whose fixture_verdict is "ok". It writes its
    # argv to <receipt>.gate-argv.json, so a test can read the arguments Register passed.
    $script:GatePy = "$script:Root/mock_run_gate.py"
    Set-Content -LiteralPath $script:GatePy -Encoding utf8NoBOM -Value @'
import json
import sys

args = sys.argv[1:]
receipt = args[args.index("--check-receipt") + 1]
with open(receipt + ".gate-argv.json", "w", encoding="utf-8") as f:
    json.dump(args, f)
try:
    with open(receipt, encoding="utf-8") as f:
        doc = json.load(f)
except (OSError, ValueError) as exc:
    print(f"RECEIPT FAIL: unreadable ({exc.__class__.__name__})")
    print(f"RECEIPT REJECTED: {receipt}")
    sys.exit(1)
if doc.get("fixture_verdict") == "ok":
    print(f"RECEIPT OK: {receipt}")
    sys.exit(0)
print("RECEIPT FAIL: fixture verdict")
print(f"RECEIPT REJECTED: {receipt}")
sys.exit(1)
'@

    function New-Receipt([string]$Name, [string]$Verdict) {
        $path = "$script:Root/$Name/gate-result.json"
        New-Item -ItemType Directory -Force -Path (Split-Path -Parent $path) | Out-Null
        $doc = [ordered]@{ fixture_verdict = $Verdict; cli_version = '2.1.296'; identity = [ordered]@{ kit_revision = 'kitrev-fixture' } }
        Set-Content -LiteralPath $path -Value ($doc | ConvertTo-Json -Depth 4) -Encoding utf8NoBOM
        $path
    }
    $script:GoodReceipt = New-Receipt 'receipt-ok' 'ok'
    $script:BadReceipt = New-Receipt 'receipt-rejected' 'rejected'

    function New-Config([bool]$Ruling = $false, [int]$GateWait = 0, [string]$Ttl = '5m') {
        $path = "$script:Root/config-$([guid]::NewGuid().ToString('N').Substring(0, 8)).json"
        $doc = [ordered]@{ ruling_enabled = $Ruling; gate_wait_max_min = $GateWait; cache_ttl = $Ttl; credits_start_policy = 'human-only' }
        Set-Content -LiteralPath $path -Value ($doc | ConvertTo-Json) -Encoding utf8NoBOM
        $path
    }
    $script:Config = New-Config

    function New-ProbeRecord([string[]]$Keys) {
        $path = "$script:Root/record-$([guid]::NewGuid().ToString('N').Substring(0, 8)).md"
        $text = @('# Probe Record fixture', '', '```yaml', 'probe_record:') + @($Keys | ForEach-Object { "  $_" }) + @('```', '')
        Set-Content -LiteralPath $path -Value ($text -join "`n") -Encoding utf8NoBOM
        $path
    }
    $script:Record = New-ProbeRecord @('p7_decision: run', 'p8b_driver: pending')

    function New-Id([string]$Prefix) {
        $id = "$Prefix-$([guid]::NewGuid().ToString('N').Substring(0, 10))"
        $script:RunIds.Add($id)
        $id
    }

    function New-ManifestDoc([string]$RunId) {
        [ordered]@{
            schema = 'credits-run.v1'; run_id = $RunId; kind = 'exec'
            project_root = $script:Project; plan_folder = 'docs/execution/plans/2026-10-15-fixture/'
            brief = $script:Brief
            launch = [ordered]@{
                working_directory = $script:Project; claude_exe = $script:Mock; python_exe = $script:Py
                permission_mode = 'bypassPermissions'; effort = 'low'; segment_cap_usd = 20.0; timeout_sec = 3600
            }
            budget = [ordered]@{ run_cap_usd = 50.0 }
            messaging = [ordered]@{ orchestrator_sessions = @('00000000-0000-4000-8000-0000000000aa'); ruling_enabled = $false; gate_wait_max_min = 0 }
            depends_on = @(); lane = "tree:$script:Project"
        }
    }

    function Save-Manifest($Doc) {
        $path = "$script:Root/manifest-$($Doc.run_id)-$([guid]::NewGuid().ToString('N').Substring(0, 6)).json"
        Set-Content -LiteralPath $path -Value ($Doc | ConvertTo-Json -Depth 8) -Encoding utf8NoBOM
        $path
    }

    function New-Manifest([string]$RunId) { Save-Manifest (New-ManifestDoc $RunId) }

    # A fake scheduler adapter (AC-D.6). Modes: ok, run_throws (Register of the run task throws),
    # monitor_throws (Register of the monitor task throws), readback_missing (Get finds no run task).
    function New-FakeScheduler([string]$Mode = 'ok') {
        $state = @{ Mode = $Mode; Tasks = @{}; Calls = [System.Collections.Generic.List[string]]::new() }
        @{
            State    = $state
            Register = {
                param($Definition)
                $key = "$($Definition.TaskPath)$($Definition.TaskName)"
                $state.Calls.Add("Register:$key")
                if ($state.Mode -eq 'run_throws' -and $Definition.TaskName -ne 'Monitor') { throw 'fixture: the run task registration failed' }
                if ($state.Mode -eq 'monitor_throws' -and $Definition.TaskName -eq 'Monitor') { throw 'fixture: the monitor task registration failed' }
                $state.Tasks[$key] = $Definition
            }.GetNewClosure()
            Get      = {
                param($TaskPath, $TaskName)
                $state.Calls.Add("Get:$TaskPath$TaskName")
                if ($state.Mode -eq 'readback_missing' -and $TaskName -ne 'Monitor') { return $null }
                $state.Tasks["$TaskPath$TaskName"]
            }.GetNewClosure()
            Start    = {
                param($TaskPath, $TaskName)
                $state.Calls.Add("Start:$TaskPath$TaskName")
            }.GetNewClosure()
        }
    }

    function Import-CreditsRun {
        if (-not (Get-Module -Name CreditsRun)) { Import-Module -Name $script:Module -Force -DisableNameChecking -ErrorAction Stop }
    }

    # Run Register-CreditsRun.ps1 in this process (the adapter is a hashtable of script blocks).
    # Returns Code, Payload (the last JSON line), Thrown and Lines; a missing script or a throw
    # fails the test, not the container.
    function Invoke-Register {
        param([string]$Manifest, [hashtable]$Scheduler, [hashtable]$Extra = @{}, [string]$Db = $script:Db)
        $params = @{
            Manifest = $Manifest; Receipt = $script:GoodReceipt; StateDb = $Db; ConfigPath = $script:Config
            ProbeRecord = $script:Record; Scheduler = $Scheduler; RunGate = $script:GatePy; KeyFile = $script:KeyFile
        }
        foreach ($k in $Extra.Keys) { $params[$k] = $Extra[$k] }
        $global:LASTEXITCODE = 0
        $lines = @(); $thrown = $null
        try { $lines = @(& $script:Register @params 2>$null) } catch { $thrown = $_.Exception.Message }
        $code = $global:LASTEXITCODE
        $payload = $null
        $last = @($lines | ForEach-Object { "$_" } | Where-Object { $_.TrimStart().StartsWith('{') }) | Select-Object -Last 1
        if ($last) { try { $payload = $last | ConvertFrom-Json -ErrorAction Stop } catch { $payload = $null } }
        [pscustomobject]@{ Code = $code; Payload = $payload; Thrown = $thrown; Lines = $lines }
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
        if (-not (Test-Path -LiteralPath $Db)) { return @() }
        $code = 'import json, sqlite3, sys; c = sqlite3.connect("file:" + sys.argv[1] + "?mode=ro", uri=True); c.row_factory = sqlite3.Row; print(json.dumps([dict(r) for r in c.execute(sys.argv[2], sys.argv[3:])]))'
        @((& $script:Py -X utf8 -c $code $Db $Sql @Params | Out-String) | ConvertFrom-Json)
    }

    function Get-Run([string]$Db, [string]$RunId) { @(Get-Rows $Db 'SELECT * FROM runs WHERE run_id = ?' @($RunId)) | Select-Object -First 1 }

    function Test-SamePath([string]$A, [string]$B) {
        [System.IO.Path]::GetFullPath($A).TrimEnd('\', '/') -eq [System.IO.Path]::GetFullPath($B).TrimEnd('\', '/')
    }

    $script:Db = "$script:Root/state.db"
    Invoke-Store $script:Db 'init' | Out-Null
}

AfterAll {
    $env:CREDITS_TEST_EFFECT_LOG = $script:SavedEffectLog
    if ($script:Root -and (Test-Path -LiteralPath $script:Root)) { Remove-Item -LiteralPath $script:Root -Recurse -Force -ErrorAction SilentlyContinue }
}

Describe 'AC-D.1: a valid manifest and a qualifying M-1 receipt → registered (R§4.2 steps 1 to 4)' {
    BeforeAll {
        $script:OkRun = New-Id 'd1-ok'
        $script:OkManifest = New-Manifest $script:OkRun
        $script:OkFake = New-FakeScheduler
        $script:OkRes = Invoke-Register -Manifest $script:OkManifest -Scheduler $script:OkFake
        $script:OkKey = "\{{PROJECT_NAME_TITLE}}\Credits\$script:OkRun"
    }

    It 'AC-D.1: Register prints result changed, state registered, and exits 0' {
        $script:OkRes.Thrown | Should -BeNullOrEmpty
        $script:OkRes.Code | Should -Be 0
        $script:OkRes.Payload.result | Should -Be 'changed'
        $script:OkRes.Payload.run_id | Should -Be $script:OkRun
        $script:OkRes.Payload.state | Should -Be 'registered'
    }

    It 'AC-D.1: the store holds the run in registered with the receipt cli_version and kit_revision' {
        $run = Get-Run $script:Db $script:OkRun
        $run | Should -Not -BeNullOrEmpty
        $run.state | Should -Be 'registered'
        $run.cli_version | Should -Be '2.1.296'
        $run.kit_revision | Should -Be 'kitrev-fixture'
        $run.supervision | Should -Be 'job'
    }

    It 'AC-D.1: the gate got --check-receipt, --project, --python and --claude from the manifest' {
        $argvFile = "$script:GoodReceipt.gate-argv.json"
        Test-Path -LiteralPath $argvFile | Should -BeTrue
        $argv = @([System.IO.File]::ReadAllText($argvFile) | ConvertFrom-Json)
        Test-SamePath $argv[[array]::IndexOf($argv, '--check-receipt') + 1] $script:GoodReceipt | Should -BeTrue
        Test-SamePath $argv[[array]::IndexOf($argv, '--project') + 1] $script:Project | Should -BeTrue
        Test-SamePath $argv[[array]::IndexOf($argv, '--python') + 1] $script:Py | Should -BeTrue
        Test-SamePath $argv[[array]::IndexOf($argv, '--claude') + 1] $script:Mock | Should -BeTrue
    }

    It 'AC-D.1: the run task is \{{PROJECT_NAME_TITLE}}\Credits\{run id}: absolute pwsh, -File Start-CreditsRun.ps1 -RunId only, Interactive, Limited' {
        $def = $script:OkFake.State.Tasks[$script:OkKey]
        $def | Should -Not -BeNullOrEmpty
        $def.TaskPath | Should -Be '\{{PROJECT_NAME_TITLE}}\Credits\'
        $def.TaskName | Should -Be $script:OkRun
        [System.IO.Path]::IsPathRooted($def.Execute) | Should -BeTrue
        [System.IO.Path]::GetFileName($def.Execute) | Should -Be 'pwsh.exe'
        $def.Argument | Should -BeLike '-NoProfile -NonInteractive -ExecutionPolicy Bypass -WindowStyle Hidden -File "*" -RunId *'
        $file = [regex]::Match($def.Argument, '-File "([^"]+)"').Groups[1].Value
        Test-SamePath $file $script:Launcher | Should -BeTrue
        $def.Argument | Should -Match "-RunId $([regex]::Escape($script:OkRun))$"
        Test-SamePath $def.WorkingDirectory $script:Project | Should -BeTrue
        $def.LogonType | Should -Be 'Interactive'
        $def.RunLevel | Should -Be 'Limited'
    }

    It 'AC-D.1: the run task settings: batteries allowed, IgnoreNew, timeout plus 2 h, priority 5, no trigger, no restart' {
        $def = $script:OkFake.State.Tasks[$script:OkKey]
        $def.AllowStartIfOnBatteries | Should -BeTrue
        $def.DontStopIfGoingOnBatteries | Should -BeTrue
        $def.MultipleInstances | Should -Be 'IgnoreNew'
        [int]$def.ExecutionTimeLimitSec | Should -Be (3600 + 7200)
        [int]$def.Priority | Should -Be 5
        @($def.Triggers).Count | Should -Be 0
        [int]$def.RestartCount | Should -Be 0
        [bool]$def.WakeToRun | Should -BeFalse
    }

    It 'AC-D.1: the stored task_hash is the hash of the registered run task definition' {
        Import-CreditsRun
        $run = Get-Run $script:Db $script:OkRun
        $run.task_hash | Should -Not -BeNullOrEmpty
        $run.task_hash | Should -Be (Get-CreditsTaskDefinitionHash -Definition $script:OkFake.State.Tasks[$script:OkKey])
    }

    It 'AC-D.1: the monitor task is registered with an AtLogOn trigger and a 5-minute repeat' {
        $mon = $script:OkFake.State.Tasks['\{{PROJECT_NAME_TITLE}}\Credits\Monitor']
        $mon | Should -Not -BeNullOrEmpty
        @($mon.Triggers | ForEach-Object { $_.Kind }) | Should -Contain 'AtLogOn'
        @($mon.Triggers | Where-Object { $_.RepetitionInterval -eq 'PT5M' }).Count | Should -Be 1
    }

    It 'AC-D.1: Register never starts a task' {
        @($script:OkFake.State.Calls | Where-Object { $_ -like 'Start:*' }).Count | Should -Be 0
    }

    It 'AC-D.1: a second run on the same adapter registers the monitor task only once' {
        $other = New-Id 'd1-second'
        $res = Invoke-Register -Manifest (New-Manifest $other) -Scheduler $script:OkFake
        $res.Code | Should -Be 0
        $res.Payload.state | Should -Be 'registered'
        @($script:OkFake.State.Calls | Where-Object { $_ -eq 'Register:\{{PROJECT_NAME_TITLE}}\Credits\Monitor' }).Count | Should -Be 1
    }
}

Describe 'AC-D.1 negative: the manifest schema and the local-path rule' {
    It 'AC-D.1 negative: <Name> → refused manifest_invalid, no store row, no task' -ForEach @(
        @{ Name = 'an unknown key in launch'; Edit = { param($d) $d.launch['restart_on_failure'] = $true } }
        @{ Name = 'an unknown key in messaging'; Edit = { param($d) $d.messaging['auto_ruling'] = $true } }
        @{ Name = 'an unknown key in budget'; Edit = { param($d) $d.budget['floor_usd'] = 1 } }
        @{ Name = 'an unknown top-level key'; Edit = { param($d) $d['extra'] = 1 } }
        @{ Name = 'a wrong schema name'; Edit = { param($d) $d.schema = 'credits-run.v0' } }
        @{ Name = 'a string timeout'; Edit = { param($d) $d.launch.timeout_sec = '3600' } }
    ) {
        $run = New-Id 'd1-schema'
        $doc = New-ManifestDoc $run
        & $Edit $doc
        $fake = New-FakeScheduler
        $res = Invoke-Register -Manifest (Save-Manifest $doc) -Scheduler $fake
        $res.Code | Should -Be 3
        $res.Payload.result | Should -Be 'refused'
        $res.Payload.reason | Should -Be 'manifest_invalid'
        Get-Run $script:Db $run | Should -BeNullOrEmpty
        $fake.State.Calls.Count | Should -Be 0
    }

    It 'AC-D.1 negative: <Name> → refused path_not_local' -ForEach @(
        @{ Name = 'a UNC project_root'; Edit = { param($d) $d.project_root = '\\fixture-server\share\project' } }
        @{ Name = 'a relative brief'; Edit = { param($d) $d.brief = 'briefs/fixture.md' } }
        @{ Name = 'a working_directory with ..'; Edit = { param($d) $d.launch.working_directory = "$($d.project_root)/../elsewhere" } }
        @{ Name = 'a UNC claude_exe'; Edit = { param($d) $d.launch.claude_exe = '\\fixture-server\share\claude.cmd' } }
        @{ Name = 'a relative python_exe'; Edit = { param($d) $d.launch.python_exe = 'python.exe' } }
    ) {
        $run = New-Id 'd1-path'
        $doc = New-ManifestDoc $run
        & $Edit $doc
        $fake = New-FakeScheduler
        $res = Invoke-Register -Manifest (Save-Manifest $doc) -Scheduler $fake
        $res.Code | Should -Be 3
        $res.Payload.result | Should -Be 'refused'
        $res.Payload.reason | Should -Be 'path_not_local'
        Get-Run $script:Db $run | Should -BeNullOrEmpty
        $fake.State.Calls.Count | Should -Be 0
    }
}

Describe 'AC-D.1 negative: no qualifying M-1 receipt (MX-24, MX-33)' {
    It 'mx_24_ AC-D.1 negative: no receipt file → refused receipt_rejected, no store row, no task' {
        $run = New-Id 'd1-norcpt'
        $fake = New-FakeScheduler
        $res = Invoke-Register -Manifest (New-Manifest $run) -Scheduler $fake -Extra @{ Receipt = "$script:Root/absent/gate-result.json" }
        $res.Code | Should -Be 3
        $res.Payload.reason | Should -Be 'receipt_rejected'
        Get-Run $script:Db $run | Should -BeNullOrEmpty
        $fake.State.Calls.Count | Should -Be 0
    }

    It 'mx_33_ AC-D.1 negative: the gate rejects the receipt (exit 1) → refused receipt_rejected, no store row, no task' {
        $run = New-Id 'd1-badrcpt'
        $fake = New-FakeScheduler
        $res = Invoke-Register -Manifest (New-Manifest $run) -Scheduler $fake -Extra @{ Receipt = $script:BadReceipt }
        $res.Code | Should -Be 3
        $res.Payload.reason | Should -Be 'receipt_rejected'
        Test-Path -LiteralPath "$script:BadReceipt.gate-argv.json" | Should -BeTrue -Because 'the gate ran and said no'
        Get-Run $script:Db $run | Should -BeNullOrEmpty
        $fake.State.Calls.Count | Should -Be 0
    }
}

Describe 'AC-D.1 negative: the D-6/D-7 switches stay off until AC-I.6' {
    It 'AC-D.1 negative: <Name> → refused messaging_locked' -ForEach @(
        @{ Name = 'manifest ruling_enabled true'; Edit = { param($d) $d.messaging.ruling_enabled = $true }; Ruling = $false }
        @{ Name = 'manifest gate_wait_max_min 30 with ruling'; Edit = { param($d) $d.messaging.ruling_enabled = $true; $d.messaging.gate_wait_max_min = 30 }; Ruling = $false }
        @{ Name = 'config ruling_enabled true'; Edit = { param($d) }; Ruling = $true }
    ) {
        $run = New-Id 'd1-msg'
        $doc = New-ManifestDoc $run
        & $Edit $doc
        $fake = New-FakeScheduler
        $res = Invoke-Register -Manifest (Save-Manifest $doc) -Scheduler $fake -Extra @{ ConfigPath = (New-Config -Ruling $Ruling) }
        $res.Code | Should -Be 3
        $res.Payload.reason | Should -Be 'messaging_locked'
        Get-Run $script:Db $run | Should -BeNullOrEmpty
        $fake.State.Calls.Count | Should -Be 0
    }
}

Describe 'AC-0.5: the cache TTL stays 5 minutes until P-7 has a result' {
    It 'AC-0.5 negative: cache_ttl 1h with p7_decision only (no p7_result) → refused cache_ttl_unproven' {
        $run = New-Id 'a05-unproven'
        $fake = New-FakeScheduler
        $res = Invoke-Register -Manifest (New-Manifest $run) -Scheduler $fake -Extra @{ ConfigPath = (New-Config -Ttl '1h'); ProbeRecord = $script:Record }
        $res.Code | Should -Be 3
        $res.Payload.reason | Should -Be 'cache_ttl_unproven'
        Get-Run $script:Db $run | Should -BeNullOrEmpty
    }

    It 'AC-0.5: cache_ttl 1h with a p7_result entry → registered' {
        $run = New-Id 'a05-proven'
        $record = New-ProbeRecord @('p7_decision: run', 'p7_result: "1h TTL cache reads observed (fixture)"')
        $res = Invoke-Register -Manifest (New-Manifest $run) -Scheduler (New-FakeScheduler) -Extra @{ ConfigPath = (New-Config -Ttl '1h'); ProbeRecord = $record }
        $res.Code | Should -Be 0
        $res.Payload.state | Should -Be 'registered'
    }

    It 'AC-0.5: the 5-minute default needs no P-7 entry' {
        $run = New-Id 'a05-default'
        $res = Invoke-Register -Manifest (New-Manifest $run) -Scheduler (New-FakeScheduler) -Extra @{ ProbeRecord = (New-ProbeRecord @('p8b_driver: pending')) }
        $res.Code | Should -Be 0
        $res.Payload.state | Should -Be 'registered'
    }
}

Describe 'AC-D.1: registration repair (MX-34, the S2 part)' {
    It 'mx_34_ AC-D.1: the run task registration throws → registration_failed with the reason; a repeat repairs it to registered' {
        $run = New-Id 'mx34-runthrow'
        $manifest = New-Manifest $run
        $fake = New-FakeScheduler 'run_throws'
        $res = Invoke-Register -Manifest $manifest -Scheduler $fake
        $res.Code | Should -Not -Be 0
        $res.Payload.state | Should -Be 'registration_failed'
        $row = Get-Run $script:Db $run
        $row.state | Should -Be 'registration_failed'
        $row.registration_reason | Should -Not -BeNullOrEmpty
        $fake.State.Mode = 'ok'
        $again = Invoke-Register -Manifest $manifest -Scheduler $fake
        $again.Code | Should -Be 0
        $again.Payload.state | Should -Be 'registered'
        (Get-Run $script:Db $run).state | Should -Be 'registered'
    }

    It 'mx_34_ AC-D.1: the read-back finds no run task → registration_failed, never registered' {
        $run = New-Id 'mx34-readback'
        $fake = New-FakeScheduler 'readback_missing'
        $res = Invoke-Register -Manifest (New-Manifest $run) -Scheduler $fake
        $res.Code | Should -Not -Be 0
        (Get-Run $script:Db $run).state | Should -Be 'registration_failed'
    }

    It 'mx_34_ AC-D.1: died after the import (store registering, no task) → a repeat registers both tasks and moves to registered' {
        $run = New-Id 'mx34-afterimport'
        $manifest = New-Manifest $run
        Invoke-Store $script:Db 'register' @('--run-id', $run, '--manifest', $manifest, '--cli-version', '2.1.296', '--kit-revision', 'kitrev-fixture') | Out-Null
        (Get-Run $script:Db $run).state | Should -Be 'registering'
        $fake = New-FakeScheduler
        $res = Invoke-Register -Manifest $manifest -Scheduler $fake
        $res.Code | Should -Be 0
        $res.Payload.state | Should -Be 'registered'
        $fake.State.Tasks.ContainsKey("\{{PROJECT_NAME_TITLE}}\Credits\$run") | Should -BeTrue
        $fake.State.Tasks.ContainsKey('\{{PROJECT_NAME_TITLE}}\Credits\Monitor') | Should -BeTrue
    }

    It 'mx_34_ AC-D.1: died after the run task, before the monitor task → a repeat adds the monitor and moves to registered' {
        Import-CreditsRun
        $run = New-Id 'mx34-afterrun'
        $manifest = New-Manifest $run
        Invoke-Store $script:Db 'register' @('--run-id', $run, '--manifest', $manifest, '--cli-version', '2.1.296', '--kit-revision', 'kitrev-fixture') | Out-Null
        $fake = New-FakeScheduler
        $pwshPath = (Get-Process -Id $PID).Path
        $seeded = New-CreditsTaskDefinition -RunId $run -ProjectRoot $script:Project -PwshPath $pwshPath -LauncherPath $script:Launcher -TimeoutSec 3600
        $fake.State.Tasks["\{{PROJECT_NAME_TITLE}}\Credits\$run"] = $seeded
        $fake.State.Tasks.ContainsKey('\{{PROJECT_NAME_TITLE}}\Credits\Monitor') | Should -BeFalse
        $res = Invoke-Register -Manifest $manifest -Scheduler $fake
        $res.Code | Should -Be 0
        $res.Payload.state | Should -Be 'registered'
        $fake.State.Tasks.ContainsKey('\{{PROJECT_NAME_TITLE}}\Credits\Monitor') | Should -BeTrue
    }

    It 'mx_34_ AC-D.1: the monitor registration throws → registration_failed; a repeat repairs it to registered' {
        $run = New-Id 'mx34-monthrow'
        $manifest = New-Manifest $run
        $fake = New-FakeScheduler 'monitor_throws'
        $res = Invoke-Register -Manifest $manifest -Scheduler $fake
        $res.Code | Should -Not -Be 0
        (Get-Run $script:Db $run).state | Should -Be 'registration_failed'
        $fake.State.Mode = 'ok'
        $again = Invoke-Register -Manifest $manifest -Scheduler $fake
        $again.Code | Should -Be 0
        (Get-Run $script:Db $run).state | Should -Be 'registered'
    }

    It 'AC-D.1: a registered run with the same manifest and the same task → no_change, the run task is not registered again' {
        $run = New-Id 'd1-repeat'
        $manifest = New-Manifest $run
        $fake = New-FakeScheduler
        (Invoke-Register -Manifest $manifest -Scheduler $fake).Code | Should -Be 0
        $before = @($fake.State.Calls | Where-Object { $_ -eq "Register:\{{PROJECT_NAME_TITLE}}\Credits\$run" }).Count
        $res = Invoke-Register -Manifest $manifest -Scheduler $fake
        $res.Code | Should -Be 0
        $res.Payload.result | Should -Be 'no_change'
        $res.Payload.state | Should -Be 'registered'
        @($fake.State.Calls | Where-Object { $_ -eq "Register:\{{PROJECT_NAME_TITLE}}\Credits\$run" }).Count | Should -Be $before
    }

    It 'AC-D.1 negative: a registering run with another manifest → refused manifest_changed, the stored manifest stays' {
        $run = New-Id 'd1-changed'
        $first = New-Manifest $run
        Invoke-Store $script:Db 'register' @('--run-id', $run, '--manifest', $first, '--cli-version', '2.1.296', '--kit-revision', 'kitrev-fixture') | Out-Null
        $sha = (Get-Run $script:Db $run).manifest_sha256
        $doc = New-ManifestDoc $run
        $doc.launch.segment_cap_usd = 30.0
        $res = Invoke-Register -Manifest (Save-Manifest $doc) -Scheduler (New-FakeScheduler)
        $res.Code | Should -Be 3
        $res.Payload.reason | Should -Be 'manifest_changed'
        (Get-Run $script:Db $run).manifest_sha256 | Should -Be $sha
    }

    It 'AC-D.1 negative: a run past registration (requested) → refused already_started, no task change' {
        $run = New-Id 'd1-started'
        $manifest = New-Manifest $run
        $fake = New-FakeScheduler
        (Invoke-Register -Manifest $manifest -Scheduler $fake).Code | Should -Be 0
        Invoke-Store $script:Db 'request' @('--run-id', $run, '--started-by', 'human-command') | Out-Null
        $calls = $fake.State.Calls.Count
        $res = Invoke-Register -Manifest $manifest -Scheduler $fake
        $res.Code | Should -Be 3
        $res.Payload.reason | Should -Be 'already_started'
        (Get-Run $script:Db $run).state | Should -Be 'requested'
        @($fake.State.Calls | Select-Object -Skip $calls | Where-Object { $_ -like 'Register:*' }).Count | Should -Be 0
    }
}

Describe 'AC-21 (f): a manifest without caps passes the schema check; credits_state.py decides' {
    BeforeAll {
        # A manifest with no segment_cap_usd and no run_cap_usd, rooted at its own project.
        function New-UncappedDoc([string]$RunId, [string]$Switch) {
            $project = "$script:Root/project-$RunId"
            New-Item -ItemType Directory -Force -Path "$project/.agent" | Out-Null
            if ($Switch) {
                $limits = [System.IO.File]::ReadAllText((Join-Path $script:Repo '.agent/review-limits.json')) | ConvertFrom-Json
                $limits.token_budgets = $Switch
                Set-Content -LiteralPath "$project/.agent/review-limits.json" -Value ($limits | ConvertTo-Json -Depth 4) -Encoding utf8NoBOM
            }
            $doc = New-ManifestDoc $RunId
            $doc.project_root = $project
            $doc.launch.working_directory = $project
            $doc.lane = "tree:$project"
            $doc.launch.Remove('segment_cap_usd')
            $doc.budget.Remove('run_cap_usd')
            $doc
        }
    }

    It 'AC-21 (f): under token_budgets off → registered, and the store holds no cap' {
        $run = New-Id 'u-off'
        $fake = New-FakeScheduler
        $res = Invoke-Register -Manifest (Save-Manifest (New-UncappedDoc $run 'off')) -Scheduler $fake
        $res.Code | Should -Be 0 -Because "$($res.Lines) $($res.Thrown)"
        $res.Payload.state | Should -Be 'registered'
        $stored = Get-Run $script:Db $run
        $stored.segment_cap_usd | Should -BeNullOrEmpty
        $stored.run_cap_usd | Should -BeNullOrEmpty
    }

    It 'AC-21 (f) negative: <Name> → the store refuses manifest_invalid naming token_budgets, no store row, no task' -ForEach @(
        @{ Name = 'token_budgets on'; Switch = 'on' }
        @{ Name = 'no review-limits file'; Switch = '' }
    ) {
        $run = New-Id 'u-on'
        $fake = New-FakeScheduler
        $res = Invoke-Register -Manifest (Save-Manifest (New-UncappedDoc $run $Switch)) -Scheduler $fake
        $res.Code | Should -Be 3
        $res.Payload.reason | Should -Be 'manifest_invalid'
        $res.Payload.message | Should -Match 'token_budgets'
        Get-Run $script:Db $run | Should -BeNullOrEmpty
        $fake.State.Calls.Count | Should -Be 0
    }
}

Describe 'AC-D.1: the credits-run.v1 schema file' {
    It 'AC-D.1: the schema exists and names every manifest key of R§4.1' {
        Test-Path -LiteralPath $script:Schema | Should -BeTrue
        $doc = [System.IO.File]::ReadAllText($script:Schema) | ConvertFrom-Json -AsHashtable
        foreach ($k in @('schema', 'run_id', 'kind', 'project_root', 'plan_folder', 'brief', 'launch', 'budget', 'messaging', 'depends_on', 'lane', 'chain')) {
            $doc.properties.Keys | Should -Contain $k
        }
        foreach ($k in @('working_directory', 'claude_exe', 'python_exe', 'permission_mode', 'model', 'effort', 'segment_cap_usd', 'timeout_sec')) {
            $doc.properties.launch.properties.Keys | Should -Contain $k
        }
    }

    It 'AC-D.1: every object node in the schema sets additionalProperties false' {
        Test-Path -LiteralPath $script:Schema | Should -BeTrue
        $doc = [System.IO.File]::ReadAllText($script:Schema) | ConvertFrom-Json -AsHashtable
        $open = [System.Collections.Generic.List[string]]::new()
        $walk = $null
        $walk = {
            param($Node, [string]$Path)
            if ($Node -is [System.Collections.IDictionary]) {
                if ($Node['type'] -eq 'object' -or $Node.ContainsKey('properties')) {
                    if (-not ($Node.ContainsKey('additionalProperties') -and $Node['additionalProperties'] -is [bool] -and -not $Node['additionalProperties'])) { $open.Add($Path) }
                }
                foreach ($k in @($Node.Keys)) { & $walk $Node[$k] "$Path/$k" }
            } elseif ($Node -is [System.Collections.IList]) {
                for ($i = 0; $i -lt $Node.Count; $i++) { & $walk $Node[$i] "$Path/$i" }
            }
        }
        & $walk $doc '#'
        @($open) | Should -BeNullOrEmpty
    }
}

Describe 'AC-D.6: no test registers a real task' {
    It 'AC-D.6: New-CreditsSchedulerAdapter returns Register, Get and Start script blocks (not called here)' {
        Import-CreditsRun
        $adapter = New-CreditsSchedulerAdapter
        foreach ($k in @('Register', 'Get', 'Start')) { $adapter[$k] | Should -BeOfType [scriptblock] }
    }

    It 'AC-D.6: no run id of this file has a real task under \{{PROJECT_NAME_TITLE}}\Credits\' {
        $found = @(foreach ($id in $script:RunIds) {
                Get-ScheduledTask -TaskPath '\{{PROJECT_NAME_TITLE}}\Credits\' -TaskName $id -ErrorAction SilentlyContinue
            })
        $found.Count | Should -Be 0
    }
}
