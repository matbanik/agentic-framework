# Installer USB drive

This drive installs Ubuntu on a new fleet machine, such as a laptop or a micro PC, that has no operating
system yet. After the install, the fleet SSH drive in [../usb/README.md](../usb/README.md) connects the
machine to the hub.

You are the agent on the hub machine, which runs Windows. Follow this file in order. A line that starts
`STOP FOR HUMAN` is a stop: tell the human what the step needs, and wait until they say it is done.

## Which image

Use **Ubuntu 26.04.1 LTS Desktop, amd64**, on every new Linux member.

- The fleet SSH kit is tested on Ubuntu, and Ubuntu uses the same package system on every machine.
- An LTS release gets updates until 2031.
- Its recent kernel supports new laptop and mini PC hardware without extra drivers.
- The desktop is needed for the sign-ins a human makes at each machine's screen. You can switch it off
  later.

This image runs on Intel and AMD processors only. Check the machine's processor first, and use the arm64
image for an ARM machine. When a newer LTS point release is out, use it in place of 26.04.1.

## 1. Download and check the image

Run this in Git Bash. Git for Windows includes `gpg`. The key's fingerprint is Ubuntu's published CD image
signing key, and a private `GNUPGHOME` keeps it out of the user's own keyring.

```bash
mkdir -p /c/Temp/ubuntu-iso && cd /c/Temp/ubuntu-iso
base=https://releases.ubuntu.com/26.04.1
curl -fsSLO "$base/SHA256SUMS" -fsSLO "$base/SHA256SUMS.gpg"
export GNUPGHOME="$PWD/gnupg" && mkdir -p -m 700 "$GNUPGHOME"
gpg --keyserver hkps://keyserver.ubuntu.com --recv-keys 843938DF228D22F7B3742BC0D94AA3F0EFE21092
gpg --verify SHA256SUMS.gpg SHA256SUMS
curl -fLO "$base/ubuntu-26.04.1-desktop-amd64.iso"
sha256sum -c --ignore-missing SHA256SUMS
```

`gpg` must report `Good signature from "Ubuntu CD Image Automatic Signing Key (2012)"`, and `sha256sum` must
print `OK` for the image. If either fails, delete the image and stop. The download is about 6.5 GB.

## 2. Write the drive

The drive must hold at least 8 GB. Writing it erases everything on it.

**STOP FOR HUMAN: plug-in.** The human plugs in the drive and confirms nothing on it is needed. Use a USB
port on the back of a desktop PC, because a front port or a hub can drop the drive in the middle of the
write.

List the USB drives. Without `-Serial` the script changes nothing.

```powershell
$iso = 'C:\Temp\ubuntu-iso\ubuntu-26.04.1-desktop-amd64.iso'
pwsh -NoProfile -File .agent\fleet\install-usb\write-installer-usb.ps1 -Iso $iso
```

Tell the human the model and size of the drive you'll use, and take its serial number from the list. The
script finds the drive by its serial number, not by disk number, because disk numbers change when drives are
plugged in or out.

**STOP FOR HUMAN: UAC.** The write needs an administrator. The agent's shell isn't elevated, so start the
script in an elevated window, and the human accepts the UAC prompt.

```powershell
$script = (Resolve-Path .agent\fleet\install-usb\write-installer-usb.ps1).Path
$serial = '<serial from the list>'
Start-Process pwsh -Verb RunAs -Wait -ArgumentList "-NoProfile -ExecutionPolicy Bypass -File `"$script`" -Iso `"$iso`" -Serial $serial"
Get-Content C:\Temp\ubuntu-iso\write-installer-usb.log | Select-String 'Target|RESULT'
```

The script works in this order:

1. It checks the image against `SHA256SUMS`.
2. It erases the drive and writes the image byte for byte. It writes the partition table last, so Windows
   can't mount the drive halfway through.
3. It reads the drive back and compares it with the image's checksum.

It stops before changing anything if it can't find exactly one USB drive with that serial, or if the image
doesn't match. The window closes when it ends, and the log keeps the result. The last line is `RESULT=OK`
or `RESULT=FAILED <reason>`. The write takes about 3 minutes, and the read-back about 2.

The Ubuntu image is a hybrid image: it already holds a partition table and a UEFI boot partition. That's why a
plain byte-for-byte copy makes the drive bootable, on UEFI and on older BIOS machines, with Secure Boot on.

When it ends, Windows may say it can't read the drive and offer to format it. **Click Cancel.** That's normal
for a Linux installer drive.

If it fails:

- **`A device which does not exist was specified`:** the drive dropped off USB. Plug it into another port,
  and run the same command with `-VerifyOnly` added. That only reads the drive. If the check fails, run the
  full write again.
- **Any other failure:** run the full write again.

The script needs PowerShell 7 (`pwsh`). Windows PowerShell 5.1 can't open a whole disk for writing.

## 3. Install Ubuntu on the machine

**STOP FOR HUMAN: install.** The human does each install at the machine.

1. Plug the drive in, power the machine on, and press its one-time boot menu key. That's usually F12, F11,
   F10, F9, F8, F7 or Esc, depending on the maker. Choose the USB drive. Leave Secure Boot on.
2. In the installer, choose **Install Ubuntu** and an interactive install. Turn on **Install third-party
   software for graphics and Wi-Fi hardware**.
3. Choose **Erase disk and install Ubuntu**, which removes everything on the machine's own disk.
4. Give the computer the name it will have in the fleet. Create the account the agent will use, with a
   password.
5. When the install finishes, remove the drive and restart.

The same drive installs every machine. It doesn't change when it's used, so it needs no rewriting between
machines.

Then connect the machine to the hub with the Linux steps in [../usb/README.md](../usb/README.md).

## After the setup

These are optional, once the machine is reachable over SSH.

- **An always-on machine:** turn off sleep:
  `sudo systemctl mask sleep.target suspend.target hibernate.target hybrid-sleep.target`.
- **A laptop that runs with its lid shut:** set `HandleLidSwitch=ignore` and `HandleLidSwitchExternalPower=ignore`
  in `/etc/systemd/logind.conf`, then restart.
- **No desktop:** `sudo systemctl set-default multi-user.target`, then restart. `graphical.target` brings
  the desktop back.

## Reuse the drive for storage

The drive holds the installer until it's erased. To make it a plain exFAT drive again, run this in an
administrator PowerShell, with `<n>` the disk number that `Get-Disk` shows for the drive:

```powershell
Clear-Disk -Number <n> -RemoveData -RemoveOEM -Confirm:$false
Initialize-Disk -Number <n> -PartitionStyle GPT
New-Partition -DiskNumber <n> -UseMaximumSize -AssignDriveLetter | Format-Volume -FileSystem exFAT -NewFileSystemLabel USB
```
