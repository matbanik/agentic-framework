# Runs the member as the scheduled task "Fleet member", which has no trigger, so nothing starts at
# boot, and which outlives the WinRM shell that starts it. ACTION is Start (default), Restart, Stop or
# Remove. Remove reverses Start.
$ErrorActionPreference = 'Stop'
$Task = 'Fleet member'
$FleetHome = "$HOME\.agent\fleet"
if (-not $ACTION) { $ACTION = 'Start' }

function Stop-Member {
    Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
        Where-Object { $_.CommandLine -like '*fleet.py*member*' } |
        ForEach-Object { Invoke-CimMethod -InputObject $_ -MethodName Terminate | Out-Null }
    Stop-ScheduledTask -TaskName $Task -ErrorAction SilentlyContinue
}

function Register-Member {
    $py = Get-ChildItem "$env:LOCALAPPDATA\Programs\Python\Python3*\python.exe" |
        Sort-Object { [int]($_.Directory.Name -replace '\D') } -Descending | Select-Object -First 1 -ExpandProperty FullName
    $command = "/c `"`"$py`" `"$FleetHome\fleet.py`" member >> `"$FleetHome\member.log`" 2>&1`""
    $action = New-ScheduledTaskAction -Execute 'cmd.exe' -Argument $command
    $principal = New-ScheduledTaskPrincipal -UserId "$env:COMPUTERNAME\$env:USERNAME" -LogonType S4U
    $settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit ([TimeSpan]::Zero) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew
    Register-ScheduledTask -TaskName $Task -Action $action -Principal $principal -Settings $settings | Out-Null
}

switch ($ACTION) {
    'Start' {
        if (-not (Get-ScheduledTask -TaskName $Task -ErrorAction SilentlyContinue)) { Register-Member }
        Start-ScheduledTask -TaskName $Task
    }
    'Restart' {
        Stop-Member
        Start-ScheduledTask -TaskName $Task
    }
    'Stop' { Stop-Member }
    'Remove' {
        Stop-Member
        Unregister-ScheduledTask -TaskName $Task -Confirm:$false
        Write-Output "Removed $Task"
        exit 0
    }
    default { throw "unknown ACTION: $ACTION" }
}
Start-Sleep -Seconds 2
Write-Output "$Task is $((Get-ScheduledTask -TaskName $Task).State)"
