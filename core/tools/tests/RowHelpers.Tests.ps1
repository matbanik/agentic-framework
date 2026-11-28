# MEU-986 row-helper module of docs/execution/plans/2026-11-26-row-helper-module (AC-986.1 to AC-986.9).
# The tests import tools/RowHelpers.psm1 and call each function on files under $TestDrive.
# A fake interpreter stands in for python: a script in $TestDrive that logs its arguments and
# its environment, and prints the text and exits with the code that its JSON configuration gives.
# A fake script stands in for the re-pin runner. No test runs a real guard suite, a real pytest
# or the real re-pin runner, and no test writes to this repository.
# While the module is absent, BeforeEach throws "module missing: <path>", so each It fails for
# that reason.

Describe 'RowHelpers' {
    BeforeAll {
        $script:Repo = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
        $script:ModulePath = Join-Path $script:Repo 'tools/RowHelpers.psm1'
        $script:Loaded = $false
        if (Test-Path -LiteralPath $script:ModulePath) {
            Import-Module $script:ModulePath -Force
            $script:Loaded = $true
        }
        $venvPy = Join-Path $script:Repo '.venv/Scripts/python.exe'
        $script:Py = if (Test-Path -LiteralPath $venvPy) { $venvPy } else { (Get-Command python -ErrorAction Stop).Source }
        $script:EnvNames = @('TMP', 'TEMP', 'TMPDIR', 'COLUMNS', 'FAKE_PY_CFG', 'RH_TEST_WORKERS')
        $script:Api = @('Add-BaseFail', 'Assert-NoNewRed', 'Assert-Run', 'Get-FailIds', 'Invoke-GuardSplit', 'Invoke-PolicyRepin', 'Invoke-RedRerun', 'Set-PyTemp')
        $script:Header = '=========================== short test summary info ============================'

        $script:FakePy = @'
import hashlib
import json
import os
import sys
from pathlib import Path

cfg = json.loads(Path(os.environ["FAKE_PY_CFG"]).read_text(encoding="utf-8"))
args = sys.argv[1:]
with open(cfg["log"], "a", encoding="utf-8") as fh:
    fh.write(json.dumps({
        "args": args,
        "columns": os.environ.get("COLUMNS"),
        "tmp": os.environ.get("TMP"),
        "temp": os.environ.get("TEMP"),
        "tmpdir": os.environ.get("TMPDIR"),
    }) + "\n")
rest = args[2:] if args[:2] == ["-m", "pytest"] else args
if "--collect-only" in rest:
    entry = cfg["collect"]
elif "-m" in rest:
    entry = cfg["half1"] if rest[rest.index("-m") + 1] == "not serial" else cfg["half2"]
else:
    tid = rest[0]
    count = Path(cfg["log"] + "." + hashlib.sha256(tid.encode()).hexdigest()[:12])
    n = int(count.read_text()) if count.exists() else 0
    count.write_text(str(n + 1))
    runs = cfg["rerun"][tid]
    entry = runs[min(n, len(runs) - 1)]
sys.stdout.write(entry["text"])
sys.stdout.flush()
sys.exit(entry["code"])
'@

        function Write-Utf8([string]$Path, [string]$Text) {
            New-Item -ItemType Directory -Force -Path (Split-Path -Parent $Path) | Out-Null
            [IO.File]::WriteAllText($Path, $Text, [Text.UTF8Encoding]::new($false))
        }

        function New-Dir([string]$Name) {
            $d = Join-Path $TestDrive "$Name-$([guid]::NewGuid().ToString('N').Substring(0, 8))"
            New-Item -ItemType Directory -Force -Path $d | Out-Null
            $d
        }

        # A pytest -rfE receipt: the summary header, one line per entry of $Fails, the summary line.
        function New-Receipt([string]$Path, [string[]]$Fails = @(), [string]$Summary, [string[]]$Before = @()) {
            $lines = @('============================= test session starts ==============================') + $Before + @($script:Header) + $Fails
            if ($Summary) { $lines += $Summary }
            Write-Utf8 $Path (($lines -join "`n") + "`n")
            $Path
        }

        # A fake interpreter in a new folder. $Cfg holds collect, half1, half2 and rerun entries.
        function New-Fake([hashtable]$Cfg) {
            $d = New-Dir 'fake'
            $Cfg['log'] = Join-Path $d 'log.jsonl'
            Write-Utf8 (Join-Path $d 'fake.py') $script:FakePy
            Write-Utf8 (Join-Path $d 'cfg.json') ($Cfg | ConvertTo-Json -Depth 8)
            $env:FAKE_PY_CFG = Join-Path $d 'cfg.json'
            [pscustomobject]@{ Dir = $d; Python = @($script:Py, (Join-Path $d 'fake.py')); Log = $Cfg['log'] }
        }

        function Get-Calls($Fake) {
            if (-not (Test-Path -LiteralPath $Fake.Log)) { return @() }
            @(Get-Content -LiteralPath $Fake.Log | Where-Object { $_ } | ForEach-Object { $_ | ConvertFrom-Json })
        }

        function Get-TreeHash([string]$Root) {
            @(Get-ChildItem -LiteralPath $Root -Recurse -File | Sort-Object FullName | ForEach-Object {
                    "$($_.FullName.Substring($Root.Length)) $((Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash)"
                }) -join "`n"
        }

        function Get-Entry([string]$Text, [int]$Code) { @{ text = $Text; code = $Code } }

        # Two guard files: one plain, one with the serial marker.
        function New-Guards([string]$Dir, [switch]$NoSerial) {
            $g1 = Join-Path $Dir 'test_g1.py'
            $g2 = Join-Path $Dir 'test_g2.py'
            Write-Utf8 $g1 "def test_one():`n    assert True`n"
            $mark = if ($NoSerial) { '' } else { "import pytest`n`npytestmark = pytest.mark.serial`n`n" }
            Write-Utf8 $g2 "$($mark)def test_two():`n    assert True`n"
            @($g1, $g2)
        }

        function Get-Census {
            $name = 'zori' + 'vest'
            $user = 'mat' + 'banik'
            "$name|$user|" + '[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[a-z]{2,}|\b[PC]:[/\\]'
        }
    }

    BeforeEach {
        $script:SavedEnv = @{}
        foreach ($n in $script:EnvNames) { $script:SavedEnv[$n] = [Environment]::GetEnvironmentVariable($n) }
        if (-not $script:Loaded) { throw "module missing: $script:ModulePath" }
    }

    AfterEach {
        foreach ($n in $script:SavedEnv.Keys) { [Environment]::SetEnvironmentVariable($n, $script:SavedEnv[$n]) }
    }

    AfterAll {
        Remove-Module RowHelpers -Force -ErrorAction SilentlyContinue
    }

    Context 'Set-PyTemp (AC-986.1)' {
        It 'makes the folder and sets TMP, TEMP and TMPDIR to it' {
            $d = Join-Path (New-Dir 'pt') 'a/b'
            $env:TMP | Should -Not -Be $d
            Test-Path -LiteralPath $d | Should -BeFalse
            $out = Set-PyTemp -Path $d
            $out | Should -BeNullOrEmpty
            Test-Path -LiteralPath $d -PathType Container | Should -BeTrue
            $full = (Resolve-Path -LiteralPath $d).ProviderPath
            $env:TMP | Should -Be $full
            $env:TEMP | Should -Be $full
            $env:TMPDIR | Should -Be $full
        }
    }

    Context 'Get-FailIds (AC-986.2)' {
        It 'returns the id and the normalized line of each FAILED and ERROR line, sorted by id' {
            $f = New-Receipt (Join-Path (New-Dir 'gf') 'r.txt') -Fails @(
                'FAILED t.py::test_b - AssertionError: at 0x1f3a in pytest-12 on gw3',
                'ERROR t.py::test_a - fixture boom',
                'FAILED t.py::test_c[empty output] - ValueError: x'
            ) -Summary '=================== 2 failed, 4 passed, 1 error in 1.00s ==================='
            $r = @(Get-FailIds -Receipt $f)
            ($r.Id -join '|') | Should -Be 't.py::test_a|t.py::test_b|t.py::test_c[empty output]'
            $r[0].Line | Should -Be 'fixture boom'
            $r[1].Line | Should -Be 'AssertionError: at 0x? in pytest-N on gwN'
            $r[2].Line | Should -Be 'ValueError: x'
        }

        It 'gives the same line for two lines that differ only in 0x addresses, pytest-<n> and gw<n>' {
            $d = New-Dir 'gf'
            $a = New-Receipt (Join-Path $d 'a.txt') -Fails @('FAILED t.py::test_x - E at 0xdead pytest-3 gw0') -Summary '1 failed in 0.10s'
            $b = New-Receipt (Join-Path $d 'b.txt') -Fails @('FAILED t.py::test_x - E at 0xbeef01 pytest-41 gw12') -Summary '1 failed in 0.10s'
            (Get-FailIds $a).Line | Should -Be (Get-FailIds $b).Line
        }

        It 'gives a different line for a different message' {
            $d = New-Dir 'gf'
            $a = New-Receipt (Join-Path $d 'a.txt') -Fails @('FAILED t.py::test_x - E one') -Summary '1 failed in 0.10s'
            $b = New-Receipt (Join-Path $d 'b.txt') -Fails @('FAILED t.py::test_x - E two') -Summary '1 failed in 0.10s'
            (Get-FailIds $a).Line | Should -Not -Be (Get-FailIds $b).Line
        }

        It 'keeps an id with a parameter part that has spaces whole, with and without a message' {
            $f = New-Receipt (Join-Path (New-Dir 'gf') 'r.txt') -Fails @(
                'FAILED t.py::test_a[empty output] - AssertionError: no - text',
                'FAILED t.py::test_b[two words here]'
            ) -Summary '2 failed in 0.10s'
            $r = @(Get-FailIds $f)
            $r[0].Id | Should -Be 't.py::test_a[empty output]'
            $r[0].Line | Should -Be 'AssertionError: no - text'
            $r[1].Id | Should -Be 't.py::test_b[two words here]'
            $r[1].Line | Should -Be ''
        }

        It 'gives no id for a PASSED line and no line text for a FAILED line without a message' {
            $f = New-Receipt (Join-Path (New-Dir 'gf') 'r.txt') -Fails @('PASSED t.py::test_p', 'FAILED t.py::test_q') -Summary '1 failed, 1 passed in 0.10s'
            $r = @(Get-FailIds $f)
            $r.Count | Should -Be 1
            $r[0].Id | Should -Be 't.py::test_q'
            $r[0].Line | Should -Be ''
        }

        It 'keeps the first line of an id that has two lines' {
            $f = New-Receipt (Join-Path (New-Dir 'gf') 'r.txt') -Fails @('FAILED t.py::test_d - first', 'ERROR t.py::test_d - second') -Summary '1 failed, 1 error in 0.10s'
            { Get-FailIds $f } | Should -Throw -ExpectedMessage 'fail_ids_short:1!=2'
            $g = New-Receipt (Join-Path (New-Dir 'gf') 'r.txt') -Fails @('FAILED t.py::test_d - first', 'ERROR t.py::test_d - second')
            $r = @(Get-FailIds $g)
            $r.Count | Should -Be 1
            $r[0].Line | Should -Be 'first'
        }

        It 'throws fail_ids_short when the summary counts more reds than the receipt lists' {
            $f = New-Receipt (Join-Path (New-Dir 'gf') 'r.txt') -Fails @('FAILED t.py::test_a - E') -Summary '======= 2 failed, 3 passed in 0.50s ======='
            { Get-FailIds -Receipt $f } | Should -Throw -ExpectedMessage 'fail_ids_short:1!=2'
        }

        It 'ignores a log line above the summary header' {
            $f = New-Receipt (Join-Path (New-Dir 'gf') 'r.txt') -Before @('ERROR root:x.py:1 boom', 'FAILED t.py::test_above - E') -Fails @('FAILED t.py::test_z - E') -Summary '1 failed in 0.10s'
            $r = @(Get-FailIds $f)
            ($r.Id -join '|') | Should -Be 't.py::test_z'
        }
    }

    Context 'Assert-Run (AC-986.3)' {
        It 'returns the summary line on exit 0 and exit 1, called by position' {
            $f = New-Receipt (Join-Path (New-Dir 'ar') 'r.txt') -Summary '======================== 3 passed in 0.10s ========================='
            Assert-Run $f 0 | Should -Be '======================== 3 passed in 0.10s ========================='
            $g = New-Receipt (Join-Path (New-Dir 'ar') 'r.txt') -Fails @('FAILED t.py::test_a - E') -Summary '1 failed, 2 passed in 0.20s'
            Assert-Run $g 1 | Should -Be '1 failed, 2 passed in 0.20s'
            Assert-Run -Receipt $g -Code 1 | Should -Be '1 failed, 2 passed in 0.20s'
        }

        It 'throws run_fail code=<c> on an exit code other than 0 and 1, also with a summary' {
            $f = New-Receipt (Join-Path (New-Dir 'ar') 'r.txt') -Summary '3 passed in 0.10s'
            { Assert-Run $f 2 } | Should -Throw -ExpectedMessage 'run_fail code=2'
            { Assert-Run $f 5 } | Should -Throw -ExpectedMessage 'run_fail code=5'
        }

        It 'throws no_summary on exit 0 with no summary line' {
            $f = New-Receipt (Join-Path (New-Dir 'ar') 'r.txt')
            { Assert-Run $f 0 } | Should -Throw -ExpectedMessage 'no_summary'
        }

        It 'throws no_summary on two summary lines' {
            $f = New-Receipt (Join-Path (New-Dir 'ar') 'r.txt') -Before @('3 passed in 0.10s') -Summary '3 passed in 0.10s'
            { Assert-Run $f 0 } | Should -Throw -ExpectedMessage 'no_summary'
        }
    }

    Context 'Assert-NoNewRed (AC-986.4)' {
        It 'returns no_new_red when each red is in the base file or in -Allow' {
            $d = New-Dir 'nr'
            $f = New-Receipt (Join-Path $d 'r.txt') -Fails @('FAILED t.py::test_a - E one', 'FAILED t.py::test_b - E two') -Summary '2 failed in 0.10s'
            Write-Utf8 (Join-Path $d 'base.txt') "t.py::test_a`n"
            Assert-NoNewRed $f (Join-Path $d 'base.txt') @('t.py::test_b') | Should -Be 'no_new_red'
        }

        It 'reads a CRLF base file and an LF base file' {
            $d = New-Dir 'nr'
            $f = New-Receipt (Join-Path $d 'r.txt') -Fails @('FAILED t.py::test_a - E at 0xabc', 'FAILED t.py::test_b - E') -Summary '2 failed in 0.10s'
            Write-Utf8 (Join-Path $d 'crlf.txt') "t.py::test_a`tE at 0x?`r`nt.py::test_b`r`n"
            Write-Utf8 (Join-Path $d 'lf.txt') "t.py::test_a`tE at 0x?`nt.py::test_b`n"
            Assert-NoNewRed -Receipt $f -BaseFail (Join-Path $d 'crlf.txt') | Should -Be 'no_new_red'
            Assert-NoNewRed -Receipt $f -BaseFail (Join-Path $d 'lf.txt') | Should -Be 'no_new_red'
        }

        It 'accepts an <id><tab><line> entry only for the same normalized line' {
            $d = New-Dir 'nr'
            Write-Utf8 (Join-Path $d 'base.txt') "t.py::test_a`tE at 0x? on gwN`n"
            $same = New-Receipt (Join-Path $d 'same.txt') -Fails @('FAILED t.py::test_a - E at 0xdead on gw7') -Summary '1 failed in 0.10s'
            Assert-NoNewRed $same (Join-Path $d 'base.txt') | Should -Be 'no_new_red'
            $other = New-Receipt (Join-Path $d 'other.txt') -Fails @('FAILED t.py::test_a - E another reason') -Summary '1 failed in 0.10s'
            { Assert-NoNewRed $other (Join-Path $d 'base.txt') } | Should -Throw -ExpectedMessage 'not_green'
        }

        It 'reads more than one receipt' {
            $d = New-Dir 'nr'
            $a = New-Receipt (Join-Path $d 'a.txt') -Fails @('FAILED t.py::test_a - E') -Summary '1 failed in 0.10s'
            $b = New-Receipt (Join-Path $d 'b.txt') -Fails @('FAILED t.py::test_new - E') -Summary '1 failed in 0.10s'
            Write-Utf8 (Join-Path $d 'base.txt') "t.py::test_a`n"
            Assert-NoNewRed @($a) (Join-Path $d 'base.txt') | Should -Be 'no_new_red'
            { Assert-NoNewRed @($a, $b) (Join-Path $d 'base.txt') } | Should -Throw -ExpectedMessage 'not_green'
        }

        It 'throws no_base_fail when the base file is absent' {
            $d = New-Dir 'nr'
            $f = New-Receipt (Join-Path $d 'r.txt') -Summary '1 passed in 0.10s'
            { Assert-NoNewRed $f (Join-Path $d 'absent.txt') } | Should -Throw -ExpectedMessage 'no_base_fail'
        }

        It 'throws not_green for a new red' {
            $d = New-Dir 'nr'
            $f = New-Receipt (Join-Path $d 'r.txt') -Fails @('FAILED t.py::test_new - E') -Summary '1 failed in 0.10s'
            Write-Utf8 (Join-Path $d 'base.txt') ''
            { Assert-NoNewRed $f (Join-Path $d 'base.txt') } | Should -Throw -ExpectedMessage 'not_green'
        }

        It 'with -Python and -RerunDir runs the new red again, keeps both receipts and still throws not_green' {
            $d = New-Dir 'nr'
            $f = New-Receipt (Join-Path $d 'r.txt') -Fails @('FAILED t.py::test_new - E first') -Summary '1 failed in 0.10s'
            $before = (Get-FileHash -LiteralPath $f -Algorithm SHA256).Hash
            Write-Utf8 (Join-Path $d 'base.txt') "t.py::test_other`n"
            $again = "$script:Header`nFAILED t.py::test_new - E second`n1 failed in 0.10s`n"
            $fake = New-Fake @{ rerun = @{ 't.py::test_new' = @((Get-Entry $again 1)) } }
            $rr = Join-Path $d 'rerun'
            { Assert-NoNewRed $f (Join-Path $d 'base.txt') -Python $fake.Python -RerunDir $rr } | Should -Throw -ExpectedMessage 'not_green'
            (Get-FileHash -LiteralPath $f -Algorithm SHA256).Hash | Should -Be $before
            Test-Path -LiteralPath (Join-Path $rr 'rerun-1.txt') | Should -BeTrue
            (Get-Content -LiteralPath (Join-Path $rr 'rerun-1.txt') -Raw) | Should -Match 'E second'
            $calls = @(Get-Calls $fake)
            $calls.Count | Should -Be 1
            ($calls[0].args -join '|') | Should -Be '-m|pytest|t.py::test_new|-n|0|-p|no:cacheprovider|-rfE|--tb=short'
        }
    }

    Context 'Invoke-RedRerun (AC-986.5)' {
        It 'runs one process per id with the -n 0 arguments and writes a new receipt per id' {
            $d = New-Dir 'rr'
            $red = "$script:Header`nFAILED t.py::test_a - E at 0x1f`n1 failed in 0.10s`n"
            $pass = "1 passed in 0.10s`n"
            $fake = New-Fake @{ rerun = @{ 't.py::test_a' = @((Get-Entry $red 1)); 't.py::test_b[two words]' = @((Get-Entry $pass 0)) } }
            $r = @(Invoke-RedRerun -Python $fake.Python -Ids @('t.py::test_a', 't.py::test_b[two words]') -Out $d)
            $r.Count | Should -Be 2
            $r[0].Id | Should -Be 't.py::test_a'
            $r[0].Red | Should -BeTrue
            $r[0].Line | Should -Be 'E at 0x?'
            $r[0].Receipt | Should -Be (Join-Path $d 'rerun-1.txt')
            $r[1].Id | Should -Be 't.py::test_b[two words]'
            $r[1].Red | Should -BeFalse
            $r[1].Receipt | Should -Be (Join-Path $d 'rerun-2.txt')
            $calls = @(Get-Calls $fake)
            $calls.Count | Should -Be 2
            ($calls[0].args -join '|') | Should -Be '-m|pytest|t.py::test_a|-n|0|-p|no:cacheprovider|-rfE|--tb=short'
            ($calls[1].args -join '|') | Should -Be '-m|pytest|t.py::test_b[two words]|-n|0|-p|no:cacheprovider|-rfE|--tb=short'
            $calls[0].columns | Should -Be '200'
        }

        It 'never writes into an existing receipt' {
            $d = New-Dir 'rr'
            Write-Utf8 (Join-Path $d 'rerun-1.txt') "keep these bytes`n"
            $before = (Get-FileHash -LiteralPath (Join-Path $d 'rerun-1.txt') -Algorithm SHA256).Hash
            $fake = New-Fake @{ rerun = @{ 't.py::test_a' = @((Get-Entry "1 passed in 0.10s`n" 0)) } }
            $r = @(Invoke-RedRerun -Python $fake.Python -Ids @('t.py::test_a') -Out $d)
            $r[0].Receipt | Should -Be (Join-Path $d 'rerun-2.txt')
            (Get-FileHash -LiteralPath (Join-Path $d 'rerun-1.txt') -Algorithm SHA256).Hash | Should -Be $before
        }

        It 'throws rerun_exit:<c> on an exit code other than 0 and 1' {
            $d = New-Dir 'rr'
            $fake = New-Fake @{ rerun = @{ 't.py::test_a' = @((Get-Entry "internal error`n" 3)) } }
            { Invoke-RedRerun -Python $fake.Python -Ids @('t.py::test_a') -Out $d } | Should -Throw -ExpectedMessage 'rerun_exit:3'
        }
    }

    Context 'Add-BaseFail (AC-986.6)' {
        It 'writes red twice to the base file and red one time to intermittent.txt' {
            $d = New-Dir 'bf'
            $first = Join-Path $d 'half1.txt'
            $redA = "$script:Header`nFAILED t.py::test_a - E again at 0x99`n1 failed in 0.10s`n"
            $fake = New-Fake @{ rerun = @{ 't.py::test_a' = @((Get-Entry $redA 1)); 't.py::test_b' = @((Get-Entry "1 passed in 0.10s`n" 0)) } }
            $split = [pscustomobject]@{
                Folder = $d
                Reds   = @(
                    [pscustomobject]@{ Id = 't.py::test_a'; Line = 'E first'; Receipt = $first },
                    [pscustomobject]@{ Id = 't.py::test_b'; Line = 'E flaky'; Receipt = $first }
                )
            }
            $out = Join-Path $d 'base-fail.txt'
            Add-BaseFail -Split $split -Python $fake.Python -Out $out | Should -Be 'base_fail=1 intermittent=1'
            [IO.File]::ReadAllText($out) | Should -Be "t.py::test_a`tE again at 0x?`n"
            $second = Join-Path $d 'rerun-2.txt'
            [IO.File]::ReadAllText((Join-Path $d 'intermittent.txt')) | Should -Be "t.py::test_b`tintermittent; cause unconfirmed`t$first`t$second`n"
        }

        It 'takes the split from the pipeline and writes empty files when no test is red' {
            $d = New-Dir 'bf'
            $fake = New-Fake @{ rerun = @{} }
            $out = Join-Path $d 'base-fail.txt'
            [pscustomobject]@{ Folder = $d; Reds = @() } | Add-BaseFail -Python $fake.Python -Out $out | Should -Be 'base_fail=0 intermittent=0'
            [IO.File]::ReadAllText($out) | Should -Be ''
            [IO.File]::ReadAllText((Join-Path $d 'intermittent.txt')) | Should -Be ''
            @(Get-Calls $fake).Count | Should -Be 0
        }
    }

    Context 'Invoke-GuardSplit (AC-986.7)' {
        BeforeAll {
            $script:Collect3 = "t.py::a`nt.py::b`nt.py::c`n`n3 tests collected in 0.01s`n"
        }

        It 'runs the collect run and the two halves with their exact arguments and the workers of -WorkersEnv' {
            $d = New-Dir 'gs'
            $g = New-Guards $d
            $env:RH_TEST_WORKERS = '3'
            $fake = New-Fake @{
                collect = (Get-Entry $script:Collect3 0)
                half1   = (Get-Entry "$script:Header`nFAILED t.py::a - E at 0x1`n=== 1 failed, 1 passed, 1 deselected in 0.10s ===`n" 1)
                half2   = (Get-Entry "=== 1 passed, 2 deselected in 0.10s ===`n" 0)
            }
            $tmpBefore = $env:TMP
            $s = Invoke-GuardSplit -Python $fake.Python -Guards $g -Receipts (Join-Path $d 'rc') -WorkersEnv RH_TEST_WORKERS -Phase p1
            $s.Folder | Should -Be (Join-Path (Join-Path $d 'rc') 'split-p1-a1')
            $s.N | Should -Be 3
            $s.Counts.half1.failed | Should -Be 1
            $s.Counts.half1.passed | Should -Be 1
            $s.Counts.half2.passed | Should -Be 1
            @($s.Reds).Count | Should -Be 1
            $s.Reds[0].Id | Should -Be 't.py::a'
            $s.Reds[0].Line | Should -Be 'E at 0x?'
            $s.Reds[0].Receipt | Should -Be (Join-Path $s.Folder 'half1.txt')
            $env:TMP | Should -Be $tmpBefore
            $calls = @(Get-Calls $fake)
            $calls.Count | Should -Be 3
            $gs = $g -join '|'
            ($calls[0].args -join '|') | Should -Be "-m|pytest|$gs|--collect-only|-q|-p|no:cacheprovider"
            ($calls[1].args -join '|') | Should -Be "-m|pytest|$gs|-m|not serial|-n|3|--dist|loadfile|-p|no:cacheprovider|-rfE|--tb=short"
            ($calls[2].args -join '|') | Should -Be "-m|pytest|$gs|-m|serial|-n|0|-p|no:cacheprovider|-rfE|--tb=short"
            $tmp = Join-Path $s.Folder 'tmp'
            foreach ($c in $calls[1..2]) {
                $c.columns | Should -Be '200'
                $c.tmp | Should -Be $tmp
                $c.temp | Should -Be $tmp
                $c.tmpdir | Should -Be $tmp
            }
            foreach ($f in 'collect.txt', 'half1.txt', 'half2.txt', 'split.json') { Test-Path -LiteralPath (Join-Path $s.Folder $f) | Should -BeTrue }
            $j = Get-Content -LiteralPath (Join-Path $s.Folder 'split.json') -Raw | ConvertFrom-Json
            $j.n | Should -Be 3
            $j.workers | Should -Be 3
            $j.sum | Should -Be 3
        }

        It 'uses -Workers when the variable of -WorkersEnv is not set' {
            $d = New-Dir 'gs'
            $g = New-Guards $d
            $env:RH_TEST_WORKERS = $null
            $fake = New-Fake @{
                collect = (Get-Entry $script:Collect3 0)
                half1   = (Get-Entry "2 passed, 1 deselected in 0.10s`n" 0)
                half2   = (Get-Entry "1 passed, 2 deselected in 0.10s`n" 0)
            }
            $null = Invoke-GuardSplit -Python $fake.Python -Guards $g -Receipts $d -WorkersEnv RH_TEST_WORKERS -Phase p1
            (@(Get-Calls $fake)[1].args -join '|') | Should -BeLike '*|-n|4|--dist|loadfile|*'
            $null = Invoke-GuardSplit -Python $fake.Python -Guards $g -Receipts $d -Workers 2 -Phase p1
            (@(Get-Calls $fake)[4].args -join '|') | Should -BeLike '*|-n|2|--dist|loadfile|*'
        }

        It 'throws split_bad_workers for workers 0' {
            $d = New-Dir 'gs'
            $g = New-Guards $d
            $fake = New-Fake @{ collect = (Get-Entry $script:Collect3 0) }
            { Invoke-GuardSplit -Python $fake.Python -Guards $g -Receipts $d -Workers 0 -Phase p1 } | Should -Throw -ExpectedMessage 'split_bad_workers'
            $env:RH_TEST_WORKERS = '0'
            { Invoke-GuardSplit -Python $fake.Python -Guards $g -Receipts $d -WorkersEnv RH_TEST_WORKERS -Phase p1 } | Should -Throw -ExpectedMessage 'split_bad_workers'
            $env:RH_TEST_WORKERS = 'four'
            { Invoke-GuardSplit -Python $fake.Python -Guards $g -Receipts $d -WorkersEnv RH_TEST_WORKERS -Phase p1 } | Should -Throw -ExpectedMessage 'split_bad_workers'
            @(Get-Calls $fake).Count | Should -Be 0
        }

        It 'throws split_collect_fail when the collect run fails' {
            $d = New-Dir 'gs'
            $g = New-Guards $d
            $fake = New-Fake @{ collect = (Get-Entry "ERROR collecting t.py`n" 2) }
            { Invoke-GuardSplit -Python $fake.Python -Guards $g -Receipts $d -Phase p1 } | Should -Throw -ExpectedMessage 'split_collect_fail'
        }

        It 'throws split_run_fail:half1 code=5 when half 1 exits 5' {
            $d = New-Dir 'gs'
            $g = New-Guards $d
            $fake = New-Fake @{ collect = (Get-Entry $script:Collect3 0); half1 = (Get-Entry "3 deselected in 0.10s`n" 5); half2 = (Get-Entry "3 passed in 0.10s`n" 0) }
            { Invoke-GuardSplit -Python $fake.Python -Guards $g -Receipts $d -Phase p1 } | Should -Throw -ExpectedMessage 'split_run_fail:half1 code=5'
        }

        It 'throws split_no_summary:half<k> when a half has no summary line' {
            $d = New-Dir 'gs'
            $g = New-Guards $d
            $fake = New-Fake @{ collect = (Get-Entry $script:Collect3 0); half1 = (Get-Entry "no summary here`n" 0); half2 = (Get-Entry "1 passed in 0.10s`n" 0) }
            { Invoke-GuardSplit -Python $fake.Python -Guards $g -Receipts $d -Phase p1 } | Should -Throw -ExpectedMessage 'split_no_summary:half1'
        }

        It 'throws split_exit5_with_serial when half 2 exits 5 and a guard file holds mark.serial' {
            $d = New-Dir 'gs'
            $g = New-Guards $d
            $fake = New-Fake @{ collect = (Get-Entry $script:Collect3 0); half1 = (Get-Entry "3 passed in 0.10s`n" 0); half2 = (Get-Entry "3 deselected in 0.10s`n" 5) }
            { Invoke-GuardSplit -Python $fake.Python -Guards $g -Receipts $d -Phase p1 } | Should -Throw -ExpectedMessage 'split_exit5_with_serial'
        }

        It 'accepts half 2 exit 5 when no guard file holds mark.serial' {
            $d = New-Dir 'gs'
            $g = New-Guards $d -NoSerial
            $fake = New-Fake @{ collect = (Get-Entry $script:Collect3 0); half1 = (Get-Entry "3 passed in 0.10s`n" 0); half2 = (Get-Entry "3 deselected in 0.10s`n" 5) }
            $s = Invoke-GuardSplit -Python $fake.Python -Guards $g -Receipts $d -Phase p1
            $s.N | Should -Be 3
            $s.Counts.half2.passed | Should -Be 0
        }

        It 'throws split_count_mismatch:<sum>!=<N> when the halves count N+1 tests' {
            $d = New-Dir 'gs'
            $g = New-Guards $d
            $fake = New-Fake @{ collect = (Get-Entry $script:Collect3 0); half1 = (Get-Entry "2 passed, 1 skipped in 0.10s`n" 0); half2 = (Get-Entry "1 passed in 0.10s`n" 0) }
            { Invoke-GuardSplit -Python $fake.Python -Guards $g -Receipts $d -Phase p1 } | Should -Throw -ExpectedMessage 'split_count_mismatch:4!=3'
        }

        It 'makes a2 on a second call and leaves a1 unchanged' {
            $d = New-Dir 'gs'
            $g = New-Guards $d
            $fake = New-Fake @{ collect = (Get-Entry $script:Collect3 0); half1 = (Get-Entry "2 passed in 0.10s`n" 0); half2 = (Get-Entry "1 passed in 0.10s`n" 0) }
            $s1 = Invoke-GuardSplit -Python $fake.Python -Guards $g -Receipts $d -Phase p1
            $h1 = Get-TreeHash $s1.Folder
            $s2 = Invoke-GuardSplit -Python $fake.Python -Guards $g -Receipts $d -Phase p1
            $s1.Folder | Should -Be (Join-Path $d 'split-p1-a1')
            $s2.Folder | Should -Be (Join-Path $d 'split-p1-a2')
            Get-TreeHash $s1.Folder | Should -Be $h1
        }
    }

    Context 'Invoke-PolicyRepin (AC-986.8)' {
        BeforeAll {
            # A fake re-pin runner: it logs its arguments and prints the lines that the test gives.
            function New-FakeRepin([string]$DryLast, [string]$RealLast) {
                $d = New-Dir 'rp'
                $log = Join-Path $d 'calls.txt'
                $text = @"
param([string]`$Receipts, [switch]`$DryRun, [string]`$Python, [string]`$Repo)
"Receipts=`$Receipts DryRun=`$DryRun Python=`$Python Repo=`$Repo" | Add-Content -LiteralPath '$log'
if (`$DryRun) { 'COMPONENT a b'; '$DryLast' } else { 'SINGLE_RUN tag=x'; '$RealLast' }
exit 0
"@
                Write-Utf8 (Join-Path $d 'repin.ps1') $text
                [pscustomobject]@{ Script = (Join-Path $d 'repin.ps1'); Log = $log; Dir = $d }
            }
        }

        It 'runs the dry call, then the real call, each in a new attempt folder' {
            $fake = New-FakeRepin 'repin_dryrun_ok' 'repin_ok'
            $rc = Join-Path $fake.Dir 'rc'
            Invoke-PolicyRepin -Script $fake.Script -Receipts $rc | Should -Be 'repin_ok'
            Invoke-PolicyRepin -Script $fake.Script -Receipts $rc -Python 'py.exe' -Repo 'repo' | Should -Be 'repin_ok'
            $calls = @(Get-Content -LiteralPath $fake.Log)
            $calls.Count | Should -Be 4
            $a1 = Join-Path $rc 'repin-a1'
            $a2 = Join-Path $rc 'repin-a2'
            $calls[0] | Should -Be "Receipts=$(Join-Path $a1 'dry') DryRun=True Python= Repo="
            $calls[1] | Should -Be "Receipts=$(Join-Path $a1 'real') DryRun=False Python= Repo="
            $calls[2] | Should -Be "Receipts=$(Join-Path $a2 'dry') DryRun=True Python=py.exe Repo=repo"
            $calls[3] | Should -Be "Receipts=$(Join-Path $a2 'real') DryRun=False Python=py.exe Repo=repo"
        }

        It 'throws repin_dryrun_fail without repin_dryrun_ok and makes no real call' {
            $fake = New-FakeRepin 'FAILURES 1' 'repin_ok'
            { Invoke-PolicyRepin -Script $fake.Script -Receipts (Join-Path $fake.Dir 'rc') } | Should -Throw -ExpectedMessage 'repin_dryrun_fail'
            @(Get-Content -LiteralPath $fake.Log).Count | Should -Be 1
        }

        It 'throws repin_fail when the real call does not end with repin_ok' {
            $fake = New-FakeRepin 'repin_dryrun_ok' 'policy_not_last'
            { Invoke-PolicyRepin -Script $fake.Script -Receipts (Join-Path $fake.Dir 'rc') } | Should -Throw -ExpectedMessage 'repin_fail'
            @(Get-Content -LiteralPath $fake.Log).Count | Should -Be 2
        }
    }

    Context 'NEUTRAL and the API (AC-986.9)' {
        It 'finds no project name, user name, email address or drive path in the module and its tests' {
            $census = Get-Census
            foreach ($rel in 'tools/RowHelpers.psm1', 'tools/tests/RowHelpers.Tests.ps1', 'tools/tests/test_row_helpers_pester.py') {
                $hits = @(Select-String -LiteralPath (Join-Path $script:Repo $rel) -Pattern $census)
                ($hits | ForEach-Object { "$rel`:$($_.LineNumber): $($_.Line)" }) -join "`n" | Should -BeNullOrEmpty
            }
        }

        It 'fails the census for a module copy with the project name in a comment' {
            $copy = Join-Path (New-Dir 'nt') 'RowHelpers.psm1'
            $name = 'Zori' + 'vest'
            Write-Utf8 $copy ((Get-Content -LiteralPath $script:ModulePath -Raw) + "`n# $name`n")
            @(Select-String -LiteralPath $copy -Pattern (Get-Census)).Count | Should -Be 1
        }

        It 'has exactly one tools/*.psm1 that defines both Assert-Run and Assert-NoNewRed' {
            $both = @(Get-ChildItem -LiteralPath (Join-Path $script:Repo 'tools') -Filter '*.psm1' -File | Where-Object {
                    $t = Get-Content -LiteralPath $_.FullName -Raw
                    $t -match 'function\s+Assert-Run\b' -and $t -match 'function\s+Assert-NoNewRed\b'
                })
            $both.Count | Should -Be 1
            $both[0].Name | Should -Be 'RowHelpers.psm1'
        }

        It 'exports only the functions of MODULE_API' {
            $m = Get-Module RowHelpers
            $m | Should -Not -BeNullOrEmpty
            (@($m.ExportedFunctions.Keys | Sort-Object) -join '|') | Should -Be ($script:Api -join '|')
            @($m.ExportedCmdlets.Keys).Count | Should -Be 0
            @($m.ExportedAliases.Keys).Count | Should -Be 0
            @($m.ExportedVariables.Keys).Count | Should -Be 0
        }
    }
}
