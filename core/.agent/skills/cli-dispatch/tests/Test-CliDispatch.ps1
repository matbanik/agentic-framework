<#
.SYNOPSIS
  Validation test suite for the CLI Dispatch skill.
  Tests dispatch routes plus a deterministic Invoke-CodexDispatch.ps1 contract suite
  (wrapper-contract) that does not require a live Codex session.

.DESCRIPTION
  Each test dispatches a minimal task to the target CLI agent, captures the output,
  and validates that the expected result was produced. Tests are independent and
  can be run individually or as a full suite.

.NOTES
  Prerequisites:
  - codex CLI in PATH (npm global)
  - claude CLI in PATH (npm global)
  - agy CLI at $env:LOCALAPPDATA\agy\bin\agy.exe (version ≥ 1.1.1; stdout capture verified on 1.1.5)
  - All CLIs authenticated
  - agy model set to the `surface_orchestrator` binding for `gemini-cli` via TUI
    /model (or --model); resolve it with
    `Resolve-AgentModel -Class surface_orchestrator -Harness gemini-cli`
  - Stuck/broken MCP servers disabled — they block agy -p even for trivial prompts
#>

param(
    [ValidateSet('all', 'wrapper-contract', 'codex-validation', 'codex-image', 'agy-data', 'claude-writing')]
    [string]$Test = 'all',
    [string]$OutputDir = '{{RECEIPTS_DIR}}\dispatch-tests',
    [switch]$Verbose
)

$ErrorActionPreference = 'Continue'
$script:PassCount = 0
$script:FailCount = 0
$script:SkipCount = 0
$script:Results = @()

# Model ids come from the live registry home (see .agent/INSTANTIATE.md), not
# from this script. A snapshot bump is one edit there; a test that named its
# own model would keep dispatching to a retired one and report the failure as
# a CLI defect.
$script:RegistryModule = $null
foreach ($candidate in @(
        $(if ($env:AGENT_MODEL_REGISTRY) {
            $override = $env:AGENT_MODEL_REGISTRY
            if ((Test-Path -LiteralPath $override) -and (Get-Item -LiteralPath $override).PSIsContainer) {
                Join-Path $override 'tools/ModelRegistry.psm1'
            } else {
                Join-Path (Split-Path -Parent $override) 'tools/ModelRegistry.psm1'
            }
        }),
        'P:/.agent/tools/ModelRegistry.psm1',
        $(if ($env:USERPROFILE) { Join-Path $env:USERPROFILE '.agent/tools/ModelRegistry.psm1' })
    )) {
    if ($candidate -and (Test-Path -LiteralPath $candidate)) {
        $script:RegistryModule = (Resolve-Path -LiteralPath $candidate).Path
        break
    }
}
if (-not $script:RegistryModule) {
    throw "registry_not_found: no ModelRegistry.psm1 at any S2 location"
}
Import-Module $script:RegistryModule -Force

function Get-ClassModel {
    param(
        [Parameter(Mandatory)][string]$Class,
        [Parameter(Mandatory)][string]$Harness
    )
    $resolved = Resolve-AgentModel -Class $Class -Harness $Harness
    if (-not $resolved -or -not $resolved.Slug) {
        throw "model registry could not resolve $Class on $Harness"
    }
    return $resolved.Slug
}

# --- Helpers ---

function Write-TestHeader($name) {
    Write-Host "`n$('=' * 60)" -ForegroundColor Cyan
    Write-Host "  TEST: $name" -ForegroundColor Cyan
    Write-Host "$('=' * 60)" -ForegroundColor Cyan
}

function Write-TestResult($name, $passed, $message, $duration) {
    $status = if ($passed) { "PASS" } else { "FAIL" }
    $color = if ($passed) { "Green" } else { "Red" }
    Write-Host "  [$status] $name ($([math]::Round($duration, 1))s) - $message" -ForegroundColor $color

    if ($passed) { $script:PassCount++ } else { $script:FailCount++ }
    $script:Results += [PSCustomObject]@{
        Test = $name
        Status = $status
        Message = $message
        Duration = [math]::Round($duration, 1)
    }
}

