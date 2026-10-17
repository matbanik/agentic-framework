# The start policy of the framework template (AC-J.5 of
# docs/execution/plans/2026-10-15-scheduled-credits-runs in the source project).
# credits_start_policy in .agent/credits/config.json says who may start a scheduled run:
# human-only (the default the template ships) refuses an agent-on-user-chat start before the
# script reads the scheduler or the store; agent-on-user-chat lets it through.
# The policy check runs first, so every case here stops before a task or a store call: the
# injected scheduler records its calls and the store path is never created.

BeforeAll {
    $script:Repo = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
    $script:Caller = Join-Path $script:Repo '.agent/skills/claude-credits/Start-CreditsRunTask.ps1'
    $script:Root = "{{RECEIPTS_DIR}}/credits-startpolicy-tests/$([guid]::NewGuid().ToString('N'))"
    New-Item -ItemType Directory -Force -Path $script:Root | Out-Null
    $script:Db = "$script:Root/state.db"
    $script:SavedConfig = $env:CREDITS_CONFIG

    function New-Config([string]$Policy) {
        $path = "$script:Root/config-$([guid]::NewGuid().ToString('N')).json"
        $doc = [ordered]@{ ruling_enabled = $false; gate_wait_max_min = 0; cache_ttl = '5m'; credits_start_policy = $Policy }
        Set-Content -LiteralPath $path -Value ($doc | ConvertTo-Json) -Encoding utf8NoBOM
        $path
    }

    # A scheduler adapter that records each call and has no task, so a call that passes the
    # policy stops at task_missing.
    function New-RecordingScheduler {
        $calls = [System.Collections.Generic.List[string]]::new()
        $adapter = @{
            Calls    = $calls
            Register = { param($Path, $Name) $calls.Add("Register:$Name") }.GetNewClosure()
            Get      = { param($Path, $Name) $calls.Add("Get:$Name"); $null }.GetNewClosure()
            Start    = { param($Path, $Name) $calls.Add("Start:$Name") }.GetNewClosure()
        }
        $adapter
    }

    function Invoke-Start([string]$ConfigPath, [hashtable]$Scheduler, [hashtable]$Extra) {
        $env:CREDITS_CONFIG = $ConfigPath
        $params = @{ RunId = 'policy-run'; StateDb = $script:Db; Scheduler = $Scheduler; AcceptTimeoutMs = 300; PollIntervalMs = 50; OutcomeTimeoutMs = 300 }
        foreach ($k in $Extra.Keys) { $params[$k] = $Extra[$k] }
        $global:LASTEXITCODE = 0
        $lines = @(& $script:Caller @params 2>$null)
        $code = $global:LASTEXITCODE
        $last = @($lines | ForEach-Object { "$_" } | Where-Object { $_.TrimStart().StartsWith('{') }) | Select-Object -Last 1
        [pscustomobject]@{ Code = $code; Payload = $(if ($last) { $last | ConvertFrom-Json } else { $null }) }
    }
}

AfterAll {
    $env:CREDITS_CONFIG = $script:SavedConfig
    if ($script:Root -and (Test-Path -LiteralPath $script:Root)) { Remove-Item -LiteralPath $script:Root -Recurse -Force -ErrorAction SilentlyContinue }
}

Describe 'AC-J.5: the start policy' {
    It 'human-only refuses an agent-on-user-chat start: exit 3, reason start_policy, no scheduler call, no store' {
        $fake = New-RecordingScheduler
        $res = Invoke-Start (New-Config 'human-only') $fake @{ StartedBy = 'agent-on-user-chat'; StartQuote = 'start policy-run' }
        $res.Code | Should -Be 3
        $res.Payload.outcome | Should -Be 'refused'
        $res.Payload.reason | Should -Be 'start_policy'
        $res.Payload.message | Should -Match 'credits_start_policy'
        $fake.Calls.Count | Should -Be 0
        Test-Path -LiteralPath $script:Db | Should -BeFalse
    }

    It 'human-only lets a human-command start through to the task check' {
        $fake = New-RecordingScheduler
        $res = Invoke-Start (New-Config 'human-only') $fake @{ StartedBy = 'human-command' }
        $res.Code | Should -Be 3
        $res.Payload.reason | Should -Be 'task_missing'
        ($fake.Calls -join ',') | Should -Be 'Get:policy-run'
    }

    It 'agent-on-user-chat lets an agent-on-user-chat start through to the task check' {
        $fake = New-RecordingScheduler
        $res = Invoke-Start (New-Config 'agent-on-user-chat') $fake @{ StartedBy = 'agent-on-user-chat'; StartQuote = 'start policy-run' }
        $res.Code | Should -Be 3
        $res.Payload.reason | Should -Be 'task_missing'
        ($fake.Calls -join ',') | Should -Be 'Get:policy-run'
    }

    It 'an unknown policy value is refused as config_invalid before any scheduler call' {
        $fake = New-RecordingScheduler
        $res = Invoke-Start (New-Config 'anyone') $fake @{ StartedBy = 'human-command' }
        $res.Code | Should -Be 3
        $res.Payload.reason | Should -Be 'config_invalid'
        $fake.Calls.Count | Should -Be 0
    }

    It 'a config without credits_start_policy is refused as config_invalid' {
        $path = "$script:Root/three-keys.json"
        Set-Content -LiteralPath $path -Value '{"ruling_enabled": false, "gate_wait_max_min": 0, "cache_ttl": "5m"}' -Encoding utf8NoBOM
        $fake = New-RecordingScheduler
        $res = Invoke-Start $path $fake @{ StartedBy = 'human-command' }
        $res.Code | Should -Be 3
        $res.Payload.reason | Should -Be 'config_invalid'
        $fake.Calls.Count | Should -Be 0
    }
}
