# AC-2, AC-3 (PowerShell half), AC-5, AC-11 and AC-15 (Windows half) of the USB kit usability plan, for
# .agent/fleet/usb/setup-windows.ps1: the record it writes on every exit path, the elevation, the Name rule, the PATH
# fix, the prerequisites and the send of the record to the hub.
# Nothing here touches the system: the steps and the commands that change it are mocked, and the record goes to
# TestDrive.
BeforeDiscovery {
    $nameCases = @(
        @{ raw = 'Lab_Mini07'; want = 'lab-mini07' }
        @{ raw = '--Lab PC__2--'; want = 'lab-pc-2' }
        @{ raw = '___'; want = 'member' }
        @{ raw = ('a' * 62) + '_' + ('b' * 7); want = ('a' * 62) }
        @{ raw = 'LAB-PC'; want = 'lab-pc' }
    )
    $tokenCases = @(
        @{ label = 'missing'; token = $null }
        @{ label = 'short'; token = 'short' }
        @{ label = 'bad character'; token = ('a' * 31) + '!' }
        @{ label = 'too long'; token = ('a' * 65) }
    )
}

BeforeAll {
    $script:UsbDir = Join-Path $PSScriptRoot '../../.agent/fleet/usb'
    $script:SetupPath = Join-Path $script:UsbDir 'setup-windows.ps1'
    $script:CmdPath = Join-Path $script:UsbDir 'Setup Windows.cmd'
    $script:FleetUsbPath = (Resolve-Path (Join-Path $script:UsbDir 'fleet_usb.py')).ProviderPath
    $script:LoadError = $null
    # A script that cannot load as a library fails each test body below, never a block.
    try { . $script:SetupPath -LibraryOnly } catch { $script:LoadError = $_.Exception.Message }

    $script:RunId = 'abcd1234efgh5678'
    # Every Step-* function of the script is one step of the run, so a step that a later row adds is mocked too.
    $script:StepNames = @(Get-Command -CommandType Function -Name 'Step-*' -ErrorAction SilentlyContinue | ForEach-Object Name)
    $script:HostKey = 'ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIHk2mQ7c9fV1pXw3sLr8tN0bYc4eZq6uJd5aGh2iKo1m'

    function Assert-Loaded {
        if ($script:LoadError) { throw "setup-windows.ps1 did not load with -LibraryOnly: $script:LoadError" }
    }

    # fleet_usb.py read_record on a file: an empty string when it accepts, its message when it refuses.
    function Test-Record([string]$Path) {
        $code = "import importlib.util, pathlib, sys; s = importlib.util.spec_from_file_location('fleet_usb', sys.argv[1]); " +
            "m = importlib.util.module_from_spec(s); sys.modules['fleet_usb'] = m; s.loader.exec_module(m); " +
            "m.read_record(pathlib.Path(sys.argv[2]))"
        $out = & python -I -c $code $script:FleetUsbPath $Path 2>&1
        if ($LASTEXITCODE -ne 0) { ($out | Out-String) } else { '' }
    }

    function Read-Json([string]$Path) { [IO.File]::ReadAllText($Path) | ConvertFrom-Json }

    function Get-StepStatus($Record, [string]$Id) { @($Record.steps | Where-Object { $_.step -eq $Id }) | Select-Object -First 1 }
}

Describe 'setup-windows.ps1 Invoke-Setup' {
    BeforeEach {
        Assert-Loaded
        $script:usb = Join-Path $TestDrive ([guid]::NewGuid().ToString('N'))
        New-Item -ItemType Directory $script:usb | Out-Null
        $script:recordPath = Join-Path $script:usb 'members/lab-mini07.json'
        foreach ($name in $script:StepNames) { Mock $name { 'fine' } }
        Mock Get-ToolVersion { $null }
        Mock Step-HostKey { @{ detail = 'pinned'; data = @{ Port = 22; HostKey = $script:HostKey; Addresses = @('192.0.2.10') } } }
    }

    It 'AC-2: writes a final record with ok true when every step is ok' {
        $result = Invoke-Setup -Usb $script:usb -RunId $script:RunId -Account 'lab' -ComputerName 'Lab_Mini07'
        $record = Read-Json $script:recordPath
        $record.v | Should -Be 2
        $record.final | Should -BeTrue
        $record.ok | Should -BeTrue
        $record.name | Should -Be 'lab-mini07'
        $record.run_id | Should -Be $script:RunId
        @($record.steps | Where-Object { $_.status -ne 'ok' }) | Should -BeNullOrEmpty
        @($record.steps).Count | Should -Be $script:StepNames.Count
        $record.port | Should -Be 22
        $record.host_key | Should -Be $script:HostKey
        @($record.addresses) | Should -Be @('192.0.2.10')
        Test-Record $script:recordPath | Should -BeNullOrEmpty
        $result.ok | Should -BeTrue
    }

    It 'AC-2: a step that throws ends failed, ok is false and the later steps still run' {
        Mock Step-Firewall { throw 'the firewall rule could not be made' }
        $result = Invoke-Setup -Usb $script:usb -RunId $script:RunId -Account 'lab' -ComputerName 'Lab_Mini07'
        $record = Read-Json $script:recordPath
        $record.final | Should -BeTrue
        $record.ok | Should -BeFalse
        (Get-StepStatus $record 'firewall').status | Should -Be 'failed'
        (Get-StepStatus $record 'firewall').detail | Should -BeLike '*the firewall rule could not be made*'
        (Get-StepStatus $record 'host_key').status | Should -Be 'ok'
        (Get-StepStatus $record 'codex').status | Should -Be 'ok'
        Test-Record $script:recordPath | Should -BeNullOrEmpty
        $result.ok | Should -BeFalse
    }

    It 'AC-2: a step that needs a failed step ends skipped' {
        Mock Step-SshServer { throw 'sshd would not start' }
        Invoke-Setup -Usb $script:usb -RunId $script:RunId -Account 'lab' -ComputerName 'Lab_Mini07' | Out-Null
        $record = Read-Json $script:recordPath
        (Get-StepStatus $record 'ssh_server').status | Should -Be 'failed'
        (Get-StepStatus $record 'hub_key').status | Should -Be 'skipped'
        (Get-StepStatus $record 'hub_key').detail | Should -Be 'needs ssh_server'
        (Get-StepStatus $record 'host_key').status | Should -Be 'skipped'
        (Get-StepStatus $record 'claude').status | Should -Be 'ok'
    }

    It 'AC-2: a checkpoint is on the drive after each step' {
        $script:snapshot = Join-Path $script:usb 'snapshot.json'
        Mock Step-HubKey { Copy-Item -LiteralPath $script:recordPath -Destination $script:snapshot; 'fine' }
        Invoke-Setup -Usb $script:usb -RunId $script:RunId -Account 'lab' -ComputerName 'Lab_Mini07' | Out-Null
        $checkpoint = Read-Json $script:snapshot
        $checkpoint.final | Should -BeFalse
        $checkpoint.ok | Should -BeFalse
        $ids = @($checkpoint.steps | ForEach-Object step)
        $ids | Should -Contain 'elevate'
        $ids | Should -Contain 'ssh_server'
        $ids[-1] | Should -Be 'firewall'
        $ids | Should -Not -Contain 'hub_key'
    }

    It 'AC-2: a step that raises PipelineStoppedException (Ctrl+C) ends failed with detail interrupted, in a final record' {
        # The exception stops the whole pipeline and no catch block sees it, so the probe runs in its own process.
        $probe = Join-Path $script:usb 'probe.ps1'
        $lines = @(
            "param([string]`$Usb)"
            ". '$($script:SetupPath -replace "'", "''")' -LibraryOnly"
        )
        foreach ($name in $script:StepNames) { $lines += "function $name { 'fine' }" }
        $lines += "function Step-Firewall { throw [System.Management.Automation.PipelineStoppedException]::new() }"
        $lines += "Invoke-Setup -Usb `$Usb -RunId '$script:RunId' -Account 'lab' -ComputerName 'Lab_Mini07' | Out-Null"
        [IO.File]::WriteAllLines($probe, $lines)
        & pwsh -NoProfile -File $probe -Usb $script:usb *> $null
        $record = Read-Json $script:recordPath
        $record.final | Should -BeTrue
        $record.ok | Should -BeFalse
        (Get-StepStatus $record 'firewall').status | Should -Be 'failed'
        (Get-StepStatus $record 'firewall').detail | Should -Be 'interrupted'
        @($record.steps | ForEach-Object step)[-1] | Should -Be 'firewall'
        Test-Record $script:recordPath | Should -BeNullOrEmpty
    }
}

