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

    # Tools the run may use without a permission prompt, passed as
    # `--allowedTools`. A headless run denies every prompt, so a tool such as
    # WebSearch must be listed here. Names or rules, e.g. 'WebSearch','WebFetch'.
    # `pwsh -File` passes 'A,B' as one string, so items are also split on commas.
    [Parameter(Mandatory = $false)]
    [string[]]$AllowedTools,

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

    # The ID of the new session, a lowercase UUID. Omitted: a random UUID.
    # Refused with -ResumeDispatchId, which keeps the source session's ID.
    [Parameter(Mandatory = $false)]
    [string]$SessionId,

    # What the run is for, recorded as status.json `kind`. Omitted: null.
    [Parameter(Mandatory = $false)]
    [ValidateSet('plan', 'exec')]
    [string]$Kind,

    # Check the arguments, the paths and a continuation source, print
    # `dispatch_args_ok` and exit 0 without creating a directory or starting a process.
    [Parameter(Mandatory = $false)]
    [switch]$ValidateOnly,

    [Parameter(Mandatory = $false)]
    [string]$ClaudeExecutable = 'claude',

    # A file whose first non-empty line is a Claude Console API key. The key goes
    # to the child only, as ANTHROPIC_API_KEY, so the run bills that Console org
    # instead of the inherited login. It is never logged or written to a run file.
    # Omitted: the child inherits the caller's auth.
    [Parameter(Mandatory = $false)]
    [string]$ApiKeyFile,

    # With -ValidateOnly only: check that -ApiKeyFile exists, opens for read and
    # sits outside a git work tree, but do not read its contents. The credits
    # front end passes it (its -ValidateOnly checks presence and ACL only).
    [Parameter(Mandatory = $false)]
    [switch]$KeyFileMetadataOnly,

    # Starts the CLI in place of Process.Start. It gets the final start info
    # (after the CREDITS_* names are removed) and returns the started Process.
    # The credits wrapper uses it to create the child suspended inside a job.
    [Parameter(Mandatory = $false)]
    [scriptblock]$LaunchHook
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
# -SessionId: the lowercase RFC 4122 form only. Match it with -cmatch.
$NewSessionIdPattern = '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\z'
# Creation times in running.json. RFC 3339 allows a space in place of the `T`;
# with the space, pwsh 7 ConvertFrom-Json keeps the value a string and does not
# turn it into a DateTime that a later string cast shifts or truncates.
$CreationTimeFormat = "yyyy-MM-dd HH:mm:ss.fffffff'Z'"

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
    # A dispatched child is not the human's session: its stops never send email.
    $psi.EnvironmentVariables['AGENT_NOTIFY'] = 'off'
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

# A cost value from parsed JSON as a double, or $null when it is not a number.
function ConvertTo-CostOrNull {
    param($Value)
    if ($Value -is [double] -or $Value -is [single] -or $Value -is [decimal] -or
        $Value -is [int] -or $Value -is [long]) {
        return [double]$Value
    }
    return $null
}

# The UTC creation time of a process in $CreationTimeFormat, or $null when the
# process is gone or cannot be read.
function Get-ProcessCreationUtc {
    param([Parameter(Mandatory = $true)][int]$ProcessId)
    try {
        $p = Get-Process -Id $ProcessId -ErrorAction Stop
        return $p.StartTime.ToUniversalTime().ToString($CreationTimeFormat, [System.Globalization.CultureInfo]::InvariantCulture)
    } catch {
        return $null
    }
}

# The Windows boot counter (BootId). It changes at every boot, so a process id
# recorded in an earlier boot is never read as live. $null when it cannot be read.
function Get-BootId {
    $key = 'HKLM:\SYSTEM\CurrentControlSet\Control\Session Manager\Memory Management\PrefetchParameters'
    try {
        $value = (Get-ItemProperty -LiteralPath $key -Name BootId -ErrorAction Stop).BootId
        if ($null -eq $value) { return $null }
        return "bootid:$value"
    } catch {
        return $null
    }
}

