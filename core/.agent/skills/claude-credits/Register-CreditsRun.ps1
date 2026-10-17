<#
.SYNOPSIS
    Register one scheduled credits run: check the manifest, import it into the credits store and
    register its on-demand task \{{PROJECT_NAME_TITLE}}\Credits\<run id> (report section 4.2).

.DESCRIPTION
    The steps:
      1. Check the manifest against schemas/credits-run.v1.json and the local-path rule (every
         path is an absolute local path: no UNC path, no relative path, no '..' segment).
         project_root and launch.working_directory must be one directory (project_mismatch).
      2. Check the messaging switches (the manifest and .agent/credits/config.json). A switch on
         (ruling_enabled true or gate_wait_max_min above 0) needs the approved governance text
         of report sections 7.6 and 7.7 in the project tree: each anchor line must be in its
         file under project_root (AC-I.6). Else the run is refused with messaging_locked. Check
         the cache TTL: a TTL other than 5m needs a p7_result entry in the Probe Record.
      3. Check the M-1 receipt: run_gate.py --check-receipt <receipt> --project <project_root>
         --python <launch.python_exe> --claude <launch.claude_exe> must exit 0.
      4. Import the manifest (credits_state.py register): the run is 'registering'.
      5. Register the run task (no trigger) and, when it is missing, the monitor task.
      6. Read the run task back. A match moves the run to 'registered' with the definition hash;
         an error or a mismatch moves it to 'registration_failed' with the reason.

    A second call for the same run repairs it: a run in 'registering' or 'registration_failed'
    runs steps 5 and 6 again; a 'registered' run whose tasks are present and equal to the stored
    hash is no_change. A run in a later state is refused (already_started). The script never
    starts a task. Start a run with Start-CreditsRunTask.ps1.

    The script prints one JSON line and exits:
      0  changed or no_change (the run is registered);
      1  registration_failed (the reason is in the line and in the store);
      3  refused before any store write, or by the store (the reason is in the line);
      9  an unexpected error.

.EXAMPLE
    pwsh -NoProfile -File .agent/skills/claude-credits/Register-CreditsRun.ps1 -Manifest {{RECEIPTS_DIR}}/credits/my-plan-exec.json -Receipt {{RECEIPTS_DIR}}/credits/m1/gate-result.json
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$Manifest,

    # The M-1 receipt that run_gate.py checks. A copy goes next to the store, for the launcher.
    [Parameter(Mandatory = $true)][string]$Receipt,

    [string]$StateDb = '{{RECEIPTS_DIR}}/credits/state.db',

    # Default: $env:CREDITS_CONFIG, else .agent/credits/config.json of this repository.
    [string]$ConfigPath,

    # The file that holds the Probe Record yaml block (the plan's task.md). Read only, and
    # needed, for a cache TTL other than 5m.
    [string]$ProbeRecord,

    # The Task Scheduler adapter: a hashtable of Register, Get and Start script blocks.
    # Default: New-CreditsSchedulerAdapter (the real Task Scheduler).
    [hashtable]$Scheduler,

    # Default: probes/run_gate.py next to this script.
    [string]$RunGate,

    # Default: $env:CLAUDE_CREDITS_KEY_FILE, else ~/.anthropic/claude-credits.key. Checked for
    # presence only; this script never reads it.
    [string]$KeyFile
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '../../..')).Path
Import-Module -Name (Join-Path $PSScriptRoot 'CreditsRun.psm1') -Force -DisableNameChecking -ErrorAction Stop

$script:RunId = $null

function Write-Result([hashtable]$Payload, [int]$Code) {
    Write-Output ($Payload | ConvertTo-Json -Compress -Depth 6)
    $global:LASTEXITCODE = $Code
}

# A refusal carries its reason in Exception.Data, so the outer catch can tell it from an error.
function Stop-Refused([string]$Reason, [string]$Message) {
    $refusal = [System.InvalidOperationException]::new($Message)
    $refusal.Data['credits_refusal'] = $Reason
    throw $refusal
}

# --- step 1: the manifest -------------------------------------------------------------------

function Test-JsonType($Value, [string]$Type) {
    switch ($Type) {
        'object' { return $Value -is [System.Collections.IDictionary] }
        'array' { return ($Value -is [System.Collections.IList]) -and -not ($Value -is [string]) }
        'string' { return $Value -is [string] }
        'boolean' { return $Value -is [bool] }
        'integer' { return ($Value -is [int] -or $Value -is [long]) }
        'number' { return ($Value -is [int] -or $Value -is [long] -or $Value -is [double] -or $Value -is [decimal]) }
        default { throw "the schema uses an unsupported type: $Type" }
    }
}

