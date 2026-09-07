<#
.SYNOPSIS
    Resolve a model capability class to a concrete harness slug.

.DESCRIPTION
    The PowerShell leg of the model capability registry. It reads the compiled
    `model-registry.json` with ConvertFrom-Json and nothing else, so a dispatch
    wrapper gains no interpreter dependency: on a machine with only PowerShell,
    resolution still works.

    The resolution order is the contract, not an implementation detail:
    class -> harness -> contract -> effort -> emit. Every unsatisfied step throws
    a named code. Nothing here substitutes a model, assumes an author vendor, or
    downgrades an effort level silently.

    This module deliberately mirrors tools/resolve_model.py. Both read the same
    compiled artifact, and tests/test_powershell_module.py asserts the two agree
    on every class and harness in the registry.

.NOTES
    A binding change is a human commit (`bump_gate: human`). This module reads
    the registry; it never writes one.
#>

Set-StrictMode -Version Latest

$script:EffortOrder = @('none', 'low', 'medium', 'high', 'xhigh', 'max')
$script:PriceBands = @('low', 'medium', 'high', 'xhigh')
$script:EffortHints = @('routine', 'risk_path')
$script:Harnesses = @(
    'codex-cli', 'cursor-task', 'cursor-agent-cli',
    'claude-code-agents', 'claude-p', 'gemini-cli'
)
$script:OverlayCompiledName = 'model-registry.local.json'
# The overlay a human edits. This module cannot read it and never tries: the
# name exists only so discovery can tell "this project declares no overlay"
# apart from "this project's overlay was never compiled", which are the same
# silence otherwise and mean opposite things.
$script:OverlaySourceName = 'model-registry.local.yaml'
# The key `resolve sync` stamps into a compiled overlay, naming the registry it
# was validated against. This module has no schema validator, so provenance is
# what separates an artifact written by the validating writer from one edited
# by hand or left over from an older registry.
$script:OverlayProvenanceKey = 'validated_against'

function Throw-RegistryError {
    <#
        One shape for every failure: "<code>: <detail>". Callers match on the
        code, humans read the detail.
    #>
    param(
        [Parameter(Mandatory)][string]$Code,
        [Parameter(Mandatory)][string]$Detail
    )
    throw "${Code}: ${Detail}"
}

function Get-Prop {
    <# Read a possibly-absent property off a ConvertFrom-Json object. #>
    param($Object, [string]$Name)

    if ($null -eq $Object) { return $null }
    if ($Object -is [System.Collections.IDictionary]) {
        if ($Object.Contains($Name)) { return $Object[$Name] }
        return $null
    }
    $property = $Object.PSObject.Properties[$Name]
    if ($null -eq $property) { return $null }
    return $property.Value
}

function Get-PropNames {
    <#
        Returns a plain array. PowerShell unrolls it on output, so every caller
        wraps the call in @() — that is what keeps an empty result an empty array
        instead of $null, and a single result an array instead of a scalar.
    #>
    param($Object)

    if ($null -eq $Object) { return @() }
    if ($Object -is [System.Collections.IDictionary]) { return @($Object.Keys) }
    return @($Object.PSObject.Properties.Name)
}

function Get-AsArray {
    <# Normalize an absent / scalar / array JSON value to an array. Wrap in @(). #>
    param($Value)

    if ($null -eq $Value) { return @() }
    if ($Value -is [string]) { return @($Value) }
    return @($Value)
}

function Get-RegistryCandidate {
    <#
        The S2 locate order: AGENT_MODEL_REGISTRY, then P:\.agent, then the user
        profile. Returned as a list so the order is inspectable.
    #>
    [CmdletBinding()]
    param()

    $candidates = [System.Collections.Generic.List[string]]::new()
    if ($env:AGENT_MODEL_REGISTRY) { $candidates.Add($env:AGENT_MODEL_REGISTRY) }
    $candidates.Add('P:/.agent/model-registry.json')
    if ($env:USERPROFILE) {
        $candidates.Add((Join-Path $env:USERPROFILE '.agent/model-registry.json'))
    }
    return $candidates
}

function Resolve-RegistryPath {
    [CmdletBinding()]
    param([string]$Explicit)

    if ($Explicit) {
        if (-not (Test-Path -LiteralPath $Explicit)) {
            Throw-RegistryError 'registry_not_found' "$Explicit does not exist"
        }
        return (Resolve-Path -LiteralPath $Explicit).Path
    }

    # An override that was set is a decision to use that document; falling
    # through to the machine registry would resolve against a different one than
    # the caller named. An override that was never set is not a decision.
    if ($env:AGENT_MODEL_REGISTRY -and
        -not (Test-Path -LiteralPath $env:AGENT_MODEL_REGISTRY)) {
        Throw-RegistryError 'registry_not_found' (
            "AGENT_MODEL_REGISTRY names $($env:AGENT_MODEL_REGISTRY), which does " +
            'not exist; refusing to fall back to another registry'
        )
    }

    $candidates = Get-RegistryCandidate
    foreach ($candidate in $candidates) {
        if (Test-Path -LiteralPath $candidate) {
            return (Resolve-Path -LiteralPath $candidate).Path
        }
    }
    Throw-RegistryError 'registry_not_found' (
        'no registry at any S2 location: ' + ($candidates -join ', ')
    )
}

