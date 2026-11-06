# Credits on a fleet member (WP-A2 of docs/execution/plans/2026-11-04-fleet-agents).
# The route `launch.auth: subscription` runs a scheduled credits run on a member: an S4U task, no key
# file, and the subscription token passed to the CLI only.
#
# Every launch goes to a mock `claude` that records its argv, the NAMES of its environment and a hash
# of the token, never the token. The token, the key, the store and the receipt are temp files. The
# M-1 gate is a mock that records its argv. No test registers a real task: the adapter is injected.

BeforeAll {
    $script:Repo = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
    $script:Skill = Join-Path $script:Repo '.agent/skills/claude-credits'
    $script:Register = Join-Path $script:Skill 'Register-CreditsRun.ps1'
    $script:Launcher = Join-Path $script:Skill 'Start-CreditsRun.ps1'
    $script:Invoke = Join-Path $script:Skill 'Invoke-ClaudeCredits.ps1'
    $script:Module = Join-Path $script:Skill 'CreditsRun.psm1'
    $script:StateTool = Join-Path $script:Repo 'tools/credits_state.py'
    $script:Root = "{{RECEIPTS_DIR}}/credits-fleet-tests/$([guid]::NewGuid().ToString('N'))"
    $script:Out = "$script:Root/dispatch"
    $script:Project = "$script:Root/project"
    $script:GateProject = "$script:Root/gate-project"
    New-Item -ItemType Directory -Force -Path $script:Out, $script:Project, $script:GateProject, "$script:Root/credentials" | Out-Null
    $script:EffectLog = "$script:Root/effects.jsonl"
    $script:SavedEffectLog = $env:CREDITS_TEST_EFFECT_LOG
    $env:CREDITS_TEST_EFFECT_LOG = $script:EffectLog
    $script:Db = "$script:Root/store/state.db"
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $script:Db) | Out-Null

    $venvPy = Join-Path $script:Repo '.venv/Scripts/python.exe'
    $script:Py = if (Test-Path -LiteralPath $venvPy) { $venvPy } else { (Get-Command python -ErrorAction Stop).Source }
    $script:BasePython = (& $script:Py -c 'import sys; print(sys._base_executable)' | Out-String).Trim()

    $script:KeyFile = "$script:Root/fake.key"
    Set-Content -LiteralPath $script:KeyFile -Value ('sk-' + 'ant-api03-' + ('A' * 40)) -Encoding utf8NoBOM
    $script:MissingKey = "$script:Root/no-such.key"
    $script:Token = "fake-oauth-$([guid]::NewGuid().ToString('N'))"
    $script:TokenSha = [System.Convert]::ToHexString([System.Security.Cryptography.SHA256]::HashData([System.Text.Encoding]::UTF8.GetBytes($script:Token))).ToLowerInvariant()
    $script:TokenFile = "$script:Root/credentials/claude-oauth-token"
    [System.IO.File]::WriteAllText($script:TokenFile, "$script:Token`n")
    $script:Brief = "$script:Root/brief.md"
    Set-Content -LiteralPath $script:Brief -Value 'credits fleet test brief' -Encoding utf8NoBOM

    $mockPy = "$script:Root/mock_claude.py"
    Set-Content -LiteralPath $mockPy -Encoding utf8NoBOM -Value @'
import hashlib
import json
import os
import sys

args = sys.argv[1:]
if "--version" in args:
    print("2.1.296 (Claude Code)")
    sys.exit(0)
stdin_text = sys.stdin.read()
token = os.environ.get("CLAUDE_CODE_OAUTH_TOKEN")
log = os.environ.get("MOCK_CALL_LOG")
if log:
    record = {
        "argv": args,
        "stdin": stdin_text,
        "env_names": sorted(k.upper() for k in os.environ),
        "scrub": os.environ.get("CLAUDE_CODE_SUBPROCESS_ENV_SCRUB"),
        "token_sha256": hashlib.sha256(token.encode()).hexdigest() if token else None,
    }
    with open(log, "a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")
sid = None
if "--session-id" in args:
    sid = args[args.index("--session-id") + 1]
elif "--resume" in args:
    sid = args[args.index("--resume") + 1]
out = {"type": "result", "result": "MOCK_RESULT_OK", "is_error": False, "total_cost_usd": 0.0123}
if sid:
    out["session_id"] = sid
print(json.dumps(out))
sys.exit(0)
'@
    $script:Mock = "$script:Root/mock_claude.bat"
    Set-Content -LiteralPath $script:Mock -Encoding ascii -Value "@echo off`r`n`"$script:BasePython`" -X utf8 `"$mockPy`" %*"

    # The mock M-1 gate: exit 0 for the fixture receipt. It adds its argv to <receipt>.gate-argv.jsonl.
    $script:GatePy = "$script:Root/mock_run_gate.py"
    Set-Content -LiteralPath $script:GatePy -Encoding utf8NoBOM -Value @'
import json
import sys

args = sys.argv[1:]
receipt = args[args.index("--check-receipt") + 1]
with open(receipt + ".gate-argv.jsonl", "a", encoding="utf-8") as f:
    f.write(json.dumps(args) + "\n")