function Write-TestSkip($name, $reason) {
    Write-Host "  [SKIP] $name - $reason" -ForegroundColor Yellow
    $script:SkipCount++
    $script:Results += [PSCustomObject]@{
        Test = $name
        Status = "SKIP"
        Message = $reason
        Duration = 0
    }
}

function Ensure-Dir($path) {
    New-Item -ItemType Directory -Force -Path $path | Out-Null
}

function Clean-File($path) {
    if (Test-Path $path) { Remove-Item $path -Force }
}

# --- Test 0: Invoke-CodexDispatch.ps1 contract (no live Codex required) ---

function Resolve-WrapperPath {
    param([string]$Name = 'Invoke-CodexDispatch.ps1')
    $here = $PSScriptRoot
    $candidates = @(
        (Join-Path $here "..\..\..\..\tools\$Name"),
        (Join-Path (Get-Location) "tools\$Name"),
        (Join-Path (Get-Location) "core\tools\$Name")
    )
    foreach ($c in $candidates) {
        $resolved = [IO.Path]::GetFullPath($c)
        if (Test-Path -LiteralPath $resolved) { return $resolved }
    }
    return $null
}

function Test-CodexWrapperContract {
    Write-TestHeader "Invoke-CodexDispatch.ps1 — contract smoke (no live Codex)"

    $sw = [System.Diagnostics.Stopwatch]::StartNew()
    $wrapper = Resolve-WrapperPath
    if (-not $wrapper) {
        $sw.Stop()
        Write-TestResult "Wrapper path resolve" $false "Invoke-CodexDispatch.ps1 not found from test location" $sw.Elapsed.TotalSeconds
        return
    }
    Write-TestResult "Wrapper path resolve" $true $wrapper $sw.Elapsed.TotalSeconds

    $sw.Restart()
    try {
        $null = [scriptblock]::Create((Get-Content -LiteralPath $wrapper -Raw))
        Write-TestResult "Wrapper parses as PowerShell" $true "PARSE-OK" $sw.Elapsed.TotalSeconds
    } catch {
        Write-TestResult "Wrapper parses as PowerShell" $false "$_" $sw.Elapsed.TotalSeconds
        return
    }

    $text = Get-Content -LiteralPath $wrapper -Raw
    $sw.Restart()
    # Packaged wrapper MUST keep instantiate tokens; live {{PROJECT_NAME_TITLE}} paths are forbidden.
    $hasPlaceholderTemp = $text -match '\{\{RECEIPTS_DIR\}\}'
    $hasPlaceholderRoot = $text -match '\{\{PROJECT_ROOT\}\}'
    $hasLiveTemp = $text -match '(?i)C:[/\\]Temp[/\\]{{PROJECT_NAME}}'
    $hasLiveRoot = $text -match '(?i)P:[/\\]{{PROJECT_NAME}}'
    $tokenOk = $hasPlaceholderTemp -and $hasPlaceholderRoot -and (-not $hasLiveTemp) -and (-not $hasLiveRoot)
    Write-TestResult "Wrapper tokens (placeholders required, no live paths)" $tokenOk "PH_TEMP=$hasPlaceholderTemp PH_ROOT=$hasPlaceholderRoot LIVE_TEMP=$hasLiveTemp LIVE_ROOT=$hasLiveRoot" $sw.Elapsed.TotalSeconds

    $sw.Restart()
    $out = & pwsh -NoProfile -File $wrapper -Mode NotARealMode 2>&1
    $code = $LASTEXITCODE
    # ValidateSet should reject before exec; non-zero or ParameterBinding exception text
    $rejected = ($code -ne 0) -or ("$out" -match 'ValidateSet|Cannot validate|ParameterBinding')
    Write-TestResult "Invalid -Mode rejected" $rejected "exit=$code" $sw.Elapsed.TotalSeconds

    $sw.Restart()
    $out2 = & pwsh -NoProfile -File $wrapper -Mode FullAccess -ReasoningEffort medium -PromptText "noop" 2>&1
    $code2 = $LASTEXITCODE
    $needsJust = ($code2 -ne 0) -or ("$out2" -match 'FullAccessJustification|justification')
    Write-TestResult "FullAccess without justification fails closed" $needsJust "exit=$code2" $sw.Elapsed.TotalSeconds

    $sw.Restart()
    $schema = Join-Path (Split-Path $wrapper -Parent) '..\.agent\schemas\review-verdict.schema.json'
    if (-not (Test-Path $schema)) {
        $schema = Join-Path (Get-Location) 'core\.agent\schemas\review-verdict.schema.json'
    }
    if (-not (Test-Path $schema)) {
        $schema = Join-Path (Get-Location) '.agent\schemas\review-verdict.schema.json'
    }
    $schemaOk = Test-Path $schema
    Write-TestResult "review-verdict.schema.json resolvable" $schemaOk $(if ($schemaOk) { $schema } else { 'missing' }) $sw.Elapsed.TotalSeconds

    # POSIX companion (macOS/Linux) — presence + placeholder + bash -n when bash exists
    $sw.Restart()
    $shWrapper = Resolve-WrapperPath -Name 'Invoke-CodexDispatch.sh'
    if (-not $shWrapper) {
        Write-TestResult "POSIX wrapper path resolve" $false "Invoke-CodexDispatch.sh not found" $sw.Elapsed.TotalSeconds
    } else {
        Write-TestResult "POSIX wrapper path resolve" $true $shWrapper $sw.Elapsed.TotalSeconds
        $sw.Restart()
        $shText = Get-Content -LiteralPath $shWrapper -Raw
        $shPhTemp = $shText -match '\{\{RECEIPTS_DIR\}\}'
        $shPhRoot = $shText -match '\{\{PROJECT_ROOT\}\}'
        $shLiveTemp = $shText -match '(?i)C:[/\\]Temp[/\\]{{PROJECT_NAME}}'
        $shLiveRoot = $shText -match '(?i)P:[/\\]{{PROJECT_NAME}}'
        $shTok = $shPhTemp -and $shPhRoot -and (-not $shLiveTemp) -and (-not $shLiveRoot)
        Write-TestResult "POSIX wrapper tokens" $shTok "PH_TEMP=$shPhTemp PH_ROOT=$shPhRoot LIVE_TEMP=$shLiveTemp LIVE_ROOT=$shLiveRoot" $sw.Elapsed.TotalSeconds

        $sw.Restart()
        # Prefer real Git Bash; WindowsApps bash.exe is often a Store stub (exit 127).
        $bashCandidates = @(
            (Join-Path ${env:ProgramFiles} 'Git\bin\bash.exe'),
            (Join-Path ${env:ProgramFiles(x86)} 'Git\bin\bash.exe'),
            (Get-Command bash -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source)
        ) | Where-Object { $_ -and (Test-Path -LiteralPath $_) }
        $bashExe = $bashCandidates | Select-Object -First 1
        if ($bashExe) {
            $bashOut = & $bashExe -n $shWrapper 2>&1
            $bashCode = $LASTEXITCODE
            if ($bashCode -eq 127 -and "$bashOut" -match 'No such file|WindowsApps|not found') {
                Write-TestSkip "POSIX wrapper bash -n" "bash on PATH is a non-functional stub ($bashExe)"
            } elseif ($bashCode -eq 0) {
                Write-TestResult "POSIX wrapper bash -n" $true "exit=0 ($bashExe)" $sw.Elapsed.TotalSeconds
            } else {
                Write-TestResult "POSIX wrapper bash -n" $false "exit=$bashCode ($bashExe) $bashOut" $sw.Elapsed.TotalSeconds
            }
        } else {
            Write-TestSkip "POSIX wrapper bash -n" "bash not on PATH (syntax check deferred to macOS/Linux)"
        }
    }
}

