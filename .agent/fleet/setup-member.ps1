# Sets up a fleet member on the member itself: installs what is missing, sets Codex's two config lines,
# chooses the Codex sandbox by a real write under a one-shot S4U task, tests a full-access Codex write the
# way a Codex job runs, and writes setup-report.json.
# It holds no hosts or credentials, and it never reads a Codex login. It runs under Windows PowerShell,
# because pwsh may be one of the tools it installs.
param([switch]$LibraryOnly)

$ErrorActionPreference = 'Stop'

$script:MemberTools = @(
    @{ name = 'claude'; url = 'https://claude.ai/install.ps1'; arguments = @() }
    @{ name = 'codex'; url = 'https://chatgpt.com/codex/install.ps1'; arguments = @() }
    @{ name = 'pwsh'; url = 'https://aka.ms/install-powershell.ps1'; arguments = @('-AddToPath') }
    @{ name = 'uv'; url = 'https://astral.sh/uv/install.ps1'; arguments = @() }
)
$script:ProbeTask = 'Fleet setup probe'
$script:ProbeWaitSeconds = 300
$script:ProbeFile = 'probe.txt'
$script:ClaudeProbeBudgetUsd = '0.25'

function Update-SessionPath {
    $env:Path = [Environment]::GetEnvironmentVariable('Path', 'User') + ';' + [Environment]::GetEnvironmentVariable('Path', 'Machine')
}

function Test-MemberTool {
    param([string]$Name)
    [bool](Get-Command $Name -ErrorAction SilentlyContinue)
}

function Get-ToolVersion {
    param([string]$Name)
    if (-not (Test-MemberTool $Name)) { return $null }
    $ErrorActionPreference = 'Continue'
    "$(& $Name --version 2>&1 | Select-Object -First 1)"
}

function Invoke-Installer {
    param([string]$Name, [string]$Url, [string[]]$Arguments = @())
    $ErrorActionPreference = 'Continue'
    $installer = Join-Path $env:TEMP "$Name-install.ps1"
    curl.exe -sS -L -f -o $installer $Url
    if ($LASTEXITCODE -ne 0) { throw "tool_install_failed:${Name}: curl exit $LASTEXITCODE" }
    powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $installer @Arguments *> "$installer.log"
    $code = $LASTEXITCODE
    Remove-Item $installer -ErrorAction SilentlyContinue
    if ($code -ne 0) { throw "tool_install_failed:${Name}: installer exit $code, see $installer.log" }
}

# Returns $true only when it installed the tool.
function Install-MemberTool {
    param([string]$Name, [string]$Url, [string[]]$Arguments = @())
    if (Test-MemberTool $Name) { return $false }
    Invoke-Installer -Name $Name -Url $Url -Arguments $Arguments
    Update-SessionPath
    if (-not (Test-MemberTool $Name)) { throw "tool_install_failed:${Name}: not on PATH after installing" }
    return $true
}

# Sets one key by its exact line and leaves every other byte alone. Latin-1 round-trips any byte, so
# nothing else in the file is reinterpreted. Returns $true only when the file changed.
function Set-CodexConfigLine {
    param([string]$Path, [string]$Key, [string]$Value)
    $bytes = [Text.Encoding]::GetEncoding(28591)
    $text = if (Test-Path $Path) { $bytes.GetString([IO.File]::ReadAllBytes($Path)) } else { '' }
    # A dotted key such as windows.sandbox goes inside its table when the file has one: TOML refuses a
    # table defined both ways. Otherwise the key belongs to the top level, before the first table.
    $table, $leaf = $Key -split '\.', 2
    $header = if ($leaf) {
        [regex]::Match($text, "(?m)^[ \t]*\[[ \t]*$([regex]::Escape($table))[ \t]*\][ \t]*(#[^\r\n]*)?(\r?\n|$)")
    }
    if ($header -and $header.Success) {
        $start = $header.Index + $header.Length
        $name = $leaf
        if (-not $header.Groups[2].Value) { $text += "`n"; $start++ }
    } else {
        $start = 0
        $name = $Key
    }
    $next = [regex]::Match($text.Substring($start), '(?m)^[ \t]*\[')
    $section = if ($next.Success) { $text.Substring($start, $next.Index) } else { $text.Substring($start) }
    $line = "$name = $Value"
    $found = [regex]::Match($section, "(?m)^[ \t]*$([regex]::Escape($name))[ \t]*=[^\r\n]*")
    if ($found.Success) {
        if ($found.Value -ceq $line) { return $false }
        $text = $text.Remove($start + $found.Index, $found.Length).Insert($start + $found.Index, $line)
    } else {
        # First in its section: TOML would read a key added at the end as part of the next table.
        $text = $text.Insert($start, "$line`n")
    }
    New-Item -ItemType Directory -Force (Split-Path $Path) | Out-Null
    [IO.File]::WriteAllBytes($Path, $bytes.GetBytes($text))
    return $true
}

