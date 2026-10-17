# S2a manual supervision (Component B of docs/execution/plans/2026-10-15-scheduled-credits-runs).
# AC-B.9 Invoke-ClaudeCredits.ps1 -RunId -SessionId follows report section 7.2 steps 1 to 5: the
# job, register_minimal with the wrapper identity (R7-c), the child created suspended inside the
# job, manual_identity, then the resume with CREDITS_RUN_ID, CREDITS_STATE_DB and CREDITS_SEGMENT
# only (R6-c). When the wrapper ends, it calls complete_segment (MX-35, MX-43).
#
# Every run goes to a mock `claude` that records its argv, its pid, its parent pid, its CREDITS_*
# environment and the segment row it reads from the store at its own start. The key file holds a
# fake key. Every store is a temp file (AC-B.10); store effects go to a test effect log. Each child
# gets its own environment block without CLAUDECODE and CLAUDE_CODE_ENTRYPOINT; this process's
# environment is never changed.

BeforeAll {
    $script:Repo = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
    $script:Credits = Join-Path $script:Repo '.agent/skills/claude-credits/Invoke-ClaudeCredits.ps1'
    $script:Module = Join-Path $script:Repo '.agent/skills/claude-credits/CreditsRun.psm1'
    $script:StateTool = Join-Path $script:Repo 'tools/credits_state.py'
    $script:Root = "{{RECEIPTS_DIR}}/credits-manual-tests/$([guid]::NewGuid().ToString('N'))"
    $script:Out = "$script:Root/dispatch"
    $script:WorkDir = "$script:Root/work"
    New-Item -ItemType Directory -Force -Path $script:Out, $script:WorkDir | Out-Null
    $script:EffectLog = "$script:Root/effects.jsonl"
    $script:Db = "$script:Root/state.db"

    $script:KeyFile = "$script:Root/fake.key"
    Set-Content -LiteralPath $script:KeyFile -Value ('sk-' + 'ant-api03-' + ('A' * 40)) -Encoding utf8NoBOM
    $script:Prompt = "$script:Root/prompt.md"
    Set-Content -LiteralPath $script:Prompt -Value 'credits manual supervision test prompt' -Encoding utf8NoBOM

    $venvPy = Join-Path $script:Repo '.venv/Scripts/python.exe'
    $script:Py = if (Test-Path -LiteralPath $venvPy) { $venvPy } else { (Get-Command python -ErrorAction Stop).Source }
    $script:BasePython = (& $script:Py -c 'import sys; print(sys._base_executable)' | Out-String).Trim()
    $mockPy = "$script:Root/mock_claude.py"
    Set-Content -LiteralPath $mockPy -Encoding utf8NoBOM -Value @'
import json
import os
import sqlite3
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
seen = None
db = os.environ.get("CREDITS_STATE_DB")
segment = os.environ.get("CREDITS_SEGMENT")
if db and segment:
    con = sqlite3.connect("file:" + db.replace("\\", "/") + "?mode=ro", uri=True)
    row = con.execute(
        "SELECT state, pid FROM segments WHERE segment_id = ?", (segment,)
    ).fetchone()
    con.close()
    seen = None if row is None else {"state": row[0], "pid": row[1]}
argv_file = os.environ.get("MOCK_ARGV_FILE")
if argv_file:
    with open(argv_file, "w", encoding="utf-8") as f:
        json.dump(
            {
                "argv": args,
                "pid": os.getpid(),
                "ppid": os.getppid(),
                "seen": seen,
                "env": {
                    k.upper(): v
                    for k, v in os.environ.items()
                    if k.upper().startswith("CREDITS_")
                },
            },
            f,
        )
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

    $script:Strip = @('CLAUDECODE', 'CLAUDE_CODE_ENTRYPOINT')

    # Start pwsh -File <Script> <Arguments> with this process's environment minus CLAUDECODE,
    # CLAUDE_CODE_ENTRYPOINT, CREDITS_* and MOCK_*, plus the test effect log and $Env (a $null
    # value removes the name). -NoWait returns the running process.
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
        $so = $p.StandardOutput.ReadToEndAsync(); $se = $p.StandardError.ReadToEndAsync()
        if ($NoWait) { return [pscustomobject]@{ Process = $p; StdOut = $so; StdErr = $se } }
        if (-not $p.WaitForExit(240000)) { & taskkill.exe /PID $p.Id /T /F *> $null; throw "child timed out: $Script" }
        $p.WaitForExit()
        [pscustomobject]@{ Code = $p.ExitCode; Out = $so.Result; Err = $se.Result }
    }

    function New-Id([string]$Prefix) { "$Prefix-$([guid]::NewGuid().ToString('N').Substring(0, 10))" }
    function New-SessionId { [guid]::NewGuid().ToString().ToLowerInvariant() }

    function Get-CreditsArgs([string]$Id, [string[]]$Extra = @()) {
        @('-PromptFile', $script:Prompt, '-DispatchId', $Id, '-OutputDir', $script:Out, '-KeyFile', $script:KeyFile,
            '-ClaudeExecutable', $script:Mock, '-WorkingDirectory', $script:WorkDir, '-Effort', 'low', '-TimeoutSec', '120') + $Extra
    }

    function Read-Json([string]$Path) { [System.IO.File]::ReadAllText($Path, [System.Text.Encoding]::UTF8) | ConvertFrom-Json }

    # Rows of one read-only query with ? parameters, as objects.
    function Get-Rows([string]$Sql, [string[]]$Params = @()) {
        $code = 'import json, sqlite3, sys; c = sqlite3.connect("file:" + sys.argv[1] + "?mode=ro", uri=True); c.row_factory = sqlite3.Row; print(json.dumps([dict(r) for r in c.execute(sys.argv[2], sys.argv[3:])]))'
        @((& $script:Py -X utf8 -c $code $script:Db $Sql @Params | Out-String) | ConvertFrom-Json)
    }

    function Import-CreditsRun {
        if (-not (Get-Module -Name CreditsRun)) { Import-Module -Name $script:Module -Force -DisableNameChecking -ErrorAction Stop }
    }

    # Wait for the mock's argv file. No throw: a wrapper that exits first fails the tests below,
    # not the container.
    function Wait-Mock($Child, [string]$ArgvFile, [int]$Seconds = 90) {
        $deadline = (Get-Date).AddSeconds($Seconds)
        while ((Get-Date) -lt $deadline -and -not (Test-Path -LiteralPath $ArgvFile) -and -not $Child.Process.HasExited) { Start-Sleep -Milliseconds 250 }
        Start-Sleep -Milliseconds 300
        if (Test-Path -LiteralPath $ArgvFile) { Read-Json $ArgvFile } else { $null }
    }

    function Test-Alive([int]$ProcessId) { $null -ne (Get-Process -Id $ProcessId -ErrorAction SilentlyContinue) }

    function Test-SamePath([string]$A, [string]$B) {
        [System.IO.Path]::GetFullPath($A).TrimEnd('\', '/') -eq [System.IO.Path]::GetFullPath($B).TrimEnd('\', '/')
    }

    $init = [System.Diagnostics.ProcessStartInfo]::new($script:Py)
    foreach ($a in @('-X', 'utf8', $script:StateTool, '--db', $script:Db, 'init')) { $init.ArgumentList.Add($a) }
    $init.UseShellExecute = $false
    $init.Environment['CREDITS_TEST_EFFECT_LOG'] = $script:EffectLog
    $initProc = [System.Diagnostics.Process]::Start($init); $initProc.WaitForExit()
}

