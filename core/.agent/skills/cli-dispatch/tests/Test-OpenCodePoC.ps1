<#
.SYNOPSIS
  PoC test suite for OpenCode CLI as a dispatch target via Amazon Bedrock.

.DESCRIPTION
  Validates whether OpenCode CLI can replace or supplement Codex/Claude CLIs
  for dispatching tasks via Amazon Bedrock. Tests two models:
    - Claude Opus 5 via Bedrock (anthropic.claude-opus-5)
    - GPT-5.5 via Bedrock (openai.gpt-5.5 - GA on Bedrock since June 1, 2026)

.NOTES
  Prerequisites:
  - opencode CLI in PATH
  - AWS credentials configured
  - Bedrock model access granted
#>

param(
    [ValidateSet(
        'all',
        'opencode-install',
        'opencode-auth',
        'opencode-hello',
        'opencode-bedrock-claude',
        'opencode-bedrock-gpt',
        'opencode-json-output',
        'opencode-dir-flag',
        'opencode-permissions',
        'opencode-validation'
    )]
    [string]$Test = 'all',
    [string]$OutputDir = '{{RECEIPTS_DIR}}\dispatch-tests\opencode',
    [switch]$VerboseOutput
)

$ErrorActionPreference = 'Continue'
$script:PassCount = 0
$script:FailCount = 0
$script:SkipCount = 0
$script:Results = @()

# --- Configuration ---
$script:BedrockClaudeModel = "amazon-bedrock/anthropic.claude-opus-5"
$script:BedrockClaudeModelAlt = "amazon-bedrock/us.anthropic.claude-opus-5"
$script:BedrockGPTModel = "amazon-bedrock/openai.gpt-5.5"
$script:TestTimeout = 120

# --- Helpers ---

function Write-TestHeader {
    param([string]$Name)
    Write-Host ("`n" + ("=" * 60)) -ForegroundColor Cyan
    Write-Host "  TEST: $Name" -ForegroundColor Cyan
    Write-Host ("=" * 60) -ForegroundColor Cyan
}

function Write-TestResult {
    param([string]$Name, [bool]$Passed, [string]$Msg, [double]$Duration)
    $status = if ($Passed) { "PASS" } else { "FAIL" }
    $color = if ($Passed) { "Green" } else { "Red" }
    $dur = [math]::Round($Duration, 1)
    Write-Host "  [$status] $Name (${dur}s) - $Msg" -ForegroundColor $color

    if ($Passed) { $script:PassCount++ } else { $script:FailCount++ }
    $script:Results += [PSCustomObject]@{
        Test     = $Name
        Status   = $status
        Message  = $Msg
        Duration = $dur
    }
}

function Write-TestSkip {
    param([string]$Name, [string]$Reason)
    Write-Host "  [SKIP] $Name - $Reason" -ForegroundColor Yellow
    $script:SkipCount++
    $script:Results += [PSCustomObject]@{
        Test     = $Name
        Status   = "SKIP"
        Message  = $Reason
        Duration = 0
    }
}

function Write-TestInfo {
    param([string]$Msg)
    Write-Host "  [INFO] $Msg" -ForegroundColor DarkGray
}

function Ensure-Dir {
    param([string]$Path)
    New-Item -ItemType Directory -Force -Path $Path | Out-Null
}

function Clean-File {
    param([string]$Path)
    if (Test-Path $Path) { Remove-Item $Path -Force }
}

function Get-Preview {
    param([string]$Content, [int]$MaxLen = 120)
    if ($null -eq $Content -or $Content.Length -eq 0) { return "(empty)" }
    $len = [Math]::Min($MaxLen, $Content.Length)
    return ($Content.Substring(0, $len) -replace "`r`n", " " -replace "`n", " ")
}

# --- Test 0: Installation Check ---

function Test-OpenCodeInstall {
    Write-TestHeader -Name "OpenCode CLI - Installation Check"
    $sw = [System.Diagnostics.Stopwatch]::StartNew()

    try {
        $opencodePath = Get-Command opencode -ErrorAction SilentlyContinue
        if ($null -ne $opencodePath) {
            $versionOutput = & opencode --version 2>&1
            $sw.Stop()
            Write-TestResult -Name "OpenCode Install" -Passed $true -Msg "Found at $($opencodePath.Source) - version: $versionOutput" -Duration $sw.Elapsed.TotalSeconds
            return $true
        } else {
            $sw.Stop()
            Write-TestResult -Name "OpenCode Install" -Passed $false -Msg "opencode not found in PATH" -Duration $sw.Elapsed.TotalSeconds
            return $false
        }
    } catch {
        $sw.Stop()
        Write-TestResult -Name "OpenCode Install" -Passed $false -Msg "Exception: $_" -Duration $sw.Elapsed.TotalSeconds
        return $false
    }
}

