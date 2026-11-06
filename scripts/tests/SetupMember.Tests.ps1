# AC-2 to AC-4 of the fleet agents plan: what setup-member.ps1 publishes, that it is idempotent, and that
# a real write chooses the Codex sandbox.
BeforeAll {
    $script:SetupPath = Join-Path $PSScriptRoot '../../.agent/fleet/setup-member.ps1'
    . $script:SetupPath -LibraryOnly

    function script:Get-SetupProblems {
        param([string]$Text)
        $rules = [ordered]@{
            'ipv4 literal' = '(?<![\d.])\d{1,3}(\.\d{1,3}){3}(?![\d.])'
            'host name' = '(?-i)\b(DUPER|SUPER)\b'
            'drive path' = '(?<![A-Za-z0-9_])[A-Za-z]:[\\/]'
            'token command' = 'setup-token'
            'login file' = 'auth\.json|\.credentials\.json'
        }
        foreach ($name in $rules.Keys) {
            if ($Text -match $rules[$name]) { $name }
        }
    }

}

Describe 'setup-member.ps1 publishes no host or credential' {
    It 'AC-2: the clean file has no problems' {
        @(Get-SetupProblems (Get-Content $script:SetupPath -Raw)) | Should -BeNullOrEmpty
    }

    It 'AC-2: a copy with <label> fails' -ForEach @(
        @{ label = 'an IPv4 literal'; line = '$h = "10.1.2.3"'; rule = 'ipv4 literal' }
        @{ label = 'one member''s name'; line = '$h = "DUPER"'; rule = 'host name' }
        @{ label = 'the hub machine''s name'; line = '$h = "SUPER"'; rule = 'host name' }
        @{ label = 'a drive-letter path'; line = '$h = "P:\x"'; rule = 'drive path' }
        @{ label = 'the token command'; line = 'claude setup-token'; rule = 'token command' }
        @{ label = 'a read of the Codex login'; line = 'Get-Content "$HOME\.codex\auth.json"'; rule = 'login file' }
        @{ label = 'a read of the Claude login'; line = 'Get-Content "$HOME\.claude\.credentials.json"'; rule = 'login file' }
    ) {
        $text = (Get-Content $script:SetupPath -Raw) + "`n" + $line + "`n"
        @(Get-SetupProblems $text) | Should -Contain $rule
    }
}