function Get-TextSha256 {
    <#
        Hash the file's bytes via .NET rather than Get-FileHash.

        Two reasons, both learned the hard way. `Get-FileHash` is not present on
        every Windows PowerShell 5.1 surface, and `Invoke-CodexDispatch.ps1` runs
        under `powershell`, not `pwsh` — so relying on it wrote an empty
        `registry_sha256` into the receipt instead of raising. And hashing bytes
        is what makes this agree with the resolver leg's `sha256_file`.
    #>
    param([Parameter(Mandatory)][string]$Path)

    $sha = $null
    try {
        $bytes = [System.IO.File]::ReadAllBytes((Resolve-Path -LiteralPath $Path).Path)
        $sha = [System.Security.Cryptography.SHA256]::Create()
        $hash = $sha.ComputeHash($bytes)
        return -join ($hash | ForEach-Object { $_.ToString('x2') })
    }
    catch {
        Throw-RegistryError 'registry_unreadable' (
            "cannot hash $Path : $($_.Exception.Message)"
        )
    }
    finally {
        if ($null -ne $sha) { $sha.Dispose() }
    }
}

function Get-EffectiveClass {
    <#
        Flatten an `extends` chain. `verifier: {extends: builder}` is its own
        class that shares the builder's contract today; flattening here lets it
        diverge later without touching a caller.
    #>
    param($Registry, [string]$Name)

    $classes = Get-Prop $Registry 'classes'
    $chain = [System.Collections.Generic.List[object]]::new()
    $seen = [System.Collections.Generic.List[string]]::new()
    $current = $Name

    while ($current) {
        if ($seen -contains $current) {
            Throw-RegistryError 'class_extends_cycle' (($seen + $current) -join ' -> ')
        }
        $seen.Add($current)
        $entry = Get-Prop $classes $current
        if ($null -eq $entry) {
            Throw-RegistryError 'unknown_class' (
                "'$current' is not a known class. Known classes: " +
                ((Get-PropNames $classes | Sort-Object) -join ', ')
            )
        }
        $chain.Add($entry)
        $current = Get-Prop $entry 'extends'
    }

    # Every helper call is wrapped in @() on purpose: `foreach ($x in f)` does not
    # unroll a function's returned array the way an assignment does, so an
    # unwrapped call would bind $key to the whole array and quietly produce a
    # hashtable keyed by an array.
    $contract = @{}
    $bindings = @{}
    for ($i = $chain.Count - 1; $i -ge 0; $i--) {
        $entryContract = Get-Prop $chain[$i] 'contract'
        foreach ($key in @(Get-PropNames $entryContract)) {
            $contract[$key] = Get-Prop $entryContract $key
        }
        $entryBindings = Get-Prop $chain[$i] 'bindings'
        foreach ($key in @(Get-PropNames $entryBindings)) {
            $bindings[$key] = Get-Prop $entryBindings $key
        }
    }
    return @{ Contract = $contract; Bindings = $bindings }
}

function Test-CanExpressEffort {
    <#
        Can this snapshot be dispatched at $Effort on $Harness? A harness that
        encodes effort in the model id answers from its id map; everything else
        answers from the snapshot's ladder. No ladder means the snapshot takes
        no effort selector at all.
    #>
    param($Entry, [string]$Harness, [string]$Effort)

    $harnessId = Get-Prop (Get-Prop $Entry 'harness_ids') $Harness
    if ($harnessId -is [string]) {
        return (@(Get-AsArray (Get-Prop $Entry 'efforts')) -contains $Effort)
    }
    return (@(Get-PropNames $harnessId) -contains $Effort)
}

function Get-EmittedSlug {
    param($Entry, [string]$Harness, $Effort)

    $harnessId = Get-Prop (Get-Prop $Entry 'harness_ids') $Harness
    if ($harnessId -is [string]) { return $harnessId }
    if (-not $Effort) {
        Throw-RegistryError 'effort_required_for_harness' (
            "$Harness encodes effort in the model id, so an effort must resolve"
        )
    }
    return (Get-Prop $harnessId $Effort)
}