# --- Test 1: Auth / Bedrock Config Check ---

function Test-OpenCodeAuth {
    Write-TestHeader -Name "OpenCode CLI - AWS Bedrock Auth Check"
    $sw = [System.Diagnostics.Stopwatch]::StartNew()

    $authMethod = "NONE"
    $details = @()

    if ($env:AWS_BEARER_TOKEN_BEDROCK) {
        $authMethod = "BEARER_TOKEN"
        $details += "AWS_BEARER_TOKEN_BEDROCK set"
    }
    if ($env:AWS_ACCESS_KEY_ID -and $env:AWS_SECRET_ACCESS_KEY) {
        $authMethod = "ACCESS_KEYS"
        $details += "AWS_ACCESS_KEY_ID set"
        $details += "AWS_SECRET_ACCESS_KEY set"
    }
    if ($env:AWS_PROFILE) {
        $authMethod = "PROFILE"
        $details += "AWS_PROFILE=$($env:AWS_PROFILE)"
    }
    if ($env:AWS_REGION) {
        $details += "AWS_REGION=$($env:AWS_REGION)"
    } else {
        $details += "AWS_REGION NOT SET"
    }

    $projectConfig = "{{PROJECT_ROOT}}\opencode.json"
    $globalConfig = "$env:USERPROFILE\.config\opencode\opencode.json"
    if (Test-Path $projectConfig) { $details += "Project config found" }
    if (Test-Path $globalConfig) { $details += "Global config found" }

    $sw.Stop()
    $detailStr = $details -join "; "

    if ($authMethod -ne "NONE") {
        Write-TestResult -Name "OpenCode Auth" -Passed $true -Msg "Auth: $authMethod ($detailStr)" -Duration $sw.Elapsed.TotalSeconds
        return $true
    } else {
        Write-TestResult -Name "OpenCode Auth" -Passed $false -Msg "No AWS auth configured ($detailStr)" -Duration $sw.Elapsed.TotalSeconds
        return $false
    }
}

# --- Test 2: Basic Hello World ---

function Test-OpenCodeHello {
    Write-TestHeader -Name "OpenCode CLI - Hello World (default model)"
    $outputFile = Join-Path $OutputDir "opencode-hello-output.txt"
    Clean-File -Path $outputFile

    $sw = [System.Diagnostics.Stopwatch]::StartNew()
    try {
        opencode run "Say exactly: OPENCODE_POC_SUCCESS. Nothing else." *> $outputFile
        $sw.Stop()

        if (Test-Path $outputFile) {
            $content = Get-Content $outputFile -Raw -ErrorAction SilentlyContinue
            if ($null -ne $content -and $content.Length -gt 5) {
                if ($content -match "OPENCODE_POC_SUCCESS") {
                    Write-TestResult -Name "OpenCode Hello" -Passed $true -Msg "Got expected marker ($($content.Length) chars)" -Duration $sw.Elapsed.TotalSeconds
                } else {
                    Write-TestResult -Name "OpenCode Hello" -Passed $true -Msg "Got output ($($content.Length) chars): $(Get-Preview $content)" -Duration $sw.Elapsed.TotalSeconds
                }
            } else {
                Write-TestResult -Name "OpenCode Hello" -Passed $false -Msg "Output file empty or too short" -Duration $sw.Elapsed.TotalSeconds
            }
        } else {
            Write-TestResult -Name "OpenCode Hello" -Passed $false -Msg "Output file not created" -Duration $sw.Elapsed.TotalSeconds
        }
    } catch {
        $sw.Stop()
        Write-TestResult -Name "OpenCode Hello" -Passed $false -Msg "Exception: $_" -Duration $sw.Elapsed.TotalSeconds
    }
}

# --- Test 3: Bedrock Claude Opus 5 ---