# Check one value against one schema node. Supports the keywords the credits-run.v1 schema uses;
# any other keyword is an error, so the schema cannot grow a rule that this check skips.
function Test-SchemaNode($Value, [System.Collections.IDictionary]$Node, [string]$Path) {
    $known = @('$schema', '$id', 'title', 'description', 'type', 'const', 'enum', 'pattern', 'minLength',
        'minimum', 'exclusiveMinimum', 'required', 'additionalProperties', 'properties', 'items', 'minItems')
    foreach ($k in $Node.Keys) { if ($k -notin $known) { throw "the schema uses an unsupported keyword at ${Path}: $k" } }
    if ($Node.Contains('const') -and -not ($Value -is [string] -and $Value -ceq $Node['const'])) { Stop-Refused 'manifest_invalid' "$Path must be '$($Node['const'])'" }
    if ($Node.Contains('enum') -and -not ($Value -is [string] -and @($Node['enum']) -ccontains $Value)) { Stop-Refused 'manifest_invalid' "$Path must be one of: $(@($Node['enum']) -join ', ')" }
    if ($Node.Contains('type') -and -not (Test-JsonType $Value $Node['type'])) { Stop-Refused 'manifest_invalid' "$Path must be of type $($Node['type'])" }
    if ($Value -is [string]) {
        if ($Node.Contains('minLength') -and $Value.Length -lt [int]$Node['minLength']) { Stop-Refused 'manifest_invalid' "$Path is too short" }
        if ($Node.Contains('pattern') -and $Value -cnotmatch $Node['pattern']) { Stop-Refused 'manifest_invalid' "$Path does not match $($Node['pattern'])" }
    }
    if ((Test-JsonType $Value 'number') -and -not ($Value -is [bool])) {
        $number = [double]$Value
        if ([double]::IsNaN($number) -or [double]::IsInfinity($number)) { Stop-Refused 'manifest_invalid' "$Path must be a finite number" }
        if ($Node.Contains('minimum') -and $number -lt [double]$Node['minimum']) { Stop-Refused 'manifest_invalid' "$Path must be >= $($Node['minimum'])" }
        if ($Node.Contains('exclusiveMinimum') -and $number -le [double]$Node['exclusiveMinimum']) { Stop-Refused 'manifest_invalid' "$Path must be > $($Node['exclusiveMinimum'])" }
    }
    if ($Value -is [System.Collections.IDictionary]) {
        $props = if ($Node.Contains('properties')) { $Node['properties'] } else { @{} }
        foreach ($req in @($Node['required'] | Where-Object { $_ })) {
            if (-not $Value.Contains($req)) { Stop-Refused 'manifest_invalid' "$Path.$req is required" }
        }
        foreach ($key in @($Value.Keys)) {
            if ($props.Contains($key)) { Test-SchemaNode $Value[$key] $props[$key] "$Path.$key" }
            elseif ($Node.Contains('additionalProperties') -and $Node['additionalProperties'] -eq $false) { Stop-Refused 'manifest_invalid' "$Path has an unknown key: $key" }
        }
    }
    if ((Test-JsonType $Value 'array') -and $Node.Contains('type') -and $Node['type'] -eq 'array') {
        if ($Node.Contains('minItems') -and @($Value).Count -lt [int]$Node['minItems']) { Stop-Refused 'manifest_invalid' "$Path needs at least $($Node['minItems']) items" }
        if ($Node.Contains('items')) {
            $i = 0
            foreach ($item in $Value) { Test-SchemaNode $item $Node['items'] "$Path[$i]"; $i++ }
        }
    }
}

