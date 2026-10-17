# S1 wrapper fixes (Component A of docs/execution/plans/2026-10-15-scheduled-credits-runs).
# AC-A.1 G-1 permission mode on resume, AC-A.2 G-2 liveness by pid and creation time,
# AC-A.3 G-3 recovery status, AC-A.5 G-5 kind and session cost, AC-A.6 -SessionId,
# AC-A.7 -ValidateOnly on the credits front end, AC-A.8 no CREDITS_* in a child dispatch.
# AC-A.4 (stop_gate `done`) is in tools/tests/test_stop_gate_done.py.
#
# Every run goes through .agent/skills/claude-credits/Invoke-ClaudeCredits.ps1 to a mock `claude`
# that records its argv, process id and CREDITS_* environment. No test reaches a real model: the
# key file holds a fake key, and -ClaudeExecutable is always the mock. Each child process gets
# its own environment block without CLAUDECODE and CLAUDE_CODE_ENTRYPOINT (a plain terminal for
# the mock only, as tests/tooling/test_invoke_claude_dispatch.py does); this process's
# environment is never changed.

BeforeAll {
    $script:Repo = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
    $script:Credits = Join-Path $script:Repo '.agent/skills/claude-credits/Invoke-ClaudeCredits.ps1'
    $script:GetDispatch = Join-Path $script:Repo 'tools/Get-ClaudeDispatch.ps1'
    $script:Root = "{{RECEIPTS_DIR}}/credits-wrapper-tests/$([guid]::NewGuid().ToString('N'))"
    $script:Out = "$script:Root/dispatch"
    $script:WorkDir = "$script:Root/work"
    New-Item -ItemType Directory -Force -Path $script:Out, $script:WorkDir | Out-Null

    # The fake key matches the wrapper's key pattern. It is built at run time, so no key-shaped
    # literal sits in the repository.
    $script:KeyFile = "$script:Root/fake.key"
    Set-Content -LiteralPath $script:KeyFile -Value ('sk-' + 'ant-api03-' + ('A' * 40)) -Encoding utf8NoBOM
    $script:Prompt = "$script:Root/prompt.md"
    Set-Content -LiteralPath $script:Prompt -Value 'credits wrapper test prompt' -Encoding utf8NoBOM

    # The mock runs on the base interpreter, not a venv launcher, so the process that cmd.exe
    # starts is the mock itself and its pid is the one the wrapper must record (G-2).
    $venvPy = Join-Path $script:Repo '.venv/Scripts/python.exe'
    $py = if (Test-Path -LiteralPath $venvPy) { $venvPy } else { (Get-Command python -ErrorAction Stop).Source }
    $script:BasePython = (& $py -c 'import sys; print(sys._base_executable)' | Out-String).Trim()
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
        json.dump(
            {
                "argv": args,
                "cwd": os.getcwd(),
                "pid": os.getpid(),
                "env": {
                    k.upper(): v
                    for k, v in os.environ.items()
                    if k.upper().startswith("CREDITS_") or k.upper() == "ZV_MARK"
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
elif "--resume" in args:
    sid = args[args.index("--resume") + 1]
out = {
    "type": "result",
    "result": "MOCK_RESULT_OK",
    "is_error": False,
    "total_cost_usd": float(os.environ.get("MOCK_COST", "0.0123")),
}
if sid:
    out["session_id"] = sid
print(json.dumps(out))
sys.exit(0)
'@
    $script:Mock = "$script:Root/mock_claude.bat"
    Set-Content -LiteralPath $script:Mock -Encoding ascii -Value "@echo off`r`n`"$script:BasePython`" -X utf8 `"$mockPy`" %*"

    $script:Strip = @('CLAUDECODE', 'CLAUDE_CODE_ENTRYPOINT')

    # Start pwsh -File <Script> <Arguments> with an environment built from this process's
    # environment minus CLAUDECODE, CLAUDE_CODE_ENTRYPOINT, CREDITS_* and MOCK_*, plus $Env
    # (a $null value removes the name). -NoWait returns the running process.
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

    # Arguments for Invoke-ClaudeCredits.ps1 with the test paths; $Extra is appended.
    function Get-CreditsArgs([string]$Id, [string[]]$Extra = @()) {
        @('-PromptFile', $script:Prompt, '-DispatchId', $Id, '-OutputDir', $script:Out, '-KeyFile', $script:KeyFile,
            '-ClaudeExecutable', $script:Mock, '-WorkingDirectory', $script:WorkDir, '-Effort', 'low', '-TimeoutSec', '120') + $Extra
    }

    function Invoke-Credits([string]$Id, [string[]]$Extra = @(), [hashtable]$Env = @{}) {
        Start-Child -Script $script:Credits -Arguments (Get-CreditsArgs $Id $Extra) -Env $Env
    }

    function Read-Json([string]$Path) { [System.IO.File]::ReadAllText($Path, [System.Text.Encoding]::UTF8) | ConvertFrom-Json }
    function Read-Status([string]$Id) { Read-Json "$script:Out/$Id/status.json" }

    # The argv the mock recorded, as one list of strings.
    function Get-Argv([string]$File) { @((Read-Json $File).argv) }
    function Get-ArgAfter([string[]]$Argv, [string]$Flag) {
        $i = [array]::IndexOf($Argv, $Flag); if ($i -lt 0 -or $i + 1 -ge $Argv.Count) { return $null }; $Argv[$i + 1]
    }
}

AfterAll {
    if ($script:Root -and (Test-Path -LiteralPath $script:Root)) { Remove-Item -LiteralPath $script:Root -Recurse -Force -ErrorAction SilentlyContinue }
}

Describe 'AC-A.1 G-1: a resume keeps the parent permission mode' {
    BeforeAll {
        $script:Parent1 = New-Id 'a1-parent'
        $script:Parent1Run = Invoke-Credits $script:Parent1 @('-PermissionMode', 'acceptEdits')
    }

    It 'AC-A.1: the parent run finishes and records acceptEdits' {
        $script:Parent1Run.Code | Should -Be 0 -Because $script:Parent1Run.Err
        (Read-Status $script:Parent1).permission_mode | Should -Be 'acceptEdits'
    }

    It 'AC-A.1: -Resume with no -PermissionMode passes the parent mode to the CLI' {
        $id = New-Id 'a1-resume'; $argvFile = "$script:Root/$id.argv.json"
        $res = Invoke-Credits $id @('-Resume', $script:Parent1) @{ MOCK_ARGV_FILE = $argvFile }
        $res.Code | Should -Be 0 -Because $res.Err
        $argv = Get-Argv $argvFile
        Get-ArgAfter $argv '--permission-mode' | Should -Be 'acceptEdits'
        Get-ArgAfter $argv '--resume' | Should -Be (Read-Status $script:Parent1).session_id
        (Read-Status $id).permission_mode | Should -Be 'acceptEdits'
    }

    It 'AC-A.1: an explicit -PermissionMode on -Resume still wins' {
        $id = New-Id 'a1-explicit'; $argvFile = "$script:Root/$id.argv.json"
        $res = Invoke-Credits $id @('-Resume', $script:Parent1, '-PermissionMode', 'plan') @{ MOCK_ARGV_FILE = $argvFile }
        $res.Code | Should -Be 0 -Because $res.Err
        Get-ArgAfter (Get-Argv $argvFile) '--permission-mode' | Should -Be 'plan'
    }

    It 'AC-A.1 negative: a parent record with no mode exits non-zero permission_mode_unknown and launches nothing' {
        $src = New-Id 'a1-nomode'
        New-Item -ItemType Directory -Force -Path "$script:Out/$src" | Out-Null
        $st = Read-Status $script:Parent1
        $st.PSObject.Properties.Remove('permission_mode')
        $st.dispatch_id = $src
        Set-Content -LiteralPath "$script:Out/$src/status.json" -Value ($st | ConvertTo-Json -Depth 6) -Encoding utf8NoBOM
        $id = New-Id 'a1-refused'; $log = "$script:Root/$id.calls.txt"
        $res = Invoke-Credits $id @('-Resume', $src) @{ MOCK_CALL_LOG = $log }
        $res.Code | Should -Not -Be 0
        $res.Err | Should -Match 'permission_mode_unknown'
        Test-Path -LiteralPath $log | Should -BeFalse -Because 'no CLI launch, and no silent plan default'
        Test-Path -LiteralPath "$script:Out/$id" | Should -BeFalse
    }
}

Describe 'AC-A.2 and AC-A.3: liveness by pid and creation time, and the recovery status command' {
    BeforeAll {
        $script:Live = New-Id 'a2-live'
        $script:LiveArgv = "$script:Root/$script:Live.argv.json"
        $script:LiveChild = Start-Child -Script $script:Credits -NoWait `
            -Arguments (Get-CreditsArgs $script:Live @('-PermissionMode', 'acceptEdits')) `
            -Env @{ MOCK_ARGV_FILE = $script:LiveArgv; MOCK_HANG_SECONDS = '180' }
        # Wait for the mock to start and running.json to exist. No throw here: a missing file
        # fails the tests below, not the container.
        $deadline = (Get-Date).AddSeconds(90)
        while ((Get-Date) -lt $deadline -and -not ((Test-Path -LiteralPath $script:LiveArgv) -and (Test-Path -LiteralPath "$script:Out/$script:Live/running.json"))) {
            Start-Sleep -Milliseconds 250
        }
        Start-Sleep -Milliseconds 500
        $script:Running = if (Test-Path -LiteralPath "$script:Out/$script:Live/running.json") { Read-Json "$script:Out/$script:Live/running.json" } else { $null }
        $script:MockPid = if (Test-Path -LiteralPath $script:LiveArgv) { [int](Read-Json $script:LiveArgv).pid } else { $null }
    }

    AfterAll {
        if ($script:LiveChild -and -not $script:LiveChild.Process.HasExited) { & taskkill.exe /PID $script:LiveChild.Process.Id /T /F *> $null }
        if ($script:MockPid) { Stop-Process -Id $script:MockPid -Force -ErrorAction SilentlyContinue }
    }

    It 'AC-A.2: running.json holds the claude process id, its creation time and the boot id' {
        $script:Running | Should -Not -BeNullOrEmpty
        $script:MockPid | Should -Not -BeNullOrEmpty
        $script:Running.claude_pid | Should -Be $script:MockPid -Because 'the pid is the CLI process, not cmd.exe'
        $proc = Get-Process -Id $script:MockPid -ErrorAction Stop
        $recorded = [datetimeoffset]::Parse([string]$script:Running.claude_creation_utc, [cultureinfo]::InvariantCulture).UtcDateTime
        [math]::Abs(($recorded - $proc.StartTime.ToUniversalTime()).TotalSeconds) | Should -BeLessOrEqual 1
        [string]$script:Running.boot_id | Should -Not -BeNullOrEmpty
    }

    It 'AC-A.2: Get-ClaudeDispatch reads the live run as running' {
        $res = Start-Child -Script $script:GetDispatch -Arguments @($script:Live, '-OutputDir', $script:Out, '-Json')
        $res.Code | Should -Be 0 -Because $res.Err
        ($res.Out | ConvertFrom-Json).state | Should -Be 'running'
    }

    It 'AC-A.2 negative: a live process with the same pid and a different creation time is reported dead' {
        $me = Get-Process -Id $PID
        $created = $me.StartTime.ToUniversalTime()
        foreach ($case in @(@{ Name = 'a2-match'; Created = $created; Want = 'running' }, @{ Name = 'a2-reused'; Created = $created.AddHours(-1); Want = 'died' })) {
            $dir = "$script:Out/$(New-Id $case.Name)"
            New-Item -ItemType Directory -Force -Path $dir | Out-Null
            $rec = [ordered]@{
                schema_version = 'dispatch-running.v1'; dispatch_id = (Split-Path -Leaf $dir); pid = $PID
                claude_pid = $PID; claude_creation_utc = $case.Created.ToString('o'); boot_id = [string]$script:Running.boot_id
                session_id = [guid]::NewGuid().ToString(); session_mode = 'fresh'; model = 'fixture-model'
                auth_mode = 'api_key_file'; start_utc = $case.Created.ToString('yyyy-MM-ddTHH:mm:ssZ'); working_directory = $script:WorkDir
            }
            Set-Content -LiteralPath "$dir/running.json" -Value ($rec | ConvertTo-Json) -Encoding utf8NoBOM
            $res = Start-Child -Script $script:GetDispatch -Arguments @((Split-Path -Leaf $dir), '-OutputDir', $script:Out, '-Json')
            $res.Code | Should -Be 0 -Because $res.Err
            ($res.Out | ConvertFrom-Json).state | Should -Be $case.Want -Because "case $($case.Name)"
        }
    }

    It 'AC-A.3 negative: the recovery command refuses a run whose process is still live (run_alive) and writes no file' {
        $res = Start-Child -Script $script:GetDispatch -Arguments @($script:Live, '-OutputDir', $script:Out, '-RecoverStatus')
        $res.Code | Should -Not -Be 0
        $res.Err | Should -Match 'run_alive'
        Test-Path -LiteralPath "$script:Out/$script:Live/status.json" | Should -BeFalse
    }

    It 'AC-A.3: after the run dies, the recovery command writes status.json marked recovered' {
        & taskkill.exe /PID $script:LiveChild.Process.Id /T /F *> $null
        if ($script:MockPid) { Stop-Process -Id $script:MockPid -Force -ErrorAction SilentlyContinue }
        $script:LiveChild.Process.WaitForExit(30000) | Out-Null
        Start-Sleep -Milliseconds 500
        Test-Path -LiteralPath "$script:Out/$script:Live/status.json" | Should -BeFalse -Because 'the wrapper died before it wrote status.json'

        $res = Start-Child -Script $script:GetDispatch -Arguments @($script:Live, '-OutputDir', $script:Out, '-RecoverStatus')
        $res.Code | Should -Be 0 -Because $res.Err
        $st = Read-Status $script:Live
        $st.recovered | Should -BeTrue
        $st.cli | Should -Be 'claude'
        $st.session_id | Should -Be $script:Running.session_id
        $st.working_directory | Should -Be $script:Running.working_directory
        $st.permission_mode | Should -Be 'acceptEdits'
        $st.model_class | Should -Be 'isolated_worker'
    }

    It 'AC-A.3: a resume from the recovered record is accepted and keeps the mode' {
        $id = New-Id 'a3-resume'; $argvFile = "$script:Root/$id.argv.json"
        $res = Invoke-Credits $id @('-Resume', $script:Live) @{ MOCK_ARGV_FILE = $argvFile }
        $res.Code | Should -Be 0 -Because $res.Err
        $argv = Get-Argv $argvFile
        Get-ArgAfter $argv '--resume' | Should -Be $script:Running.session_id
        Get-ArgAfter $argv '--permission-mode' | Should -Be 'acceptEdits'
    }
}

Describe 'AC-A.5 G-5: kind, the session total and the segment delta' {
    BeforeAll {
        $script:Seg1 = New-Id 'a5-seg1'
        $script:Seg1Run = Invoke-Credits $script:Seg1 @('-Kind', 'exec', '-PermissionMode', 'acceptEdits') @{ MOCK_COST = '0.25' }
    }

    It 'AC-A.5: a fresh segment records kind, the session total and a delta equal to the total' {
        $script:Seg1Run.Code | Should -Be 0 -Because $script:Seg1Run.Err
        $st = Read-Status $script:Seg1
        $st.kind | Should -Be 'exec'
        [double]$st.session_total_usd | Should -Be 0.25
        [double]$st.segment_delta_usd | Should -Be 0.25
        $st.cost_untrusted | Should -BeFalse
    }

    It 'AC-A.5: a resumed segment records the delta from the previous session total' {
        $id = New-Id 'a5-seg2'
        $res = Invoke-Credits $id @('-Resume', $script:Seg1, '-Kind', 'exec') @{ MOCK_COST = '0.40' }
        $res.Code | Should -Be 0 -Because $res.Err
        $st = Read-Status $id
        $st.kind | Should -Be 'exec'
        [double]$st.session_total_usd | Should -Be 0.40
        [math]::Abs([double]$st.segment_delta_usd - 0.15) | Should -BeLessThan 1e-9
        $st.cost_untrusted | Should -BeFalse
    }

    It 'AC-A.5 negative: a total lower than the previous one gives a null delta and cost_untrusted' {
        $id = New-Id 'a5-lower'
        $res = Invoke-Credits $id @('-Resume', $script:Seg1, '-Kind', 'exec') @{ MOCK_COST = '0.10' }
        $res.Code | Should -Be 0 -Because $res.Err
        $st = Read-Status $id
        $st.PSObject.Properties.Name | Should -Contain 'segment_delta_usd'
        $st.segment_delta_usd | Should -BeNullOrEmpty
        $st.cost_untrusted | Should -BeTrue
    }

    It 'AC-A.5 negative: a zero total gives a null delta and cost_untrusted' {
        $id = New-Id 'a5-zero'
        $res = Invoke-Credits $id @('-Kind', 'plan') @{ MOCK_COST = '0' }
        $res.Code | Should -Be 0 -Because $res.Err
        $st = Read-Status $id
        $st.kind | Should -Be 'plan'
        $st.PSObject.Properties.Name | Should -Contain 'segment_delta_usd'
        $st.segment_delta_usd | Should -BeNullOrEmpty
        $st.cost_untrusted | Should -BeTrue
    }
}

Describe 'AC-A.6: -SessionId' {
    It 'AC-A.6: -SessionId passes --session-id for a new session' {
        $sid = [guid]::NewGuid().ToString().ToLowerInvariant()
        $id = New-Id 'a6-sid'; $argvFile = "$script:Root/$id.argv.json"
        $res = Invoke-Credits $id @('-SessionId', $sid) @{ MOCK_ARGV_FILE = $argvFile }
        $res.Code | Should -Be 0 -Because $res.Err
        Get-ArgAfter (Get-Argv $argvFile) '--session-id' | Should -Be $sid
        (Read-Status $id).session_id | Should -Be $sid
    }

    It 'AC-A.6 negative: a value that is not a lowercase UUID is refused before launch (<Value>)' -ForEach @(
        @{ Value = 'not-a-uuid' }
        @{ Value = 'AAAAAAAA-BBBB-4CCC-8DDD-EEEEEEEEEEEE' }
    ) {
        $id = New-Id 'a6-bad'; $log = "$script:Root/$id.calls.txt"
        $res = Invoke-Credits $id @('-SessionId', $Value) @{ MOCK_CALL_LOG = $log }
        $res.Code | Should -Not -Be 0
        Test-Path -LiteralPath $log | Should -BeFalse
        Test-Path -LiteralPath "$script:Out/$id" | Should -BeFalse
    }
}

Describe 'AC-A.7: -ValidateOnly on the credits front end' {
    It 'AC-A.7: valid arguments, brief and key file exit 0 with no launch' {
        $id = New-Id 'a7-ok'; $log = "$script:Root/$id.calls.txt"
        $res = Invoke-Credits $id @('-ValidateOnly') @{ MOCK_CALL_LOG = $log }
        $res.Code | Should -Be 0 -Because $res.Err
        $res.Out | Should -Match 'dispatch_args_ok'
        Test-Path -LiteralPath $log | Should -BeFalse
        Test-Path -LiteralPath "$script:Out/$id" | Should -BeFalse
    }

    It 'AC-A.7: -ValidateOnly also runs from inside a Claude Code session (SKILL.md Hand-over step 4)' {
        $id = New-Id 'a7-nested'; $log = "$script:Root/$id.calls.txt"
        $res = Invoke-Credits $id @('-ValidateOnly') @{ MOCK_CALL_LOG = $log; CLAUDE_CODE_ENTRYPOINT = 'claude-vscode' }
        $res.Code | Should -Be 0 -Because $res.Err
        $res.Out | Should -Match 'dispatch_args_ok'
        Test-Path -LiteralPath $log | Should -BeFalse
    }

    It 'AC-A.7 negative: a missing brief exits non-zero with no launch' {
        $id = New-Id 'a7-nobrief'; $log = "$script:Root/$id.calls.txt"
        $a = Get-CreditsArgs $id @('-ValidateOnly')
        $a[[array]::IndexOf($a, '-PromptFile') + 1] = "$script:Root/missing-brief.md"
        $res = Start-Child -Script $script:Credits -Arguments $a -Env @{ MOCK_CALL_LOG = $log }
        $res.Code | Should -Not -Be 0
        $res.Out | Should -Not -Match 'dispatch_args_ok'
        Test-Path -LiteralPath $log | Should -BeFalse
        Test-Path -LiteralPath "$script:Out/$id" | Should -BeFalse
    }
}

Describe 'AC-A.8: a child dispatch never inherits CREDITS_ENV' {
    It 'AC-A.8 negative: a parent with all of CREDITS_ENV set gives a child with none of them' {
        $id = New-Id 'a8-env'; $argvFile = "$script:Root/$id.argv.json"
        $res = Invoke-Credits $id @() @{
            MOCK_ARGV_FILE = $argvFile; ZV_MARK = 'kept'
            CREDITS_RUN_ID = 'run-a8'; CREDITS_STATE_DB = "$script:Root/state.db"
            CREDITS_SEGMENT = 'seg-a8'; CREDITS_BASE_COMMIT = '0123456789abcdef0123456789abcdef01234567'
        }
        $res.Code | Should -Be 0 -Because $res.Err
        $envDump = (Read-Json $argvFile).env
        $envDump.ZV_MARK | Should -Be 'kept' -Because 'the dump sees ordinary variables'
        @($envDump.PSObject.Properties.Name | Where-Object { $_ -like 'CREDITS_*' }) | Should -BeNullOrEmpty
    }
}