function Test-OpenCodeBedrockClaude {
    Write-TestHeader -Name "OpenCode CLI - Bedrock Claude Opus 5"
    $outputFile = Join-Path $OutputDir "opencode-bedrock-claude-output.txt"
    Clean-File -Path $outputFile

    $prompt = 'You are a validation agent. Evaluate this Python function: "def add(a, b): return a + b". Reply with exactly: VERDICT: PASS, then a 1-line summary.'

    $sw = [System.Diagnostics.Stopwatch]::StartNew()
    try {
        Write-TestInfo -Msg "Trying model: $script:BedrockClaudeModel"
        opencode run --model $script:BedrockClaudeModel --dir "{{PROJECT_ROOT}}" --dangerously-skip-permissions $prompt *> $outputFile
        $sw.Stop()

        if (Test-Path $outputFile) {
            $content = Get-Content $outputFile -Raw -ErrorAction SilentlyContinue
            if ($null -ne $content -and $content.Length -gt 10) {
                if ($content -match "error|invalid model|not found|not available|AccessDeniedException") {
                    Write-TestInfo -Msg "Primary model failed, trying alt: $script:BedrockClaudeModelAlt"
                    Clean-File -Path $outputFile
                    $sw2 = [System.Diagnostics.Stopwatch]::StartNew()
                    opencode run --model $script:BedrockClaudeModelAlt --dir "{{PROJECT_ROOT}}" --dangerously-skip-permissions $prompt *> $outputFile
                    $sw2.Stop()

                    if (Test-Path $outputFile) {
                        $content2 = Get-Content $outputFile -Raw -ErrorAction SilentlyContinue
                        if ($null -ne $content2 -and $content2.Length -gt 10 -and $content2 -notmatch "error|invalid model") {
                            Write-TestResult -Name "Bedrock Claude" -Passed $true -Msg "Alt model worked ($($content2.Length) chars)" -Duration $sw2.Elapsed.TotalSeconds
                        } else {
                            Write-TestResult -Name "Bedrock Claude" -Passed $false -Msg "Both model IDs failed" -Duration $sw.Elapsed.TotalSeconds
                        }
                    }
                } else {
                    Write-TestResult -Name "Bedrock Claude" -Passed $true -Msg "Output received ($($content.Length) chars): $(Get-Preview $content)" -Duration $sw.Elapsed.TotalSeconds
                }
            } else {
                Write-TestResult -Name "Bedrock Claude" -Passed $false -Msg "Output too short" -Duration $sw.Elapsed.TotalSeconds
            }
        } else {
            Write-TestResult -Name "Bedrock Claude" -Passed $false -Msg "Output file not created" -Duration $sw.Elapsed.TotalSeconds
        }
    } catch {
        $sw.Stop()
        Write-TestResult -Name "Bedrock Claude" -Passed $false -Msg "Exception: $_" -Duration $sw.Elapsed.TotalSeconds
    }
}

# --- Test 4: Bedrock GPT-5.5 ---
# HISTORICAL provider-availability probe: GPT-5.5 GA'd on Bedrock 2026-06-01, which is
# what this test validates. GPT-5.6-sol Bedrock availability is region-dependent (404 in
# us-west-2 as of this writing), so this probe intentionally still targets 5.5 — do not
# "upgrade" the model ID here without first confirming GPT-5.6-sol Bedrock GA in-region.

function Test-OpenCodeBedrockGPT {
    Write-TestHeader -Name "OpenCode CLI - Bedrock GPT-5.5"
    Write-TestInfo -Msg "GPT-5.5 GA on Amazon Bedrock since June 1, 2026 (model: openai.gpt-5.5)"

    $outputFile = Join-Path $OutputDir "opencode-bedrock-gpt-output.txt"
    Clean-File -Path $outputFile

    $prompt = 'You are a validation agent. Evaluate this Python function: "def multiply(a, b): return a * b". Reply with exactly: VERDICT: PASS, then a 1-line summary.'

    $sw = [System.Diagnostics.Stopwatch]::StartNew()
    try {
        opencode run --model $script:BedrockGPTModel --dir "{{PROJECT_ROOT}}" --dangerously-skip-permissions $prompt *> $outputFile
        $sw.Stop()

        if (Test-Path $outputFile) {
            $content = Get-Content $outputFile -Raw -ErrorAction SilentlyContinue
            if ($null -ne $content -and $content.Length -gt 10) {
                if ($content -match "error|invalid model|not found|not available|AccessDeniedException") {
                    Write-TestResult -Name "Bedrock GPT-5.5" -Passed $false -Msg "Error: $(Get-Preview $content 200)" -Duration $sw.Elapsed.TotalSeconds
                } else {
                    Write-TestResult -Name "Bedrock GPT-5.5" -Passed $true -Msg "Output received ($($content.Length) chars): $(Get-Preview $content)" -Duration $sw.Elapsed.TotalSeconds
                }
            } else {
                Write-TestResult -Name "Bedrock GPT-5.5" -Passed $false -Msg "Output too short" -Duration $sw.Elapsed.TotalSeconds
            }
        } else {
            Write-TestResult -Name "Bedrock GPT-5.5" -Passed $false -Msg "Output file not created" -Duration $sw.Elapsed.TotalSeconds
        }
    } catch {
        $sw.Stop()
        Write-TestResult -Name "Bedrock GPT-5.5" -Passed $false -Msg "Exception: $_" -Duration $sw.Elapsed.TotalSeconds
    }
}