AfterAll {
    if ($script:Root -and (Test-Path -LiteralPath $script:Root)) { Remove-Item -LiteralPath $script:Root -Recurse -Force -ErrorAction SilentlyContinue }
}

Describe 'AC-B.9: a manual run with -RunId follows R§7.2 steps 1 to 5' {
    BeforeAll {
        $script:RunId = New-Id 'b9-run'
        $script:Sid = New-SessionId
        $script:Disp = New-Id 'b9-disp'
        $script:Argv = "$script:Root/$script:Disp.argv.json"
        # Stale CREDITS_* values in the wrapper's own environment must not reach the child.
        $script:Live = Start-Child -Script $script:Credits -NoWait `
            -Arguments (Get-CreditsArgs $script:Disp @('-RunId', $script:RunId, '-SessionId', $script:Sid, '-StateDb', $script:Db)) `
            -Env @{ MOCK_ARGV_FILE = $script:Argv; MOCK_HANG_SECONDS = '25'; CREDITS_RUN_ID = 'run-stale'; CREDITS_BASE_COMMIT = 'base-commit-fixture' }
        $script:Seen = Wait-Mock $script:Live $script:Argv
        $script:Segs = @(Get-Rows 'SELECT * FROM segments WHERE run_id = ?' @($script:RunId))
    }

    AfterAll {
        if ($script:Live -and -not $script:Live.Process.HasExited) { & taskkill.exe /PID $script:Live.Process.Id /T /F *> $null }
        if ($script:Seen) { Stop-Process -Id ([int]$script:Seen.pid) -Force -ErrorAction SilentlyContinue }
    }

    It 'AC-B.9: register_minimal stored one manual job segment with the wrapper identity and the job name (R7-c)' {
        $script:Seen | Should -Not -BeNullOrEmpty -Because 'the mock started'
        $script:Segs.Count | Should -Be 1
        $seg = $script:Segs[0]
        $seg.supervision | Should -Be 'manual'
        $seg.job | Should -Be 1
        $seg.expected_session_id | Should -Be $script:Sid
        $seg.job_name | Should -Be "Local\{{PROJECT_NAME_UPPER}}Credits-$($seg.segment_id)"
        $seg.wrapper_pid | Should -Be $script:Live.Process.Id
        $seg.wrapper_created | Should -Not -BeNullOrEmpty
        [string]$seg.boot_id | Should -Not -BeNullOrEmpty
        $seg.win_session | Should -Be ([System.Diagnostics.Process]::GetCurrentProcess().SessionId)
        $seg.lane | Should -BeNullOrEmpty -Because 'a manual segment holds no lane'
        [double]$seg.reservation_usd | Should -Be 0
    }

    It 'AC-B.9: manual_identity stored the suspended child before the resume (the child sees state running and its own identity)' {
        $script:Seen.seen | Should -Not -BeNullOrEmpty
        $script:Seen.seen.state | Should -Be 'running'
        $recorded = [int]$script:Seen.seen.pid
        $recorded | Should -Be ([int]$script:Segs[0].pid)
        @([int]$script:Seen.pid, [int]$script:Seen.ppid) | Should -Contain $recorded -Because 'the recorded pid is the child the wrapper created, or the shell that runs the CLI'
    }

    It 'AC-B.9: only the resumed child gets CREDITS_RUN_ID, CREDITS_STATE_DB and CREDITS_SEGMENT, with no CREDITS_BASE_COMMIT' {
        $envDump = $script:Seen.env
        @($envDump.PSObject.Properties.Name | Sort-Object) | Should -Be @('CREDITS_RUN_ID', 'CREDITS_SEGMENT', 'CREDITS_STATE_DB')
        $envDump.CREDITS_RUN_ID | Should -Be $script:RunId
        $envDump.CREDITS_SEGMENT | Should -Be $script:Segs[0].segment_id
        Test-SamePath $envDump.CREDITS_STATE_DB $script:Db | Should -BeTrue
        $argv = @($script:Seen.argv)
        $argv[[array]::IndexOf($argv, '--session-id') + 1] | Should -Be $script:Sid
    }

    It 'AC-B.9: the job proof reads the running child as live' {
        Import-CreditsRun
        $seg = $script:Segs[0]
        $proof = Get-CreditsJobProof -JobName $seg.job_name -LauncherSession ([int]$seg.win_session) -BootId ([string]$seg.boot_id) `
            -Processes @(@{ pid = [int]$seg.wrapper_pid; created = $seg.wrapper_created }, @{ pid = [int]$seg.pid; created = $seg.created })
        $proof.Result | Should -Be 'live'
    }

    It 'AC-B.9: when the wrapper ends, it calls complete_segment once (finalized_by wrapper) after the store steps in order' {
        $script:Live.Process.WaitForExit(240000) | Should -BeTrue
        $script:Live.Process.WaitForExit()
        $script:Live.Process.ExitCode | Should -Be 0 -Because $script:Live.StdErr.Result
        $seg = (Get-Rows 'SELECT * FROM segments WHERE run_id = ?' @($script:RunId))[0]
        $seg.finalized_utc | Should -Not -BeNullOrEmpty
        $seg.finalized_by | Should -Be 'wrapper'
        $verbs = @(Get-Rows "SELECT verb, to_state FROM transitions WHERE entity = 'segment' AND entity_id = ? ORDER BY id" @($seg.segment_id))
        $verbs[0].verb | Should -Be 'register_minimal'
        $verbs[0].to_state | Should -Be 'identity_pending'
        $verbs[1].verb | Should -Be 'manual_identity'
        $verbs[1].to_state | Should -Be 'running'
        $verbs[-1].verb | Should -Be 'complete_segment'
        @($verbs | Where-Object { $_.verb -eq 'complete_segment' }).Count | Should -Be 1
    }
}

Describe 'AC-B.9: a wrapper that dies takes its child with it (MX-35)' {
    BeforeAll {
        $script:KillRun = New-Id 'b9-kill'
        $script:KillDisp = New-Id 'b9-kdisp'
        $script:KillArgv = "$script:Root/$script:KillDisp.argv.json"
        $script:Kill = Start-Child -Script $script:Credits -NoWait `
            -Arguments (Get-CreditsArgs $script:KillDisp @('-RunId', $script:KillRun, '-SessionId', (New-SessionId), '-StateDb', $script:Db)) `
            -Env @{ MOCK_ARGV_FILE = $script:KillArgv; MOCK_HANG_SECONDS = '180' }
        $script:KillSeen = Wait-Mock $script:Kill $script:KillArgv
    }

    AfterAll {
        if ($script:Kill -and -not $script:Kill.Process.HasExited) { & taskkill.exe /PID $script:Kill.Process.Id /T /F *> $null }
        if ($script:KillSeen) { Stop-Process -Id ([int]$script:KillSeen.pid) -Force -ErrorAction SilentlyContinue }
    }

    It 'AC-B.9: killing only the wrapper ends the CLI through kill-on-close, and the job proof then reads gone' {
        $script:KillSeen | Should -Not -BeNullOrEmpty -Because 'the mock started'
        $mockPid = [int]$script:KillSeen.pid
        Test-Alive $mockPid | Should -BeTrue
        Stop-Process -Id $script:Kill.Process.Id -Force
        $deadline = (Get-Date).AddSeconds(20)
        while ((Get-Date) -lt $deadline -and (Test-Alive $mockPid)) { Start-Sleep -Milliseconds 200 }
        Test-Alive $mockPid | Should -BeFalse -Because 'the job handle closed with the wrapper'
        $seg = (Get-Rows 'SELECT * FROM segments WHERE run_id = ?' @($script:KillRun))[0]
        $seg.finalized_utc | Should -BeNullOrEmpty -Because 'the wrapper died before complete_segment; the monitor finalizes it'
        Import-CreditsRun
        $proof = Get-CreditsJobProof -JobName $seg.job_name -LauncherSession ([int]$seg.win_session) -BootId ([string]$seg.boot_id) `
            -Processes @(@{ pid = [int]$seg.wrapper_pid; created = $seg.wrapper_created }, @{ pid = [int]$seg.pid; created = $seg.created })
        $proof.Result | Should -Be 'gone'
    }
}

