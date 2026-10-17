<#
.SYNOPSIS
    Cancel one scheduled credits run (report section 7.4). The store cancel verb sets
    cancel_requested_utc on the open segment; the launcher of that segment sees it, ends the job
    and finalizes the segment cancelled.

.DESCRIPTION
    A run that is not yet running moves to cancelled at once, and its pending request ends as
    not_started (cancelled). A run that is cancelled already, or in another final state, is
    no_change: the script never changes a final state.

    The script prints one JSON line and exits:
      0  changed or no_change;
      3  refused by the store (for example an unknown run);
      9  an unexpected error.

.EXAMPLE
    pwsh -NoProfile -File .agent/skills/claude-credits/Stop-CreditsRun.ps1 -RunId my-plan-exec
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][ValidatePattern('^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$')][string]$RunId,

    [string]$StateDb = '{{RECEIPTS_DIR}}/credits/state.db',

    # Saved in the store with the cancel (optional).
    [string]$Reason
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

Import-Module -Name (Join-Path $PSScriptRoot 'CreditsRun.psm1') -Force -DisableNameChecking -ErrorAction Stop

function Write-Result([hashtable]$Payload, [int]$Code) {
    Write-Output ($Payload | ConvertTo-Json -Compress -Depth 6)
    $global:LASTEXITCODE = $Code
}

try {
    $cancelArgs = @('--run-id', $RunId)
    if ($Reason) { $cancelArgs += @('--reason', $Reason) }
    $res = Invoke-CreditsState -StateDb $StateDb -Verb 'cancel' -Arguments $cancelArgs
    if ($res.Code -eq 0 -and $null -ne $res.Payload) {
        Write-Result @{ result = [string]$res.Payload.result; run_id = $RunId; state = 'cancelled' } 0
        exit 0
    }
    $errorCode = if ($null -ne $res.Payload -and $null -ne $res.Payload.PSObject.Properties['error']) { [string]$res.Payload.error } else { $null }
    if ($res.Code -eq 3 -and $errorCode -eq 'invalid_transition') {
        # A run in another final state (done, failed, ...) stays as it is.
        $now = Invoke-CreditsState -StateDb $StateDb -Verb 'run_status' -Arguments @('--run-id', $RunId)
        $state = if ($now.Code -eq 0 -and $null -ne $now.Payload -and $now.Payload.exists) { [string]$now.Payload.state } else { $null }
        Write-Result @{ result = 'no_change'; run_id = $RunId; state = $state } 0
        exit 0
    }
    if ($res.Code -eq 3) {
        $message = if ($null -ne $res.Payload.PSObject.Properties['message']) { [string]$res.Payload.message } else { '' }
        Write-Result @{ result = 'refused'; run_id = $RunId; reason = $errorCode; message = $message } 3
        exit 3
    }
    throw "credits_state.py cancel failed: $(Format-CreditsStateError $res)"
} catch {
    Write-Result @{ result = 'error'; run_id = $RunId; message = $_.Exception.Message } 9
    exit 9
}
