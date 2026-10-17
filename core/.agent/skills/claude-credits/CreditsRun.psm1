<#
.SYNOPSIS
    The job helper and the store helpers of the scheduled credits runs.

.DESCRIPTION
    A credits segment that carries messaging runs inside a named Windows job object,
    Local\{{PROJECT_NAME_UPPER}}Credits-<segment id>, created with JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE. Its
    supervisor (the launcher or the manual wrapper) holds the only handle, so when the supervisor
    dies the job closes and Windows ends every member. The child is created suspended and inside
    the job in one CreateProcess call (PROC_THREAD_ATTRIBUTE_JOB_LIST), so no instant exists in
    which it runs outside the job (report sections 4.4 and 7.2).

    Get-CreditsJobProof reads the job from another process and returns one of:
      live     the job exists and has members;
      empty    the job exists with no members, or the boot id changed (every process of the old
               boot is gone);
      gone     no job of that name in the launcher's Windows session, and every recorded process
               is dead (pid plus creation time);
      unknown  any other result: an open error, a recorded process that still lives, or a check
               from another Windows session, where a Local\ name is not visible (MX-30).

    Stop-CreditsJobByName ends every member of a live job that the monitor does not hold
    (report section 4.4: a dead launcher with a live job). Get-CreditsProcessState gives dead,
    alive or unknown for one recorded process.

    Invoke-CreditsState runs tools/credits_state.py with the repository's Python and returns its
    exit code and its JSON payload. Complete-CreditsSegment finalizes one segment and throws when
    the store refuses.
#>

Set-StrictMode -Version Latest

$script:RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot '../../..')).Path
$script:StateTool = Join-Path $script:RepoRoot 'tools/credits_state.py'
$script:JobNamePrefix = 'Local\{{PROJECT_NAME_UPPER}}Credits-'
# Store times have second precision; a recorded creation time matches a process whose real
# creation time is less than this many seconds away.
$script:CreationToleranceSec = 2.0

