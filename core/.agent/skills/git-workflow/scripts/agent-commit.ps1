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
.EXAMPLE
    .\agent-commit.ps1 -Message "feat: add new feature"
    .\agent-commit.ps1 -Message "feat: add feature" -Body "Detailed description" -Branch "dev"
    .\agent-commit.ps1 -Message "fix: correct bug" -NoPush
    .\agent-commit.ps1 -Message "wip: save progress" -SkipTests -NoPush
#>
param(
    [string]$Message,

    [string]$Body = "",

    [switch]$NoPush,

    [string]$Branch = "main",

    [switch]$SkipTests,

    [string]$RepositoryPath,

    [string]$ScopeManifest,

    [string]$ExpectedBase,

    [string]$ExpectedTree,

    [string]$ContentDescriptor,

    [string]$MessageFile,

    [string]$OutputState
)

$ErrorActionPreference = "Stop"

function Invoke-RtkGitExact {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Repo,
        [Parameter(Mandatory = $true)]
        [string[]]$Arguments
    )

    $output = @(& rtk proxy git -C $Repo @Arguments)
    $code = $LASTEXITCODE
    if ($code -ne 0) {
        throw "git command failed with exit code $code`: git $($Arguments -join ' ')"
    }
    return (($output | ForEach-Object { [string]$_ }) -join "`n").Trim()
}

