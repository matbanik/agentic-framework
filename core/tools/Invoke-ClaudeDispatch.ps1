[CmdletBinding()]
param(
    # The capability class this dispatch needs. The registry (located per
    # .agent/INSTANTIATE.md S2) binds a class to a concrete snapshot for
    # the claude-p harness, so a model bump is one edit there and no edit here.
    [Parameter(Mandatory = $true)]
    [string]$ModelClass,

    # Vendor of the agent that authored the work. Required for any class that
    # declares `vendor_distinct_from: author`. A session may set
    # {{PROJECT_NAME_UPPER}}_AUTHOR_VENDOR once instead of passing it per call.
    [Parameter(Mandatory = $false)]
    [string]$AuthorVendor,

    # Explicit snapshot override. It still goes through the registry, which
    # checks that the snapshot exists, is not retired and meets the class contract.
    [Parameter(Mandatory = $false)]
    [string]$Model,

    # Omitted: the class default from the registry. Passed to `claude --effort`.
    [Parameter(Mandatory = $false)]
    [ValidateSet('low', 'medium', 'high', 'xhigh', 'max')]
    [string]$ReasoningEffort,

    [Parameter(Mandatory = $false)]
    [string]$PromptFile,

    [Parameter(Mandatory = $false)]
    [string]$PromptText,

    [Parameter(Mandatory = $false)]
    [string]$DispatchId,

    [Parameter(Mandatory = $false)]
    [string]$OutputDir = '{{RECEIPTS_DIR}}/dispatch',

    # `plan` is read-only. A caller that needs writes passes the mode explicitly.
    [Parameter(Mandatory = $false)]
    [ValidateSet('plan', 'acceptEdits', 'dontAsk', 'bypassPermissions')]
    [string]$PermissionMode = 'plan',

    # Omitted: no --max-budget-usd. The CLI ends a run that reaches the budget.
    [Parameter(Mandatory = $false)]
    [double]$MaxBudgetUsd,

    # 0 = derive from the effort (low/medium=900, high=1800, xhigh=2700, max=3600).
    [Parameter(Mandatory = $false)]
    [ValidateRange(0, 86400)]
    [int]$TimeoutSec = 0,

    # The process working directory. `claude -p` has no -C, so this is where the
    # session runs and where its tools see the files. Default: this repository.
    [Parameter(Mandatory = $false)]
    [string]$WorkingDirectory,

    # A repository-held PromptFile must sit under this root or one of its
    # worktrees. Default: the repository that holds this wrapper.
    [Parameter(Mandatory = $false)]
    [string]$RepoRoot,

    [Parameter(Mandatory = $false)]
    [switch]$Force,

    # Continue the Claude session of an earlier dispatch in the same OutputDir.
    # The session ID is read from <OutputDir>/<id>/status.json. Review classes
    # are refused, so every review round starts fresh.
    [Parameter(Mandatory = $false)]
    [string]$ResumeDispatchId,

    # Branch a new Claude session from an earlier dispatch's session. Same
    # source rules and refusals as -ResumeDispatchId; the two are exclusive.
    [Parameter(Mandatory = $false)]
    [string]$ForkDispatchId,

    # Check the arguments, the paths and a continuation source, print
    # `dispatch_args_ok` and exit 0 without creating a directory or starting a process.
    [Parameter(Mandatory = $false)]
    [switch]$ValidateOnly,

    [Parameter(Mandatory = $false)]
    [string]$ClaudeExecutable = 'claude'
)

# The repository that holds this wrapper. It is always the registry project,
# so a scratch -WorkingDirectory does not change the model resolution.
$wrapperRepoRoot = Split-Path -Parent $PSScriptRoot

# The classes whose sessions are never continued (resume or fork), as target or
# as source. This is the same set, with the same error names, as the canonical
# set in tools/Invoke-CodexDispatch.ps1; the resume/fork tests pin both copies
# to one expected set and to the review classes the registry names.
$ResumeReviewDenyClasses = @(
    'independent_reviewer',
    'fallback_reviewer',
    'peer_reviewer',
    'checklist_validator'
)

$DispatchIdPattern = '^[A-Za-z0-9][A-Za-z0-9._-]{0,79}\z'
$SessionIdPattern = '^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\z'

# Write a named continuation refusal on stderr and stop with exit 1. Every
# refusal runs before the run directory exists and before claude is started.
function Stop-ContinuationRefused {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][string]$Detail
    )
    [Console]::Error.WriteLine("${Name}: $Detail")
    exit 1
}

# Write a named argument error on stderr and stop with exit 1.
function Stop-DispatchArgs {
    param([Parameter(Mandatory = $true)][string]$Message)
    [Console]::Error.WriteLine($Message)
    exit 1
}

function Write-TextNoBom {
    param(
        [string]$Path,
        [string]$Content
    )
    $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($Path, $Content, $utf8NoBom)
}

function Get-Sha256File {
    param([Parameter(Mandatory = $true)][string]$Path)
    $stream = [System.IO.File]::OpenRead($Path)
    $sha = [System.Security.Cryptography.SHA256]::Create()
    try {
        $bytes = $sha.ComputeHash($stream)
        return ([System.BitConverter]::ToString($bytes)).Replace('-', '').ToLowerInvariant()
    } finally {
        $sha.Dispose()
        $stream.Dispose()
    }
}