if (-not ('ClaudeCredits.JobNative' -as [type])) {
    Add-Type -Language CSharp -TypeDefinition @'
using System;
using System.ComponentModel;
using System.Runtime.InteropServices;
using System.Text;

namespace ClaudeCredits
{
    /// <summary>A child created suspended inside a job. Resume or Abandon closes its handles.</summary>
    public sealed class JobChild
    {
        public int ProcessId { get; internal set; }
        public DateTime CreationUtc { get; internal set; }
        internal IntPtr ProcessHandle;
        internal IntPtr ThreadHandle;
    }

    public static class JobNative
    {
        const uint JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000;
        const int JobObjectBasicAccountingInformation = 1;
        const int JobObjectExtendedLimitInformation = 9;
        const uint JOB_OBJECT_QUERY = 0x0004;
        const int ERROR_ALREADY_EXISTS = 183;
        const int ERROR_INVALID_PARAMETER = 87;
        const uint EXTENDED_STARTUPINFO_PRESENT = 0x00080000;
        const uint CREATE_SUSPENDED = 0x00000004;
        const uint CREATE_UNICODE_ENVIRONMENT = 0x00000400;
        const uint CREATE_NO_WINDOW = 0x08000000;
        static readonly IntPtr PROC_THREAD_ATTRIBUTE_JOB_LIST = (IntPtr)0x0002000D;
        const uint PROCESS_QUERY_LIMITED_INFORMATION = 0x1000;
        const uint SYNCHRONIZE = 0x00100000;
        const uint WAIT_TIMEOUT = 0x102;
        const uint WAIT_OBJECT_0 = 0;

        [StructLayout(LayoutKind.Sequential)]
        struct JOBOBJECT_BASIC_LIMIT_INFORMATION
        {
            public long PerProcessUserTimeLimit;
            public long PerJobUserTimeLimit;
            public uint LimitFlags;
            public UIntPtr MinimumWorkingSetSize;
            public UIntPtr MaximumWorkingSetSize;
            public uint ActiveProcessLimit;
            public UIntPtr Affinity;
            public uint PriorityClass;
            public uint SchedulingClass;
        }

        [StructLayout(LayoutKind.Sequential)]
        struct IO_COUNTERS
        {
            public ulong ReadOperationCount, WriteOperationCount, OtherOperationCount;
            public ulong ReadTransferCount, WriteTransferCount, OtherTransferCount;
        }

        [StructLayout(LayoutKind.Sequential)]
        struct JOBOBJECT_EXTENDED_LIMIT_INFORMATION
        {
            public JOBOBJECT_BASIC_LIMIT_INFORMATION BasicLimitInformation;
            public IO_COUNTERS IoInfo;
            public UIntPtr ProcessMemoryLimit;
            public UIntPtr JobMemoryLimit;
            public UIntPtr PeakProcessMemoryUsed;
            public UIntPtr PeakJobMemoryUsed;
        }

        [StructLayout(LayoutKind.Sequential)]
        struct JOBOBJECT_BASIC_ACCOUNTING_INFORMATION
        {
            public long TotalUserTime, TotalKernelTime, ThisPeriodTotalUserTime, ThisPeriodTotalKernelTime;
            public uint TotalPageFaultCount, TotalProcesses, ActiveProcesses, TotalTerminatedProcesses;
        }

        [StructLayout(LayoutKind.Sequential)]
        struct STARTUPINFO
        {
            public int cb;
            public IntPtr lpReserved, lpDesktop, lpTitle;
            public int dwX, dwY, dwXSize, dwYSize, dwXCountChars, dwYCountChars, dwFillAttribute, dwFlags;
            public short wShowWindow, cbReserved2;
            public IntPtr lpReserved2, hStdInput, hStdOutput, hStdError;
        }

        [StructLayout(LayoutKind.Sequential)]
        struct STARTUPINFOEX
        {
            public STARTUPINFO StartupInfo;
            public IntPtr lpAttributeList;
        }

        [StructLayout(LayoutKind.Sequential)]
        struct PROCESS_INFORMATION
        {
            public IntPtr hProcess, hThread;
            public int dwProcessId, dwThreadId;
        }

        [DllImport("kernel32.dll", SetLastError = true, CharSet = CharSet.Unicode)]
        static extern IntPtr CreateJobObjectW(IntPtr attributes, string name);
        [DllImport("kernel32.dll", SetLastError = true, CharSet = CharSet.Unicode)]
        static extern IntPtr OpenJobObjectW(uint access, bool inherit, string name);
        [DllImport("kernel32.dll", SetLastError = true)]
        static extern bool SetInformationJobObject(IntPtr job, int infoClass, ref JOBOBJECT_EXTENDED_LIMIT_INFORMATION info, uint length);
        [DllImport("kernel32.dll", SetLastError = true)]
        static extern bool QueryInformationJobObject(IntPtr job, int infoClass, out JOBOBJECT_BASIC_ACCOUNTING_INFORMATION info, uint length, IntPtr returnLength);
        [DllImport("kernel32.dll", SetLastError = true)]
        static extern bool TerminateJobObject(IntPtr job, uint exitCode);
        [DllImport("kernel32.dll", SetLastError = true)]
        static extern bool CloseHandle(IntPtr handle);
        [DllImport("kernel32.dll", SetLastError = true)]
        static extern bool InitializeProcThreadAttributeList(IntPtr list, int count, int flags, ref IntPtr size);
        [DllImport("kernel32.dll", SetLastError = true)]
        static extern bool UpdateProcThreadAttribute(IntPtr list, uint flags, IntPtr attribute, IntPtr value, IntPtr size, IntPtr previous, IntPtr returnSize);
        [DllImport("kernel32.dll")]
        static extern void DeleteProcThreadAttributeList(IntPtr list);
        [DllImport("kernel32.dll", SetLastError = true, CharSet = CharSet.Unicode)]
        static extern bool CreateProcessW(string application, StringBuilder commandLine, IntPtr processAttributes, IntPtr threadAttributes,
            bool inheritHandles, uint flags, IntPtr environment, string currentDirectory, ref STARTUPINFOEX startupInfo, out PROCESS_INFORMATION info);
        [DllImport("kernel32.dll", SetLastError = true)]
        static extern uint ResumeThread(IntPtr thread);
        [DllImport("kernel32.dll", SetLastError = true)]
        static extern bool TerminateProcess(IntPtr process, uint exitCode);
        [DllImport("kernel32.dll", SetLastError = true)]
        static extern IntPtr OpenProcess(uint access, bool inherit, int processId);
        [DllImport("kernel32.dll", SetLastError = true)]
        static extern uint WaitForSingleObject(IntPtr handle, uint milliseconds);
        [DllImport("kernel32.dll", SetLastError = true)]
        static extern bool GetProcessTimes(IntPtr process, out long creation, out long exit, out long kernel, out long user);

        /// <summary>Create the named kill-on-close job. Throws when a job of that name exists.</summary>
        public static IntPtr CreateKillOnCloseJob(string name)
        {
            // No security attributes: the handle is not inheritable, so no child holds the job open.
            IntPtr job = CreateJobObjectW(IntPtr.Zero, name);
            int error = Marshal.GetLastWin32Error();
            if (job == IntPtr.Zero) throw new Win32Exception(error, "CreateJobObject failed for " + name);
            if (error == ERROR_ALREADY_EXISTS)
            {
                CloseHandle(job);
                throw new InvalidOperationException("job_exists: a job named " + name + " exists; its handle is never shared");
            }
            var info = new JOBOBJECT_EXTENDED_LIMIT_INFORMATION();
            info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
            if (!SetInformationJobObject(job, JobObjectExtendedLimitInformation, ref info, (uint)Marshal.SizeOf(info)))
            {
                error = Marshal.GetLastWin32Error();
                CloseHandle(job);
                throw new Win32Exception(error, "SetInformationJobObject failed for " + name);
            }
            return job;
        }

        public static int ActiveProcesses(IntPtr job)
        {
            JOBOBJECT_BASIC_ACCOUNTING_INFORMATION info;
            if (!QueryInformationJobObject(job, JobObjectBasicAccountingInformation, out info, (uint)Marshal.SizeOf(typeof(JOBOBJECT_BASIC_ACCOUNTING_INFORMATION)), IntPtr.Zero))
                throw new Win32Exception(Marshal.GetLastWin32Error(), "QueryInformationJobObject failed");
            return (int)info.ActiveProcesses;
        }

        /// <summary>Open the job by name for a query. Returns 0 and the member count, or the Win32 error.</summary>
        public static int ObserveJob(string name, out int activeProcesses)
        {
            activeProcesses = -1;
            IntPtr job = OpenJobObjectW(JOB_OBJECT_QUERY, false, name);
            if (job == IntPtr.Zero) return Marshal.GetLastWin32Error();
            try
            {
                JOBOBJECT_BASIC_ACCOUNTING_INFORMATION info;
                if (!QueryInformationJobObject(job, JobObjectBasicAccountingInformation, out info, (uint)Marshal.SizeOf(typeof(JOBOBJECT_BASIC_ACCOUNTING_INFORMATION)), IntPtr.Zero))
                    return Marshal.GetLastWin32Error();
                activeProcesses = (int)info.ActiveProcesses;
                return 0;
            }
            finally { CloseHandle(job); }
        }

        public static void Terminate(IntPtr job, uint exitCode)
        {
            if (!TerminateJobObject(job, exitCode))
                throw new Win32Exception(Marshal.GetLastWin32Error(), "TerminateJobObject failed");
        }

        public static void Close(IntPtr handle)
        {
            if (handle != IntPtr.Zero && !CloseHandle(handle))
                throw new Win32Exception(Marshal.GetLastWin32Error(), "CloseHandle failed");
        }

        /// <summary>
        /// Create the process suspended and inside the job in one call, with no inherited handle.
        /// environmentBlock is null for this process's environment, else "k=v\0...\0".
        /// </summary>
        public static JobChild StartSuspendedInJob(IntPtr job, string application, string commandLine, string currentDirectory, string environmentBlock)
        {
            IntPtr size = IntPtr.Zero;
            InitializeProcThreadAttributeList(IntPtr.Zero, 1, 0, ref size);
            IntPtr list = Marshal.AllocHGlobal(size);
            IntPtr jobs = Marshal.AllocHGlobal(IntPtr.Size);
            IntPtr env = IntPtr.Zero;
            bool listReady = false;
            try
            {
                if (!InitializeProcThreadAttributeList(list, 1, 0, ref size))
                    throw new Win32Exception(Marshal.GetLastWin32Error(), "InitializeProcThreadAttributeList failed");
                listReady = true;
                Marshal.WriteIntPtr(jobs, job);
                if (!UpdateProcThreadAttribute(list, 0, PROC_THREAD_ATTRIBUTE_JOB_LIST, jobs, (IntPtr)IntPtr.Size, IntPtr.Zero, IntPtr.Zero))
                    throw new Win32Exception(Marshal.GetLastWin32Error(), "UpdateProcThreadAttribute(JOB_LIST) failed");
                var si = new STARTUPINFOEX();
                si.StartupInfo.cb = Marshal.SizeOf(typeof(STARTUPINFOEX));
                si.lpAttributeList = list;
                uint flags = EXTENDED_STARTUPINFO_PRESENT | CREATE_SUSPENDED | CREATE_NO_WINDOW;
                if (environmentBlock != null)
                {
                    env = Marshal.StringToHGlobalUni(environmentBlock + "\0");
                    flags |= CREATE_UNICODE_ENVIRONMENT;
                }
                PROCESS_INFORMATION pi;
                if (!CreateProcessW(application, new StringBuilder(commandLine), IntPtr.Zero, IntPtr.Zero, false, flags, env, currentDirectory, ref si, out pi))
                    throw new Win32Exception(Marshal.GetLastWin32Error(), "CreateProcess failed for " + application);
                long creation, exit, kernel, user;
                if (!GetProcessTimes(pi.hProcess, out creation, out exit, out kernel, out user))
                {
                    int error = Marshal.GetLastWin32Error();
                    TerminateProcess(pi.hProcess, 1);
                    CloseHandle(pi.hThread);
                    CloseHandle(pi.hProcess);
                    throw new Win32Exception(error, "GetProcessTimes failed for the new child");
                }
                return new JobChild
                {
                    ProcessId = pi.dwProcessId,
                    CreationUtc = DateTime.FromFileTimeUtc(creation),
                    ProcessHandle = pi.hProcess,
                    ThreadHandle = pi.hThread,
                };
            }
            finally
            {
                if (listReady) DeleteProcThreadAttributeList(list);
                Marshal.FreeHGlobal(list);
                Marshal.FreeHGlobal(jobs);
                if (env != IntPtr.Zero) Marshal.FreeHGlobal(env);
            }
        }

        public static void Resume(JobChild child)
        {
            if (child.ThreadHandle == IntPtr.Zero) throw new InvalidOperationException("the child was already resumed or abandoned");
            try
            {
                if (ResumeThread(child.ThreadHandle) == uint.MaxValue)
                    throw new Win32Exception(Marshal.GetLastWin32Error(), "ResumeThread failed");
            }
            finally { ReleaseHandles(child); }
        }

        /// <summary>End a child that was never resumed and close its handles.</summary>
        public static void Abandon(JobChild child)
        {
            if (child.ProcessHandle != IntPtr.Zero) TerminateProcess(child.ProcessHandle, 1);
            ReleaseHandles(child);
        }

        static void ReleaseHandles(JobChild child)
        {
            if (child.ThreadHandle != IntPtr.Zero) { CloseHandle(child.ThreadHandle); child.ThreadHandle = IntPtr.Zero; }
            if (child.ProcessHandle != IntPtr.Zero) { CloseHandle(child.ProcessHandle); child.ProcessHandle = IntPtr.Zero; }
        }

        /// <summary>
        /// 0: no such process, or it exited. 1: it runs; creationUtc is set. 2: it cannot be read
        /// (for example access denied), so it may run.
        /// </summary>
        public static int ProbeProcess(int processId, out DateTime creationUtc)
        {
            creationUtc = DateTime.MinValue;
            IntPtr process = OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION | SYNCHRONIZE, false, processId);
            if (process == IntPtr.Zero)
                return Marshal.GetLastWin32Error() == ERROR_INVALID_PARAMETER ? 0 : 2;
            try
            {
                uint wait = WaitForSingleObject(process, 0);
                if (wait == WAIT_OBJECT_0) return 0;
                if (wait != WAIT_TIMEOUT) return 2;
                long creation, exit, kernel, user;
                if (!GetProcessTimes(process, out creation, out exit, out kernel, out user)) return 2;
                creationUtc = DateTime.FromFileTimeUtc(creation);
                return 1;
            }
            finally { CloseHandle(process); }
        }
    }
}
'@
}