Describe 'setup is idempotent' {
    BeforeEach {
        $script:fleetHome = Join-Path $TestDrive ([guid]::NewGuid().ToString('N'))
        $script:config = Join-Path $script:fleetHome 'codex\config.toml'
        $script:present = @('claude', 'codex', 'pwsh', 'uv')
        Mock Test-MemberTool { $script:present -contains $Name }
        Mock Invoke-Installer { $script:present += $Name }
        Mock Get-ToolVersion { "$Name 1.0" }
        Mock Update-SessionPath {}
        Mock Invoke-AdminCodexExec {}
        Mock Invoke-CodexSandboxUninstall {}
        Mock Test-CodexWrite { $true }
        Mock Test-ClaudeWrite { $true }
    }

    It 'AC-3: a second run with every tool present installs nothing and changes no byte' {
        Invoke-MemberSetup -FleetHome $script:fleetHome -CodexConfig $script:config | Out-Null
        $before = [IO.File]::ReadAllBytes($script:config)
        $second = Invoke-MemberSetup -FleetHome $script:fleetHome -CodexConfig $script:config

        Should -Invoke Invoke-Installer -Times 0 -Exactly
        @($second.changed) | Should -BeNullOrEmpty
        [IO.File]::ReadAllBytes($script:config) | Should -Be $before
    }

    It 'AC-3: with codex absent the installer runs exactly once, for codex' {
        $script:present = @('claude', 'pwsh', 'uv')
        $report = Invoke-MemberSetup -FleetHome $script:fleetHome -CodexConfig $script:config

        Should -Invoke Invoke-Installer -Times 1 -Exactly
        Should -Invoke Invoke-Installer -Times 1 -Exactly -ParameterFilter { $Name -eq 'codex' }
        @($report.changed) | Should -Contain 'codex'
    }

    It 'AC-3: a tool still missing after its installer stops the run' {
        $script:present = @('claude', 'pwsh', 'uv')
        Mock Invoke-Installer {}
        { Invoke-MemberSetup -FleetHome $script:fleetHome -CodexConfig $script:config } |
            Should -Throw '*tool_install_failed:codex*'
    }

    It 'AC-3: a config.toml with other lines keeps them byte-identical' {
        New-Item -ItemType Directory -Force (Split-Path $script:config) | Out-Null
        $others = [Text.Encoding]::GetEncoding(28591).GetBytes("# caf$([char]0xE9)`r`nmodel = `"x`"`n`n[projects.'a']`r`ntrust_level = `"trusted`"`n")
        [IO.File]::WriteAllBytes($script:config, $others)
        Invoke-MemberSetup -FleetHome $script:fleetHome -CodexConfig $script:config | Out-Null

        $after = [IO.File]::ReadAllBytes($script:config)
        $text = [Text.Encoding]::GetEncoding(28591).GetString($after)
        $kept = [Text.Encoding]::GetEncoding(28591).GetString($others)
        $text.EndsWith($kept) | Should -BeTrue
        $text.Substring(0, $text.Length - $kept.Length) |
            Should -Be "windows.sandbox = `"elevated`"`ncli_auth_credentials_store = `"file`"`n"
    }

    It 'AC-3: an existing key is replaced in place and its line ending stays' {
        New-Item -ItemType Directory -Force (Split-Path $script:config) | Out-Null
        [IO.File]::WriteAllText($script:config, "a = 1`r`nwindows.sandbox = `"old`"`r`nb = 2`r`n")
        Set-CodexConfigLine -Path $script:config -Key 'windows.sandbox' -Value '"unelevated"' | Should -BeTrue
        [IO.File]::ReadAllText($script:config) | Should -BeExactly "a = 1`r`nwindows.sandbox = `"unelevated`"`r`nb = 2`r`n"
    }

    It 'AC-3: a [windows] table has its sandbox key replaced inside it, the file still parses and a second run changes nothing' {
        New-Item -ItemType Directory -Force (Split-Path $script:config) | Out-Null
        [IO.File]::WriteAllText($script:config, "model = `"x`"`r`n[windows]`r`nsandbox = `"unelevated`"`r`n[projects.'a']`r`nsandbox = `"keep`"`r`n")
        Set-CodexConfigLine -Path $script:config -Key 'windows.sandbox' -Value '"elevated"' | Should -BeTrue
        $after = "model = `"x`"`r`n[windows]`r`nsandbox = `"elevated`"`r`n[projects.'a']`r`nsandbox = `"keep`"`r`n"
        [IO.File]::ReadAllText($script:config) | Should -BeExactly $after
        Set-CodexConfigLine -Path $script:config -Key 'windows.sandbox' -Value '"elevated"' | Should -BeFalse
        [IO.File]::ReadAllText($script:config) | Should -BeExactly $after
        python -c "import sys, tomllib; print(tomllib.load(open(sys.argv[1], 'rb'))['windows']['sandbox'])" $script:config |
            Should -Be 'elevated'
    }

    It 'AC-3: a [windows] table without the key gets it under its header' {
        New-Item -ItemType Directory -Force (Split-Path $script:config) | Out-Null
        [IO.File]::WriteAllText($script:config, "[windows] # mine`nother = 1`n")
        Set-CodexConfigLine -Path $script:config -Key 'windows.sandbox' -Value '"unelevated"' | Should -BeTrue
        [IO.File]::ReadAllText($script:config) | Should -BeExactly "[windows] # mine`nsandbox = `"unelevated`"`nother = 1`n"
    }

    It 'AC-3: a [windows] header on the last line with no line end still parses' {
        New-Item -ItemType Directory -Force (Split-Path $script:config) | Out-Null
        [IO.File]::WriteAllText($script:config, "a = 1`n[windows]")
        Set-CodexConfigLine -Path $script:config -Key 'windows.sandbox' -Value '"elevated"' | Should -BeTrue
        [IO.File]::ReadAllText($script:config) | Should -BeExactly "a = 1`n[windows]`nsandbox = `"elevated`"`n"
    }

    It 'AC-3: setup run twice on a [windows] table config leaves one valid table' {
        New-Item -ItemType Directory -Force (Split-Path $script:config) | Out-Null
        [IO.File]::WriteAllText($script:config, "[windows]`nsandbox = `"unelevated`"`n")
        Invoke-MemberSetup -FleetHome $script:fleetHome -CodexConfig $script:config | Out-Null
        $before = [IO.File]::ReadAllBytes($script:config)
        $second = Invoke-MemberSetup -FleetHome $script:fleetHome -CodexConfig $script:config

        @($second.changed) | Should -BeNullOrEmpty
        [IO.File]::ReadAllBytes($script:config) | Should -Be $before
        python -c "import sys, tomllib; c = tomllib.load(open(sys.argv[1], 'rb')); print(c['windows']['sandbox'], c['cli_auth_credentials_store'])" $script:config |
            Should -Be 'elevated file'
    }

    It 'AC-3: the report carries the fields the live check reads' {
        $registry = Join-Path $script:fleetHome 'registry.json'
        New-Item -ItemType Directory -Force $script:fleetHome | Out-Null
        Set-Content $registry '{"classes":{"isolated_worker":{"bindings":{"codex-cli":{"slug":"m-1"}}}}}'
        Invoke-MemberSetup -FleetHome $script:fleetHome -CodexConfig $script:config -Registry $registry | Out-Null

        $report = Get-Content (Join-Path $script:fleetHome 'setup-report.json') -Raw | ConvertFrom-Json
        $report.isolated_worker_slug | Should -Be 'm-1'
        $report.versions.pwsh | Should -Be 'pwsh 1.0'
        $report.write_tests.claude | Should -Be 'pass'
        $report.write_tests.codex | Should -Be 'pass'
        $report.write_tests.codex_sandbox | Should -Be 'pass'
        $report.elevated_tried | Should -BeTrue
        $report.sandbox | Should -Be 'elevated'
    }
}

Describe 'a real write chooses the sandbox' {
    BeforeEach {
        $script:root = Join-Path $TestDrive ([guid]::NewGuid().ToString('N'))
        New-Item -ItemType Directory -Force $script:root | Out-Null
        $script:config = Join-Path $script:root 'config.toml'
        $script:writes = @{ elevated = $false; unelevated = $true; full = $true }
        Mock Invoke-AdminCodexExec {}
        Mock Invoke-CodexSandboxUninstall {}
        # Stands in for the S4U run, and always reports success: only the file can tell. A full-access run
        # ignores the sandbox setting, as Codex does.
        Mock Invoke-S4uWrite {
            $sandbox = if ($Sandbox -eq 'danger-full-access') { 'full' } else {
                [regex]::Match([IO.File]::ReadAllText($script:config), 'windows\.sandbox = "(\w+)"').Groups[1].Value
            }
            if ($script:writes[$sandbox]) { Set-Content (Join-Path $Dir $FileName) $Contents -NoNewline }
            0
        }
    }

    It 'P-4: the full-access test runs the probe with danger-full-access, and the sandbox test with workspace-write' {
        Test-CodexWrite -ProbeRoot $script:root -FullAccess | Out-Null
        Should -Invoke Invoke-S4uWrite -Times 1 -Exactly -ParameterFilter { $Cli -eq 'codex' -and $Sandbox -eq 'danger-full-access' }
        Set-CodexConfigLine -Path $script:config -Key 'windows.sandbox' -Value '"unelevated"' | Out-Null
        Test-CodexWrite -ProbeRoot $script:root | Out-Null
        Should -Invoke Invoke-S4uWrite -Times 1 -Exactly -ParameterFilter { $Cli -eq 'codex' -and $Sandbox -eq 'workspace-write' }
    }

    It 'P-4: the probe script names the sandbox it was given' {
        $dir = New-ProbeDir -ProbeRoot $script:root -Cli 'codex'
        $probe = New-ProbeScript -Cli codex -Dir $dir -FileName 'probe.txt' -Contents 'x' -TokenPath '' -Sandbox 'danger-full-access'
        Get-Content $probe -Raw | Should -Match "codex exec --skip-git-repo-check --sandbox danger-full-access '"
        $probe = New-ProbeScript -Cli codex -Dir $dir -FileName 'probe.txt' -Contents 'x' -TokenPath ''
        Get-Content $probe -Raw | Should -Match "codex exec --skip-git-repo-check --sandbox workspace-write '"
    }

    It 'AC-4: exit 0 with no file is a fail' {
        Mock Invoke-S4uWrite { 0 }
        Test-CodexWrite -ProbeRoot $script:root | Should -BeFalse
    }

    It 'AC-4: the wrong contents are a fail' {
        Mock Invoke-S4uWrite { Set-Content (Join-Path $Dir $FileName) 'something else'; 0 }
        Test-CodexWrite -ProbeRoot $script:root | Should -BeFalse
    }

    It 'AC-4: the expected file passes' {
        Mock Invoke-S4uWrite { Set-Content (Join-Path $Dir $FileName) $Contents; 0 }
        Test-CodexWrite -ProbeRoot $script:root | Should -BeTrue
    }

    It 'AC-4: elevated that writes is kept, with no uninstall' {
        $script:writes.elevated = $true
        $out = Select-CodexSandbox -ConfigPath $script:config -ProbeRoot $script:root -ElevatedTried $false -Current ''

        $out.sandbox | Should -Be 'elevated'
        $out.elevated_tried | Should -BeTrue
        Should -Invoke Invoke-AdminCodexExec -Times 1 -Exactly
        Should -Invoke Invoke-CodexSandboxUninstall -Times 0 -Exactly
    }

    It 'AC-4: elevated failing then unelevated passing chooses unelevated and uninstalls once' {
        $out = Select-CodexSandbox -ConfigPath $script:config -ProbeRoot $script:root -ElevatedTried $false -Current ''

        $out.sandbox | Should -Be 'unelevated'
        $out.write_test | Should -Be 'pass'
        $out.elevated_tried | Should -BeTrue
        Should -Invoke Invoke-CodexSandboxUninstall -Times 1 -Exactly
        [IO.File]::ReadAllText($script:config) | Should -Match 'windows\.sandbox = "unelevated"'
    }

    It 'P-4: both sandboxes failing is recorded, and a full-access write that passes exits 0' {
        $script:writes.unelevated = $false
        Mock Test-MemberTool { $true }
        Mock Get-ToolVersion { '1.0' }
        Mock Update-SessionPath {}
        Mock Test-ClaudeWrite { $true }
        $home2 = Join-Path $script:root 'home'
        $report = Invoke-MemberSetup -FleetHome $home2 -CodexConfig $script:config

        $report.reason | Should -BeNullOrEmpty
        $report.write_tests.codex | Should -Be 'pass'
        $report.write_tests.codex_sandbox | Should -Be 'fail'
        Get-SetupExitCode -Report $report | Should -Be 0
        (Get-Content (Join-Path $home2 'setup-report.json') -Raw | ConvertFrom-Json).elevated_tried | Should -BeTrue
    }

    It 'P-4: a full-access write that fails reports codex_no_write, and the run exits 1' {
        $script:writes.full = $false
        Mock Test-MemberTool { $true }
        Mock Get-ToolVersion { '1.0' }
        Mock Update-SessionPath {}
        Mock Test-ClaudeWrite { $true }
        $report = Invoke-MemberSetup -FleetHome (Join-Path $script:root 'home') -CodexConfig $script:config

        $report.reason | Should -Be 'codex_no_write'
        $report.write_tests.codex | Should -Be 'fail'
        $report.write_tests.codex_sandbox | Should -Be 'pass'
        Get-SetupExitCode -Report $report | Should -Be 1
    }

    It 'AC-4: a clean run exits 0' {
        Get-SetupExitCode -Report @{ reason = $null } | Should -Be 0
    }

    It 'AC-4: elevated_tried true makes no elevated attempt' {
        $out = Select-CodexSandbox -ConfigPath $script:config -ProbeRoot $script:root -ElevatedTried $true -Current 'unelevated'

        $out.sandbox | Should -Be 'unelevated'
        Should -Invoke Invoke-AdminCodexExec -Times 0 -Exactly
        Should -Invoke Invoke-CodexSandboxUninstall -Times 0 -Exactly
    }

    It 'AC-4: a kept elevated that stops writing falls back once, with no second admin run' {
        Set-CodexConfigLine -Path $script:config -Key 'windows.sandbox' -Value '"elevated"' | Out-Null
        $out = Select-CodexSandbox -ConfigPath $script:config -ProbeRoot $script:root -ElevatedTried $true -Current 'elevated'

        $out.sandbox | Should -Be 'unelevated'
        Should -Invoke Invoke-AdminCodexExec -Times 0 -Exactly
        Should -Invoke Invoke-CodexSandboxUninstall -Times 1 -Exactly
    }
}

Describe 'fleet-tasks.ps1 holds the Codex job tasks' {
    BeforeAll {
        $script:TasksPath = Join-Path $PSScriptRoot '../../.agent/fleet/fleet-tasks.ps1'
        . $script:TasksPath -LibraryOnly
        $script:Named = @{
            Run = 'run-1'; Brief = 'C:/home/receipts/fleet-briefs/run-1/brief-1.md'; Slot = 'C:/home/agent/run-1/slot'; DispatchId = 'run-1-1'
        }
    }

    Context 'the file on disk' {
        It 'AC-29: it publishes no host or credential' {
            @(Get-SetupProblems (Get-Content $script:TasksPath -Raw)) | Should -BeNullOrEmpty
        }


        It 'AC-29: <label> is a binding error' -ForEach @(
            @{ label = 'an unknown action'; extra = @('-Action', 'Nope', '-Run', 'run-1') }
            @{ label = 'a run name with an underscore'; extra = @('-Action', 'CodexState', '-Run', 'bad_name', '-DispatchId', 'd') }
            @{ label = 'a run name in upper case'; extra = @('-Action', 'CodexState', '-Run', 'BAD', '-DispatchId', 'd') }
            @{ label = 'a parameter it does not have'; extra = @('-Action', 'CodexState', '-Run', 'run-1', '-Other', 'x') }
        ) {
            & pwsh -NoProfile -NonInteractive -File $script:TasksPath @extra *> $null
            $LASTEXITCODE | Should -Not -Be 0
        }
    }

    Context 'CodexStart' {
        BeforeEach {
            Mock Register-ScheduledTask {}
            Mock Start-ScheduledTask {}
        }

        It 'AC-29: registers the one-shot S4U task under the run''s path and starts it' {
            Start-CodexTask @script:Named
            Should -Invoke Register-ScheduledTask -Times 1 -Exactly -ParameterFilter {
                $TaskPath -eq '\Fleet\Codex\' -and $TaskName -eq 'run-1' -and $Force -and $Principal.LogonType -eq 'S4U'
            }
            Should -Invoke Start-ScheduledTask -Times 1 -Exactly -ParameterFilter { $TaskPath -eq '\Fleet\Codex\' -and $TaskName -eq 'run-1' }
        }

        It 'AC-29: the task''s action is this script with CodexRun' {
            Start-CodexTask @script:Named
            Should -Invoke Register-ScheduledTask -Times 1 -Exactly -ParameterFilter {
                $Action.Execute -eq 'pwsh' -and
                $Action.Arguments -match '-File "[^"]*fleet-tasks\.ps1"' -and
                $Action.Arguments -match '-Action CodexRun -Run run-1 ' -and
                $Action.Arguments -match '-Brief "C:/home/receipts/fleet-briefs/run-1/brief-1\.md"' -and
                $Action.Arguments -match '-Slot "C:/home/agent/run-1/slot"' -and
                $Action.Arguments -match '-DispatchId run-1-1' -and
                $Action.Arguments -notmatch 'ResumeDispatchId'
            }
        }

        It 'AC-29: a resume adds the prior dispatch to the task''s action' {
            Start-CodexTask @script:Named -ResumeDispatchId 'run-1-0'
            Should -Invoke Register-ScheduledTask -Times 1 -Exactly -ParameterFilter { $Action.Arguments -match '-ResumeDispatchId run-1-0' }
        }

        # Read from the command, because a real call without one would wait at a prompt.
        It 'AC-29: <name> is required' -ForEach @(@{ name = 'Brief' }, @{ name = 'Slot' }, @{ name = 'DispatchId' }) {
            (Get-Command Start-CodexTask).Parameters[$name].Attributes.Mandatory | Should -Contain $true
        }
    }

    Context 'CodexRun' {
        It 'AC-29: the wrapper gets the fleet class, the full-access mode and the non-review switch' {
            $wrapper = Get-CodexWrapperArguments -Kit 'C:/home/kit' -Brief 'b.md' -Slot 'C:/home/agent/run-1/slot' -DispatchId 'run-1-1'
            $wrapper[0..3] | Should -Be @('-NoProfile', '-NonInteractive', '-File', 'C:/home/kit/tools/Invoke-CodexDispatch.ps1')
            $wrapper | Should -Contain '-NonReviewDispatch'
            $wrapper[$wrapper.IndexOf('-ModelClass') + 1] | Should -Be 'isolated_worker'
            $wrapper[$wrapper.IndexOf('-Mode') + 1] | Should -Be 'FullAccess'
            $wrapper[$wrapper.IndexOf('-PromptFile') + 1] | Should -Be 'b.md'
            $wrapper[$wrapper.IndexOf('-DispatchId') + 1] | Should -Be 'run-1-1'
            $wrapper[$wrapper.IndexOf('-WorkingDirectory') + 1] | Should -Be 'C:/home/agent/run-1/slot'
            $wrapper | Should -Not -Contain '-ResumeDispatchId'
        }

        It 'P-4: full access carries a justification the wrapper accepts' {
            $wrapper = Get-CodexWrapperArguments -Kit 'k' -Brief 'b.md' -Slot 's' -DispatchId 'd'
            $why = $wrapper[$wrapper.IndexOf('-FullAccessJustification') + 1]
            ($why -replace '\s', '').Length | Should -BeGreaterOrEqual 20
            $why | Should -Match 'P-4'
        }

        It 'AC-29: a resume passes the prior id with the same class' {
            $wrapper = Get-CodexWrapperArguments -Kit 'k' -Brief 'b.md' -Slot 's' -DispatchId 'run-1-2' -ResumeDispatchId 'run-1-1'
            $wrapper[$wrapper.IndexOf('-ResumeDispatchId') + 1] | Should -Be 'run-1-1'
            $wrapper[$wrapper.IndexOf('-ModelClass') + 1] | Should -Be 'isolated_worker'
        }

        It 'AC-29: the manifest''s options reach the wrapper' {
            $options = [pscustomobject]@{ model = 'gpt-test'; effort = 'xhigh'; timeout_sec = 600 }
            $wrapper = Get-CodexWrapperArguments -Kit 'k' -Brief 'b.md' -Slot 's' -DispatchId 'd' -Options $options
            $wrapper[$wrapper.IndexOf('-Model') + 1] | Should -Be 'gpt-test'
            $wrapper[$wrapper.IndexOf('-ReasoningEffort') + 1] | Should -Be 'xhigh'
            $wrapper[$wrapper.IndexOf('-TimeoutSec') + 1] | Should -Be '600'
        }

        It 'AC-29: with no options the wrapper keeps its own defaults' {
            $wrapper = Get-CodexWrapperArguments -Kit 'k' -Brief 'b.md' -Slot 's' -DispatchId 'd' -Options ([pscustomobject]@{ cli = 'codex' })
            foreach ($name in '-Model', '-ReasoningEffort', '-TimeoutSec') { $wrapper | Should -Not -Contain $name }
        }
    }

    Context 'CodexState' {
        BeforeEach {
            $script:StateHome = Join-Path $TestDrive ([guid]::NewGuid().ToString('N'))
            $script:Dispatch = Join-Path $script:StateHome 'receipts/dispatch/run-1-1'
            New-Item -ItemType Directory -Path $script:Dispatch -Force | Out-Null
            Mock Get-ScheduledTask { [pscustomobject]@{ State = 'Ready' } }
            Mock Get-ScheduledTaskInfo { [pscustomobject]@{ LastTaskResult = 0 } }
        }

        It 'AC-29: it prints one JSON line' {
            $out = @(Get-CodexState -FleetHome $script:StateHome -Run 'run-1' -DispatchId 'run-1-1')
            $out.Count | Should -Be 1
            ($out[0] | ConvertFrom-Json).running | Should -BeFalse
        }

        It 'AC-29: a task in state <state> is running: <running>' -ForEach @(
            @{ state = 'Running'; running = $true }
            @{ state = 'Queued'; running = $true }
            @{ state = 'Ready'; running = $false }
            @{ state = 'Disabled'; running = $false }
        ) {
            Mock Get-ScheduledTask { [pscustomobject]@{ State = $state } }
            (Get-CodexState -FleetHome $script:StateHome -Run 'run-1' -DispatchId 'run-1-1' | ConvertFrom-Json).running | Should -Be $running
        }

        It 'AC-29: no task is not running' {
            Mock Get-ScheduledTask {}
            $state = Get-CodexState -FleetHome $script:StateHome -Run 'run-1' -DispatchId 'run-1-1' | ConvertFrom-Json
            $state.running | Should -BeFalse
            $state.task_result | Should -BeNullOrEmpty
        }

        It 'AC-29: the task result is reported for the busy check' {
            Mock Get-ScheduledTaskInfo { [pscustomobject]@{ LastTaskResult = 11 } }
            (Get-CodexState -FleetHome $script:StateHome -Run 'run-1' -DispatchId 'run-1-1' | ConvertFrom-Json).task_result | Should -Be 11
        }

        It 'AC-29: <label> gives <expected>' -ForEach @(
            @{ label = 'the last of two lines'; text = "Status: STOPPED:decision`nmore`nStatus: DONE`n"; expected = 'DONE' }
            @{ label = 'CRLF endings'; text = "text`r`nStatus: STOPPED:decision`r`n"; expected = 'STOPPED:decision' }
            @{ label = 'the wrong case kept as written'; text = "Status: done`n"; expected = 'done' }
        ) {
            [IO.File]::WriteAllText((Join-Path $script:Dispatch 'final.md'), $text)
            (Get-CodexState -FleetHome $script:StateHome -Run 'run-1' -DispatchId 'run-1-1' | ConvertFrom-Json).status_line | Should -BeExactly $expected
        }

        It 'AC-29: <label> has no status line' -ForEach @(
            @{ label = 'text with none'; text = "All good.`n" }
            @{ label = 'a lower-case key'; text = "status: DONE`n" }
            @{ label = 'an indented line'; text = "  Status: DONE`n" }
            @{ label = 'no space after the colon'; text = "Status:DONE`n" }
            @{ label = 'a line that only starts alike'; text = "Status report: DONE`n" }
        ) {
            [IO.File]::WriteAllText((Join-Path $script:Dispatch 'final.md'), $text)
            (Get-CodexState -FleetHome $script:StateHome -Run 'run-1' -DispatchId 'run-1-1' | ConvertFrom-Json).status_line | Should -BeNullOrEmpty
        }

        It 'AC-29: no final.md has no status line' {
            (Get-CodexState -FleetHome $script:StateHome -Run 'run-1' -DispatchId 'run-1-1' | ConvertFrom-Json).status_line | Should -BeNullOrEmpty
        }
    }

    Context 'CodexStop and Remove' {
        BeforeEach {
            Mock Stop-ScheduledTask {}
            Mock Unregister-ScheduledTask {}
        }

        It 'AC-29: CodexStop stops this run''s task' {
            Mock Get-ScheduledTask { [pscustomobject]@{ State = 'Running' } }
            Stop-CodexTask -Run 'run-1'
            Should -Invoke Stop-ScheduledTask -Times 1 -Exactly -ParameterFilter { $TaskPath -eq '\Fleet\Codex\' -and $TaskName -eq 'run-1' }
        }

        It 'AC-29: Remove unregisters this run''s Codex and credits tasks' {
            Mock Get-ScheduledTask { [pscustomobject]@{ State = 'Ready' } }
            Remove-RunTasks -Run 'run-1'
            Should -Invoke Unregister-ScheduledTask -Times 1 -Exactly -ParameterFilter { $TaskPath -eq '\Fleet\Codex\' -and $TaskName -eq 'run-1' -and -not $Confirm }
            Should -Invoke Unregister-ScheduledTask -Times 1 -Exactly -ParameterFilter { $TaskPath -eq '\Fleet\Credits\' -and $TaskName -eq 'run-1' -and -not $Confirm }
        }

        It 'AC-29: Remove with no tasks is fine' {
            Mock Get-ScheduledTask {}
            Remove-RunTasks -Run 'run-1'
            Should -Invoke Unregister-ScheduledTask -Times 0 -Exactly
        }
    }
}
