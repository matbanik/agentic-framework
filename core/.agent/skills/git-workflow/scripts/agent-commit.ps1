#!/usr/bin/env pwsh
<#
.SYNOPSIS
    Agent-safe git commit and push. Validates signing config, runs tests, stages, commits, pushes.
.DESCRIPTION
    This script wraps the git commit workflow to prevent agent hangs from GPG/editor prompts.
    It validates SSH signing config before committing, runs lint + tests, and provides clear error messages.
.PARAMETER Message
    The commit message (required). Use conventional commits format.
.PARAMETER Body
    Optional commit body for multi-line messages.
.PARAMETER NoPush
    Skip pushing to origin after commit. Default: push enabled.
.PARAMETER Branch
    Branch to push to. Default: main.
.PARAMETER SkipTests
    Skip the lint + test gate (for WIP commits). Default: false.
.PARAMETER RepositoryPath
    Exact-scope mode: the repository of the granted op. The op id is in
    {{PROJECT_NAME_UPPER}}_COMMIT_GRANT; tools/commit_batch.py runs the op's phases, so this
    script never commits on its own authority.
.PARAMETER Phase
    Exact-scope mode: candidate, publish or index runs one op phase. Without it the three phases
    run in order and stop at the first that does not succeed.
.PARAMETER ScopeManifest
    Exact-scope mode: the op's paths, one per line; they must equal the op's packet paths.
.PARAMETER ExpectedBase
    Exact-scope mode: the op's parent commit.
.PARAMETER ExpectedTree
    Exact-scope mode: the op's tree.
.PARAMETER ContentDescriptor
    Exact-scope mode: JSON with parent, tree, message_sha256, author and signing fingerprint.
.PARAMETER MessageFile
    Exact-scope mode: the op's commit message.
.PARAMETER OutputState
    Exact-scope mode: where the published commit's state JSON is written.
.EXAMPLE
    .\agent-commit.ps1 -Message "feat: add new feature"
    .\agent-commit.ps1 -Message "feat: add feature" -Body "Detailed description" -Branch "dev"
    .\agent-commit.ps1 -Message "fix: correct bug" -NoPush
    .\agent-commit.ps1 -Message "wip: save progress" -SkipTests -NoPush
    $env:{{PROJECT_NAME_UPPER}}_COMMIT_GRANT = "op-1"; .\agent-commit.ps1 -RepositoryPath . -NoPush
#>
param(
    [string]$Message,

    [string]$Body = "",

    [switch]$NoPush,

    [string]$Branch = "main",

    [switch]$SkipTests,

    [string]$RepositoryPath,

    [string]$Phase,

    [string]$ScopeManifest,

    [string]$ExpectedBase,

    [string]$ExpectedTree,

    [string]$ContentDescriptor,

    [string]$MessageFile,

    [string]$OutputState
)

$ErrorActionPreference = "Stop"

function Write-ExactResult {
    param([System.Collections.IDictionary]$Result)
    Write-Output ($Result | ConvertTo-Json -Compress)
}

function Get-ProjectEnv {
    # The adopter's project prefix names these variables; reading them by name keeps the
    # lookup valid before and after the template's {{PROJECT_NAME_UPPER}} is filled.
    param([string]$Suffix)
    return [Environment]::GetEnvironmentVariable("{{PROJECT_NAME_UPPER}}_$Suffix")
}

# The tree's gate lease: the executor lease's protocol (tools/executor_worktree.py).
# <git dir>/{{PROJECT_NAME}}-gate.lock holds one byte locked at offset 2**20 while held,
# and a JSON body carrying a 32-hex token; the children get that token in
# {{PROJECT_NAME_UPPER}}_GATE_LEASE_TOKEN. The file is never deleted: a contender could
# lock the unlinked file while a third process created and locked a new one.
$LeaseLockOffset = 1048576
$script:LeaseStream = $null
$script:LeaseTokenBefore = $null

