# The launcher environment file (framework-template-scope.md, Port plan 5; EA-88): a Task Scheduler
# task starts the launcher with the logon environment, so a session-scoped name such as
# AGENT_MODEL_REGISTRY_HOME (.agent/INSTANTIATE.md section 1) reaches a scheduled run only through
# <store folder>/launcher.env.json, filled at adoption. Read-CreditsLauncherEnv reads that file:
# a missing file adds nothing; a file that is not valid throws launcher_env_invalid, and the
# launcher then ends the segment launch_failed before any CLI call.
# Every file is under TestDrive; no test starts a launcher or changes this process's environment.

BeforeAll {
    $script:Repo = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
    $script:Module = Join-Path $script:Repo '.agent/skills/claude-credits/CreditsRun.psm1'
    Import-Module -Name $script:Module -Force -DisableNameChecking -ErrorAction Stop

    # Write $Text to a new file under TestDrive and return its path.
    function New-EnvFile([string]$Text) {
        $path = Join-Path $TestDrive ("launcher-{0}.env.json" -f [guid]::NewGuid().ToString('N'))
        [System.IO.File]::WriteAllText($path, $Text, [System.Text.UTF8Encoding]::new($false))
        return $path
    }
}

AfterAll {
    Remove-Module -Name CreditsRun -Force -ErrorAction SilentlyContinue
}

Describe 'EA-88: Read-CreditsLauncherEnv reads a valid launcher environment file' {
    It 'EA-88: a missing file gives no names and no PATH folders' {
        $r = Read-CreditsLauncherEnv -Path (Join-Path $TestDrive 'no-such-launcher.env.json')
        @($r.Env.Keys).Count | Should -Be 0
        @($r.PathPrepend).Count | Should -Be 0
    }

    It 'EA-88: env names and path_prepend folders are returned in file order' {
        $path = New-EnvFile '{"env": {"AGENT_MODEL_REGISTRY_HOME": "D:/shared/.agent", "TOOL_HOME": "D:/tools"}, "path_prepend": ["D:/tools/bin", "D:/more/bin"]}'
        $r = Read-CreditsLauncherEnv -Path $path
        @($r.Env.Keys) | Should -Be @('AGENT_MODEL_REGISTRY_HOME', 'TOOL_HOME')
        $r.Env['AGENT_MODEL_REGISTRY_HOME'] | Should -Be 'D:/shared/.agent'
        @($r.PathPrepend) | Should -Be @('D:/tools/bin', 'D:/more/bin')
    }

    It 'EA-88: both top-level keys are optional' {
        $r = Read-CreditsLauncherEnv -Path (New-EnvFile '{}')
        @($r.Env.Keys).Count | Should -Be 0
        @($r.PathPrepend).Count | Should -Be 0
    }
}

Describe 'EA-88 negative: a launcher environment file that is not valid throws launcher_env_invalid' {
    It 'EA-88 negative: <Case>' -ForEach @(
        @{ Case = 'not JSON'; Text = '{"env": ' }
        @{ Case = 'top level is not an object'; Text = '["env"]' }
        @{ Case = 'an unknown top-level key'; Text = '{"env": {}, "extra": 1}' }
        @{ Case = 'env is not an object'; Text = '{"env": ["A"]}' }
        @{ Case = 'a value that is not a string'; Text = '{"env": {"TOOL_HOME": 5}}' }
        @{ Case = 'a name that is not a variable name'; Text = '{"env": {"TOOL-HOME": "x"}}' }
        @{ Case = 'two names that differ only in case'; Text = '{"env": {"TOOL_HOME": "a", "tool_home": "b"}}' }
        @{ Case = 'PATH (use path_prepend)'; Text = '{"env": {"PATH": "D:/x"}}' }
        @{ Case = 'a CREDITS_ name'; Text = '{"env": {"CREDITS_RUN_ID": "x"}}' }
        @{ Case = 'an ANTHROPIC_ name (the key comes only from the key file)'; Text = '{"env": {"ANTHROPIC_API_KEY": "x"}}' }
        @{ Case = 'a CLAUDE_CODE_ name'; Text = '{"env": {"CLAUDE_CODE_ENTRYPOINT": "cli"}}' }
        @{ Case = 'CLAUDECODE'; Text = '{"env": {"CLAUDECODE": "1"}}' }
        @{ Case = 'DISABLE_PROMPT_CACHING'; Text = '{"env": {"DISABLE_PROMPT_CACHING": "1"}}' }
        @{ Case = 'DISABLE_AUTOUPDATER'; Text = '{"env": {"DISABLE_AUTOUPDATER": "0"}}' }
        @{ Case = 'BASH_DEFAULT_TIMEOUT_MS'; Text = '{"env": {"BASH_DEFAULT_TIMEOUT_MS": "5"}}' }
        @{ Case = 'ELECTRON_RUN_AS_NODE'; Text = '{"env": {"ELECTRON_RUN_AS_NODE": "1"}}' }
        @{ Case = 'path_prepend is a string'; Text = '{"path_prepend": "D:/tools/bin"}' }
        @{ Case = 'a relative path_prepend folder'; Text = '{"path_prepend": ["tools/bin"]}' }
        @{ Case = 'a path_prepend folder with a list separator'; Text = '{"path_prepend": ["D:/a;D:/b"]}' }
        @{ Case = 'a path_prepend folder that is not a string'; Text = '{"path_prepend": [7]}' }
    ) {
        $path = New-EnvFile $Text
        { Read-CreditsLauncherEnv -Path $path } | Should -Throw -ExpectedMessage 'launcher_env_invalid:*'
    }
}

Describe 'EA-88: the launcher uses the file of its store folder' {
    It 'EA-88: Start-CreditsRun.ps1 reads launcher.env.json of the store folder and ends a bad file as launch_failed' {
        $launcher = [System.IO.File]::ReadAllText((Join-Path $script:Repo '.agent/skills/claude-credits/Start-CreditsRun.ps1'))
        $launcher | Should -Match ([regex]::Escape("Read-CreditsLauncherEnv -Path (Join-Path (Split-Path -Parent `$StateDb) 'launcher.env.json')"))
        $launcher | Should -Match 'credits_launcher_env_invalid'
    }
}
