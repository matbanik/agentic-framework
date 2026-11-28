#Requires -Version 7.2
<#
.SYNOPSIS
    Row helpers of a plan row: the pytest receipt checks, the base rule, the split guard run and the
    policy re-pin, in one tested module.

.DESCRIPTION
    A plan row imports this module and calls its functions. It does not copy them.

    Each failure writes its evidence with Write-Host and then throws its token. No function calls
    exit, so `pwsh -NoProfile -Command` exits 1 on a failure. A caller that catches the error
    prints the token from $_.Exception.Message.

    The module holds no project value. A project value enters only as a parameter, for example the
    name of the worker variable (-WorkersEnv) or the path of the re-pin runner (-Script).

    Functions:
      Set-PyTemp          makes a folder and sets TMP, TEMP and TMPDIR to it.
      Get-FailIds         reads the FAILED and ERROR lines of a pytest -rfE receipt.
      Assert-Run          checks the exit code and the one summary line of a pytest receipt.
      Assert-NoNewRed     checks that each red of the receipts is a base fail or an allowed id.
      Invoke-RedRerun     runs each id again alone, one process and one new receipt per id.
      Add-BaseFail        writes the base file and intermittent.txt by the base rule.
      Invoke-GuardSplit   runs the guard files in two halves (not serial, serial) with a count check.
      Invoke-PolicyRepin  runs the re-pin runner dry, then real, in a new attempt folder.
#>

Set-StrictMode -Version 3.0

# The summary line of Assert-Run (one match is necessary).
$script:RunSummaryRe = [regex]::new('^(=+ )?\d+ (passed|failed).* in [0-9.]+s', 'IgnoreCase')
# Each pytest summary line (for the counts of Get-FailIds and of the split halves).
$script:SummaryRe = [regex]::new('^(=+ )?\d+ (passed|failed|errors?|skipped|deselected|xfailed|xpassed|warnings?)\b.* in [0-9.]+s')
# A failure line of the short test summary: group 2 is the id, group 5 is the line text.
$script:FailRe = [regex]::new('^(FAILED|ERROR) ([^\s\[]+(\[.*?\])?)( - (.*))?$')
$script:RedCountRe = [regex]::new('(\d+) (?:failed|errors?)\b')
$script:CollectRe = [regex]::new('^(\d+) tests? collected')
$script:ShortMark = 'short test summary info'
$script:RerunArgs = @('-n', '0', '-p', 'no:cacheprovider', '-rfE', '--tb=short')
$script:PytestEnv = @{ COLUMNS = '200' }
$script:Utf8 = [Text.UTF8Encoding]::new($false)

# ---- Private functions.

# The lines of a text file, without line ends, one output item each. A missing file throws
# receipt_missing:<path>.
function Read-Lines([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        Write-Host "receipt_missing $Path"
        throw "receipt_missing:$Path"
    }
    $text = [IO.File]::ReadAllText((Resolve-FullPath $Path))
    if ($text.Length -eq 0) { return }
    $lines = $text -split "`r?`n"
    if ($lines[-1] -eq '') { $lines = $lines[0..($lines.Count - 2)] }
    $lines
}

function Resolve-FullPath([string]$Path) {
    $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($Path)
}

function Write-Tail([string]$Path, [int]$Count = 30) {
    if (Test-Path -LiteralPath $Path -PathType Leaf) {
        Get-Content -LiteralPath $Path -Tail $Count | ForEach-Object { Write-Host $_ }
    }
}

function Write-Text([string]$Path, [string[]]$Lines) {
    $text = ($Lines | ForEach-Object { "$_`n" }) -join ''
    [IO.File]::WriteAllText((Resolve-FullPath $Path), $text, $script:Utf8)
}

# The FAIL_LINE normalization of one line text.
function Get-NormalLine([string]$Line) {
    $Line = $Line -creplace '0x[0-9a-f]+', '0x?'
    $Line = $Line -creplace 'pytest-\d+', 'pytest-N'
    $Line -creplace '\bgw\d+\b', 'gwN'
}