Describe 'setup-windows.ps1 elevation' {
    BeforeEach {
        Assert-Loaded
        $script:usb = Join-Path $TestDrive ([guid]::NewGuid().ToString('N'))
        New-Item -ItemType Directory (Join-Path $script:usb 'members') | Out-Null
        $script:recordPath = Join-Path $script:usb 'members/lab-mini07.json'
        Mock Test-Administrator { $false }
        Mock New-RunId { $script:RunId }
        Mock Invoke-Setup { throw 'an unelevated run must not run the steps' }
    }

    It 'AC-2: a UAC prompt that is cancelled (error 1223) leaves a final record: elevate failed, the admin steps skipped' {
        Mock Start-Process { throw [System.ComponentModel.Win32Exception]::new(1223) }
        $result = Start-Setup -Usb $script:usb -ForUser 'Lab User' -ComputerName 'Lab_Mini07' -Self (Join-Path $script:usb 'setup-windows.ps1')
        $record = Read-Json $script:recordPath
        $record.final | Should -BeTrue
        $record.ok | Should -BeFalse
        $record.run_id | Should -Be $script:RunId
        $record.user | Should -Be 'Lab User'
        (Get-StepStatus $record 'elevate').status | Should -Be 'failed'
        (Get-StepStatus $record 'elevate').detail | Should -BeLike 'elevation cancelled or failed: *'
        foreach ($id in @('ssh_server', 'firewall', 'hub_key', 'admin_rights', 'host_key')) {
            (Get-StepStatus $record $id).status | Should -Be 'skipped'
            (Get-StepStatus $record $id).detail | Should -Be 'needs elevate'
        }
        Test-Record $script:recordPath | Should -BeNullOrEmpty
        $result.ok | Should -BeFalse
    }

    It 'AC-2: a child that wrote a final record with this run id leaves the record as it is' {
        $script:final = (@{
                v = 2; run_id = $script:RunId; final = $true; name = 'lab-mini07'; os = 'windows'; user = 'Lab User'; ok = $true
                steps = @(@{ step = 'elevate'; status = 'ok'; detail = '' }); tools = @{}; gui = $true; session_type = 'windows'
                rustdesk_id = $null; port = $null; host_key = $null; addresses = @(); delivery = $null
            } | ConvertTo-Json -Depth 6)
        Mock Start-Process { [IO.File]::WriteAllText($script:recordPath, $script:final); [pscustomobject]@{ ExitCode = 0 } }
        Start-Setup -Usb $script:usb -ForUser 'Lab User' -ComputerName 'Lab_Mini07' -Self (Join-Path $script:usb 'setup-windows.ps1') | Out-Null
        [IO.File]::ReadAllText($script:recordPath) | Should -BeExactly $script:final
    }

    It 'AC-2: a child that left only a checkpoint is finalized by the parent' {
        $script:checkpoint = (@{
                v = 2; run_id = $script:RunId; final = $false; name = 'lab-mini07'; os = 'windows'; user = 'Lab User'; ok = $false
                steps = @(@{ step = 'elevate'; status = 'ok'; detail = '' }, @{ step = 'account'; status = 'ok'; detail = 'Lab User' })
                tools = @{}; gui = $true; session_type = 'windows'; rustdesk_id = $null; port = $null; host_key = $null
                addresses = @(); delivery = $null
            } | ConvertTo-Json -Depth 6)
        Mock Start-Process { [IO.File]::WriteAllText($script:recordPath, $script:checkpoint); [pscustomobject]@{ ExitCode = 1 } }
        $result = Start-Setup -Usb $script:usb -ForUser 'Lab User' -ComputerName 'Lab_Mini07' -Self (Join-Path $script:usb 'setup-windows.ps1')
        $record = Read-Json $script:recordPath
        $record.final | Should -BeTrue
        $record.ok | Should -BeFalse
        (Get-StepStatus $record 'account').status | Should -Be 'ok'
        @($record.steps | Where-Object { $_.status -eq 'failed' }).Count | Should -BeGreaterThan 0
        Test-Record $script:recordPath | Should -BeNullOrEmpty
        $result.ok | Should -BeFalse
    }

    It 'AC-2: a child that checkpointed every step through host_key and then died leaves a record the hub can read' {
        $ids = @('elevate', 'account', 'packages', 'ssh_server', 'firewall', 'hub_key', 'admin_rights', 'pwsh', 'uv', 'claude',
            'codex', 'rustdesk', 'host_key')
        $script:checkpoint = (@{
                v = 2; run_id = $script:RunId; final = $false; name = 'lab-mini07'; os = 'windows'; user = 'Lab User'; ok = $false
                steps = @($ids | ForEach-Object { @{ step = $_; status = 'ok'; detail = '' } })
                tools = @{}; gui = $true; session_type = 'windows'; rustdesk_id = $null; port = 22; host_key = $script:HostKey
                addresses = @('192.0.2.10'); delivery = $null
            } | ConvertTo-Json -Depth 6)
        Mock Start-Process { [IO.File]::WriteAllText($script:recordPath, $script:checkpoint); [pscustomobject]@{ ExitCode = 1 } }
        $result = Start-Setup -Usb $script:usb -ForUser 'Lab User' -ComputerName 'Lab_Mini07' -Self (Join-Path $script:usb 'setup-windows.ps1')
        $record = Read-Json $script:recordPath
        $record.final | Should -BeTrue
        $record.ok | Should -BeFalse
        @($record.steps | Where-Object { $_.step -eq 'elevate' }).Count | Should -Be 1
        (Get-StepStatus $record 'elevate').status | Should -Be 'failed'
        (Get-StepStatus $record 'host_key').status | Should -Be 'ok'
        Test-Record $script:recordPath | Should -BeNullOrEmpty
        $result.ok | Should -BeFalse
    }

    It 'AC-2: the string from Get-ElevatedArgs reaches a script in a folder with a space with -RunId and -ForUser intact' {
        $folder = Join-Path $TestDrive 'Fleet Kit'
        New-Item -ItemType Directory $folder | Out-Null
        $probe = Join-Path $folder 'setup-windows.ps1'
        $out = Join-Path $folder 'received.json'
        [IO.File]::WriteAllText($probe, "param([string]`$RunId, [string]`$ForUser)`r`n" +
            "[IO.File]::WriteAllText((Join-Path `$PSScriptRoot 'received.json'), (@{ RunId = `$RunId; ForUser = `$ForUser } | ConvertTo-Json))`r`n")
        $argumentString = Get-ElevatedArgs $probe $script:RunId 'Lab User'
        $argumentString | Should -BeOfType [string]
        $process = Start-Process -FilePath 'powershell' -ArgumentList $argumentString -Wait -PassThru -WindowStyle Hidden
        $process.ExitCode | Should -Be 0
        $got = Read-Json $out
        $got.RunId | Should -BeExactly $script:RunId
        $got.ForUser | Should -BeExactly 'Lab User'
    }

    It 'AC-2: Setup Windows.cmd holds no exit /b and no -Verb RunAs, and runs setup-windows.ps1' {
        $text = [IO.File]::ReadAllText($script:CmdPath)
        $text | Should -Not -Match '(?i)exit\s+/b'
        $text | Should -Not -Match '(?i)-Verb\s+RunAs'
        $text | Should -Match 'setup-windows\.ps1'
    }
}

Describe 'the Name rule in PowerShell' {
    BeforeEach { Assert-Loaded }

    It 'AC-3: <raw> gives <want>, and the result matches NAME' -ForEach $nameCases {
        $got = ConvertTo-MemberName $raw
        $got | Should -BeExactly $want
        $got | Should -Match '^[a-z0-9][a-z0-9-]{0,62}$'
    }
}

