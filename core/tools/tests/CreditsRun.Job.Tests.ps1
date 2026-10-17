# S2a job helper (Component B of docs/execution/plans/2026-10-15-scheduled-credits-runs).
# AC-B.7 the named kill-on-close job, a child created suspended inside it, and the job proof
# (live, empty, gone, unknown; report section 4.4, R5-d, R6-c). AC-B.8 Complete-CreditsSegment is
# idempotent (MX-3, MX-8).
#
# The children are short Python scripts on the base interpreter. Every store is a temp file
# (AC-B.10): the real store is never opened. Store effects go to a test effect log, so no test
# writes the Application event log.

BeforeAll {
    $script:Repo = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
    $script:Module = Join-Path $script:Repo '.agent/skills/claude-credits/CreditsRun.psm1'
    $script:StateTool = Join-Path $script:Repo 'tools/credits_state.py'
    $script:Root = "{{RECEIPTS_DIR}}/credits-job-tests/$([guid]::NewGuid().ToString('N'))"
    New-Item -ItemType Directory -Force -Path $script:Root | Out-Null
    $script:EffectLog = "$script:Root/effects.jsonl"

    $venvPy = Join-Path $script:Repo '.venv/Scripts/python.exe'
    $script:Py = if (Test-Path -LiteralPath $venvPy) { $venvPy } else { (Get-Command python -ErrorAction Stop).Source }
    $script:BasePython = (& $script:Py -c 'import sys; print(sys._base_executable)' | Out-String).Trim()

    # The child writes its pid to the marker file, then sleeps. A marker that is absent proves
    # that the child has not run yet.
    $script:ChildPy = "$script:Root/child.py"
    Set-Content -LiteralPath $script:ChildPy -Encoding utf8NoBOM -Value @'
import os
import sys
import time

with open(sys.argv[1], "w", encoding="utf-8") as f:
    f.write(str(os.getpid()))
time.sleep(float(sys.argv[2]))
'@

    function New-Id([string]$Prefix) { "$Prefix-$([guid]::NewGuid().ToString('N').Substring(0, 10))" }

    # The module is imported in each test, not here: a missing module fails the tests, not the
    # container.
    function Import-CreditsRun {
        if (-not (Get-Module -Name CreditsRun)) { Import-Module -Name $script:Module -Force -DisableNameChecking -ErrorAction Stop }
    }

    function Start-JobChild($Job, [string]$Marker, [int]$Seconds = 60) {
        Start-CreditsJobProcess -Job $Job -FilePath $script:BasePython `
            -CommandLine "-X utf8 `"$script:ChildPy`" `"$Marker`" $Seconds" -WorkingDirectory $script:Root
    }

    function Wait-Until([scriptblock]$Condition, [int]$Seconds = 20) {
        $deadline = (Get-Date).AddSeconds($Seconds)
        while ((Get-Date) -lt $deadline) { if (& $Condition) { return $true }; Start-Sleep -Milliseconds 200 }
        return [bool](& $Condition)
    }

    function Test-Alive([int]$ProcessId) { $null -ne (Get-Process -Id $ProcessId -ErrorAction SilentlyContinue) }

    # One credits_state.py call with no inherited CREDITS_* value and the test effect log.
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
        $payload = $null
        try { $payload = $so.Result | ConvertFrom-Json -ErrorAction Stop } catch { $payload = $null }
        [pscustomobject]@{ Code = $p.ExitCode; Payload = $payload; Out = $so.Result; Err = $se.Result }
    }

    function Assert-Store([string]$Db, [string]$Verb, [string[]]$Arguments = @()) {
        $res = Invoke-Store $Db $Verb $Arguments
        if ($res.Code -ne 0) { throw "store $Verb failed: exit=$($res.Code) out=$($res.Out) err=$($res.Err)" }
        $res.Payload
    }

    # Rows of one read-only query, as objects.
    function Get-Rows([string]$Db, [string]$Sql) {
        $code = 'import json, sqlite3, sys; c = sqlite3.connect("file:" + sys.argv[1] + "?mode=ro", uri=True); c.row_factory = sqlite3.Row; print(json.dumps([dict(r) for r in c.execute(sys.argv[2])]))'
        $text = (& $script:Py -X utf8 -c $code $Db $Sql | Out-String)
        @($text | ConvertFrom-Json)
    }

    function Get-UtcText([datetime]$Value) { $Value.ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ') }

    # A scheduled-style segment that holds a lane and a reservation: register, registered,
    # request, accept, admit, launched (report section 4.7 lifecycle).
    function New-LaunchedSegment([string]$Db, [string]$RunId) {
        $manifest = "$script:Root/manifest-$RunId.json"
        $doc = [ordered]@{
            schema = 'credits-run.v1'; run_id = $RunId; kind = 'exec'
            project_root = 'X:/fixture-project'; plan_folder = 'docs/execution/plans/2026-10-15-fixture/'
            brief = "$script:Root/brief.md"
            launch = [ordered]@{
                working_directory = 'X:/fixture-project'; claude_exe = 'C:/fixture/claude.cmd'; python_exe = 'C:/fixture/python.exe'
                permission_mode = 'bypassPermissions'; model = 'fixture-model'; effort = 'high'; segment_cap_usd = 75.0; timeout_sec = 43200
            }
            budget = [ordered]@{ run_cap_usd = 200.0 }
            messaging = [ordered]@{ orchestrator_sessions = @('00000000-0000-4000-8000-0000000000aa'); ruling_enabled = $false; gate_wait_max_min = 0 }
            depends_on = @(); lane = "tree:X:/fixture-tree-$RunId"
        }
        Set-Content -LiteralPath $manifest -Value ($doc | ConvertTo-Json -Depth 6) -Encoding utf8NoBOM
        $session = [guid]::NewGuid().ToString().ToLowerInvariant()
        $segment = "seg-$RunId"
        Assert-Store $Db 'register' @('--run-id', $RunId, '--manifest', $manifest, '--cli-version', '9.9.9', '--kit-revision', 'kitrev-fixture') | Out-Null
        Assert-Store $Db 'registered' @('--run-id', $RunId, '--task-hash', "taskhash-$RunId") | Out-Null
        Assert-Store $Db 'request' @('--run-id', $RunId, '--started-by', 'human-command', '--request-id', "req-$RunId") | Out-Null
        Assert-Store $Db 'accept' @('--run-id', $RunId, '--launcher-pid', '4242', '--launcher-created', (Get-UtcText (Get-Date).AddMinutes(-10)),
            '--boot-id', 'boot-fixture-1', '--win-session', '1', '--attempt-id', "att-$RunId", '--dispatch-id', "disp-$RunId",
            '--expected-session-id', $session) | Out-Null
        Assert-Store $Db 'admit' @('--attempt-id', "att-$RunId", '--segment-id', $segment) | Out-Null
        Assert-Store $Db 'launched' @('--segment-id', $segment, '--pid', '5151', '--created', (Get-UtcText (Get-Date)), '--boot-id', 'boot-fixture-1') | Out-Null
        $segment
    }

    # Everything complete_segment may change, as one comparable text.
    function Get-ReleaseState([string]$Db, [string]$Segment) {
        $parts = @(
            Get-Rows $Db 'SELECT lane, segment_id, claimed_utc FROM lanes ORDER BY lane'
            Get-Rows $Db "SELECT state, finalized_utc, finalized_by, reservation_usd, reservation_released_utc FROM segments WHERE segment_id = '$Segment'"
            Get-Rows $Db 'SELECT * FROM exposures ORDER BY segment_id'
            Get-Rows $Db 'SELECT COUNT(*) AS n FROM transitions'
        )
        $parts | ConvertTo-Json -Depth 4 -Compress
    }
}