# The effort-scaled default timeout; the same table as the Codex wrapper.
function Get-DefaultDispatchTimeoutSec {
    param([string]$Effort)
    switch ($Effort) {
        'medium' { return 900 }
        'high' { return 1800 }
        'xhigh' { return 2700 }
        'max' { return 3600 }
        default { return 900 }
    }
}

# Windows drops trailing dots and spaces from a path name and compares names
# without case, so 'source', 'Source' and 'source.' name one directory. Two
# paths name the same directory when their keys are equal.
function Get-RunDirIdentityKey {
    param([Parameter(Mandatory = $true)][string]$Path)
    $names = $Path.Replace('\', '/').Split('/') | ForEach-Object { $_.TrimEnd('.', ' ') }
    return ($names -join '/').ToUpperInvariant()
}

function Get-PhysicalPath {
    param(
        [string]$path,
        [System.Collections.Generic.HashSet[string]]$seen = $null
    )
    if ([string]::IsNullOrEmpty($path)) { return "" }
    if ($seen -eq $null) {
        $seen = New-Object System.Collections.Generic.HashSet[string]([System.StringComparer]::OrdinalIgnoreCase)
    }

    $cleanPath = $path.Replace('\', '/')
    # Under Windows PowerShell GetFullPath throws on an illegal character or a
    # colon after the drive, and that error does not stop the script: $absPath
    # would stay empty and the walk below would return the drive root.
    try {
        $absPath = [System.IO.Path]::GetFullPath($cleanPath).Replace('\', '/')
    }
    catch {
        throw "Not a valid path: $path"
    }

    if (-not $seen.Add($absPath)) {
        throw "Circular reparse-point path detected: $absPath"
    }

    $components = $absPath.Split('/')
    $resolved = $components[0]
    if ([string]::IsNullOrEmpty($resolved)) {
        $resolved = "/"
    }

    for ($i = 1; $i -lt $components.Count; $i++) {
        $name = $components[$i]
        if ([string]::IsNullOrEmpty($name)) { continue }

        $resolved = Join-Path $resolved $name
        if (Test-Path -LiteralPath $resolved) {
            $item = Get-Item -LiteralPath $resolved -Force
            $isReparsePoint = (($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0)
            if ($isReparsePoint) {
                $targets = @($item.Target)
                if ($targets.Count -ne 1 -or [string]::IsNullOrWhiteSpace([string]$targets[0])) {
                    throw "Unsupported or unresolved reparse point: $resolved"
                }
                $firstTarget = [string]$targets[0]
                $currentTarget = $firstTarget -replace '^\\\?\?\\', ''
                $currentTarget = $currentTarget -replace '^\\\\\?\\', ''
                if (-not [System.IO.Path]::IsPathRooted($currentTarget)) {
                    $linkParent = Split-Path -Parent $resolved
                    $currentTarget = Join-Path $linkParent $currentTarget
                }
                $resolved = Get-PhysicalPath $currentTarget $seen
            }
        }
    }
    return [System.IO.Path]::GetFullPath($resolved).Replace('\', '/')
}

function Test-UnderAcceptedRoot {
    # True when the canonical $Path equals, or sits under, one of the canonical $Roots.
    param(
        [string]$Path,
        [string[]]$Roots
    )
    if ([string]::IsNullOrEmpty($Path)) { return $false }
    foreach ($root in $Roots) {
        if ([string]::IsNullOrEmpty($root)) { continue }
        if ($Path -eq $root -or $Path.StartsWith($root + "/", [System.StringComparison]::OrdinalIgnoreCase)) {
            return $true
        }
    }
    return $false
}

function Get-AcceptedRepoRoots {
    # The canonical repository root followed by every worktree git lists for it.
    param([string]$CanonicalRepoRoot)
    $roots = New-Object System.Collections.Generic.List[string]
    $roots.Add($CanonicalRepoRoot)
    $listing = @()
    try {
        $listing = @(& git -C $CanonicalRepoRoot worktree list --porcelain 2>$null)
        if ($LASTEXITCODE -ne 0) { $listing = @() }
    } catch {
        $listing = @()
    }
    foreach ($entry in $listing) {
        $line = [string]$entry
        if (-not $line.StartsWith('worktree ', [System.StringComparison]::Ordinal)) { continue }
        try {
            $worktreeRoot = Get-PhysicalPath $line.Substring(9)
        } catch {
            continue
        }
        if (-not [string]::IsNullOrEmpty($worktreeRoot) -and -not $roots.Contains($worktreeRoot)) {
            $roots.Add($worktreeRoot)
        }
    }
    return $roots.ToArray()
}

# The words that run a resolved executable in cmd.exe (New-CmdStartInfo): a
# .cmd/.bat shim or an .exe runs directly; an npm .ps1 shim runs through its
# sibling .cmd when there is one, else through powershell.
function Get-LaunchSpec {
    param([Parameter(Mandatory = $true)][string]$ResolvedExecutable)
    $extension = [System.IO.Path]::GetExtension($ResolvedExecutable)
    if ($extension -eq '.ps1') {
        $sibling = [System.IO.Path]::ChangeExtension($ResolvedExecutable, '.cmd')
        if (Test-Path -LiteralPath $sibling -PathType Leaf) {
            return @{ Command = @($sibling) }
        }
        return @{ Command = @('powershell', '-NoProfile', '-File', $ResolvedExecutable) }
    }
    return @{ Command = @($ResolvedExecutable) }
}

# cmd.exe expands %NAME% anywhere in its command line, also inside quotes, so a
# literal path that holds a percent sign would name another file. Each word and
# each redirect target goes in through its own environment variable: cmd.exe
# expands a reference once and does not scan the result again, and /v:off keeps
# !NAME! literal. A .cmd or .bat shim runs directly in this cmd.exe; a nested
# 'cmd.exe /c' would parse the expanded path a second time. Returns the start
# info and a log text (the command line, then each variable and its value).
function New-CmdStartInfo {
    param(
        [Parameter(Mandatory = $true)][string[]]$Command,
        [string]$StdinPath,
        [string]$StdoutPath,
        [string]$StderrPath
    )
    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = 'cmd.exe'
    $psi.UseShellExecute = $false
    $psi.CreateNoWindow = $true
    $log = New-Object System.Collections.Generic.List[string]
    $words = @()
    for ($i = 0; $i -lt $Command.Count; $i++) {
        if ($Command[$i] -eq '') {
            # cmd.exe leaves a reference to an empty variable unexpanded.
            $words += '""'
            continue
        }
        $name = "{{PROJECT_NAME_UPPER}}_DISPATCH_ARG$i"
        # Inner quotes are escaped for the CLI's own argv parser.
        $psi.EnvironmentVariables[$name] = $Command[$i] -replace '"', '\"'
        $words += "`"%$name%`""
        $log.Add("$name=$($Command[$i])")
    }
    $line = $words -join ' '
    $redirects = @(
        @('<', '{{PROJECT_NAME_UPPER}}_DISPATCH_STDIN', $StdinPath),
        @('>', '{{PROJECT_NAME_UPPER}}_DISPATCH_STDOUT', $StdoutPath),
        @('2>', '{{PROJECT_NAME_UPPER}}_DISPATCH_STDERR', $StderrPath)
    )
    foreach ($redirect in $redirects) {
        if (-not [string]::IsNullOrEmpty($redirect[2])) {
            $psi.EnvironmentVariables[$redirect[1]] = $redirect[2]
            $line += " $($redirect[0]) `"%$($redirect[1])%`""
            $log.Add("$($redirect[1])=$($redirect[2])")
        }
    }
    $psi.Arguments = '/v:off /s /c "' + $line + '"'
    $log.Insert(0, $psi.Arguments)
    return @{ StartInfo = $psi; Log = ($log -join "`n") }
}

# Read a version child's stdout and stderr under one deadline. Both streams are
# read at the same time, so a full stderr pipe cannot block stdout. A child that
# is still running at the deadline is killed with its whole tree, and $null is
# returned. A grandchild can keep a pipe open after the child exits, so the
# reads are also bounded.
function Read-VersionProcessOutput {
    param(
        [Parameter(Mandatory = $true)][System.Diagnostics.Process]$Process,
        [Parameter(Mandatory = $true)][int]$TimeoutMs
    )
    $outTask = $Process.StandardOutput.ReadToEndAsync()
    $errTask = $Process.StandardError.ReadToEndAsync()
    if (-not $Process.WaitForExit($TimeoutMs)) {
        Stop-DispatchProcessTree -Process $Process
        return $null
    }
    try {
        $null = [System.Threading.Tasks.Task]::WaitAll([System.Threading.Tasks.Task[]]@($outTask, $errTask), 5000)
    } catch {
        [Console]::Error.WriteLine("Version output read failed: $($_.Exception.Message)")
    }
    $out = ''
    $err = ''
    if ($outTask.Status -eq [System.Threading.Tasks.TaskStatus]::RanToCompletion) { $out = $outTask.Result }
    if ($errTask.Status -eq [System.Threading.Tasks.TaskStatus]::RanToCompletion) { $err = $errTask.Result }
    return @{ Out = $out; Err = $err }
}

function Get-ClaudeCliVersionString {
    param([Parameter(Mandatory = $true)][hashtable]$Launch)
    $versionPsi = (New-CmdStartInfo -Command (@($Launch.Command) + @('--version'))).StartInfo
    $versionPsi.RedirectStandardOutput = $true
    $versionPsi.RedirectStandardError = $true
    $versionProc = [System.Diagnostics.Process]::Start($versionPsi)
    try {
        $streams = Read-VersionProcessOutput -Process $versionProc -TimeoutMs 10000
    } finally {
        $versionProc.Dispose()
    }
    if ($null -eq $streams) {
        return 'unknown'
    }
    $combined = ($streams.Out + "`n" + $streams.Err).Trim()
    if ([string]::IsNullOrWhiteSpace($combined)) {
        return 'unknown'
    }
    return ($combined -split "`r?`n" | Where-Object { -not [string]::IsNullOrWhiteSpace($_) } | Select-Object -First 1).Trim()
}

# Kill the whole tree: cmd.exe -> .bat/.cmd -> the CLI. Killing only cmd.exe
# leaves the CLI running.
function Stop-DispatchProcessTree {
    param([Parameter(Mandatory = $true)][System.Diagnostics.Process]$Process)
    $Process.Refresh()
    if ($Process.HasExited) { return }
    try {
        $null = & taskkill.exe /PID $Process.Id /T /F 2>$null
    } catch {
        [Console]::Error.WriteLine("taskkill failed for PID $($Process.Id): $($_.Exception.Message)")
    }
    $Process.Refresh()
    if (-not $Process.HasExited) {
        try {
            $Process.Kill()
        } catch {
            [Console]::Error.WriteLine("Kill failed for PID $($Process.Id): $($_.Exception.Message)")
        }
    }
}

# Read one property of a parsed JSON object, or $null when it is absent.
function Get-JsonProp {
    param($Object, [string]$Name)
    if ($null -eq $Object) { return $null }
    $prop = $Object.PSObject.Properties[$Name]
    if ($null -eq $prop) { return $null }
    return $prop.Value
}

# Every path argument is checked once, before any use. The characters below
# are illegal in a Windows path under both PowerShell editions; GetFullPath
# catches the rest, such as a colon after the drive under Windows PowerShell.
# Without this check a bad value became an empty path, which Get-PhysicalPath
# turned into the drive root.
function Assert-PathArgument {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [string]$Value
    )
    if ([string]::IsNullOrEmpty($Value)) { return }
    $valid = $Value.IndexOfAny([char[]]((0..31) + 34, 60, 62, 124)) -lt 0
    if ($valid) {
        try { [void][System.IO.Path]::GetFullPath($Value) } catch { $valid = $false }
    }
    if (-not $valid) { Stop-DispatchArgs "$Name is not a valid path: $Value" }
}

# 1. Parameter validation
if ([string]::IsNullOrEmpty($PromptText) -and [string]::IsNullOrEmpty($PromptFile)) {
    Stop-DispatchArgs "Either -PromptText or -PromptFile must be specified."
}
if (-not [string]::IsNullOrEmpty($PromptText) -and -not [string]::IsNullOrEmpty($PromptFile)) {
    Stop-DispatchArgs "Cannot specify both -PromptText and -PromptFile."
}
Assert-PathArgument -Name 'PromptFile' -Value $PromptFile
Assert-PathArgument -Name 'OutputDir' -Value $OutputDir
Assert-PathArgument -Name 'WorkingDirectory' -Value $WorkingDirectory
Assert-PathArgument -Name 'RepoRoot' -Value $RepoRoot
if ([string]::IsNullOrWhiteSpace($ModelClass)) {
    Stop-DispatchArgs "ModelClass must be specified."
}
if ($PSBoundParameters.ContainsKey('MaxBudgetUsd') -and -not ($MaxBudgetUsd -gt 0)) {
    Stop-DispatchArgs "MaxBudgetUsd must be greater than 0."
}

# Continuation switches (resume / fork). The argument checks that need no
# source run directory run here, before model resolution, so a review class
# with no claude-p binding still gets the named refusal and not a registry error.
$resumeRequested = $PSBoundParameters.ContainsKey('ResumeDispatchId')
$forkRequested = $PSBoundParameters.ContainsKey('ForkDispatchId')
$continuationMode = 'fresh'
$sourceDispatchId = $null
if ($resumeRequested -and $forkRequested) {
    Stop-ContinuationRefused -Name 'resume_fork_exclusive' `
        -Detail 'specify -ResumeDispatchId or -ForkDispatchId, not both'
}
if ($resumeRequested) {
    $continuationMode = 'resume'
    $sourceDispatchId = $ResumeDispatchId
}
elseif ($forkRequested) {
    $continuationMode = 'fork'
    $sourceDispatchId = $ForkDispatchId
}
if ($continuationMode -ne 'fresh' -and $ResumeReviewDenyClasses -contains $ModelClass) {
    Stop-ContinuationRefused -Name 'resume_refused_review_class' `
        -Detail "class '$ModelClass' is a review class; every review round starts fresh"
}

# 2. Model selection through the registry (harness claude-p)
$modelWasGiven = $PSBoundParameters.ContainsKey('Model')
if ($modelWasGiven -and ([string]::IsNullOrEmpty($Model) -or $Model -notmatch '^[a-zA-Z0-9.-]+\z')) {
    Stop-DispatchArgs "Invalid Model format."
}
if ([string]::IsNullOrWhiteSpace($AuthorVendor) -and $env:{{PROJECT_NAME_UPPER}}_AUTHOR_VENDOR) {
    $AuthorVendor = $env:{{PROJECT_NAME_UPPER}}_AUTHOR_VENDOR
}

$registryModulePath = $null
$moduleCandidates = [System.Collections.Generic.List[string]]::new()
# LOCATE_ORDER is exclusive: a configured file or home that is missing must not
# fall through to %USERPROFILE%/.agent. See .agent/INSTANTIATE.md S2. The same
# order as Invoke-CodexDispatch.ps1.
if ($env:AGENT_MODEL_REGISTRY) {
    $override = $env:AGENT_MODEL_REGISTRY
    if ((Test-Path -LiteralPath $override) -and (Get-Item -LiteralPath $override).PSIsContainer) {
        $moduleCandidates.Add((Join-Path $override 'tools/ModelRegistry.psm1'))
    } else {
        $overrideHome = Split-Path -Parent $override
        $moduleCandidates.Add((Join-Path $overrideHome 'tools/ModelRegistry.psm1'))
    }
} elseif ($env:AGENT_MODEL_REGISTRY_HOME) {
    $moduleCandidates.Add((Join-Path $env:AGENT_MODEL_REGISTRY_HOME 'tools/ModelRegistry.psm1'))
} elseif ($env:USERPROFILE) {
    $moduleCandidates.Add((Join-Path $env:USERPROFILE '.agent/tools/ModelRegistry.psm1'))
}
foreach ($candidate in $moduleCandidates) {
    if (Test-Path -LiteralPath $candidate) {
        $registryModulePath = (Resolve-Path -LiteralPath $candidate).Path
        break
    }
}
if (-not $registryModulePath) {
    Stop-DispatchArgs "registry_not_found: no ModelRegistry.psm1 at any S2 location: $($moduleCandidates -join ', ')"
}
Import-Module $registryModulePath -Force -ErrorAction Stop

$resolveArgs = @{
    Class   = $ModelClass
    Harness = 'claude-p'
    Project = $wrapperRepoRoot
}
if (-not [string]::IsNullOrWhiteSpace($AuthorVendor)) {
    $resolveArgs['AuthorVendor'] = $AuthorVendor
}
if ($modelWasGiven) {
    $resolveArgs['Slug'] = $Model
}
if ($ReasoningEffort) {
    $resolveArgs['Effort'] = $ReasoningEffort
}
try {
    $resolved = Resolve-AgentModel @resolveArgs
}
catch {
    # Named registry failures (unknown_class, unknown_slug, ...) are reported as-is.
    Stop-DispatchArgs $_.Exception.Message
}
$Model = $resolved.slug
$ReasoningEffort = $resolved.effort
$effortClamped = [bool]$resolved.effort_clamped
$modelResolution = $resolved.resolution
$registryVersion = $resolved.registry_version
$registrySha256 = $resolved.registry_sha256
$overlaySha256 = $resolved.overlay_sha256
$overlayPath = $resolved.overlay_path

# 3. Paths
if (-not [string]::IsNullOrEmpty($DispatchId)) {
    if ($DispatchId -notmatch $DispatchIdPattern) {
        Stop-DispatchArgs "Invalid DispatchId format."
    }
} else {
    $randomSuffix = Get-Random -Minimum 1000 -Maximum 9999
    $DispatchId = "claude-" + (Get-Date -Format 'yyyyMMddHHmmss') + "-$randomSuffix"
}

if ([System.Management.Automation.WildcardPattern]::ContainsWildcardCharacters($OutputDir)) {
    Stop-DispatchArgs "OutputDir must not contain wildcard characters."
}
$canonicalOutputDir = Get-PhysicalPath $OutputDir
$parentOutputDir = Get-PhysicalPath "{{RECEIPTS_DIR}}"
if (-not ($canonicalOutputDir -eq $parentOutputDir -or $canonicalOutputDir.StartsWith($parentOutputDir + "/", [System.StringComparison]::OrdinalIgnoreCase))) {
    Stop-DispatchArgs "OutputDir must be under {{RECEIPTS_DIR}}"
}

if ([string]::IsNullOrEmpty($WorkingDirectory)) {
    $WorkingDirectory = $wrapperRepoRoot
}
$canonicalWorkDir = Get-PhysicalPath $WorkingDirectory
if (-not (Test-Path -LiteralPath $canonicalWorkDir -PathType Container)) {
    Stop-DispatchArgs "WorkingDirectory does not exist."
}

if ([string]::IsNullOrEmpty($RepoRoot)) {
    $RepoRoot = $wrapperRepoRoot
}
$canonicalRepoRoot = Get-PhysicalPath $RepoRoot
if ([string]::IsNullOrEmpty($canonicalRepoRoot) -or -not (Test-Path -LiteralPath $canonicalRepoRoot -PathType Container)) {
    Stop-DispatchArgs "RepoRoot does not exist."
}

if (-not [string]::IsNullOrEmpty($PromptFile)) {
    $canonicalPromptFile = Get-PhysicalPath $PromptFile
    if (-not (Test-Path -LiteralPath $canonicalPromptFile -PathType Leaf)) {
        Stop-DispatchArgs "PromptFile does not exist."
    }
    $acceptedRoots = @(Get-AcceptedRepoRoots -CanonicalRepoRoot $canonicalRepoRoot)
    $inRepo = Test-UnderAcceptedRoot -Path $canonicalPromptFile -Roots $acceptedRoots
    $inTemp = ($canonicalPromptFile -eq $parentOutputDir -or $canonicalPromptFile.StartsWith($parentOutputDir + "/", [System.StringComparison]::OrdinalIgnoreCase))
    if (-not ($inRepo -or $inTemp)) {
        Stop-DispatchArgs "PromptFile must be under the repository root or one of its worktrees, or {{RECEIPTS_DIR}}."
    }
}

# 4. Continuation source. The source is an earlier run directory in the same
# OutputDir; its status.json supplies the session to continue. Every check
# runs before -ValidateOnly, so a validate-only call proves the source too.
$sourceSessionId = $null
if ($continuationMode -ne 'fresh') {
    if ([string]::IsNullOrEmpty($sourceDispatchId) -or $sourceDispatchId -notmatch $DispatchIdPattern) {
        Stop-ContinuationRefused -Name 'resume_source_invalid' `
            -Detail "source dispatch ID '$sourceDispatchId' is not a valid dispatch ID"
    }
    if ($sourceDispatchId -eq $DispatchId) {
        Stop-ContinuationRefused -Name 'resume_source_is_target' `
            -Detail "source '$sourceDispatchId' is the target run; use a new -DispatchId"
    }
    $sourceRunDir = Get-PhysicalPath ([System.IO.Path]::GetFullPath((Join-Path $canonicalOutputDir $sourceDispatchId)))
    if (-not $sourceRunDir.StartsWith($canonicalOutputDir + "/", [System.StringComparison]::OrdinalIgnoreCase)) {
        Stop-ContinuationRefused -Name 'resume_source_invalid' `
            -Detail "source '$sourceDispatchId' resolves outside OutputDir"
    }
    # A target that names the source directory under another spelling would be
    # deleted by -Force and rewritten, so the source would be lost.
    $targetRunDir = Get-PhysicalPath ([System.IO.Path]::GetFullPath((Join-Path $canonicalOutputDir $DispatchId)))
    if ([string]::Equals((Get-RunDirIdentityKey $targetRunDir), (Get-RunDirIdentityKey $sourceRunDir),
            [System.StringComparison]::Ordinal)) {
        Stop-ContinuationRefused -Name 'resume_source_is_target' `
            -Detail "target '$DispatchId' names the source run directory '$sourceDispatchId'; use a new -DispatchId"
    }
    $sourceStatusPath = Join-Path $sourceRunDir 'status.json'
    if (-not (Test-Path -LiteralPath $sourceStatusPath -PathType Leaf)) {
        Stop-ContinuationRefused -Name 'resume_source_not_found' `
            -Detail "no status.json for source '$sourceDispatchId' at $sourceStatusPath"
    }
    try {
        $sourceStatus = Get-Content -LiteralPath $sourceStatusPath -Raw -Encoding UTF8 |
            ConvertFrom-Json -ErrorAction Stop
    }
    catch {
        Stop-ContinuationRefused -Name 'resume_source_invalid' `
            -Detail "source status.json does not parse: $($_.Exception.Message)"
    }
    if ($null -eq $sourceStatus -or $sourceStatus -isnot [System.Management.Automation.PSCustomObject]) {
        Stop-ContinuationRefused -Name 'resume_source_invalid' `
            -Detail 'source status.json is not a JSON object'
    }
    $sourceClass = Get-JsonProp $sourceStatus 'model_class'
    $sourceKind = Get-JsonProp $sourceStatus 'dispatch_kind'
    $sourceCli = Get-JsonProp $sourceStatus 'cli'
    $sourceSid = Get-JsonProp $sourceStatus 'session_id'
    $sourceWorkDir = Get-JsonProp $sourceStatus 'working_directory'
    # dispatch_kind is 'non-review' for a non-review run and the ledger mode
    # (plan, execution, ...) for a Codex review-loop run. It is checked before
    # the cli, so a Codex review source is refused as a review and not as a
    # CLI mismatch.
    if (($sourceClass -is [string] -and $ResumeReviewDenyClasses -contains $sourceClass) -or
        ($null -ne $sourceKind -and $sourceKind -cne 'non-review')) {
        Stop-ContinuationRefused -Name 'resume_refused_review_class' `
            -Detail "source class '$sourceClass' kind '$sourceKind' is a review session"
    }
    if ($sourceCli -cne 'claude') {
        Stop-ContinuationRefused -Name 'resume_source_cli_mismatch' `
            -Detail "source cli '$sourceCli' is not 'claude'"
    }
    if ($null -eq $sourceSid -or ($sourceSid -is [string] -and $sourceSid.Length -eq 0)) {
        Stop-ContinuationRefused -Name 'resume_source_missing_session_id' `
            -Detail "source '$sourceDispatchId' recorded no session_id"
    }
    if ($sourceSid -isnot [string] -or $sourceSid -notmatch $SessionIdPattern) {
        Stop-ContinuationRefused -Name 'resume_source_invalid_session_id' `
            -Detail "source session_id '$sourceSid' is not a UUID"
    }
    $sourceWorkNorm = if ($sourceWorkDir -is [string]) { $sourceWorkDir.Replace('\', '/').TrimEnd('/') } else { '' }
    $targetWorkNorm = $canonicalWorkDir.Replace('\', '/').TrimEnd('/')
    if (-not [string]::Equals($sourceWorkNorm, $targetWorkNorm, [System.StringComparison]::OrdinalIgnoreCase)) {
        Stop-ContinuationRefused -Name 'resume_source_workdir_mismatch' `
            -Detail "source working_directory '$sourceWorkDir' differs from '$canonicalWorkDir'"
    }
    if ($sourceClass -cne $ModelClass) {
        Stop-ContinuationRefused -Name 'resume_source_class_mismatch' `
            -Detail "source class '$sourceClass' differs from target class '$ModelClass'"
    }
    $sourceSessionId = $sourceSid
}

# -ValidateOnly stops here: every argument, path and source rule above has
# passed, and no directory, executable lookup or process has been touched.
if ($ValidateOnly) {
    [Console]::Out.WriteLine("dispatch_args_ok")
    exit 0
}

# 5. Executable and version. Under Windows PowerShell the .NET path methods
# throw on a value that is not a path (an illegal character, or quotes kept
# around it), and the script would go on with no executable; such a value is
# refused like a missing file, before the run directory exists.
$resolvedExecutable = $null
try {
    $executableIsRooted = [System.IO.Path]::IsPathRooted($ClaudeExecutable)
    if ($executableIsRooted) {
        $resolvedExecutable = Get-PhysicalPath $ClaudeExecutable
        if (-not (Test-Path -LiteralPath $resolvedExecutable -PathType Leaf)) {
            $resolvedExecutable = $null
        }
    } else {
        $cmdObj = @(Get-Command -Name $ClaudeExecutable -CommandType Application, ExternalScript -ErrorAction Stop)[0]
        $resolvedExecutable = $cmdObj.Source
    }
} catch {
    $resolvedExecutable = $null
}
if ([string]::IsNullOrEmpty($resolvedExecutable)) {
    Stop-DispatchArgs "Executable not found: $ClaudeExecutable"
}
if ($executableIsRooted) {
    $ext = [System.IO.Path]::GetExtension($resolvedExecutable)
    if ($ext -notmatch '^\.(exe|cmd|bat|ps1)$') {
        Stop-DispatchArgs "Invalid executable extension: $ext"
    }
}
$launch = Get-LaunchSpec -ResolvedExecutable $resolvedExecutable
$cliVersion = 'unknown'
try {
    $cliVersion = Get-ClaudeCliVersionString -Launch $launch
} catch {
    $cliVersion = 'unknown'
}

if ($TimeoutSec -le 0) {
    $TimeoutSec = Get-DefaultDispatchTimeoutSec -Effort $ReasoningEffort
}

# 6. Run directory
$runDir = [System.IO.Path]::GetFullPath((Join-Path $canonicalOutputDir $DispatchId)).Replace('\', '/')
$physicalRunDir = Get-PhysicalPath $runDir
if (-not $physicalRunDir.StartsWith($canonicalOutputDir + "/", [System.StringComparison]::OrdinalIgnoreCase)) {
    Stop-DispatchArgs "Run directory must remain physically contained under OutputDir."
}
if (Test-Path -LiteralPath $runDir) {
    if ($Force) {
        # Resolve the existing leaf again just before deletion, so a reparse
        # point cannot redirect -Force outside the authorized root.
        $physicalRunDir = Get-PhysicalPath $runDir
        if (-not $physicalRunDir.StartsWith($canonicalOutputDir + "/", [System.StringComparison]::OrdinalIgnoreCase)) {
            Stop-DispatchArgs "Run directory must remain physically contained under OutputDir before deletion."
        }
        Remove-Item -LiteralPath $runDir -Recurse -Force
    } else {
        Stop-DispatchArgs "Collision error: Directory $runDir already exists. Use -Force to overwrite."
    }
}
[System.IO.Directory]::CreateDirectory($runDir) | Out-Null

# The prompt goes in on stdin, never in argv.
$promptTempFile = "$runDir/prompt_temp.txt"
if (-not [string]::IsNullOrEmpty($PromptText)) {
    Write-TextNoBom $promptTempFile $PromptText
} else {
    Copy-Item -LiteralPath $canonicalPromptFile -Destination $promptTempFile -Force
}

# 7. Argv. The session flags follow the Probe Record of
# docs/execution/plans/2026-10-08-cli-dispatch-resume-fork/task.md:
# claude_preassigned_session_id = honored, claude_fork_accepts_session_id = yes,
# and recall = yes for both switches. Never --no-session-persistence: a run it
# touches can never be resumed.
$argsList = @(
    '-p',
    '--output-format', 'json',
    '--model', $Model,
    '--effort', $ReasoningEffort,
    '--permission-mode', $PermissionMode
)
$maxBudgetText = $null
if ($PSBoundParameters.ContainsKey('MaxBudgetUsd')) {
    $maxBudgetText = $MaxBudgetUsd.ToString([System.Globalization.CultureInfo]::InvariantCulture)
    $argsList += @('--max-budget-usd', $maxBudgetText)
}
$preassignedSessionId = $null
switch ($continuationMode) {
    'fresh' {
        $preassignedSessionId = [guid]::NewGuid().ToString()
        $argsList += @('--session-id', $preassignedSessionId)
    }
    'resume' {
        $argsList += @('--resume', $sourceSessionId)
    }
    'fork' {
        $preassignedSessionId = [guid]::NewGuid().ToString()
        $argsList += @('--resume', $sourceSessionId, '--fork-session', '--session-id', $preassignedSessionId)
    }
}
$sanitizedArgs = @($argsList)

# 8. Process execution: stdin from the prompt file, stdout to output.json,
# stderr to stderr.txt, in the working directory.
$outputPath = "$runDir/output.json"
$finalPath = "$runDir/final.md"
$stderrPath = "$runDir/stderr.txt"
$launchCmd = New-CmdStartInfo -Command (@($launch.Command) + $argsList) `
    -StdinPath $promptTempFile -StdoutPath $outputPath -StderrPath $stderrPath
Write-TextNoBom "$runDir/cmd_line.txt" $launchCmd.Log

$start = Get-Date
$startUtc = $start.ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
# A launch that fails stops here: polling a process that never started would
# wait through -TimeoutSec and then report a timeout.
$proc = $null
try {
    $psi = $launchCmd.StartInfo
    $psi.WorkingDirectory = $canonicalWorkDir
    $proc = [System.Diagnostics.Process]::Start($psi)
} catch {
    Remove-Item -LiteralPath $promptTempFile -ErrorAction SilentlyContinue
    Stop-DispatchArgs "claude dispatch failed: launch failed: $($_.Exception.Message)"
}
if ($null -eq $proc) {
    Remove-Item -LiteralPath $promptTempFile -ErrorAction SilentlyContinue
    Stop-DispatchArgs 'claude dispatch failed: launch failed: no process started'
}

$timedOut = $false
$stopwatch = [System.Diagnostics.Stopwatch]::StartNew()
while (-not $proc.HasExited) {
    if ($stopwatch.Elapsed.TotalSeconds -ge $TimeoutSec) {
        $timedOut = $true
        break
    }
    Start-Sleep -Milliseconds 250
    $proc.Refresh()
}
if ($timedOut) {
    Stop-DispatchProcessTree -Process $proc
}
try {
    $null = $proc.WaitForExit(5000)
} catch {
    [Console]::Error.WriteLine("WaitForExit failed: $($_.Exception.Message)")
}
$end = Get-Date
$endUtc = $end.ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
$elapsedMs = [math]::Round(($end - $start).TotalMilliseconds)
$proc.Refresh()
$childExitCode = if ($proc.HasExited) { $proc.ExitCode } else { $null }
Remove-Item -LiteralPath $promptTempFile -ErrorAction SilentlyContinue

# 9. Output. Success = child exit 0, output.json parses to an object, is_error false.
$parsed = $null
$parseError = $null
$rawOutput = ''
if (Test-Path -LiteralPath $outputPath -PathType Leaf) {
    $rawOutput = [System.IO.File]::ReadAllText($outputPath, [System.Text.Encoding]::UTF8)
}
if ([string]::IsNullOrWhiteSpace($rawOutput)) {
    $parseError = 'output.json is empty'
} else {
    try {
        $parsed = $rawOutput | ConvertFrom-Json -ErrorAction Stop
        if ($parsed -isnot [System.Management.Automation.PSCustomObject]) {
            $parsed = $null
            $parseError = 'output.json is not a JSON object'
        }
    } catch {
        $parsed = $null
        $parseError = "output.json does not parse: $($_.Exception.Message)"
    }
}
$isError = Get-JsonProp $parsed 'is_error'
$result = Get-JsonProp $parsed 'result'
if ($result -is [string]) {
    Write-TextNoBom $finalPath $result
}

$outputSessionId = Get-JsonProp $parsed 'session_id'
if ($outputSessionId -is [string] -and $outputSessionId -match $SessionIdPattern) {
    $sessionId = $outputSessionId
    $sessionIdSource = 'cli_output'
} elseif ($null -ne $preassignedSessionId) {
    $sessionId = $preassignedSessionId
    $sessionIdSource = 'preassigned'
} else {
    $sessionId = $null
    $sessionIdSource = 'none'
}

$errorSummary = ''
if ($timedOut) {
    $errorSummary = "timed out after $TimeoutSec s; process tree killed"
} elseif ($childExitCode -ne 0) {
    $errorSummary = "claude exited with code $childExitCode"
} elseif ($null -eq $parsed) {
    $errorSummary = $parseError
} elseif (-not ($isError -is [bool])) {
    $errorSummary = 'output.json has no boolean is_error'
} elseif ($isError) {
    $resultText = if ($result -is [string]) { $result } else { '' }
    if ($resultText.Length -gt 200) { $resultText = $resultText.Substring(0, 200) }
    $errorSummary = "claude reported is_error: $resultText"
}
$wrapperExitCode = if ([string]::IsNullOrEmpty($errorSummary)) { 0 } else { 1 }

# 10. status.json (dispatch-status.v1), written atomically
$wrapperSha256 = Get-Sha256File -Path $PSCommandPath
$statusManifest = [ordered]@{
    schema_version = "dispatch-status.v1"
    dispatch_id = $DispatchId
    model = $Model
    model_class = $ModelClass
    author_vendor = if ([string]::IsNullOrWhiteSpace($AuthorVendor)) { $null } else { $AuthorVendor }
    registry_version = $registryVersion
    registry_sha256 = $registrySha256
    overlay_sha256 = $overlaySha256
    overlay_path = $overlayPath
    resolution = $modelResolution
    # Session record. A later -ResumeDispatchId / -ForkDispatchId reads
    # cli, dispatch_kind, model_class, working_directory and session_id from
    # here. A headless Claude run is never bound to a review loop, so its kind
    # is always 'non-review', the value Invoke-CodexDispatch.ps1 writes for a
    # -NonReviewDispatch run.
    cli = "claude"
    dispatch_kind = "non-review"
    session_id = $sessionId
    session_id_source = $sessionIdSource
    session_mode = $continuationMode
    source_dispatch_id = $sourceDispatchId
    source_session_id = $sourceSessionId
    effort_clamped = $effortClamped
    reasoning_effort = $ReasoningEffort
    permission_mode = $PermissionMode
    max_budget_usd = $maxBudgetText
    output_paths = [ordered]@{
        output = $outputPath
        final_output = $finalPath
        stderr = $stderrPath
    }
    sanitized_argv = $sanitizedArgs
    start_utc = $startUtc
    end_utc = $endUtc
    elapsed_ms = $elapsedMs
    timeout_sec = $TimeoutSec
    timed_out = $timedOut
    cli_version = $cliVersion
    exit_code = $wrapperExitCode
    child_exit_code = $childExitCode
    is_error = if ($isError -is [bool]) { $isError } else { $null }
    error_summary = $errorSummary
    working_directory = $canonicalWorkDir
    wrapper_sha256 = $wrapperSha256
}
$statusFile = "$runDir/status.json"
$statusTmp = "$statusFile.tmp"
Write-TextNoBom $statusTmp ($statusManifest | ConvertTo-Json -Depth 4)
Move-Item -LiteralPath $statusTmp -Destination $statusFile -Force

if ($wrapperExitCode -ne 0) {
    [Console]::Error.WriteLine("claude dispatch failed: $errorSummary")
}
exit $wrapperExitCode