function Get-CreditsJobName {
    <# .SYNOPSIS The job name of a segment: Local\{{PROJECT_NAME_UPPER}}Credits-<segment id>. #>
    param([Parameter(Mandatory = $true)][ValidatePattern('^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$')][string]$SegmentId)
    return $script:JobNamePrefix + $SegmentId
}

function New-CreditsJob {
    <#
    .SYNOPSIS
        Create the named kill-on-close job of a segment and return its only handle.
    .DESCRIPTION
        Throws when the job cannot be created, and when a job of that name exists: the caller never
        shares a handle that another supervisor holds.
    #>
    param([Parameter(Mandatory = $true)][ValidatePattern('^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$')][string]$SegmentId)
    $name = Get-CreditsJobName -SegmentId $SegmentId
    $handle = [ClaudeCredits.JobNative]::CreateKillOnCloseJob($name)
    return [pscustomobject]@{ Name = $name; SegmentId = $SegmentId; Handle = $handle; Closed = $false }
}

function Assert-OpenJob($Job) {
    if ($null -eq $Job -or $Job.Closed -or $Job.Handle -eq [IntPtr]::Zero) { throw "the job handle is closed" }
}

function Get-CreditsJobActiveCount {
    <# .SYNOPSIS The number of live processes in the job. #>
    param([Parameter(Mandatory = $true)]$Job)
    Assert-OpenJob $Job
    return [ClaudeCredits.JobNative]::ActiveProcesses($Job.Handle)
}

function ConvertTo-CreditsEnvironmentBlock {
    param([Parameter(Mandatory = $true)][System.Collections.IDictionary]$Environment)
    $pairs = foreach ($key in $Environment.Keys) {
        $name = [string]$key
        if ([string]::IsNullOrEmpty($name) -or $name.Contains('=') -or $name.Contains("`0")) { throw "not a valid environment name: '$name'" }
        $value = [string]$Environment[$key]
        if ($value.Contains("`0")) { throw "the value of $name holds a NUL character" }
        [pscustomobject]@{ Name = $name; Text = "$name=$value" }
    }
    # Windows expects the block sorted by name, without regard to case.
    $sorted = @($pairs) | Sort-Object -Property @{ Expression = { $_.Name.ToUpperInvariant() } }
    return ((@($sorted | ForEach-Object { $_.Text }) -join "`0") + "`0")
}