print(f"RECEIPT OK: {receipt}")
sys.exit(0)
'@
    $script:Receipt = "$script:Root/receipt/gate-result.json"
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $script:Receipt) | Out-Null
    Set-Content -LiteralPath $script:Receipt -Encoding utf8NoBOM -Value '{"cli_version": "2.1.296", "identity": {"kit_revision": "kitrev-fixture"}}'

    $script:Config = "$script:Root/config.json"
    Set-Content -LiteralPath $script:Config -Encoding utf8NoBOM -Value '{"ruling_enabled": false, "gate_wait_max_min": 0, "cache_ttl": "5m", "credits_start_policy": "human-only"}'

    # A wrapper that records the arguments the launcher gives it and starts nothing.
    $script:StubWrapper = "$script:Root/stub_wrapper.ps1"
    Set-Content -LiteralPath $script:StubWrapper -Encoding utf8NoBOM -Value '[System.IO.File]::WriteAllText($env:MOCK_WRAPPER_ARGV, (ConvertTo-Json -InputObject @($args) -Compress))'

    function New-Id([string]$Prefix) { "$Prefix-$([guid]::NewGuid().ToString('N').Substring(0, 10))" }

    function New-ManifestDoc([string]$RunId, [hashtable]$Launch = @{}) {
        $doc = [ordered]@{
            schema = 'credits-run.v1'; run_id = $RunId; kind = 'exec'
            project_root = $script:Project; plan_folder = 'docs/execution/plans/2026-11-04-fixture/'
            brief = $script:Brief
            launch = [ordered]@{
                working_directory = $script:Project; claude_exe = $script:Mock; python_exe = $script:Py
                permission_mode = 'bypassPermissions'; effort = 'low'; segment_cap_usd = 20.0; timeout_sec = 3600
            }
            budget = [ordered]@{ run_cap_usd = 50.0 }
            messaging = [ordered]@{ orchestrator_sessions = @('00000000-0000-4000-8000-0000000000aa'); ruling_enabled = $false; gate_wait_max_min = 0 }
            depends_on = @(); lane = "tree:$script:Project/$RunId"
        }
        foreach ($k in $Launch.Keys) { $doc.launch[$k] = $Launch[$k] }
        $doc
    }

    # The launch fields of the member route.
    function Get-MemberLaunch([hashtable]$Extra = @{}) {
        $launch = @{ auth = 'subscription'; permission_mode = 'acceptEdits' }
        foreach ($k in $Extra.Keys) { $launch[$k] = $Extra[$k] }
        $launch
    }

    function New-FakeScheduler {
        $state = @{ Tasks = @{} }
        @{
            State    = $state
            Register = { param($Definition) $state.Tasks["$($Definition.TaskPath)$($Definition.TaskName)"] = $Definition }.GetNewClosure()
            Get      = { param($TaskPath, $TaskName) $state.Tasks["$TaskPath$TaskName"] }.GetNewClosure()
            Start    = { param($TaskPath, $TaskName) }.GetNewClosure()
        }
    }

    # Run Register-CreditsRun.ps1 in this process, as Register-CreditsRun.Tests.ps1 does.
    function Invoke-Register {
        param($Doc, [string]$KeyFile = $script:KeyFile, [hashtable]$Scheduler = (New-FakeScheduler))
        $manifest = "$script:Root/manifest-$($Doc.run_id).json"
        Set-Content -LiteralPath $manifest -Value ($Doc | ConvertTo-Json -Depth 8) -Encoding utf8NoBOM
        $params = @{
            Manifest = $manifest; Receipt = $script:Receipt; StateDb = $script:Db; ConfigPath = $script:Config
            Scheduler = $Scheduler; RunGate = $script:GatePy; KeyFile = $KeyFile
        }
        $global:LASTEXITCODE = 0
        $lines = @(); $thrown = $null
        try { $lines = @(& $script:Register @params 2>$null) } catch { $thrown = $_.Exception.Message }
        $code = $global:LASTEXITCODE
        $payload = $null
        $last = @($lines | ForEach-Object { "$_" } | Where-Object { $_.TrimStart().StartsWith('{') }) | Select-Object -Last 1
        if ($last) { $payload = $last | ConvertFrom-Json }
        [pscustomobject]@{ Code = $code; Payload = $payload; Thrown = $thrown; Scheduler = $Scheduler }
    }

    # One child pwsh with this environment minus CLAUDECODE, CLAUDE_CODE_ENTRYPOINT, CREDITS_* and
    # MOCK_*, plus the test effect log and $Env.
    function Start-Child {
        param([string]$Script, [string[]]$Arguments, [hashtable]$Env = @{})
        $psi = [System.Diagnostics.ProcessStartInfo]::new('pwsh')
        foreach ($a in @('-NoProfile', '-File', $Script) + $Arguments) { $psi.ArgumentList.Add([string]$a) }
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
        if (-not $p.WaitForExit(240000)) { & taskkill.exe /PID $p.Id /T /F *> $null; throw "child timed out: $Script" }
        $p.WaitForExit()
        [pscustomobject]@{ Code = $p.ExitCode; Out = $so.Result; Err = $se.Result }
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

    function Get-Rows([string]$Sql, [string[]]$Params = @()) {
        $code = 'import json, sqlite3, sys; c = sqlite3.connect("file:" + sys.argv[1] + "?mode=ro", uri=True); c.row_factory = sqlite3.Row; print(json.dumps([dict(r) for r in c.execute(sys.argv[2], sys.argv[3:])]))'
        @((& $script:Py -X utf8 -c $code $script:Db $Sql @Params | Out-String) | ConvertFrom-Json)
    }

    function Get-LauncherArgs([string]$RunId, [string[]]$Extra = @()) {
        @('-RunId', $RunId, '-StateDb', $script:Db, '-OutputDir', $script:Out, '-KeyFile', $script:KeyFile,
            '-TokenFile', $script:TokenFile, '-RunGate', $script:GatePy, '-Receipt', $script:Receipt,
            '-LaunchWaitMs', '60000', '-TerminateWaitMs', '5000', '-CancelPollMs', '1000') + $Extra
    }

    function Get-Payload($Child) {
        $last = @("$($Child.Out)" -split "`r?`n" | Where-Object { $_.TrimStart().StartsWith('{') }) | Select-Object -Last 1
        if (-not $last) { return $null }
        $last | ConvertFrom-Json
    }

    function Get-Calls([string]$Path) {
        if (-not (Test-Path -LiteralPath $Path)) { return @() }
        @([System.IO.File]::ReadAllLines($Path) | Where-Object { $_.Trim() } | ForEach-Object { $_ | ConvertFrom-Json })
    }

    # Register a run and request it.
    function New-RequestedRun([string]$RunId, [hashtable]$Launch = @{}, [string]$KeyFile = $script:KeyFile) {
        $res = Invoke-Register (New-ManifestDoc $RunId $Launch) -KeyFile $KeyFile
        if ($res.Code -ne 0) { throw "registration failed: $($res.Payload | ConvertTo-Json -Compress) $($res.Thrown)" }
        Assert-Store 'request' @('--run-id', $RunId, '--started-by', 'human-command', '--request-id', "req0-$RunId") | Out-Null
    }

    # Launch a requested run to the end with the real wrapper; returns the child and the call log.
    function Start-RunToEnd([string]$RunId, [hashtable]$Env = @{}, [string[]]$Extra = @()) {
        $calls = "$script:Root/$RunId.calls.jsonl"
        $Env['MOCK_CALL_LOG'] = $calls
        $child = Start-Child $script:Launcher (Get-LauncherArgs $RunId $Extra) -Env $Env
        [pscustomobject]@{ Child = $child; Calls = $calls }
    }

    # The arguments the launcher gives its wrapper.
    function Get-WrapperArgs([string]$RunId, [string[]]$Extra = @()) {
        $file = "$script:Root/$RunId.wrapper.json"
        $null = Start-Child $script:Launcher (Get-LauncherArgs $RunId (@('-WrapperScript', $script:StubWrapper) + $Extra)) -Env @{ MOCK_WRAPPER_ARGV = $file }
        if (-not (Test-Path -LiteralPath $file)) { return $null }
        @([System.IO.File]::ReadAllText($file) | ConvertFrom-Json)
    }

    # The files under the test folder that hold the token, as UTF-8 or UTF-16 text. Its own file is
    # the one place it belongs.
    function Get-FilesHoldingToken {
        $utf16 = [System.Text.Encoding]::Latin1.GetString([System.Text.Encoding]::Unicode.GetBytes($script:Token))
        @(Get-ChildItem -LiteralPath $script:Root -Recurse -File | Where-Object { $_.Directory.Name -ne 'credentials' } | Where-Object {
                $text = [System.Text.Encoding]::Latin1.GetString([System.IO.File]::ReadAllBytes($_.FullName))
                $text.Contains($script:Token) -or $text.Contains($utf16)
            } | ForEach-Object { $_.FullName })
    }

    # The lines that assign to the two names this route must leave alone.
    function Get-EntrypointAssignments([string]$Text) {
        $names = 'CLAUDECODE|CLAUDE_CODE_ENTRYPOINT'
        @($Text -split "`r?`n" | Where-Object {
                $_ -match "\`$env:($names)\s*=[^=]" -or
                $_ -match "(Environment|EnvironmentVariables)\[['""]($names)['""]\]\s*=[^=]" -or
                $_ -match "SetEnvironmentVariable\(['""]($names)['""]"
            })
    }

    Assert-Store 'init' | Out-Null
}