function Assert-Contract {
    <#
        Raise the first unsatisfied clause. The order matters: a structural
        impossibility is reported as such rather than as whichever check happened
        to run first.
    #>
    param(
        [string]$ClassName,
        [hashtable]$Contract,
        [string]$Slug,
        $Entry,
        [string]$AuthorVendor,
        [int]$InputTokens
    )

    $floor = $Contract['effort_floor']
    $ceiling = Get-Prop $Entry 'effort_ceiling_effective'
    if ($floor -and $ceiling) {
        if ($script:EffortOrder.IndexOf($floor) -gt $script:EffortOrder.IndexOf($ceiling)) {
            Throw-RegistryError 'contract_conflict' (
                "$ClassName requires effort_floor '$floor' but '$Slug' measures no " +
                "better than '$ceiling'; this resolves to nothing rather than to a " +
                'silent downgrade'
            )
        }
    }

    $required = @(Get-AsArray $Contract['capabilities'])
    $have = @(Get-AsArray (Get-Prop $Entry 'capabilities'))
    $missing = @($required | Where-Object { $have -notcontains $_ })
    if ($missing.Count -gt 0) {
        Throw-RegistryError 'capability_unsatisfied' (
            "'$Slug' lacks $($missing -join ', ') required by $ClassName"
        )
    }

    $vendorAllow = @(Get-AsArray $Contract['vendor_allow'])
    $vendor = Get-Prop $Entry 'vendor'
    if ($vendorAllow.Count -gt 0 -and $vendorAllow -notcontains $vendor) {
        Throw-RegistryError 'vendor_not_allowed' (
            "'$Slug' is vendor '$vendor'; $ClassName allows $($vendorAllow -join ', ')"
        )
    }

    if ($Contract['vendor_distinct_from'] -eq 'author') {
        if (-not $AuthorVendor) {
            Throw-RegistryError 'author_vendor_required' (
                "$ClassName declares vendor_distinct_from: author, so the author's " +
                'vendor must be supplied (-AuthorVendor). Assuming it would either ' +
                'fake diversity or refuse a valid reviewer'
            )
        }
        if ($AuthorVendor -eq $vendor) {
            Throw-RegistryError 'vendor_diversity_violation' (
                "author vendor '$AuthorVendor' equals '$Slug''s vendor; $ClassName " +
                'requires a different vendor'
            )
        }
    }

    $authMode = $Contract['auth_mode']
    if ($authMode) {
        $auth = @(Get-AsArray (Get-Prop $Entry 'auth'))
        if ($auth -notcontains $authMode) {
            Throw-RegistryError 'auth_mode_unavailable' (
                "'$Slug' does not offer '$authMode' required by $ClassName"
            )
        }
    }

    $ceilingBand = $Contract['price_ceiling_band']
    $band = Get-Prop $Entry 'price_band'
    if ($ceilingBand -and $band) {
        if ($script:PriceBands.IndexOf($band) -gt $script:PriceBands.IndexOf($ceilingBand)) {
            Throw-RegistryError 'price_ceiling_exceeded' (
                "'$Slug' is band '$band' but $ClassName caps at '$ceilingBand'"
            )
        }
    }

    if (@(Get-AsArray $Contract['forbid']) -contains $Slug) {
        Throw-RegistryError 'forbidden_slug' "$ClassName forbids '$Slug'"
    }

    if ($InputTokens -gt 0) {
        $context = Get-Prop $Entry 'context'
        $limit = Get-Prop $context 'input_tokens'
        if ($limit -and $InputTokens -gt $limit) {
            if (Get-Prop $context 'reprices_whole_request_above') {
                Throw-RegistryError 'split_the_review' (
                    "$InputTokens input tokens crosses '$Slug''s $limit-token " +
                    'boundary, above which the ENTIRE request reprices; split the ' +
                    'work rather than straddle the cliff'
                )
            }
            Throw-RegistryError 'context_limit_exceeded' (
                "$InputTokens input tokens exceeds '$Slug''s $limit-token window"
            )
        }
    }
}