function Start-CreditsJobProcess {
    <#
    .SYNOPSIS
        Create a process suspended and inside the job, with no inherited handle.
    .DESCRIPTION
        -CommandLine holds the arguments only, as Windows parses them; the quoted -FilePath goes
        before them. -Environment replaces the environment block; without it the child gets this
        process's environment. Returns the child: ProcessId and CreationUtc. Call
        Resume-CreditsJobProcess to start it.
    #>
    param(
        [Parameter(Mandatory = $true)]$Job,
        [Parameter(Mandatory = $true)][string]$FilePath,
        [string]$CommandLine = '',
        [Parameter(Mandatory = $true)][string]$WorkingDirectory,
        [System.Collections.IDictionary]$Environment
    )
    Assert-OpenJob $Job
    if (-not [System.IO.Path]::IsPathRooted($FilePath)) {
        $found = Get-Command -Name $FilePath -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($null -eq $found) { throw "executable not found: $FilePath" }
        $FilePath = $found.Source
    }
    if (-not (Test-Path -LiteralPath $FilePath -PathType Leaf)) { throw "executable not found: $FilePath" }
    if (-not (Test-Path -LiteralPath $WorkingDirectory -PathType Container)) { throw "working directory not found: $WorkingDirectory" }
    $line = "`"$FilePath`""
    if (-not [string]::IsNullOrEmpty($CommandLine)) { $line += " $CommandLine" }
    $block = if ($PSBoundParameters.ContainsKey('Environment') -and $null -ne $Environment) { ConvertTo-CreditsEnvironmentBlock -Environment $Environment } else { $null }
    return [ClaudeCredits.JobNative]::StartSuspendedInJob($Job.Handle, $FilePath, $line, (Resolve-Path -LiteralPath $WorkingDirectory).ProviderPath, $block)
}

function Resume-CreditsJobProcess {
    <# .SYNOPSIS Resume a child that Start-CreditsJobProcess created, and close its handles. #>
    param([Parameter(Mandatory = $true)][ClaudeCredits.JobChild]$Child)
    [ClaudeCredits.JobNative]::Resume($Child)
}

function Stop-CreditsJob {
    <# .SYNOPSIS End every member of the job and wait until the job is empty. #>
    param([Parameter(Mandatory = $true)]$Job, [int]$TimeoutSec = 15)
    if ($null -eq $Job -or $Job.Closed) { return }
    [ClaudeCredits.JobNative]::Terminate($Job.Handle, 1)
    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    while ((Get-CreditsJobActiveCount -Job $Job) -gt 0) {
        if ((Get-Date) -ge $deadline) { throw "the job $($Job.Name) still has members after $TimeoutSec s" }
        Start-Sleep -Milliseconds 100
    }
}

function Close-CreditsJob {
    <#
    .SYNOPSIS
        Close the job handle. When it is the last handle, Windows ends every member (kill on
        close) and the name goes away. A second call does nothing.
    #>
    param([Parameter(Mandatory = $true)]$Job)
    if ($null -eq $Job -or $Job.Closed) { return }
    $handle = $Job.Handle
    $Job.Handle = [IntPtr]::Zero
    $Job.Closed = $true
    [ClaudeCredits.JobNative]::Close($handle)
}

function Get-CreditsBootId {
    <#
    .SYNOPSIS
        The boot id, as "bootid:<n>", from the BootId value of the PrefetchParameters key: the same
        source as tools/Invoke-ClaudeDispatch.ps1. Throws when it cannot be read.
    #>
    $key = 'HKLM:\SYSTEM\CurrentControlSet\Control\Session Manager\Memory Management\PrefetchParameters'
    $value = (Get-ItemProperty -LiteralPath $key -Name BootId -ErrorAction Stop).BootId
    if ($null -eq $value) { throw "the BootId value is empty" }
    return "bootid:$value"
}

function ConvertTo-CreditsUtc($Value) {
    if ($null -eq $Value) { return $null }
    if ($Value -is [datetime]) {
        if ($Value.Kind -eq [System.DateTimeKind]::Unspecified) { return [datetime]::SpecifyKind($Value, [System.DateTimeKind]::Utc) }
        return $Value.ToUniversalTime()
    }
    if ($Value -is [System.DateTimeOffset]) { return $Value.UtcDateTime }
    $styles = [System.Globalization.DateTimeStyles]::AssumeUniversal -bor [System.Globalization.DateTimeStyles]::AdjustToUniversal
    $parsed = [datetime]::MinValue
    if ([datetime]::TryParse([string]$Value, [System.Globalization.CultureInfo]::InvariantCulture, $styles, [ref]$parsed)) { return $parsed }
    return $null
}

function Format-CreditsUtc {
    <# .SYNOPSIS A UTC time in the store format, yyyy-MM-ddTHH:mm:ssZ (seconds truncated). #>
    param([Parameter(Mandatory = $true)][datetime]$Value)
    return (ConvertTo-CreditsUtc $Value).ToString('yyyy-MM-ddTHH:mm:ssZ', [System.Globalization.CultureInfo]::InvariantCulture)
}

function Get-RecordedValue($Record, [string]$Name) {
    if ($Record -is [System.Collections.IDictionary]) { return $Record[$Name] }
    $prop = $Record.PSObject.Properties[$Name]
    if ($null -eq $prop) { return $null }
    return $prop.Value
}

function Test-CreditsProcessAlive {
    <#
    .SYNOPSIS
        'dead', 'alive' or 'unknown' for one recorded process. A live pid with another creation
        time is a reused pid, so it is dead. A creation time that cannot be read is unknown.
    #>
    param([Parameter(Mandatory = $true)][int]$ProcessId, $Created)
    $actual = [datetime]::MinValue
    $probe = [ClaudeCredits.JobNative]::ProbeProcess($ProcessId, [ref]$actual)
    if ($probe -eq 0) { return 'dead' }
    if ($probe -ne 1) { return 'unknown' }
    $recorded = ConvertTo-CreditsUtc $Created
    if ($null -eq $recorded) { return 'unknown' }
    if ([math]::Abs(($actual - $recorded).TotalSeconds) -lt $script:CreationToleranceSec) { return 'alive' }
    return 'dead'
}

function Get-CreditsJobProof {
    <#
    .SYNOPSIS
        The job proof of a segment: live, empty, gone or unknown (report section 4.4, R5-d).
    .DESCRIPTION
        -Processes lists the recorded identities (pid and created) of the supervisor and the child.
        -Observation replaces what this host reports, key by key, for tests: boot_id, open_error
        (0 for an open job), active_processes and current_session. A missing key is read from the
        host.
    #>
    param(
        [Parameter(Mandatory = $true)][string]$JobName,
        [Parameter(Mandatory = $true)][int]$LauncherSession,
        [Parameter(Mandatory = $true)][string]$BootId,
        [object[]]$Processes = @(),
        [hashtable]$Observation = @{}
    )
    $currentBoot = if ($Observation.ContainsKey('boot_id')) { [string]$Observation['boot_id'] } else { Get-CreditsBootId }
    if ($BootId -ne $currentBoot) {
        return [pscustomobject]@{ Result = 'empty'; Reason = 'boot_changed'; OpenError = $null; ActiveProcesses = $null }
    }

    $openError = 0
    $active = -1
    if ($Observation.ContainsKey('open_error')) {
        $openError = [int]$Observation['open_error']
        if ($openError -eq 0) {
            if ($Observation.ContainsKey('active_processes')) { $active = [int]$Observation['active_processes'] }
            else { $openError = [ClaudeCredits.JobNative]::ObserveJob($JobName, [ref]$active) }
        }
    } else {
        $openError = [ClaudeCredits.JobNative]::ObserveJob($JobName, [ref]$active)
        if ($openError -eq 0 -and $Observation.ContainsKey('active_processes')) { $active = [int]$Observation['active_processes'] }
    }

    if ($openError -eq 0) {
        $result = if ($active -gt 0) { 'live' } else { 'empty' }
        return [pscustomobject]@{ Result = $result; Reason = 'job_open'; OpenError = 0; ActiveProcesses = $active }
    }
    # 2 ERROR_FILE_NOT_FOUND: no job of that name in this session's Local\ namespace.
    if ($openError -ne 2) {
        return [pscustomobject]@{ Result = 'unknown'; Reason = 'open_error'; OpenError = $openError; ActiveProcesses = $null }
    }
    $session = if ($Observation.ContainsKey('current_session')) { [int]$Observation['current_session'] } else { [System.Diagnostics.Process]::GetCurrentProcess().SessionId }
    if ($session -ne $LauncherSession) {
        return [pscustomobject]@{ Result = 'unknown'; Reason = 'other_session'; OpenError = $openError; ActiveProcesses = $null }
    }
    foreach ($record in @($Processes)) {
        if ($null -eq $record) { continue }
        $pidValue = Get-RecordedValue $record 'pid'
        if ($null -eq $pidValue -or [string]::IsNullOrWhiteSpace([string]$pidValue)) { continue }
        $state = Test-CreditsProcessAlive -ProcessId ([int]$pidValue) -Created (Get-RecordedValue $record 'created')
        if ($state -ne 'dead') {
            return [pscustomobject]@{ Result = 'unknown'; Reason = "process_$state"; OpenError = $openError; ActiveProcesses = $null }
        }
    }
    return [pscustomobject]@{ Result = 'gone'; Reason = 'not_found_all_dead'; OpenError = $openError; ActiveProcesses = $null }
}

if (-not ('ClaudeCredits.JobControl' -as [type])) {
    Add-Type -Language CSharp -TypeDefinition @'
using System;
using System.Runtime.InteropServices;

namespace ClaudeCredits
{
    /// <summary>Terminate a named job from a process that does not hold it (report section 4.4).</summary>
    public static class JobControl
    {
        const uint JOB_OBJECT_QUERY = 0x0004;
        const uint JOB_OBJECT_TERMINATE = 0x0008;

        [DllImport("kernel32.dll", SetLastError = true, CharSet = CharSet.Unicode)]
        static extern IntPtr OpenJobObjectW(uint access, bool inherit, string name);
        [DllImport("kernel32.dll", SetLastError = true)]
        static extern bool TerminateJobObject(IntPtr job, uint exitCode);
        [DllImport("kernel32.dll", SetLastError = true)]
        static extern bool CloseHandle(IntPtr handle);

        /// <summary>Open the job by name and end every member. Returns 0, or the Win32 error.</summary>
        public static int TerminateByName(string name, uint exitCode)
        {
            IntPtr job = OpenJobObjectW(JOB_OBJECT_TERMINATE | JOB_OBJECT_QUERY, false, name);
            if (job == IntPtr.Zero) return Marshal.GetLastWin32Error();
            try
            {
                if (!TerminateJobObject(job, exitCode)) return Marshal.GetLastWin32Error();
                return 0;
            }
            finally { CloseHandle(job); }
        }
    }
}
'@
}

function Stop-CreditsJobByName {
    <#
    .SYNOPSIS
        End every member of the named job of a segment. Returns 0, or the Win32 error of the open
        or the terminate call (2: no job of that name). The caller does not finalize: a later pass
        reads the job proof again (report section 4.4, P-8b f).
    #>
    param(
        [Parameter(Mandatory = $true)][ValidatePattern('^Local\\{{PROJECT_NAME_UPPER}}Credits-[A-Za-z0-9][A-Za-z0-9._-]{0,127}$')][string]$JobName,
        [uint32]$ExitCode = 1
    )
    return [ClaudeCredits.JobControl]::TerminateByName($JobName, $ExitCode)
}

function Get-CreditsProcessState {
    <# .SYNOPSIS 'dead', 'alive' or 'unknown' for one recorded process (pid plus creation time). #>
    param([Parameter(Mandatory = $true)][int]$ProcessId, $Created)
    return Test-CreditsProcessAlive -ProcessId $ProcessId -Created $Created
}

function Get-CreditsPython {
    <# .SYNOPSIS The repository's virtual-environment Python, else python on PATH. #>
    $venv = Join-Path $script:RepoRoot '.venv/Scripts/python.exe'
    if (Test-Path -LiteralPath $venv -PathType Leaf) { return $venv }
    $found = Get-Command -Name python -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($null -eq $found) { throw 'python not found: no .venv in the repository and no python on PATH' }
    return $found.Source
}

function Invoke-CreditsState {
    <#
    .SYNOPSIS
        Run one credits_state.py verb. Returns Code, Payload (the parsed JSON line, or $null), Out
        and Err. It does not throw on a non-zero exit; the caller reads Code.
    #>
    param(
        [Parameter(Mandatory = $true)][string]$StateDb,
        [Parameter(Mandatory = $true)][ValidatePattern('^[a-z_]+$')][string]$Verb,
        [string[]]$Arguments = @(),
        [ValidateRange(1, 3600)][int]$TimeoutSec = 180,
        # The store clock (--now-utc), for the verbs whose result depends on an age.
        [Nullable[datetime]]$NowUtc
    )
    # PowerShell unwraps a [Nullable[datetime]] parameter to a plain [datetime]; it has no .Value.
    $clock = if ($null -ne $NowUtc) { @('--now-utc', (Format-CreditsUtc ([datetime]$NowUtc))) } else { @() }
    $psi = [System.Diagnostics.ProcessStartInfo]::new((Get-CreditsPython))
    foreach ($a in @('-X', 'utf8', $script:StateTool, '--db', $StateDb) + $clock + @($Verb) + @($Arguments)) { $psi.ArgumentList.Add([string]$a) }
    $psi.UseShellExecute = $false
    $psi.CreateNoWindow = $true
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true
    $proc = [System.Diagnostics.Process]::Start($psi)
    try {
        $outTask = $proc.StandardOutput.ReadToEndAsync()
        $errTask = $proc.StandardError.ReadToEndAsync()
        if (-not $proc.WaitForExit($TimeoutSec * 1000)) {
            try { $proc.Kill($true) } catch { [Console]::Error.WriteLine("credits_state.py kill failed: $($_.Exception.Message)") }
            throw "credits_state.py $Verb did not end in $TimeoutSec s"
        }
        $proc.WaitForExit()
        $out = $outTask.Result
        $payload = $null
        $last = @($out -split "`r?`n" | Where-Object { -not [string]::IsNullOrWhiteSpace($_) }) | Select-Object -Last 1
        if ($last) {
            try { $payload = $last | ConvertFrom-Json -ErrorAction Stop } catch { $payload = $null }
        }
        return [pscustomobject]@{ Code = $proc.ExitCode; Payload = $payload; Out = $out; Err = $errTask.Result }
    } finally {
        $proc.Dispose()
    }
}

function Format-CreditsStateError($Result) {
    $error_ = $null
    if ($null -ne $Result.Payload) {
        $prop = $Result.Payload.PSObject.Properties['error']
        if ($null -ne $prop) { $error_ = $prop.Value }
    }
    $text = if ($error_) { ($error_ | ConvertTo-Json -Compress -Depth 4) } else { ($Result.Out + ' ' + $Result.Err).Trim() }
    return "exit $($Result.Code): $text"
}

function Complete-CreditsSegment {
    <#
    .SYNOPSIS
        Finalize one segment (complete_segment). A second call returns no_change. Throws when the
        store refuses or fails, and returns the store payload otherwise.
    #>
    param(
        [Parameter(Mandatory = $true)][string]$StateDb,
        [Parameter(Mandatory = $true)][string]$SegmentId,
        [Parameter(Mandatory = $true)][ValidateSet('launcher', 'monitor', 'wrapper')][string]$FinalizedBy,
        [Parameter(Mandatory = $true)][ValidatePattern('^[a-z][a-z0-9_]{0,63}$')][string]$Class,
        [Nullable[double]]$SessionTotalUsd,
        [Nullable[int]]$ExitCode
    )
    $argsList = @('--segment-id', $SegmentId, '--finalized-by', $FinalizedBy, '--class', $Class)
    if ($null -ne $SessionTotalUsd) { $argsList += @('--session-total-usd', ([double]$SessionTotalUsd).ToString('R', [System.Globalization.CultureInfo]::InvariantCulture)) }
    if ($null -ne $ExitCode) { $argsList += @('--exit-code', [string][int]$ExitCode) }
    $res = Invoke-CreditsState -StateDb $StateDb -Verb complete_segment -Arguments $argsList
    if ($res.Code -ne 0) { throw "complete_segment failed for ${SegmentId}: $(Format-CreditsStateError $res)" }
    return $res.Payload
}

function Start-CreditsManualChild {
    <#
    .SYNOPSIS
        Report section 7.2 steps 3 to 5 for a manual run: create the child suspended inside the
        job, store its identity (manual_identity), then resume it with CREDITS_RUN_ID,
        CREDITS_STATE_DB and CREDITS_SEGMENT. Returns the child as a Process.
    .DESCRIPTION
        $StartInfo is the dispatch wrapper's final start info: its file name, arguments, working
        directory and environment are used as they are, plus the three CREDITS_* names. A child
        whose identity the store refuses is ended before it runs, and the call throws.
    #>
    param(
        [Parameter(Mandatory = $true)][System.Diagnostics.ProcessStartInfo]$StartInfo,
        [Parameter(Mandatory = $true)][hashtable]$Context
    )
    $environment = [System.Collections.Generic.Dictionary[string, string]]::new([System.StringComparer]::OrdinalIgnoreCase)
    foreach ($key in @($StartInfo.Environment.Keys)) {
        if ($key -match '^CREDITS_') { continue }
        $environment[$key] = [string]$StartInfo.Environment[$key]
    }
    $environment['CREDITS_RUN_ID'] = $Context.RunId
    $environment['CREDITS_STATE_DB'] = $Context.StateDb
    $environment['CREDITS_SEGMENT'] = $Context.SegmentId

    $workDir = if ($StartInfo.WorkingDirectory) { $StartInfo.WorkingDirectory } else { (Get-Location).ProviderPath }
    $child = Start-CreditsJobProcess -Job $Context.Job -FilePath $StartInfo.FileName -CommandLine $StartInfo.Arguments `
        -WorkingDirectory $workDir -Environment $environment
    $process = $null
    try {
        # Open the Process while the child is suspended: it cannot exit before its handle is held,
        # so its exit code stays readable.
        $process = [System.Diagnostics.Process]::GetProcessById($child.ProcessId)
        $null = $process.Handle
        $res = Invoke-CreditsState -StateDb $Context.StateDb -Verb manual_identity -Arguments @(
            '--segment-id', $Context.SegmentId, '--pid', [string]$child.ProcessId, '--created', (Format-CreditsUtc $child.CreationUtc))
        if ($res.Code -ne 0) { throw "manual_identity failed for $($Context.SegmentId): $(Format-CreditsStateError $res)" }
    } catch {
        [ClaudeCredits.JobNative]::Abandon($child)
        if ($null -ne $process) { $process.Dispose() }
        throw
    }
    Resume-CreditsJobProcess -Child $child
    $Context.Resumed = $true
    return $process
}