function Enter-GateLease {
    # Takes the lease, or runs nested when the holder's body token is the inherited one;
    # refuses lease_held otherwise. It writes nothing to the pipeline but a refusal.
    param([string]$FirstPhase)
    if (-not $IsWindows -and $PSVersionTable.PSEdition -eq "Core") {
        # .NET's byte-range lock on Unix is an fcntl record lock, which does not exclude the
        # flock(1) holders of the same lease; agent-commit.sh takes the lease with flock.
        [Console]::Error.WriteLine("ERROR: the gate lease needs Windows here; run agent-commit.sh on this OS.")
        Write-ExactResult ([ordered]@{ result = "refused"; reason = "lease_unsupported"; phase = $FirstPhase })
        exit 1
    }
    $gitDir = @(& git -C $RepositoryPath rev-parse --absolute-git-dir 2>$null)
    if ($LASTEXITCODE -ne 0 -or $gitDir.Count -ne 1 -or [string]::IsNullOrWhiteSpace($gitDir[0])) {
        [Console]::Error.WriteLine("ERROR: not a git repository: $RepositoryPath")
        Write-ExactResult ([ordered]@{ result = "usage"; reason = "repository"; phase = $FirstPhase })
        exit 2
    }
    $leasePath = Join-Path ([string]$gitDir[0]) "{{PROJECT_NAME}}-gate.lock"
    $inherited = Get-ProjectEnv "GATE_LEASE_TOKEN"
    $stream = [System.IO.File]::Open($leasePath, [System.IO.FileMode]::OpenOrCreate,
        [System.IO.FileAccess]::ReadWrite, [System.IO.FileShare]::ReadWrite)
    try {
        $stream.Lock($LeaseLockOffset, 1)
    } catch [System.IO.IOException] {
        # Held by another handle. Its body lies outside the locked byte, so it reads.
        $held = ""
        try {
            $buffer = New-Object byte[] 4096
            $stream.Position = 0
            $count = $stream.Read($buffer, 0, $buffer.Length)
            $held = [System.Text.Encoding]::UTF8.GetString($buffer, 0, $count)
        } finally {
            $stream.Dispose()
        }
        $match = [regex]::Match($held, '"token"\s*:\s*"([0-9a-f]{32})"')
        if ($inherited -and $match.Success -and $match.Groups[1].Value -ceq $inherited) {
            return
        }
        [Console]::Error.WriteLine("ERROR: the gate lease $leasePath is held by another run.")
        Write-ExactResult ([ordered]@{ result = "refused"; reason = "lease_held"; phase = $FirstPhase })
        exit 1
    }
    $script:LeaseStream = $stream
    $random = New-Object byte[] 16
    [System.Security.Cryptography.RandomNumberGenerator]::Fill($random)
    $token = -join ($random | ForEach-Object { $_.ToString("x2") })
    # The body is written after the lock and never decides who holds the lease.
    $body = [ordered]@{
        schema = 1
        pid = $PID
        argv = @("agent-commit.ps1")
        started_utc = [DateTime]::UtcNow.ToString("yyyy-MM-ddTHH:mm:ss+00:00")
        token = $token
    }
    $bytes = [System.Text.Encoding]::UTF8.GetBytes(($body | ConvertTo-Json -Compress) + "`n")
    $stream.SetLength(0)
    $stream.Position = 0
    $stream.Write($bytes, 0, $bytes.Length)
    $stream.Flush()
    $script:LeaseTokenBefore = Get-ProjectEnv "GATE_LEASE_TOKEN"
    [Environment]::SetEnvironmentVariable("{{PROJECT_NAME_UPPER}}_GATE_LEASE_TOKEN", $token)
}

function Exit-GateLease {
    # Truncate the body, unlock, close, and restore the inherited token. Only a lease this
    # run took is released.
    if ($null -eq $script:LeaseStream) { return }
    $stream = $script:LeaseStream
    $script:LeaseStream = $null
    try {
        $stream.SetLength(0)
        $stream.Unlock($LeaseLockOffset, 1)
    } finally {
        $stream.Dispose()
        [Environment]::SetEnvironmentVariable("{{PROJECT_NAME_UPPER}}_GATE_LEASE_TOKEN", $script:LeaseTokenBefore)
    }
}

