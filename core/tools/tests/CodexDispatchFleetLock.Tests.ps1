# One Codex job at a time on a fleet member (WP-A4 of docs/execution/plans/2026-11-04-fleet-agents).
# When FLEET_CODEX_LOCK is set, Invoke-CodexDispatch.ps1 holds that file for its whole life, and a job inherits the
# variable, so a job that calls the wrapper finds it busy.
#
# Every launch goes to a stub `codex` first on PATH, which records each exec. The registry is a fixture, so the home
# registry is not read.

BeforeAll {
    $script:Repo = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
    $script:Wrapper = Join-Path $script:Repo 'tools/Invoke-CodexDispatch.ps1'
    $script:Root = "{{RECEIPTS_DIR}}/codex-lock-tests/$([guid]::NewGuid().ToString('N'))"
    $script:Bin = "$script:Root/bin"
    $script:Out = "$script:Root/dispatch"
    $script:RegistryHome = "$script:Root/registry-home"
    New-Item -ItemType Directory -Force -Path $script:Bin, $script:Out, "$script:RegistryHome/tools" | Out-Null

    $script:Saved = @{}
    foreach ($name in 'Path', 'AGENT_MODEL_REGISTRY', 'AGENT_MODEL_REGISTRY_HOME', 'FLEET_CODEX_LOCK') {
        $script:Saved[$name] = [Environment]::GetEnvironmentVariable($name)
    }
    $moduleHome = if ($env:AGENT_MODEL_REGISTRY_HOME) { $env:AGENT_MODEL_REGISTRY_HOME } else { Join-Path $env:USERPROFILE '.agent' }
    Copy-Item -LiteralPath (Join-Path $moduleHome 'tools/ModelRegistry.psm1') -Destination "$script:RegistryHome/tools/ModelRegistry.psm1"
    @{
        schema_version = 1
        updated = '2026-01-01'
        pins = @{}
        classes = @{ isolated_worker = @{ contract = @{ effort_default = 'medium' }; bindings = @{ 'codex-cli' = @{ slug = 'fake-codex' } } } }
        catalog = @{ 'fake-codex' = @{ vendor = 'openai'; harness_ids = @{ 'codex-cli' = @{ medium = 'fake-codex'; high = 'fake-codex' } }; efforts = @('medium', 'high') } }
    } | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath "$script:RegistryHome/model-registry.json" -Encoding utf8NoBOM
    # The file itself, so neither the wrapper nor any version of the module looks at a home registry.
    $env:AGENT_MODEL_REGISTRY = "$script:RegistryHome/model-registry.json"
    $env:AGENT_MODEL_REGISTRY_HOME = $null
    $env:Path = "$script:Bin;$env:Path"

    $stub = @'
Add-Content -LiteralPath $env:STUB_CALLS -Value 'exec'
for ($i = 0; $i -lt $args.Count; $i++) {
    if ($args[$i] -eq '-o') { Set-Content -LiteralPath $args[$i + 1] -Value 'Status: DONE' -Encoding utf8NoBOM }
}
if ($env:STUB_ENTERED) {
    Set-Content -LiteralPath $env:STUB_ENTERED -Value 'entered'
    $deadline = (Get-Date).AddSeconds(60)
    while (-not (Test-Path -LiteralPath $env:STUB_RELEASE) -and (Get-Date) -lt $deadline) { Start-Sleep -Milliseconds 100 }
}
if ($env:STUB_NESTED) {
    $record = $env:STUB_NESTED
    $env:STUB_NESTED = $null
    $text = & pwsh -NoProfile -NonInteractive -File $env:STUB_WRAPPER -NonReviewDispatch -ModelClass isolated_worker -Mode ReviewWorkspace -PromptText inner -OutputDir $env:STUB_OUT 2>&1
    Set-Content -LiteralPath $record -Value "$LASTEXITCODE $text"
}
Write-Output '{"type":"thread.started","thread_id":"11111111-2222-3333-4444-555555555555"}'
Write-Output '{"type":"turn.completed"}'
exit 0
'@
    [IO.File]::WriteAllText("$script:Bin/fake-codex.ps1", $stub)
    $shim = "@echo off`r`nif `"%~1`"==`"--version`" (`r`n  echo codex-cli 9.9.9`r`n  exit /b 0`r`n)`r`npwsh -NoProfile -ExecutionPolicy Bypass -File `"%~dp0fake-codex.ps1`" %*`r`nexit /b %ERRORLEVEL%`r`n"
    [IO.File]::WriteAllText("$script:Bin/codex.cmd", $shim)

    $env:STUB_WRAPPER = $script:Wrapper
    $env:STUB_OUT = $script:Out

    function script:Invoke-Wrapper {
        param([string[]]$Extra = @())
        $id = "lock-$([guid]::NewGuid().ToString('N').Substring(0, 12))"
        $text = & pwsh -NoProfile -NonInteractive -File $script:Wrapper -NonReviewDispatch -ModelClass isolated_worker -Mode ReviewWorkspace -PromptText outer -DispatchId $id -OutputDir $script:Out @Extra 2>&1
        [pscustomobject]@{ Exit = $LASTEXITCODE; Text = ($text | Out-String) }
    }

    function script:Get-StubCalls {
        if (Test-Path -LiteralPath $env:STUB_CALLS) { @(Get-Content -LiteralPath $env:STUB_CALLS).Count } else { 0 }
    }
}