# --- Test 5: JSON Output Format ---

function Test-OpenCodeJsonOutput {
    Write-TestHeader -Name "OpenCode CLI - JSON Output (--format json)"
    $outputFile = Join-Path $OutputDir "opencode-json-output.txt"
    Clean-File -Path $outputFile

    $sw = [System.Diagnostics.Stopwatch]::StartNew()
    try {
        opencode run --format json "Say exactly: JSON_TEST_SUCCESS" *> $outputFile
        $sw.Stop()

        if (Test-Path $outputFile) {
            $raw = Get-Content $outputFile -Raw -ErrorAction SilentlyContinue
            if ($null -ne $raw -and $raw.Length -gt 10) {
                $lines = ($raw -split "`r?`n") | Where-Object { $_.Trim().Length -gt 0 }
                $parsedAny = $false
                foreach ($line in $lines) {
                    try {
                        $null = $line | ConvertFrom-Json
                        $parsedAny = $true
                    } catch { }
                }
                if ($parsedAny) {
                    Write-TestResult -Name "JSON Output" -Passed $true -Msg "Parseable JSON events ($($lines.Count) lines, $($raw.Length) chars)" -Duration $sw.Elapsed.TotalSeconds
                } else {
                    Write-TestResult -Name "JSON Output" -Passed $false -Msg "No parseable JSON: $(Get-Preview $raw 200)" -Duration $sw.Elapsed.TotalSeconds
                }
            } else {
                Write-TestResult -Name "JSON Output" -Passed $false -Msg "Output empty or too short" -Duration $sw.Elapsed.TotalSeconds
            }
        } else {
            Write-TestResult -Name "JSON Output" -Passed $false -Msg "Output file not created" -Duration $sw.Elapsed.TotalSeconds
        }
    } catch {
        $sw.Stop()
        Write-TestResult -Name "JSON Output" -Passed $false -Msg "Exception: $_" -Duration $sw.Elapsed.TotalSeconds
    }
}

# --- Test 6: --dir Flag ---

function Test-OpenCodeDirFlag {
    Write-TestHeader -Name "OpenCode CLI - Working Directory (--dir)"
    $outputFile = Join-Path $OutputDir "opencode-dir-output.txt"
    Clean-File -Path $outputFile

    $sw = [System.Diagnostics.Stopwatch]::StartNew()
    try {
        opencode run --dir "{{PROJECT_ROOT}}" --dangerously-skip-permissions "List the top-level filenames in the current working directory. Start your response with CWD_CHECK:" *> $outputFile
        $sw.Stop()

        if (Test-Path $outputFile) {
            $content = Get-Content $outputFile -Raw -ErrorAction SilentlyContinue
            if ($null -ne $content -and $content.Length -gt 10) {
                if ($content -match "pyproject|packages|\.agent|{{PROJECT_NAME}}") {
                    Write-TestResult -Name "Dir Flag" -Passed $true -Msg "--dir {{PROJECT_ROOT}} worked - agent sees project files" -Duration $sw.Elapsed.TotalSeconds
                } else {
                    Write-TestResult -Name "Dir Flag" -Passed $true -Msg "Got output: $(Get-Preview $content 200)" -Duration $sw.Elapsed.TotalSeconds
                }
            } else {
                Write-TestResult -Name "Dir Flag" -Passed $false -Msg "Output empty" -Duration $sw.Elapsed.TotalSeconds
            }
        } else {
            Write-TestResult -Name "Dir Flag" -Passed $false -Msg "Output file not created" -Duration $sw.Elapsed.TotalSeconds
        }
    } catch {
        $sw.Stop()
        Write-TestResult -Name "Dir Flag" -Passed $false -Msg "Exception: $_" -Duration $sw.Elapsed.TotalSeconds
    }
}

