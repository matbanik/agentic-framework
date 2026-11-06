# Runs a member's Codex job as a one-shot S4U task, so it survives the member's own process and needs no sign-in.
# fleet.py calls one -Action at a time. It holds no hosts or credentials, and the mode is fixed: full access, with
# the justification below (P-4).
[CmdletBinding(DefaultParameterSetName = 'Run')]
param(
    [Parameter(Mandatory, ParameterSetName = 'Run')]
    [ValidateSet('CodexStart', 'CodexRun', 'CodexState', 'CodexStop', 'Remove')]
    [string]$Action,

    [Parameter(Mandatory, ParameterSetName = 'Run')]
    [ValidatePattern('(?-i)^[a-z0-9-]{1,32}\z')]
    [string]$Run,

    [Parameter(ParameterSetName = 'Run')][string]$Brief,
    [Parameter(ParameterSetName = 'Run')][string]$Slot,
    [Parameter(ParameterSetName = 'Run')][string]$DispatchId,
    [Parameter(ParameterSetName = 'Run')][string]$ResumeDispatchId,

    [Parameter(Mandatory, ParameterSetName = 'Library')][switch]$LibraryOnly
)

$ErrorActionPreference = 'Stop'

$script:CodexTaskPath = '\Fleet\Codex\'
$script:CreditsTaskPath = '\Fleet\Credits\'
$script:CodexModelClass = 'isolated_worker'
# P-4: the Windows sandbox can't start pwsh or apply a patch under an S4U task, so a fleet Codex job has full
# access. The brief keeps it to reading and to writing in its slot and temp. A Claude job's Codex call stays sandboxed.
$script:CodexMode = 'FullAccess'
$script:CodexJustification = 'Human ruling P-4, 2026-11-05: the Windows sandbox cannot start pwsh or apply a patch under an S4U task'
$script:TaskLimitHours = 24

function Start-CodexTask {
    param(
        [Parameter(Mandatory)][string]$Run,
        [Parameter(Mandatory)][string]$Brief,
        [Parameter(Mandatory)][string]$Slot,
        [Parameter(Mandatory)][string]$DispatchId,
        [string]$ResumeDispatchId
    )
    $argument = "-NoProfile -NonInteractive -File `"$PSCommandPath`" -Action CodexRun -Run $Run -Brief `"$Brief`" -Slot `"$Slot`" -DispatchId $DispatchId"
    if ($ResumeDispatchId) { $argument += " -ResumeDispatchId $ResumeDispatchId" }
    $action = New-ScheduledTaskAction -Execute 'pwsh' -Argument $argument
    $principal = New-ScheduledTaskPrincipal -UserId "$env:COMPUTERNAME\$env:USERNAME" -LogonType S4U
    $settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Hours $script:TaskLimitHours) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
    Register-ScheduledTask -TaskPath $script:CodexTaskPath -TaskName $Run -Action $action -Principal $principal -Settings $settings -Force | Out-Null
    Start-ScheduledTask -TaskPath $script:CodexTaskPath -TaskName $Run
}

function Get-CodexWrapperArguments {
    param(
        [Parameter(Mandatory)][string]$Kit,
        [Parameter(Mandatory)][string]$Brief,
        [Parameter(Mandatory)][string]$Slot,
        [Parameter(Mandatory)][string]$DispatchId,
        [string]$ResumeDispatchId,
        $Options
    )
    $wrapper = @(
        '-NoProfile', '-NonInteractive', '-File', "$Kit/tools/Invoke-CodexDispatch.ps1", '-NonReviewDispatch',
        '-ModelClass', $script:CodexModelClass, '-Mode', $script:CodexMode, '-FullAccessJustification', $script:CodexJustification,
        '-PromptFile', $Brief, '-DispatchId', $DispatchId, '-WorkingDirectory', $Slot
    )
    if ($ResumeDispatchId) { $wrapper += '-ResumeDispatchId', $ResumeDispatchId }
    if ($Options.model) { $wrapper += '-Model', [string]$Options.model }
    if ($Options.effort) { $wrapper += '-ReasoningEffort', [string]$Options.effort }
    if ($Options.timeout_sec) { $wrapper += '-TimeoutSec', [string]$Options.timeout_sec }
    $wrapper
}