# The one script a write test runs. The Claude token reaches this process's environment only.
function New-ProbeScript {
    param([string]$Cli, [string]$Dir, [string]$FileName, [string]$Contents, [string]$TokenPath, [string]$Sandbox = 'workspace-write')
    $prompt ="Create a file named $FileName in the current directory containing exactly this text and nothing else: $Contents"
    $lines = @(
        '$ErrorActionPreference = ''Continue'''
        '$env:Path = [Environment]::GetEnvironmentVariable(''Path'', ''User'') + '';'' + [Environment]::GetEnvironmentVariable(''Path'', ''Machine'')'
        'Set-Location $PSScriptRoot'
    )
    if ($Cli -eq 'claude') {
        $lines += @(
            "`$env:CLAUDE_CODE_OAUTH_TOKEN = (Get-Content '$TokenPath' -Raw).Trim()"
            'Remove-Item Env:\ANTHROPIC_API_KEY -ErrorAction SilentlyContinue'
            '$env:CLAUDE_CODE_SUBPROCESS_ENV_SCRUB = ''1'''
            "`$null | & claude -p '$prompt' --max-budget-usd $script:ClaudeProbeBudgetUsd --permission-mode acceptEdits --allowedTools Write --output-format text"
        )
    } else {
        $lines += "`$null | & codex exec --skip-git-repo-check --sandbox $Sandbox '$prompt'"
    }
    $path = Join-Path $Dir 'probe.ps1'
    [IO.File]::WriteAllLines($path, [string[]]$lines, [Text.Encoding]::ASCII)
    return $path
}

# Runs the probe under a one-shot S4U task, the way the member runs a job. What it returns means nothing:
# the file is the only evidence.
function Invoke-S4uWrite {
    param([string]$Cli, [string]$Dir, [string]$FileName, [string]$Contents, [string]$TokenPath, [string]$Sandbox = 'workspace-write')
    $probe = New-ProbeScript -Cli $Cli -Dir $Dir -FileName $FileName -Contents $Contents -TokenPath $TokenPath -Sandbox $Sandbox
    $done = Join-Path $Dir 'probe.done'
    $argument = "/c powershell -NoProfile -NonInteractive -ExecutionPolicy Bypass -File `"$probe`" > `"$Dir\probe-output.txt`" 2>&1 & echo done> `"$done`""
    $action = New-ScheduledTaskAction -Execute 'cmd.exe' -Argument $argument
    $principal = New-ScheduledTaskPrincipal -UserId "$env:COMPUTERNAME\$env:USERNAME" -LogonType S4U
    $settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Seconds $script:ProbeWaitSeconds) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
    Register-ScheduledTask -TaskName $script:ProbeTask -Action $action -Principal $principal -Settings $settings -Force | Out-Null
    try {
        Start-ScheduledTask -TaskName $script:ProbeTask
        $deadline = (Get-Date).AddSeconds($script:ProbeWaitSeconds)
        while (-not (Test-Path $done) -and (Get-Date) -lt $deadline) { Start-Sleep -Seconds 3 }
    } finally {
        Unregister-ScheduledTask -TaskName $script:ProbeTask -Confirm:$false
    }
}