# The next free number n of the items "<prefix><n><suffix>" in $Dir: one more than the highest.
function Get-NextNumber([string]$Dir, [string]$Prefix, [string]$Suffix) {
    $re = [regex]::new('^' + [regex]::Escape($Prefix) + '(\d+)' + [regex]::Escape($Suffix) + '$')
    $high = 0
    foreach ($item in @(Get-ChildItem -LiteralPath $Dir -Force -ErrorAction Stop)) {
        $m = $re.Match($item.Name)
        if ($m.Success -and [int]$m.Groups[1].Value -gt $high) { $high = [int]$m.Groups[1].Value }
    }
    $high + 1
}

# Run $Command (an array: the program and its first arguments) with $Arguments. All output goes
# to $Path. The variables of $Environment are set for the run only. Returns the exit code.
function Invoke-NativeToFile([string[]]$Command, [string[]]$Arguments, [string]$Path, [hashtable]$Environment = @{}) {
    $ErrorActionPreference = 'Continue'
    $PSNativeCommandUseErrorActionPreference = $false
    $exe = $Command[0]
    if (-not (Get-Command -Name $exe -CommandType Application -ErrorAction SilentlyContinue)) {
        Write-Host "no_program $exe"
        throw "no_program:$exe"
    }
    $pre = @($Command | Select-Object -Skip 1)
    $saved = @{}
    foreach ($k in $Environment.Keys) {
        $saved[$k] = [Environment]::GetEnvironmentVariable($k)
        [Environment]::SetEnvironmentVariable($k, $Environment[$k])
    }
    $encoding = [Console]::OutputEncoding
    try {
        try { [Console]::OutputEncoding = $script:Utf8 } catch { Write-Verbose "console encoding kept: $($_.Exception.Message)" }
        & $exe @pre @Arguments *> (Resolve-FullPath $Path)
        $code = $LASTEXITCODE
    } finally {
        foreach ($k in $saved.Keys) { [Environment]::SetEnvironmentVariable($k, $saved[$k]) }
        try { [Console]::OutputEncoding = $encoding } catch { Write-Verbose "console encoding not restored: $($_.Exception.Message)" }
    }
    $code
}

# The counts of one pytest summary line.
function Get-SummaryCounts([string]$Line) {
    $counts = [ordered]@{ passed = 0; failed = 0; errors = 0; skipped = 0; xfailed = 0; xpassed = 0; deselected = 0 }
    foreach ($m in [regex]::Matches($Line, '(\d+) (passed|failed|errors?|skipped|xfailed|xpassed|deselected)\b')) {
        $word = $m.Groups[2].Value
        if ($word -like 'error*') { $word = 'errors' }
        $counts[$word] += [int]$m.Groups[1].Value
    }
    $counts
}

function Get-RunTotal($Counts) {
    $Counts.passed + $Counts.failed + $Counts.errors + $Counts.skipped + $Counts.xfailed + $Counts.xpassed
}

# ---- Exported functions.

function Set-PyTemp {
    <#
    .SYNOPSIS
        Make the folder -Path and set TMP, TEMP and TMPDIR to its full path.
    #>
    [CmdletBinding()]
    param([Parameter(Mandatory, Position = 0)][ValidateNotNullOrEmpty()][string]$Path)
    New-Item -ItemType Directory -Force -Path $Path -ErrorAction Stop | Out-Null
    $full = (Resolve-Path -LiteralPath $Path -ErrorAction Stop).ProviderPath
    $env:TMP = $full
    $env:TEMP = $full
    $env:TMPDIR = $full
}

