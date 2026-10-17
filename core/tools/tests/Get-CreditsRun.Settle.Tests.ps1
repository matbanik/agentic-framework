# S2a settle (Component B of docs/execution/plans/2026-10-15-scheduled-credits-runs).
# AC-B.5 Get-CreditsRun.ps1 -Settle closes a crash exposure only on Console evidence or a noted
# human adjustment (report sections 4.1 and 4.5, R4-b). The transcript sum never settles one.
#
# Each test gets its own run and segment: complete_segment with no session total leaves the
# segment's reservation as an open exposure. Every store is a temp file (AC-B.10).

BeforeAll {
    $script:Repo = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
    $script:GetRun = Join-Path $script:Repo '.agent/skills/claude-credits/Get-CreditsRun.ps1'
    $script:StateTool = Join-Path $script:Repo 'tools/credits_state.py'
    $script:Root = "{{RECEIPTS_DIR}}/credits-settle-tests/$([guid]::NewGuid().ToString('N'))"
    New-Item -ItemType Directory -Force -Path $script:Root | Out-Null
    $script:EffectLog = "$script:Root/effects.jsonl"
    $script:Db = "$script:Root/state.db"

    $venvPy = Join-Path $script:Repo '.venv/Scripts/python.exe'
    $script:Py = if (Test-Path -LiteralPath $venvPy) { $venvPy } else { (Get-Command python -ErrorAction Stop).Source }

    function New-Id([string]$Prefix) { "$Prefix-$([guid]::NewGuid().ToString('N').Substring(0, 10))" }

    # Start a process with no inherited CREDITS_* value, plus the test effect log.
    function Start-Clean([string]$File, [string[]]$Arguments) {
        $psi = [System.Diagnostics.ProcessStartInfo]::new($File)
        foreach ($a in $Arguments) { $psi.ArgumentList.Add([string]$a) }
        $psi.UseShellExecute = $false
        $psi.RedirectStandardOutput = $true
        $psi.RedirectStandardError = $true
        foreach ($name in @($psi.Environment.Keys)) {
            if ($name -like 'CREDITS_*' -or $name -in @('CLAUDECODE', 'CLAUDE_CODE_ENTRYPOINT')) { $null = $psi.Environment.Remove($name) }
        }
        $psi.Environment['CREDITS_TEST_EFFECT_LOG'] = $script:EffectLog
        $p = [System.Diagnostics.Process]::Start($psi)
        $so = $p.StandardOutput.ReadToEndAsync(); $se = $p.StandardError.ReadToEndAsync()
        if (-not $p.WaitForExit(120000)) { & taskkill.exe /PID $p.Id /T /F *> $null; throw "timed out: $File" }
        $p.WaitForExit()
        [pscustomobject]@{ Code = $p.ExitCode; Out = $so.Result; Err = $se.Result }
    }

    function Assert-Store([string]$Verb, [string[]]$Arguments = @()) {
        $res = Start-Clean $script:Py (@('-X', 'utf8', $script:StateTool, '--db', $script:Db, $Verb) + $Arguments)
        if ($res.Code -ne 0) { throw "store $Verb failed: exit=$($res.Code) out=$($res.Out) err=$($res.Err)" }
        $res.Out | ConvertFrom-Json
    }

    function Invoke-Settle([string[]]$Arguments) {
        Start-Clean 'pwsh' (@('-NoProfile', '-File', $script:GetRun, '-StateDb', $script:Db) + $Arguments)
    }

    function Get-Exposure([string]$Segment) {
        $code = 'import json, sqlite3, sys; c = sqlite3.connect("file:" + sys.argv[1] + "?mode=ro", uri=True); c.row_factory = sqlite3.Row; print(json.dumps([dict(r) for r in c.execute("SELECT * FROM exposures WHERE segment_id = ?", (sys.argv[2],))]))'
        @((& $script:Py -X utf8 -c $code $script:Db $Segment | Out-String) | ConvertFrom-Json)
    }

    function Get-UtcText([datetime]$Value) { $Value.ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ') }

    # A run whose one segment ended with no trusted total: its 75 USD reservation stays an open
    # exposure (report section 4.1).
    function New-OpenExposure {
        $runId = New-Id 'b5'
        $manifest = "$script:Root/manifest-$runId.json"
        $doc = [ordered]@{
            schema = 'credits-run.v1'; run_id = $runId; kind = 'exec'
            project_root = 'X:/fixture-project'; plan_folder = 'docs/execution/plans/2026-10-15-fixture/'
            brief = "$script:Root/brief.md"
            launch = [ordered]@{
                working_directory = 'X:/fixture-project'; claude_exe = 'C:/fixture/claude.cmd'; python_exe = 'C:/fixture/python.exe'
                permission_mode = 'bypassPermissions'; model = 'fixture-model'; effort = 'high'; segment_cap_usd = 75.0; timeout_sec = 43200
            }
            budget = [ordered]@{ run_cap_usd = 200.0 }
            messaging = [ordered]@{ orchestrator_sessions = @('00000000-0000-4000-8000-0000000000aa'); ruling_enabled = $false; gate_wait_max_min = 0 }
            depends_on = @(); lane = "tree:X:/fixture-tree-$runId"
        }
        Set-Content -LiteralPath $manifest -Value ($doc | ConvertTo-Json -Depth 6) -Encoding utf8NoBOM
        $segment = "seg-$runId"
        Assert-Store 'register' @('--run-id', $runId, '--manifest', $manifest, '--cli-version', '9.9.9', '--kit-revision', 'kitrev-fixture') | Out-Null
        Assert-Store 'registered' @('--run-id', $runId, '--task-hash', "taskhash-$runId") | Out-Null
        Assert-Store 'request' @('--run-id', $runId, '--started-by', 'human-command', '--request-id', "req-$runId") | Out-Null
        Assert-Store 'accept' @('--run-id', $runId, '--launcher-pid', '4242', '--launcher-created', (Get-UtcText (Get-Date).AddMinutes(-10)),
            '--boot-id', 'boot-fixture-1', '--win-session', '1', '--attempt-id', "att-$runId", '--dispatch-id', "disp-$runId",
            '--expected-session-id', [guid]::NewGuid().ToString().ToLowerInvariant()) | Out-Null
        Assert-Store 'admit' @('--attempt-id', "att-$runId", '--segment-id', $segment) | Out-Null
        Assert-Store 'launched' @('--segment-id', $segment, '--pid', '5151', '--created', (Get-UtcText (Get-Date)), '--boot-id', 'boot-fixture-1') | Out-Null
        Assert-Store 'complete_segment' @('--segment-id', $segment, '--finalized-by', 'launcher', '--class', 'crashed') | Out-Null
        $segment
    }

    Assert-Store 'init' | Out-Null
}

AfterAll {
    if ($script:Root -and (Test-Path -LiteralPath $script:Root)) { Remove-Item -LiteralPath $script:Root -Recurse -Force -ErrorAction SilentlyContinue }
}

Describe 'AC-B.5: -Settle releases an exposure only on evidence or a noted human adjustment' {
    It 'AC-B.5: the fixture leaves an open exposure' {
        $seg = New-OpenExposure
        $exp = Get-Exposure $seg
        $exp.Count | Should -Be 1
        $exp[0].state | Should -Be 'open'
    }

    It 'AC-B.5: -Source console -AmountUsd sets settled_console with the amount' {
        $seg = New-OpenExposure
        $res = Invoke-Settle @('-Settle', $seg, '-Source', 'console', '-AmountUsd', '3.5')
        $res.Code | Should -Be 0 -Because "$($res.Out) $($res.Err)"
        $exp = (Get-Exposure $seg)[0]
        $exp.state | Should -Be 'settled_console'
        [double]$exp.amount_usd | Should -Be 3.5
        $exp.settled_by | Should -Match '^console:'
        $exp.settled_utc | Should -Not -BeNullOrEmpty
    }

    It 'AC-B.5: -Source human -AmountUsd -Note is recorded as human_adjusted with the note and the OS user' {
        $seg = New-OpenExposure
        $res = Invoke-Settle @('-Settle', $seg, '-Source', 'human', '-AmountUsd', '4', '-Note', 'console page not open yet')
        $res.Code | Should -Be 0 -Because "$($res.Out) $($res.Err)"
        $exp = (Get-Exposure $seg)[0]
        $exp.state | Should -Be 'human_adjusted'
        [double]$exp.amount_usd | Should -Be 4
        $exp.note | Should -Be 'console page not open yet'
        $exp.settled_by | Should -Match ('^human:.*' + [regex]::Escape([Environment]::UserName))
    }

    It 'AC-B.5: an agent settle on the user''s words records -StartedBy agent-on-user-chat and the quote' {
        $seg = New-OpenExposure
        $quote = 'settle that crashed segment at four dollars'
        $res = Invoke-Settle @('-Settle', $seg, '-Source', 'human', '-AmountUsd', '4', '-Note', 'no console access', '-StartedBy', 'agent-on-user-chat', '-Quote', $quote)
        $res.Code | Should -Be 0 -Because "$($res.Out) $($res.Err)"
        $exp = (Get-Exposure $seg)[0]
        $exp.state | Should -Be 'human_adjusted'
        $exp.settled_by | Should -Match 'agent-on-user-chat'
        $exp.settled_by | Should -Match ([regex]::Escape($quote))
    }

    It 'AC-B.5 negative: -Source transcript is refused (transcript_not_evidence) and the exposure stays open' {
        $seg = New-OpenExposure
        $res = Invoke-Settle @('-Settle', $seg, '-Source', 'transcript', '-AmountUsd', '1')
        $res.Code | Should -Not -Be 0
        "$($res.Out) $($res.Err)" | Should -Match 'transcript_not_evidence'
        (Get-Exposure $seg)[0].state | Should -Be 'open'
    }

    It 'AC-B.5 negative: -Source human with no -Note is refused (note_required) and the exposure stays open' {
        $seg = New-OpenExposure
        $res = Invoke-Settle @('-Settle', $seg, '-Source', 'human', '-AmountUsd', '1')
        $res.Code | Should -Not -Be 0
        "$($res.Out) $($res.Err)" | Should -Match 'note_required'
        (Get-Exposure $seg)[0].state | Should -Be 'open'
    }

    It 'AC-B.5 negative: -StartedBy agent-on-user-chat with no -Quote is refused (quote_required) and the exposure stays open' {
        $seg = New-OpenExposure
        $res = Invoke-Settle @('-Settle', $seg, '-Source', 'console', '-AmountUsd', '1', '-StartedBy', 'agent-on-user-chat')
        $res.Code | Should -Not -Be 0
        "$($res.Out) $($res.Err)" | Should -Match 'quote_required'
        (Get-Exposure $seg)[0].state | Should -Be 'open'
    }

    It 'AC-B.5 negative: a second settle of the same segment is refused (no_exposure) and keeps the first amount' {
        $seg = New-OpenExposure
        (Invoke-Settle @('-Settle', $seg, '-Source', 'console', '-AmountUsd', '2')).Code | Should -Be 0
        $res = Invoke-Settle @('-Settle', $seg, '-Source', 'console', '-AmountUsd', '9')
        $res.Code | Should -Not -Be 0
        "$($res.Out) $($res.Err)" | Should -Match 'no_exposure'
        [double](Get-Exposure $seg)[0].amount_usd | Should -Be 2
    }
}