function Invoke-ExactScopeCommit {
    # tools/commit_batch.py is the authority: this script passes it the granted op and the exact
    # parameters, one phase at a time, under the tree's gate lease, and prints its JSON
    # (R§4.5, EA-8 (j), EA-10). agent-commit.sh's exact_scope_commit is the same contract.
    $allPhases = @("candidate", "publish", "index")
    if ($Phase -and $allPhases -notcontains $Phase) {
        Write-ExactResult ([ordered]@{ result = "usage"; reason = "phase"; phase = $Phase })
        exit 2
    }
    $phases = if ($Phase) { @($Phase) } else { $allPhases }
    if (-not $NoPush) {
        [Console]::Error.WriteLine("ERROR: exact-scope mode requires -NoPush; pushing is a separate approved checkpoint.")
        Write-ExactResult ([ordered]@{ result = "refused"; reason = "push"; phase = $phases[0] })
        exit 1
    }
    if ([string]::IsNullOrWhiteSpace((Get-ProjectEnv "COMMIT_GRANT"))) {
        Write-ExactResult ([ordered]@{ result = "refused"; reason = "grant"; phase = $phases[0] })
        exit 1
    }

    $pythonOverride = Get-ProjectEnv "PYTHON"
    $python = @(if ($pythonOverride) { $pythonOverride } else { "uv", "run", "python" })
    $exact = @()
    foreach ($pair in @(
            @("--expect-base", $ExpectedBase),
            @("--expect-tree", $ExpectedTree),
            @("--scope-manifest", $ScopeManifest),
            @("--message-file", $MessageFile),
            @("--descriptor", $ContentDescriptor))) {
        if (-not [string]::IsNullOrWhiteSpace($pair[1])) { $exact += @($pair[0], $pair[1]) }
    }

    $PSNativeCommandUseErrorActionPreference = $false
    Enter-GateLease $phases[0]
    $last = $null
    $failed = 0
    try {
        foreach ($step in $phases) {
            $childArgs = @($python | Select-Object -Skip 1) + @("-m", "tools.commit_batch", "--repo", $RepositoryPath, "--step", $step) + $exact
            $lines = @(& $python[0] @childArgs)
            $code = $LASTEXITCODE
            $last = $null
            foreach ($line in $lines) {
                Write-Output ([string]$line)
                if (([string]$line).TrimStart().StartsWith("{")) {
                    try { $last = ([string]$line) | ConvertFrom-Json } catch { $last = $null }
                }
            }
            if ($code -ne 0) { $failed = $code; break }
        }
    } finally {
        Exit-GateLease
    }
    if ($failed -ne 0) { exit $failed }

    if ($OutputState -and $null -ne $last -and $last.commit) {
        $state = [ordered]@{
            schema_version = 1
            actual_sha = [string]$last.commit
            parent = [string]$last.parent
            tree = [string]$last.tree
            signature_verified = $true
            content_descriptor_sha256 = if ($ContentDescriptor) { (Get-FileHash -LiteralPath $ContentDescriptor -Algorithm SHA256).Hash.ToLowerInvariant() } else { $null }
            scope = @($last.paths)
        }
        $state | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $OutputState -Encoding utf8
    }
}

if ($RepositoryPath -or $Phase -or $ScopeManifest -or $ExpectedBase -or $ExpectedTree -or $ContentDescriptor -or $MessageFile -or $OutputState) {
    Invoke-ExactScopeCommit
    exit 0
}

if ([string]::IsNullOrWhiteSpace($Message)) {
    Write-Host "ERROR: -Message is required in legacy commit mode." -ForegroundColor Red
    exit 1
}

Write-Host "`n=== Agent-Safe Git Commit ===" -ForegroundColor Cyan

$messageText = "$Message`n$Body"
if ($messageText -match "(?i)(co-authored-by:\s*(claude|anthropic)|generated\s+(with|by)\s+(claude|anthropic)|authored\s+(with|by)\s+(claude|anthropic))") {
    Write-Host "ERROR: Commit messages must not include AI co-author or generated-by attribution." -ForegroundColor Red
    Write-Host "Remove trailers such as 'Co-Authored-By: Claude' or 'Generated with Claude'." -ForegroundColor Red
    exit 1
}

# ── Step 1: Validate signing config ──────────────────────────────────────
Write-Host "`n[1/7] Checking signing config..." -ForegroundColor Yellow

$gpgSign = git config --global commit.gpgsign 2>$null
$gpgFormat = git config --global gpg.format 2>$null
$signingKey = git config --global user.signingkey 2>$null

