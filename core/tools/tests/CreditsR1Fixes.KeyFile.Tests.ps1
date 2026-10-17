# R1-F8 (execution review round 1) of docs/execution/plans/2026-10-15-scheduled-credits-runs.
# AC-A.7: the credits -ValidateOnly checks the parameters, the brief and the key file (presence
# and ACL only), then exits 0 with no launch. It must not read the key file contents. A normal
# credits launch keeps the full key check and refuses a file that holds no Console key before any
# process starts. A direct tools/Invoke-ClaudeDispatch.ps1 -ApiKeyFile -ValidateOnly call (not the
# credits front end) keeps its content check unchanged.
#
# Every key file here is a fixture in a temp folder with fixture text, never a real key. The CLI is
# a mock that logs each session call.

BeforeAll {
    $script:Repo = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
    $script:Credits = Join-Path $script:Repo '.agent/skills/claude-credits/Invoke-ClaudeCredits.ps1'
    $script:Dispatch = Join-Path $script:Repo 'tools/Invoke-ClaudeDispatch.ps1'
    $script:Root = "{{RECEIPTS_DIR}}/credits-r1-keyfile-tests/$([guid]::NewGuid().ToString('N'))"
    $script:Out = "$script:Root/dispatch"
    $script:WorkDir = "$script:Root/work"
    New-Item -ItemType Directory -Force -Path $script:Out, $script:WorkDir | Out-Null

    # A file that holds no Console key: any content check refuses it.
    $script:BadKey = "$script:Root/keys/not-a-key.key"
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $script:BadKey) | Out-Null
    Set-Content -LiteralPath $script:BadKey -Value 'fixture-text-that-is-not-a-console-key' -Encoding utf8NoBOM
    $script:Prompt = "$script:Root/prompt.md"
    Set-Content -LiteralPath $script:Prompt -Value 'credits r1 key file test prompt' -Encoding utf8NoBOM

    # A key file inside a git work tree (metadata, not content).
    $script:RepoDir = "$script:Root/fixture-repo"
    New-Item -ItemType Directory -Force -Path $script:RepoDir | Out-Null
    & git -C $script:RepoDir init -q *> $null
    $script:InRepoKey = "$script:RepoDir/in-repo.key"
    Set-Content -LiteralPath $script:InRepoKey -Value 'fixture-text-that-is-not-a-console-key' -Encoding utf8NoBOM

    $venvPy = Join-Path $script:Repo '.venv/Scripts/python.exe'
    $py = if (Test-Path -LiteralPath $venvPy) { $venvPy } else { (Get-Command python -ErrorAction Stop).Source }
    $script:BasePython = (& $py -c 'import sys; print(sys._base_executable)' | Out-String).Trim()
    $mockPy = "$script:Root/mock_claude.py"
    Set-Content -LiteralPath $mockPy -Encoding utf8NoBOM -Value @'
import json
import os
import sys

args = sys.argv[1:]
if "--version" in args:
    print("2.1.296 (Claude Code)")
    sys.exit(0)
sys.stdin.read()
log = os.environ.get("MOCK_CALL_LOG")
if log:
    with open(log, "a", encoding="utf-8") as f:
        f.write(json.dumps(args) + "\n")
print(json.dumps({"type": "result", "result": "MOCK_RESULT_OK", "is_error": False, "total_cost_usd": 0.0}))
sys.exit(0)
'@
    $script:Mock = "$script:Root/mock_claude.bat"
    Set-Content -LiteralPath $script:Mock -Encoding ascii -Value "@echo off`r`n`"$script:BasePython`" -X utf8 `"$mockPy`" %*"

    # pwsh -File <Script> <Arguments> with no CLAUDECODE, CLAUDE_CODE_ENTRYPOINT, CREDITS_* or MOCK_*
    # from this process, plus $Env.
    function Start-Child([string]$Script, [string[]]$Arguments, [hashtable]$Env = @{}) {
        $psi = [System.Diagnostics.ProcessStartInfo]::new('pwsh')
        foreach ($a in @('-NoProfile', '-File', $Script) + $Arguments) { $psi.ArgumentList.Add([string]$a) }
        $psi.UseShellExecute = $false
        $psi.RedirectStandardOutput = $true
        $psi.RedirectStandardError = $true
        foreach ($name in @($psi.Environment.Keys)) {
            if ($name -in @('CLAUDECODE', 'CLAUDE_CODE_ENTRYPOINT') -or $name -like 'CREDITS_*' -or $name -like 'MOCK_*') { $null = $psi.Environment.Remove($name) }
        }
        foreach ($k in $Env.Keys) { $psi.Environment[$k] = [string]$Env[$k] }
        $p = [System.Diagnostics.Process]::Start($psi)
        $so = $p.StandardOutput.ReadToEndAsync(); $se = $p.StandardError.ReadToEndAsync()
        if (-not $p.WaitForExit(240000)) { & taskkill.exe /PID $p.Id /T /F *> $null; throw "child timed out: $Script" }
        $p.WaitForExit()
        [pscustomobject]@{ Code = $p.ExitCode; Out = $so.Result; Err = $se.Result }
    }

    function New-Id([string]$Prefix) { "$Prefix-$([guid]::NewGuid().ToString('N').Substring(0, 10))" }

    function Invoke-Credits([string]$Id, [string]$KeyFile, [string[]]$Extra = @(), [hashtable]$Env = @{}) {
        $a = @('-PromptFile', $script:Prompt, '-DispatchId', $Id, '-OutputDir', $script:Out, '-KeyFile', $KeyFile,
            '-ClaudeExecutable', $script:Mock, '-WorkingDirectory', $script:WorkDir, '-Effort', 'low', '-TimeoutSec', '120') + $Extra
        Start-Child $script:Credits $a $Env
    }

    function Invoke-Dispatch([string]$Id, [string]$KeyFile, [string[]]$Extra = @(), [hashtable]$Env = @{}) {
        $a = @('-ModelClass', 'isolated_worker', '-AuthorVendor', 'anthropic', '-ReasoningEffort', 'low', '-PermissionMode', 'plan',
            '-PromptFile', $script:Prompt, '-DispatchId', $Id, '-OutputDir', $script:Out, '-ApiKeyFile', $KeyFile,
            '-ClaudeExecutable', $script:Mock, '-WorkingDirectory', $script:WorkDir) + $Extra
        Start-Child $script:Dispatch $a $Env
    }
}