function Resolve-AgentModel {
    <#
    .SYNOPSIS
        Resolve a capability class to the concrete slug a harness accepts.

    .PARAMETER Class
        A registry class name, e.g. independent_reviewer. Never a model slug.

    .PARAMETER Harness
        The execution surface consuming the slug.

    .PARAMETER Effort
        An effort band, or the hint 'routine' / 'risk_path'.

    .PARAMETER AuthorVendor
        Vendor of the agent whose work is under review. Required for any class
        declaring vendor_distinct_from: author — absence is an error, not an
        assumption.

    .EXAMPLE
        Resolve-AgentModel -Class independent_reviewer -Harness codex-cli `
            -AuthorVendor xai -Format argv
    #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$Class,
        [Parameter(Mandatory)][string]$Harness,
        [string]$Effort,
        [string]$AuthorVendor,
        [string]$Project,
        [string]$RegistryPath,
        [string]$Slug,
        [int]$InputTokens = 0,
        [ValidateSet('object', 'json', 'argv', 'argv-array', 'ps1', 'env')][string]$Format = 'object'
    )

    $path = Resolve-RegistryPath -Explicit $RegistryPath
    $registrySha = Get-TextSha256 -Path $path
    $registry = Get-Content -LiteralPath $path -Raw -Encoding UTF8 | ConvertFrom-Json

    $overlayPath = $null
    $overlaySha = $null
    if ($Project) {
        $overlayPath = Find-OverlayCompiled -Project $Project
        if ($overlayPath) {
            $overlaySha = Get-TextSha256 -Path $overlayPath
            $overlay = Import-CompiledOverlay -Path $overlayPath -RegistrySha $registrySha
            $registry = Merge-Overlay -Registry $registry -Overlay $overlay
        }
    }

    # 1 - class
    $classes = Get-Prop $registry 'classes'
    if (@(Get-PropNames $classes) -notcontains $Class) {
        Throw-RegistryError 'unknown_class' (
            "'$Class' is not a known class. Known classes: " +
            ((Get-PropNames $classes | Sort-Object) -join ', ')
        )
    }

    # 2 - harness
    if ($script:Harnesses -notcontains $Harness) {
        Throw-RegistryError 'unknown_harness' (
            "'$Harness' is not a known harness. Known harnesses: " +
            ($script:Harnesses -join ', ')
        )
    }
    $effective = Get-EffectiveClass -Registry $registry -Name $Class
    $contract = $effective.Contract
    $bindings = $effective.Bindings
    if (-not $bindings.ContainsKey($Harness)) {
        Throw-RegistryError 'unresolvable_on_harness' (
            "'$Class' has no binding on '$Harness'. It is bound on: " +
            (($bindings.Keys | Sort-Object) -join ', ') +
            '. No substitute is chosen from another class'
        )
    }

    if ($Effort -eq 'inherit') {
        if ($contract.ContainsKey('inherit_allowed') -and -not $contract['inherit_allowed']) {
            Throw-RegistryError 'inherit_not_allowed' (
                "$Class sets inherit_allowed: false - inheriting the coordinator's " +
                "model would silently change this class's tier"
            )
        }
        $Effort = $null
    }

    $binding = $bindings[$Harness]
    $catalog = Get-Prop $registry 'catalog'
    $warnings = [System.Collections.Generic.List[string]]::new()

    # 3 - the caller's effort request, before any candidate is considered
    $explicitRequest = $null
    if ($Effort -and $script:EffortHints -contains $Effort) {
        $mapped = Get-Prop (Get-Prop $binding 'effort_map') $Effort
        if (-not $mapped) {
            Throw-RegistryError 'effort_hint_unmapped' (
                "$Class/$Harness declares no effort_map entry for '$Effort'"
            )
        }
        $explicitRequest = $mapped
    }
    elseif ($Effort) {
        if ($script:EffortOrder -notcontains $Effort) {
            Throw-RegistryError 'unknown_effort_requested' (
                "'$Effort' is not an effort level. Known levels: " +
                ($script:EffortOrder -join ', ')
            )
        }
        $explicitRequest = $Effort
    }

    # 4 - candidates: the primary binding, then its declared alternates.
    #     `fallbacks` are runtime rate-limit rungs, reported but never
    #     auto-selected, so `resolution` stays honest.
    $candidates = [System.Collections.Generic.List[object]]::new()
    if ($Slug) {
        $candidates.Add(@{ Resolution = 'explicit_override'; Slug = $Slug })
    }
    else {
        $candidates.Add(@{ Resolution = 'default'; Slug = (Get-Prop $binding 'slug') })
        $index = 0
        foreach ($alternate in @(Get-AsArray (Get-Prop $binding 'alternates'))) {
            $index++
            $candidates.Add(@{ Resolution = "alternate_$index"; Slug = $alternate })
        }
    }

    $contractFailure = $null
    $effortFailure = $null
    $harnessFailure = $null

    foreach ($candidate in $candidates) {
        $slugId = $candidate.Slug
        $entry = Get-Prop $catalog $slugId
        if ($null -eq $entry) {
            if (-not $contractFailure) {
                $contractFailure = "unknown_slug: '$slugId' is absent from the catalog"
            }
            continue
        }

        try {
            Assert-Contract -ClassName $Class -Contract $contract -Slug $slugId `
                -Entry $entry -AuthorVendor $AuthorVendor -InputTokens $InputTokens
        }
        catch {
            $message = $_.Exception.Message
            if ($message -match '^(author_vendor_required|split_the_review):') { throw }
            if (-not $contractFailure) { $contractFailure = $message }
            continue
        }

        $candidateWarnings = [System.Collections.Generic.List[string]]::new()

        # Whether this model exists on the harness at all, asked before the
        # effort ladder and the emitter - neither means anything for a snapshot
        # the harness cannot dispatch. Left to the emitter, the omission had
        # nothing to read and was reported as a missing effort, which pointed
        # the caller at the wrong field entirely (R4-F4).
        #
        # It follows the contract rather than preceding it: a binding that
        # breaks policy is worth naming even when the snapshot is also misfiled,
        # because policy is the part the operator can act on.
        $publishedOn = @(Get-PropNames (Get-Prop $entry 'harness_ids'))
        if ($publishedOn -notcontains $Harness) {
            if (-not $harnessFailure) {
                $available = if ($publishedOn.Count) {
                    ($publishedOn | Sort-Object) -join ', '
                } else { '<no harness>' }
                $harnessFailure = "slug_not_on_harness: '$slugId' is not published " +
                    "on $Harness; it is available on: $available"
            }
            continue
        }

        # A positive caller effort is a selection on the ladder, so it is
        # checked against the level that actually resolves - after the floor
        # raises and the ceiling clamps it - by the post-clamp check below.
        # Checking the raw request here instead made the answer depend on the
        # ladder's shape: with effort_floor 'high', 'medium' resolved at 'high'
        # while 'low' was refused, though both dispatch at 'high' (R4-F3,
        # AC-0.9). The other reader carries the same ordering.
        #
        # 'none' is not a rung. It asks for no reasoning effort at all, so a
        # floor cannot be satisfied by raising it - that would grant the
        # opposite of the request - and it keeps its own refusal.
        if ($explicitRequest -eq 'none' -and $contract['effort_floor']) {
            if (-not $effortFailure) {
                $effortFailure = "unknown_effort_level: $Class declares effort_floor " +
                    "'$($contract['effort_floor'])' on $Harness; 'none' asks for no " +
                    "reasoning effort and cannot satisfy a floor"
            }
            continue
        }

        # 5 - default -> hint -> floor -> clamp
        $wanted = $explicitRequest
        if (-not $wanted) { $wanted = Get-Prop $binding 'effort' }
        if (-not $wanted) { $wanted = $contract['effort_default'] }

        $floor = $contract['effort_floor']
        # R3-F2: a floor with nothing to raise is still a floor - it is the
        # minimum this class may be dispatched at, not a modifier on a default
        # that happens to exist.
        if ($floor -and ((-not $wanted) -or
            $script:EffortOrder.IndexOf($wanted) -lt $script:EffortOrder.IndexOf($floor))) {
            if ($wanted) {
                $candidateWarnings.Add("effort_raised_to_floor: $wanted -> $floor ($Class floor)")
            }
            $wanted = $floor
        }

        $clamped = $false
        $ceiling = Get-Prop $entry 'effort_ceiling_effective'
        if ($wanted -and $ceiling -and
            $script:EffortOrder.IndexOf($wanted) -gt $script:EffortOrder.IndexOf($ceiling)) {
            $candidateWarnings.Add(
                "effort_clamped: $wanted -> $ceiling ($slugId measures no better above this level)"
            )
            $wanted = $ceiling
            $clamped = $true
        }

        if ($wanted -and
            -not (Test-CanExpressEffort -Entry $entry -Harness $Harness -Effort $wanted)) {
            if ($explicitRequest) {
                if (-not $effortFailure) {
                    $ladder = @(Get-AsArray (Get-Prop $entry 'efforts'))
                    $ladderText = if ($ladder.Count) { $ladder -join ', ' } else { '<none>' }
                    $effortFailure = "unknown_effort_level: '$slugId' cannot be " +
                        "dispatched at '$wanted' on $Harness; its ladder is $ladderText"
                }
                continue
            }
            if ($floor) {
                # R3-F2: clearing an *optional* default for a snapshot with no
                # effort selector is legitimate; clearing a mandatory floor is a
                # silent downgrade. Fail the candidate so a declared alternate
                # can answer, and name the conflict when none can.
                if (-not $effortFailure) {
                    $ladder = @(Get-AsArray (Get-Prop $entry 'efforts'))
                    $ladderText = if ($ladder.Count) { $ladder -join ', ' } else { '<none>' }
                    $effortFailure = "effort_floor_unsatisfiable: $Class requires at " +
                        "least '$floor' on $Harness, and '$slugId' takes no '$wanted' " +
                        "setting there; its ladder is $ladderText"
                }
                continue
            }
            $candidateWarnings.Add(
                "effort_not_applicable: $slugId takes no effort selector on $Harness"
            )
            $wanted = $null
        }

        if ($candidate.Resolution -like 'alternate_*') {
            $candidateWarnings.Add(
                "binding_alternate_selected: $(Get-Prop $binding 'slug') -> $slugId " +
                "(primary cannot serve effort '$(if ($explicitRequest) { $explicitRequest } else { $wanted })')"
            )
        }

        foreach ($existing in $warnings) { $candidateWarnings.Insert(0, $existing) }

        $vendor = Get-Prop $entry 'vendor'
        # 6 - emit
        $result = [ordered]@{
            class            = $Class
            harness          = $Harness
            slug             = (Get-EmittedSlug -Entry $entry -Harness $Harness -Effort $wanted)
            catalog_id       = $slugId
            effort           = $wanted
            effort_clamped   = $clamped
            extra_args       = @(Get-AsArray (Get-Prop $binding 'extra_args'))
            fallbacks        = @(Get-AsArray (Get-Prop $binding 'fallbacks'))
            vendor           = $vendor
            author_vendor    = $(if ($AuthorVendor) { $AuthorVendor } else { $null })
            vendor_distinct  = $(if ($AuthorVendor) { $AuthorVendor -ne $vendor } else { $null })
            price_band       = (Get-Prop $entry 'price_band')
            registry_path    = $path
            registry_version = (Get-Prop $registry 'updated')
            registry_sha256  = $registrySha
            overlay_path     = $overlayPath
            overlay_sha256   = $overlaySha
            resolution       = $candidate.Resolution
            warnings         = @($candidateWarnings)
        }
        return Format-AgentModelResult -Result $result -Format $Format
    }

    # The harness conflict is the most concrete of the three - it is a fact
    # about the catalog rather than a judgement about policy - so it is the one
    # worth reporting when candidates failed for different reasons.
    if ($harnessFailure) { throw $harnessFailure }
    if ($contractFailure) { throw $contractFailure }
    if ($effortFailure) { throw $effortFailure }
    Throw-RegistryError 'unresolvable_class' "no candidate satisfies $Class on $Harness"
}