if ($gpgSign -eq "true" -and $gpgFormat -ne "ssh") {
    Write-Host "ERROR: GPG signing is enabled but format is '$gpgFormat' (not 'ssh')." -ForegroundColor Red
    Write-Host "This WILL cause a hang. Fix with:" -ForegroundColor Red
    Write-Host "  git config --global gpg.format ssh" -ForegroundColor White
    Write-Host "  git config --global user.signingkey `"C:/Users/$env:USERNAME/.ssh/id_ed25519_signing.pub`"" -ForegroundColor White
    exit 1
}

if ($gpgSign -eq "true" -and $gpgFormat -eq "ssh") {
    if (-not $signingKey -or -not (Test-Path ($signingKey -replace '^~', $env:USERPROFILE))) {
        Write-Host "ERROR: SSH signing key not found at '$signingKey'." -ForegroundColor Red
        exit 1
    }
    Write-Host "  SSH signing: OK (key: $signingKey)" -ForegroundColor Green
}
else {
    Write-Host "  Signing: disabled (commits will be unsigned)" -ForegroundColor DarkYellow
}

# ── Step 2: Check remote URL ────────────────────────────────────────────
Write-Host "[2/7] Checking remote URL..." -ForegroundColor Yellow

$remoteUrl = git remote get-url origin 2>$null
if ($remoteUrl -match "^https://") {
    Write-Host "  WARNING: Remote uses HTTPS ($remoteUrl) -- push may prompt for credentials." -ForegroundColor DarkYellow
}
else {
    Write-Host "  Remote: OK ($remoteUrl)" -ForegroundColor Green
}

# ── Step 3: Staging changes ─────────────────────────────────────────────
Write-Host "[3/7] Staging changes..." -ForegroundColor Yellow

git add -A
$status = git status --short
if (-not $status) {
    Write-Host "  Nothing to commit -- working tree clean." -ForegroundColor DarkYellow
    exit 0
}
$fileCount = ($status -split "`n").Count
Write-Host "  Staged $fileCount file(s)" -ForegroundColor Green

# ── Step 4: Run lint + tests ────────────────────────────────────────────
if ($SkipTests) {
    Write-Host "[4/7] Lint + tests skipped (-SkipTests)" -ForegroundColor DarkYellow
}
else {
    Write-Host "[4/7] Running lint + tests..." -ForegroundColor Yellow

    # 4a: Ruff lint
    Write-Host "  [4a] Ruff lint..." -ForegroundColor Yellow
    $ruffOutput = uv run ruff check packages/ tests/ 2>&1
    if ($LASTEXITCODE -ne 0) {
        Write-Host "  FAILED: Ruff lint errors found:" -ForegroundColor Red
        Write-Host $ruffOutput -ForegroundColor Red
        Write-Host "`n  Fix with: uv run ruff check packages/ tests/ --fix" -ForegroundColor White
        exit 1
    }
    Write-Host "  Ruff: passed" -ForegroundColor Green

    # 4b: Unit tests
    Write-Host "  [4b] Unit tests..." -ForegroundColor Yellow
    $pytestOutput = uv run pytest tests/unit/ -x --tb=line -q 2>&1
    if ($LASTEXITCODE -ne 0) {
        Write-Host "  FAILED: Unit tests:" -ForegroundColor Red
        Write-Host $pytestOutput -ForegroundColor Red
        exit 1
    }
    Write-Host "  Unit tests: passed" -ForegroundColor Green

    # 4c: OpenAPI spec drift check
    Write-Host "  [4c] OpenAPI spec drift check..." -ForegroundColor Yellow
    if (Test-Path "tools/export_openapi.py") {
        # "Regenerate rather than fail" applies to spec *drift*, not to the regeneration
        # itself. Discarding the exporter's status into $null meant a crashed exporter
        # produced no diff, and no diff was announced as "up to date" -- the strongest
        # available claim, made at the exact moment the check had learned nothing.
        $exportOutput = uv run python tools/export_openapi.py -o openapi.committed.json 2>&1
        if ($LASTEXITCODE -ne 0) {
            Write-Host "  FAILED: OpenAPI export exited $LASTEXITCODE, so spec drift is unknown:" -ForegroundColor Red
            Write-Host $exportOutput -ForegroundColor Red
            if ($LASTEXITCODE -eq 3) { exit 3 }
            exit 1
        }
        $specDiff = git diff --name-only openapi.committed.json 2>&1
        if ($LASTEXITCODE -ne 0) {
            Write-Host "  FAILED: git diff on openapi.committed.json exited $LASTEXITCODE, so drift is unknown:" -ForegroundColor Red
            Write-Host $specDiff -ForegroundColor Red
            exit 1
        }
        if ($specDiff) {
            Write-Host "  OpenAPI spec was stale -- auto-regenerated and staged." -ForegroundColor DarkYellow
            git add openapi.committed.json
        }
        else {
            Write-Host "  OpenAPI spec: up to date" -ForegroundColor Green
        }
    }
    else {
        Write-Host "  OpenAPI export tool not found -- skipped" -ForegroundColor DarkYellow
    }
}
# ── Step 5: Commit ──────────────────────────────────────────────────────
Write-Host "[5/7] Committing..." -ForegroundColor Yellow

if ($Body) {
    git commit -m $Message -m $Body
}
else {
    git commit -m $Message
}

if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: git commit failed with exit code $LASTEXITCODE" -ForegroundColor Red
    exit $LASTEXITCODE
}
Write-Host "  Committed successfully" -ForegroundColor Green

# ── Step 6: Push ────────────────────────────────────────────────────────
if (-not $NoPush) {
    Write-Host "[6/7] Pushing to origin/$Branch..." -ForegroundColor Yellow
    git push origin $Branch
    if ($LASTEXITCODE -ne 0) {
        Write-Host "ERROR: git push failed with exit code $LASTEXITCODE" -ForegroundColor Red
        exit $LASTEXITCODE
    }
    Write-Host "  Pushed successfully" -ForegroundColor Green
}
else {
    Write-Host "[6/7] Push skipped (-NoPush)" -ForegroundColor DarkYellow
}

# ── Step 7: Verify ──────────────────────────────────────────────────────
Write-Host "[7/7] Verifying..." -ForegroundColor Yellow

$lastCommit = git log --oneline -1
Write-Host "  Latest: $lastCommit" -ForegroundColor Green

Write-Host "`n=== Done ===" -ForegroundColor Cyan