AfterAll {
    if ($script:Root -and (Test-Path -LiteralPath $script:Root)) { Remove-Item -LiteralPath $script:Root -Recurse -Force -ErrorAction SilentlyContinue }
}

Describe 'R1-F8: the credits -ValidateOnly checks the key file presence and ACL only' {
    It 'R1-F8: a key file whose contents are not a key passes the credits -ValidateOnly (contents not read), no launch' {
        $id = New-Id 'f8-vo-bad'; $log = "$script:Root/$id.calls.txt"
        $res = Invoke-Credits $id $script:BadKey @('-ValidateOnly') @{ MOCK_CALL_LOG = $log }
        $res.Code | Should -Be 0 -Because $res.Err
        $res.Out | Should -Match 'dispatch_args_ok'
        "$($res.Out)$($res.Err)" | Should -Not -Match 'api_key_file_invalid'
        Test-Path -LiteralPath $log | Should -BeFalse
        Test-Path -LiteralPath "$script:Out/$id" | Should -BeFalse
    }

    It 'R1-F8: a normal credits launch with the same file is refused api_key_file_invalid before any process starts' {
        $id = New-Id 'f8-run-bad'; $log = "$script:Root/$id.calls.txt"
        $res = Invoke-Credits $id $script:BadKey @() @{ MOCK_CALL_LOG = $log }
        $res.Code | Should -Not -Be 0
        $res.Err | Should -Match 'api_key_file_invalid'
        Test-Path -LiteralPath $log | Should -BeFalse
        Test-Path -LiteralPath "$script:Out/$id" | Should -BeFalse
    }

    It 'R1-F8: a missing key file still fails the credits -ValidateOnly' {
        $id = New-Id 'f8-vo-missing'; $log = "$script:Root/$id.calls.txt"
        $res = Invoke-Credits $id "$script:Root/keys/no-such.key" @('-ValidateOnly') @{ MOCK_CALL_LOG = $log }
        $res.Code | Should -Not -Be 0
        $res.Out | Should -Not -Match 'dispatch_args_ok'
        Test-Path -LiteralPath $log | Should -BeFalse
    }

    It 'R1-F8: a key file locked against readers fails the credits -ValidateOnly (the ACL and open check stays)' {
        $id = New-Id 'f8-vo-locked'; $log = "$script:Root/$id.calls.txt"
        $locked = "$script:Root/keys/locked.key"
        Set-Content -LiteralPath $locked -Value 'fixture-text-that-is-not-a-console-key' -Encoding utf8NoBOM
        $hold = [System.IO.File]::Open([System.IO.Path]::GetFullPath($locked), 'Open', 'ReadWrite', 'None')
        try { $res = Invoke-Credits $id $locked @('-ValidateOnly') @{ MOCK_CALL_LOG = $log } } finally { $hold.Dispose() }
        $res.Code | Should -Not -Be 0
        $res.Out | Should -Not -Match 'dispatch_args_ok'
        Test-Path -LiteralPath $log | Should -BeFalse
    }

    It 'R1-F8: a key file inside a git work tree still fails the credits -ValidateOnly (api_key_file_in_repo)' {
        $id = New-Id 'f8-vo-repo'; $log = "$script:Root/$id.calls.txt"
        $res = Invoke-Credits $id $script:InRepoKey @('-ValidateOnly') @{ MOCK_CALL_LOG = $log }
        $res.Code | Should -Not -Be 0
        $res.Err | Should -Match 'api_key_file_in_repo'
        Test-Path -LiteralPath $log | Should -BeFalse
    }
}

Describe 'R1-F8: the direct dispatch keeps its key checks' {
    It 'R1-F8: Invoke-ClaudeDispatch.ps1 -ApiKeyFile -ValidateOnly (no credits front end) still refuses api_key_file_invalid' {
        $id = New-Id 'f8-direct'; $log = "$script:Root/$id.calls.txt"
        $res = Invoke-Dispatch $id $script:BadKey @('-ValidateOnly') @{ MOCK_CALL_LOG = $log }
        $res.Code | Should -Not -Be 0
        $res.Err | Should -Match 'api_key_file_invalid'
        Test-Path -LiteralPath $log | Should -BeFalse
        Test-Path -LiteralPath "$script:Out/$id" | Should -BeFalse
    }

    It 'R1-F8: -KeyFileMetadataOnly without -ValidateOnly is refused before any process starts' {
        $id = New-Id 'f8-meta-run'; $log = "$script:Root/$id.calls.txt"
        $res = Invoke-Dispatch $id $script:BadKey @('-KeyFileMetadataOnly') @{ MOCK_CALL_LOG = $log }
        $res.Code | Should -Not -Be 0
        $res.Err | Should -Match 'key_file_metadata_only_needs_validate_only'
        Test-Path -LiteralPath $log | Should -BeFalse
        Test-Path -LiteralPath "$script:Out/$id" | Should -BeFalse
    }
}