function Test-ProbeFile {
    param([string]$Path, [string]$Expected)
    (Test-Path $Path) -and ((Get-Content $Path -Raw).Trim() -ceq $Expected)
}

function New-ProbeDir {
    param([string]$ProbeRoot, [string]$Cli)
    $dir = Join-Path $ProbeRoot "$Cli-$([guid]::NewGuid().ToString('N').Substring(0, 8))"
    New-Item -ItemType Directory -Force $dir | Out-Null
    return $dir
}

# Passes only if the expected file exists with the expected contents. A failed probe's folder stays,
# for whoever reads why.
function Test-CliWrite {
    param([string]$Cli, [string]$ProbeRoot, [string]$TokenPath = '', [string]$Sandbox = 'workspace-write')
    $dir = New-ProbeDir -ProbeRoot $ProbeRoot -Cli $Cli
    $contents = "fleet-setup-$([guid]::NewGuid().ToString('N'))"
    Invoke-S4uWrite -Cli $Cli -Dir $dir -FileName $script:ProbeFile -Contents $contents -TokenPath $TokenPath -Sandbox $Sandbox | Out-Null
    $passed = Test-ProbeFile -Path (Join-Path $dir $script:ProbeFile) -Expected $contents
    if ($passed) { Remove-Item $dir -Recurse -Force }
    return [bool]$passed
}

# A Codex job runs with full access (P-4), so -FullAccess is the test that decides setup. Without it, the
# test is the sandbox that a Claude job's Codex call still uses.
function Test-CodexWrite {
    param([string]$ProbeRoot, [switch]$FullAccess)
    $sandbox = if ($FullAccess) { 'danger-full-access' } else { 'workspace-write' }
    Test-CliWrite -Cli codex -ProbeRoot $ProbeRoot -Sandbox $sandbox
}

function Test-ClaudeWrite {
    param([string]$ProbeRoot, [string]$TokenPath)
    if (-not (Test-Path $TokenPath)) { return $false }
    Test-CliWrite -Cli claude -ProbeRoot $ProbeRoot -TokenPath $TokenPath
}

# The one codex exec in this elevated session that A-8 needs, since the CLI has no setup command for the
# elevated sandbox. Its outcome is not evidence: only the S4U test that follows decides.
function Invoke-AdminCodexExec {
    param([string]$ProbeRoot)
    $ErrorActionPreference = 'Continue'
    $dir = New-ProbeDir -ProbeRoot $ProbeRoot -Cli 'codex-admin'
    $probe = New-ProbeScript -Cli codex -Dir $dir -FileName $script:ProbeFile -Contents 'fleet-setup-admin' -TokenPath ''
    powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $probe *> "$dir\probe-output.txt"
}

function Invoke-CodexSandboxUninstall {
    $ErrorActionPreference = 'Continue'
    $null | & codex sandbox uninstall *> $null
}

# Elevated gets one try on each member, recorded by elevated_tried. Outcome is decided by a real write.
function Select-CodexSandbox {
    param([string]$ConfigPath, [string]$ProbeRoot, [bool]$ElevatedTried, [string]$Current)
    $changed = $false
    $keep = {
        param([string]$Sandbox)
        @{ sandbox = $Sandbox; elevated_tried = $true; write_test = 'pass'; changed = $changed; reason = $null }
    }
    if (-not $ElevatedTried) {
        $changed = Set-CodexConfigLine -Path $ConfigPath -Key 'windows.sandbox' -Value '"elevated"'
        Invoke-AdminCodexExec -ProbeRoot $ProbeRoot | Out-Null
        if (Test-CodexWrite -ProbeRoot $ProbeRoot) { return & $keep 'elevated' }
        Invoke-CodexSandboxUninstall | Out-Null
    } elseif ($Current -eq 'elevated') {
        if (Test-CodexWrite -ProbeRoot $ProbeRoot) { return & $keep 'elevated' }
        Invoke-CodexSandboxUninstall | Out-Null
    }
    if (Set-CodexConfigLine -Path $ConfigPath -Key 'windows.sandbox' -Value '"unelevated"') { $changed = $true }
    if (Test-CodexWrite -ProbeRoot $ProbeRoot) { return & $keep 'unelevated' }
    @{ sandbox = 'unelevated'; elevated_tried = $true; write_test = 'fail'; changed = $changed; reason = 'sandbox_no_write' }
}