# The CLI process that cmd.exe started: its first child that is not conhost.exe.
# Waits up to $WaitMs for it. $null when cmd.exe exits first or none appears.
function Find-CliProcess {
    param(
        [Parameter(Mandatory = $true)][System.Diagnostics.Process]$Launcher,
        [int]$WaitMs = 10000
    )
    $watch = [System.Diagnostics.Stopwatch]::StartNew()
    while ($watch.ElapsedMilliseconds -lt $WaitMs) {
        $children = @()
        try {
            $children = @(Get-CimInstance -ClassName Win32_Process -Filter "ParentProcessId = $($Launcher.Id)" -ErrorAction Stop |
                Where-Object { $_.Name -ne 'conhost.exe' } | Sort-Object CreationDate)
        } catch {
            [Console]::Error.WriteLine("claude dispatch: child process query failed: $($_.Exception.Message)")
        }
        if ($children.Count -gt 0) {
            $childId = [int]$children[0].ProcessId
            $created = Get-ProcessCreationUtc -ProcessId $childId
            if ($null -ne $created) {
                return [pscustomobject]@{ ProcessId = $childId; CreationUtc = $created }
            }
        }
        if ($Launcher.HasExited) { break }
        Start-Sleep -Milliseconds 100
    }
    return $null
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
Assert-PathArgument -Name 'ApiKeyFile' -Value $ApiKeyFile
if ($KeyFileMetadataOnly -and -not $ValidateOnly) {
    Stop-DispatchArgs "key_file_metadata_only_needs_validate_only: -KeyFileMetadataOnly is used only with -ValidateOnly."
}
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
$requestedSessionId = $null
if ($PSBoundParameters.ContainsKey('SessionId')) {
    if ([string]::IsNullOrEmpty($SessionId) -or $SessionId -cnotmatch $NewSessionIdPattern) {
        Stop-DispatchArgs "session_id_invalid: -SessionId must be a lowercase UUID"
    }
    if ($continuationMode -eq 'resume') {
        Stop-ContinuationRefused -Name 'session_id_with_resume' `
            -Detail 'a resumed session keeps the source session ID; omit -SessionId'
    }
    $requestedSessionId = $SessionId
}
$kindValue = if ($PSBoundParameters.ContainsKey('Kind')) { $Kind } else { $null }

# 2. Model selection through the registry (harness claude-p)
$modelWasGiven = $PSBoundParameters.ContainsKey('Model')
if ($modelWasGiven -and ([string]::IsNullOrEmpty($Model) -or $Model -notmatch '^[a-zA-Z0-9.-]+\z')) {
    Stop-DispatchArgs "Invalid Model format."
}
# GetEnvironmentVariable, not $env:, so the template file parses before the name is substituted.
$envAuthorVendor = [Environment]::GetEnvironmentVariable('{{PROJECT_NAME_UPPER}}_AUTHOR_VENDOR')
if ([string]::IsNullOrWhiteSpace($AuthorVendor) -and $envAuthorVendor) {
    $AuthorVendor = $envAuthorVendor
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

# 4b. API key file. Checked before -ValidateOnly; the key is never printed.
$apiKey = $null
$authMode = 'inherited'
$allowedToolList = @($AllowedTools | ForEach-Object { "$_" -split ',' } |
    ForEach-Object { $_.Trim() } | Where-Object { $_ })
foreach ($tool in $allowedToolList) {
    if ($tool -notmatch '^[A-Za-z][A-Za-z0-9_]*(\([^()\r\n]*\))?$') {
        Stop-DispatchArgs "allowed_tools_invalid: '$tool' is not a tool name or rule"
    }
}

$canonicalKeyFile = $null
if (-not [string]::IsNullOrEmpty($ApiKeyFile)) {
    $canonicalKeyFile = Get-PhysicalPath $ApiKeyFile
    if (-not (Test-Path -LiteralPath $canonicalKeyFile -PathType Leaf)) {
        Stop-DispatchArgs "api_key_file_not_found: $ApiKeyFile"
    }
    if ($KeyFileMetadataOnly) {
        # Presence and ACL only: open for read and close at once. The contents are
        # not read; the launch that follows checks them.
        try {
            [System.IO.File]::Open($canonicalKeyFile, 'Open', 'Read', 'ReadWrite').Dispose()
        } catch {
            Stop-DispatchArgs "api_key_file_unreadable: $ApiKeyFile ($($_.Exception.GetType().Name))"
        }
    } else {
        $keyLines = @(Get-Content -LiteralPath $canonicalKeyFile -Encoding UTF8 |
            Where-Object { -not [string]::IsNullOrWhiteSpace($_) } | Select-Object -First 1)
        $apiKey = if ($keyLines.Count -gt 0) { ([string]$keyLines[0]).Trim() } else { '' }
        # Console API keys: sk-ant-api03-... and the newer sk-ant-usr-... Subscription
        # OAuth tokens (sk-ant-oat/ort) and admin keys are not API keys and are refused.
        if ($apiKey -notmatch '^sk-ant-(api\d{2}|usr)-[A-Za-z0-9_-]{20,}\z') {
            Stop-DispatchArgs "api_key_file_invalid: $ApiKeyFile does not hold a Console API key (sk-ant-api03-.. or sk-ant-usr-..)"
        }
    }
    # A key file inside a work tree is one `git add` away from a commit.
    $keyInRepo = $false
    try {
        $null = & git -C (Split-Path -Parent $canonicalKeyFile) rev-parse --is-inside-work-tree 2>$null
        $keyInRepo = ($LASTEXITCODE -eq 0)
    } catch {
        $keyInRepo = $false
    }
    if ($keyInRepo) {
        Stop-DispatchArgs "api_key_file_in_repo: $ApiKeyFile is inside a git work tree; move it out"
    }
    $authMode = 'api_key_file'
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
if ($allowedToolList.Count -gt 0) {
    $argsList += @('--allowedTools', ($allowedToolList -join ','))
}
$preassignedSessionId = $null
switch ($continuationMode) {
    'fresh' {
        $preassignedSessionId = if ($null -ne $requestedSessionId) { $requestedSessionId } else { [guid]::NewGuid().ToString() }
        $argsList += @('--session-id', $preassignedSessionId)
    }
    'resume' {
        $argsList += @('--resume', $sourceSessionId)
    }
    'fork' {
        $preassignedSessionId = if ($null -ne $requestedSessionId) { $requestedSessionId } else { [guid]::NewGuid().ToString() }
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
$cachingEnvRemoved = @()
$creditsEnvRemoved = @()
try {
    $psi = $launchCmd.StartInfo
    $psi.WorkingDirectory = $canonicalWorkDir
    if ($authMode -eq 'api_key_file') {
        $psi.EnvironmentVariables['ANTHROPIC_API_KEY'] = $apiKey
        # ANTHROPIC_AUTH_TOKEN outranks the API key in the CLI's auth order.
        if ($psi.EnvironmentVariables.ContainsKey('ANTHROPIC_AUTH_TOKEN')) {
            $psi.EnvironmentVariables.Remove('ANTHROPIC_AUTH_TOKEN')
        }
    }
    # DISABLE_PROMPT_CACHING* turns prompt caching off, so every call resends
    # the whole context at the full input price. A long-lived parent (an IDE
    # started before the variable was removed) still carries it; the child
    # never gets it. Names are upper-cased: Windows PowerShell lists them lower.
    foreach ($name in @($psi.EnvironmentVariables.Keys)) {
        if ($name -match '^DISABLE_PROMPT_CACHING') {
            $psi.EnvironmentVariables.Remove($name)
            $cachingEnvRemoved += $name.ToUpperInvariant()
        }
    }
    $cachingEnvRemoved = @($cachingEnvRemoved | Sort-Object -Unique)
    if ($cachingEnvRemoved.Count -gt 0) {
        [Console]::Error.WriteLine("claude dispatch: removed $($cachingEnvRemoved -join ', ') from the child environment; prompt caching stays on")
    }
    # CREDITS_RUN_ID, CREDITS_STATE_DB, CREDITS_SEGMENT and CREDITS_BASE_COMMIT
    # (CREDITS_ENV) name the scheduled credits run that launched this wrapper.
    # The CLI session is not that run, so no CREDITS_* name reaches the child.
    foreach ($name in @($psi.EnvironmentVariables.Keys)) {
        if ($name -match '^CREDITS_') {
            $psi.EnvironmentVariables.Remove($name)
            $creditsEnvRemoved += $name.ToUpperInvariant()
        }
    }
    $creditsEnvRemoved = @($creditsEnvRemoved | Sort-Object -Unique)
    if ($null -ne $LaunchHook) {
        $proc = @(& $LaunchHook $psi) | Where-Object { $_ -is [System.Diagnostics.Process] } | Select-Object -Last 1
    } else {
        $proc = [System.Diagnostics.Process]::Start($psi)
    }
} catch {
    Remove-Item -LiteralPath $promptTempFile -ErrorAction SilentlyContinue
    Stop-DispatchArgs "claude dispatch failed: launch failed: $($_.Exception.Message)"
}
if ($null -eq $proc) {
    Remove-Item -LiteralPath $promptTempFile -ErrorAction SilentlyContinue
    Stop-DispatchArgs 'claude dispatch failed: launch failed: no process started'
}
$apiKey = $null

# running.json marks a live run: status.json is written only at the end, so a
# reader (tools/Get-ClaudeDispatch.ps1) uses this file's pid and session_id to
# tell a running dispatch from a dead one and to find its live transcript.
# A process id alone is not proof of life: Windows reuses ids. The reader
# matches each recorded id with its creation time and the boot it ran in.
# `pid` is cmd.exe; `claude_pid` is the CLI process cmd.exe started, and
# `launcher_pid` is this wrapper, which writes status.json when the CLI ends.
# model_class, kind and permission_mode let a recovered status.json
# (Get-ClaudeDispatch.ps1 -RecoverStatus) be resumed with the same mode.
$liveSessionId = if ($null -ne $preassignedSessionId) { $preassignedSessionId } else { $sourceSessionId }
$cliProcess = Find-CliProcess -Launcher $proc
$runningManifest = [ordered]@{
    schema_version = "dispatch-running.v1"
    dispatch_id = $DispatchId
    pid = $proc.Id
    claude_pid = if ($null -ne $cliProcess) { $cliProcess.ProcessId } else { $null }
    claude_creation_utc = if ($null -ne $cliProcess) { $cliProcess.CreationUtc } else { $null }
    launcher_pid = $PID
    launcher_creation_utc = Get-ProcessCreationUtc -ProcessId $PID
    boot_id = Get-BootId
    session_id = $liveSessionId
    session_mode = $continuationMode
    source_dispatch_id = $sourceDispatchId
    model = $Model
    model_class = $ModelClass
    kind = $kindValue
    permission_mode = $PermissionMode
    auth_mode = $authMode
    start_utc = $startUtc
    working_directory = $canonicalWorkDir
    prompt_caching_env_removed = $cachingEnvRemoved
    credits_env_removed = $creditsEnvRemoved
}
Write-TextNoBom "$runDir/running.json" ($runningManifest | ConvertTo-Json -Depth 2)

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
    # Promotional / monthly API credits cover `claude -p` run by the human, not
    # runs launched from a Claude Code session (billed as Claude Code).
    if ($authMode -eq 'api_key_file' -and $resultText -match 'credit balance' -and $env:CLAUDE_CODE_ENTRYPOINT) {
        $errorSummary += " (launched from a Claude Code session, entrypoint '$($env:CLAUDE_CODE_ENTRYPOINT)'," +
            " which bills as Claude Code; API credits do not cover it. Run the dispatch from a terminal.)"
    }
}
$wrapperExitCode = if ([string]::IsNullOrEmpty($errorSummary)) { 0 } else { 1 }

# total_cost_usd from the CLI is the running total of the whole session, not of
# this run. The segment's own cost is that total minus the session's total at
# the end of the run this one continues: 0 for a fresh session, the source's
# total for a resume. A fork has no measured baseline (no probe shows whether
# its total carries the source's), so its delta stays unknown. A total that is
# zero, missing or not above the baseline cannot be a real segment cost; the
# delta is then null and cost_untrusted is true.
$previousSessionTotal = $null
switch ($continuationMode) {
    'fresh' { $previousSessionTotal = 0.0 }
    'resume' {
        $previousSessionTotal = ConvertTo-CostOrNull (Get-JsonProp $sourceStatus 'session_total_usd')
        if ($null -eq $previousSessionTotal) {
            $previousSessionTotal = ConvertTo-CostOrNull (Get-JsonProp $sourceStatus 'total_cost_usd')
        }
    }
}
$sessionTotalUsd = ConvertTo-CostOrNull (Get-JsonProp $parsed 'total_cost_usd')
$segmentDeltaUsd = $null
if ($null -ne $sessionTotalUsd -and $null -ne $previousSessionTotal -and
    $sessionTotalUsd -gt 0 -and $sessionTotalUsd -gt $previousSessionTotal) {
    $segmentDeltaUsd = [math]::Round($sessionTotalUsd - $previousSessionTotal, 10)
}

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
    # here. A headless Claude run is never bound to a review loop, so its
    # dispatch_kind is always 'non-review', the value Invoke-CodexDispatch.ps1
    # writes for a -NonReviewDispatch run. kind is what the run is for.
    cli = "claude"
    dispatch_kind = "non-review"
    kind = $kindValue
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
    # Billing record. auth_mode is 'api_key_file' or 'inherited'; the key
    # itself is never written. launch_entrypoint is the caller's
    # CLAUDE_CODE_ENTRYPOINT (null outside a Claude Code session).
    auth_mode = $authMode
    api_key_file = $canonicalKeyFile
    launch_entrypoint = if ($env:CLAUDE_CODE_ENTRYPOINT) { $env:CLAUDE_CODE_ENTRYPOINT } else { $null }
    total_cost_usd = Get-JsonProp $parsed 'total_cost_usd'
    session_total_usd = $sessionTotalUsd
    segment_delta_usd = $segmentDeltaUsd
    cost_untrusted = ($null -eq $segmentDeltaUsd)
    # DISABLE_PROMPT_CACHING* variables kept out of the child (empty: none set).
    prompt_caching_env_removed = $cachingEnvRemoved
    # CREDITS_* variables kept out of the child (empty: none set).
    credits_env_removed = $creditsEnvRemoved
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
