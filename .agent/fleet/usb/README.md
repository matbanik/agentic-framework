# Fleet USB drive

This drive gives the hub machine an SSH admin connection to a new Windows, macOS or Linux machine. Nothing on it
is secret. `hub.pub` is the hub's public key, and each `members/<name>.json` holds a machine's name, account,
addresses and public host key. Anyone who can change the drive could swap `hub.pub` for their own key, so keep
the drive with you.

Use an exFAT drive, which all three systems can read and write.

A new machine with no operating system needs the installer drive first: see
[../install-usb/README.md](../install-usb/README.md).

## 1. On the hub machine

```powershell
python .agent/fleet/usb/fleet_usb.py prepare E:\fleet-usb
```

This prints the hub key's fingerprint (`SHA256:...`). Each machine's script prints the fingerprint of the key it
installs, and the two must match.

## 2. On each machine

Sign in as the account the agent will use. On Windows that account must be an administrator, and on macOS and
Linux it must be able to use `sudo`.

Each system has a file to double-click. A window opens, shows what the setup did, and stays open until you
press a key.

**Windows.** Double-click **Setup Windows.cmd** and accept the administrator prompt. The first run can take 10 to
15 minutes while Windows downloads OpenSSH Server, and the window shows no progress meanwhile. It installs OpenSSH
Server, starts it now and at each boot, and sets sessions to start in Windows PowerShell. It lets port 22 answer
the local subnet only, and installs the hub's key for administrators.

**macOS.** Double-click **Setup Mac.command**. Terminal opens and asks for your password. If macOS asks whether
Terminal may use files on a removable volume, allow it. If Remote Login is off and the script can't turn it on,
it opens System Settings and stops. Turn on **General > Sharing > Remote Login**, then double-click the file
again. Then click the **(i)** button beside Remote Login and turn on **Allow full disk access for remote
users**. No script can set that. If that switch isn't there, open **Privacy & Security > Full Disk Access**,
click **+**, press **Cmd+Shift+G**, enter `/usr/libexec/sshd-keygen-wrapper`, click **Open**, and turn it on.

**Linux (Ubuntu Desktop).** Ubuntu's file manager won't run a file from the drive, so you do two steps once:
copy **Setup Linux.desktop** to the Desktop, then right-click it there and choose **Allow Launching**. Then
double-click it. A terminal opens and asks for your password. The setup installs and starts `openssh-server`.
When `ufw` is on, it lets port 22 answer the local subnet only. It also lets the account's services keep
running after the account signs out.

If a double-click does nothing, run the script from a terminal instead:

```text
Windows (Terminal (Admin)):  powershell -NoProfile -ExecutionPolicy Bypass -File E:\fleet-usb\setup-windows.ps1
macOS:                       sudo bash /Volumes/<drive>/fleet-usb/setup-unix.sh
Linux:                       sudo bash /media/$USER/<drive>/fleet-usb/setup-unix.sh
```

On macOS and Linux the script also installs the hub's key in `~/.ssh/authorized_keys`, and gives the account
`sudo` without a password in `/etc/sudoers.d/fleet-agent`.

You can run a script again at any time, and a repeat run changes nothing. Each run rewrites that machine's
record on the drive.

**A VMware VM on the Mac.** Set the VM's network adapter to **Bridged**, so the hub machine can reach it. Then
connect the drive to the VM (**Virtual Machine > USB & Bluetooth**). Ubuntu Desktop mounts it under
`/media/$USER/`. Take a snapshot before the first run, so that you can repeat the setup from a clean state.

## 3. Back on the hub machine

```powershell
python .agent/fleet/usb/fleet_usb.py import E:\fleet-usb
```

For each machine, this pins its host key and writes an entry named after the machine in `~/.ssh/fleet_config`,
which `~/.ssh/config` includes. Then it connects to the machine. The run passes when every machine reports
`full access`. After that, `ssh <name>` reaches the machine with no prompt, and the agent can take it from
there.

## Undo

**Windows.** Remove the hub's line from `C:\ProgramData\ssh\administrators_authorized_keys`, then run
`Stop-Service sshd; Set-Service sshd -StartupType Disabled`.

**macOS and Linux.** Remove the hub's line from `~/.ssh/authorized_keys`, then delete
`/etc/sudoers.d/fleet-agent`. Turn off Remote Login on macOS, or stop the SSH service on Linux.

**Hub machine.** Delete the machine's entry from `~/.ssh/fleet_members.json`, its `Host` block from
`~/.ssh/fleet_config`, and its line from `~/.ssh/fleet_known_hosts`.
