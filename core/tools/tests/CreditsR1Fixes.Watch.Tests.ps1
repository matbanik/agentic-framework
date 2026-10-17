# Round-1 review fix R1-F1 (plan docs/execution/plans/2026-10-15-scheduled-credits-runs).
# AC-E.2 the monitor marks done only when tools/completion_preflight.py --json reports ok. A
#   preflight that fails (a usage error with missing=[], a nonzero exit, or ok=false) is not
#   completion evidence: the run is done_unverified and its missing list names the preflight.
#
# Part 1 runs the real monitor on a real store: a plan folder that the preflight refuses as a
# usage error (exit 2, missing=[]). Part 2 loads the monitor functions and gives Get-RunClass a
# fake preflight tool for each response shape.

BeforeAll {
    $script:Repo = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
    $script:Skill = Join-Path $script:Repo '.agent/skills/claude-credits'
    $script:Watch = Join-Path $script:Skill 'Watch-CreditsRuns.ps1'
    $script:Module = Join-Path $script:Skill 'CreditsRun.psm1'
    $script:StateTool = Join-Path $script:Repo 'tools/credits_state.py'
    $script:Root = "{{RECEIPTS_DIR}}/credits-r1-watch-tests/$([guid]::NewGuid().ToString('N'))"
    $script:Out = "$script:Root/dispatch"
    New-Item -ItemType Directory -Force -Path $script:Out | Out-Null
    $script:EffectLog = "$script:Root/effects.jsonl"
    $script:SavedEffectLog = $env:CREDITS_TEST_EFFECT_LOG
    $env:CREDITS_TEST_EFFECT_LOG = $script:EffectLog
    $script:Db = $null

    $venvPy = Join-Path $script:Repo '.venv/Scripts/python.exe'
    $script:Py = if (Test-Path -LiteralPath $venvPy) { $venvPy } else { (Get-Command python -ErrorAction Stop).Source }
    $script:BasePython = (& $script:Py -c 'import sys; print(sys._base_executable)' | Out-String).Trim()
    $script:Brief = "$script:Root/brief.md"
    Set-Content -LiteralPath $script:Brief -Value 'credits r1 monitor test brief' -Encoding utf8NoBOM
    $script:Claude = "$script:Root/claude.bat"
    Set-Content -LiteralPath $script:Claude -Value '@echo off' -Encoding ascii

    if (-not (Get-Module -Name CreditsRun)) { Import-Module -Name $script:Module -Force -DisableNameChecking -ErrorAction Stop }
    $script:BootId = Get-CreditsBootId
    $script:WinSession = [string](Get-Process -Id $PID).SessionId

    function Get-UtcText([datetime]$Value) { $Value.ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ') }

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

    function New-Store {
        $dir = "$script:Root/store-$([guid]::NewGuid().ToString('N').Substring(0, 10))"
        New-Item -ItemType Directory -Force -Path $dir | Out-Null
        $script:Db = "$dir/state.db"
        Assert-Store 'init' | Out-Null
    }

    function Get-Rows([string]$Sql, [string[]]$Params = @()) {
        $code = "import json, sqlite3, sys; c = sqlite3.connect('file:' + sys.argv[1] + '?mode=ro', uri=True); c.row_factory = sqlite3.Row; print(json.dumps([dict(r) for r in c.execute(sys.argv[2], sys.argv[3:])]))"
        @((Invoke-Py $code (@($script:Db, $Sql) + $Params)) | ConvertFrom-Json)
    }

    function Set-Rows([string]$Sql, [string[]]$Params = @()) {
        $code = 'import sqlite3, sys; c = sqlite3.connect(sys.argv[1]); c.execute(sys.argv[2], sys.argv[3:]); c.commit(); c.close()'
        Invoke-Py $code (@($script:Db, $Sql) + $Params) | Out-Null
    }

    function New-DeadIdentity {
        $p = Start-Process -FilePath $script:BasePython -ArgumentList '-c "import time; time.sleep(0.3)"' -PassThru -NoNewWindow
        $created = Get-UtcText $p.StartTime
        $p.WaitForExit()
        [pscustomobject]@{ Pid = $p.Id; Created = $created }
    }

    # An exec run with a running segment whose launcher and CLI are dead, for one plan folder.
    function New-RunningRun([string]$RunId, [string]$Project, [string]$PlanFolder) {
        New-Item -ItemType Directory -Force -Path $Project | Out-Null
        $doc = [ordered]@{
            schema = 'credits-run.v1'; run_id = $RunId; kind = 'exec'
            project_root = $Project; plan_folder = $PlanFolder
            brief = $script:Brief
            launch = [ordered]@{
                working_directory = $Project; claude_exe = $script:Claude; python_exe = $script:Py
                permission_mode = 'bypassPermissions'; effort = 'low'; segment_cap_usd = 20.0; timeout_sec = 3600
            }
            budget = [ordered]@{ run_cap_usd = 50.0 }
            messaging = [ordered]@{ orchestrator_sessions = @('00000000-0000-4000-8000-0000000000aa'); ruling_enabled = $false; gate_wait_max_min = 0 }
            depends_on = @(); lane = "tree:$Project/$RunId"
        }
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
        # The capture and the seal, so that only the preflight decides done.
        Set-Rows 'INSERT INTO landings (run_id, part, path, blob, sealed_utc) VALUES (?, ?, ?, ?, NULL)' @($RunId, 'product', 'tools/fixture.py', 'blob-product')
        Set-Rows 'INSERT INTO landings (run_id, part, path, blob, sealed_utc) VALUES (?, ?, ?, ?, ?)' @($RunId, 'closeout', '.agent/context/handoffs/fixture-handoff.md', 'blob-closeout', (Get-UtcText (Get-Date)))
        $dir = "$script:Out/disp-$RunId"
        New-Item -ItemType Directory -Force -Path $dir | Out-Null
        Set-Content -LiteralPath "$dir/status.json" -Value '{"exit_code": 0, "timed_out": false, "total_cost_usd": 1.0}' -Encoding utf8NoBOM -NoNewline
        Set-Content -LiteralPath "$dir/output.json" -Value '{"type": "result", "subtype": "success", "is_error": false, "total_cost_usd": 1.0}' -Encoding utf8NoBOM -NoNewline
        Set-Content -LiteralPath "$dir/final.md" -Value "Closeout complete.`n`nStatus: DONE`n" -Encoding utf8NoBOM -NoNewline
    }

    function Invoke-Watch {
        $notifier = { param($notice) }
        $global:LASTEXITCODE = 0
        $lines = @(); $thrown = $null
        try { $lines = @(& $script:Watch -StateDb $script:Db -OutputDir $script:Out -Notifier $notifier -HostEvents @() 2>$null) } catch { $thrown = $_.Exception.Message }
        $last = @($lines | ForEach-Object { "$_" } | Where-Object { $_.TrimStart().StartsWith('{') }) | Select-Object -Last 1
        [pscustomobject]@{ Code = $global:LASTEXITCODE; Payload = $(if ($last) { $last | ConvertFrom-Json } else { $null }); Thrown = $thrown }
    }

    function Assert-Pass($Result) {
        $Result.Thrown | Should -BeNullOrEmpty
        $Result.Code | Should -Be 0
        $Result.Payload.outcome | Should -Be 'pass'
    }
}

AfterAll {
    $env:CREDITS_TEST_EFFECT_LOG = $script:SavedEffectLog
    if ($script:Root -and (Test-Path -LiteralPath $script:Root)) { Remove-Item -LiteralPath $script:Root -Recurse -Force -ErrorAction SilentlyContinue }
}

Describe 'R1-F1 AC-E.2: a failed preflight through the real monitor' {
    It 'R1-F1 AC-E.2 negative: Status DONE and a plan folder the preflight refuses (usage error, missing=[]) → done_unverified, missing names preflight' {
        New-Store
        $run = "r1f1-typo-$([guid]::NewGuid().ToString('N').Substring(0, 8))"
        $tree = "$script:Root/tree-$run"
        New-RunningRun $run $tree '2026-typo'
        # The real preflight answers this plan folder with a usage error and an empty missing list.
        $probe = & $script:Py -X utf8 (Join-Path $script:Repo 'tools/completion_preflight.py') --plan '2026-typo' --tree $tree --json
        $probeCode = $LASTEXITCODE
        $probeDoc = @($probe | Where-Object { "$_".TrimStart().StartsWith('{') })[-1] | ConvertFrom-Json
        $probeCode | Should -Be 2
        $probeDoc.ok | Should -BeFalse
        @($probeDoc.missing).Count | Should -Be 0

        Assert-Pass (Invoke-Watch)
        Assert-Pass (Invoke-Watch)
        $state = @(Get-Rows 'SELECT * FROM runs WHERE run_id = ?' @($run)) | Select-Object -First 1
        $state.state | Should -Be 'done_unverified'
        $state.stop_class | Should -Be 'done_unverified'
        $notice = @(Get-Rows 'SELECT * FROM notices WHERE run_id = ? AND kind = ?' @($run, 'stop')) | Select-Object -First 1
        $notice | Should -Not -BeNullOrEmpty
        $body = $notice.body_json | ConvertFrom-Json
        @($body.missing) | Should -Contain 'preflight'
    }
}

Describe 'R1-F1 AC-E.2: Get-RunClass accepts the preflight only on exit 0 and ok=true' {
    BeforeAll {
        $tokens = $null; $parseErrors = $null
        $ast = [System.Management.Automation.Language.Parser]::ParseFile($script:Watch, [ref]$tokens, [ref]$parseErrors)
        foreach ($fn in $ast.FindAll({ param($n) $n -is [System.Management.Automation.Language.FunctionDefinitionAst] }, $false)) {
            . ([scriptblock]::Create($fn.Extent.Text))
        }
        $script:UnitRoot = "$script:Root/unit"
        $script:OutDir = "$script:UnitRoot/out"
        $script:ChildTimeoutMs = 120000
        $script:LogPath = "$script:UnitRoot/monitor.jsonl"
        New-Item -ItemType Directory -Force -Path "$script:OutDir/probe" | Out-Null
        Set-Content -LiteralPath "$script:OutDir/probe/final.md" -Value "Status: DONE`n" -Encoding utf8NoBOM -NoNewline
        Set-Content -LiteralPath "$script:OutDir/probe/status.json" -Value '{"exit_code":0}' -Encoding utf8NoBOM -NoNewline

        # A fake preflight tool: prints one JSON line and exits with the given code.
        function New-FakePreflight([string]$Json, [int]$ExitCode) {
            $path = "$script:UnitRoot/fake_preflight_$([guid]::NewGuid().ToString('N').Substring(0, 8)).py"
            Set-Content -LiteralPath $path -Encoding utf8NoBOM -Value @"
import sys
sys.stdout.write('$Json' + '\n')
sys.exit($ExitCode)
"@
            $path
        }

        function Get-PlanRunClass {
            $run = [pscustomobject]@{
                kind     = 'plan'
                manifest = @{ kind = 'plan'; project_root = $script:UnitRoot; plan_folder = 'docs/execution/plans/2026-10-15-fixture/' }
                segment  = @{ dispatch_id = 'probe'; stop_class = 'exited'; exit_code = 0 }
            }
            Get-RunClass $run
        }
    }

    It 'R1-F1 positive control: exit 0 and ok=true → done' {
        $script:PreflightTool = New-FakePreflight '{"ok": true, "missing": []}' 0
        $verdict = Get-PlanRunClass
        $verdict.Class | Should -Be 'done'
        @($verdict.Missing).Count | Should -Be 0
    }

    It 'R1-F1 negative: a usage error (exit 2, ok=false, missing=[]) → done_unverified, missing names preflight' {
        $script:PreflightTool = New-FakePreflight '{"ok": false, "missing": [], "error": "usage: the plan folder is not directly under docs/execution/plans/"}' 2
        $verdict = Get-PlanRunClass
        $verdict.Class | Should -Be 'done_unverified'
        @($verdict.Missing) | Should -Contain 'preflight'
    }

    It 'R1-F1 negative: exit 0 with ok=false and missing=[] → done_unverified' {
        $script:PreflightTool = New-FakePreflight '{"ok": false, "missing": []}' 0
        $verdict = Get-PlanRunClass
        $verdict.Class | Should -Be 'done_unverified'
        @($verdict.Missing) | Should -Contain 'preflight'
    }

    It 'R1-F1 negative: a nonzero exit with ok=true → done_unverified' {
        $script:PreflightTool = New-FakePreflight '{"ok": true, "missing": []}' 1
        $verdict = Get-PlanRunClass
        $verdict.Class | Should -Be 'done_unverified'
        @($verdict.Missing) | Should -Contain 'preflight'
    }

    It 'R1-F1 negative: a JSON line with no ok field → done_unverified' {
        $script:PreflightTool = New-FakePreflight '{"missing": []}' 0
        $verdict = Get-PlanRunClass
        $verdict.Class | Should -Be 'done_unverified'
        @($verdict.Missing) | Should -Contain 'preflight'
    }

    It 'R1-F1: a failing preflight keeps its own missing ids (exit 1, ok=false)' {
        $script:PreflightTool = New-FakePreflight '{"ok": false, "missing": ["approved_verdict"]}' 1
        $verdict = Get-PlanRunClass
        $verdict.Class | Should -Be 'done_unverified'
        @($verdict.Missing) | Should -Contain 'approved_verdict'
    }
}