function Find-OverlayCompiled {
    <#
        Walk upward for a project overlay and return the compiled artifact.

        Only the compiled sibling is ever read: this module has no schema
        validator and no way to parse the source, and `resolve sync` is what
        writes the artifact it does read.

        Discovery stops at the first `.agent` that declares an overlay at all --
        by artifact or by source name. Walking past a project whose overlay was
        never compiled would answer it with global policy, or worse, with some
        ancestor's, and every command would still exit 0 while the project's own
        accepted contract went unenforced (R2-F5). Testing for the source is a
        name lookup, nothing more, so the module stays free of any interpreter.
    #>
    [CmdletBinding()]
    param([Parameter(Mandatory)][string]$Project)

    $current = (Resolve-Path -LiteralPath $Project).Path
    while ($current) {
        $agentDir = Join-Path $current '.agent'
        $candidate = Join-Path $agentDir $script:OverlayCompiledName
        if (Test-Path -LiteralPath $candidate) { return $candidate }
        $source = Join-Path $agentDir $script:OverlaySourceName
        if (Test-Path -LiteralPath $source) {
            Throw-RegistryError 'overlay_not_compiled' (
                "$source has no compiled sibling at $candidate. This module " +
                'reads only the compiled artifact, so resolving here would ' +
                "silently drop the project's own policy. Run " +
                '`resolve_model.py sync` to compile it.'
            )
        }
        $parent = Split-Path -Parent $current
        if ($parent -eq $current) { break }
        $current = $parent
    }
    return $null
}