# The job's status is its final message, read by CodexState. This exit code only carries the wrapper's busy refusal.
function Invoke-CodexRun {
    param(
        [Parameter(Mandatory)][string]$FleetHome,
        [Parameter(Mandatory)][string]$Run,
        [Parameter(Mandatory)][string]$Brief,
        [Parameter(Mandatory)][string]$Slot,
        [Parameter(Mandatory)][string]$DispatchId,
        [string]$ResumeDispatchId
    )
    # A task's Path can lack what setup added for this user. Appended, so what is found first now stays first.
    $env:Path = "$env:Path;" + [Environment]::GetEnvironmentVariable('Path', 'User') + ';' + [Environment]::GetEnvironmentVariable('Path', 'Machine')
    # A job inherits this, so a job that calls the wrapper finds the lock held.
    $env:FLEET_CODEX_LOCK = Join-Path $FleetHome 'codex.lock'
    $options = Get-Content (Join-Path $FleetHome "agent/$Run/manifest.json") -Raw | ConvertFrom-Json
    $given = @{ Kit = (Join-Path $FleetHome 'kit'); Brief = $Brief; Slot = $Slot; DispatchId = $DispatchId; ResumeDispatchId = $ResumeDispatchId; Options = $options }
    $wrapper = Get-CodexWrapperArguments @given
    & pwsh @wrapper *> (Join-Path $FleetHome "receipts/fleet-briefs/$Run/$DispatchId.log")
    $LASTEXITCODE
}

function Get-CodexState {
    param(
        [Parameter(Mandatory)][string]$FleetHome,
        [Parameter(Mandatory)][string]$Run,
        [Parameter(Mandatory)][string]$DispatchId
    )
    $task = Get-ScheduledTask -TaskPath $script:CodexTaskPath -TaskName $Run -ErrorAction SilentlyContinue
    $result = $null
    if ($task) { $result = (Get-ScheduledTaskInfo -TaskPath $script:CodexTaskPath -TaskName $Run).LastTaskResult }
    $final = Join-Path $FleetHome "receipts/dispatch/$DispatchId/final.md"
    $line = $null
    if (Test-Path -LiteralPath $final) {
        $found = @(Get-Content -LiteralPath $final | Where-Object { $_ -cmatch '^Status: ' })
        if ($found.Count) { $line = ($found[-1] -creplace '^Status: ', '').TrimEnd() }
    }
    [ordered]@{ running = [bool]($task -and "$($task.State)" -in 'Running', 'Queued'); task_result = $result; status_line = $line } | ConvertTo-Json -Compress
}

function Stop-CodexTask {
    param([Parameter(Mandatory)][string]$Run)
    if (Get-ScheduledTask -TaskPath $script:CodexTaskPath -TaskName $Run -ErrorAction SilentlyContinue) {
        Stop-ScheduledTask -TaskPath $script:CodexTaskPath -TaskName $Run
    }
}

function Remove-RunTasks {
    param([Parameter(Mandatory)][string]$Run)
    foreach ($path in $script:CodexTaskPath, $script:CreditsTaskPath) {
        if (Get-ScheduledTask -TaskPath $path -TaskName $Run -ErrorAction SilentlyContinue) {
            Unregister-ScheduledTask -TaskPath $path -TaskName $Run -Confirm:$false
        }
    }
}

if ($LibraryOnly) { return }

# The script sits in <home>/kit/fleet, and an S4U task has no FLEET_HOME.
$fleetHome = Split-Path (Split-Path $PSScriptRoot)
switch ($Action) {
    'CodexStart' { Start-CodexTask -Run $Run -Brief $Brief -Slot $Slot -DispatchId $DispatchId -ResumeDispatchId $ResumeDispatchId }
    'CodexRun' { $code = Invoke-CodexRun -FleetHome $fleetHome -Run $Run -Brief $Brief -Slot $Slot -DispatchId $DispatchId -ResumeDispatchId $ResumeDispatchId; exit $code }
    'CodexState' { Get-CodexState -FleetHome $fleetHome -Run $Run -DispatchId $DispatchId }
    'CodexStop' { Stop-CodexTask -Run $Run }
    'Remove' { Remove-RunTasks -Run $Run }
}
