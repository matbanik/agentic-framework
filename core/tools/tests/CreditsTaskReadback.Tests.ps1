# Row 34 defect (EA-88): the real scheduler adapter reads a task back with ConvertFrom-CreditsScheduledTask.
# A run task has no trigger (Start-CreditsRunTask starts it on demand), so Get-ScheduledTask gives
# Triggers = $null. @($null) holds one $null item, and under Set-StrictMode the read of
# $null.CimClass throws, so Register-CreditsRun ends with exit 9 on the first real registration.
# AC-D.6 holds: no test here registers or reads a real task; the task is a plain object.

BeforeAll {
    $script:Repo = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
    $script:Module = Join-Path $script:Repo '.agent/skills/claude-credits/CreditsRun.psm1'
    Import-Module -Name $script:Module -Force -DisableNameChecking -ErrorAction Stop

    # A read-back in the shape of Get-ScheduledTask, for a run task with no trigger.
    function New-FakeRunTask {
        [pscustomobject]@{
            TaskPath  = '\ReadbackTest\Credits\'
            TaskName  = 'readback-run'
            Actions   = @([pscustomobject]@{ Execute = 'pwsh.exe'; Arguments = '-NoProfile -File run.ps1'; WorkingDirectory = 'C:/readback/project' })
            Principal = [pscustomobject]@{ LogonType = 'Interactive'; RunLevel = 'Limited' }
            Settings  = [pscustomobject]@{
                DisallowStartIfOnBatteries = $false
                StopIfGoingOnBatteries     = $false
                MultipleInstances          = 'IgnoreNew'
                ExecutionTimeLimit         = 'PT0S'
                Priority                   = 7
                RestartCount               = 0
                WakeToRun                  = $false
            }
            Triggers  = $null
        }
    }
}

AfterAll {
    Remove-Module -Name CreditsRun -Force -ErrorAction SilentlyContinue
}

Describe 'EA-88: a task with no trigger reads back without an error' {
    It 'EA-88: ConvertFrom-CreditsScheduledTask returns an empty trigger list for Triggers = $null' {
        $task = New-FakeRunTask
        $read = InModuleScope CreditsRun -Parameters @{ Task = $task } {
            param($Task)
            ConvertFrom-CreditsScheduledTask $Task
        }
        $read | Should -Not -BeNullOrEmpty
        @($read.Triggers).Count | Should -Be 0
    }

    It 'EA-88: the read-back hash equals the hash of the same definition with Triggers = @()' {
        $task = New-FakeRunTask
        $read = InModuleScope CreditsRun -Parameters @{ Task = $task } {
            param($Task)
            ConvertFrom-CreditsScheduledTask $Task
        }
        $definition = [pscustomobject][ordered]@{
            TaskPath                   = '\ReadbackTest\Credits\'
            TaskName                   = 'readback-run'
            Execute                    = 'pwsh.exe'
            Argument                   = '-NoProfile -File run.ps1'
            WorkingDirectory           = 'C:/readback/project'
            LogonType                  = 'Interactive'
            RunLevel                   = 'Limited'
            AllowStartIfOnBatteries    = $true
            DontStopIfGoingOnBatteries = $true
            MultipleInstances          = 'IgnoreNew'
            ExecutionTimeLimitSec      = 0
            Priority                   = 7
            Triggers                   = @()
            RestartCount               = 0
            WakeToRun                  = $false
        }
        Get-CreditsTaskDefinitionHash -Definition $read | Should -Be (Get-CreditsTaskDefinitionHash -Definition $definition)
    }
}