AfterAll {
    $env:CREDITS_TEST_EFFECT_LOG = $script:SavedEffectLog
    if ($script:Root -and (Test-Path -LiteralPath $script:Root)) { Remove-Item -LiteralPath $script:Root -Recurse -Force -ErrorAction SilentlyContinue }
}

Describe 'AC-6: the manifest rules of the route' {
    It 'AC-6: a manifest with no auth behaves as the key route' {
        $res = Invoke-Register (New-ManifestDoc (New-Id 'ac6-absent'))
        $res.Code | Should -Be 0 -Because "$($res.Payload | ConvertTo-Json -Compress)"
        $res.Payload.result | Should -Be 'changed'
        $def = $res.Scheduler.State.Tasks.Values | Where-Object { $_.TaskName -ne 'Monitor' }
        $def.LogonType | Should -Be 'Interactive'
    }

    It 'AC-6: auth subscription with a gate project registers' {
        $res = Invoke-Register (New-ManifestDoc (New-Id 'ac6-sub') (Get-MemberLaunch @{ gate_project = $script:GateProject; allowed_tools = @('Read', 'Bash(git status)') }))
        $res.Code | Should -Be 0 -Because "$($res.Payload | ConvertTo-Json -Compress)"
    }

    It 'AC-6: an unknown auth value is refused' {
        $res = Invoke-Register (New-ManifestDoc (New-Id 'ac6-bad') @{ auth = 'x' })
        $res.Code | Should -Be 3
        $res.Payload.reason | Should -Be 'manifest_invalid'
    }

    It 'AC-6: gate_project with auth key is refused' {
        $res = Invoke-Register (New-ManifestDoc (New-Id 'ac6-gate-key') @{ auth = 'key'; gate_project = $script:GateProject })
        $res.Code | Should -Be 3
        $res.Payload.reason | Should -Be 'manifest_invalid'
    }

    It 'AC-6: gate_project with no auth is refused' {
        $res = Invoke-Register (New-ManifestDoc (New-Id 'ac6-gate-none') @{ gate_project = $script:GateProject })
        $res.Code | Should -Be 3
        $res.Payload.reason | Should -Be 'manifest_invalid'
    }

    It 'AC-6: a gate_project that is not a local path is refused' {
        $res = Invoke-Register (New-ManifestDoc (New-Id 'ac6-gate-unc') (Get-MemberLaunch @{ gate_project = '\\host\share\gate' }))
        $res.Code | Should -Be 3
        $res.Payload.reason | Should -Be 'path_not_local'
    }

    It 'AC-6: an allowed tool that the dispatch wrapper would refuse is refused here' {
        $res = Invoke-Register (New-ManifestDoc (New-Id 'ac6-tool') (Get-MemberLaunch @{ allowed_tools = @('not a tool') }))
        $res.Code | Should -Be 3
        $res.Payload.reason | Should -Be 'manifest_invalid'
    }

    It 'AC-6: an unknown launch key is refused' {
        $res = Invoke-Register (New-ManifestDoc (New-Id 'ac6-key') @{ surprise = 'x' })
        $res.Code | Should -Be 3
        $res.Payload.reason | Should -Be 'manifest_invalid'
    }
}