function Get-FailIds {
    <#
    .SYNOPSIS
        Read the FAILED and ERROR lines of a pytest -rfE receipt.
    .DESCRIPTION
        Reads only the lines after the "short test summary info" header. Each line that matches
        ^(FAILED|ERROR) ([^\s\[]+(\[.*?\])?)( - (.*))?$ gives the id (group 2) and the line text
        (group 5), normalized: 0x<hex> becomes 0x?, pytest-<n> becomes pytest-N, gw<n> becomes gwN.
        For an id with two lines, the first line is kept. When the receipt has a summary line, the
        count of the ids must equal the failed count plus the error count of the last summary line.
    .OUTPUTS
        One object {Id; Line} per id, sorted by id (ordinal).
    #>
    [CmdletBinding()]
    param([Parameter(Mandatory, Position = 0)][ValidateNotNullOrEmpty()][string]$Receipt)
    $lines = @(Read-Lines $Receipt)
    $found = [Collections.Generic.Dictionary[string, string]]::new([StringComparer]::Ordinal)
    $start = -1
    for ($i = 0; $i -lt $lines.Count; $i++) {
        if ($lines[$i].Contains($script:ShortMark)) { $start = $i; break }
    }
    if ($start -ge 0) {
        for ($i = $start + 1; $i -lt $lines.Count; $i++) {
            $m = $script:FailRe.Match($lines[$i].TrimEnd())
            if (-not $m.Success) { continue }
            $id = $m.Groups[2].Value
            if (-not $found.ContainsKey($id)) { $found[$id] = Get-NormalLine $m.Groups[5].Value }
        }
    }
    $summaries = @($lines | Where-Object { $script:SummaryRe.IsMatch($_.Trim()) })
    if ($summaries.Count) {
        $want = 0
        foreach ($m in $script:RedCountRe.Matches($summaries[-1])) { $want += [int]$m.Groups[1].Value }
        if ($want -ne $found.Count) {
            Write-Host "fail_ids_short $Receipt summary: $($summaries[-1])"
            throw "fail_ids_short:$($found.Count)!=$want"
        }
    }
    $ids = [string[]]@($found.Keys)
    [Array]::Sort($ids, [StringComparer]::Ordinal)
    foreach ($id in $ids) { [pscustomobject]@{ Id = $id; Line = $found[$id] } }
}

function Assert-Run {
    <#
    .SYNOPSIS
        Check a pytest receipt: exit 0 or 1, and exactly one summary line. Returns the summary line.
    .EXAMPLE
        Assert-Run "$r/base.txt" $code
    #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory, Position = 0)][ValidateNotNullOrEmpty()][string]$Receipt,
        [Parameter(Mandatory, Position = 1)][int]$Code
    )
    if ($Code -notin 0, 1) {
        Write-Tail $Receipt
        throw "run_fail code=$Code"
    }
    $summaries = @(Read-Lines $Receipt | Where-Object { $script:RunSummaryRe.IsMatch($_) })
    if ($summaries.Count -ne 1) {
        Write-Tail $Receipt
        Write-Host "summary_lines $($summaries.Count)"
        throw 'no_summary'
    }
    $summaries[0]
}