function Get-IsolatedWorkerSlug {
    param([string]$Registry)
    if (-not (Test-Path $Registry)) { return $null }
    (Get-Content $Registry -Raw | ConvertFrom-Json).classes.isolated_worker.bindings.'codex-cli'.slug
}

function Read-SetupReport {
    param([string]$Path)
    if (Test-Path $Path) { Get-Content $Path -Raw | ConvertFrom-Json }
}

function Invoke-MemberSetup {
    param(
        [string]$FleetHome = (Join-Path $HOME '.agent\fleet'),
        [string]$CodexConfig = (Join-Path $HOME '.codex\config.toml'),
        [string]$Registry = (Join-Path $HOME '.agent\model-registry.json')
    )
    New-Item -ItemType Directory -Force $FleetHome | Out-Null
    $reportPath = Join-Path $FleetHome 'setup-report.json'
    $probeRoot = Join-Path $FleetHome 'setup-probe'
    $previous = Read-SetupReport -Path $reportPath
    Update-SessionPath

    $changed = New-Object Collections.ArrayList
    foreach ($tool in $script:MemberTools) {
        if (Install-MemberTool -Name $tool.name -Url $tool.url -Arguments $tool.arguments) { [void]$changed.Add($tool.name) }
    }
    if (Set-CodexConfigLine -Path $CodexConfig -Key 'cli_auth_credentials_store' -Value '"file"') {
        [void]$changed.Add('cli_auth_credentials_store')
    }
    $selected = Select-CodexSandbox -ConfigPath $CodexConfig -ProbeRoot $probeRoot `
        -ElevatedTried ([bool]$previous.elevated_tried) -Current ([string]$previous.sandbox)
    if ($selected.changed) { [void]$changed.Add('windows.sandbox') }
    # A sandbox that can't write is recorded, not a failure: only a Claude job's Codex call uses it.
    $codexWrite = Test-CodexWrite -ProbeRoot $probeRoot -FullAccess
    $claudeWrite = Test-ClaudeWrite -ProbeRoot $probeRoot -TokenPath (Join-Path $FleetHome 'credentials\claude-oauth-token')

    $versions = [ordered]@{}
    foreach ($tool in $script:MemberTools) { $versions[$tool.name] = Get-ToolVersion -Name $tool.name }
    $reason = if (-not $codexWrite) { 'codex_no_write' } elseif (-not $claudeWrite) { 'claude_no_write' } else { $null }
    $report = [ordered]@{
        changed = @($changed)
        versions = $versions
        sandbox = $selected.sandbox
        elevated_tried = $selected.elevated_tried
        write_tests = [ordered]@{
            claude = $(if ($claudeWrite) { 'pass' } else { 'fail' })
            codex = $(if ($codexWrite) { 'pass' } else { 'fail' })
            codex_sandbox = $selected.write_test
        }
        isolated_worker_slug = Get-IsolatedWorkerSlug -Registry $Registry
        reason = $reason
    }
    [IO.File]::WriteAllText($reportPath, ($report | ConvertTo-Json -Depth 4), (New-Object Text.UTF8Encoding($false)))
    return $report
}

function Get-SetupExitCode {
    param($Report)
    if ($Report.reason) { 1 } else { 0 }
}

if ($LibraryOnly) { return }

$finished = Invoke-MemberSetup
$finished | ConvertTo-Json -Depth 4
exit (Get-SetupExitCode -Report $finished)