Describe 'the Windows PATH fix' {
    BeforeEach {
        Assert-Loaded
        $script:userPath = 'C:\Tools;C:\Other'
        $script:installed = $false
        Mock Get-PathValue { if ($Scope -eq 'User') { $script:userPath } else { 'C:\Windows' } }
        Mock Set-UserPathValue { $script:userPath = $Value }
        Mock Update-SessionPath {}
        Mock Invoke-Native { $script:installed = $true; 0 }
        Mock Test-OnPath { $script:installed }
        Mock Get-ToolVersion { $null }
    }

    It 'AC-5: %USERPROFILE%\.local\bin is in the User Path once after two runs' {
        $entry = Join-Path $env:USERPROFILE '.local\bin'
        Step-Claude | Out-Null
        $script:installed = $false
        Step-Claude | Out-Null
        Step-Codex | Out-Null
        $found = @($script:userPath -split ';' | Where-Object { $_ -ieq $entry })
        $found.Count | Should -Be 1
        $script:userPath | Should -BeLike 'C:\Tools;C:\Other;*'
    }

    It 'AC-5: a tool missing after its install ends failed with not on PATH after install, and no exception leaves Invoke-Setup' {
        Mock Test-OnPath { $false }
        { Step-Claude } | Should -Throw '*not on PATH after install*'
        $script:usb = Join-Path $TestDrive ([guid]::NewGuid().ToString('N'))
        New-Item -ItemType Directory $script:usb | Out-Null
        foreach ($name in ($script:StepNames | Where-Object { $_ -ne 'Step-Claude' })) { Mock $name { 'fine' } }
        Mock Step-HostKey { @{ detail = 'pinned'; data = @{ Port = 22; HostKey = $script:HostKey; Addresses = @('192.0.2.10') } } }
        { Invoke-Setup -Usb $script:usb -RunId $script:RunId -Account 'lab' -ComputerName 'Lab_Mini07' | Out-Null } | Should -Not -Throw
        $record = Read-Json (Join-Path $script:usb 'members/lab-mini07.json')
        (Get-StepStatus $record 'claude').status | Should -Be 'failed'
        (Get-StepStatus $record 'claude').detail | Should -BeLike '*not on PATH after install*'
        (Get-StepStatus $record 'codex').status | Should -Be 'ok'
    }
}

# AC-11 of the USB kit usability plan: the Windows prerequisites. A fake disk stands in for the machine: winget and
# the installers are mocked, a tool is "installed" when the mocked command puts it on the fake disk, and it is found
# only when its folder is in $env:Path, which Update-SessionPath rebuilds from the Machine and User registry values.
Describe 'the Windows prerequisites' {
    BeforeEach {
        Assert-Loaded
        $script:pathBefore = $env:Path
        $env:Path = 'C:\Windows'
        $homeBin = Join-Path $env:USERPROFILE '.local\bin'
        $script:calls = New-Object System.Collections.Generic.List[object]
        $script:hasWinget = $true
        $script:wingetLands = $true
        $script:wingetExit = @{ 'Git.Git' = 0; 'Python.Python.3.14' = 0; 'Microsoft.PowerShell' = 0 }
        $script:wingetPlaces = @{
            'Git.Git'              = @{ Tool = 'git'; Scope = 'Machine'; Dir = 'C:\FleetTest\Git\cmd' }
            'Python.Python.3.14'   = @{ Tool = 'python'; Scope = 'Machine'; Dir = 'C:\FleetTest\Python314' }
            'Microsoft.PowerShell' = @{ Tool = 'pwsh'; Scope = 'Machine'; Dir = 'C:\FleetTest\PowerShell\7' }
        }
        $script:toolDirs = @{ git = 'C:\FleetTest\Git\cmd'; python = 'C:\FleetTest\Python314'; pwsh = 'C:\FleetTest\PowerShell\7'; uv = $homeBin }
        $script:onDisk = @{}
        $script:userPath = 'C:\FleetTest\Other'
        $script:machinePath = 'C:\Windows'
        Mock Get-PathValue { if ($Scope -eq 'User') { $script:userPath } else { $script:machinePath } }
        Mock Set-UserPathValue { $script:userPath = $Value }
        Mock Test-OnPath {
            if ($Name -eq 'winget') { return $script:hasWinget }
            $dir = $script:toolDirs[$Name]
            return [bool]($dir -and $script:onDisk[$Name] -and (@($env:Path -split ';') -contains $dir))
        }
        Mock Invoke-Native {
            $script:calls.Add([pscustomobject]@{ File = $File; Arguments = @($Arguments) })
            if ($File -eq 'winget') {
                $id = $Arguments[2]
                $code = $script:wingetExit[$id]
                if ($code -eq 0 -and $script:wingetLands) {
                    $place = $script:wingetPlaces[$id]
                    $script:onDisk[$place.Tool] = $true
                    if ($place.Scope -eq 'User') { $script:userPath += ';' + $place.Dir } else { $script:machinePath += ';' + $place.Dir }
                }
                return $code
            }
            if ($File -eq 'powershell.exe') { $script:onDisk['uv'] = $true }
            return 0
        }
    }

    AfterEach { $env:Path = $script:pathBefore }

    It 'AC-11: the step list puts packages after account and pwsh and uv before claude, and pwsh, uv, claude and codex need account' {
        $steps = @(Get-SetupSteps)
        (@($steps | ForEach-Object Id) -join ',') | Should -BeExactly 'elevate,account,packages,ssh_server,firewall,hub_key,admin_rights,pwsh,uv,claude,codex,rustdesk,host_key'
        foreach ($id in @('pwsh', 'uv', 'claude', 'codex')) {
            @($steps | Where-Object { $_.Id -eq $id }).Needs | Should -Contain 'account'
        }
        @($steps | Where-Object { $_.Id -eq 'packages' }).Fn | Should -BeExactly 'Step-Packages'
    }

    It 'AC-11: winget installs Git.Git, Python.Python.3.14 and Microsoft.PowerShell with -e --silent and both agreement flags' {
        Step-Packages | Out-Null
        Step-Pwsh | Out-Null
        $winget = @($script:calls | Where-Object { $_.File -eq 'winget' })
        $winget.Count | Should -Be 3
        (@($winget | ForEach-Object { $_.Arguments[2] }) -join ',') | Should -BeExactly 'Git.Git,Python.Python.3.14,Microsoft.PowerShell'
        foreach ($call in $winget) {
            $call.Arguments[0] | Should -BeExactly 'install'
            $call.Arguments[1] | Should -BeExactly '--id'
            (@($call.Arguments)[3..($call.Arguments.Count - 1)] -join ' ') | Should -BeExactly '-e --silent --accept-package-agreements --accept-source-agreements'
        }
    }

    It 'AC-11: winget exit <name> counts as already installed, so packages and pwsh end ok' -ForEach @(
        @{ name = '0x8A15002B (signed)'; code = -1978335189 }
        @{ name = '0x8A15002B (unsigned)'; code = 2316632107 }
        @{ name = '0x8A150061 (signed)'; code = -1978335135 }
        @{ name = '0x8A150061 (unsigned)'; code = 2316632161 }
    ) {
        $script:onDisk = @{ git = $true; python = $true; pwsh = $true }
        $script:machinePath = 'C:\Windows;C:\FleetTest\Git\cmd;C:\FleetTest\Python314;C:\FleetTest\PowerShell\7'
        foreach ($id in @($script:wingetExit.Keys)) { $script:wingetExit[$id] = $code }
        (Step-Packages) | Should -BeLike '*already installed*'
        (Step-Pwsh) | Should -BeLike '*already installed*'
    }

    It 'AC-11: a winget failure fails the step and the next package is still tried' {
        $script:wingetExit['Git.Git'] = 1603
        { Step-Packages } | Should -Throw '*Git.Git*1603*'
        @($script:calls | Where-Object { $_.File -eq 'winget' } | ForEach-Object { $_.Arguments[2] }) | Should -Contain 'Python.Python.3.14'
    }

    It 'AC-11: a tool that the installer adds only to the User Path registry value is found after the PATH rebuild' {
        $script:wingetPlaces['Git.Git'].Scope = 'User'
        Step-Packages | Should -Not -BeNullOrEmpty
        $script:userPath | Should -BeLike '*C:\FleetTest\Git\cmd*'
        $script:machinePath | Should -Not -BeLike '*Git*'
        @($env:Path -split ';') | Should -Contain 'C:\FleetTest\Git\cmd'
    }

    It 'AC-11: a tool that is still missing after a good winget exit ends the step failed with not on PATH after install' {
        $script:wingetLands = $false
        { Step-Packages } | Should -Throw '*not on PATH after install*'
        { Step-Pwsh } | Should -Throw '*not on PATH after install*'
    }

    It 'AC-11: uv installs with its official PowerShell installer, is put on the User Path once and ends ok' {
        Step-Uv | Should -Be 'installed'
        $curl = @($script:calls | Where-Object { $_.File -eq 'curl.exe' })
        $curl.Count | Should -Be 1
        $curl[0].Arguments | Should -Contain 'https://astral.sh/uv/install.ps1'
        @($script:calls | Where-Object { $_.File -eq 'powershell.exe' }).Count | Should -Be 1
        $entry = Join-Path $env:USERPROFILE '.local\bin'
        @($script:userPath -split ';' | Where-Object { $_ -ieq $entry }).Count | Should -Be 1
    }

    It 'AC-11: tools holds the versions of git, python, pwsh, uv, claude and codex, read after the PATH rebuild, and a missing tool has no key' {
        $homeBin = Join-Path $env:USERPROFILE '.local\bin'
        $script:userPath = "C:\FleetTest\Other;$homeBin"
        $script:machinePath = 'C:\Windows;C:\FleetTest\Git\cmd;C:\FleetTest\PowerShell\7'
        $script:dirOf = @{ git = 'C:\FleetTest\Git\cmd'; py = 'C:\Windows'; pwsh = 'C:\FleetTest\PowerShell\7'; uv = $homeBin; claude = $homeBin }
        $script:versionOf = @{
            git = 'git version 2.47.1.windows.1'; py = 'Python 3.14.0'; pwsh = 'PowerShell 7.5.1'; uv = 'uv 0.9.5'; claude = '2.1.0 (Claude Code)'
        }
        Mock Get-ToolVersion {
            $dir = $script:dirOf[$Command]
            if ($dir -and (@($env:Path -split ';') -contains $dir)) { return $script:versionOf[$Command] }
            return $null
        }
        $tools = Get-ToolVersions
        $tools['git'] | Should -BeExactly 'git version 2.47.1.windows.1'
        $tools['python'] | Should -BeExactly 'Python 3.14.0'
        $tools['pwsh'] | Should -BeExactly 'PowerShell 7.5.1'
        $tools['uv'] | Should -BeExactly 'uv 0.9.5'
        $tools['claude'] | Should -BeExactly '2.1.0 (Claude Code)'
        @($tools.Keys) | Should -Not -Contain 'codex'
    }

    It 'AC-11: the final record holds the tool versions, no key for a missing tool, and fleet_usb.py accepts it' {
        $script:usb = Join-Path $TestDrive ([guid]::NewGuid().ToString('N'))
        New-Item -ItemType Directory $script:usb | Out-Null
        foreach ($name in $script:StepNames) { Mock $name { 'fine' } }
        Mock Step-HostKey { @{ detail = 'pinned'; data = @{ Port = 22; HostKey = $script:HostKey; Addresses = @('192.0.2.10') } } }
        Mock Get-ToolVersion {
            switch ($Command) {
                'git' { 'git version 2.47.1.windows.1' }
                'uv' { 'uv 0.9.5' }
                default { $null }
            }
        }
        Invoke-Setup -Usb $script:usb -RunId $script:RunId -Account 'lab' -ComputerName 'Lab_Mini07' | Out-Null
        $recordPath = Join-Path $script:usb 'members/lab-mini07.json'
        $record = Read-Json $recordPath
        $record.tools.git | Should -BeExactly 'git version 2.47.1.windows.1'
        $record.tools.uv | Should -BeExactly 'uv 0.9.5'
        @($record.tools.PSObject.Properties.Name) | Should -Not -Contain 'codex'
        $env:Path = $script:pathBefore   # the fixture narrowed it; Test-Record runs python
        Test-Record $recordPath | Should -BeNullOrEmpty
    }

    It 'AC-11: with no winget, packages and pwsh end failed with the App Installer detail, nothing throws and the record is final' {
        $script:hasWinget = $false
        $script:usb = Join-Path $TestDrive ([guid]::NewGuid().ToString('N'))
        New-Item -ItemType Directory $script:usb | Out-Null
        foreach ($name in ($script:StepNames | Where-Object { $_ -notin @('Step-Packages', 'Step-Pwsh') })) { Mock $name { 'fine' } }
        Mock Step-HostKey { @{ detail = 'pinned'; data = @{ Port = 22; HostKey = $script:HostKey; Addresses = @('192.0.2.10') } } }
        { Invoke-Setup -Usb $script:usb -RunId $script:RunId -Account 'lab' -ComputerName 'Lab_Mini07' | Out-Null } | Should -Not -Throw
        $recordPath = Join-Path $script:usb 'members/lab-mini07.json'
        $record = Read-Json $recordPath
        $record.final | Should -BeTrue
        $record.ok | Should -BeFalse
        foreach ($id in @('packages', 'pwsh')) {
            (Get-StepStatus $record $id).status | Should -Be 'failed'
            (Get-StepStatus $record $id).detail | Should -Be 'install App Installer from the Microsoft Store'
        }
        (Get-StepStatus $record 'claude').status | Should -Be 'ok'
        (Get-StepStatus $record 'host_key').status | Should -Be 'ok'
        $env:Path = $script:pathBefore   # the fixture narrowed it; Test-Record runs python
        Test-Record $recordPath | Should -BeNullOrEmpty
    }
}