Describe 'AC-7: the logon of each route' {
    BeforeAll {
        $script:Sub = Invoke-Register (New-ManifestDoc (New-Id 'ac7-sub') (Get-MemberLaunch))
        $script:Key = Invoke-Register (New-ManifestDoc (New-Id 'ac7-key'))
    }

    It 'AC-7: the subscription route registers an S4U run task with no trigger' {
        $def = $script:Sub.Scheduler.State.Tasks.Values | Where-Object { $_.TaskName -ne 'Monitor' }
        $def.LogonType | Should -Be 'S4U'
        @($def.Triggers).Count | Should -Be 0
    }

    It 'AC-7: the subscription route registers an S4U monitor with its five-minute repeat and no AtLogOn' {
        $def = $script:Sub.Scheduler.State.Tasks.Values | Where-Object { $_.TaskName -eq 'Monitor' }
        $def.LogonType | Should -Be 'S4U'
        @($def.Triggers.Kind) | Should -Be @('Once')
        @($def.Triggers)[0].RepetitionInterval | Should -Be 'PT5M'
    }

    It 'AC-7: the readback hash of the subscription run task matches, so the run is registered' {
        $script:Sub.Payload.state | Should -Be 'registered'
    }

    It 'AC-7: the key route still registers Interactive tasks, and the monitor keeps AtLogOn' {
        $run = $script:Key.Scheduler.State.Tasks.Values | Where-Object { $_.TaskName -ne 'Monitor' }
        $monitor = $script:Key.Scheduler.State.Tasks.Values | Where-Object { $_.TaskName -eq 'Monitor' }
        $run.LogonType | Should -Be 'Interactive'
        $monitor.LogonType | Should -Be 'Interactive'
        @($monitor.Triggers.Kind) | Should -Be @('AtLogOn', 'Once')
    }

    It 'AC-7: the task definitions default to the key route' {
        Import-Module -Name $script:Module -Force -DisableNameChecking -ErrorAction Stop
        $def = New-CreditsTaskDefinition -RunId 'r1' -ProjectRoot 'C:\p' -PwshPath 'C:\pwsh.exe' -LauncherPath 'C:\l.ps1' -TimeoutSec 60
        $def.LogonType | Should -Be 'Interactive'
        $def = New-CreditsTaskDefinition -RunId 'r1' -ProjectRoot 'C:\p' -PwshPath 'C:\pwsh.exe' -LauncherPath 'C:\l.ps1' -TimeoutSec 60 -Subscription
        $def.LogonType | Should -Be 'S4U'
    }
}

Describe 'AC-8: no key on the member route' {
    It 'AC-8: auth subscription with no key file registers' {
        $res = Invoke-Register (New-ManifestDoc (New-Id 'ac8-reg') (Get-MemberLaunch)) -KeyFile $script:MissingKey
        $res.Code | Should -Be 0 -Because "$($res.Payload | ConvertTo-Json -Compress)"
    }

    It 'AC-8: auth key with no key file still gives key_missing' {
        $res = Invoke-Register (New-ManifestDoc (New-Id 'ac8-key') @{ auth = 'key' }) -KeyFile $script:MissingKey
        $res.Code | Should -Be 3
        $res.Payload.reason | Should -Be 'key_missing'
    }

    It 'AC-8: a manifest with no auth and no key file still gives key_missing' {
        $res = Invoke-Register (New-ManifestDoc (New-Id 'ac8-none')) -KeyFile $script:MissingKey
        $res.Code | Should -Be 3
        $res.Payload.reason | Should -Be 'key_missing'
    }

    It 'AC-8: the launcher gives the wrapper -Subscription and -TokenFile, and no -KeyFile' {
        $run = New-Id 'ac8-argv'
        New-RequestedRun $run (Get-MemberLaunch) $script:MissingKey
        $argv = Get-WrapperArgs $run @('-KeyFile', $script:MissingKey)
        $argv | Should -Not -BeNullOrEmpty
        $argv | Should -Contain '-Subscription'
        $argv[[array]::IndexOf($argv, '-TokenFile') + 1] | Should -Be $script:TokenFile
        $argv | Should -Not -Contain '-KeyFile'
    }

    It 'AC-8: the run launches and finishes with no key file' {
        $run = New-Id 'ac8-run'
        New-RequestedRun $run (Get-MemberLaunch) $script:MissingKey
        $end = Start-RunToEnd $run -Extra @('-KeyFile', $script:MissingKey)
        $end.Child.Code | Should -Be 0 -Because "$($end.Child.Out) $($end.Child.Err)"
        @(Get-Calls $end.Calls).Count | Should -Be 1
    }
}