function Get-CreditsConstants {
    <#
    .SYNOPSIS
        The request limits of the store (tools/credits_state.py): a launcher accepts a request
        younger than REQUEST_ACCEPT_TIMEOUT_S, and the monitor ends a pending request older than
        ORPHAN_REQUEST_S (report section 4.2).
    #>
    return [pscustomobject]@{ REQUEST_ACCEPT_TIMEOUT_S = 120; ORPHAN_REQUEST_S = 150 }
}

function Get-CreditsTaskArgument([string]$ScriptPath, [string]$Tail) {
    $text = "-NoProfile -NonInteractive -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$ScriptPath`""
    if ($Tail) { $text += " $Tail" }
    return $text
}

function Assert-AbsolutePath([string]$Path, [string]$Name) {
    if ([string]::IsNullOrWhiteSpace($Path) -or -not [System.IO.Path]::IsPathRooted($Path)) { throw "$Name must be an absolute path: '$Path'" }
}

function New-CreditsTaskDefinition {
    <#
    .SYNOPSIS
        The expected definition of the run task \{{PROJECT_NAME_TITLE}}\Credits\<run id> (report section 4.2,
        step 3): no trigger, the current user, Interactive, Limited, and the launcher with -RunId
        only.
    .DESCRIPTION
        The scheduler adapter registers this object, and its read-back returns an object of the
        same shape, so Get-CreditsTaskDefinitionHash compares the two.
    #>
    param(
        [Parameter(Mandatory = $true)][ValidatePattern('^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$')][string]$RunId,
        [Parameter(Mandatory = $true)][string]$ProjectRoot,
        [Parameter(Mandatory = $true)][string]$PwshPath,
        [Parameter(Mandatory = $true)][string]$LauncherPath,
        [Parameter(Mandatory = $true)][ValidateRange(1, 604800)][int]$TimeoutSec
    )
    Assert-AbsolutePath $ProjectRoot 'ProjectRoot'
    Assert-AbsolutePath $PwshPath 'PwshPath'
    Assert-AbsolutePath $LauncherPath 'LauncherPath'
    return [pscustomobject][ordered]@{
        TaskPath                   = '\{{PROJECT_NAME_TITLE}}\Credits\'
        TaskName                   = $RunId
        Execute                    = $PwshPath
        Argument                   = Get-CreditsTaskArgument $LauncherPath "-RunId $RunId"
        WorkingDirectory           = $ProjectRoot
        LogonType                  = 'Interactive'
        RunLevel                   = 'Limited'
        AllowStartIfOnBatteries    = $true
        DontStopIfGoingOnBatteries = $true
        MultipleInstances          = 'IgnoreNew'
        # The task limit is the segment timeout plus 2 h, so the launcher always ends first.
        ExecutionTimeLimitSec      = $TimeoutSec + 7200
        Priority                   = 5
        Triggers                   = @()
        RestartCount               = 0
        WakeToRun                  = $false
    }
}

