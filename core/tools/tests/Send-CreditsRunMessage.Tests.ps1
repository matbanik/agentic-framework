# S1b orchestrator send (Component C of docs/execution/plans/2026-10-15-scheduled-credits-runs).
# AC-C.6 Send-CreditsRunMessage.ps1 accepts info, query and stop-after-row, validates the message
# against credits-msg.v1 and writes one messages row with the next (run_id, seq) (report section
# 4.6.2). kind ruling was refused (kind_not_enabled) until S6b; from S6b a ruling with no ruling
# fields fails the schema (EA-73). An extra field fails the schema.
#
# Every store is a temp file (AC-B.10). The runs are manual runs from register_minimal.

BeforeAll {
    $script:Repo = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
    $script:Send = Join-Path $script:Repo '.agent/skills/claude-credits/Send-CreditsRunMessage.ps1'
    $script:Schema = Join-Path $script:Repo '.agent/skills/claude-credits/schemas/credits-msg.v1.json'
    $script:StateTool = Join-Path $script:Repo 'tools/credits_state.py'
    $script:Root = "{{RECEIPTS_DIR}}/credits-send-tests/$([guid]::NewGuid().ToString('N'))"
    New-Item -ItemType Directory -Force -Path $script:Root | Out-Null
    $script:EffectLog = "$script:Root/effects.jsonl"
    $script:Db = "$script:Root/state.db"
    # Plan Constant Classification: the body cap of one message (R4.6.2; see the reflection EA).
    $script:BodyMax = 4000

    $venvPy = Join-Path $script:Repo '.venv/Scripts/python.exe'
    $script:Py = if (Test-Path -LiteralPath $venvPy) { $venvPy } else { (Get-Command python -ErrorAction Stop).Source }

    function New-Id([string]$Prefix) { "$Prefix-$([guid]::NewGuid().ToString('N').Substring(0, 10))" }

    # Start a process with no inherited CREDITS_* value, plus the test effect log.
    function Start-Clean([string]$File, [string[]]$Arguments) {
        $psi = [System.Diagnostics.ProcessStartInfo]::new($File)
        foreach ($a in $Arguments) { $psi.ArgumentList.Add([string]$a) }
        $psi.UseShellExecute = $false
        $psi.RedirectStandardOutput = $true
        $psi.RedirectStandardError = $true
        $psi.StandardOutputEncoding = [System.Text.Encoding]::UTF8
        $psi.StandardErrorEncoding = [System.Text.Encoding]::UTF8
        foreach ($name in @($psi.Environment.Keys)) {
            if ($name -like 'CREDITS_*' -or $name -in @('CLAUDECODE', 'CLAUDE_CODE_ENTRYPOINT')) { $null = $psi.Environment.Remove($name) }
        }
        $psi.Environment['CREDITS_TEST_EFFECT_LOG'] = $script:EffectLog
        $p = [System.Diagnostics.Process]::Start($psi)
        $so = $p.StandardOutput.ReadToEndAsync(); $se = $p.StandardError.ReadToEndAsync()
        if (-not $p.WaitForExit(120000)) { & taskkill.exe /PID $p.Id /T /F *> $null; throw "timed out: $File" }
        $p.WaitForExit()
        [pscustomobject]@{ Code = $p.ExitCode; Out = $so.Result; Err = $se.Result }
    }

    function Assert-Store([string]$Verb, [string[]]$Arguments = @()) {
        $res = Start-Clean $script:Py (@('-X', 'utf8', $script:StateTool, '--db', $script:Db, $Verb) + $Arguments)
        if ($res.Code -ne 0) { throw "store $Verb failed: exit=$($res.Code) out=$($res.Out) err=$($res.Err)" }
        $res.Out | ConvertFrom-Json
    }

    function Get-UtcText([datetime]$Value) { $Value.ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ') }

    # A manual run with one running segment.
    function New-Run {
        $runId = New-Id 'c6'
        $segment = "seg-$runId"
        Assert-Store 'register_minimal' @('--run-id', $runId, '--segment-id', $segment, '--wrapper-pid', '6161',
            '--wrapper-created', (Get-UtcText (Get-Date).AddMinutes(-1)), '--boot-id', 'boot-fixture-1', '--win-session', '1',
            '--job-name', "Local\{{PROJECT_NAME_UPPER}}Credits-$segment", '--expected-session-id', [guid]::NewGuid().ToString().ToLowerInvariant()) | Out-Null
        Assert-Store 'manual_identity' @('--segment-id', $segment, '--pid', '5151', '--created', (Get-UtcText (Get-Date))) | Out-Null
        $runId
    }

    function Invoke-Send([string[]]$Arguments) {
        $res = Start-Clean 'pwsh' (@('-NoProfile', '-File', $script:Send, '-StateDb', $script:Db) + $Arguments)
        $json = $null
        # Output that is not JSON leaves Json empty, so each test fails on its own assertion.
        if ($res.Out -and $res.Out.Trim()) {
            try { $json = $res.Out | ConvertFrom-Json -ErrorAction Stop } catch { $json = $null }
        }
        [pscustomobject]@{ Code = $res.Code; Out = $res.Out; Err = $res.Err; Json = $json }
    }

    function Get-Messages([string]$RunId) {
        $code = 'import json, sqlite3, sys; c = sqlite3.connect("file:" + sys.argv[1] + "?mode=ro", uri=True); c.row_factory = sqlite3.Row; print(json.dumps([dict(r) for r in c.execute("SELECT * FROM messages WHERE run_id = ? ORDER BY seq", (sys.argv[2],))]))'
        @((& $script:Py -X utf8 -c $code $script:Db $RunId | Out-String) | ConvertFrom-Json)
    }

    # The canonical hash (R4.6.2): sorted keys, no spaces, UTF-8, non-ASCII kept, nulls included.
    function Get-PayloadHash([string]$RunId, [string]$Kind, [string]$Quote) {
        $code = 'import hashlib, json, sys; doc = {"run_id": sys.argv[1], "kind": sys.argv[2], "decision_id": None, "gate_id": None, "orchestrator_session_id": None, "user_message_uuid": None, "human_quote": sys.argv[3] or None}; print(hashlib.sha256(json.dumps(doc, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")).hexdigest())'
        (& $script:Py -X utf8 -c $code $RunId $Kind $Quote | Out-String).Trim()
    }

    function New-MessageDoc {
        [ordered]@{
            schema = 'credits-msg.v1'; run_id = 'c6-fixture'; kind = 'info'; body = 'fixture body'
            human_quote = $null; decision_id = $null; gate_id = $null
            orchestrator_session_id = $null; user_message_uuid = $null
        }
    }

    Assert-Store 'init' | Out-Null
}

AfterAll {
    if ($script:Root -and (Test-Path -LiteralPath $script:Root)) { Remove-Item -LiteralPath $script:Root -Recurse -Force -ErrorAction SilentlyContinue }
}

Describe 'AC-C.6: Send-CreditsRunMessage.ps1 writes one message with the next seq' {
    It 'AC-C.6: info, query and stop-after-row get seq 1, 2 and 3' {
        $runId = New-Run
        $kinds = @('info', 'query', 'stop-after-row')
        for ($i = 0; $i -lt $kinds.Count; $i++) {
            $res = Invoke-Send @('-RunId', $runId, '-Kind', $kinds[$i], '-Body', "fixture body $i")
            $res.Code | Should -Be 0 -Because "$($res.Out) $($res.Err)"
            $res.Json.result | Should -Be 'changed'
            [int]$res.Json.seq | Should -Be ($i + 1)
            $res.Json.msg_id | Should -Not -BeNullOrEmpty
        }
        $rows = Get-Messages $runId
        $rows.Count | Should -Be 3
        @($rows | ForEach-Object { $_.kind }) | Should -Be $kinds
        @($rows | ForEach-Object { [int]$_.seq }) | Should -Be @(1, 2, 3)
    }

    It 'AC-C.6: the seq starts at 1 for each run' {
        $first = New-Run
        $second = New-Run
        (Invoke-Send @('-RunId', $first, '-Kind', 'info', '-Body', 'one')).Code | Should -Be 0
        (Invoke-Send @('-RunId', $first, '-Kind', 'info', '-Body', 'two')).Code | Should -Be 0
        $res = Invoke-Send @('-RunId', $second, '-Kind', 'info', '-Body', 'other run')
        $res.Code | Should -Be 0 -Because "$($res.Out) $($res.Err)"
        [int]$res.Json.seq | Should -Be 1
    }

    It 'AC-C.6: payload_hash is the SHA-256 of the canonical identity fields' {
        $runId = New-Run
        $quote = 'proceed — send it'
        $res = Invoke-Send @('-RunId', $runId, '-Kind', 'query', '-Body', 'report status', '-HumanQuote', $quote)
        $res.Code | Should -Be 0 -Because "$($res.Out) $($res.Err)"
        $want = Get-PayloadHash $runId 'query' $quote
        $res.Json.payload_hash | Should -Be $want
        (Get-Messages $runId)[0].payload_hash | Should -Be $want
    }

    # From S6b (AC-C.6 "before S6b"; EA-73) the ruling kind is sent; one with no decision, gate,
    # session or uuid has nothing the verifier can check (R4.6.2, R4.6.3), so the schema refuses it.
    It 'AC-C.6: kind ruling with no decision, gate, session or uuid is refused schema_invalid and writes no row' {
        $runId = New-Run
        $res = Invoke-Send @('-RunId', $runId, '-Kind', 'ruling', '-Body', 'D-1: A')
        $res.Code | Should -Be 3 -Because "$($res.Out) $($res.Err)"
        $res.Json.error | Should -Be 'schema_invalid'
        @(Get-Messages $runId).Count | Should -Be 0
    }

    It 'AC-C.6: an unknown run is refused unknown_run' {
        $res = Invoke-Send @('-RunId', 'c6-not-registered', '-Kind', 'info', '-Body', 'fixture body')
        $res.Code | Should -Be 3 -Because "$($res.Out) $($res.Err)"
        $res.Json.error | Should -Be 'unknown_run'
        @(Get-Messages 'c6-not-registered').Count | Should -Be 0
    }

    It 'AC-C.6: a body over the cap is refused body_too_long and writes no row' {
        $runId = New-Run
        $res = Invoke-Send @('-RunId', $runId, '-Kind', 'info', '-Body', ('x' * ($script:BodyMax + 1)))
        $res.Code | Should -Be 3 -Because "$($res.Out) $($res.Err)"
        $res.Json.error | Should -Be 'body_too_long'
        @(Get-Messages $runId).Count | Should -Be 0
    }
}

Describe 'AC-C.6: the credits-msg.v1 schema' {
    It 'AC-C.6: the schema file exists' {
        Test-Path -LiteralPath $script:Schema -PathType Leaf | Should -BeTrue
    }

    It 'AC-C.6: a full valid message passes the schema' {
        $doc = New-MessageDoc
        Test-Json -Json ($doc | ConvertTo-Json -Depth 4) -SchemaFile $script:Schema -ErrorAction SilentlyContinue | Should -BeTrue
    }

    It 'AC-C.6: an extra field fails the schema (additionalProperties false)' {
        $doc = New-MessageDoc
        $doc['priority'] = 'high'
        Test-Json -Json ($doc | ConvertTo-Json -Depth 4) -SchemaFile $script:Schema -ErrorAction SilentlyContinue | Should -BeFalse
    }

    It 'AC-C.6: a ruling with no decision, gate, session or uuid and an unknown kind fail the schema' {
        foreach ($kind in @('ruling', 'shout')) {
            $doc = New-MessageDoc
            $doc['kind'] = $kind
            Test-Json -Json ($doc | ConvertTo-Json -Depth 4) -SchemaFile $script:Schema -ErrorAction SilentlyContinue | Should -BeFalse -Because $kind
        }
    }

    It 'AC-C.6: a body over the cap fails the schema' {
        $doc = New-MessageDoc
        $doc['body'] = 'x' * ($script:BodyMax + 1)
        Test-Json -Json ($doc | ConvertTo-Json -Depth 4) -SchemaFile $script:Schema -ErrorAction SilentlyContinue | Should -BeFalse
    }
}