function Assert-NoNewRed {
    <#
    .SYNOPSIS
        Check that each red of the receipts is a base fail or an allowed id. Returns no_new_red.
    .DESCRIPTION
        A base file line is <id> or <id><tab><line>. An <id> entry accepts any failure line of that
        id. An <id><tab><line> entry accepts only the same normalized line. -Allow ids accept any
        line. With -Python and -RerunDir, each new red runs again alone (Invoke-RedRerun), both
        receipts stay, and the function still throws not_green.
    #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory, Position = 0)][ValidateNotNullOrEmpty()][string[]]$Receipt,
        [Parameter(Mandatory, Position = 1)][ValidateNotNullOrEmpty()][string]$BaseFail,
        [Parameter(Position = 2)][AllowEmptyCollection()][string[]]$Allow = @(),
        [string[]]$Python,
        [string]$RerunDir
    )
    if ([bool]$Python -ne [bool]$RerunDir) {
        Write-Host 'rerun_args -Python and -RerunDir go together'
        throw 'rerun_args'
    }
    if (-not (Test-Path -LiteralPath $BaseFail -PathType Leaf)) {
        Write-Host "no_base_fail $BaseFail"
        throw 'no_base_fail'
    }
    $anyLine = [Collections.Generic.HashSet[string]]::new([StringComparer]::Ordinal)
    $lineOf = [Collections.Generic.Dictionary[string, Collections.Generic.HashSet[string]]]::new([StringComparer]::Ordinal)
    foreach ($entry in @(Read-Lines $BaseFail)) {
        if (-not $entry.Trim()) { continue }
        $id, $line = $entry -split "`t", 2
        if ($null -eq $line) {
            [void]$anyLine.Add($id)
        } else {
            if (-not $lineOf.ContainsKey($id)) { $lineOf[$id] = [Collections.Generic.HashSet[string]]::new([StringComparer]::Ordinal) }
            [void]$lineOf[$id].Add((Get-NormalLine $line))
        }
    }
    foreach ($a in @($Allow)) { if ($a) { [void]$anyLine.Add($a) } }
    $new = [Collections.Generic.List[object]]::new()
    $seen = [Collections.Generic.HashSet[string]]::new([StringComparer]::Ordinal)
    foreach ($rec in $Receipt) {
        foreach ($red in @(Get-FailIds -Receipt $rec)) {
            if ($anyLine.Contains($red.Id)) { continue }
            if ($lineOf.ContainsKey($red.Id) -and $lineOf[$red.Id].Contains($red.Line)) { continue }
            if ($seen.Add("$($red.Id)`t$($red.Line)")) {
                $new.Add([pscustomobject]@{ Id = $red.Id; Line = $red.Line; Receipt = $rec })
            }
        }
    }
    if ($new.Count -eq 0) { return 'no_new_red' }
    foreach ($red in $new) { Write-Host "new_red $($red.Id)`t$($red.Line)`t$($red.Receipt)" }
    if ($Python) {
        $ids = @($new | ForEach-Object Id | Select-Object -Unique)
        foreach ($r in @(Invoke-RedRerun -Python $Python -Ids $ids -Out $RerunDir)) {
            Write-Host "rerun $($r.Id) red=$($r.Red) line=$($r.Line) receipt=$($r.Receipt)"
        }
    }
    throw 'not_green'
}

function Invoke-RedRerun {
    <#
    .SYNOPSIS
        Run each id again alone: one process per id, one new receipt <Out>/rerun-<k>.txt per id.
    .DESCRIPTION
        Each run is <Python> -m pytest <id> -n 0 -p no:cacheprovider -rfE --tb=short, with
        COLUMNS=200. A receipt that exists is never written. Exit 0 or 1 is a result; each other
        exit code throws rerun_exit:<c>.
    .OUTPUTS
        One object {Id; Red; Line; Receipt} per id.
    #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][ValidateNotNullOrEmpty()][string[]]$Python,
        [Parameter(Mandatory)][ValidateNotNullOrEmpty()][string[]]$Ids,
        [Parameter(Mandatory)][ValidateNotNullOrEmpty()][string]$Out
    )
    New-Item -ItemType Directory -Force -Path $Out -ErrorAction Stop | Out-Null
    foreach ($id in $Ids) {
        $k = Get-NextNumber $Out 'rerun-' '.txt'
        $rec = Join-Path $Out "rerun-$k.txt"
        if (Test-Path -LiteralPath $rec) {
            Write-Host "rerun_exists $rec"
            throw "rerun_exists:$rec"
        }
        $code = Invoke-NativeToFile -Command $Python -Arguments (@('-m', 'pytest', $id) + $script:RerunArgs) -Path $rec -Environment $script:PytestEnv
        [IO.File]::AppendAllText((Resolve-FullPath $rec), "rerun_exit $code`n", $script:Utf8)
        if ($code -notin 0, 1) {
            Write-Tail $rec
            throw "rerun_exit:$code"
        }
        $hit = @(Get-FailIds -Receipt $rec | Where-Object { $_.Id -ceq $id })
        [pscustomobject]@{
            Id      = $id
            Red     = [bool]$hit.Count
            Line    = $(if ($hit.Count) { $hit[0].Line } else { '' })
            Receipt = $rec
        }
    }
}