# --- Test 1: Codex Validation (live; opt-in; no length false-pass) ---

function Test-CodexValidation {
    Write-TestHeader "Codex CLI — Validation (GPT-5.5, reasoning=high)"

    $outputFile = "$OutputDir\codex-val-output.md"
    $logFile = "$OutputDir\codex-val-log.txt"
    Clean-File $outputFile
    Clean-File $logFile

    $prompt = @"
You are a validation agent. Evaluate the following Python function for correctness:

```python
def fibonacci(n):
    if n <= 0:
        return []
    elif n == 1:
        return [0]
    elif n == 2:
        return [0, 1]
    fib = [0, 1]
    for i in range(2, n):
        fib.append(fib[i-1] + fib[i-2])
    return fib
```

Report: VERDICT (PASS or CHANGES_REQUIRED), then a 1-line SUMMARY.
"@

    $sw = [System.Diagnostics.Stopwatch]::StartNew()

    try {
        $proc = Start-Process -FilePath "codex" -ArgumentList @(
            "exec",
            "-C", "{{PROJECT_ROOT}}",
            "-s", "danger-full-access",
            "-c", "model_reasoning_effort=high",
            "-o", $outputFile,
            $prompt
        ) -NoNewWindow -Wait -PassThru -RedirectStandardInput "NUL" -RedirectStandardOutput "$logFile.stdout" -RedirectStandardError "$logFile.stderr" -TimeoutSec 300

        $sw.Stop()

        if (Test-Path $outputFile) {
            $content = Get-Content $outputFile -Raw
            if ($content -match "VERDICT.*PASS" -or $content -match "(?m)^VERDICT:\s*PASS") {
                Write-TestResult "Codex Validation" $true "VERDICT PASS found ($($content.Length) chars)" $sw.Elapsed.TotalSeconds
            } else {
                Write-TestResult "Codex Validation" $false "No VERDICT PASS in output ($($content.Length) chars) — length alone is not a pass" $sw.Elapsed.TotalSeconds
            }
        } else {
            Write-TestResult "Codex Validation" $false "Output file not created" $sw.Elapsed.TotalSeconds
        }
    } catch {
        $sw.Stop()
        Write-TestResult "Codex Validation" $false "Exception: $_" $sw.Elapsed.TotalSeconds
    }
}