Describe 'Test-OnPath and the Microsoft Store python alias' {
    BeforeEach {
        Assert-Loaded
        $script:pathBefore = $env:Path
        $script:store = Join-Path $TestDrive 'Microsoft\WindowsApps'
        $script:real = Join-Path $TestDrive 'Python314'
        New-Item -ItemType Directory $script:store, $script:real -Force | Out-Null
        foreach ($file in @((Join-Path $script:store 'python.exe'), (Join-Path $script:store 'python3.exe'), (Join-Path $script:store 'winget.exe'), (Join-Path $script:real 'python.exe'))) {
            [IO.File]::WriteAllText($file, '')
        }
    }

    AfterEach { $env:Path = $script:pathBefore }

    It 'AC-11: the python.exe stub in WindowsApps is not a Python on PATH, and winget.exe in the same folder is a tool' {
        $env:Path = $script:store
        Test-OnPath 'python' | Should -BeFalse
        Test-OnPath 'python3' | Should -BeFalse
        Test-OnPath 'winget' | Should -BeTrue
    }

    It 'AC-11: a python.exe outside WindowsApps is found even when the stub comes first on PATH' {
        $env:Path = "$($script:store);$($script:real)"
        Test-OnPath 'python' | Should -BeTrue
    }
}

Describe 'setup-windows.ps1 send to the hub' {
    BeforeAll {
        # hub.txt as prepare writes it: the url lines, the extra lines, then the token line.
        function Set-HubFile([string]$Usb, [string[]]$Urls, [string]$Token, [string[]]$Extra = @(), [string]$Eol = "`n") {
            $lines = @($Urls | ForEach-Object { "url=$_" }) + @($Extra)
            if ($Token) { $lines += "token=$Token" }
            [IO.File]::WriteAllText((Join-Path $Usb 'hub.txt'), (($lines -join $Eol) + $Eol), (New-Object Text.UTF8Encoding $false))
        }

        function Invoke-Run {
            Invoke-Setup -Usb $script:usb -RunId $script:RunId -Account 'lab' -ComputerName 'Lab_Mini07'
        }
    }

    BeforeEach {
        Assert-Loaded
        $script:usb = Join-Path $TestDrive ([guid]::NewGuid().ToString('N'))
        New-Item -ItemType Directory $script:usb | Out-Null
        $script:recordPath = Join-Path $script:usb 'members/lab-mini07.json'
        $script:token = 'abcdefghij0123456789ABCDEFGHIJ_-'
        $script:urls = @('http://192.0.2.1:8771', 'http://192.0.2.2:8771', 'http://192.0.2.3:8771')
        $script:route = '/v1/usb-record'
        # What each POST saw, kept at the moment of the call: its arguments, the body file and the drive copy.
        $script:posts = New-Object System.Collections.Generic.List[object]
        # URL -> @{ Code; Exit }. A URL that is not here fails with curl exit 7.
        $script:answers = @{}
        foreach ($name in $script:StepNames) { Mock $name { 'fine' } }
        Mock Get-ToolVersion { $null }
        Mock Step-HostKey { @{ detail = 'pinned'; data = @{ Port = 22; HostKey = $script:HostKey; Addresses = @('192.0.2.10') } } }
        Mock Get-CurlPath { 'C:\stub\curl.exe' }
        Mock Invoke-Curl {
            $url = $Arguments[-1]
            $at = [array]::IndexOf($Arguments, '--data-binary')
            $bodyFile = $Arguments[$at + 1].Substring(1)
            $copy = Join-Path $script:usb "at-post-$($script:posts.Count + 1).json"
            Copy-Item -LiteralPath $script:recordPath -Destination $copy
            $script:posts.Add([pscustomobject]@{
                    Curl = $Curl; Args = ($Arguments -join ' '); Url = $url; Body = (Read-Json $bodyFile)
                    Drive = (Read-Json $script:recordPath); DriveFile = $copy
                })
            $answer = $script:answers[($url -replace '/v1/usb-record$', '')]
            if ($answer) { [pscustomobject]@{ Exit = $answer.Exit; Output = $answer.Code } }
            else { [pscustomobject]@{ Exit = 7; Output = '000' } }
        }
    }

    It 'AC-15: each URL is tried in order and the send stops at the first 200' {
        Set-HubFile $script:usb $script:urls $script:token
        $script:answers[$script:urls[0]] = @{ Code = '503'; Exit = 0 }
        $script:answers[$script:urls[1]] = @{ Code = '200'; Exit = 0 }
        $script:answers[$script:urls[2]] = @{ Code = '200'; Exit = 0 }
        $result = Invoke-Run
        $script:posts.Count | Should -Be 2
        $script:posts[0].Url | Should -Be ($script:urls[0] + $script:route)
        $script:posts[1].Url | Should -Be ($script:urls[1] + $script:route)
        $record = Read-Json $script:recordPath
        $record.delivery.status | Should -Be 'sent'
        $record.delivery.detail | Should -Be $script:urls[1]
        Test-Record $script:recordPath | Should -BeNullOrEmpty
        $result.ok | Should -BeTrue
    }

    It 'AC-15: the request carries the token header, the timeouts and the record file, and the token is never printed' {
        Set-HubFile $script:usb $script:urls $script:token
        $script:answers[$script:urls[0]] = @{ Code = '200'; Exit = 0 }
        $shown = (Invoke-Run 6>&1 | Out-String)
        $script:posts.Count | Should -Be 1
        $script:posts[0].Curl | Should -Be 'C:\stub\curl.exe'
        $script:posts[0].Args | Should -BeLike "*-H X-Fleet-Token: $($script:token)*"
        $script:posts[0].Args | Should -BeLike '*--connect-timeout 5*'
        $script:posts[0].Args | Should -BeLike '*--max-time 20*'
        $script:posts[0].Args | Should -BeLike '*-X POST*'
        $script:posts[0].Args | Should -BeLike '*--data-binary @*'
        $shown | Should -Not -BeLike "*$($script:token)*"
    }

    It 'AC-15: the drive copy is pending before the first POST and the body has delivery null' {
        Set-HubFile $script:usb $script:urls $script:token
        $script:answers[$script:urls[0]] = @{ Code = '503'; Exit = 0 }
        Invoke-Run | Out-Null
        $first = $script:posts[0]
        $first.Drive.delivery.status | Should -Be 'pending'
        $first.Drive.delivery.detail | Should -Be ''
        $first.Drive.final | Should -BeTrue
        $first.Body.delivery | Should -BeNullOrEmpty
        Test-Record $first.DriveFile | Should -BeNullOrEmpty
        $expected = $first.Drive
        $expected.delivery = $null
        ($first.Body | ConvertTo-Json -Depth 6) | Should -BeExactly ($expected | ConvertTo-Json -Depth 6)
    }

    It 'AC-15: when every URL fails the copy ends failed with each result, and an offline run is still ok' {
        Set-HubFile $script:usb $script:urls $script:token
        $script:answers[$script:urls[0]] = @{ Code = '503'; Exit = 0 }
        $script:answers[$script:urls[1]] = @{ Code = '000'; Exit = 7 }
        $script:answers[$script:urls[2]] = @{ Code = '403'; Exit = 0 }
        $result = Invoke-Run
        $script:posts.Count | Should -Be 3
        $record = Read-Json $script:recordPath
        $record.delivery.status | Should -Be 'failed'
        $record.delivery.detail | Should -BeLike "*$($script:urls[0]) HTTP 503*"
        $record.delivery.detail | Should -BeLike "*$($script:urls[1]) curl exit 7*"
        $record.delivery.detail | Should -BeLike "*$($script:urls[2]) HTTP 403*"
        $record.final | Should -BeTrue
        $record.ok | Should -BeTrue
        Test-Record $script:recordPath | Should -BeNullOrEmpty
        $result.ok | Should -BeTrue
    }

    It 'AC-15: the failed detail is cut to 300 characters' {
        $many = @(1..12 | ForEach-Object { "http://192.0.2.$($_):8771" })
        Set-HubFile $script:usb $many $script:token
        foreach ($url in $many) { $script:answers[$url] = @{ Code = '503'; Exit = 0 } }
        Invoke-Run | Out-Null
        $script:posts.Count | Should -Be 12
        $record = Read-Json $script:recordPath
        $record.delivery.status | Should -Be 'failed'
        $record.delivery.detail.Length | Should -Be 300
        $record.delivery.detail | Should -BeLike "$($many[0]) HTTP 503; $($many[1]) HTTP 503*"
        Test-Record $script:recordPath | Should -BeNullOrEmpty
    }

    It 'AC-15: with no hub.txt the copy is failed and nothing is sent' {
        $result = Invoke-Run
        $script:posts.Count | Should -Be 0
        $record = Read-Json $script:recordPath
        $record.delivery.status | Should -Be 'failed'
        $record.delivery.detail | Should -Be 'no hub.txt'
        Test-Record $script:recordPath | Should -BeNullOrEmpty
        $result.ok | Should -BeTrue
    }

    It 'AC-15: with no curl.exe the copy is failed with no curl' {
        Mock Get-CurlPath { $null }
        Set-HubFile $script:usb $script:urls $script:token
        $result = Invoke-Run
        $script:posts.Count | Should -Be 0
        $record = Read-Json $script:recordPath
        $record.delivery.status | Should -Be 'failed'
        $record.delivery.detail | Should -Be 'no curl'
        $result.ok | Should -BeTrue
    }

    It 'AC-15: a token line that is <label> leaves the copy failed and nothing is sent' -ForEach $tokenCases {
        Set-HubFile $script:usb $script:urls $token
        $result = Invoke-Run
        $script:posts.Count | Should -Be 0
        $record = Read-Json $script:recordPath
        $record.delivery.status | Should -Be 'failed'
        $record.delivery.detail | Should -Be 'no valid token line in hub.txt'
        Test-Record $script:recordPath | Should -BeNullOrEmpty
        $result.ok | Should -BeTrue
    }

    It 'AC-15: a hub.txt with no url line leaves the copy failed and nothing is sent' {
        Set-HubFile $script:usb @() $script:token
        Invoke-Run | Out-Null
        $script:posts.Count | Should -Be 0
        $record = Read-Json $script:recordPath
        $record.delivery.status | Should -Be 'failed'
        $record.delivery.detail | Should -Be 'no url line in hub.txt'
    }

    It 'AC-15: a url line that is not a plain http URL is ignored and hub.txt is never evaluated' {
        $marker = Join-Path $script:usb 'evaluated'
        $touch = "New-Item -ItemType File '$marker'"
        $urls = @('file:///etc/passwd', 'http://192.0.2.1:8771/extra', "http://192.0.2.1:8771;$touch", "http://`$($touch)", $script:urls[1])
        Set-HubFile $script:usb $urls $script:token -Extra @("`$($touch)", "& $touch", "; $touch")
        $script:answers[$script:urls[1]] = @{ Code = '200'; Exit = 0 }
        Invoke-Run | Out-Null
        Test-Path -LiteralPath $marker | Should -BeFalse
        $script:posts.Count | Should -Be 1
        $script:posts[0].Url | Should -Be ($script:urls[1] + $script:route)
        (Read-Json $script:recordPath).delivery.detail | Should -Be $script:urls[1]
    }

    It 'AC-15: a hub.txt with Windows line ends is read' {
        Set-HubFile $script:usb $script:urls $script:token -Eol "`r`n"
        $script:answers[$script:urls[0]] = @{ Code = '200'; Exit = 0 }
        Invoke-Run | Out-Null
        $script:posts.Count | Should -Be 1
        $script:posts[0].Args | Should -BeLike "*-H X-Fleet-Token: $($script:token) *"
        (Read-Json $script:recordPath).delivery.status | Should -Be 'sent'
    }

    It 'AC-15: a send never changes the result that ok gives' {
        Mock Step-Firewall { throw 'the firewall rule could not be made' }
        Set-HubFile $script:usb $script:urls $script:token
        $script:answers[$script:urls[0]] = @{ Code = '200'; Exit = 0 }
        $result = Invoke-Run
        $record = Read-Json $script:recordPath
        $record.ok | Should -BeFalse
        $record.delivery.status | Should -Be 'sent'
        $result.ok | Should -BeFalse
    }

    It 'AC-15: a run stopped during the send (PipelineStoppedException) leaves a complete record with delivery pending' {
        # The exception stops the whole pipeline and no catch block sees it, so the probe runs in its own process.
        Set-HubFile $script:usb $script:urls $script:token
        $probe = Join-Path $script:usb 'probe.ps1'
        $lines = @(
            "param([string]`$Usb)"
            ". '$($script:SetupPath -replace "'", "''")' -LibraryOnly"
        )
        foreach ($name in $script:StepNames) { $lines += "function $name { 'fine' }" }
        $lines += "function Step-HostKey { @{ detail = 'pinned'; data = @{ Port = 22; HostKey = '$($script:HostKey)'; Addresses = @('192.0.2.10') } } }"
        $lines += "function Get-CurlPath { 'curl.exe' }"
        $lines += "function Invoke-Curl { throw [System.Management.Automation.PipelineStoppedException]::new() }"
        $lines += "Invoke-Setup -Usb `$Usb -RunId '$script:RunId' -Account 'lab' -ComputerName 'Lab_Mini07' | Out-Null"
        [IO.File]::WriteAllLines($probe, $lines)
        & pwsh -NoProfile -File $probe -Usb $script:usb *> $null
        $record = Read-Json $script:recordPath
        $record.final | Should -BeTrue
        $record.ok | Should -BeTrue
        $record.delivery.status | Should -Be 'pending'
        Test-Record $script:recordPath | Should -BeNullOrEmpty
    }

    It 'AC-15: a parent whose UAC prompt was cancelled sends the record it finalized' {
        Mock Test-Administrator { $false }
        Mock New-RunId { $script:RunId }
        Mock Invoke-Setup { throw 'an unelevated run must not run the steps' }
        Mock Start-Process { throw [System.ComponentModel.Win32Exception]::new(1223) }
        Set-HubFile $script:usb $script:urls $script:token
        $script:answers[$script:urls[0]] = @{ Code = '200'; Exit = 0 }
        $result = Start-Setup -Usb $script:usb -ForUser 'Lab User' -ComputerName 'Lab_Mini07' -Self (Join-Path $script:usb 'setup-windows.ps1')
        $script:posts.Count | Should -Be 1
        $script:posts[0].Body.ok | Should -BeFalse
        $record = Read-Json $script:recordPath
        $record.delivery.status | Should -Be 'sent'
        $record.final | Should -BeTrue
        $result.ok | Should -BeFalse
    }

    It 'AC-15: a parent whose elevated child wrote a final record sends nothing' {
        Mock Test-Administrator { $false }
        Mock New-RunId { $script:RunId }
        Mock Invoke-Setup { throw 'an unelevated run must not run the steps' }
        $script:final = (@{
                v = 2; run_id = $script:RunId; final = $true; name = 'lab-mini07'; os = 'windows'; user = 'Lab User'; ok = $true
                steps = @(@{ step = 'elevate'; status = 'ok'; detail = '' }); tools = @{}; gui = $true; session_type = 'windows'
                rustdesk_id = $null; port = $null; host_key = $null; addresses = @()
                delivery = @{ status = 'sent'; detail = $script:urls[0] }
            } | ConvertTo-Json -Depth 6)
        Mock Start-Process { [IO.File]::WriteAllText($script:recordPath, $script:final); [pscustomobject]@{ ExitCode = 0 } }
        Set-HubFile $script:usb $script:urls $script:token
        Start-Setup -Usb $script:usb -ForUser 'Lab User' -ComputerName 'Lab_Mini07' -Self (Join-Path $script:usb 'setup-windows.ps1') | Out-Null
        $script:posts.Count | Should -Be 0
        [IO.File]::ReadAllText($script:recordPath) | Should -BeExactly $script:final
    }
}