function New-CreditsMonitorTaskDefinition {
    <#
    .SYNOPSIS
        The expected definition of \{{PROJECT_NAME_TITLE}}\Credits\Monitor (report section 4.2, step 4): an
        AtLogOn trigger plus a Once trigger that repeats every 5 minutes with no duration.
    #>
    param(
        [Parameter(Mandatory = $true)][string]$PwshPath,
        [Parameter(Mandatory = $true)][string]$MonitorPath,
        [Parameter(Mandatory = $true)][string]$WorkingDirectory
    )
    Assert-AbsolutePath $PwshPath 'PwshPath'
    Assert-AbsolutePath $MonitorPath 'MonitorPath'
    Assert-AbsolutePath $WorkingDirectory 'WorkingDirectory'
    return [pscustomobject][ordered]@{
        TaskPath                   = '\{{PROJECT_NAME_TITLE}}\Credits\'
        TaskName                   = 'Monitor'
        Execute                    = $PwshPath
        Argument                   = Get-CreditsTaskArgument $MonitorPath ''
        WorkingDirectory           = $WorkingDirectory
        LogonType                  = 'Interactive'
        RunLevel                   = 'Limited'
        AllowStartIfOnBatteries    = $true
        DontStopIfGoingOnBatteries = $true
        MultipleInstances          = 'IgnoreNew'
        ExecutionTimeLimitSec      = 600
        Priority                   = 7
        Triggers                   = @(
            [pscustomobject][ordered]@{ Kind = 'AtLogOn'; RepetitionInterval = $null }
            [pscustomobject][ordered]@{ Kind = 'Once'; RepetitionInterval = 'PT5M' }
        )
        RestartCount               = 0
        WakeToRun                  = $false
    }
}

function ConvertTo-CreditsCanonical($Value) {
    if ($null -eq $Value) { return $null }
    if ($Value -is [string] -or $Value -is [bool] -or $Value -is [ValueType]) { return $Value }
    if ($Value -is [System.Collections.IDictionary]) {
        $out = [ordered]@{}
        foreach ($k in @($Value.Keys | ForEach-Object { [string]$_ } | Sort-Object -CaseSensitive)) { $out[$k] = ConvertTo-CreditsCanonical $Value[$k] }
        return $out
    }
    if ($Value -is [System.Collections.IEnumerable]) {
        return , @(foreach ($item in $Value) { ConvertTo-CreditsCanonical $item })
    }
    $out = [ordered]@{}
    foreach ($name in @($Value.PSObject.Properties | Where-Object { $_.MemberType -in 'NoteProperty', 'Property' } | ForEach-Object { $_.Name } | Sort-Object -CaseSensitive)) {
        $out[$name] = ConvertTo-CreditsCanonical $Value.PSObject.Properties[$name].Value
    }
    return $out
}

function Get-CreditsTaskDefinitionHash {
    <# .SYNOPSIS The SHA-256 (hex) of a task definition as canonical JSON (keys sorted). #>
    param([Parameter(Mandatory = $true)]$Definition)
    $json = ConvertTo-Json -InputObject (ConvertTo-CreditsCanonical $Definition) -Depth 8 -Compress
    $bytes = [System.Text.Encoding]::UTF8.GetBytes($json)
    return [System.Convert]::ToHexString([System.Security.Cryptography.SHA256]::HashData($bytes)).ToLowerInvariant()
}

function ConvertFrom-CreditsScheduledTask($Task) {
    # The read-back of a real task, in the shape of New-CreditsTaskDefinition.
    $action = @($Task.Actions)[0]
    $settings = $Task.Settings
    # A run task has no trigger: Get-ScheduledTask gives Triggers = $null, and @($null) holds one
    # $null item that Set-StrictMode does not let us read (EA-88).
    $triggers = @(foreach ($t in @($Task.Triggers | Where-Object { $null -ne $_ })) {
            $kind = switch ($t.CimClass.CimClassName) {
                'MSFT_TaskLogonTrigger' { 'AtLogOn' }
                'MSFT_TaskTimeTrigger' { 'Once' }
                default { [string]$t.CimClass.CimClassName }
            }
            $interval = if ($null -ne $t.Repetition -and $t.Repetition.Interval) { [string]$t.Repetition.Interval } else { $null }
            [pscustomobject][ordered]@{ Kind = $kind; RepetitionInterval = $interval }
        })
    $limit = if ($settings.ExecutionTimeLimit) { [int][System.Xml.XmlConvert]::ToTimeSpan($settings.ExecutionTimeLimit).TotalSeconds } else { 0 }
    return [pscustomobject][ordered]@{
        TaskPath                   = [string]$Task.TaskPath
        TaskName                   = [string]$Task.TaskName
        Execute                    = [string]$action.Execute
        Argument                   = [string]$action.Arguments
        WorkingDirectory           = [string]$action.WorkingDirectory
        LogonType                  = [string]$Task.Principal.LogonType
        RunLevel                   = [string]$Task.Principal.RunLevel
        AllowStartIfOnBatteries    = -not [bool]$settings.DisallowStartIfOnBatteries
        DontStopIfGoingOnBatteries = -not [bool]$settings.StopIfGoingOnBatteries
        MultipleInstances          = [string]$settings.MultipleInstances
        ExecutionTimeLimitSec      = $limit
        Priority                   = [int]$settings.Priority
        Triggers                   = $triggers
        RestartCount               = [int]$settings.RestartCount
        WakeToRun                  = [bool]$settings.WakeToRun
    }
}