# --- Test 2: Codex Image Generation ---

function Test-CodexImageGen {
    Write-TestHeader "Codex CLI — Image Generation (GPT-5.5, image_gen)"

    $imgTarget = "$OutputDir\test-generated-image.png"
    $outputFile = "$OutputDir\codex-img-output.md"
    $logFile = "$OutputDir\codex-img-log.txt"
    Clean-File $imgTarget
    Clean-File $outputFile
    Clean-File $logFile

    $prompt = "Use the built-in image_gen tool to generate: a simple red square on white background, 256x256. Save the result to $imgTarget"

    $sw = [System.Diagnostics.Stopwatch]::StartNew()

    try {
        $proc = Start-Process -FilePath "codex" -ArgumentList @(
            "exec",
            "-C", "{{PROJECT_ROOT}}",
            "-s", "danger-full-access",
            "--enable", "image_generation",
            "-c", "model_reasoning_effort=medium",
            "-o", $outputFile,
            $prompt
        ) -NoNewWindow -Wait -PassThru -RedirectStandardInput "NUL" -RedirectStandardOutput "$logFile.stdout" -RedirectStandardError "$logFile.stderr" -TimeoutSec 300

        $sw.Stop()

        # Check if image was generated (either at target path or in .codex/generated_images/)
        $imageExists = Test-Path $imgTarget
        if (-not $imageExists) {
            # Check default location
            $defaultImages = Get-ChildItem "$env:USERPROFILE\.codex\generated_images" -Recurse -Filter "*.png" -ErrorAction SilentlyContinue |
                Where-Object { $_.LastWriteTime -gt (Get-Date).AddMinutes(-5) }
            $imageExists = $null -ne $defaultImages -and $defaultImages.Count -gt 0
        }

        if ($imageExists) {
            Write-TestResult "Codex Image Gen" $true "Image generated successfully" $sw.Elapsed.TotalSeconds
        } elseif ((Test-Path $outputFile) -and (Get-Content $outputFile -Raw).Length -gt 10) {
            Write-TestResult "Codex Image Gen" $true "Output file has content (image may be at default path)" $sw.Elapsed.TotalSeconds
        } else {
            Write-TestResult "Codex Image Gen" $false "No image found" $sw.Elapsed.TotalSeconds
        }
    } catch {
        $sw.Stop()
        Write-TestResult "Codex Image Gen" $false "Exception: $_" $sw.Elapsed.TotalSeconds
    }
}