AfterAll {
    if ($script:Root -and (Test-Path -LiteralPath $script:Root)) { Remove-Item -LiteralPath $script:Root -Recurse -Force -ErrorAction SilentlyContinue }
}

Describe 'AC-B.7: the named kill-on-close job and a child created suspended inside it' {
    It 'AC-B.7: New-CreditsJob names the job Local\{{PROJECT_NAME_UPPER}}Credits- plus the segment id' {
        Import-CreditsRun
        $seg = New-Id 'b7-name'
        $job = New-CreditsJob -SegmentId $seg
        try {
            $job.Name | Should -Be "Local\{{PROJECT_NAME_UPPER}}Credits-$seg"
            Get-CreditsJobActiveCount -Job $job | Should -Be 0
        } finally { Close-CreditsJob -Job $job }
    }

    It 'AC-B.7: the child is created suspended inside the job, runs only after the resume, and the proof is live' {
        Import-CreditsRun
        $seg = New-Id 'b7-live'; $marker = "$script:Root/$seg.marker"
        $job = New-CreditsJob -SegmentId $seg
        try {
            $child = Start-JobChild $job $marker 60
            $child.ProcessId | Should -BeGreaterThan 0
            Get-CreditsJobActiveCount -Job $job | Should -Be 1 -Because 'the child is inside the job from its creation'
            Start-Sleep -Milliseconds 1500
            Test-Path -LiteralPath $marker | Should -BeFalse -Because 'a suspended child has not run'
            Resume-CreditsJobProcess -Child $child
            Wait-Until { Test-Path -LiteralPath $marker } | Should -BeTrue
            $proof = Get-CreditsJobProof -JobName $job.Name -LauncherSession ([System.Diagnostics.Process]::GetCurrentProcess().SessionId) `
                -BootId (Get-CreditsBootId) -Processes @(@{ pid = $child.ProcessId; created = $child.CreationUtc })
            $proof.Result | Should -Be 'live'
        } finally { Stop-CreditsJob -Job $job; Close-CreditsJob -Job $job }
    }

    It 'AC-B.7: Stop-CreditsJob ends every member (empty), and after the last handle closes the proof is gone' {
        Import-CreditsRun
        $seg = New-Id 'b7-gone'; $marker = "$script:Root/$seg.marker"
        $job = New-CreditsJob -SegmentId $seg
        $child = Start-JobChild $job $marker 60
        Resume-CreditsJobProcess -Child $child
        Wait-Until { Test-Path -LiteralPath $marker } | Should -BeTrue
        $session = [System.Diagnostics.Process]::GetCurrentProcess().SessionId
        $procs = @(@{ pid = $child.ProcessId; created = $child.CreationUtc })
        Stop-CreditsJob -Job $job
        Get-CreditsJobActiveCount -Job $job | Should -Be 0
        (Get-CreditsJobProof -JobName $job.Name -LauncherSession $session -BootId (Get-CreditsBootId) -Processes $procs).Result | Should -Be 'empty'
        Close-CreditsJob -Job $job
        (Get-CreditsJobProof -JobName $job.Name -LauncherSession $session -BootId (Get-CreditsBootId) -Processes $procs).Result | Should -Be 'gone'
    }

    It 'AC-B.7: closing the only job handle ends a running child (kill on close)' {
        Import-CreditsRun
        $seg = New-Id 'b7-close'; $marker = "$script:Root/$seg.marker"
        $job = New-CreditsJob -SegmentId $seg
        $child = Start-JobChild $job $marker 120
        Resume-CreditsJobProcess -Child $child
        Wait-Until { Test-Path -LiteralPath $marker } | Should -BeTrue
        Test-Alive $child.ProcessId | Should -BeTrue
        Close-CreditsJob -Job $job
        Wait-Until { -not (Test-Alive $child.ProcessId) } | Should -BeTrue -Because 'kill-on-close ends the members when the last handle closes'
    }

    It 'AC-B.7 negative: a second job with the same segment id is refused, so the wrapper never shares the handle' {
        Import-CreditsRun
        $seg = New-Id 'b7-dup'
        $job = New-CreditsJob -SegmentId $seg
        try {
            { New-CreditsJob -SegmentId $seg } | Should -Throw
        } finally { Close-CreditsJob -Job $job }
    }
}

Describe 'AC-B.7: the job proof with injected observations (report section 4.4, R5-d)' {
    BeforeAll {
        $script:Session = [System.Diagnostics.Process]::GetCurrentProcess().SessionId
        $script:DeadProcs = @(@{ pid = 999999; created = '2026-10-15T12:00:00Z' })
    }

    It 'AC-B.7: injected open with <Count> active processes → <Want>' -ForEach @(
        @{ Count = 3; Want = 'live' }
        @{ Count = 0; Want = 'empty' }
    ) {
        Import-CreditsRun
        $proof = Get-CreditsJobProof -JobName 'Local\{{PROJECT_NAME_UPPER}}Credits-b7-inject' -LauncherSession $script:Session -BootId (Get-CreditsBootId) `
            -Processes $script:DeadProcs -Observation @{ open_error = 0; active_processes = $Count }
        $proof.Result | Should -Be $Want
    }

    It 'AC-B.7: a different boot id → empty, whatever the lookup returns' {
        Import-CreditsRun
        $proof = Get-CreditsJobProof -JobName 'Local\{{PROJECT_NAME_UPPER}}Credits-b7-boot' -LauncherSession $script:Session -BootId 'bootid:fixture-old' `
            -Processes $script:DeadProcs -Observation @{ open_error = 5 }
        $proof.Result | Should -Be 'empty'
    }

    It 'AC-B.7: not found in the launcher session with every recorded pid dead → gone' {
        Import-CreditsRun
        $proof = Get-CreditsJobProof -JobName "Local\{{PROJECT_NAME_UPPER}}Credits-$(New-Id 'b7-absent')" -LauncherSession $script:Session `
            -BootId (Get-CreditsBootId) -Processes $script:DeadProcs
        $proof.Result | Should -Be 'gone'
    }

    It 'AC-B.7: a live pid with another creation time is a reused pid and counts as dead → gone' {
        Import-CreditsRun
        $me = (Get-Process -Id $PID).StartTime.ToUniversalTime().AddHours(-1)
        $proof = Get-CreditsJobProof -JobName "Local\{{PROJECT_NAME_UPPER}}Credits-$(New-Id 'b7-reused')" -LauncherSession $script:Session `
            -BootId (Get-CreditsBootId) -Processes @(@{ pid = $PID; created = (Get-UtcText $me) })
        $proof.Result | Should -Be 'gone'
    }

    It 'AC-B.7 negative: an injected access error → unknown (MX-30)' {
        Import-CreditsRun
        $proof = Get-CreditsJobProof -JobName 'Local\{{PROJECT_NAME_UPPER}}Credits-b7-denied' -LauncherSession $script:Session -BootId (Get-CreditsBootId) `
            -Processes $script:DeadProcs -Observation @{ open_error = 5 }
        $proof.Result | Should -Be 'unknown'
    }

    It 'AC-B.7 negative: not found while a recorded pid lives → unknown (MX-30)' {
        Import-CreditsRun
        $me = (Get-Process -Id $PID).StartTime.ToUniversalTime()
        $proof = Get-CreditsJobProof -JobName "Local\{{PROJECT_NAME_UPPER}}Credits-$(New-Id 'b7-alive')" -LauncherSession $script:Session `
            -BootId (Get-CreditsBootId) -Processes @(@{ pid = $PID; created = (Get-UtcText $me) })
        $proof.Result | Should -Be 'unknown'
    }

    It 'AC-B.7 negative: not found from another Windows session → unknown' {
        Import-CreditsRun
        $proof = Get-CreditsJobProof -JobName "Local\{{PROJECT_NAME_UPPER}}Credits-$(New-Id 'b7-session')" -LauncherSession $script:Session `
            -BootId (Get-CreditsBootId) -Processes $script:DeadProcs -Observation @{ current_session = $script:Session + 1 }
        $proof.Result | Should -Be 'unknown'
    }
}

Describe 'AC-B.8: Complete-CreditsSegment is idempotent (MX-3, MX-8)' {
    BeforeAll {
        $script:Db = "$script:Root/b8-state.db"
        Assert-Store $script:Db 'init' | Out-Null
        $script:Seg8 = New-LaunchedSegment $script:Db (New-Id 'b8')
    }

    It 'AC-B.8: the first call finalizes the segment and releases the lane and the reservation once' {
        Import-CreditsRun
        @(Get-Rows $script:Db 'SELECT lane FROM lanes WHERE segment_id IS NOT NULL').Count | Should -Be 1
        $out = Complete-CreditsSegment -StateDb $script:Db -SegmentId $script:Seg8 -FinalizedBy launcher -Class exited -SessionTotalUsd 1.25
        $out.result | Should -Be 'changed'
        @(Get-Rows $script:Db 'SELECT lane FROM lanes WHERE segment_id IS NOT NULL').Count | Should -Be 0
        $row = (Get-Rows $script:Db "SELECT finalized_by, reservation_released_utc FROM segments WHERE segment_id = '$script:Seg8'")[0]
        $row.finalized_by | Should -Be 'launcher'
        $row.reservation_released_utc | Should -Not -BeNullOrEmpty
    }

    It 'AC-B.8 negative: a second call is no_change and leaves the lanes, the reservation and the counts as they were' {
        Import-CreditsRun
        $before = Get-ReleaseState $script:Db $script:Seg8
        $out = Complete-CreditsSegment -StateDb $script:Db -SegmentId $script:Seg8 -FinalizedBy launcher -Class exited -SessionTotalUsd 1.25
        $out.result | Should -Be 'no_change'
        Get-ReleaseState $script:Db $script:Seg8 | Should -Be $before
    }

    It 'AC-B.8 negative: a refused call (unknown segment) throws and changes nothing' {
        Import-CreditsRun
        $before = Get-ReleaseState $script:Db $script:Seg8
        { Complete-CreditsSegment -StateDb $script:Db -SegmentId 'seg-missing' -FinalizedBy launcher -Class exited } | Should -Throw
        Get-ReleaseState $script:Db $script:Seg8 | Should -Be $before
    }
}