function Add-BaseFail {
    <#
    .SYNOPSIS
        Apply the base rule to the reds of a split run. Returns base_fail=<n> intermittent=<m>.
    .DESCRIPTION
        Each red of -Split (the output of Invoke-GuardSplit, or any object with Reds of
        {Id; Line; Receipt}) runs again alone (Invoke-RedRerun, receipts beside -Out). Red twice
        goes to -Out as <id><tab><line>, with the line of the second run. Red one time goes to
        intermittent.txt beside -Out as
        <id><tab>intermittent; cause unconfirmed<tab><first receipt><tab><second receipt>.
        Both files are written again on each call.
    #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory, ValueFromPipeline)][object]$Split,
        [Parameter(Mandatory)][ValidateNotNullOrEmpty()][string[]]$Python,
        [Parameter(Mandatory)][ValidateNotNullOrEmpty()][string]$Out
    )
    begin { $reds = [Collections.Generic.List[object]]::new() }
    process {
        if (-not $Split.PSObject.Properties['Reds']) {
            Write-Host 'add_base_bad_split the split has no Reds'
            throw 'add_base_bad_split'
        }
        foreach ($red in @($Split.Reds)) { if ($null -ne $red) { $reds.Add($red) } }
    }
    end {
        $dir = Split-Path -Parent (Resolve-FullPath $Out)
        New-Item -ItemType Directory -Force -Path $dir -ErrorAction Stop | Out-Null
        $first = [ordered]@{}
        foreach ($red in $reds) { if (-not $first.Contains($red.Id)) { $first[$red.Id] = $red } }
        $base = [Collections.Generic.List[string]]::new()
        $flaky = [Collections.Generic.List[string]]::new()
        if ($first.Count) {
            $again = @(Invoke-RedRerun -Python $Python -Ids ([string[]]@($first.Keys)) -Out $dir)
            foreach ($r in $again) {
                if ($r.Red) {
                    $base.Add("$($r.Id)`t$($r.Line)")
                } else {
                    $flaky.Add("$($r.Id)`tintermittent; cause unconfirmed`t$($first[$r.Id].Receipt)`t$($r.Receipt)")
                }
            }
        }
        Write-Text $Out $base
        Write-Text (Join-Path $dir 'intermittent.txt') $flaky
        "base_fail=$($base.Count) intermittent=$($flaky.Count)"
    }
}