function Read-Manifest([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { Stop-Refused 'manifest_invalid' "the manifest file does not exist: $Path" }
    $bytes = [System.IO.File]::ReadAllBytes($Path)
    try {
        $text = [System.Text.UTF8Encoding]::new($false, $true).GetString($bytes)
        # -DateKind String keeps an ISO time (chain.given_at) as text for the schema check.
        $doc = ConvertFrom-Json -InputObject $text -AsHashtable -Depth 16 -DateKind String -ErrorAction Stop
    } catch {
        Stop-Refused 'manifest_invalid' "the manifest is not UTF-8 JSON: $($_.Exception.Message)"
    }
    $schemaPath = Join-Path $PSScriptRoot 'schemas/credits-run.v1.json'
    $schema = ConvertFrom-Json -InputObject ([System.IO.File]::ReadAllText($schemaPath)) -AsHashtable -Depth 32 -ErrorAction Stop
    Test-SchemaNode $doc $schema '$'
    $sha = [System.Convert]::ToHexString([System.Security.Cryptography.SHA256]::HashData($bytes)).ToLowerInvariant()
    return [pscustomobject]@{ Doc = $doc; Sha256 = $sha }
}

# An absolute local path: a drive letter, no UNC or device prefix, no '.' or '..' segment.
function Assert-LocalPath([string]$Value, [string]$Name) {
    $local = $Value -match '^[A-Za-z]:[\\/]' -and $Value -notmatch '^[\\/]{2}'
    $segments = @($Value -split '[\\/]+' | Where-Object { $_ -in @('.', '..') })
    if (-not $local -or $segments.Count -gt 0) { Stop-Refused 'path_not_local' "$Name must be an absolute local path with no '..': '$Value'" }
}

function Assert-ManifestPaths($Doc) {
    $paths = [ordered]@{
        project_root             = $Doc['project_root']
        brief                    = $Doc['brief']
        'launch.working_directory' = $Doc['launch']['working_directory']
        'launch.claude_exe'      = $Doc['launch']['claude_exe']
        'launch.python_exe'      = $Doc['launch']['python_exe']
    }
    foreach ($name in $paths.Keys) { Assert-LocalPath ([string]$paths[$name]) $name }
    foreach ($name in @('project_root', 'launch.working_directory')) {
        if (-not (Test-Path -LiteralPath $paths[$name] -PathType Container)) { Stop-Refused 'path_missing' "$name does not exist: '$($paths[$name])'" }
    }
    foreach ($name in @('brief', 'launch.claude_exe', 'launch.python_exe')) {
        if (-not (Test-Path -LiteralPath $paths[$name] -PathType Leaf)) { Stop-Refused 'path_missing' "$name does not exist: '$($paths[$name])'" }
    }
    # The session works in the project it is registered for (report section 4.1): both paths
    # are one physical directory, after case, junctions and trailing separators are resolved.
    if (-not (Test-CreditsSameDirectory -Left $paths['project_root'] -Right $paths['launch.working_directory'])) {
        Stop-Refused 'project_mismatch' ("launch.working_directory '$($paths['launch.working_directory'])' is not the project_root " +
            "'$($paths['project_root'])'; both must be the same directory")
    }
}

# --- step 2: messaging and the cache TTL -------------------------------------------------------

function Read-CreditsConfig([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { Stop-Refused 'config_invalid' "the credits config does not exist: $Path" }
    try { $cfg = ConvertFrom-Json -InputObject ([System.IO.File]::ReadAllText($Path)) -AsHashtable -ErrorAction Stop }
    catch { Stop-Refused 'config_invalid' "the credits config is not JSON: $($_.Exception.Message)" }
    $keys = @('cache_ttl', 'credits_start_policy', 'gate_wait_max_min', 'ruling_enabled')
    if (-not ($cfg -is [System.Collections.IDictionary]) -or (@($cfg.Keys | Sort-Object) -join ',') -ne ($keys -join ',')) {
        Stop-Refused 'config_invalid' "the credits config must hold exactly: $($keys -join ', ')"
    }
    if (-not ($cfg['ruling_enabled'] -is [bool])) { Stop-Refused 'config_invalid' 'ruling_enabled must be true or false' }
    if (-not (Test-JsonType $cfg['gate_wait_max_min'] 'integer') -or $cfg['gate_wait_max_min'] -lt 0) { Stop-Refused 'config_invalid' 'gate_wait_max_min must be an integer >= 0' }
    if ($cfg['cache_ttl'] -cnotin @('5m', '1h')) { Stop-Refused 'config_invalid' 'cache_ttl must be 5m or 1h' }
    if ($cfg['credits_start_policy'] -cnotin @('human-only', 'agent-on-user-chat')) { Stop-Refused 'config_invalid' 'credits_start_policy must be human-only or agent-on-user-chat' }
    return $cfg
}

# The added lines of the approved governance texts (report sections 7.6 and 7.7; task row 26).
# Each one must be in its file, as an exact substring (ordinal), before a switch may be on.
$script:GovernanceAnchors = @(
    @{ File = 'GUARDRAILS.md'; Line = 'except the hook frame `ruling (verified: <session>/<uuid>)` that (b) names' }
    @{ File = 'GUARDRAILS.md'; Line = 'a credits-inbox `ruling` that the inbox hook matched to a user-typed entry' }
    @{ File = 'AGENTS.md'; Line = 'Under `end_turn_signal: gate-wait-then-exit`, a human-decision gate first runs that bounded wait' }
    @{ File = '.agent/docs/human-decision-protocol.md'; Line = '(`gate-wait-then-exit` is the one bounded wait, defined in `harness-profiles.md`)' }
)

# The anchors missing from the tree under $ProjectRoot, as '<file>: <line>' strings.
function Get-MissingAnchors([string]$ProjectRoot) {
    $missing = [System.Collections.Generic.List[string]]::new()
    $texts = @{}
    foreach ($anchor in $script:GovernanceAnchors) {
        $file = $anchor.File
        if (-not $texts.ContainsKey($file)) {
            $path = Join-Path $ProjectRoot $file
            $texts[$file] = if (Test-Path -LiteralPath $path -PathType Leaf) {
                [System.IO.File]::ReadAllText($path, [System.Text.Encoding]::UTF8)
            } else { $null }
        }
        $text = $texts[$file]
        if ($null -eq $text -or -not $text.Contains([string]$anchor.Line, [System.StringComparison]::Ordinal)) {
            $missing.Add("${file}: $($anchor.Line)")
        }
    }
    return , $missing
}

# A switch on needs every governance anchor in the project tree (AC-I.6, report section 7.7).
function Assert-MessagingLocked($Doc, $Config) {
    $messaging = $Doc['messaging']
    $sources = @()
    if ($messaging['ruling_enabled'] -or [int]$messaging['gate_wait_max_min'] -gt 0) { $sources += 'the manifest' }
    if ($Config['ruling_enabled'] -or [int]$Config['gate_wait_max_min'] -gt 0) { $sources += 'the credits config' }
    if ($sources.Count -eq 0) { return }
    $missing = Get-MissingAnchors ([string]$Doc['project_root'])
    if ($missing.Count -gt 0) {
        Stop-Refused 'messaging_locked' ("$($sources -join ' and ') turns on ruling_enabled or gate_wait_max_min, but " +
            "$($missing.Count) approved governance line(s) are not in the tree under $($Doc['project_root']): $($missing -join ' | ')")
    }
}

# A TTL other than the 5-minute default needs a p7_result entry in the Probe Record yaml block.
function Assert-CacheTtl($Config, [string]$RecordPath) {
    if ($Config['cache_ttl'] -ceq '5m') { return }
    if (-not $RecordPath -or -not (Test-Path -LiteralPath $RecordPath -PathType Leaf)) {
        Stop-Refused 'cache_ttl_unproven' "cache_ttl $($Config['cache_ttl']) needs a Probe Record with p7_result; none at '$RecordPath'"
    }
    $text = [System.IO.File]::ReadAllText($RecordPath)
    $blocks = [regex]::Matches($text, '(?ms)^```yaml\s*$(.*?)^```')
    foreach ($block in $blocks) {
        $body = $block.Groups[1].Value
        if ($body -match '(?m)^probe_record:\s*$' -and $body -match '(?m)^\s+p7_result:\s*\S') { return }
    }
    Stop-Refused 'cache_ttl_unproven' "cache_ttl $($Config['cache_ttl']) needs a p7_result entry in the Probe Record"
}

# --- step 3: the M-1 receipt ------------------------------------------------------------------

function Assert-Receipt($Doc, [string]$ReceiptPath, [string]$GatePath) {
    if (-not (Test-Path -LiteralPath $ReceiptPath -PathType Leaf)) { Stop-Refused 'receipt_rejected' "no M-1 receipt at '$ReceiptPath'" }
    if (-not (Test-Path -LiteralPath $GatePath -PathType Leaf)) { throw "run_gate.py not found: $GatePath" }
    $psi = [System.Diagnostics.ProcessStartInfo]::new((Get-CreditsPython))
    foreach ($a in @('-X', 'utf8', $GatePath, '--check-receipt', $ReceiptPath, '--project', $Doc['project_root'],
            '--python', $Doc['launch']['python_exe'], '--claude', $Doc['launch']['claude_exe'])) { $psi.ArgumentList.Add([string]$a) }
    $psi.UseShellExecute = $false
    $psi.CreateNoWindow = $true
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true
    $proc = [System.Diagnostics.Process]::Start($psi)
    try {
        $outTask = $proc.StandardOutput.ReadToEndAsync()
        $errTask = $proc.StandardError.ReadToEndAsync()
        if (-not $proc.WaitForExit(300000)) {
            try { $proc.Kill($true) } catch { [Console]::Error.WriteLine("run_gate.py kill failed: $($_.Exception.Message)") }
            Stop-Refused 'receipt_rejected' 'run_gate.py did not end in 300 s'
        }
        $proc.WaitForExit()
        if ($proc.ExitCode -ne 0) {
            $last = @(($outTask.Result + "`n" + $errTask.Result) -split "`r?`n" | Where-Object { $_.Trim() }) | Select-Object -Last 3
            Stop-Refused 'receipt_rejected' "run_gate.py exit $($proc.ExitCode): $($last -join ' | ')"
        }
    } finally {
        $proc.Dispose()
    }
    try { $receiptDoc = ConvertFrom-Json -InputObject ([System.IO.File]::ReadAllText($ReceiptPath)) -AsHashtable -ErrorAction Stop }
    catch { Stop-Refused 'receipt_rejected' "the receipt is not JSON: $($_.Exception.Message)" }
    $cli = $receiptDoc['cli_version']
    $kit = if ($receiptDoc['identity'] -is [System.Collections.IDictionary]) { $receiptDoc['identity']['kit_revision'] } else { $null }
    if (-not ($cli -is [string]) -or -not $cli -or -not ($kit -is [string]) -or -not $kit) {
        Stop-Refused 'receipt_rejected' 'the receipt has no cli_version or identity.kit_revision'
    }
    return [pscustomobject]@{ CliVersion = $cli; KitRevision = $kit }
}

# --- steps 4 to 6: the store and the tasks -----------------------------------------------------

function Invoke-Store([string]$Verb, [string[]]$Arguments) {
    $res = Invoke-CreditsState -StateDb $StateDb -Verb $Verb -Arguments $Arguments
    if ($res.Code -eq 3 -and $null -ne $res.Payload) {
        $reason = [string]$res.Payload.error
        Stop-Refused $reason ([string]$res.Payload.message)
    }
    if ($res.Code -ne 0) { throw "credits_state.py $Verb failed: $(($res.Out + ' ' + $res.Err).Trim())" }
    return $res.Payload
}

function Get-TaskHashOrNull($Definition) {
    if ($null -eq $Definition) { return $null }
    return Get-CreditsTaskDefinitionHash -Definition $Definition
}

try {
    if (-not $ConfigPath) { $ConfigPath = if ($env:CREDITS_CONFIG) { $env:CREDITS_CONFIG } else { Join-Path $repoRoot '.agent/credits/config.json' } }
    if (-not $RunGate) { $RunGate = Join-Path $PSScriptRoot 'probes/run_gate.py' }
    if (-not $KeyFile) { $KeyFile = if ($env:CLAUDE_CREDITS_KEY_FILE) { $env:CLAUDE_CREDITS_KEY_FILE } else { Join-Path $HOME '.anthropic/claude-credits.key' } }

    $manifestInfo = Read-Manifest $Manifest
    $doc = $manifestInfo.Doc
    $script:RunId = [string]$doc['run_id']
    Assert-ManifestPaths $doc
    $config = Read-CreditsConfig $ConfigPath
    Assert-MessagingLocked $doc $config
    Assert-CacheTtl $config $ProbeRecord
    if (-not (Test-Path -LiteralPath $KeyFile -PathType Leaf)) { Stop-Refused 'key_missing' "no credits key file at '$KeyFile'" }
    $receiptInfo = Assert-Receipt $doc $Receipt $RunGate

    if ($null -eq $Scheduler) { $Scheduler = New-CreditsSchedulerAdapter }
    $pwshPath = Join-Path $PSHOME 'pwsh.exe'
    $runDef = New-CreditsTaskDefinition -RunId $script:RunId -ProjectRoot $doc['project_root'] -PwshPath $pwshPath `
        -LauncherPath (Join-Path $PSScriptRoot 'Start-CreditsRun.ps1') -TimeoutSec ([int]$doc['launch']['timeout_sec'])
    $monitorDef = New-CreditsMonitorTaskDefinition -PwshPath $pwshPath -MonitorPath (Join-Path $PSScriptRoot 'Watch-CreditsRuns.ps1') -WorkingDirectory $repoRoot
    $runHash = Get-CreditsTaskDefinitionHash -Definition $runDef

    $status = Invoke-Store 'run_status' @('--run-id', $script:RunId)
    if ($status.exists) {
        $state = [string]$status.state
        if ($state -notin @('registering', 'registration_failed', 'registered')) {
            Stop-Refused 'already_started' "run $($script:RunId) is $state; only a run in registering, registration_failed or registered can be registered again"
        }
        if ($status.manifest_sha256 -ne $manifestInfo.Sha256) {
            Stop-Refused 'manifest_changed' "run $($script:RunId) holds another manifest (sha256 $($status.manifest_sha256))"
        }
        if ($state -eq 'registered') {
            $runBack = & $Scheduler['Get'] '\{{PROJECT_NAME_TITLE}}\Credits\' $script:RunId
            $monBack = & $Scheduler['Get'] '\{{PROJECT_NAME_TITLE}}\Credits\' 'Monitor'
            if ($null -ne $monBack -and (Get-TaskHashOrNull $runBack) -eq $status.task_hash) {
                Write-Result @{ result = 'no_change'; run_id = $script:RunId; state = 'registered' } 0
                exit 0
            }
        }
    }

    # Step 4: import (a repeat with the same manifest is no_change in the store).
    $copyDir = Join-Path (Split-Path -Parent $StateDb) 'receipts'
    $null = Invoke-Store 'register' @('--run-id', $script:RunId, '--manifest', $Manifest,
        '--cli-version', $receiptInfo.CliVersion, '--kit-revision', $receiptInfo.KitRevision)
    New-Item -ItemType Directory -Force -Path $copyDir | Out-Null
    Copy-Item -LiteralPath $Receipt -Destination (Join-Path $copyDir "$($script:RunId).gate-result.json") -Force

    # Steps 5 and 6: the tasks, then the read-back.
    $failure = $null
    try { & $Scheduler['Register'] $runDef | Out-Null }
    catch { $failure = "run_task_register: $($_.Exception.Message)" }
    if (-not $failure) {
        try {
            if ($null -eq (& $Scheduler['Get'] '\{{PROJECT_NAME_TITLE}}\Credits\' 'Monitor')) { & $Scheduler['Register'] $monitorDef | Out-Null }
            if ($null -eq (& $Scheduler['Get'] '\{{PROJECT_NAME_TITLE}}\Credits\' 'Monitor')) { $failure = 'monitor_task_readback_missing' }
        } catch { $failure = "monitor_task_register: $($_.Exception.Message)" }
    }
    if (-not $failure) {
        $runBack = & $Scheduler['Get'] '\{{PROJECT_NAME_TITLE}}\Credits\' $script:RunId
        if ($null -eq $runBack) { $failure = 'run_task_readback_missing' }
        elseif ((Get-TaskHashOrNull $runBack) -ne $runHash) { $failure = 'run_task_readback_mismatch' }
    }

    $current = Invoke-Store 'run_status' @('--run-id', $script:RunId)
    if ($failure) {
        # A registered run stays registered (the store has no way back); the line names its state.
        $failedState = [string]$current.state
        if ($failedState -ne 'registered') {
            $null = Invoke-Store 'registration_failed' @('--run-id', $script:RunId, '--reason', $failure)
            $failedState = 'registration_failed'
        }
        Write-Result @{ result = 'failed'; run_id = $script:RunId; state = $failedState; reason = $failure } 1
        exit 1
    }
    if ($current.state -eq 'registered' -and $current.task_hash -ne $runHash) {
        # The store keeps the first hash of a registered run; a task that now differs is reported.
        Write-Result @{ result = 'failed'; run_id = $script:RunId; state = 'registered'; reason = 'task_hash_changed' } 1
        exit 1
    }
    $null = Invoke-Store 'registered' @('--run-id', $script:RunId, '--task-hash', $runHash)
    Write-Result @{ result = 'changed'; run_id = $script:RunId; state = 'registered' } 0
    exit 0
} catch {
    $ex = $_.Exception
    if ($ex.Data.Contains('credits_refusal')) {
        Write-Result @{ result = 'refused'; run_id = $script:RunId; reason = [string]$ex.Data['credits_refusal']; message = $ex.Message } 3
        exit 3
    }
    Write-Result @{ result = 'error'; run_id = $script:RunId; message = $ex.Message } 9
    exit 9
}