Describe 'AC-9: the token reaches claude and nothing else' {
    BeforeAll {
        $script:Run9 = New-Id 'ac9-run'
        New-RequestedRun $script:Run9 (Get-MemberLaunch) $script:MissingKey
        $script:End9 = Start-RunToEnd $script:Run9 -Env @{ ANTHROPIC_API_KEY = 'fake-parent-key'; ANTHROPIC_AUTH_TOKEN = 'fake-parent-auth' } -Extra @('-KeyFile', $script:MissingKey)
        $script:Call9 = @(Get-Calls $script:End9.Calls) | Select-Object -First 1
    }

    It 'AC-9: the CLI gets the token and the scrub' {
        $script:Call9 | Should -Not -BeNullOrEmpty -Because "$($script:End9.Child.Out) $($script:End9.Child.Err)"
        $script:Call9.env_names | Should -Contain 'CLAUDE_CODE_OAUTH_TOKEN'
        $script:Call9.token_sha256 | Should -Be $script:TokenSha
        $script:Call9.env_names | Should -Contain 'CLAUDE_CODE_SUBPROCESS_ENV_SCRUB'
        $script:Call9.scrub | Should -Be '1'
    }

    It 'AC-9: the CLI gets neither Anthropic key, though the parent has both' {
        $script:Call9 | Should -Not -BeNullOrEmpty
        $script:Call9.env_names | Should -Not -Contain 'ANTHROPIC_API_KEY'
        $script:Call9.env_names | Should -Not -Contain 'ANTHROPIC_AUTH_TOKEN'
    }

    It 'AC-9: the token is in no output and no file' {
        $script:End9.Child.Out | Should -Not -Match $script:Token
        $script:End9.Child.Err | Should -Not -Match $script:Token
        Get-FilesHoldingToken | Should -BeNullOrEmpty
    }

    It 'AC-9: the scan finds the token in a file that holds it' {
        $planted = "$script:Root/planted.txt"
        [System.IO.File]::WriteAllText($planted, "x$($script:Token)y")
        try { Get-FilesHoldingToken | Should -Contain ((Get-Item -LiteralPath $planted).FullName) }
        finally { Remove-Item -LiteralPath $planted }
    }

    It 'AC-9: the launcher refuses a missing token file with token_missing, and the CLI never starts' {
        $run = New-Id 'ac9-missing'
        New-RequestedRun $run (Get-MemberLaunch)
        $end = Start-RunToEnd $run -Extra @('-TokenFile', "$script:Root/credentials/no-such-token")
        (Get-Payload $end.Child).reason | Should -Be 'token_missing'
        $end.Child.Code | Should -Be 1
        Test-Path -LiteralPath $end.Calls | Should -BeFalse
    }

    It 'AC-9: the launcher refuses an empty token file with token_missing, and the CLI never starts' {
        $run = New-Id 'ac9-empty'
        $empty = "$script:Root/credentials/empty-token"
        [System.IO.File]::WriteAllText($empty, '')
        New-RequestedRun $run (Get-MemberLaunch)
        $end = Start-RunToEnd $run -Extra @('-TokenFile', $empty)
        (Get-Payload $end.Child).reason | Should -Be 'token_missing'
        Test-Path -LiteralPath $end.Calls | Should -BeFalse
    }

    It 'AC-9: the wrapper refuses a blank or missing token file, and the CLI never starts' {
        $blank = "$script:Root/credentials/blank-token"
        [System.IO.File]::WriteAllText($blank, "  `r`n")
        foreach ($file in @($blank, "$script:Root/credentials/no-such-token")) {
            $id = New-Id 'ac9-wrapper'
            $calls = "$script:Root/$id.calls.jsonl"
            $child = Start-Child $script:Invoke @('-Scheduled', '-Subscription', '-TokenFile', $file, '-PromptText', 'x', '-OutputDir', $script:Out,
                '-DispatchId', $id, '-ClaudeExecutable', $script:Mock, '-WorkingDirectory', $script:Project) -Env @{
                CREDITS_RUN_ID = $id; CREDITS_STATE_DB = $script:Db; CREDITS_SEGMENT = "seg-$id"; MOCK_CALL_LOG = $calls
            }
            $child.Code | Should -Not -Be 0
            $child.Err | Should -Match 'token_missing'
            Test-Path -LiteralPath $calls | Should -BeFalse
        }
    }

    It 'AC-9: -Subscription needs -Scheduled, a token file and no key file' {
        foreach ($case in @(
                @('-Subscription', '-TokenFile', $script:TokenFile),
                @('-Scheduled', '-Subscription'),
                @('-Scheduled', '-TokenFile', $script:TokenFile),
                @('-Scheduled', '-Subscription', '-TokenFile', $script:TokenFile, '-KeyFile', $script:KeyFile))) {
            $child = Start-Child $script:Invoke (@('-PromptText', 'x', '-OutputDir', $script:Out, '-ClaudeExecutable', $script:Mock) + $case) -Env @{
                CREDITS_RUN_ID = 'r'; CREDITS_STATE_DB = $script:Db; CREDITS_SEGMENT = 's'
            }
            $child.Code | Should -Be 2 -Because ($case -join ' ')
        }
    }

    It 'AC-9: no credits script assigns to CLAUDECODE or CLAUDE_CODE_ENTRYPOINT' {
        foreach ($file in @($script:Invoke, $script:Launcher, $script:Register, $script:Module)) {
            Get-EntrypointAssignments ([System.IO.File]::ReadAllText($file)) | Should -BeNullOrEmpty -Because $file
        }
    }

    It 'AC-9: the source check finds each form of assignment' {
        foreach ($bad in @('$env:CLAUDECODE = ""', '$psi.Environment["CLAUDE_CODE_ENTRYPOINT"] = "sdk-cli"',
                '$psi.EnvironmentVariables[''CLAUDECODE''] = "1"', '[Environment]::SetEnvironmentVariable("CLAUDE_CODE_ENTRYPOINT", "x")')) {
            @(Get-EntrypointAssignments $bad).Count | Should -Be 1 -Because $bad
        }
        Get-EntrypointAssignments 'if ($env:CLAUDECODE -eq "1") { }' | Should -BeNullOrEmpty
    }
}