function Invoke-GuardSplit {
    <#
    .SYNOPSIS
        Run the guard files in two halves with a count check, in a new attempt folder.
    .DESCRIPTION
        One unsplit "--collect-only -q" run gives N. Half 1 runs -m "not serial" -n <w> --dist
        loadfile. Half 2 runs -m serial -n 0. <w> is the integer in the variable that -WorkersEnv
        names, else -Workers. Each run uses -Python, -p no:cacheprovider, COLUMNS=200 and
        Set-PyTemp <folder>/tmp; the halves also use -rfE --tb=short. The environment is restored
        after the runs. Exit 0 or 1 needs one summary line. Exit 5 is accepted only for half 2, and
        only when no guard file holds "mark.serial". The sum of passed, failed, errors, skipped,
        xfailed and xpassed of both halves must equal N. Each call makes a new folder
        <Receipts>/split-<Phase>-a<n> and writes collect.txt, half1.txt, half2.txt and split.json.
    .OUTPUTS
        {Folder; N; Counts; Reds}. Reds holds {Id; Line; Receipt} for each red of the halves.
    #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][ValidateNotNullOrEmpty()][string[]]$Python,
        [Parameter(Mandatory)][ValidateNotNullOrEmpty()][string[]]$Guards,
        [Parameter(Mandatory)][ValidateNotNullOrEmpty()][string]$Receipts,
        [int]$Workers = 4,
        [string]$WorkersEnv,
        [Parameter(Mandatory)][ValidatePattern('^[A-Za-z0-9._-]+$')][string]$Phase
    )
    $w = $Workers
    if ($WorkersEnv) {
        $v = [Environment]::GetEnvironmentVariable($WorkersEnv)
        if (-not [string]::IsNullOrWhiteSpace($v)) {
            $n = 0
            if (-not [int]::TryParse($v.Trim(), [ref]$n)) {
                Write-Host "split_bad_workers $WorkersEnv=$v"
                throw 'split_bad_workers'
            }
            $w = $n
        }
    }
    if ($w -lt 1) {
        Write-Host "split_bad_workers workers=$w"
        throw 'split_bad_workers'
    }
    foreach ($g in $Guards) {
        if (-not (Test-Path -LiteralPath $g -PathType Leaf)) {
            Write-Host "split_guard_missing $g"
            throw "split_guard_missing:$g"
        }
    }
    $serial = [bool]@(Select-String -LiteralPath $Guards -SimpleMatch -Pattern 'mark.serial' -List).Count
    $root = Resolve-FullPath $Receipts
    New-Item -ItemType Directory -Force -Path $root -ErrorAction Stop | Out-Null
    $folder = Join-Path $root "split-$Phase-a$(Get-NextNumber $root "split-$Phase-a" '')"
    New-Item -ItemType Directory -Path $folder -ErrorAction Stop | Out-Null

    $saved = @{}
    foreach ($k in 'TMP', 'TEMP', 'TMPDIR') { $saved[$k] = [Environment]::GetEnvironmentVariable($k) }
    $counts = [ordered]@{}
    $codes = [ordered]@{}
    $reds = [Collections.Generic.List[object]]::new()
    try {
        Set-PyTemp -Path (Join-Path $folder 'tmp')
        $collect = Join-Path $folder 'collect.txt'
        $code = Invoke-NativeToFile -Command $Python -Arguments (@('-m', 'pytest') + $Guards + @('--collect-only', '-q', '-p', 'no:cacheprovider')) -Path $collect -Environment $script:PytestEnv
        $nLine = @(Read-Lines $collect | Where-Object { $script:CollectRe.IsMatch($_.Trim()) })
        if ($code -ne 0 -or $nLine.Count -ne 1) {
            Write-Tail $collect
            Write-Host "split_collect_fail code=$code lines=$($nLine.Count)"
            throw 'split_collect_fail'
        }
        $total = [int]$script:CollectRe.Match($nLine[0].Trim()).Groups[1].Value
        $halves = [ordered]@{
            half1 = @('-m', 'not serial', '-n', "$w", '--dist', 'loadfile')
            half2 = @('-m', 'serial', '-n', '0')
        }
        foreach ($half in $halves.Keys) {
            $rec = Join-Path $folder "$half.txt"
            $code = Invoke-NativeToFile -Command $Python -Arguments (@('-m', 'pytest') + $Guards + $halves[$half] + @('-p', 'no:cacheprovider', '-rfE', '--tb=short')) -Path $rec -Environment $script:PytestEnv
            $codes[$half] = $code
            if ($code -eq 5 -and $half -eq 'half2') {
                if ($serial) {
                    Write-Tail $rec
                    throw 'split_exit5_with_serial'
                }
                $counts[$half] = Get-SummaryCounts ''
                continue
            }
            if ($code -notin 0, 1) {
                Write-Tail $rec
                throw "split_run_fail:$half code=$code"
            }
            $sum = @(Read-Lines $rec | Where-Object { $script:SummaryRe.IsMatch($_.Trim()) })
            if ($sum.Count -ne 1) {
                Write-Tail $rec
                throw "split_no_summary:$half"
            }
            $counts[$half] = Get-SummaryCounts $sum[0]
            foreach ($red in @(Get-FailIds -Receipt $rec)) {
                $reds.Add([pscustomobject]@{ Id = $red.Id; Line = $red.Line; Receipt = $rec })
            }
        }
    } finally {
        foreach ($k in $saved.Keys) { [Environment]::SetEnvironmentVariable($k, $saved[$k]) }
    }
    $sumAll = (Get-RunTotal $counts.half1) + (Get-RunTotal $counts.half2)
    $record = [ordered]@{
        phase   = $Phase
        folder  = $folder
        workers = $w
        serial  = $serial
        n       = $total
        sum     = $sumAll
        codes   = $codes
        counts  = $counts
        reds    = @($reds)
    }
    [IO.File]::WriteAllText((Join-Path $folder 'split.json'), ($record | ConvertTo-Json -Depth 6), $script:Utf8)
    if ($sumAll -ne $total) {
        Write-Host "split_count_mismatch half1=$(Get-RunTotal $counts.half1) half2=$(Get-RunTotal $counts.half2) n=$total"
        throw "split_count_mismatch:$sumAll!=$total"
    }
    [pscustomobject]@{ Folder = $folder; N = $total; Counts = $counts; Reds = @($reds) }
}