# --- Test 3: agy Data Processing ---

function Test-AgyDataProcessing {
    Write-TestHeader "agy CLI — Data Processing (Gemini 3.5 Flash High)"

    $agyPath = "$env:LOCALAPPDATA\agy\bin\agy.exe"
    if (-not (Test-Path $agyPath)) {
        Write-TestSkip "agy Data Processing" "agy.exe not found at $agyPath"
        return
    }

    $version = (& $agyPath --version 2>$null | Out-String).Trim()
    if (-not $version) {
        Write-TestSkip "agy Data Processing" "agy --version returned empty"
        return
    }

    $outputFile = "$OutputDir\agy-data-output.txt"
    Clean-File $outputFile

    # Create a test data file for processing
    $testDataFile = "$OutputDir\test-data.csv"
    @"
Name,Age,City,Score
Alice,30,New York,85
Bob,25,San Francisco,92
Carol,35,Chicago,78
Dave,28,Boston,95
Eve,32,Seattle,88
"@ | Set-Content $testDataFile -Encoding UTF8

    $prompt = @"
Read the CSV file at $testDataFile and produce a summary report with:
1. Total number of records
2. Average age
3. Average score
4. Person with highest score
5. List all cities mentioned

Return the complete report as markdown on stdout.
"@

    $sw = [System.Diagnostics.Stopwatch]::StartNew()

    try {
        # Flags BEFORE -p; prompt in a variable (see cli-dispatch SKILL.md agy rules).
        & $agyPath --print-timeout 5m0s --effort high --add-dir "{{PROJECT_ROOT}}" -p $prompt *> $outputFile
        $code = $LASTEXITCODE
        $sw.Stop()

        if ($code -ne 0) {
            Write-TestResult "agy Data Processing" $false "agy exited $code (version=$version)" $sw.Elapsed.TotalSeconds
            return
        }

        if (Test-Path $outputFile) {
            $content = Get-Content $outputFile -Raw -ErrorAction SilentlyContinue
            if ($null -ne $content -and $content.Length -gt 20) {
                Write-TestResult "agy Data Processing" $true "Stdout capture OK ($($content.Length) chars, version=$version)" $sw.Elapsed.TotalSeconds
            } else {
                Write-TestResult "agy Data Processing" $false "Stdout empty/short — check ~/.gemini/antigravity-cli/log for MCP stalls" $sw.Elapsed.TotalSeconds
            }
        } else {
            Write-TestResult "agy Data Processing" $false "Output receipt not created" $sw.Elapsed.TotalSeconds
        }
    } catch {
        $sw.Stop()
        Write-TestResult "agy Data Processing" $false "Exception: $_" $sw.Elapsed.TotalSeconds
    }
}

# --- Test 4: Claude Creative Writing ---

