<#
.SYNOPSIS
    Send one orchestrator message to a credits run.

.DESCRIPTION
    The orchestrator's send command (report section 4.6.2). It checks the message against
    schemas/credits-msg.v1.json, then runs credits_state.py send. The store gives the message
    the run's next seq and the msg_id <run_id>-m<seq>, stores the payload_hash of the identity
    fields, and asks the monitor for a pass (rescan.request next to the store).

    The inbox hook of the run delivers the message on the next tool call or Stop of the bound
    session (report section 4.6.4).

    Kinds: info, query, stop-after-row and ruling. A ruling needs -HumanQuote, -Decision, -GateId,
    -OrchestratorSession and -UserMessageUuid (schema_invalid without them;
    `tools/credits_msg.py locate --session <id> --quote "<words>"` proposes the uuid); the inbox hook checks
    it against the typed entry of the orchestrator session before it frames it as a ruling
    (report section 4.6.3). The body has at most 4000 characters (body_too_long).

    Output: the store's JSON line. Exit codes: the store's codes. 0 changed, 2 usage,
    3 refused (kind_not_enabled, body_too_long, schema_invalid, unknown_run), 9 crash, 75 busy.

.EXAMPLE
    pwsh -File .agent/skills/claude-credits/Send-CreditsRunMessage.ps1 -RunId it8-10-exec -Kind info -Body "CI on main is red for an external reason."

.EXAMPLE
    pwsh -File .agent/skills/claude-credits/Send-CreditsRunMessage.ps1 -RunId it8-10-exec -Kind ruling -Body "D-1: A" -HumanQuote "D-1: A" -Decision D-1 -GateId g-it8-10-exec-1-1 -OrchestratorSession <session id> -UserMessageUuid <uuid of the typed entry>
#>
[CmdletBinding()]
param(
    # The credits store. Default: the store of Invoke-ClaudeCredits.ps1 with its default -OutputDir.
    [string]$StateDb = '{{RECEIPTS_DIR}}/credits/state.db',

    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$')]
    [string]$RunId,

    # The schema and the store refuse ruling with their own reason, so the value is not limited here.
    [Parameter(Mandatory = $true)]
    [string]$Kind,

    [Parameter(Mandatory = $true)]
    [string]$Body,

    # The human's words when the message carries a human instruction.
    [string]$HumanQuote,

    [string]$Decision,
    [string]$GateId,
    [string]$OrchestratorSession,
    [string]$UserMessageUuid
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

Import-Module -Name (Join-Path $PSScriptRoot 'CreditsRun.psm1') -Force -DisableNameChecking

$EnabledKinds = @('info', 'query', 'stop-after-row', 'ruling')
$BodyMax = 4000
$SchemaFile = Join-Path $PSScriptRoot 'schemas/credits-msg.v1.json'

function Write-Refusal([string]$Error_, [string]$Message) {
    $doc = [ordered]@{ result = 'refused'; error = $Error_; message = $Message; verb = 'send' }
    [Console]::Out.WriteLine(($doc | ConvertTo-Json -Compress))
    exit 3
}

function ConvertTo-NullableText([string]$Value) {
    if ([string]::IsNullOrEmpty($Value)) { return $null }
    return $Value
}

if (-not (Test-Path -LiteralPath $StateDb -PathType Leaf)) {
    [Console]::Error.WriteLine("Send-CreditsRunMessage: no credits store at $StateDb")
    exit 2
}

$doc = [ordered]@{
    schema                  = 'credits-msg.v1'
    run_id                  = $RunId
    kind                    = $Kind
    body                    = $Body
    human_quote             = ConvertTo-NullableText $HumanQuote
    decision_id             = ConvertTo-NullableText $Decision
    gate_id                 = ConvertTo-NullableText $GateId
    orchestrator_session_id = ConvertTo-NullableText $OrchestratorSession
    user_message_uuid       = ConvertTo-NullableText $UserMessageUuid
}
$valid = Test-Json -Json ($doc | ConvertTo-Json -Depth 4) -SchemaFile $SchemaFile -ErrorAction SilentlyContinue
if (-not $valid) {
    # The same reasons as the store, so a refusal reads the same from either check.
    if ($Kind -notin $EnabledKinds) {
        Write-Refusal 'kind_not_enabled' "kind $Kind is not enabled in this phase"
    }
    if ($Body.Length -gt $BodyMax) {
        Write-Refusal 'body_too_long' "the body has $($Body.Length) characters; the cap is $BodyMax"
    }
    Write-Refusal 'schema_invalid' "the message does not match credits-msg.v1 ($SchemaFile)"
}

$arguments = @('--run-id', $RunId, '--kind', $Kind, '--body', $Body)
if ($HumanQuote) { $arguments += @('--human-quote', $HumanQuote) }
if ($Decision) { $arguments += @('--decision-id', $Decision) }
if ($GateId) { $arguments += @('--gate-id', $GateId) }
if ($OrchestratorSession) { $arguments += @('--orchestrator-session', $OrchestratorSession) }
if ($UserMessageUuid) { $arguments += @('--user-message-uuid', $UserMessageUuid) }

$res = Invoke-CreditsState -StateDb $StateDb -Verb send -Arguments $arguments
if ($res.Out) { [Console]::Out.Write($res.Out) }
if ($res.Err) { [Console]::Error.Write($res.Err) }
exit $res.Code