# AC-17 of the USB kit usability plan (WP-K5, member side): the rustdesk step of setup-windows.ps1. It checks the sha256
# of the MSI on the drive, installs it, waits for the service, gives the service the hub's server and key, reads the id
# and records it. Nothing here touches the system: the program, the service, the config files, the sleeps and msiexec are
# mocked, and the drive is TestDrive.
Describe 'the Windows rustdesk step' {
    BeforeAll {
        $script:rdHost = 'hub.example.test'
        $script:rdKey = 'Xq3b9mYtL2vKd8WcN1sPz7RfH4jGa6UeO0iT5yBnM2k='
        $script:rdVersion = '1.4.1'
        $script:rdMsi = 'rustdesk-1.4.1-x86_64.msi'
        $script:rdDeb = 'rustdesk-1.4.1-x86_64.deb'
        $script:rdId = '123456789'
        $script:rdTomlId = '987654321'
        $script:rdConfigArg = "host=$($script:rdHost),key=$($script:rdKey)"

        function Get-Sha256Hex([byte[]]$Bytes) {
            $sha = [Security.Cryptography.SHA256]::Create()
            try { return (-join ($sha.ComputeHash($Bytes) | ForEach-Object { $_.ToString('x2') })) } finally { $sha.Dispose() }
        }

        # rustdesk.txt as `prepare` writes it and the files in rustdesk\; a tampered file differs from its line.
        function New-RdDrive {
            param([string[]]$Names = @($script:rdMsi), [string]$HostName = $script:rdHost, [string]$Key = $script:rdKey,
                [string]$Version = $script:rdVersion, [string[]]$Tamper = @(), [string]$Eol = "`n", [string[]]$Extra = @())
            $folder = Join-Path $script:usb 'rustdesk'
            New-Item -ItemType Directory $folder -Force | Out-Null
            $lines = @("version=$Version", "host=$HostName", "key=$Key") + $Extra
            foreach ($name in $Names) {
                $body = [Text.Encoding]::ASCII.GetBytes("the body of $name")
                $onDisk = if ($Tamper -contains $name) { $body + [Text.Encoding]::ASCII.GetBytes(' tampered') } else { $body }
                [IO.File]::WriteAllBytes((Join-Path $folder $name), [byte[]]$onDisk)
                $lines += "file=$name $(Get-Sha256Hex $body)"
            }
            [IO.File]::WriteAllText((Join-Path $script:usb 'rustdesk.txt'), (($lines -join $Eol) + $Eol))
        }

        # The step reads the run through $ctx, as every step does, so the helper holds it in its own scope.
        function Invoke-RdStep {
            $ctx = @{ Usb = $script:usb; Account = 'lab' }
            return (@(Step-RustDesk) | Select-Object -Last 1)
        }

        function Get-RdEventIndex([string]$Pattern, [int]$After = -1) {
            for ($i = $After + 1; $i -lt $script:events.Count; $i++) { if ($script:events[$i] -like $Pattern) { return $i } }
            return -1
        }
    }

    BeforeEach {
        Assert-Loaded
        $script:usb = Join-Path $TestDrive ([guid]::NewGuid().ToString('N'))
        New-Item -ItemType Directory $script:usb | Out-Null
        $script:events = New-Object System.Collections.Generic.List[string]
        $script:sleeps = New-Object System.Collections.Generic.List[int]
        $script:files = @{}
        $script:dirs = [pscustomobject]@{ Service = 'C:\FleetTest\Service\RustDesk\config'; Account = 'C:\FleetTest\Account\RustDesk\config' }
        $script:serviceToml = Join-Path $script:dirs.Service 'RustDesk2.toml'
        $script:accountToml = Join-Path $script:dirs.Account 'RustDesk2.toml'
        # Installed: the version on the system. Persist: --config writes the host to the service's RustDesk2.toml, as the
        # real program does. IdAfter and IdAfterRestart: the --get-id calls that print nothing after a start. IdLimit: the
        # --get-id calls in all that may print the id (-1 for no limit). Never: the service never answers.
        $script:rd = @{
            Installed = $null; Persist = $false; ConfigExit = 0; MsiExit = 0; Never = $false
            IdAfter = 0; IdAfterRestart = 0; IdLimit = -1; Calls = 0; Total = 0
        }
        $script:waitBefore = $env:FLEET_RUSTDESK_WAIT_S
        $env:FLEET_RUSTDESK_WAIT_S = '6'

        Mock Get-RustDeskExe { 'C:\FleetTest\RustDesk\rustdesk.exe' }
        Mock Get-RustDeskConfigDirs { $script:dirs }
        Mock Get-RustDeskVersion { $script:rd.Installed }
        Mock Read-ConfigFile { $script:files[$Path] }
        Mock Write-ConfigFile { $script:files[$Path] = $Text; $script:events.Add("write $Path") }
        Mock Start-Sleep { $script:sleeps.Add([int]$Seconds); $script:events.Add("sleep $Seconds") }
        Mock Restart-Service {
            $script:events.Add("restart $Name")
            $script:rd.Calls = 0
            $script:rd.IdAfter = $script:rd.IdAfterRestart
        }
        Mock Invoke-Native {
            $script:events.Add("$File " + (@($Arguments) -join ' '))
            if ($File -eq 'msiexec.exe') {
                if ($script:rd.MsiExit -eq 0 -or $script:rd.MsiExit -eq 3010) { $script:rd.Installed = '1.4.1' }
                return $script:rd.MsiExit
            }
            return 0
        }
        Mock Invoke-RustDesk {
            $script:events.Add('rd ' + (@($Arguments) -join ' '))
            $output = ''
            if ($Arguments[0] -eq '--get-id') {
                $script:rd.Total++
                $script:rd.Calls++
                $quiet = $script:rd.Never -or ($script:rd.Calls -le $script:rd.IdAfter) -or
                    ($script:rd.IdLimit -ge 0 -and $script:rd.Total -gt $script:rd.IdLimit)
                if (-not $quiet) { $output = $script:rdId }
            }
            $code = 0
            if ($Arguments[0] -eq '--config') {
                $code = $script:rd.ConfigExit
                if ($script:rd.Persist) {
                    $configured = ((@($Arguments)[1] -split ',')[0]) -replace '^host=', ''
                    $script:files[$script:serviceToml] = "[options]`ncustom-rendezvous-server = '$configured'`n"
                }
            }
            return [pscustomobject]@{ Exit = $code; Output = $output }
        }
    }

    AfterEach { $env:FLEET_RUSTDESK_WAIT_S = $script:waitBefore }

    It 'AC-17: a sha256 mismatch ends the step failed, naming sha256, and msiexec is never called' {
        New-RdDrive -Tamper @($script:rdMsi)
        { Invoke-RdStep } | Should -Throw '*sha256*'
        @($script:events | Where-Object { $_ -like 'msiexec*' }).Count | Should -Be 0
        $script:events.Count | Should -Be 0
    }

    It 'AC-17: an MSI that is missing from the drive ends the step failed, naming the file, and msiexec is never called' {
        New-RdDrive
        Remove-Item -LiteralPath (Join-Path (Join-Path $script:usb 'rustdesk') $script:rdMsi)
        { Invoke-RdStep } | Should -Throw "*$($script:rdMsi)*"
        $script:events.Count | Should -Be 0
    }

    It 'AC-17: a match runs msiexec /i with /qn and /norestart before the first --get-id, and --config once after it' {
        $script:rd.Persist = $true
        New-RdDrive
        $result = Invoke-RdStep
        $msi = Join-Path (Join-Path $script:usb 'rustdesk') $script:rdMsi
        $install = $script:events.IndexOf("msiexec.exe /i $msi /qn /norestart")
        $firstId = Get-RdEventIndex 'rd --get-id*'
        $install | Should -BeGreaterOrEqual 0
        $firstId | Should -BeGreaterThan $install
        @($script:events | Where-Object { $_ -eq "rd --config $($script:rdConfigArg)" }).Count | Should -Be 1
        $script:events.IndexOf("rd --config $($script:rdConfigArg)") | Should -BeGreaterThan $firstId
        $result.data.RustDeskId | Should -BeExactly $script:rdId
        $result.detail | Should -Not -BeNullOrEmpty
    }

    It 'AC-17: the Ready wait polls --get-id with a 2 second sleep after each empty answer, and the step goes on at the first id' {
        $script:rd.Persist = $true
        $script:rd.IdAfter = 2
        New-RdDrive
        $result = Invoke-RdStep
        ($script:sleeps -join ',') | Should -BeExactly '2,2'
        $firstConfig = $script:events.IndexOf("rd --config $($script:rdConfigArg)")
        @($script:events[0..$firstConfig] | Where-Object { $_ -eq 'rd --get-id' }).Count | Should -Be 3
        $result.data.RustDeskId | Should -BeExactly $script:rdId
    }

    It 'AC-17: a service that never prints an id ends the step failed with service not ready, and --config is never run' {
        $script:rd.Never = $true
        New-RdDrive
        { Invoke-RdStep } | Should -Throw -ExpectedMessage 'service not ready'
        @($script:events | Where-Object { $_ -like 'rd --config*' }).Count | Should -Be 0
        @($script:sleeps | Where-Object { $_ -ne 2 }).Count | Should -Be 0
        ($script:sleeps | Measure-Object -Sum).Sum | Should -BeLessOrEqual 6
        ($script:sleeps | Measure-Object -Sum).Sum | Should -BeGreaterThan 0
    }

    It 'AC-17: when --config reaches the service nothing is written and the service is not restarted' {
        $script:rd.Persist = $true
        New-RdDrive
        $result = Invoke-RdStep
        @($script:events | Where-Object { $_ -like 'write *' }).Count | Should -Be 0
        @($script:events | Where-Object { $_ -like 'restart *' }).Count | Should -Be 0
        $result.data.RustDeskId | Should -BeExactly $script:rdId
    }

    It 'AC-17: when the service config lacks the host both RustDesk2.toml files are written, the service restarts and the step waits for Ready again' {
        $script:rd.IdAfterRestart = 1
        New-RdDrive
        $result = Invoke-RdStep
        foreach ($path in @($script:serviceToml, $script:accountToml)) {
            $text = [string]$script:files[$path]
            $text | Should -BeLike '*[[]options]*'
            $text | Should -BeLike "*custom-rendezvous-server = '$($script:rdHost)'*"
            $text | Should -BeLike "*key = '$($script:rdKey)'*"
            $script:events.IndexOf("write $path") | Should -BeGreaterThan $script:events.IndexOf("rd --config $($script:rdConfigArg)")
        }
        $restart = $script:events.IndexOf('restart RustDesk')
        $restart | Should -BeGreaterThan $script:events.IndexOf("write $($script:serviceToml)")
        $restart | Should -BeGreaterThan $script:events.IndexOf("write $($script:accountToml)")
        Get-RdEventIndex 'rd --get-id*' $restart | Should -BeGreaterThan $restart
        @($script:sleeps) | Should -Contain 2
        $result.data.RustDeskId | Should -BeExactly $script:rdId
    }

    It 'AC-17: a --config that exits non-zero does not fail the step by itself; the read-back decides' {
        $script:rd.ConfigExit = 1
        New-RdDrive
        $result = Invoke-RdStep
        $script:events | Should -Contain 'restart RustDesk'
        $result.data.RustDeskId | Should -BeExactly $script:rdId
    }

    It 'AC-17: the TOML fallback keeps the other settings, replaces an old server and an old key, and writes each of them once' {
        $old = "rendezvous_server = 'old.example.test:21116'`nnat_type = 1`n`n[options]`n" +
            "custom-rendezvous-server = 'old.example.test'`nkey = 'oldoldoldoldoldoldoldoldoldoldoldoldoldoldoldold'`ntheme = 'dark'`n"
        $script:files[$script:serviceToml] = $old
        New-RdDrive
        Invoke-RdStep | Out-Null
        $text = [string]$script:files[$script:serviceToml]
        $text | Should -BeLike "*nat_type = 1*"
        $text | Should -BeLike "*theme = 'dark'*"
        $text | Should -BeLike "*rendezvous_server = 'old.example.test:21116'*"
        $text | Should -Not -BeLike '*oldoldold*'
        $text | Should -BeLike "*custom-rendezvous-server = '$($script:rdHost)'*"
        ([regex]::Matches($text, 'custom-rendezvous-server')).Count | Should -Be 1
        ([regex]::Matches($text, '(?m)^key = ')).Count | Should -Be 1
    }

    It 'AC-17: a service that answers at first and not after the restart ends the step failed with service not ready' {
        $script:rd.IdLimit = 1
        New-RdDrive
        { Invoke-RdStep } | Should -Throw -ExpectedMessage 'service not ready'
        $script:events | Should -Contain 'restart RustDesk'
    }

    It 'AC-17: when --get-id prints no id after the Ready wait the id comes from RustDesk.toml of the service' {
        $script:rd.Persist = $true
        $script:rd.IdLimit = 1
        $script:files[(Join-Path $script:dirs.Service 'RustDesk.toml')] = "enc_id = 'x'`nid = '$($script:rdTomlId)'`n"
        New-RdDrive
        $result = Invoke-RdStep
        $result.data.RustDeskId | Should -BeExactly $script:rdTomlId
    }

    It 'AC-17: with no id from --get-id and none in RustDesk.toml the step fails and names the id' {
        $script:rd.Persist = $true
        $script:rd.IdLimit = 1
        New-RdDrive
        { Invoke-RdStep } | Should -Throw '*id*'
    }

    It 'AC-17: an installed version equal to the file skips msiexec and the step still gives the service the server' {
        $script:rd.Installed = '1.4.1'
        New-RdDrive
        $result = Invoke-RdStep
        @($script:events | Where-Object { $_ -like 'msiexec*' }).Count | Should -Be 0
        $script:events | Should -Contain "rd --config $($script:rdConfigArg)"
        $result.data.RustDeskId | Should -BeExactly $script:rdId
    }

    It 'AC-17: an older installed version is installed over with msiexec' {
        $script:rd.Installed = '1.3.0'
        New-RdDrive
        Invoke-RdStep | Out-Null
        @($script:events | Where-Object { $_ -like 'msiexec.exe /i *' }).Count | Should -Be 1
    }

    It 'AC-17: msiexec exit 3010 (a restart is pending) counts as installed, and any other non-zero exit fails the step' {
        $script:rd.MsiExit = 3010
        New-RdDrive
        (Invoke-RdStep).data.RustDeskId | Should -BeExactly $script:rdId
        $script:rd.MsiExit = 1603
        $script:rd.Installed = $null
        { Invoke-RdStep } | Should -Throw '*msiexec*1603*'
    }

    It 'AC-17: with no rustdesk.txt on the drive the step is skipped with no server configured and nothing runs' {
        $result = Invoke-RdStep
        $result.status | Should -BeExactly 'skipped'
        $result.detail | Should -BeExactly 'no server configured'
        $script:events.Count | Should -Be 0
    }

    It 'AC-17: a rustdesk.txt with no Windows asset is skipped with no asset for windows and nothing runs' {
        New-RdDrive -Names @($script:rdDeb)
        $result = Invoke-RdStep
        $result.status | Should -BeExactly 'skipped'
        $result.detail | Should -BeExactly 'no asset for windows'
        $script:events.Count | Should -Be 0
    }

    It 'AC-17: a rustdesk.txt with no valid host ends the step failed, naming rustdesk.txt, and nothing runs' {
        New-RdDrive -HostName 'hub example'
        { Invoke-RdStep } | Should -Throw '*rustdesk.txt*'
        $script:events.Count | Should -Be 0
    }

    It 'AC-17: rustdesk.txt is read as data, and a Windows line end does not hide a line' {
        $marker = Join-Path $script:usb 'pwned'
        $extra = @("`$(Set-Content -LiteralPath '$marker' -Value x)", "file=..\x.msi $('0' * 64)", 'unknown=1')
        $script:rd.Persist = $true
        New-RdDrive -Extra $extra -Eol "`r`n"
        $result = Invoke-RdStep
        $result.data.RustDeskId | Should -BeExactly $script:rdId
        Test-Path -LiteralPath $marker | Should -BeFalse
        @($script:events | Where-Object { $_ -like '*x.msi*' }).Count | Should -Be 0
    }

    It 'AC-17: the tool versions hold rustdesk from Get-RustDeskVersion, and no key when it is not installed' {
        Mock Update-SessionPath { }
        Mock Get-ToolVersion { $null }
        $script:rd.Installed = '1.4.1'
        (Get-ToolVersions)['rustdesk'] | Should -BeExactly '1.4.1'
        $script:rd.Installed = $null
        @((Get-ToolVersions).Keys) | Should -Not -Contain 'rustdesk'
    }
}