Describe 'AC-10: allowed tools and the permission mode reach the CLI' {
    It 'AC-10: launch.allowed_tools and acceptEdits reach the CLI' {
        $run = New-Id 'ac10-tools'
        New-RequestedRun $run (Get-MemberLaunch @{ allowed_tools = @('Read', 'Edit', 'Bash(git status)') })
        $end = Start-RunToEnd $run
        $argv = @(@(Get-Calls $end.Calls)[0].argv)
        $argv[[array]::IndexOf($argv, '--allowedTools') + 1] | Should -Be 'Read,Edit,Bash(git status)'
        $argv[[array]::IndexOf($argv, '--permission-mode') + 1] | Should -Be 'acceptEdits'
    }

    It 'AC-10: with allowed_tools absent there is no --allowedTools flag' {
        $run = New-Id 'ac10-none'
        New-RequestedRun $run (Get-MemberLaunch)
        $end = Start-RunToEnd $run
        @(@(Get-Calls $end.Calls)[0].argv) | Should -Not -Contain '--allowedTools'
    }

    It 'AC-10: a key-route manifest gives the wrapper the same arguments as before this route' {
        $run = New-Id 'ac10-key'
        New-RequestedRun $run
        $argv = Get-WrapperArgs $run
        $argv | Should -Not -BeNullOrEmpty
        $flags = @($argv | Where-Object { "$_".StartsWith('-') -and "$_" -cmatch '^-[A-Z]' })
        $flags | Should -Be @('-Scheduled', '-PromptFile', '-KeyFile', '-ClaudeExecutable', '-MaxBudgetUsd', '-DispatchId', '-OutputDir',
            '-WorkingDirectory', '-TimeoutSec', '-Kind', '-PermissionMode', '-Effort', '-SessionId')
        $argv[[array]::IndexOf($argv, '-KeyFile') + 1] | Should -Be $script:KeyFile
    }

    It 'AC-10: a key-route run gets no token and no scrub from the wrapper' {
        $run = New-Id 'ac10-key-env'
        New-RequestedRun $run
        $end = Start-RunToEnd $run
        $call = @(Get-Calls $end.Calls)[0]
        $call.env_names | Should -Not -Contain 'CLAUDE_CODE_SUBPROCESS_ENV_SCRUB'
        $call.env_names | Should -Contain 'ANTHROPIC_API_KEY'
    }
}

Describe 'AC-12: the receipt check names the gate project' {
    BeforeAll {
        # The arguments of the last call of the mock gate.
        function Get-LastGateArgs {
            $line = [System.IO.File]::ReadAllLines("$script:Receipt.gate-argv.jsonl") | Select-Object -Last 1
            @($line | ConvertFrom-Json)
        }
        $script:KeyGateArgs = @('--check-receipt', $script:Receipt, '--project', $script:Project, '--python', $script:Py, '--claude', $script:Mock)
    }

    It 'AC-12: Register passes --gate-project when the manifest sets it' {
        $res = Invoke-Register (New-ManifestDoc (New-Id 'ac12-reg') (Get-MemberLaunch @{ gate_project = $script:GateProject }))
        $res.Code | Should -Be 0 -Because "$($res.Payload | ConvertTo-Json -Compress)"
        Get-LastGateArgs | Should -Be ($script:KeyGateArgs + @('--gate-project', $script:GateProject))
    }

    It 'AC-12: Register passes no --gate-project without it, on either route' {
        foreach ($launch in @(@{}, (Get-MemberLaunch))) {
            $res = Invoke-Register (New-ManifestDoc (New-Id 'ac12-none') $launch)
            $res.Code | Should -Be 0
            Get-LastGateArgs | Should -Be $script:KeyGateArgs
        }
    }

    It 'AC-12: the launcher passes --gate-project when the manifest sets it' {
        $run = New-Id 'ac12-start'
        New-RequestedRun $run (Get-MemberLaunch @{ gate_project = $script:GateProject })
        $null = Get-WrapperArgs $run
        Get-LastGateArgs | Should -Be ($script:KeyGateArgs + @('--gate-project', $script:GateProject))
    }

    It 'AC-12: the launcher passes no --gate-project on a key-route run' {
        $run = New-Id 'ac12-start-key'
        New-RequestedRun $run
        $null = Get-WrapperArgs $run
        Get-LastGateArgs | Should -Be $script:KeyGateArgs
    }
}

Describe 'AC-13: a resume on the member route' {
    BeforeAll {
        $script:Run13 = New-Id 'ac13-run'
        New-RequestedRun $script:Run13 (Get-MemberLaunch) $script:MissingKey
        $script:End13 = Start-RunToEnd $script:Run13 -Extra @('-KeyFile', $script:MissingKey)
        $state = (@(Get-Rows 'SELECT state FROM runs WHERE run_id = ?' @($script:Run13)) | Select-Object -First 1).state
        if ($state -eq 'finalizing') { Assert-Store 'classify' @('--run-id', $script:Run13, '--to', 'stopped', '--class', 'exited') | Out-Null }
        $script:First13 = @(Get-Rows 'SELECT * FROM attempts WHERE run_id = ?' @($script:Run13)) | Select-Object -First 1
        $brief = "$script:Root/resume-$script:Run13.md"
        Set-Content -LiteralPath $brief -Value 'the resume brief' -Encoding utf8NoBOM
        Assert-Store 'request' @('--run-id', $script:Run13, '--started-by', 'human-command', '--resume', '--resume-mode', 'session', '--brief', $brief, '--request-id', "req1-$script:Run13") | Out-Null
        $script:Child13 = Start-Child $script:Launcher (Get-LauncherArgs $script:Run13 @('-KeyFile', $script:MissingKey)) -Env @{
            MOCK_CALL_LOG = $script:End13.Calls; ANTHROPIC_API_KEY = 'fake-parent-key'; ANTHROPIC_AUTH_TOKEN = 'fake-parent-auth'
        }
        $script:Calls13 = @(Get-Calls $script:End13.Calls)
    }

    It 'AC-13: the resumed launch continues the same session, with no key file' {
        $script:Child13.Code | Should -Be 0 -Because "$($script:Child13.Out) $($script:Child13.Err)"
        $script:Calls13.Count | Should -Be 2
        $argv = @($script:Calls13[1].argv)
        $argv[[array]::IndexOf($argv, '--resume') + 1] | Should -Be $script:First13.expected_session_id
        $script:Calls13[1].stdin | Should -Match 'resume brief'
    }

    It 'AC-13: the resumed launch gets the token and the scrub, and neither Anthropic key' {
        $script:Calls13[1].token_sha256 | Should -Be $script:TokenSha
        $script:Calls13[1].scrub | Should -Be '1'
        $script:Calls13[1].env_names | Should -Not -Contain 'ANTHROPIC_API_KEY'
        $script:Calls13[1].env_names | Should -Not -Contain 'ANTHROPIC_AUTH_TOKEN'
        Get-FilesHoldingToken | Should -BeNullOrEmpty
    }

    It 'AC-13: without -Subscription a missing key file still stops with key file not found' {
        $id = New-Id 'ac13-key'
        $calls = "$script:Root/$id.calls.jsonl"
        $child = Start-Child $script:Invoke @('-Scheduled', '-Resume', $script:First13.dispatch_id, '-KeyFile', $script:MissingKey, '-PromptText', 'x',
            '-OutputDir', $script:Out, '-DispatchId', $id, '-ClaudeExecutable', $script:Mock) -Env @{
            CREDITS_RUN_ID = $id; CREDITS_STATE_DB = $script:Db; CREDITS_SEGMENT = "seg-$id"; MOCK_CALL_LOG = $calls
        }
        $child.Code | Should -Be 2
        $child.Err | Should -Match 'key file not found'
        Test-Path -LiteralPath $calls | Should -BeFalse
    }
}