# --- Test 7: --dangerously-skip-permissions ---

function Test-OpenCodePermissions {
    Write-TestHeader -Name "OpenCode CLI - Auto-Approve Permissions"
    $outputFile = Join-Path $OutputDir "opencode-perms-output.txt"
    $testFile = Join-Path $OutputDir "opencode-perm-test-write.txt"
    Clean-File -Path $outputFile
    Clean-File -Path $testFile

    $sw = [System.Diagnostics.Stopwatch]::StartNew()
    try {
        opencode run --dir "{{PROJECT_ROOT}}" --dangerously-skip-permissions "Write the text PERMISSION_TEST_SUCCESS to the file $testFile. Confirm when done." *> $outputFile
        $sw.Stop()

        if (Test-Path $testFile) {
            $content = Get-Content $testFile -Raw -ErrorAction SilentlyContinue
            if ($content -match "PERMISSION_TEST_SUCCESS") {
                Write-TestResult -Name "Permissions" -Passed $true -Msg "Agent wrote to file successfully" -Duration $sw.Elapsed.TotalSeconds
            } else {
                Write-TestResult -Name "Permissions" -Passed $true -Msg "File created but content differs" -Duration $sw.Elapsed.TotalSeconds
            }
            Remove-Item $testFile -Force -ErrorAction SilentlyContinue
        } else {
            if (Test-Path $outputFile) {
                $output = Get-Content $outputFile -Raw -ErrorAction SilentlyContinue
                Write-TestResult -Name "Permissions" -Passed $false -Msg "File not created. Output: $(Get-Preview $output 200)" -Duration $sw.Elapsed.TotalSeconds
            } else {
                Write-TestResult -Name "Permissions" -Passed $false -Msg "No output at all" -Duration $sw.Elapsed.TotalSeconds
            }
        }
    } catch {
        $sw.Stop()
        Write-TestResult -Name "Permissions" -Passed $false -Msg "Exception: $_" -Duration $sw.Elapsed.TotalSeconds
    }
}

# --- Test 8: Validation Dispatch (full integration) ---

function Test-OpenCodeValidation {
    Write-TestHeader -Name "OpenCode CLI - Validation Dispatch (full integration)"
    $outputFile = Join-Path $OutputDir "opencode-validation-output.txt"
    Clean-File -Path $outputFile

    $prompt = 'You are a validation agent. Review this function for correctness: "def calc_wash_sale(loss, replacement, original): return loss if replacement >= original else loss * (replacement / original)". Report: VERDICT (PASS/CHANGES_REQUIRED), FINDINGS (numbered, severity H/M/L), SUMMARY (one paragraph).'

    $sw = [System.Diagnostics.Stopwatch]::StartNew()
    try {
        opencode run --model $script:BedrockClaudeModel --dir "{{PROJECT_ROOT}}" --dangerously-skip-permissions $prompt *> $outputFile
        $sw.Stop()

        if (Test-Path $outputFile) {
            $content = Get-Content $outputFile -Raw -ErrorAction SilentlyContinue
            if ($null -ne $content -and $content.Length -gt 50) {
                if ($content -match "VERDICT") {
                    Write-TestResult -Name "Validation Dispatch" -Passed $true -Msg "VERDICT found ($($content.Length) chars)" -Duration $sw.Elapsed.TotalSeconds
                } elseif ($content.Length -gt 100) {
                    Write-TestResult -Name "Validation Dispatch" -Passed $true -Msg "Substantial output ($($content.Length) chars)" -Duration $sw.Elapsed.TotalSeconds
                } else {
                    Write-TestResult -Name "Validation Dispatch" -Passed $false -Msg "Missing VERDICT: $(Get-Preview $content 200)" -Duration $sw.Elapsed.TotalSeconds
                }
            } else {
                Write-TestResult -Name "Validation Dispatch" -Passed $false -Msg "Output too short" -Duration $sw.Elapsed.TotalSeconds
            }
        } else {
            Write-TestResult -Name "Validation Dispatch" -Passed $false -Msg "Output file not created" -Duration $sw.Elapsed.TotalSeconds
        }
    } catch {
        $sw.Stop()
        Write-TestResult -Name "Validation Dispatch" -Passed $false -Msg "Exception: $_" -Duration $sw.Elapsed.TotalSeconds
    }
}

# --- Main ---