function Import-CompiledOverlay {
    <#
        Read a compiled overlay, refusing one this registry did not produce.

        The tightening rules are enforced by `resolve sync`, which has a schema
        validator this module deliberately cannot. What makes merging safe is that
        the artifact was written by that validator against this exact registry —
        so the SHA it records is checked rather than the rules re-implemented.
        A missing stamp is a refusal too: an overlay nothing validated is the
        case the guard exists for.
    #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$Path,
        [Parameter(Mandatory)][string]$RegistrySha
    )

    $overlay = Get-Content -LiteralPath $Path -Raw -Encoding UTF8 | ConvertFrom-Json
    $stamped = Get-Prop $overlay $script:OverlayProvenanceKey
    if ($stamped -ne $RegistrySha) {
        $seen = if ($stamped) { $stamped } else { '(none)' }
        Throw-RegistryError 'overlay_not_validated' (
            "$Path records registry $seen but the registry in use is " +
            "$RegistrySha. Run ``resolve_model.py sync`` to revalidate and " +
            'recompile the overlay.'
        )
    }
    return $overlay
}

function Merge-Overlay {
    <# Add overlay classes; apply `constraints` as tightening deltas. #>
    [CmdletBinding()]
    param($Registry, $Overlay)

    $classes = Get-Prop $Registry 'classes'
    $globalNames = @(Get-PropNames $classes)

    foreach ($name in @(Get-PropNames (Get-Prop $Overlay 'classes'))) {
        $entry = Get-Prop (Get-Prop $Overlay 'classes') $name
        if ($globalNames -contains $name) {
            $constraints = Get-Prop $entry 'constraints'
            $globalClass = Get-Prop $classes $name
            $target = Get-Prop $globalClass 'contract'
            if ($null -eq $target) {
                # R3-F3: a class that inherits its whole contract
                # (`verifier: {extends: builder}`) carries no `contract` object
                # of its own. Writing the tightening onto the parent's object
                # would re-govern every sibling that extends it, and writing
                # onto `$null` merely emitted a non-terminating
                # PropertyNotFoundException and dropped the tightening while
                # still exiting 0 -- so give the class its own object, matching
                # the sibling reader's default-then-update merge.
                $target = [pscustomobject]@{}
                $globalClass | Add-Member -NotePropertyName 'contract' -NotePropertyValue $target
            }
            foreach ($key in @(Get-PropNames $constraints)) {
                $value = Get-Prop $constraints $key
                if ($target.PSObject.Properties[$key]) {
                    $target.PSObject.Properties[$key].Value = $value
                }
                else {
                    $target | Add-Member -NotePropertyName $key -NotePropertyValue $value
                }
            }
        }
        else {
            $classes | Add-Member -NotePropertyName $name -NotePropertyValue $entry
        }
    }
    return $Registry
}