Describe 'AC-22: Get-RunClass on the task.md a member writes' {
    BeforeAll {
        $tokens = $null; $parseErrors = $null
        $watch = Join-Path $script:Skill 'Watch-CreditsRuns.ps1'
        $ast = [System.Management.Automation.Language.Parser]::ParseFile($watch, [ref]$tokens, [ref]$parseErrors)
        foreach ($fn in $ast.FindAll({ param($n) $n -is [System.Management.Automation.Language.FunctionDefinitionAst] }, $false)) {
            . ([scriptblock]::Create($fn.Extent.Text))
        }
        Import-Module $script:Module -Force -DisableNameChecking
        $script:StoppedGates = @{}
        $table = [regex]::Match([System.IO.File]::ReadAllText($watch), '(?s)\$script:StoppedGates = @\{(.*?)\r?\n\}')
        foreach ($line in $table.Groups[1].Value -split "`r?`n") {
            if ($line -match "^\s*([a-z_]+)\s*=\s*'([^']+)'") { $script:StoppedGates[$Matches[1]] = $Matches[2] }
        }
        $script:UnitRoot = "$script:Root/ac22"
        $script:OutDir = "$script:UnitRoot/out"
        $script:ChildTimeoutMs = 120000
        $script:LogPath = "$script:UnitRoot/monitor.jsonl"
        $script:PreflightTool = Join-Path $script:Repo 'tools/completion_preflight.py'
        $script:FleetPy = Join-Path $script:Repo '.agent/fleet/fleet.py'
        New-Item -ItemType Directory -Force -Path "$script:OutDir/probe", "$script:UnitRoot/.fleet-run" | Out-Null

        # The task.md comes from fleet.py's member_task_md, so this pins what a member really writes.
        function Get-MemberRunClass([string]$Gate, [string]$FinalStatus) {
            $code = 'import importlib.util, sys; s = importlib.util.spec_from_file_location("fleet", sys.argv[1]); m = importlib.util.module_from_spec(s); sys.modules["fleet"] = m; s.loader.exec_module(m); print(m.member_task_md(sys.argv[2]), end="")'
            $text = (& $script:Py -X utf8 -c $code $script:FleetPy $Gate | Out-String)
            $text | Should -Match "(?m)^stop_gate: `"$Gate`"\r?$"
            [System.IO.File]::WriteAllText("$script:UnitRoot/.fleet-run/task.md", $text)
            Set-Content -LiteralPath "$script:OutDir/probe/final.md" -Value "$FinalStatus`n" -Encoding utf8NoBOM -NoNewline
            Set-Content -LiteralPath "$script:OutDir/probe/status.json" -Value '{"exit_code":0}' -Encoding utf8NoBOM -NoNewline
            Get-RunClass ([pscustomobject]@{
                    kind     = 'exec'
                    manifest = @{ kind = 'exec'; project_root = $script:UnitRoot; plan_folder = '.fleet-run' }
                    segment  = @{ dispatch_id = 'probe'; stop_class = 'exited'; exit_code = 0 }
                })
        }
    }

    It 'AC-22: a released gate and STOPPED:decision is decision' {
        (Get-MemberRunClass 'released:human-gate' 'Status: STOPPED:decision').Class | Should -Be 'decision'
    }

    It 'AC-22: an armed gate and STOPPED:decision is unknown' {
        $verdict = Get-MemberRunClass 'armed' 'Status: STOPPED:decision'
        $verdict.Class | Should -Be 'unknown'
        @($verdict.Missing) | Should -Contain 'stop_gate:released:human-gate'
    }

    It 'AC-22: Status: DONE is done_unverified, with the landings it lacks named' {
        $verdict = Get-MemberRunClass 'armed' 'Status: DONE'
        $verdict.Class | Should -Be 'done_unverified'
        @($verdict.Missing) | Should -Contain 'capture'
    }
}