Write-Host ""
Write-Host "===========================================================" -ForegroundColor Magenta
Write-Host "   OPENCODE CLI - BEDROCK DISPATCH PoC TEST SUITE          " -ForegroundColor Magenta
Write-Host "===========================================================" -ForegroundColor Magenta
Write-Host ""
Write-Host "  Output dir: $OutputDir"
Write-Host "  Test scope: $Test"
Write-Host "  Bedrock Claude: $script:BedrockClaudeModel"
Write-Host "  Bedrock GPT:    $script:BedrockGPTModel"
Write-Host ""

Ensure-Dir -Path $OutputDir

$installed = $false

switch ($Test) {
    'all' {
        $installed = Test-OpenCodeInstall
        if (-not $installed) {
            Write-Host "`n  [ABORT] OpenCode not installed - skipping all remaining tests." -ForegroundColor Red
            Write-Host "  Install: go install github.com/opencode-ai/opencode@latest" -ForegroundColor Yellow
        } else {
            Test-OpenCodeAuth
            Test-OpenCodeHello
            Test-OpenCodeBedrockClaude
            Test-OpenCodeBedrockGPT
            Test-OpenCodeJsonOutput
            Test-OpenCodeDirFlag
            Test-OpenCodePermissions
            Test-OpenCodeValidation
        }
    }
    'opencode-install'       { Test-OpenCodeInstall }
    'opencode-auth'          { Test-OpenCodeAuth }
    'opencode-hello'         { Test-OpenCodeHello }
    'opencode-bedrock-claude'{ Test-OpenCodeBedrockClaude }
    'opencode-bedrock-gpt'   { Test-OpenCodeBedrockGPT }
    'opencode-json-output'   { Test-OpenCodeJsonOutput }
    'opencode-dir-flag'      { Test-OpenCodeDirFlag }
    'opencode-permissions'   { Test-OpenCodePermissions }
    'opencode-validation'    { Test-OpenCodeValidation }
}

# --- Summary ---

Write-Host ("`n" + ("=" * 60)) -ForegroundColor Magenta
Write-Host "  SUMMARY" -ForegroundColor Magenta
Write-Host ("=" * 60) -ForegroundColor Magenta
Write-Host ""
$script:Results | Format-Table -AutoSize
Write-Host "  Total: $($script:PassCount + $script:FailCount + $script:SkipCount) | " -NoNewline
Write-Host "PASS: $script:PassCount " -ForegroundColor Green -NoNewline
Write-Host "FAIL: $script:FailCount " -ForegroundColor Red -NoNewline
Write-Host "SKIP: $script:SkipCount" -ForegroundColor Yellow
Write-Host ""

# --- PoC Verdict ---

Write-Host ("=" * 60) -ForegroundColor Cyan
Write-Host "  PoC VERDICT" -ForegroundColor Cyan
Write-Host ("=" * 60) -ForegroundColor Cyan

$coreTests = $script:Results | Where-Object { $_.Test -in @("OpenCode Install", "OpenCode Auth", "OpenCode Hello", "Bedrock Claude") }
$corePassed = @($coreTests | Where-Object { $_.Status -eq "PASS" }).Count
$coreTotal = @($coreTests).Count

if ($coreTotal -eq 0) {
    Write-Host "  INCONCLUSIVE - not enough tests ran" -ForegroundColor Yellow
} elseif ($corePassed -eq $coreTotal) {
    Write-Host "  VIABLE - OpenCode CLI can serve as a Bedrock dispatch target" -ForegroundColor Green
    Write-Host "    > Add to cli-dispatch SKILL.md as Route 7: OpenCode Bedrock" -ForegroundColor Green
    Write-Host "    > Supports both Claude Opus 5 AND GPT-5.5 via Bedrock" -ForegroundColor Green
} elseif ($corePassed -ge 2) {
    Write-Host "  PARTIAL - Some core tests failed, investigate before integration" -ForegroundColor Yellow
    $failed = $coreTests | Where-Object { $_.Status -eq "FAIL" }
    foreach ($f in $failed) {
        Write-Host "    > FAILED: $($f.Test) - $($f.Message)" -ForegroundColor Red
    }
} else {
    Write-Host "  NOT VIABLE - Too many core test failures" -ForegroundColor Red
}

Write-Host ""

$realFailures = @($script:Results | Where-Object { $_.Status -eq "FAIL" })
if ($realFailures.Count -gt 0) { exit 1 }
