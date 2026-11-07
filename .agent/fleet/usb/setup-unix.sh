#!/bin/bash
# Sets up a macOS or Linux machine for the hub machine's admin connection: the SSH server with the hub's key for
# the account that runs it, passwordless sudo for that account, then a record of the machine for fleet_usb.py
# import on the hub machine. Run it from the drive with sudo, as the account the agent will use:
#   sudo bash /Volumes/<drive>/fleet-usb/setup-unix.sh         (macOS)
#   sudo bash /media/<user>/<drive>/fleet-usb/setup-unix.sh    (Linux)
# It holds no hosts or credentials, and repeating it changes nothing. It keeps to bash 3.2, which macOS ships.
set -euo pipefail

die() { echo "fleet-usb: $*" >&2; exit 1; }
changed=""
note() { changed="$changed${changed:+ }$1"; }

[ "$(id -u)" -eq 0 ] || die "run it with sudo"
user="${SUDO_USER:-}"
[ -n "$user" ] && [ "$user" != root ] || die "run it with sudo from the account the agent will use, not as root"
user_re='^[A-Za-z_][A-Za-z0-9_.-]*$'
[[ $user =~ $user_re ]] || die "unexpected account name: $user"

usb="$(cd "$(dirname "$0")" && pwd)"
hub_key="$(head -n 1 "$usb/hub.pub" | tr -d '\r')"
key_re='^ssh-ed25519 [A-Za-z0-9+/]+={0,2}( [^ ]+)?$'
[[ $hub_key =~ $key_re ]] || die "hub.pub is not one ed25519 public key"

listening() { (exec 3<>/dev/tcp/127.0.0.1/22) 2>/dev/null; }
# grep -q reads held output, because under pipefail a pipe into it can fail when grep stops early.
has() { grep -q "$@"; }

case "$(uname -s)" in
Linux)
    os=linux
    home="$(getent passwd "$user" | cut -d: -f6)"
    if ! command -v sshd >/dev/null 2>&1 && [ ! -x /usr/sbin/sshd ]; then
        if command -v apt-get >/dev/null 2>&1; then
            DEBIAN_FRONTEND=noninteractive apt-get update -qq
            DEBIAN_FRONTEND=noninteractive apt-get install -y -qq openssh-server >/dev/null
        elif command -v dnf >/dev/null 2>&1; then
            dnf install -y -q openssh-server
        else
            die "install openssh-server, then run this again"
        fi
        note openssh-server
    fi
    if ! listening; then
        if systemctl cat ssh.service >/dev/null 2>&1; then svc=ssh; else svc=sshd; fi
        systemctl enable --now "$svc" >/dev/null
        note sshd-started
        sleep 1
    fi
    # Port 22 answers the local subnet only, when ufw is on.
    if command -v ufw >/dev/null 2>&1 && has '^Status: active' <<< "$(ufw status)"; then
        for cidr in $(ip -o -4 addr show scope global | awk '{print $4}'); do
            net="$(python3 -c 'import ipaddress, sys; print(ipaddress.ip_interface(sys.argv[1]).network)' "$cidr")"
            if ! has -E "^22/tcp +ALLOW +$net\$" <<< "$(ufw status)"; then
                ufw allow from "$net" to any port 22 proto tcp >/dev/null
                note "ufw-$net"
            fi
        done
    fi
    # The member keeps running after the account signs out.
    if ! has '=yes' <<< "$(loginctl show-user "$user" -p Linger 2>/dev/null || true)"; then
        loginctl enable-linger "$user"
        note linger
    fi
    addresses="$(ip -o -4 addr show scope global | awk '{split($4, a, "/"); print a[1]}')"
    name="$(hostname -s)"
    ;;
Darwin)
    os=macos
    home="$(dscl . -read "/Users/$user" NFSHomeDirectory | awk '{print $2}')"
    if ! listening; then
        systemsetup -setremotelogin on >/dev/null 2>&1 || true
        sleep 2
        if ! listening; then
            sudo -u "$user" open "x-apple.systempreferences:com.apple.Sharing-Settings.extension" || true
            die "STOP FOR HUMAN: turn on Remote Login in System Settings > General > Sharing, then run this again"
        fi
        note remote-login
    fi
    addresses="$(ifconfig | awk '$1 == "inet" && $2 !~ /^(127|169\.254)\./ {print $2}')"
    name="$(scutil --get LocalHostName)"
    ;;
*)
    die "this script covers macOS and Linux only"
    ;;
esac

# The hub's key, in the account's own authorized_keys.
group="$(id -gn "$user")"
install -d -m 700 -o "$user" -g "$group" "$home/.ssh"
keys="$home/.ssh/authorized_keys"
body="$(echo "$hub_key" | awk '{print $2}')"
if ! { [ -f "$keys" ] && has -xF "$body" <<< "$(awk '{print $2}' "$keys")"; }; then
    if [ -s "$keys" ] && [ -n "$(tail -c 1 "$keys")" ]; then echo >> "$keys"; fi
    printf '%s\n' "$hub_key" >> "$keys"
    note hub-key
fi
chown "$user:$group" "$keys"
chmod 600 "$keys"

# Full access: sudo without a password, for this account only. visudo checks the line before it is installed.
sudoers=/etc/sudoers.d/fleet-agent
line="$user ALL=(ALL) NOPASSWD: ALL"
if [ ! -f "$sudoers" ] || ! grep -qxF "$line" "$sudoers"; then
    tmp="$(mktemp)"
    printf '%s\n' "$line" > "$tmp"
    visudo -cf "$tmp" >/dev/null || { rm -f "$tmp"; die "the sudoers line failed visudo's check"; }
    install -d -m 755 /etc/sudoers.d
    install -m 440 -o root -g "$(id -gn root)" "$tmp" "$sudoers"
    rm -f "$tmp"
    note sudoers
fi

# The record for the hub machine: the name, the account, the addresses and the host key to pin.
host_key_file=/etc/ssh/ssh_host_ed25519_key.pub
[ -f "$host_key_file" ] || ssh-keygen -A >/dev/null
host_key="$(awk '{print $1 " " $2}' "$host_key_file")"
name="$(echo "$name" | tr '[:upper:]' '[:lower:]' | tr -c 'a-z0-9\n-' '-')"

json_list() { local out=""; for item in $1; do out="$out${out:+, }\"$item\""; done; echo "[$out]"; }
mkdir -p "$usb/members"
out="$usb/members/$name.json"
cat > "$out" <<EOF
{
  "v": 1,
  "name": "$name",
  "os": "$os",
  "user": "$user",
  "port": 22,
  "addresses": $(json_list "$addresses"),
  "host_key": "$host_key",
  "changed": $(json_list "$changed"),
  "created": "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
}
EOF

echo "Hub key installed: $(ssh-keygen -lf "$usb/hub.pub")"
echo "Changed: ${changed:-nothing}"
if [ "$os" = macos ]; then
    echo "On this Mac, also turn on 'Allow full disk access for remote users' under Remote Login's (i) button."
fi
echo "Wrote $out. Take the drive back to the hub machine and run the import there."