function Invoke-ExactScopeCommit {
    $required = @{
        RepositoryPath = $RepositoryPath
        ScopeManifest = $ScopeManifest
        ExpectedBase = $ExpectedBase
        ExpectedTree = $ExpectedTree
        ContentDescriptor = $ContentDescriptor
        MessageFile = $MessageFile
        OutputState = $OutputState
    }
    foreach ($entry in $required.GetEnumerator()) {
        if ([string]::IsNullOrWhiteSpace([string]$entry.Value)) {
            throw "Exact-scope mode requires -$($entry.Key)"
        }
    }
    if (-not $NoPush) {
        throw "Exact-scope mode requires -NoPush; pushing is a separate approved checkpoint"
    }

    $repo = (Resolve-Path -LiteralPath $RepositoryPath).Path
    $manifestPath = (Resolve-Path -LiteralPath $ScopeManifest).Path
    $descriptorPath = (Resolve-Path -LiteralPath $ContentDescriptor).Path
    $messagePath = (Resolve-Path -LiteralPath $MessageFile).Path
    $currentBase = Invoke-RtkGitExact -Repo $repo -Arguments @("rev-parse", "HEAD")
    if ($currentBase -ne $ExpectedBase) {
        throw "Exact-scope base drift: expected $ExpectedBase, got $currentBase"
    }

    $scope = @()
    $seen = @{}
    foreach ($raw in Get-Content -LiteralPath $manifestPath) {
        $path = $raw.Trim()
        if (-not $path -or $path.StartsWith("#")) { continue }
        if ([IO.Path]::IsPathRooted($path) -or $path.Contains("\") -or $path -match '(^|/)\.\.(/|$)') {
            throw "Unsafe exact-scope manifest path: $path"
        }
        $folded = $path.ToLowerInvariant()
        if ($seen.ContainsKey($folded)) {
            throw "Duplicate exact-scope manifest path: $path"
        }
        $seen[$folded] = $true
        $fullPath = Join-Path $repo $path
        if (-not (Test-Path -LiteralPath $fullPath -PathType Leaf)) {
            throw "Exact-scope file is missing: $path"
        }
        $scope += $path
    }
    if ($scope.Count -eq 0) {
        throw "Exact-scope manifest is empty"
    }

    $descriptor = Get-Content -LiteralPath $descriptorPath -Raw | ConvertFrom-Json
    foreach ($property in @("parent", "tree", "message_sha256", "author_name", "author_email", "signing_fingerprint")) {
        if ($null -eq $descriptor.$property -or [string]::IsNullOrWhiteSpace([string]$descriptor.$property)) {
            throw "Content descriptor is missing $property"
        }
    }
    if ($descriptor.parent -ne $ExpectedBase -or $descriptor.tree -ne $ExpectedTree) {
        throw "Content descriptor parent/tree does not match approved values"
    }
    $messageHash = (Get-FileHash -LiteralPath $messagePath -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($descriptor.message_sha256 -ne $messageHash) {
        throw "Message file hash does not match content descriptor"
    }

    $signingEnabled = Invoke-RtkGitExact -Repo $repo -Arguments @("config", "--get", "commit.gpgsign")
    $signingFormat = Invoke-RtkGitExact -Repo $repo -Arguments @("config", "--get", "gpg.format")
    $signingKey = Invoke-RtkGitExact -Repo $repo -Arguments @("config", "--get", "user.signingkey")
    if ($signingEnabled -ne "true" -or $signingFormat -ne "ssh" -or -not (Test-Path -LiteralPath $signingKey)) {
        throw "Exact-scope mode requires a usable local SSH commit-signing configuration"
    }
    $publicKey = if (Test-Path -LiteralPath "$signingKey.pub") { "$signingKey.pub" } else { $signingKey }
    $fingerprintOutput = @(& rtk proxy ssh-keygen -lf $publicKey -E sha256)
    $fingerprintCode = $LASTEXITCODE
    if ($fingerprintCode -ne 0) {
        throw "Unable to derive SSH signing fingerprint"
    }
    $fingerprint = ([string]($fingerprintOutput | Select-Object -First 1) -split '\s+' | Where-Object { $_ -like 'SHA256:*' } | Select-Object -First 1)
    if ($fingerprint -ne $descriptor.signing_fingerprint) {
        throw "SSH signing fingerprint does not match content descriptor"
    }
    $gitDirectoryValue = Invoke-RtkGitExact -Repo $repo -Arguments @("rev-parse", "--git-dir")
    $gitDirectory = if ([IO.Path]::IsPathRooted($gitDirectoryValue)) {
        $gitDirectoryValue
    }
    else {
        Join-Path $repo $gitDirectoryValue
    }
    $allowedSigners = Join-Path $gitDirectory "{{PROJECT_NAME}}-allowed-signers"
    $publicKeyText = (Get-Content -LiteralPath $publicKey -Raw).Trim()
    Set-Content -LiteralPath $allowedSigners -Value "$($descriptor.author_email) $publicKeyText" -Encoding utf8
    $null = Invoke-RtkGitExact -Repo $repo -Arguments @("config", "gpg.ssh.allowedSignersFile", $allowedSigners)

    $temporaryIndex = Join-Path ([IO.Path]::GetTempPath()) ("{{PROJECT_NAME}}-exact-index-" + [guid]::NewGuid().ToString("N"))
    $previousIndex = $env:GIT_INDEX_FILE
    try {
        $env:GIT_INDEX_FILE = $temporaryIndex
        $null = Invoke-RtkGitExact -Repo $repo -Arguments @("read-tree", $ExpectedBase)
        $null = Invoke-RtkGitExact -Repo $repo -Arguments (@("add", "--") + $scope)
        $tree = Invoke-RtkGitExact -Repo $repo -Arguments @("write-tree")
        if ($tree -ne $ExpectedTree) {
            throw "Exact-scope tree drift: expected $ExpectedTree, got $tree"
        }

        $previousAuthorName = $env:GIT_AUTHOR_NAME
        $previousAuthorEmail = $env:GIT_AUTHOR_EMAIL
        $previousCommitterName = $env:GIT_COMMITTER_NAME
        $previousCommitterEmail = $env:GIT_COMMITTER_EMAIL
        $previousAuthorDate = $env:GIT_AUTHOR_DATE
        $previousCommitterDate = $env:GIT_COMMITTER_DATE
        try {
            $env:GIT_AUTHOR_NAME = [string]$descriptor.author_name
            $env:GIT_AUTHOR_EMAIL = [string]$descriptor.author_email
            $env:GIT_COMMITTER_NAME = [string]$descriptor.author_name
            $env:GIT_COMMITTER_EMAIL = [string]$descriptor.author_email
            if ($null -ne $descriptor.timestamp -and -not [string]::IsNullOrWhiteSpace([string]$descriptor.timestamp)) {
                $env:GIT_AUTHOR_DATE = [string]$descriptor.timestamp
                $env:GIT_COMMITTER_DATE = [string]$descriptor.timestamp
            }
            $null = Invoke-RtkGitExact -Repo $repo -Arguments @("commit", "-S", "-F", $messagePath)
        }
        finally {
            $env:GIT_AUTHOR_NAME = $previousAuthorName
            $env:GIT_AUTHOR_EMAIL = $previousAuthorEmail
            $env:GIT_COMMITTER_NAME = $previousCommitterName
            $env:GIT_COMMITTER_EMAIL = $previousCommitterEmail
            $env:GIT_AUTHOR_DATE = $previousAuthorDate
            $env:GIT_COMMITTER_DATE = $previousCommitterDate
        }
        $actualSha = Invoke-RtkGitExact -Repo $repo -Arguments @("rev-parse", "HEAD")
        $actualParent = Invoke-RtkGitExact -Repo $repo -Arguments @("rev-parse", "HEAD^")
        $actualTree = Invoke-RtkGitExact -Repo $repo -Arguments @("show", "-s", "--format=%T", "HEAD")
        if ($actualParent -ne $ExpectedBase -or $actualTree -ne $ExpectedTree) {
            throw "Signed commit parent/tree does not match approved content"
        }
        $null = Invoke-RtkGitExact -Repo $repo -Arguments @("verify-commit", $actualSha)
    }
    finally {
        if ($null -eq $previousIndex) { Remove-Item Env:GIT_INDEX_FILE -ErrorAction SilentlyContinue }
        else { $env:GIT_INDEX_FILE = $previousIndex }
        if (Test-Path -LiteralPath $temporaryIndex) {
            Remove-Item -LiteralPath $temporaryIndex -Force
        }
    }

    # Bring only the committed scope entries in the caller's index to the new HEAD.
    # Any unrelated staged entries remain byte-for-byte staged.
    $null = Invoke-RtkGitExact -Repo $repo -Arguments (@("reset", "--quiet", "HEAD", "--") + $scope)

    $state = [ordered]@{
        schema_version = 1
        actual_sha = $actualSha
        parent = $actualParent
        tree = $actualTree
        signature_verified = $true
        content_descriptor_sha256 = (Get-FileHash -LiteralPath $descriptorPath -Algorithm SHA256).Hash.ToLowerInvariant()
        scope = $scope
    }
    $state | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $OutputState -Encoding utf8
    Write-Host "Exact-scope signed commit verified: $actualSha"
}

if ($RepositoryPath -or $ScopeManifest -or $ExpectedBase -or $ExpectedTree -or $ContentDescriptor -or $MessageFile -or $OutputState) {
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
    Write-Host "  WARNING: Remote uses HTTPS ($remoteUrl) — push may prompt for credentials." -ForegroundColor DarkYellow
}
else {
    Write-Host "  Remote: OK ($remoteUrl)" -ForegroundColor Green
}

# ── Step 3: Staging changes ─────────────────────────────────────────────
Write-Host "[3/7] Staging changes..." -ForegroundColor Yellow

git add -A
$status = git status --short
if (-not $status) {
    Write-Host "  Nothing to commit — working tree clean." -ForegroundColor DarkYellow
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
        $null = uv run python tools/export_openapi.py -o openapi.committed.json 2>&1
        $specDiff = git diff --name-only openapi.committed.json 2>$null
        if ($specDiff) {
            Write-Host "  OpenAPI spec was stale — auto-regenerated and staged." -ForegroundColor DarkYellow
            git add openapi.committed.json
        }
        else {
            Write-Host "  OpenAPI spec: up to date" -ForegroundColor Green
        }
    }
    else {
        Write-Host "  OpenAPI export tool not found — skipped" -ForegroundColor DarkYellow
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
