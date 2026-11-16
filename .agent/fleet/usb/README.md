# Fleet USB drive

This drive gives the hub machine an SSH admin connection to a new Windows, macOS or Linux machine. On a
machine with a screen, it also installs RustDesk, so the hub's agent can see and use the screen. Each machine
sends its record to the hub over the network. The record holds the machine's name, account, addresses and
public host key, and the result of each setup step.

The drive holds `hub.pub` (the hub's public key), `hub.txt` (the hub's URLs and a token that lets a machine
send a record) and, when you use RustDesk, `rustdesk.txt` and a `rustdesk/` folder. The token is not secret
on a network you trust, but anyone who can change the drive could swap `hub.pub` for their own key, so keep the
drive with you.

Use an exFAT drive, which all three systems can read and write.

A new machine with no operating system needs the installer drive first: see
[../install-usb/README.md](../install-usb/README.md).

## 1. On the hub machine

**RustDesk server (optional).** To use RustDesk, build the ID server first. The guide
[RustDesk server on Windows without Docker](https://matbanik.info/hobbies/systems/posts/rustdesk-server-on-windows-without-docker/)
shows how. When it is done, you have a server name or address and a public key file (`id_ed25519.pub`). Skip
this step for a fleet that needs no RustDesk.

**Firewall.** The hub must accept a record on TCP port 8771 from the local network. Open an administrator
PowerShell once and run this line. It makes a rule that is separate from the `Fleet hub 8770` rule:

```powershell
New-NetFirewallRule -DisplayName 'Fleet USB receive 8771' -Direction Inbound -Action Allow -Protocol TCP -LocalPort 8771 -RemoteAddress LocalSubnet -Profile Private
```

**Prepare the drive.** This makes the hub's key if it is missing, copies the member scripts to the drive, and
writes `hub.txt`:

```powershell
python .agent/fleet/usb/fleet_usb.py prepare E:\fleet-usb --rustdesk-host <server>[:port] --rustdesk-key-file <path>\id_ed25519.pub
```

- `--hub-url <url>` (repeat it for more than one) sets where machines send their record. Without it, the
  URLs are `http://<address>:8771` for each address of this machine.
- `--rustdesk-host` and `--rustdesk-key-file` (or `--rustdesk-key`) turn on RustDesk. The command downloads
  the latest RustDesk release for the six platforms to `rustdesk/` on the drive, and writes `rustdesk.txt` with
  the server, the key and a sha256 for each file. A machine checks each file against that sha256 before it
  installs it. The server and key are saved in `~/.ssh/fleet_rustdesk.json`, so a later run can leave them out.
  The download needs the internet.

`prepare` prints the hub key's fingerprint (`SHA256:...`). Each machine's script prints the fingerprint of the
key it installs, and the two must match.

**Receive the records.** In a second window on the hub, leave this running while you set up the machines:

```powershell
python .agent/fleet/usb/fleet_usb.py receive C:\fleet-inbox
```

It prints one line for each record it takes. Stop it with Ctrl+C, or start it with `--count 3` to stop after
three machines, or `--timeout 3600` to stop after an hour.

## 2. On each machine

Sign in as the account the agent will use. On Windows that account must be an administrator, and on macOS and
Linux it must be able to use `sudo`. The machine must reach the hub on port 8771, and the internet.

Each setup also installs git, Python, PowerShell, uv, Claude Code and Codex for that account when they are
missing, from the system packages or the official installers. A tool the account already has is left alone,
and Claude Code and Codex keep themselves updated. The setup doesn't sign in to either one.

Each system has a file to double-click. A window opens, shows what the setup did, and stays open until you
press a key. At the end it sends the machine's record to the hub, and keeps a copy on the drive.

**Windows.** Double-click **Setup Windows.cmd** and accept the administrator prompt. The first run can take 10 to
15 minutes while Windows downloads OpenSSH Server, and the window shows no progress meanwhile. It installs OpenSSH
Server, starts it now and at each boot, and sets sessions to start in Windows PowerShell. It lets port 22 answer
the local subnet only, and installs the hub's key for administrators. It installs RustDesk from the drive.

**macOS.** Double-click **Setup Mac.command**. Terminal opens and asks for your password. If macOS asks whether
Terminal may use files on a removable volume, allow it. If Remote Login is off and the script can't turn it on,
it opens System Settings and stops. Turn on **General > Sharing > Remote Login**, then double-click the file
again. Then click the **(i)** button beside Remote Login and turn on **Allow full disk access for remote
users**. No script can set that. If that switch isn't there, open **Privacy & Security > Full Disk Access**,
click **+**, press **Cmd+Shift+G**, enter `/usr/libexec/sshd-keygen-wrapper`, click **Open**, and turn it on.
The script installs RustDesk in `/Applications` and starts its two background jobs. macOS lets only a person
at the screen grant **Screen Recording** and **Accessibility** to RustDesk, so open **Privacy & Security** at
the Mac's screen and turn both on. Without them, the hub sees a black screen and can't use the mouse.

**Linux (Ubuntu Desktop).** Ubuntu's file manager won't run a file from the drive, so you do two steps once:
copy **Setup Linux.desktop** to the Desktop, then right-click it there and choose **Allow Launching**. Then
double-click it. A terminal opens and asks for your password. The setup installs and starts `openssh-server`,
and installs `curl` if it's missing.
When `ufw` is on, it lets port 22 answer the local subnet only. It also lets the account's services keep
running after the account signs out. It installs RustDesk from the drive when the machine has a desktop, and
skips it when it has none. Unattended access works best in an Xorg (X11) session: stable RustDesk limits it
in a Wayland session (known issue `FLEET-RUSTDESK-WAYLAND`).

If a double-click does nothing, run the script from a terminal instead. On macOS and Linux, run it with plain
`bash`, as the account. The script asks for root itself, so do not put `sudo` in front.

```text
Windows (Terminal (Admin)):  powershell -NoProfile -ExecutionPolicy Bypass -File E:\fleet-usb\setup-windows.ps1
macOS:                       bash /Volumes/<drive>/fleet-usb/setup-unix.sh
Linux:                       bash /media/$USER/<drive>/fleet-usb/setup-unix.sh
```

On macOS and Linux the script also installs the hub's key in `~/.ssh/authorized_keys`, and gives the account
`sudo` without a password in `/etc/sudoers.d/fleet-agent`. Claude Code and Codex go in `~/.local/bin`. On
Linux, links to them are made in `/usr/local/bin`. On macOS, a block in `~/.zshenv` puts them and Homebrew on
the PATH. On Windows, Claude Code goes in `%USERPROFILE%\.local\bin`, which the setup adds to the account's
PATH, and Codex in `%LOCALAPPDATA%\Programs\OpenAI\Codex\bin`.

You can run a script again at any time, and a repeat run changes nothing. Each run sends a new record.

If a step fails, the window says which one, and the record still goes to the hub with that result. When the
send fails (no route to the hub, a firewall, a wrong token), the window says so. Eject the drive before you
unplug it: in Files on Linux, or in Finder on macOS. A drive pulled out without ejecting can lose the copy
of the record the script just wrote. Then take the drive back to the hub machine and use step 3 on the drive.

**A VMware VM on the Mac.** Set the VM's network adapter to **Bridged**, so the hub machine can reach it. Then
connect the drive to the VM (**Virtual Machine > USB & Bluetooth**). Ubuntu Desktop mounts it under
`/media/$USER/`. Take a snapshot before the first run, so that you can repeat the setup from a clean state.

## 3. Back on the hub machine

```powershell
python .agent/fleet/usb/fleet_usb.py import C:\fleet-inbox
```

Use the folder that `receive` filled. A record that a machine kept on the drive reads the same way:
`python .agent/fleet/usb/fleet_usb.py import E:\fleet-usb`.

For each machine, this pins its host key and writes an entry named after the machine in `~/.ssh/fleet_config`,
which `~/.ssh/config` includes. Then it connects to the machine. The run passes when every machine reports
`full access`. After that, `ssh <name>` reaches the machine with no prompt, and the agent can take it from
there.

**RustDesk password.** For a machine that reported a RustDesk ID, `import` also sets its RustDesk password over
SSH. The password is in `~/.ssh/<name>-rustdesk-password.txt` on the hub. The file is made when it is missing,
with a random password, and only you can read it. In RustDesk, connect to the machine's ID (the `import` line
shows it) and enter that password. To choose your own, write 8 to 64 characters (`A-Z a-z 0-9 _ -`) in the
file before you run `import`.