function Read-CreditsLauncherEnv {
    <#
    .SYNOPSIS
        The launcher environment file (framework-template-scope.md, Port plan 5): a Task Scheduler
        task starts the launcher with the logon environment, so a session-scoped name such as
        AGENT_MODEL_REGISTRY_HOME (.agent/INSTANTIATE.md section 1) reaches a scheduled run only
        through this file. Returns Env (an ordered name → value map) and PathPrepend (the folders
        to put first in PATH). A missing file returns both empty.
    .DESCRIPTION
        The file is {"env": {"NAME": "value"}, "path_prepend": ["<absolute folder>"]}; both keys
        are optional and no other key is allowed. A name is [A-Za-z_][A-Za-z0-9_]*, used once (the
        Windows environment ignores case). The file may not set PATH (use path_prepend), a name
        the launcher sets or removes itself (CREDITS_*, CLAUDECODE, CLAUDE_CODE_*,
        ELECTRON_RUN_AS_NODE, DISABLE_PROMPT_CACHING, DISABLE_AUTOUPDATER, BASH_*_TIMEOUT_MS), or
        ANTHROPIC_* (the API key comes only from the key file). A file that is not valid throws
        "launcher_env_invalid: <reason>".
    #>
    param([Parameter(Mandatory = $true)][string]$Path)
    $result = [pscustomobject]@{ Env = [ordered]@{}; PathPrepend = [string[]]@() }
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { return $result }
    $fail = { param([string]$Reason) throw "launcher_env_invalid: ${Reason} ($Path)" }
    try {
        $doc = [System.IO.File]::ReadAllText($Path, [System.Text.Encoding]::UTF8) | ConvertFrom-Json -AsHashtable -ErrorAction Stop
    } catch {
        & $fail "not JSON: $($_.Exception.Message)"
    }
    if ($doc -isnot [System.Collections.IDictionary]) { & $fail 'the top level is not an object' }
    foreach ($key in @($doc.Keys)) {
        if ([string]$key -cnotin @('env', 'path_prepend')) { & $fail "unknown key '$key'" }
    }
    $reserved = '^(?i)(PATH|CLAUDECODE|ELECTRON_RUN_AS_NODE|DISABLE_PROMPT_CACHING|DISABLE_AUTOUPDATER|BASH_DEFAULT_TIMEOUT_MS|BASH_MAX_TIMEOUT_MS)$|^(?i)(CREDITS_|CLAUDE_CODE_|ANTHROPIC_)'
    if ($doc.Contains('env')) {
        $envMap = $doc['env']
        if ($envMap -isnot [System.Collections.IDictionary]) { & $fail 'env is not an object' }
        $seen = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::OrdinalIgnoreCase)
        foreach ($name in @($envMap.Keys)) {
            $name = [string]$name
            if ($name -cnotmatch '^[A-Za-z_][A-Za-z0-9_]*$') { & $fail "'$name' is not a variable name" }
            if (-not $seen.Add($name)) { & $fail "'$name' is set two times (names ignore case)" }
            if ($name -match $reserved) { & $fail "'$name' may not be set here" }
            $value = $envMap[$name]
            if ($value -isnot [string]) { & $fail "the value of '$name' is not a string" }
            if ($value.Contains([char]0)) { & $fail "the value of '$name' holds a NUL character" }
            $result.Env[$name] = $value
        }
    }
    if ($doc.Contains('path_prepend')) {
        $folders = $doc['path_prepend']
        if ($folders -is [string] -or $folders -isnot [System.Collections.IList]) { & $fail 'path_prepend is not a list' }
        $list = [System.Collections.Generic.List[string]]::new()
        foreach ($folder in $folders) {
            if ($folder -isnot [string]) { & $fail 'a path_prepend folder is not a string' }
            if ($folder.Contains(';') -or $folder.Contains([char]0)) { & $fail "the path_prepend folder '$folder' holds a list separator" }
            if (-not [System.IO.Path]::IsPathFullyQualified($folder)) { & $fail "the path_prepend folder '$folder' is not an absolute path" }
            $list.Add($folder)
        }
        $result.PathPrepend = $list.ToArray()
    }
    return $result
}

function New-CreditsSchedulerAdapter {
    <#
    .SYNOPSIS
        The real Task Scheduler adapter: a hashtable of Register($Definition),
        Get($TaskPath, $TaskName) and Start($TaskPath, $TaskName) script blocks. Tests inject a
        fake with the same keys (AC-D.6).
    .DESCRIPTION
        Register always registers the whole task again (-Force): Set-ScheduledTask with a new
        settings set resets every setting it does not pass (report section 4.2, traps). Get
        returns $null for a missing task, else the read-back in the shape of the definition.
    #>
    $register = {
        param($Definition)
        $action = New-ScheduledTaskAction -Execute $Definition.Execute -Argument $Definition.Argument -WorkingDirectory $Definition.WorkingDirectory
        $userId = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
        $principal = New-ScheduledTaskPrincipal -UserId $userId -LogonType $Definition.LogonType -RunLevel $Definition.RunLevel
        $settingsArgs = @{
            MultipleInstances  = $Definition.MultipleInstances
            ExecutionTimeLimit = [timespan]::FromSeconds([int]$Definition.ExecutionTimeLimitSec)
            Priority           = [int]$Definition.Priority
        }
        if ($Definition.AllowStartIfOnBatteries) { $settingsArgs['AllowStartIfOnBatteries'] = $true }
        if ($Definition.DontStopIfGoingOnBatteries) { $settingsArgs['DontStopIfGoingOnBatteries'] = $true }
        if ($Definition.WakeToRun) { $settingsArgs['WakeToRun'] = $true }
        $settings = New-ScheduledTaskSettingsSet @settingsArgs
        $triggers = @(foreach ($t in @($Definition.Triggers)) {
                switch ($t.Kind) {
                    'AtLogOn' { New-ScheduledTaskTrigger -AtLogOn -User $userId }
                    'Once' {
                        $interval = [System.Xml.XmlConvert]::ToTimeSpan([string]$t.RepetitionInterval)
                        New-ScheduledTaskTrigger -Once -At (Get-Date) -RepetitionInterval $interval
                    }
                    default { throw "unknown trigger kind: $($t.Kind)" }
                }
            })
        $taskArgs = @{
            TaskPath = $Definition.TaskPath; TaskName = $Definition.TaskName; Action = $action
            Principal = $principal; Settings = $settings; Force = $true; ErrorAction = 'Stop'
        }
        if ($triggers.Count -gt 0) { $taskArgs['Trigger'] = $triggers }
        $null = Register-ScheduledTask @taskArgs
    }
    $get = {
        param($TaskPath, $TaskName)
        $task = Get-ScheduledTask -TaskPath $TaskPath -TaskName $TaskName -ErrorAction SilentlyContinue
        if ($null -eq $task) { return $null }
        return ConvertFrom-CreditsScheduledTask $task
    }
    $start = {
        param($TaskPath, $TaskName)
        Start-ScheduledTask -TaskPath $TaskPath -TaskName $TaskName -ErrorAction Stop
    }
    return @{ Register = $register; Get = $get; Start = $start }
}

