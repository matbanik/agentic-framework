# S2 caller side (Component D of docs/execution/plans/2026-10-15-scheduled-credits-runs).
# AC-D.2 Start-CreditsRunTask.ps1 writes one single-use start request (with the quote), starts the
# task through the scheduler adapter and waits for the launcher to accept it (report section 4.2,
# REQUEST_ACCEPT_TIMEOUT_S = 120). MX-5 (a refused resume), MX-6 (the caller times out while the
# launcher accepts) and the caller timeout path.
# AC-D.6 no test starts a real task: the adapter is injected. Its Start block plays the launcher
# and moves the request through the store directly.
#
# Tests pass -AcceptTimeoutMs 300 -PollIntervalMs 50; the script uses min(value, 120000).

BeforeAll {
    $script:Repo = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
    $script:Skill = Join-Path $script:Repo '.agent/skills/claude-credits'
    $script:Caller = Join-Path $script:Skill 'Start-CreditsRunTask.ps1'
    $script:Module = Join-Path $script:Skill 'CreditsRun.psm1'
    $script:StateTool = Join-Path $script:Repo 'tools/credits_state.py'
    $script:Root = "{{RECEIPTS_DIR}}/credits-starttask-tests/$([guid]::NewGuid().ToString('N'))"
    $script:Project = "$script:Root/project"
    New-Item -ItemType Directory -Force -Path $script:Project | Out-Null
    $script:EffectLog = "$script:Root/effects.jsonl"
    $script:SavedEffectLog = $env:CREDITS_TEST_EFFECT_LOG
    $env:CREDITS_TEST_EFFECT_LOG = $script:EffectLog
    $script:RunIds = [System.Collections.Generic.List[string]]::new()

    $venvPy = Join-Path $script:Repo '.venv/Scripts/python.exe'
    $script:Py = if (Test-Path -LiteralPath $venvPy) { $venvPy } else { (Get-Command python -ErrorAction Stop).Source }
    $script:Brief = "$script:Root/brief.md"
    Set-Content -LiteralPath $script:Brief -Value 'credits start-task test brief' -Encoding utf8NoBOM
    $script:Db = "$script:Root/state.db"
    # This suite starts runs as agent-on-user-chat too, so its config allows that start
    # (Start-CreditsRunTask.Policy.Tests.ps1 covers the human-only default).
    $script:SavedConfig = $env:CREDITS_CONFIG
    $env:CREDITS_CONFIG = "$script:Root/config.json"
    Set-Content -LiteralPath $env:CREDITS_CONFIG -Encoding utf8NoBOM -Value '{"ruling_enabled": false, "gate_wait_max_min": 0, "cache_ttl": "5m", "credits_start_policy": "agent-on-user-chat"}'

    function Get-UtcText([datetime]$Value) { $Value.ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ') }

    function New-Id([string]$Prefix) {
        $id = "$Prefix-$([guid]::NewGuid().ToString('N').Substring(0, 10))"
        $script:RunIds.Add($id)
        $id
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

    # A registered run in the store. A lane may be shared to make lane_busy.
    function New-RegisteredRun([string]$RunId, [string]$Lane = '', [double]$SegmentCap = 20.0, [double]$RunCap = 50.0) {
        if (-not $Lane) { $Lane = "tree:$script:Project/$RunId" }
        $doc = [ordered]@{
            schema = 'credits-run.v1'; run_id = $RunId; kind = 'exec'
            project_root = $script:Project; plan_folder = 'docs/execution/plans/2026-10-15-fixture/'
            brief = $script:Brief
            launch = [ordered]@{
                working_directory = $script:Project; claude_exe = 'C:/fixture/claude.cmd'; python_exe = 'C:/fixture/python.exe'
                permission_mode = 'bypassPermissions'; effort = 'low'; segment_cap_usd = $SegmentCap; timeout_sec = 3600
            }
            budget = [ordered]@{ run_cap_usd = $RunCap }
            messaging = [ordered]@{ orchestrator_sessions = @('00000000-0000-4000-8000-0000000000aa'); ruling_enabled = $false; gate_wait_max_min = 0 }
            depends_on = @(); lane = $Lane
        }
        $manifest = "$script:Root/manifest-$RunId.json"
        Set-Content -LiteralPath $manifest -Value ($doc | ConvertTo-Json -Depth 6) -Encoding utf8NoBOM
        Assert-Store 'register' @('--run-id', $RunId, '--manifest', $manifest, '--cli-version', '2.1.296', '--kit-revision', 'kitrev-fixture') | Out-Null
        Assert-Store 'registered' @('--run-id', $RunId, '--task-hash', "taskhash-$RunId") | Out-Null
    }

    # The launcher steps of one start, done straight on the store: accept, admit, launched.
    function Invoke-FixtureLaunch([string]$RunId, [string]$Tag, [switch]$AcceptOnly) {
        $accepted = Assert-Store 'accept' @('--run-id', $RunId, '--launcher-pid', '4242', '--launcher-created', (Get-UtcText (Get-Date).AddMinutes(-1)),
            '--boot-id', 'boot-fixture-1', '--win-session', '1', '--attempt-id', "att-$Tag", '--dispatch-id', "disp-$Tag") | ConvertFrom-Json
        if ($AcceptOnly) { return $accepted }
        $admitted = Assert-Store 'admit' @('--attempt-id', "att-$Tag", '--segment-id', "seg-$Tag") | ConvertFrom-Json
        if ($admitted.outcome -eq 'admitted') {
            Assert-Store 'launched' @('--segment-id', "seg-$Tag", '--pid', '5151', '--created', (Get-UtcText (Get-Date)), '--boot-id', 'boot-fixture-1') | Out-Null
        }
        $admitted
    }

    # A stopped run: one full segment that the launcher finalized, then classified stopped.
    function New-StoppedRun([string]$RunId, [string]$Lane = '') {
        New-RegisteredRun $RunId $Lane
        Assert-Store 'request' @('--run-id', $RunId, '--started-by', 'human-command', '--request-id', "req0-$RunId") | Out-Null
        Invoke-FixtureLaunch $RunId "0-$RunId" | Out-Null
        Assert-Store 'complete_segment' @('--segment-id', "seg-0-$RunId", '--finalized-by', 'launcher', '--class', 'exited', '--session-total-usd', '1.5', '--exit-code', '0') | Out-Null
        Assert-Store 'classify' @('--run-id', $RunId, '--to', 'stopped', '--class', 'exited') | Out-Null
    }

    # A fake scheduler adapter (AC-D.6). Start plays the launcher for the run it starts:
    #   launch      accept, admit and launched
    #   accept_only accept and nothing more (the launcher is slow after the accept)
    #   none        nothing (the task never ran)
    function New-FakeScheduler([string]$Mode = 'launch') {
        $state = @{
            Mode = $Mode; Calls = [System.Collections.Generic.List[string]]::new(); Count = 0
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
                if ($state.Mode -eq 'none') { return }
                $tag = "$TaskName-$($state.Count)-$([guid]::NewGuid().ToString('N').Substring(0, 6))"
                $created = & $state.Utc ((Get-Date).AddMinutes(-1))
                $res = & $state.Store $state.Py $state.Tool $state.EffectLog $state.Db 'accept' @('--run-id', $TaskName, '--launcher-pid', '4242',
                    '--launcher-created', $created, '--boot-id', 'boot-fixture-1', '--win-session', '1', '--attempt-id', "att-$tag", '--dispatch-id', "disp-$tag")
                if ($res.Code -ne 0 -or $state.Mode -eq 'accept_only') { return }
                $res = & $state.Store $state.Py $state.Tool $state.EffectLog $state.Db 'admit' @('--attempt-id', "att-$tag", '--segment-id', "seg-$tag")
                if ($res.Code -ne 0 -or ($res.Out | ConvertFrom-Json).outcome -ne 'admitted') { return }
                $null = & $state.Store $state.Py $state.Tool $state.EffectLog $state.Db 'launched' @('--segment-id', "seg-$tag", '--pid', '5151',
                    '--created', (& $state.Utc (Get-Date)), '--boot-id', 'boot-fixture-1')
            }.GetNewClosure()
        }
    }

    # Run Start-CreditsRunTask.ps1 in this process. Returns Code, Payload (the last JSON line),
    # Thrown and Elapsed; a missing script or a throw fails the test, not the container.
    function Invoke-Caller {
        param([string]$RunId, [hashtable]$Scheduler, [hashtable]$Extra = @{})
        $params = @{
            RunId = $RunId; StartedBy = 'human-command'; StateDb = $script:Db; Scheduler = $Scheduler
            AcceptTimeoutMs = 300; PollIntervalMs = 50; OutcomeTimeoutMs = 1500
        }
        foreach ($k in $Extra.Keys) { $params[$k] = $Extra[$k] }
        $global:LASTEXITCODE = 0
        $lines = @(); $thrown = $null
        $watch = [System.Diagnostics.Stopwatch]::StartNew()
        try { $lines = @(& $script:Caller @params 2>$null) } catch { $thrown = $_.Exception.Message }
        $watch.Stop()
        $code = $global:LASTEXITCODE
        $payload = $null
        $last = @($lines | ForEach-Object { "$_" } | Where-Object { $_.TrimStart().StartsWith('{') }) | Select-Object -Last 1
        if ($last) { try { $payload = $last | ConvertFrom-Json -ErrorAction Stop } catch { $payload = $null } }
        [pscustomobject]@{ Code = $code; Payload = $payload; Thrown = $thrown; Elapsed = $watch.Elapsed }
    }

    Assert-Store 'init' | Out-Null
}

AfterAll {
    $env:CREDITS_TEST_EFFECT_LOG = $script:SavedEffectLog
    $env:CREDITS_CONFIG = $script:SavedConfig
    if ($script:Root -and (Test-Path -LiteralPath $script:Root)) { Remove-Item -LiteralPath $script:Root -Recurse -Force -ErrorAction SilentlyContinue }
}

Describe 'AC-D.2: one request, one task start, the launcher accepts' {
    It 'AC-D.2: the launcher accepts and launches → outcome launched, exit 0, one request, one Start call' {
        $run = New-Id 'd2-launch'
        New-RegisteredRun $run
        $fake = New-FakeScheduler 'launch'
        $res = Invoke-Caller -RunId $run -Scheduler $fake
        $res.Thrown | Should -BeNullOrEmpty
        $res.Code | Should -Be 0
        $res.Payload.outcome | Should -Be 'launched'
        $requests = Get-Requests $run
        $requests.Count | Should -Be 1
        $res.Payload.request_id | Should -Be $requests[0].request_id
        $requests[0].state | Should -Be 'launched'
        @($fake.State.Calls | Where-Object { $_ -eq "Start:\{{PROJECT_NAME_TITLE}}\Credits\$run" }).Count | Should -Be 1
        (Get-Run $run).state | Should -Be 'running'
    }

    It 'AC-D.2: a human-command start records the user and machine names in requested_by' {
        $run = New-Id 'd2-human'
        New-RegisteredRun $run
        $res = Invoke-Caller -RunId $run -Scheduler (New-FakeScheduler 'launch')
        $res.Code | Should -Be 0
        $request = (Get-Requests $run)[0]
        $request.started_by | Should -Be 'human-command'
        $request.requested_by | Should -BeLike "*$([Environment]::UserName)*"
        $request.requested_by | Should -BeLike "*$([Environment]::MachineName)*"
    }

    It 'AC-D.2: an agent-on-user-chat start stores the quote' {
        $run = New-Id 'd2-quote'
        New-RegisteredRun $run
        $quote = 'start the fixture run now'
        $res = Invoke-Caller -RunId $run -Scheduler (New-FakeScheduler 'launch') -Extra @{ StartedBy = 'agent-on-user-chat'; StartQuote = $quote }
        $res.Code | Should -Be 0
        (Get-Requests $run)[0].start_quote | Should -Be $quote
    }

    It 'AC-D.2 negative: an agent-on-user-chat start with no quote → refused, exit 3, no request, no Start call' {
        $run = New-Id 'd2-noquote'
        New-RegisteredRun $run
        $fake = New-FakeScheduler 'launch'
        $res = Invoke-Caller -RunId $run -Scheduler $fake -Extra @{ StartedBy = 'agent-on-user-chat' }
        $res.Code | Should -Be 3
        $res.Payload.outcome | Should -Be 'refused'
        $res.Payload.reason | Should -Be 'quote_required'
        (Get-Requests $run).Count | Should -Be 0
        @($fake.State.Calls | Where-Object { $_ -like 'Start:*' }).Count | Should -Be 0
        (Get-Run $run).state | Should -Be 'registered'
    }

    It 'AC-D.2 negative: a second start while a request is pending → refused, exit 3, no Start call, the first request stays pending' {
        $run = New-Id 'd2-pending'
        New-RegisteredRun $run
        Assert-Store 'request' @('--run-id', $run, '--started-by', 'human-command', '--request-id', "req-first-$run") | Out-Null
        $fake = New-FakeScheduler 'launch'
        $res = Invoke-Caller -RunId $run -Scheduler $fake
        $res.Code | Should -Be 3
        $res.Payload.outcome | Should -Be 'refused'
        @($fake.State.Calls | Where-Object { $_ -like 'Start:*' }).Count | Should -Be 0
        $requests = Get-Requests $run
        $requests.Count | Should -Be 1
        $requests[0].state | Should -Be 'pending'
    }

    It 'AC-D.2 negative: the launcher never accepts → not_started caller_timeout, the run goes back to registered, exit not 0' {
        $run = New-Id 'd2-timeout'
        New-RegisteredRun $run
        $fake = New-FakeScheduler 'none'
        $res = Invoke-Caller -RunId $run -Scheduler $fake
        $res.Thrown | Should -BeNullOrEmpty
        $res.Code | Should -Not -Be 0
        $res.Payload.outcome | Should -Be 'not_started'
        $res.Payload.reason | Should -Be 'caller_timeout'
        $res.Elapsed.TotalSeconds | Should -BeLessThan 30 -Because 'the test timeout is 300 ms, not the 120 s default'
        $request = (Get-Requests $run)[0]
        $request.state | Should -Be 'not_started'
        $request.reason | Should -Be 'caller_timeout'
        (Get-Run $run).state | Should -Be 'registered'
    }

    It 'AC-D.2: a not_started run can be started again' {
        $run = New-Id 'd2-again'
        New-RegisteredRun $run
        (Invoke-Caller -RunId $run -Scheduler (New-FakeScheduler 'none')).Payload.outcome | Should -Be 'not_started'
        $res = Invoke-Caller -RunId $run -Scheduler (New-FakeScheduler 'launch')
        $res.Code | Should -Be 0
        $res.Payload.outcome | Should -Be 'launched'
        (Get-Requests $run).Count | Should -Be 2
    }

    It 'AC-D.2: the budget floor rejects the first start → outcome rejected, the run failed' {
        $run = New-Id 'd2-floor'
        New-RegisteredRun $run -SegmentCap 4.0 -RunCap 4.0
        $res = Invoke-Caller -RunId $run -Scheduler (New-FakeScheduler 'launch')
        $res.Payload.outcome | Should -Be 'rejected'
        $res.Payload.reason | Should -Be 'budget_floor'
        (Get-Run $run).state | Should -Be 'failed'
    }
}

Describe 'AC-D.2: the caller times out while the launcher accepts (MX-6)' {
    It 'mx_6_ AC-D.2: accepted but no outcome before the caller timeout → accepted_pending, exit 4, no not_started' {
        $run = New-Id 'mx6-pending'
        New-RegisteredRun $run
        $fake = New-FakeScheduler 'accept_only'
        $res = Invoke-Caller -RunId $run -Scheduler $fake
        $res.Thrown | Should -BeNullOrEmpty
        $res.Code | Should -Be 4
        $res.Payload.outcome | Should -Be 'accepted_pending'
        $requests = Get-Requests $run
        $requests.Count | Should -Be 1
        $requests[0].state | Should -Be 'accepted'
        @(Get-Rows "SELECT * FROM requests WHERE run_id = ? AND state = 'not_started'" @($run)).Count | Should -Be 0
        (Get-Run $run).state | Should -Be 'launching'
    }

    It 'mx_6_ AC-D.2: accepted_pending names the dispatch id of the attempt' {
        $run = New-Id 'mx6-dispatch'
        New-RegisteredRun $run
        $res = Invoke-Caller -RunId $run -Scheduler (New-FakeScheduler 'accept_only')
        $attempt = @(Get-Rows 'SELECT * FROM attempts WHERE run_id = ?' @($run)) | Select-Object -First 1
        $res.Payload.dispatch_id | Should -Be $attempt.dispatch_id
    }
}

Describe 'AC-D.2: a refused resume (MX-5)' {
    It 'mx_5_ AC-D.2: a resume refused at admit (lane busy) → outcome rejected, the run stopped, one resume_refused notice; a new resume request works' {
        $lane = "tree:$script:Project/mx5-shared-$([guid]::NewGuid().ToString('N').Substring(0, 6))"
        $stopped = New-Id 'mx5-stopped'
        New-StoppedRun $stopped $lane
        (Get-Run $stopped).state | Should -Be 'stopped'
        # Another run holds the same lane with a running segment.
        $holder = New-Id 'mx5-holder'
        New-RegisteredRun $holder $lane
        Assert-Store 'request' @('--run-id', $holder, '--started-by', 'human-command') | Out-Null
        (Invoke-FixtureLaunch $holder "h-$holder").outcome | Should -Be 'admitted'

        $res = Invoke-Caller -RunId $stopped -Scheduler (New-FakeScheduler 'launch') -Extra @{ Resume = $true }
        $res.Thrown | Should -BeNullOrEmpty
        $res.Payload.outcome | Should -Be 'rejected'
        $res.Payload.reason | Should -Be 'lane_busy'
        (Get-Run $stopped).state | Should -Be 'stopped'
        @(Get-Rows "SELECT * FROM notices WHERE run_id = ? AND kind = 'resume_refused'" @($stopped)).Count | Should -Be 1

        $again = Invoke-Caller -RunId $stopped -Scheduler (New-FakeScheduler 'accept_only') -Extra @{ Resume = $true }
        $again.Payload.outcome | Should -Be 'accepted_pending'
        @(Get-Requests $stopped | Where-Object { $_.resume -eq 1 }).Count | Should -Be 2
    }

    It 'AC-D.2 negative: a resume of a run that is not stopped → refused, no request' {
        $run = New-Id 'd2-resume-reg'
        New-RegisteredRun $run
        $fake = New-FakeScheduler 'launch'
        $res = Invoke-Caller -RunId $run -Scheduler $fake -Extra @{ Resume = $true }
        $res.Code | Should -Be 3
        $res.Payload.outcome | Should -Be 'refused'
        (Get-Requests $run).Count | Should -Be 0
        @($fake.State.Calls | Where-Object { $_ -like 'Start:*' }).Count | Should -Be 0
    }
}

Describe 'AC-D.2: the wait constants' {
    It 'AC-D.2: Get-CreditsConstants gives REQUEST_ACCEPT_TIMEOUT_S 120 and ORPHAN_REQUEST_S 150' {
        if (-not (Get-Module -Name CreditsRun)) { Import-Module -Name $script:Module -Force -DisableNameChecking -ErrorAction Stop }
        $c = Get-CreditsConstants
        $c.REQUEST_ACCEPT_TIMEOUT_S | Should -Be 120
        $c.ORPHAN_REQUEST_S | Should -Be 150
    }
}

Describe 'AC-D.6: no test starts a real task' {
    It 'AC-D.6: no run id of this file has a real task under \{{PROJECT_NAME_TITLE}}\Credits\' {
        $found = @(foreach ($id in $script:RunIds) {
                Get-ScheduledTask -TaskPath '\{{PROJECT_NAME_TITLE}}\Credits\' -TaskName $id -ErrorAction SilentlyContinue
            })
        $found.Count | Should -Be 0
    }
}