function Invoke-PolicyRepin {
    <#
    .SYNOPSIS
        Run the re-pin runner dry, then real, in a new attempt folder <Receipts>/repin-a<n>.
    .DESCRIPTION
        The dry call is pwsh -NoProfile -File <Script> -Receipts <attempt>/dry -DryRun. It must
        exit 0 and end with the line repin_dryrun_ok, else repin_dryrun_fail and no real call. The
        real call uses -Receipts <attempt>/real. It must exit 0 and end with repin_ok, else
        repin_fail. -Python and -Repo go to the script when they are given. Returns repin_ok.
    #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][ValidateNotNullOrEmpty()][string]$Script,
        [Parameter(Mandatory)][ValidateNotNullOrEmpty()][string]$Receipts,
        [string]$Python,
        [string]$Repo
    )
    if (-not (Test-Path -LiteralPath $Script -PathType Leaf)) {
        Write-Host "repin_no_script $Script"
        throw "repin_no_script:$Script"
    }
    $root = Resolve-FullPath $Receipts
    New-Item -ItemType Directory -Force -Path $root -ErrorAction Stop | Out-Null
    $attempt = Join-Path $root "repin-a$(Get-NextNumber $root 'repin-a' '')"
    New-Item -ItemType Directory -Path $attempt -ErrorAction Stop | Out-Null
    $pwsh = (Get-Process -Id $PID).Path
    $extra = @()
    if ($Python) { $extra += @('-Python', $Python) }
    if ($Repo) { $extra += @('-Repo', $Repo) }
    foreach ($step in @(
            @{ Name = 'dry'; Flags = @('-DryRun'); Want = 'repin_dryrun_ok'; Token = 'repin_dryrun_fail' },
            @{ Name = 'real'; Flags = @(); Want = 'repin_ok'; Token = 'repin_fail' }
        )) {
        $dir = Join-Path $attempt $step.Name
        New-Item -ItemType Directory -Path $dir -ErrorAction Stop | Out-Null
        $out = Join-Path $attempt "$($step.Name).txt"
        $code = Invoke-NativeToFile -Command @($pwsh) -Arguments (@('-NoProfile', '-File', $Script, '-Receipts', $dir) + $step.Flags + $extra) -Path $out
        $last = @(Read-Lines $out | Where-Object { $_.Trim() }) | Select-Object -Last 1
        if ($code -ne 0 -or $null -eq $last -or $last.Trim() -ne $step.Want) {
            Write-Tail $out
            Write-Host "$($step.Token) code=$code last=$last"
            throw $step.Token
        }
    }
    'repin_ok'
}

Export-ModuleMember -Function Set-PyTemp, Get-FailIds, Assert-Run, Assert-NoNewRed, Invoke-RedRerun, Add-BaseFail, Invoke-GuardSplit, Invoke-PolicyRepin