Describe 'AC-23: fleet.py normalizes the real export of a run' {
    BeforeAll {
        $script:FleetPy = Join-Path $script:Repo '.agent/fleet/fleet.py'
        $script:Normalize = "$script:Root/normalize_view.py"
        Set-Content -LiteralPath $script:Normalize -Encoding utf8NoBOM -Value @'
import importlib.util
import json
import sys
from pathlib import Path

spec = importlib.util.spec_from_file_location("fleet", sys.argv[1])
fleet = importlib.util.module_from_spec(spec)
sys.modules["fleet"] = fleet
spec.loader.exec_module(fleet)
if sys.argv[2] == "--states":
    print(json.dumps(fleet.AGENT_RUN_STATES))
else:
    view = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8-sig"))
    print(json.dumps({**fleet.normalize_view(view, Path(sys.argv[3])), "limit": fleet.AGENT_FINAL_MAX_BYTES}))
'@
        $script:Run23 = New-Id 'ac23'
        New-RequestedRun $script:Run23 (Get-MemberLaunch)
        $null = Start-RunToEnd $script:Run23
        $script:Seg23 = @(Get-Rows 'SELECT segment_id, dispatch_id FROM segments WHERE run_id = ?' @($script:Run23))[0]

        function Set-Store([string]$Sql, [string[]]$Params) {
            $code = 'import sqlite3, sys; c = sqlite3.connect(sys.argv[1]); c.execute(sys.argv[2], sys.argv[3:]); c.commit(); c.close()'
            & $script:Py -X utf8 -c $code $script:Db $Sql @Params
            if ($LASTEXITCODE -ne 0) { throw "store update failed: $Sql" }
        }

        # The real Get-CreditsRun.ps1 -Export, then fleet.py's normalize_view on the file it wrote.
        function Get-Normalized([string]$State) {
            Set-Store 'UPDATE runs SET state = ? WHERE run_id = ?' @($State, $script:Run23)
            $child = Start-Child (Join-Path $script:Skill 'Get-CreditsRun.ps1') @($script:Run23, '-StateDb', $script:Db, '-OutputDir', $script:Out, '-Export')
            if ($child.Code -ne 0) { throw "export failed: $($child.Code) $($child.Err)" }
            $view = Join-Path (Split-Path -Parent $script:Db) "runs/$script:Run23/view.json"
            (& $script:Py -X utf8 $script:Normalize $script:FleetPy $view $script:Root | Out-String) | ConvertFrom-Json
        }

        function Set-Final([string]$Text) {
            $folder = "$script:Out/$($script:Seg23.dispatch_id)"
            New-Item -ItemType Directory -Force -Path $folder | Out-Null
            [System.IO.File]::WriteAllText("$folder/final.md", $Text)
        }

        $script:States23 = (& $script:Py -X utf8 $script:Normalize $script:FleetPy '--states' | Out-String) | ConvertFrom-Json
    }

    It 'AC-23: the table holds the plan''s three groups and every run state' {
        @($script:States23.running) | Should -Be @('registering', 'registered', 'requested', 'waiting', 'launching', 'running', 'finalizing')
        @($script:States23.done) | Should -Be @('done', 'done_unverified')
        @($script:States23.stopped) | Should -Be @('stopped', 'parked', 'done_unverified', 'failed', 'cancelled', 'registration_failed')
    }

    It 'AC-23: every state of the table gives its group' {
        Set-Final "work`nStatus: DONE`n"
        foreach ($group in 'running', 'stopped') {
            foreach ($state in @($script:States23.$group)) {
                if ($state -eq 'done_unverified') { continue }
                $r = Get-Normalized $state
                "$state=$($r.run_state)" | Should -Be "$state=$group"
                $r.verified | Should -BeFalse
            }
        }
        $done = Get-Normalized 'done'
        $done.run_state | Should -Be 'done'
        $done.verified | Should -BeTrue
    }

    It 'AC-23: done_unverified with a final DONE is done, unverified' {
        Set-Final "work`nStatus: DONE`n"
        $r = Get-Normalized 'done_unverified'
        $r.run_state | Should -Be 'done'
        $r.verified | Should -BeFalse
        $r.final_status | Should -Be 'DONE'
    }

    It 'AC-23: done_unverified with no DONE is stopped' {
        Set-Final "work`nStatus: STOPPED:decision`n"
        $r = Get-Normalized 'done_unverified'
        $r.run_state | Should -Be 'stopped'
        $r.final_status | Should -Be 'STOPPED:decision'
    }

    It 'AC-23: a state outside the table is unknown' {
        (Get-Normalized 'made_up_state').run_state | Should -Be 'unknown'
    }

    It 'AC-23: cancelled with an unfinished segment is still running' {
        $finalized = @(Get-Rows 'SELECT finalized_utc FROM segments WHERE run_id = ?' @($script:Run23))[0].finalized_utc
        Set-Store 'UPDATE segments SET finalized_utc = NULL WHERE run_id = ?' @($script:Run23)
        try { (Get-Normalized 'cancelled').run_state | Should -Be 'running' }
        finally { Set-Store 'UPDATE segments SET finalized_utc = ? WHERE run_id = ?' @($finalized, $script:Run23) }
    }

    It 'AC-23: stop_class comes from the view''s class' {
        Set-Store 'UPDATE runs SET stop_class = ? WHERE run_id = ?' @('decision', $script:Run23)
        (Get-Normalized 'stopped').stop_class | Should -Be 'decision'
    }

    It 'AC-23: final_text is final.md, cut to its tail over the limit' {
        Set-Final 'short answer'
        (Get-Normalized 'stopped').final_text | Should -Be 'short answer'
        $limit = (Get-Normalized 'stopped').limit
        Set-Final (('a' * 100) + ('b' * $limit))
        $text = (Get-Normalized 'stopped').final_text
        $text.Length | Should -Be $limit
        $text | Should -Not -Match 'a'
    }

    It 'AC-23: no final.md gives a null final_text' {
        Remove-Item -LiteralPath "$script:Out/$($script:Seg23.dispatch_id)/final.md" -Force
        $r = Get-Normalized 'stopped'
        $r.run_state | Should -Be 'stopped'
        $r.final_text | Should -BeNullOrEmpty
    }

    It 'AC-23: outbox carries the reply text a job wrote with ack' {
        $payload = '{"text": "row 1 of 2", "msg_id": "m-1"}'
        Set-Store 'INSERT INTO outbox_events (run_id, kind, semantic_key, payload_json, created_utc) VALUES (?, ?, ?, ?, ?)' @($script:Run23, 'ack', "ack:m-$script:Run23", $payload, '2026-11-05T00:00:00Z')
        $entry = @((Get-Normalized 'stopped').outbox | Where-Object { $_.kind -eq 'ack' })[0]
        $entry.text | Should -Be 'row 1 of 2'
        $entry.semantic_key | Should -Be "ack:m-$script:Run23"
    }

    It 'AC-23: session_id is the latest segment''s session' {
        $expected = @(Get-Rows 'SELECT expected_session_id FROM segments WHERE run_id = ?' @($script:Run23))[0].expected_session_id
        (Get-Normalized 'stopped').session_id | Should -Be $expected
    }
}