function Get-AgentModelArgv {
    <#
        The tokens the harness command takes, as tokens.

        One builder behind both argv formats, so they cannot drift into
        disagreeing about what was dispatched. `argv` joins them for shells that
        split on spaces; PowerShell does not split, and handing that joined
        string to a native command sends it as a single argument -- which is how
        a published snippet ends up invoking a reviewer with one malformed
        parameter instead of a model and an effort (R2-F3). `argv-array` is the
        form to splat there.
    #>
    [CmdletBinding()]
    param($Result)

    $parts = [System.Collections.Generic.List[string]]::new()
    if ($Result.harness -eq 'codex-cli') {
        $parts.Add('-m'); $parts.Add($Result.slug)
        if ($Result.effort) {
            $parts.Add('-c')
            $parts.Add("model_reasoning_effort=$($Result.effort)")
        }
    }
    else {
        $parts.Add('--model'); $parts.Add($Result.slug)
    }
    foreach ($extra in $Result.extra_args) { $parts.Add($extra) }
    return $parts.ToArray()
}

function Format-AgentModelResult {
    [CmdletBinding()]
    param($Result, [string]$Format)

    switch ($Format) {
        'object' { return [pscustomobject]$Result }
        'json' { return ([pscustomobject]$Result | ConvertTo-Json -Depth 6) }
        'argv' { return ((Get-AgentModelArgv -Result $Result) -join ' ') }
        'argv-array' {
            # The leading comma keeps the array from unrolling on return, which
            # is the whole point of the format: a caller splats it.
            return , (Get-AgentModelArgv -Result $Result)
        }
        'ps1' {
            $lines = [System.Collections.Generic.List[string]]::new()
            $lines.Add('@{')
            foreach ($key in @('class', 'harness', 'slug', 'effort', 'resolution',
                    'registry_version', 'registry_sha256', 'overlay_sha256')) {
                $value = $Result[$key]
                $rendered = if ($null -eq $value) { '$null' } else { "'$value'" }
                $lines.Add("    $($key -replace '_', '') = $rendered")
            }
            $lines.Add("    ExtraArgs = @(" +
                (($Result.extra_args | ForEach-Object { "'$_'" }) -join ', ') + ')')
            $lines.Add('}')
            return ($lines -join "`n")
        }
        'env' {
            $pairs = [ordered]@{
                AGENT_MODEL_CLASS      = $Result.class
                AGENT_MODEL_SLUG       = $Result.slug
                AGENT_MODEL_HARNESS    = $Result.harness
                AGENT_MODEL_EFFORT     = $(if ($Result.effort) { $Result.effort } else { '' })
                AGENT_MODEL_RESOLUTION = $Result.resolution
                AGENT_REGISTRY_VERSION = $Result.registry_version
                AGENT_REGISTRY_SHA256  = $Result.registry_sha256
            }
            return (($pairs.Keys | ForEach-Object { "$_=$($pairs[$_])" }) -join "`n")
        }
    }
}