if (-not ('ClaudeCredits.PowerNative' -as [type])) {
    Add-Type -Language CSharp -TypeDefinition @'
using System;
using System.ComponentModel;
using System.Runtime.InteropServices;

namespace ClaudeCredits
{
    /// <summary>Keep-awake: a PowerRequestSystemRequired power request (report section 4.3, step 5).</summary>
    public static class PowerNative
    {
        const uint POWER_REQUEST_CONTEXT_VERSION = 0;
        const uint POWER_REQUEST_CONTEXT_SIMPLE_STRING = 0x1;
        const int PowerRequestSystemRequired = 1;
        static readonly IntPtr INVALID_HANDLE_VALUE = new IntPtr(-1);

        [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
        struct REASON_CONTEXT
        {
            public uint Version;
            public uint Flags;
            [MarshalAs(UnmanagedType.LPWStr)] public string SimpleReasonString;
        }

        [DllImport("kernel32.dll", SetLastError = true)]
        static extern IntPtr PowerCreateRequest(ref REASON_CONTEXT context);
        [DllImport("kernel32.dll", SetLastError = true)]
        static extern bool PowerSetRequest(IntPtr request, int requestType);
        [DllImport("kernel32.dll", SetLastError = true)]
        static extern bool PowerClearRequest(IntPtr request, int requestType);
        [DllImport("kernel32.dll", SetLastError = true)]
        static extern bool CloseHandle(IntPtr handle);

        /// <summary>Create and set the request. Throws on an error; the caller holds the handle.</summary>
        public static IntPtr Acquire(string reason)
        {
            var context = new REASON_CONTEXT { Version = POWER_REQUEST_CONTEXT_VERSION, Flags = POWER_REQUEST_CONTEXT_SIMPLE_STRING, SimpleReasonString = reason };
            IntPtr handle = PowerCreateRequest(ref context);
            if (handle == IntPtr.Zero || handle == INVALID_HANDLE_VALUE) throw new Win32Exception(Marshal.GetLastWin32Error(), "PowerCreateRequest failed");
            if (!PowerSetRequest(handle, PowerRequestSystemRequired))
            {
                int error = Marshal.GetLastWin32Error();
                CloseHandle(handle);
                throw new Win32Exception(error, "PowerSetRequest failed");
            }
            return handle;
        }

        /// <summary>Clear the request and close its handle. Throws when the clear fails.</summary>
        public static void Release(IntPtr handle)
        {
            if (handle == IntPtr.Zero) return;
            bool cleared = PowerClearRequest(handle, PowerRequestSystemRequired);
            int error = Marshal.GetLastWin32Error();
            CloseHandle(handle);
            if (!cleared) throw new Win32Exception(error, "PowerClearRequest failed");
        }
    }
}
'@
}

function Enter-CreditsKeepAwake {
    <#
    .SYNOPSIS
        Ask Windows to stay awake while a segment runs. Returns a handle object for
        Exit-CreditsKeepAwake. It does not stop an explicit sleep or an update reboot.
    #>
    param([Parameter(Mandatory = $true)][string]$Reason)
    return [pscustomobject]@{ Handle = [ClaudeCredits.PowerNative]::Acquire($Reason); Released = $false }
}

function Exit-CreditsKeepAwake {
    <# .SYNOPSIS Release the keep-awake request. A second call does nothing. #>
    param($KeepAwake)
    if ($null -eq $KeepAwake -or $KeepAwake.Released) { return }
    $handle = $KeepAwake.Handle
    $KeepAwake.Handle = [IntPtr]::Zero
    $KeepAwake.Released = $true
    [ClaudeCredits.PowerNative]::Release($handle)
}

function Resolve-CreditsPhysicalPath {
    <#
    .SYNOPSIS
        The physical path of an existing file or directory, or $null.
    .DESCRIPTION
        Each name is looked up on disk, so the result has the on-disk case and no trailing
        separator, and a trailing dot or space drops as Windows drops it. Each junction or
        symbolic link on the way is followed to its target. $null when a name does not exist,
        the path is not valid, or links nest more than 32 deep.
    #>
    param([Parameter(Mandatory = $true)][AllowEmptyString()][string]$Path, [int]$Depth = 0)
    if ($Depth -gt 32 -or [string]::IsNullOrWhiteSpace($Path)) { return $null }
    try { $full = [System.IO.Path]::GetFullPath($Path) } catch { return $null }
    $root = [System.IO.Path]::GetPathRoot($full)
    if (-not $root) { return $null }
    $current = $root.ToUpperInvariant().Replace('/', '\')
    foreach ($raw in @($full.Substring($root.Length) -split '[\\/]+' | Where-Object { $_ })) {
        $name = $raw.TrimEnd('.', ' ')
        if (-not $name -or $name.IndexOfAny([char[]]'*?') -ge 0) { return $null }
        $entry = $null
        try { $entry = @([System.IO.DirectoryInfo]::new($current).EnumerateFileSystemInfos($name)) | Select-Object -First 1 } catch { return $null }
        if ($null -eq $entry) { return $null }
        $target = if ($entry.Attributes -band [System.IO.FileAttributes]::ReparsePoint) { [string]$entry.LinkTarget } else { '' }
        if ($target) {
            # A junction or a symbolic link: go on from its target. A relative target is
            # relative to the folder that holds the link.
            $target = $target -replace '^\\\?\?\\', '' -replace '^\\\\\?\\', ''
            if (-not [System.IO.Path]::IsPathRooted($target)) { $target = Join-Path $current $target }
            $current = Resolve-CreditsPhysicalPath -Path $target -Depth ($Depth + 1)
            if ($null -eq $current) { return $null }
        } else {
            $current = $entry.FullName
        }
    }
    return $current
}

function Test-CreditsSameDirectory {
    <#
    .SYNOPSIS
        True when both paths are existing directories with one physical path (case, junctions,
        symbolic links, trailing separators, dots and spaces resolved).
    #>
    param([AllowEmptyString()][string]$Left, [AllowEmptyString()][string]$Right)
    $a = Resolve-CreditsPhysicalPath -Path $Left
    $b = Resolve-CreditsPhysicalPath -Path $Right
    if ($null -eq $a -or $null -eq $b) { return $false }
    if (-not (Test-Path -LiteralPath $a -PathType Container)) { return $false }
    return [string]::Equals($a, $b, [System.StringComparison]::OrdinalIgnoreCase)
}

Export-ModuleMember -Function @(
    'Get-CreditsJobName', 'New-CreditsJob', 'Get-CreditsJobActiveCount', 'Start-CreditsJobProcess', 'Resume-CreditsJobProcess',
    'Stop-CreditsJob', 'Close-CreditsJob', 'Get-CreditsBootId', 'Format-CreditsUtc', 'Get-CreditsJobProof',
    'Stop-CreditsJobByName', 'Get-CreditsProcessState',
    'Get-CreditsPython', 'Invoke-CreditsState', 'Format-CreditsStateError', 'Complete-CreditsSegment', 'Start-CreditsManualChild',
    'Get-CreditsConstants', 'New-CreditsTaskDefinition', 'New-CreditsMonitorTaskDefinition', 'Get-CreditsTaskDefinitionHash',
    'New-CreditsSchedulerAdapter', 'Enter-CreditsKeepAwake', 'Exit-CreditsKeepAwake', 'Read-CreditsLauncherEnv',
    'Resolve-CreditsPhysicalPath', 'Test-CreditsSameDirectory'
)