Describe 'the Windows rustdesk record' {
    BeforeEach {
        Assert-Loaded
        $script:usb = Join-Path $TestDrive ([guid]::NewGuid().ToString('N'))
        New-Item -ItemType Directory (Join-Path $script:usb 'members') | Out-Null
        $script:recordPath = Join-Path $script:usb 'members/lab-mini07.json'
        foreach ($name in $script:StepNames) { Mock $name { 'fine' } }
        Mock Get-ToolVersion { $null }
        Mock Step-HostKey { @{ detail = 'pinned'; data = @{ Port = 22; HostKey = $script:HostKey; Addresses = @('192.0.2.10') } } }
    }

    It 'AC-17: the step list puts rustdesk right before host_key, and it needs elevate' {
        $steps = @(Get-SetupSteps)
        $ids = @($steps | ForEach-Object Id)
        $ids | Should -Contain 'rustdesk'
        [array]::IndexOf($ids, 'rustdesk') | Should -Be ([array]::IndexOf($ids, 'host_key') - 1)
        @($steps | Where-Object { $_.Id -eq 'rustdesk' }).Needs | Should -Contain 'elevate'
        @($steps | Where-Object { $_.Id -eq 'rustdesk' }).Fn | Should -BeExactly 'Step-RustDesk'
    }

    It 'AC-17: the id of the rustdesk step is in the record, beside the port and the host key of the later step' {
        Mock Step-RustDesk { @{ detail = 'installed 1.4.1'; data = @{ RustDeskId = '123456789' } } }
        Invoke-Setup -Usb $script:usb -RunId $script:RunId -Account 'lab' -ComputerName 'Lab_Mini07' | Out-Null
        $record = Read-Json $script:recordPath
        $record.rustdesk_id | Should -BeExactly '123456789'
        $record.port | Should -Be 22
        $record.host_key | Should -Be $script:HostKey
        @($record.addresses) | Should -Be @('192.0.2.10')
        (Get-StepStatus $record 'rustdesk').status | Should -Be 'ok'
        (Get-StepStatus $record 'rustdesk').detail | Should -Be 'installed 1.4.1'
        Test-Record $script:recordPath | Should -BeNullOrEmpty
    }

    It 'AC-17: a step that answers skipped is recorded skipped with its detail, the id stays null and the run is still ok' {
        Mock Step-RustDesk { @{ status = 'skipped'; detail = 'no server configured' } }
        $result = Invoke-Setup -Usb $script:usb -RunId $script:RunId -Account 'lab' -ComputerName 'Lab_Mini07'
        $record = Read-Json $script:recordPath
        (Get-StepStatus $record 'rustdesk').status | Should -Be 'skipped'
        (Get-StepStatus $record 'rustdesk').detail | Should -Be 'no server configured'
        $record.rustdesk_id | Should -BeNullOrEmpty
        $record.ok | Should -BeTrue
        $result.ok | Should -BeTrue
        Test-Record $script:recordPath | Should -BeNullOrEmpty
    }

    It 'AC-17: a rustdesk step that throws ends failed and host_key still runs and pins the host' {
        Mock Step-RustDesk { throw 'service not ready' }
        Invoke-Setup -Usb $script:usb -RunId $script:RunId -Account 'lab' -ComputerName 'Lab_Mini07' | Out-Null
        $record = Read-Json $script:recordPath
        (Get-StepStatus $record 'rustdesk').status | Should -Be 'failed'
        (Get-StepStatus $record 'rustdesk').detail | Should -Be 'service not ready'
        (Get-StepStatus $record 'host_key').status | Should -Be 'ok'
        $record.rustdesk_id | Should -BeNullOrEmpty
        $record.port | Should -Be 22
        $record.ok | Should -BeFalse
    }

    It 'AC-17: a child that left only a checkpoint with a rustdesk id leaves that id in the record the parent finalizes' {
        Mock Test-Administrator { $false }
        Mock New-RunId { $script:RunId }
        Mock Invoke-Setup { throw 'an unelevated run must not run the steps' }
        $script:checkpoint = (@{
                v = 2; run_id = $script:RunId; final = $false; name = 'lab-mini07'; os = 'windows'; user = 'Lab User'; ok = $false
                steps = @(@{ step = 'elevate'; status = 'ok'; detail = '' }, @{ step = 'account'; status = 'ok'; detail = 'Lab User' },
                    @{ step = 'rustdesk'; status = 'ok'; detail = 'installed 1.4.1' })
                tools = @{}; gui = $true; session_type = 'windows'; rustdesk_id = '123456789'; port = $null; host_key = $null
                addresses = @(); delivery = $null
            } | ConvertTo-Json -Depth 6)
        Mock Start-Process { [IO.File]::WriteAllText($script:recordPath, $script:checkpoint); [pscustomobject]@{ ExitCode = 1 } }
        Start-Setup -Usb $script:usb -ForUser 'Lab User' -ComputerName 'Lab_Mini07' -Self (Join-Path $script:usb 'setup-windows.ps1') | Out-Null
        $record = Read-Json $script:recordPath
        $record.final | Should -BeTrue
        $record.rustdesk_id | Should -BeExactly '123456789'
        (Get-StepStatus $record 'rustdesk').status | Should -Be 'ok'
        Test-Record $script:recordPath | Should -BeNullOrEmpty
    }
}