Describe 'AC-B.9 negative: no job means no messaging' {
    It 'AC-B.9 negative: the job cannot be created → no CREDITS_* variable, no segment, and a printed "messaging off" line' {
        $run = New-Id 'b9-nojob'; $disp = New-Id 'b9-ndisp'; $argvFile = "$script:Root/$disp.argv.json"
        $res = Start-Child -Script $script:Credits `
            -Arguments (Get-CreditsArgs $disp @('-RunId', $run, '-SessionId', (New-SessionId), '-StateDb', $script:Db)) `
            -Env @{ MOCK_ARGV_FILE = $argvFile; CREDITS_TEST_JOB_FAIL = '1' }
        $res.Code | Should -Be 0 -Because "the run goes on without messaging: $($res.Err)"
        "$($res.Out)`n$($res.Err)" | Should -Match 'messaging off'
        Test-Path -LiteralPath $argvFile | Should -BeTrue -Because 'the CLI still ran'
        @((Read-Json $argvFile).env.PSObject.Properties.Name | Where-Object { $_ -like 'CREDITS_*' }) | Should -BeNullOrEmpty
        @(Get-Rows 'SELECT run_id FROM runs WHERE run_id = ?' @($run)).Count | Should -Be 0
        @(Get-Rows 'SELECT segment_id FROM segments WHERE run_id = ?' @($run)).Count | Should -Be 0
    }

    It 'AC-B.9 negative: -RunId with no -SessionId is refused before any launch or store write' {
        $run = New-Id 'b9-nosid'; $disp = New-Id 'b9-sdisp'; $log = "$script:Root/$disp.calls.txt"
        $res = Start-Child -Script $script:Credits -Arguments (Get-CreditsArgs $disp @('-RunId', $run, '-StateDb', $script:Db)) -Env @{ MOCK_CALL_LOG = $log }
        $res.Code | Should -Not -Be 0
        Test-Path -LiteralPath $log | Should -BeFalse
        @(Get-Rows 'SELECT run_id FROM runs WHERE run_id = ?' @($run)).Count | Should -Be 0
    }
}