function Get-AgentModelPin {
    <#
    .SYNOPSIS
        Read a never-bumped pin, e.g. benchmark_headroom_baseline.

    .DESCRIPTION
        Benchmark isolation must follow the pin rather than a literal that
        survived in a script, so the wrapper asks for the pin by name.
    #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$Name,
        [string]$RegistryPath
    )

    $path = Resolve-RegistryPath -Explicit $RegistryPath
    $registry = Get-Content -LiteralPath $path -Raw -Encoding UTF8 | ConvertFrom-Json
    $pin = Get-Prop (Get-Prop $registry 'pins') $Name
    if ($null -eq $pin) {
        Throw-RegistryError 'unknown_pin' (
            "'$Name' is not a registry pin. Known pins: " +
            ((Get-PropNames (Get-Prop $registry 'pins') | Sort-Object) -join ', ')
        )
    }
    $catalogEntry = Get-Prop (Get-Prop $registry 'catalog') (Get-Prop $pin 'slug')
    return [pscustomobject][ordered]@{
        name             = $Name
        slug             = (Get-Prop $pin 'slug')
        effort           = (Get-Prop $pin 'effort')
        never_bump       = (Get-Prop $pin 'never_bump')
        reason           = (Get-Prop $pin 'reason')
        vendor           = (Get-Prop $catalogEntry 'vendor')
        registry_path    = $path
        registry_version = (Get-Prop $registry 'updated')
        registry_sha256  = (Get-TextSha256 -Path $path)
    }
}

function resolve {
    <#
    .SYNOPSIS
        Print the slug a capability class resolves to — nothing else.

    .DESCRIPTION
        The dispatch skills write their command templates as
        `-m $(resolve independent_reviewer)`. This makes that real. Before it
        existed the templates were prose: a reader who pasted one got "The term
        'resolve' is not recognized", and the obvious repair — typing a slug
        back in — is precisely what the registry exists to prevent.

        Output is the bare slug, because it is interpolated straight into an
        argv position. Any decoration would become part of the model name the
        CLI receives.

        The harness is inferred when the class binds exactly one, which covers
        every single-surface class the skills dispatch. When a class binds
        several — `coordinator` binds three — that is a named failure rather
        than a pick: a silently wrong harness still resolves to a real slug, so
        the dispatch would succeed on the wrong surface and nothing downstream
        would notice.

    .EXAMPLE
        $null | codex exec -m $(resolve independent_reviewer -AuthorVendor xai)

    .EXAMPLE
        $null | claude -p --model $(resolve coordinator -Harness claude-p)
    #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory, Position = 0)][string]$Class,
        [string]$Harness,
        [string]$Effort,
        [string]$AuthorVendor,
        [string]$Project,
        [string]$RegistryPath
    )

    if (-not $Harness) {
        $path = Resolve-RegistryPath -Explicit $RegistryPath
        $registry = Get-Content -LiteralPath $path -Raw -Encoding UTF8 |
            ConvertFrom-Json
        if ($Project) {
            # Merge-Overlay wants the parsed document; handing it the path made
            # this branch a no-op that still looked like it applied the overlay.
            $overlayPath = Find-OverlayCompiled -Project $Project
            if ($null -ne $overlayPath) {
                $overlay = Import-CompiledOverlay -Path $overlayPath `
                    -RegistrySha (Get-TextSha256 -Path $path)
                $registry = Merge-Overlay -Registry $registry -Overlay $overlay
            }
        }
        $entry = Get-Prop (Get-Prop $registry 'classes') $Class
        if ($null -eq $entry) {
            Throw-RegistryError 'unknown_class' (
                "'$Class' is not a registry class. Known classes: " +
                ((Get-PropNames (Get-Prop $registry 'classes') | Sort-Object) -join ', ')
            )
        }
        $bound = @(Get-PropNames (Get-Prop $entry 'bindings'))
        if ($bound.Count -ne 1) {
            Throw-RegistryError 'ambiguous_harness' (
                "'$Class' binds $($bound.Count) harnesses (" +
                (($bound | Sort-Object) -join ', ') +
                "), so the surface cannot be inferred. Pass -Harness."
            )
        }
        $Harness = $bound[0]
    }

    $arguments = @{ Class = $Class; Harness = $Harness }
    foreach ($name in 'Effort', 'AuthorVendor', 'Project', 'RegistryPath') {
        $value = Get-Variable -Name $name -ValueOnly -ErrorAction SilentlyContinue
        if ($value) { $arguments[$name] = $value }
    }
    return (Resolve-AgentModel @arguments).slug
}

Export-ModuleMember -Function Resolve-AgentModel, Get-AgentModelPin,
    Get-RegistryCandidate, Resolve-RegistryPath, resolve