## Undo

**Windows.** Remove the hub's line from `C:\ProgramData\ssh\administrators_authorized_keys`, then run
`Stop-Service sshd; Set-Service sshd -StartupType Disabled`. Remove RustDesk in **Settings > Apps**, and remove
`%USERPROFILE%\.local\bin` from the account's PATH in **Environment Variables**.

**macOS.** Remove the hub's line from `~/.ssh/authorized_keys`, delete `/etc/sudoers.d/fleet-agent`, and turn
off Remote Login. Remove RustDesk with `sudo launchctl bootout system/com.carriez.RustDesk_service`, then delete
`/Library/LaunchDaemons/com.carriez.RustDesk_service.plist`, `/Library/LaunchAgents/com.carriez.RustDesk_server.plist`
and `/Applications/RustDesk.app`. Remove the lines between `# >>> fleet-usb tools >>>` and
`# <<< fleet-usb tools <<<` from `~/.zshenv`, which undoes the PATH entry.

**Linux.** Remove the hub's line from `~/.ssh/authorized_keys`, then delete `/etc/sudoers.d/fleet-agent`. Stop the
SSH service. Remove RustDesk with `sudo apt remove rustdesk` (or `sudo dnf remove rustdesk`), and delete the
links in `/usr/local/bin` that point into `~/.local/bin`.

**Claude Code and Codex.** These stay installed. Each tool's documentation covers its uninstall.

**Hub machine.** Delete the machine's entry from `~/.ssh/fleet_members.json`, its `Host` block from
`~/.ssh/fleet_config`, its line from `~/.ssh/fleet_known_hosts`, and its `~/.ssh/<name>-rustdesk-password.txt`.
To stop taking records, close the port with `Remove-NetFirewallRule -DisplayName 'Fleet USB receive 8771'`.