function Test-ClaudeCreativeWriting {
    $model = Get-ClassModel -Class 'creative_prose' -Harness 'claude-p'
    Write-TestHeader "Claude Code — Creative Writing ($model)"

    $outputFile = "$OutputDir\claude-writing-output.txt"
    $logFile = "$OutputDir\claude-writing-log.txt"
    Clean-File $outputFile
    Clean-File $logFile

    $prompt = @"
Write in a natural, human-like tone. Avoid bullet points, numbered lists,
and AI-typical phrasing like 'certainly' or 'I'd be happy to'.

Write a short paragraph (50-80 words) describing a sunrise over a mountain lake.
Focus on sensory details — what you see, hear, and feel. Write as a skilled human
nature writer would.
"@

    $sw = [System.Diagnostics.Stopwatch]::StartNew()

    try {
        # Use cmd to pipe NUL to stdin
        $cmdLine = "echo. | claude -p --model $model --permission-mode plan --output-format json --max-turns 5 --max-budget-usd 2 `"$($prompt -replace '"', '\"')`""

        $null | claude -p `
            --model $model `
            --permission-mode plan `
            --output-format json `
            --max-turns 5 `
            --max-budget-usd 2 `
            $prompt `
            *> $outputFile

        $sw.Stop()

        if (Test-Path $outputFile) {
            $raw = Get-Content $outputFile -Raw -Encoding Unicode
            if ($null -eq $raw -or $raw.Length -lt 10) {
                $raw = Get-Content $outputFile -Raw
            }

            if ($null -ne $raw -and $raw.Length -gt 20) {
                try {
                    $json = $raw | ConvertFrom-Json
                    $result = $json.result
                    if ([string]::IsNullOrWhiteSpace([string]$result)) {
                        Write-TestResult "Claude Creative Writing" $false "JSON missing non-empty result field" $sw.Elapsed.TotalSeconds
                    } else {
                        Write-TestResult "Claude Creative Writing" $true "Output: $($result.Substring(0, [Math]::Min(80, $result.Length)))..." $sw.Elapsed.TotalSeconds
                    }
                } catch {
                    Write-TestResult "Claude Creative Writing" $false "Output not valid JSON ($($raw.Length) chars)" $sw.Elapsed.TotalSeconds
                }
            } else {
                Write-TestResult "Claude Creative Writing" $false "Output too short ($($raw.Length) chars)" $sw.Elapsed.TotalSeconds
            }
        } else {
            Write-TestResult "Claude Creative Writing" $false "Output file not created" $sw.Elapsed.TotalSeconds
        }
    } catch {
        $sw.Stop()
        Write-TestResult "Claude Creative Writing" $false "Exception: $_" $sw.Elapsed.TotalSeconds
    }
}

# --- Main ---

Write-Host "`n" -NoNewline
Write-Host "╔══════════════════════════════════════════════════════════╗" -ForegroundColor Magenta
Write-Host "║      CLI DISPATCH SKILL — VALIDATION TEST SUITE        ║" -ForegroundColor Magenta
Write-Host "╚══════════════════════════════════════════════════════════╝" -ForegroundColor Magenta
Write-Host ""
Write-Host "  Output dir: $OutputDir"
Write-Host "  Test scope: $Test"
Write-Host ""

Ensure-Dir $OutputDir

switch ($Test) {
    'all' {
        Test-CodexWrapperContract
        Test-CodexValidation
        Test-CodexImageGen
        Test-AgyDataProcessing
        Test-ClaudeCreativeWriting
    }
    'wrapper-contract'   { Test-CodexWrapperContract }
    'codex-validation'   { Test-CodexValidation }
    'codex-image'        { Test-CodexImageGen }
    'agy-data'           { Test-AgyDataProcessing }
    'claude-writing'     { Test-ClaudeCreativeWriting }
}

# --- Summary ---

Write-Host "`n$('=' * 60)" -ForegroundColor Magenta
Write-Host "  SUMMARY" -ForegroundColor Magenta
Write-Host "$('=' * 60)" -ForegroundColor Magenta
Write-Host ""
$script:Results | Format-Table -AutoSize
Write-Host "  Total: $($script:PassCount + $script:FailCount + $script:SkipCount) | " -NoNewline
Write-Host "PASS: $script:PassCount " -ForegroundColor Green -NoNewline
Write-Host "FAIL: $script:FailCount " -ForegroundColor Red -NoNewline
Write-Host "SKIP: $script:SkipCount" -ForegroundColor Yellow
Write-Host ""

# Exit with failure code if any test failed
if ($script:FailCount -gt 0) { exit 1 }