AfterAll {
    foreach ($name in $script:Saved.Keys) { [Environment]::SetEnvironmentVariable($name, $script:Saved[$name]) }
    foreach ($name in 'STUB_WRAPPER', 'STUB_OUT', 'STUB_CALLS', 'STUB_ENTERED', 'STUB_RELEASE', 'STUB_NESTED') {
        [Environment]::SetEnvironmentVariable($name, $null)
    }
    Remove-Item -LiteralPath $script:Root -Recurse -Force -ErrorAction SilentlyContinue
}

Describe 'FLEET_CODEX_LOCK' {
    BeforeEach {
        $script:Case = "$script:Root/case-$([guid]::NewGuid().ToString('N'))"
        New-Item -ItemType Directory -Path $script:Case | Out-Null
        $script:Lock = "$script:Case/codex.lock"
        $env:STUB_CALLS = "$script:Case/calls.txt"
        $env:FLEET_CODEX_LOCK = $script:Lock
        $env:STUB_ENTERED = $null
        $env:STUB_RELEASE = $null
        $env:STUB_NESTED = $null
    }

    Context 'with the lock held' {
        It 'AC-31: a wrapper exits 11 with codex_job_busy, and the stub is not called' {
            $held = [IO.File]::Open($script:Lock, 'OpenOrCreate', 'ReadWrite', 'None')
            try {
                $run = Invoke-Wrapper
            } finally {
                $held.Dispose()
            }
            $run.Exit | Should -Be 11
            $run.Text | Should -Match 'codex_job_busy'
            Get-StubCalls | Should -Be 0
        }

        It 'AC-31: a second wrapper is busy while the first runs its job, and the first still finishes' {
            $env:STUB_ENTERED = "$script:Case/entered"
            $env:STUB_RELEASE = "$script:Case/release"
            $firstArgs = @(
                '-NoProfile', '-NonInteractive', '-File', $script:Wrapper, '-NonReviewDispatch', '-ModelClass', 'isolated_worker',
                '-Mode', 'ReviewWorkspace', '-PromptText', 'first', '-DispatchId', "first-$([guid]::NewGuid().ToString('N').Substring(0, 12))", '-OutputDir', $script:Out
            )
            $first = Start-Process pwsh -ArgumentList $firstArgs -PassThru -NoNewWindow -RedirectStandardOutput "$script:Case/first.out" -RedirectStandardError "$script:Case/first.err"
            try {
                $deadline = (Get-Date).AddSeconds(60)
                while (-not (Test-Path -LiteralPath $env:STUB_ENTERED) -and (Get-Date) -lt $deadline) { Start-Sleep -Milliseconds 100 }
                Test-Path -LiteralPath $env:STUB_ENTERED | Should -BeTrue
                $second = Invoke-Wrapper
            } finally {
                Set-Content -LiteralPath $env:STUB_RELEASE -Value 'release'
            }
            $second.Exit | Should -Be 11
            $second.Text | Should -Match 'codex_job_busy'
            $first.WaitForExit(120000) | Should -BeTrue
            $first.ExitCode | Should -Be 0
            Get-StubCalls | Should -Be 1
        }

        It 'AC-31: a job that calls the wrapper gets 11, because it inherits the variable' {
            $env:STUB_NESTED = "$script:Case/nested.txt"
            $run = Invoke-Wrapper
            $run.Exit | Should -Be 0
            $nested = Get-Content -LiteralPath "$script:Case/nested.txt" -Raw
            $nested | Should -Match '^11 '
            $nested | Should -Match 'codex_job_busy'
            Get-StubCalls | Should -Be 1
        }
    }

    Context 'with the lock free' {
        It 'AC-31: a wrapper runs its job, and a lock file left behind does not stop the next one' {
            (Invoke-Wrapper).Exit | Should -Be 0
            Test-Path -LiteralPath $script:Lock | Should -BeTrue
            (Invoke-Wrapper).Exit | Should -Be 0
            Get-StubCalls | Should -Be 2
        }

        It 'AC-31: a lock that cannot be opened is busy, and the stub is not called' {
            $env:FLEET_CODEX_LOCK = "$script:Case/no-such-folder/codex.lock"
            $run = Invoke-Wrapper
            $run.Exit | Should -Be 11
            Get-StubCalls | Should -Be 0
        }
    }

    Context '-CodexExecutable' {
        It 'AC-31: with the lock set it is refused, and the named program is not run' {
            $marker = "$script:Case/ran.txt"
            $other = "$script:Case/other.cmd"
            [IO.File]::WriteAllText($other, "@echo ran> `"$marker`"`r`n")
            $run = Invoke-Wrapper -Extra @('-CodexExecutable', $other)
            $run.Exit | Should -Be 1
            $run.Text | Should -Match 'codex_executable_refused'
            Test-Path -LiteralPath $marker | Should -BeFalse
            Get-StubCalls | Should -Be 0
        }

        It 'AC-31: with the lock set it is refused before the lock is taken' {
            $run = Invoke-Wrapper -Extra @('-CodexExecutable', 'codex')
            $run.Text | Should -Match 'codex_executable_refused'
            Test-Path -LiteralPath $script:Lock | Should -BeFalse
        }
    }

    Context 'with the variable unset' {
        BeforeEach { $env:FLEET_CODEX_LOCK = $null }

        It 'AC-31: no lock file is made' {
            (Invoke-Wrapper).Exit | Should -Be 0
            Test-Path -LiteralPath $script:Lock | Should -BeFalse
            Get-StubCalls | Should -Be 1
        }

        It 'AC-31: -CodexExecutable works as it does today' {
            $run = Invoke-Wrapper -Extra @('-CodexExecutable', "$script:Bin/codex.cmd")
            $run.Exit | Should -Be 0
            Get-StubCalls | Should -Be 1
        }

        It 'AC-31: two wrappers do not wait for each other' {
            $env:STUB_ENTERED = "$script:Case/entered"
            $env:STUB_RELEASE = "$script:Case/release"
            $firstArgs = @(
                '-NoProfile', '-NonInteractive', '-File', $script:Wrapper, '-NonReviewDispatch', '-ModelClass', 'isolated_worker',
                '-Mode', 'ReviewWorkspace', '-PromptText', 'first', '-DispatchId', "first-$([guid]::NewGuid().ToString('N').Substring(0, 12))", '-OutputDir', $script:Out
            )
            $first = Start-Process pwsh -ArgumentList $firstArgs -PassThru -NoNewWindow -RedirectStandardOutput "$script:Case/first.out" -RedirectStandardError "$script:Case/first.err"
            try {
                $deadline = (Get-Date).AddSeconds(60)
                while (-not (Test-Path -LiteralPath $env:STUB_ENTERED) -and (Get-Date) -lt $deadline) { Start-Sleep -Milliseconds 100 }
                $env:STUB_ENTERED = $null
                $second = Invoke-Wrapper
            } finally {
                Set-Content -LiteralPath $env:STUB_RELEASE -Value 'release'
            }
            $second.Exit | Should -Be 0
            $first.WaitForExit(120000) | Should -BeTrue
            Get-StubCalls | Should -Be 2
        }
    }
}
