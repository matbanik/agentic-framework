#!/bin/bash
# Sets up a macOS or Linux machine for the hub machine's admin connection: the SSH server with the hub's key for
# the account that runs it, passwordless sudo for that account, and the tools that the hub's agent needs: git and
# Python from the system packages (on macOS from Homebrew), PowerShell, uv, Claude Code and Codex, with links so
# that a plain login finds them. It writes a
# record of the machine to members/<name>.json on the drive for fleet_usb.py import on the hub machine: once the
# name is known, again after each step, and a final time on every exit that bash can catch. Run it from the
# drive with bash, as the account the agent will use; it asks for root itself:
#   bash /Volumes/<drive>/fleet-usb/setup-unix.sh         (macOS)
#   bash /media/<user>/<drive>/fleet-usb/setup-unix.sh    (Linux)
# Started without root, it makes a run id and runs itself again as root through the first elevator that works:
# sudo, sudo-rs, sudo.ws, then pkexec. The next elevator is tried only when the one before is missing or exits
# 126 or 127. Afterwards it reads the record: a final record with its run id is the elevated run's own, and a
# record that is not final is finished here, with the elevate step failed and every other step skipped.
# Options, which the parent passes to the elevated run: --for-user <account> and --run-id <id>.
# After the final write it sends the record to the hub: hub.txt on the drive holds the hub's url lines and the
# token line, and curl posts the record to each url in turn until one answers 200. The drive copy's delivery is
# pending while the send runs, then sent or failed; the exit code comes from ok only, never from the send.
# Each step ends ok, failed or skipped, and a failed step does not stop the steps after it. The script holds no
# hosts or credentials, and repeating it changes nothing. It keeps to bash 3.2, which macOS ships.
# FLEET_ROOT, empty on a member, is put in front of every system path; the tests set it to a temp folder.
# FLEET_TOOL_PATH, empty on a member, replaces the folders in which the elevators and visudo are looked for.
set -euo pipefail

# The Step list of the plan, in order. A step that does not apply to this system ends skipped.
RUN_STEPS="elevate account packages ssh_server firewall hub_key admin_rights linger homebrew pwsh uv claude codex tool_links rustdesk host_key"
user_re='^[A-Za-z_][A-Za-z0-9_.-]*$'
record_user_re='^[A-Za-z0-9_][A-Za-z0-9_. -]{0,63}$'
key_re='^ssh-ed25519 [A-Za-z0-9+/]+={0,2}( [^ ]+)?$'
ipv4_re='^([0-9]{1,3}\.){3}[0-9]{1,3}$'
# The token and url lines of hub.txt, as fleet_usb.py prepare writes them.
token_re='^[A-Za-z0-9_-]{32,64}$'
hub_url_re='^https?://[A-Za-z0-9.-]+(:[0-9]{1,5})?$'
# The lines of rustdesk.txt, as fleet_usb.py prepare writes them, and the id that RustDesk prints.
rd_version_re='^[0-9]+\.[0-9]+\.[0-9]+$'
rd_host_re='^[A-Za-z0-9][A-Za-z0-9._-]{0,252}(:[0-9]{1,5})?$'
rd_key_re='^[A-Za-z0-9+/=]{40,64}$'
rd_file_re='^([A-Za-z0-9._-]+) ([0-9a-f]{64})$'
rd_id_re='^[0-9]{6,12}$'
rd_found_version_re='([0-9]+\.[0-9]+\.[0-9]+)'
rd_service_label=com.carriez.RustDesk_service
rd_server_label=com.carriez.RustDesk_server

step_ids=(); step_status=(); step_detail=()
tool_ids=(); tool_vers=()
current_step=""; interrupted=0; main_failed=0; main_done=0; finalized=0
run_id=""; name=""; os=""; user="unknown"; home=""; group=""
for_user=""; account=""; script=""; parent=0
port=""; host_key=""; addresses=""
gui=false; session_type=unknown; rustdesk_id=""
delivery_status=""; delivery_detail=""
hub_urls=""; hub_token=""; hub_curl=""
usb=""; state=""
J=""; REC=""

say() { printf 'fleet-usb: %s\n' "$*" >&2; }

# ----------------------------------------------------------------------------------------------- the record

# J becomes $1 as a JSON string: \ and " escaped, \n \r \t as escapes, other control characters as \u00XX.
json_str() {
    local s=$1 LC_ALL=C out='' c i n code hex
    n=${#s}
    for ((i = 0; i < n; i++)); do
        c=${s:i:1}
        case $c in
            \") out+='\"' ;;
            \\) out+='\\' ;;
            $'\n') out+='\n' ;;
            $'\r') out+='\r' ;;
            $'\t') out+='\t' ;;
            [\ -\~]) out+=$c ;;
            *)
                printf -v code '%d' "'$c"
                if [ "$code" -ge 0 ] && [ "$code" -lt 32 ]; then
                    printf -v hex '\\u%04x' "$code"
                    out+=$hex
                else
                    out+=$c
                fi
                ;;
        esac
    done
    J="\"$out\""
}

# J becomes $1 cut to at most 300 bytes, without a cut UTF-8 sequence at its end: the last lead byte within the
# final four bytes goes, with the continuation bytes after it, when fewer bytes follow it than its sequence needs.
cut_detail() {
    local s=$1 LC_ALL=C code k need n
    if [ ${#s} -gt 300 ]; then
        s=${s:0:300}
        n=${#s}
        for k in 1 2 3 4; do
            printf -v code '%d' "'${s: -k:1}"
            if [ "$code" -lt 128 ]; then break; fi
            if [ "$code" -ge 192 ]; then
                if [ "$code" -ge 240 ]; then need=4; elif [ "$code" -ge 224 ]; then need=3; else need=2; fi
                if [ "$k" -lt "$need" ]; then s=${s:0:n-k}; fi
                break
            fi
        done
    fi
    J=$s
}

add_step() {
    cut_detail "${3:-}"
    step_ids+=("$1")
    step_status+=("$2")
    step_detail+=("$J")
}

status_of() {
    local i
    for ((i = 0; i < ${#step_ids[@]}; i++)); do
        if [ "${step_ids[i]}" = "$1" ]; then printf '%s' "${step_status[i]}"; return 0; fi
    done
    printf 'none'
}

any_failed() {
    local i
    for ((i = 0; i < ${#step_status[@]}; i++)); do
        [ "${step_status[i]}" != failed ] || return 0
    done
    return 1
}

# ok is true only when the run ended, no step failed and no error stopped the script.
record_ok() { [ "$1" = true ] && [ "$main_failed" = 0 ] && ! any_failed; }

# REC becomes the record as JSON text, with the delivery that delivery_status and delivery_detail hold. $1: final.
build_record() {
    local final=$1 ok=false buf i sep a
    if record_ok "$final"; then ok=true; fi
    buf=$'{\n  "v": 2,\n'
    json_str "$run_id"; buf+="  \"run_id\": $J,"$'\n'
    buf+="  \"final\": $final,"$'\n'
    json_str "$name"; buf+="  \"name\": $J,"$'\n'
    json_str "$os"; buf+="  \"os\": $J,"$'\n'
    json_str "$user"; buf+="  \"user\": $J,"$'\n'
    buf+="  \"ok\": $ok,"$'\n'
    buf+='  "steps": ['
    sep=''
    for ((i = 0; i < ${#step_ids[@]}; i++)); do
        json_str "${step_detail[i]}"
        buf+="$sep"$'\n'"    {\"step\": \"${step_ids[i]}\", \"status\": \"${step_status[i]}\", \"detail\": $J}"
        sep=','
    done
    buf+=$'\n  ],\n  "tools": {'
    sep=''
    for ((i = 0; i < ${#tool_ids[@]}; i++)); do
        json_str "${tool_vers[i]}"
        buf+="$sep\"${tool_ids[i]}\": $J"
        sep=', '
    done
    buf+=$'},\n'
    buf+="  \"gui\": $gui,"$'\n'
    json_str "$session_type"; buf+="  \"session_type\": $J,"$'\n'
    if [ -n "$rustdesk_id" ]; then json_str "$rustdesk_id"; else J=null; fi
    buf+="  \"rustdesk_id\": $J,"$'\n'
    buf+="  \"port\": ${port:-null},"$'\n'
    if [ -n "$host_key" ]; then json_str "$host_key"; else J=null; fi
    buf+="  \"host_key\": $J,"$'\n'
    buf+='  "addresses": ['
    sep=''
    while IFS= read -r a; do
        if [[ $a =~ $ipv4_re ]]; then buf+="$sep\"$a\""; sep=', '; fi
    done <<< "$addresses"
    buf+=$'],\n'
    if [ -n "$delivery_status" ]; then
        json_str "$delivery_detail"
        buf+="  \"delivery\": {\"status\": \"$delivery_status\", \"detail\": $J}"$'\n'
    else
        buf+=$'  "delivery": null\n'
    fi
    buf+='}'
    REC=$buf
}

# Writes members/<name>.json through a temp file and a rename in the same folder, then sync. $1: final.
write_record() {
    local dir out tmp
    build_record "$1"
    dir="$usb/members"
    [ -d "$dir" ] || mkdir -p "$dir"
    out="$dir/$name.json"
    tmp="$dir/.$name.json.tmp"
    printf '%s\n' "$REC" > "$tmp"
    mv -f "$tmp" "$out"
    # The system writes to a USB drive in the background; a drive pulled before that write loses the record.
    sync
}

checkpoint() { write_record false; }

# ----------------------------------------------------------------------------------------------- steps

# Inside a step (a subshell): note sets the ok detail, skip and fail end the step, run records a failed command.
note() { printf '%s' "$*" > "$state/ok"; }
skip() { printf '%s' "$*" > "$state/skip"; exit 0; }
fail() { say "$*"; printf '%s' "$*" > "$state/fail"; exit 1; }
run() {
    local rc=0
    "$@" || rc=$?
    if [ "$rc" -ne 0 ]; then printf '%s exited %s' "$1" "$rc" > "$state/run"; fi
    return "$rc"
}
# A step hands a value to the steps after it through the state folder.
set_var() { printf '%s' "$2" > "$state/var.$1"; }
load_vars() {
    local v
    for v in user home group port host_key addresses gui session_type rustdesk_id; do
        if [ -f "$state/var.$v" ]; then IFS= read -r -d '' "$v" < "$state/var.$v" || true; fi
    done
}
read_file() { J=""; if [ -s "$1" ]; then IFS= read -r -d '' J < "$1" || true; fi; }

# The steps that $1 needs, or nothing: a step ends skipped when one of them did not end ok. The Step list of the
# plan gives hub_key, admin_rights and host_key the SSH server; the account steps also need the Account, because
# they write into its home folder.
need_of() {
    case $1 in
        hub_key|admin_rights) printf 'account ssh_server' ;;
        host_key) printf 'ssh_server' ;;
        pwsh) if [ "$os" = macos ]; then printf 'account homebrew'; else printf 'account'; fi ;;
        linger|homebrew|uv|claude|codex|tool_links|rustdesk) printf 'account' ;;
    esac
}

run_step() {
    local id=$1 need rc st detail
    for need in $(need_of "$id"); do
        if [ "$(status_of "$need")" != ok ]; then
            add_step "$id" skipped "needs $need"
            checkpoint
            say "$id: skipped, needs $need"
            return 0
        fi
    done
    : > "$state/ok"; : > "$state/skip"; : > "$state/fail"; : > "$state/run"
    current_step=$id
    say "$id..."
    set +e
    ( set -e; "step_$id" )
    rc=$?
    set -e
    load_vars
    if [ "$rc" -eq 0 ] && [ -s "$state/skip" ]; then
        st=skipped; read_file "$state/skip"
    elif [ "$rc" -eq 0 ]; then
        st=ok; read_file "$state/ok"
    else
        st=failed; read_file "$state/fail"
        [ -n "$J" ] || read_file "$state/run"
        [ -n "$J" ] || J="exit $rc"
    fi
    detail=$J
    add_step "$id" "$st" "$detail"
    current_step=""
    checkpoint
    say "$id: $st${detail:+, $detail}"
}

listening() { (exec 3<>/dev/tcp/127.0.0.1/22) 2>/dev/null; }
# grep -q reads held output, because under pipefail a pipe into it can fail when grep stops early.
has() { grep -q "$@"; }

# The path of command $1, looked for in FLEET_TOOL_PATH; when that is empty, in PATH, /usr/bin and /usr/sbin.
# A dangling link is not a command.
find_tool() {
    local dirs d IFS=:
    if [ -n "${FLEET_TOOL_PATH:-}" ]; then dirs=$FLEET_TOOL_PATH; else dirs="$PATH:${FLEET_ROOT:-}/usr/bin:${FLEET_ROOT:-}/usr/sbin"; fi
    for d in $dirs; do
        [ -n "$d" ] || continue
        if [ -f "$d/$1" ] && [ -x "$d/$1" ]; then printf '%s' "$d/$1"; return 0; fi
    done
    return 1
}

# The name of the account with user id $1, or nothing.
account_of_uid() {
    case $os in
        linux) getent passwd "$1" 2>/dev/null | cut -d: -f1 || true ;;
        macos) dscl . -search /Users UniqueID "$1" 2>/dev/null | awk 'NR == 1 {print $1}' || true ;;
    esac
}

# The Account: --for-user, then SUDO_USER, then the name of PKEXEC_UID (pkexec sets neither of the others), then,
# when the script started without root, the user that started it.
resolve_account() {
    local a=$for_user
    [ -n "$a" ] || a=${SUDO_USER:-}
    if [ -z "$a" ] && [[ ${PKEXEC_UID:-} =~ ^[0-9]+$ ]]; then a=$(account_of_uid "$PKEXEC_UID"); fi
    if [ -z "$a" ] && [ "$(id -u)" -ne 0 ]; then a=$(id -un 2>/dev/null || true); fi
    account=$a
}

# Runs a command as the Account in the Account's own environment, and nothing of the caller's: root's HOME, PATH
# and variables must not reach an installer that writes into the Account's home.
account_run() {
    local path="$home/.local/bin:$home/.cargo/bin:" brew
    case $os in
        linux)
            path+="/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
            runuser -u "$user" -- env -i "HOME=$home" "USER=$user" "LOGNAME=$user" "PATH=$path" "$@"
            ;;
        macos)
            if [ "$(uname -m)" = arm64 ]; then brew=/opt/homebrew; else brew=/usr/local; fi
            path+="$brew/bin:$brew/sbin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
            sudo -u "$user" -H env -i "HOME=$home" "USER=$user" "LOGNAME=$user" "PATH=$path" "$@"
            ;;
    esac
}

step_elevate() {
    [ "$(id -u)" -eq 0 ] || fail "not running as root"
}

step_account() {
    local a=$account h g
    [ -n "$a" ] || fail "no account: run it with bash from the account the agent will use"
    [ "$a" != root ] || fail "the account is root: run it with bash from the account the agent will use"
    [[ $a =~ $user_re ]] || fail "unexpected account name: $a"
    case $os in
        linux) h=$(getent passwd "$a" | cut -d: -f6) ;;
        macos) h=$(dscl . -read "/Users/$a" NFSHomeDirectory | awk '{print $2}') ;;
    esac
    [ -n "$h" ] || fail "no home folder for $a"
    g=$(id -gn "$a")
    set_var user "$a"
    set_var home "${FLEET_ROOT:-}$h"
    set_var group "$g"
    note "$a"
}

# apt waits up to 10 minutes for its lock, which Ubuntu's updater holds while it installs updates.
step_packages() {
    [ "$os" = linux ] || skip "not on $os"
    # git and python3 come with the system packages: the hub's agent needs both on every member.
    if find_tool apt-get >/dev/null; then
        export DEBIAN_FRONTEND=noninteractive
        run apt-get -o DPkg::Lock::Timeout=600 update -qq || say "apt-get update failed; installing from the cache"
        run apt-get -o DPkg::Lock::Timeout=600 install -y -qq openssh-server curl git python3 python3-venv ca-certificates >/dev/null
        note "apt-get: openssh-server curl git python3 python3-venv ca-certificates"
    elif find_tool dnf >/dev/null; then
        run dnf install -y -q openssh-server curl git python3 ca-certificates
        note "dnf: openssh-server curl git python3 ca-certificates"
    else
        fail "no apt-get or dnf: install openssh-server and curl, then run this again"
    fi
}

step_ssh_server() {
    local svc
    if listening; then note "already listening on port 22"; return 0; fi
    case $os in
        linux)
            if systemctl cat ssh.service >/dev/null 2>&1; then svc=ssh; else svc=sshd; fi
            run systemctl enable --now "$svc" >/dev/null
            sleep 1
            note "$svc enabled and started"
            ;;
        macos)
            systemsetup -setremotelogin on >/dev/null 2>&1 || true
            sleep 2
            if ! listening; then
                sudo -u "$user" open "x-apple.systempreferences:com.apple.Sharing-Settings.extension" || true
                fail "turn on Remote Login in System Settings > General > Sharing, then run this again"
            fi
            note "Remote Login turned on"
            ;;
    esac
}

# Port 22 answers the local subnets only, when ufw is on.
step_firewall() {
    local net added=""
    [ "$os" = linux ] || skip "not on $os"
    if ! command -v ufw >/dev/null 2>&1 || ! has '^Status: active' <<< "$(ufw status)"; then
        note "ufw is not active"
        return 0
    fi
    for net in $(ip -o -4 route show scope link | awk '{print $1}'); do
        if ! has -E "^22/tcp +ALLOW +$net\$" <<< "$(ufw status)"; then
            run ufw allow from "$net" to any port 22 proto tcp >/dev/null
            added="$added${added:+ }$net"
        fi
    done
    note "ufw allows port 22 from the local subnets${added:+ (added $added)}"
}

# The hub's key, in the account's own authorized_keys.
step_hub_key() {
    local hub keys body
    [ -f "$usb/hub.pub" ] || fail "no hub.pub on the drive: run fleet_usb.py prepare on the hub"
    hub="$(head -n 1 "$usb/hub.pub" | tr -d '\r')"
    [[ $hub =~ $key_re ]] || fail "hub.pub is not one ed25519 public key"
    run install -d -m 700 -o "$user" -g "$group" "$home/.ssh"
    keys="$home/.ssh/authorized_keys"
    body="$(echo "$hub" | awk '{print $2}')"
    if [ -f "$keys" ] && has -xF "$body" <<< "$(awk '{print $2}' "$keys")"; then
        note "already there"
    else
        if [ -s "$keys" ] && [ -n "$(tail -c 1 "$keys")" ]; then echo >> "$keys"; fi
        printf '%s\n' "$hub" >> "$keys"
        note "added"
    fi
    run chown "$user:$group" "$keys"
    chmod 600 "$keys"
}

# Full access: sudo without a password, for this account only. visudo checks the line before it is installed.
step_admin_rights() {
    local sudoers="${FLEET_ROOT:-}/etc/sudoers.d/fleet-agent" line tmp rc=0 visudo
    line="$user ALL=(ALL) NOPASSWD: ALL"
    if [ -f "$sudoers" ] && grep -qxF "$line" "$sudoers"; then note "already there"; return 0; fi
    # Ubuntu with sudo-rs names the check visudo.ws, beside the sudo.ws of the old sudo.
    visudo=$(find_tool visudo) || visudo=$(find_tool visudo.ws) || fail "no visudo or visudo.ws to check the sudoers line"
    tmp="$(mktemp)"
    printf '%s\n' "$line" > "$tmp"
    if ! "$visudo" -cf "$tmp" >/dev/null; then rm -f "$tmp"; fail "the sudoers line failed visudo's check"; fi
    run install -d -m 755 "${FLEET_ROOT:-}/etc/sudoers.d" \
        && run install -m 440 -o root -g "$(id -gn root)" "$tmp" "$sudoers" || rc=$?
    rm -f "$tmp"
    [ "$rc" -eq 0 ] || return "$rc"
    note "added"
}

# The member keeps running after the account signs out.
step_linger() {
    [ "$os" = linux ] || skip "not on $os"
    if has '=yes' <<< "$(loginctl show-user "$user" -p Linger 2>/dev/null || true)"; then
        note "already on"
        return 0
    fi
    run loginctl enable-linger "$user"
    note "turned on"
}

# The tools of the hub's agent that the system packages do not bring. git and Python come from step packages (on
# macOS from Homebrew). uv, Claude Code and Codex come from their official installers: each goes into the
# account's home and keeps itself updated, so it installs as the account (Claude's installer refuses sudo). A tool
# that the account's login shell already finds is left alone. Neither Claude nor Codex is signed in here.
has_cli() { [ -x "$home/.local/bin/$1" ] || account_run bash -c 'command -v "$1"' _ "$1" >/dev/null 2>&1; }
install_cli() {
    if has_cli "$1"; then note "already installed"; return 0; fi
    say "Installing $1..."
    account_run CODEX_NON_INTERACTIVE=1 bash -c 'set -o pipefail; cd ~ && curl -fsSL "$1" | "$2"' _ "$2" "$3" \
        || fail "the $1 installer failed; check the network, then run this again"
    [ -x "$home/.local/bin/$1" ] || fail "the $1 installer left no ~/.local/bin/$1"
    note "installed"
}
step_uv() { install_cli uv https://astral.sh/uv/install.sh sh; }
step_claude() { install_cli claude https://claude.ai/install.sh bash; }
step_codex() { install_cli codex https://chatgpt.com/codex/install.sh sh; }

# Links $2 at $1. A link that already leads to $2 stays as it is. A link that points nowhere is replaced. Any other
# file or link at $1 is not ours: it is left alone and the function returns 1.
link_tool() {
    local link=$1 target=$2
    mkdir -p "$(dirname "$link")"
    if [ -L "$link" ] && [ ! -e "$link" ]; then rm -f "$link"; fi
    if [ -e "$link" ] || [ -L "$link" ]; then
        [ "$link" -ef "$target" ]
        return
    fi
    ln -s "$target" "$link"
}

# macOS: Homebrew's installer refuses root, so it runs as the account, which is an administrator on macOS. Then
# git, Python and uv come from Homebrew. The next step gets PowerShell from it.
step_homebrew() {
    [ "$os" = macos ] || skip "not on $os"
    local detail="already installed"
    if ! account_run bash -c 'command -v brew' >/dev/null 2>&1; then
        say "Installing Homebrew..."
        account_run NONINTERACTIVE=1 bash -c 'set -o pipefail; cd ~ && f=$(mktemp) && trap "rm -f \"$f\"" EXIT && curl -fsSL "$1" -o "$f" && /bin/bash "$f"' \
            _ https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh \
            || fail "the Homebrew installer failed; check the network and that $user is an administrator, then run this again"
        account_run bash -c 'command -v brew' >/dev/null 2>&1 || fail "the Homebrew installer left no brew"
        detail="installed"
    fi
    account_run HOMEBREW_NO_AUTO_UPDATE=1 HOMEBREW_NO_INSTALL_UPGRADE=1 brew install git python uv >/dev/null \
        || fail "brew install git python uv failed"
    note "$detail; git python uv"
}

# Linux: snap when the system has it, else the tarball of the latest release, put in /opt/microsoft/powershell/7
# and linked at /usr/local/bin/pwsh. The snap link is made too, because /snap/bin is not on the PATH of an ssh command.
pwsh_linux() {
    local snap_pwsh="${FLEET_ROOT:-}/snap/bin/pwsh" link="${FLEET_ROOT:-}/usr/local/bin/pwsh"
    local arch ver url dir tmp
    if [ -x "$snap_pwsh" ]; then
        # An earlier run or the human installed the snap: the link is still needed for an ssh command.
        link_tool "$link" "$snap_pwsh" || [ -x "$link" ] || fail "$link exists and is not a link to pwsh; left alone"
        note "already installed"
        return 0
    fi
    if has_cli pwsh; then note "already installed"; return 0; fi
    if find_tool snap >/dev/null; then
        say "Installing PowerShell with snap..."
        if run snap install powershell --classic && [ -x "$snap_pwsh" ]; then
            link_tool "$link" "$snap_pwsh" || fail "$link exists and is not a link to pwsh; left alone"
            note "snap"
            return 0
        fi
        say "snap could not install PowerShell; downloading it instead"
    fi
    case "$(uname -m)" in
        x86_64|amd64) arch=x64 ;;
        aarch64|arm64) arch=arm64 ;;
        *) fail "no PowerShell download for $(uname -m)" ;;
    esac
    say "Installing PowerShell from its release..."
    ver=$(curl -fsSL -o /dev/null -w '%{url_effective}' https://github.com/PowerShell/PowerShell/releases/latest) \
        || fail "could not read the latest PowerShell release; check the network, then run this again"
    ver=${ver##*/v}
    [[ $ver =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || fail "the latest PowerShell release has no usable version"
    url="https://github.com/PowerShell/PowerShell/releases/download/v$ver/powershell-$ver-linux-$arch.tar.gz"
    tmp=$(mktemp)
    if ! curl -fsSL -o "$tmp" "$url"; then rm -f "$tmp"; fail "the PowerShell download failed: $url"; fi
    dir="${FLEET_ROOT:-}/opt/microsoft/powershell/7"
    mkdir -p "$dir"
    if ! tar -xzf "$tmp" --no-same-owner -C "$dir"; then rm -f "$tmp"; fail "the PowerShell archive did not unpack"; fi
    rm -f "$tmp"
    chmod +x "$dir/pwsh"
    link_tool "$link" "$dir/pwsh" || fail "$link exists and is not a link to pwsh; left alone"
    account_run pwsh --version >/dev/null 2>&1 \
        || fail "pwsh is in $dir but does not start; on some systems it needs libicu: install it, then run this again"
    note "release $ver"
}

step_pwsh() {
    case $os in
        macos)
            if has_cli pwsh; then note "already installed"; return 0; fi
            say "Installing PowerShell..."
            account_run HOMEBREW_NO_AUTO_UPDATE=1 HOMEBREW_NO_INSTALL_UPGRADE=1 brew install powershell >/dev/null \
                || fail "brew install powershell failed"
            has_cli pwsh || fail "brew install powershell left no pwsh"
            note "installed with Homebrew"
            ;;
        linux) pwsh_linux ;;
    esac
}

# Links that a login without the account's own profile finds: an ssh command from the hub reads no profile.
# Linux: /usr/local/bin has links to the tools in the account's ~/.local/bin. macOS: a block in the account's
# ~/.zshenv, which zsh reads for every shell, puts those folders and Homebrew's on PATH.
tool_links_linux() {
    local dir="${FLEET_ROOT:-}/usr/local/bin" t made="" left=""
    for t in claude codex uv uvx; do
        [ -x "$home/.local/bin/$t" ] || continue
        if link_tool "$dir/$t" "$home/.local/bin/$t"; then made+=" $t"; else left+=" /usr/local/bin/$t"; fi
    done
    if [ -z "$made$left" ]; then note "no tools to link"; return 0; fi
    note "linked:${made:- none}${left:+; left alone, another file is there:$left}"
}

zshenv_block() {
    local brew=/usr/local r="${FLEET_ROOT:-}"
    [ "$(uname -m)" != arm64 ] || brew=/opt/homebrew
    printf '%s\n' "$zshenv_begin" \
        '# The folders of the hub agent'"'"'s tools, in front of PATH for every zsh, so that an ssh command finds them.' \
        "for fleet_dir in \"\$HOME/.local/bin\" \"$r$brew/bin\" \"$r$brew/sbin\" \"$r/usr/local/bin\"; do" \
        '    case ":$PATH:" in' \
        '        *":$fleet_dir:"*) ;;' \
        '        *) if [ -d "$fleet_dir" ]; then PATH="$fleet_dir:$PATH"; fi ;;' \
        '    esac' \
        'done' \
        'unset fleet_dir' \
        'export PATH' \
        "$zshenv_end"
}

tool_links_macos() {
    local brew=/usr/local login file t have=""
    [ "$(uname -m)" != arm64 ] || brew=/opt/homebrew
    for t in claude codex uv uvx; do [ -x "$home/.local/bin/$t" ] && have=1; done
    [ -x "${FLEET_ROOT:-}$brew/bin/brew" ] && have=1
    if [ -z "$have" ]; then note "no tools to link"; return 0; fi
    login=$(dscl . -read "/Users/$user" UserShell 2>/dev/null | awk '{print $2}' || true)
    case $login in
        */zsh) ;;
        *) fail "the login shell of $user is ${login:-unknown}, not zsh: no ~/.zshenv block" ;;
    esac
    file="$home/.zshenv"
    if [ -f "$file" ] && grep -qF "$zshenv_begin" "$file"; then note "~/.zshenv already has the block"; return 0; fi
    if [ -s "$file" ] && [ -n "$(tail -c 1 "$file")" ]; then printf '\n' >> "$file"; fi
    zshenv_block >> "$file"
    run chown "$user:$group" "$file"
    note "~/.zshenv has the block"
}

zshenv_begin='# >>> fleet-usb tools >>>'
zshenv_end='# <<< fleet-usb tools <<<'

step_tool_links() {
    case $os in
        linux) tool_links_linux ;;
        macos) tool_links_macos ;;
    esac
}

# The first output line of "<tool> --version" as the account runs it, for a tool the account finds, else no key.
tool_version() {
    local key=$1 c v
    shift
    for c in "$@"; do
        v=$(account_run "$c" --version 2>/dev/null || true)
        v=${v%%$'\n'*}
        v=${v%$'\r'}
        v=${v:0:200}
        if [ -n "$v" ]; then tool_ids+=("$key"); tool_vers+=("$v"); return 0; fi
    done
}
collect_tools() {
    [ -n "$home" ] || return 0
    tool_version git git
    tool_version python python3 python
    tool_version pwsh pwsh "${FLEET_ROOT:-}/snap/bin/pwsh"
    tool_version uv uv
    tool_version claude claude
    tool_version codex codex
    tool_version rustdesk rustdesk "${FLEET_ROOT:-}/Applications/RustDesk.app/Contents/MacOS/RustDesk"
}

# ----------------------------------------------------------------------------------------------- RustDesk

# RustDesk on a member that has a screen: the program, the hub's ID server and key, and the id that the hub shows in
# its list. The drive holds what prepare put there: rustdesk.txt (the version, the host, the key, and a sha256 for
# each file) and the files in rustdesk/. rustdesk.txt is read as data, line by line; nothing in it is run.
rd_bin=""; rd_version=""; rd_host=""; rd_key=""; rd_files=""; rd_label=""; rd_kind=""; rd_asset=""; rd_sum=""
rd_grants="grant Screen Recording and Accessibility at the screen"

# A Mac has a screen. A Linux system has one when its default target is graphical or its display manager runs.
rd_has_desktop() {
    local target active
    case $os in
        macos) return 0 ;;
        linux)
            target=$(systemctl get-default 2>/dev/null || true)
            active=$(systemctl is-active display-manager.service 2>/dev/null || true)
            [ "$target" = graphical.target ] || [ "$active" = active ]
            ;;
        *) return 1 ;;
    esac
}

# The type of the newest session of the Account (x11, wayland or tty), else unknown. The output of loginctl is
# data: only a type that the record accepts is kept.
rd_session_type() {
    local list id best='' kind=unknown found
    if [ "$os" != linux ]; then printf 'unknown'; return 0; fi
    list=$(loginctl show-user "$user" -p Sessions 2>/dev/null || true)
    list=${list#Sessions=}
    for id in $list; do
        if [[ $id =~ ^[0-9]+$ ]] && { [ -z "$best" ] || [ "$id" -gt "$best" ]; }; then best=$id; fi
    done
    if [ -n "$best" ]; then
        found=$(loginctl show-session "$best" -p Type 2>/dev/null || true)
        found=${found#Type=}
        case $found in x11|wayland|tty) kind=$found ;; esac
    fi
    printf '%s' "$kind"
}

# Reads rustdesk.txt as data: the version, the host and the key (the first valid line of each), and every
# "file=<name> <sha256>" line whose name is a plain file name. Any other line is ignored.
rd_read_file() {
    local line v
    rd_version=""; rd_host=""; rd_key=""; rd_files=""
    while IFS= read -r line || [ -n "$line" ]; do
        line=${line%$'\r'}
        case $line in
            version=*) v=${line#version=}; if [ -z "$rd_version" ] && [[ $v =~ $rd_version_re ]]; then rd_version=$v; fi ;;
            host=*) v=${line#host=}; if [ -z "$rd_host" ] && [[ $v =~ $rd_host_re ]]; then rd_host=$v; fi ;;
            key=*) v=${line#key=}; if [ -z "$rd_key" ] && [[ $v =~ $rd_key_re ]]; then rd_key=$v; fi ;;
            file=*)
                v=${line#file=}
                if [[ $v =~ $rd_file_re ]]; then rd_files+="${BASH_REMATCH[1]} ${BASH_REMATCH[2]}"$'\n'; fi
                ;;
        esac
    done < "$usb/rustdesk.txt"
}

# Picks the file for this system from rd_files: sets rd_label (the name of the platform), rd_kind and, when
# rustdesk.txt lists one, rd_asset and rd_sum. Fails when the system has no package manager that RustDesk supports.
rd_pick_asset() {
    local arch re='' name sum
    arch=$(uname -m)
    case $arch in x86_64|amd64) arch=x86_64 ;; aarch64|arm64) arch=aarch64 ;; esac
    rd_asset=""; rd_sum=""
    case $os in
        linux)
            if find_tool apt-get >/dev/null; then rd_kind=deb
            elif find_tool dnf >/dev/null; then rd_kind=rpm
            else fail "no apt-get or dnf: install RustDesk by hand, then run this again"
            fi
            rd_label="linux $arch ($rd_kind)"
            case "$arch $rd_kind" in
                "x86_64 deb") re='^rustdesk-[0-9.]+-x86_64\.deb$' ;;
                "aarch64 deb") re='^rustdesk-[0-9.]+-aarch64\.deb$' ;;
                "x86_64 rpm") re='^rustdesk-[0-9.]+-0\.x86_64\.rpm$' ;;
            esac
            ;;
        macos)
            rd_kind=dmg
            rd_label="macos $arch"
            case $arch in
                x86_64) re='^rustdesk-[0-9.]+-x86_64\.dmg$' ;;
                aarch64) re='^rustdesk-[0-9.]+-aarch64\.dmg$' ;;
            esac
            ;;
    esac
    [ -n "$re" ] || return 0
    while IFS=' ' read -r name sum; do
        [ -n "$name" ] || continue
        if [[ $name =~ $re ]]; then rd_asset=$name; rd_sum=$sum; break; fi
    done <<< "$rd_files"
}

# The sha256 of file $1 in lowercase hex.
rd_sha256() {
    local out
    if command -v sha256sum >/dev/null 2>&1; then out=$(sha256sum < "$1"); out=${out%% *}
    elif command -v shasum >/dev/null 2>&1; then out=$(shasum -a 256 < "$1"); out=${out%% *}
    else out=$(openssl dgst -sha256 < "$1"); out=${out##* }
    fi
    printf '%s' "$out" | tr 'A-F' 'a-f'
}

# The installed version of RustDesk (x.y.z), or nothing.
rd_installed_version() {
    local bin out
    if [ "$os" = macos ]; then
        bin="${FLEET_ROOT:-}/Applications/RustDesk.app/Contents/MacOS/RustDesk"
        [ -x "$bin" ] || return 0
    else
        bin=$(find_tool rustdesk) || return 0
    fi
    out=$("$bin" --version 2>/dev/null || true)
    if [[ $out =~ $rd_found_version_re ]]; then printf '%s' "${BASH_REMATCH[1]}"; fi
    return 0
}

# Installs the file of the drive: a deb or an rpm with the package manager, a disk image by copying the app.
rd_install() {
    local mp rc=0 app="${FLEET_ROOT:-}/Applications/RustDesk.app"
    say "Installing RustDesk $rd_version..."
    case $rd_kind in
        deb) (cd "$usb/rustdesk" && run apt-get install -y "./$rd_asset" -o DPkg::Lock::Timeout=600 >/dev/null) || rc=$? ;;
        rpm) (cd "$usb/rustdesk" && run dnf install -y "./$rd_asset" >/dev/null) || rc=$? ;;
        dmg)
            mp=$(mktemp -d "$state/mount.XXXXXX")
            run hdiutil attach -nobrowse -readonly -mountpoint "$mp" "$usb/rustdesk/$rd_asset" >/dev/null || rc=$?
            if [ "$rc" -eq 0 ]; then
                if [ -d "$mp/RustDesk.app" ]; then
                    run ditto "$mp/RustDesk.app" "$app" || rc=$?
                else
                    rc=1
                    say "$rd_asset holds no RustDesk.app"
                fi
                run hdiutil detach "$mp" >/dev/null || say "the disk image could not be ejected"
            fi
            rmdir "$mp" 2>/dev/null || true
            ;;
    esac
    [ "$rc" -eq 0 ] || fail "installing $rd_asset failed (exit $rc)"
}

# The two launchd jobs of RustDesk on a Mac, as RustDesk's own installer writes them: the service (a system job) and
# the screen job (a job of the login window and of the Aqua session). Both belong to root and the wheel group.
rd_place_plist() {
    local dest=$1 tmp rc=0
    tmp=$(mktemp)
    cat > "$tmp"
    run install -d -m 755 "${dest%/*}" || rc=$?
    if [ "$rc" -eq 0 ]; then run install -m 644 -o root -g wheel "$tmp" "$dest" || rc=$?; fi
    rm -f "$tmp"
    [ "$rc" -eq 0 ] || fail "could not write $dest"
}
rd_write_plists() {
    rd_place_plist "${FLEET_ROOT:-}/Library/LaunchDaemons/$rd_service_label.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.carriez.RustDesk_service</string>
    <key>AssociatedBundleIdentifiers</key>
    <string>com.carriez.rustdesk</string>
    <key>KeepAlive</key>
    <true/>
    <key>ThrottleInterval</key>
    <integer>1</integer>
    <key>ProgramArguments</key>
    <array>
        <string>/Applications/RustDesk.app/Contents/MacOS/service</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>WorkingDirectory</key>
    <string>/Applications/RustDesk.app/Contents/MacOS/</string>
    <key>StandardErrorPath</key>
    <string>/var/log/rustdesk_service.err</string>
    <key>StandardOutPath</key>
    <string>/var/log/rustdesk_service.out</string>
</dict>
</plist>
PLIST
    rd_place_plist "${FLEET_ROOT:-}/Library/LaunchAgents/$rd_server_label.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.carriez.RustDesk_server</string>
    <key>AssociatedBundleIdentifiers</key>
    <string>com.carriez.rustdesk</string>
    <key>LimitLoadToSessionType</key>
    <array>
        <string>LoginWindow</string>
        <string>Aqua</string>
    </array>
    <key>KeepAlive</key>
    <dict>
        <key>SuccessfulExit</key>
        <false/>
        <key>AfterInitialDemand</key>
        <false/>
    </dict>
    <key>ThrottleInterval</key>
    <integer>1</integer>
    <key>RunAtLoad</key>
    <true/>
    <key>ProgramArguments</key>
    <array>
        <string>/Applications/RustDesk.app/Contents/MacOS/RustDesk</string>
        <string>--server</string>
    </array>
    <key>WorkingDirectory</key>
    <string>/Applications/RustDesk.app/Contents/MacOS/</string>
    <key>ProcessType</key>
    <string>Interactive</string>
</dict>
</plist>
PLIST
}

# Loads both jobs, each one after a bootout of the same job. launchd answers a bootstrap that follows a bootout too
# soon with an error, so a failed system bootstrap is tried once more after a short wait. The screen job loads only
# when the Account has a graphical session.
rd_mac_start() {
    local uid daemon="${FLEET_ROOT:-}/Library/LaunchDaemons/$rd_service_label.plist"
    local agent="${FLEET_ROOT:-}/Library/LaunchAgents/$rd_server_label.plist"
    uid=$(id -u "$user") || fail "no user id for $user"
    launchctl bootout "system/$rd_service_label" >/dev/null 2>&1 || true
    if ! launchctl bootstrap system "$daemon" >/dev/null 2>&1; then
        sleep 2
        launchctl bootout "system/$rd_service_label" >/dev/null 2>&1 || true
        run launchctl bootstrap system "$daemon" || fail "launchctl could not load the RustDesk service job"
    fi
    if launchctl print "gui/$uid" >/dev/null 2>&1; then
        launchctl bootout "gui/$uid/$rd_server_label" >/dev/null 2>&1 || true
        launchctl bootstrap "gui/$uid" "$agent" >/dev/null 2>&1 \
            || say "launchctl could not load the RustDesk screen job; sign in at the screen and run this again"
    fi
}

# The id that "--get-id" prints: the first line of 6 to 12 digits, else nothing.
rd_get_id() {
    local out line
    out=$("$rd_bin" --get-id 2>/dev/null || true)
    while IFS= read -r line; do
        line=${line%$'\r'}
        line=${line//[[:space:]]/}
        if [[ $line =~ $rd_id_re ]]; then printf '%s' "$line"; return 0; fi
    done <<< "$out"
    return 0
}

# Waits until "--get-id" prints an id: every 2 seconds, up to FLEET_RUSTDESK_WAIT_S seconds (60 when not set).
rd_wait_ready() {
    local limit=${FLEET_RUSTDESK_WAIT_S:-60} waited=0
    [[ $limit =~ ^[0-9]{1,4}$ ]] || limit=60
    while :; do
        if [ -n "$(rd_get_id)" ]; then return 0; fi
        [ "$waited" -lt "$limit" ] || return 1
        sleep 2
        waited=$((waited + 2))
    done
}

# The value of "<name> = '<value>'" (single or double quotes) in the TOML file $1: its first line of that name.
rd_toml_get() {
    local line re="^[[:space:]]*$2[[:space:]]*=[[:space:]]*[\"']([^\"']*)[\"']"
    [ -f "$1" ] || return 0
    while IFS= read -r line || [ -n "$line" ]; do
        line=${line%$'\r'}
        if [[ $line =~ $re ]]; then printf '%s' "${BASH_REMATCH[1]}"; return 0; fi
    done < "$1"
    return 0
}

# Prints the TOML file $1 with the server $2 and the key $3 in its [options] table: the old custom-rendezvous-server
# and key lines of that table go, and every other line stays. A file with no [options] table gets one at the end.
rd_merged_toml() {
    local file=$1 line section='' seen=0 table_re='^[[:space:]]*\[([^]]*)\][[:space:]]*$'
    local option_re='^[[:space:]]*(custom-rendezvous-server|key)[[:space:]]*='
    if [ -f "$file" ]; then
        while IFS= read -r line || [ -n "$line" ]; do
            line=${line%$'\r'}
            if [[ $line =~ $table_re ]]; then
                section=${BASH_REMATCH[1]}
                printf '%s\n' "$line"
                if [ "$section" = options ]; then
                    seen=1
                    printf "custom-rendezvous-server = '%s'\nkey = '%s'\n" "$2" "$3"
                fi
                continue
            fi
            if [ "$section" = options ] && [[ $line =~ $option_re ]]; then continue; fi
            printf '%s\n' "$line"
        done < "$file"
    fi
    if [ "$seen" -eq 0 ]; then printf "[options]\ncustom-rendezvous-server = '%s'\nkey = '%s'\n" "$2" "$3"; fi
}

# Creates folder $1, and every missing folder above it below the Account's home, owned by the Account.
rd_own_dir() {
    local d=$1
    if [ -d "$d" ]; then return 0; fi
    case $d in "$home"/*) rd_own_dir "${d%/*}" ;; esac
    run install -d -m 700 -o "$user" -g "$group" "$d"
}

# Writes the server and the key into RustDesk2.toml in folder $1: for the service as root, for the Account as the Account.
rd_apply_toml() {
    local dir=$1 file="$1/RustDesk2.toml" tmp rc=0
    tmp=$(mktemp)
    rd_merged_toml "$file" "$rd_host" "$rd_key" > "$tmp"
    if [ "$2" = account ]; then
        rd_own_dir "$dir" || rc=$?
        if [ "$rc" -eq 0 ]; then run install -m 644 -o "$user" -g "$group" "$tmp" "$file" || rc=$?; fi
    else
        run install -d -m 755 "$dir" || rc=$?
        if [ "$rc" -eq 0 ]; then run install -m 644 -o root -g "$(id -gn root)" "$tmp" "$file" || rc=$?; fi
    fi
    rm -f "$tmp"
    [ "$rc" -eq 0 ] || fail "could not write $file"
}

step_rustdesk() {
    local have svc_dir acct_dir got id
    if rd_has_desktop; then set_var gui true; else set_var gui false; skip "no desktop"; fi
    set_var session_type "$(rd_session_type)"
    [ -f "$usb/rustdesk.txt" ] || skip "no server configured"
    [ -r "$usb/rustdesk.txt" ] || fail "rustdesk.txt cannot be read"
    rd_read_file
    [ -n "$rd_version" ] || fail "rustdesk.txt holds no valid version line"
    [ -n "$rd_host" ] || fail "rustdesk.txt holds no valid host line"
    [ -n "$rd_key" ] || fail "rustdesk.txt holds no valid key line"
    rd_pick_asset
    [ -n "$rd_asset" ] || skip "no asset for $rd_label"
    [ -f "$usb/rustdesk/$rd_asset" ] || fail "$rd_asset is missing from the drive: run fleet_usb.py prepare on the hub"
    got=$(rd_sha256 "$usb/rustdesk/$rd_asset" || true)
    [ "$got" = "$rd_sum" ] || fail "$rd_asset does not match its sha256 in rustdesk.txt: run fleet_usb.py prepare on the hub"
    have=$(rd_installed_version)
    if [ "$have" = "$rd_version" ]; then say "RustDesk $have is already installed"; else rd_install; fi
    case $os in
        linux)
            rd_bin=$(find_tool rustdesk) || fail "no rustdesk program after the install"
            run systemctl enable --now rustdesk >/dev/null || fail "systemctl could not start the rustdesk service"
            ;;
        macos)
            rd_bin="${FLEET_ROOT:-}/Applications/RustDesk.app/Contents/MacOS/RustDesk"
            [ -x "$rd_bin" ] || fail "no RustDesk program in /Applications after the install"
            rd_write_plists
            rd_mac_start
            ;;
    esac
    rd_wait_ready || fail "service not ready"
    # Some RustDesk builds exit nonzero after they apply --config. The read-back below decides (EA-8).
    run "$rd_bin" --config "host=$rd_host,key=$rd_key" || say "rustdesk --config exited nonzero; the read-back decides"
    case $os in
        linux) svc_dir="${FLEET_ROOT:-}/root/.config/rustdesk"; acct_dir="$home/.config/rustdesk" ;;
        macos) svc_dir="${FLEET_ROOT:-}/var/root/Library/Preferences/com.carriez.RustDesk"
               acct_dir="$home/Library/Preferences/com.carriez.RustDesk" ;;
    esac
    got=$(rd_toml_get "$svc_dir/RustDesk2.toml" custom-rendezvous-server)
    if [ "$got" != "$rd_host" ]; then
        say "RustDesk did not keep the server in its service folder: writing the config files"
        rd_apply_toml "$svc_dir" root
        rd_apply_toml "$acct_dir" account
        case $os in
            linux) run systemctl restart rustdesk || fail "systemctl could not restart the rustdesk service" ;;
            macos) rd_mac_start ;;
        esac
        rd_wait_ready || fail "service not ready"
    fi
    id=$(rd_get_id)
    if [ -z "$id" ]; then id=$(rd_toml_get "$svc_dir/RustDesk.toml" id); fi
    [[ $id =~ $rd_id_re ]] || fail "no RustDesk id: --get-id printed none and RustDesk.toml holds none"
    set_var rustdesk_id "$id"
    if [ "$os" = macos ]; then note "$rd_grants"; else note "RustDesk $rd_version, server set"; fi
}

# The host key to pin, the port and the addresses, for the hub's import.
step_host_key() {
    local file="${FLEET_ROOT:-}/etc/ssh/ssh_host_ed25519_key.pub" key list
    if [ ! -f "$file" ]; then
        if [ -n "${FLEET_ROOT:-}" ]; then run ssh-keygen -A -f "$FLEET_ROOT" >/dev/null; else run ssh-keygen -A >/dev/null; fi
    fi
    [ -f "$file" ] || fail "no ed25519 host key at /etc/ssh/ssh_host_ed25519_key.pub"
    key="$(awk '{print $1 " " $2}' "$file")"
    [[ $key =~ $key_re ]] || fail "the host key file holds no ed25519 key"
    case $os in
        linux) list="$(ip -o -4 addr show scope global | awk '{split($4, a, "/"); print a[1]}')" ;;
        macos) list="$(ifconfig | awk '$1 == "inet" && $2 !~ /^(127|169\.254)\./ {print $2}')" ;;
    esac
    [ -n "$list" ] || fail "no IPv4 address on this machine"
    set_var host_key "$key"
    set_var port 22
    set_var addresses "$list"
    note "pinned on the hub at import"
}

# ----------------------------------------------------------------------------------------------- main

# The Name rule: lowercase; each character outside [a-z0-9-] becomes -; runs of - collapse; no - at either
# end; at most 63 characters; an empty result becomes member.
name_rule() {
    local s out='' c i prev=''
    s=$(printf '%s' "$1" | LC_ALL=C tr 'A-Z' 'a-z')
    local LC_ALL=C
    for ((i = 0; i < ${#s}; i++)); do
        c=${s:i:1}
        case $c in
            [a-z0-9]) out+=$c; prev=$c ;;
            *) if [ "$prev" != - ]; then out+=-; prev=-; fi ;;
        esac
    done
    out=${out#-}; out=${out%-}
    out=${out:0:63}; out=${out%-}
    printf '%s\n' "${out:-member}"
}

make_run_id() {
    local chars=abcdefghijklmnopqrstuvwxyz0123456789 i
    run_id=""
    for ((i = 0; i < 16; i++)); do run_id+=${chars:RANDOM % 36:1}; done
}

mark_interrupted() {
    interrupted=1
    if [ -n "$current_step" ]; then
        add_step "$current_step" failed interrupted
        current_step=""
    fi
}

# The steps after elevate, each skipped: a run that never got root ran none of them.
skip_root_steps() {
    local id
    for id in $RUN_STEPS; do
        if [ "$(status_of "$id")" = none ]; then add_step "$id" skipped "needs elevate"; fi
    done
}

# On Linux, a sudo link that points nowhere (an interrupted sudo to sudo-rs switch leaves one) is put right with
# the alternatives system, through pkexec, before the elevators are tried. It never switches the alternative.
repair_sudo() {
    local link="${FLEET_ROOT:-}/usr/bin/sudo" pkexec
    [ "$os" = linux ] || return 0
    if [ -L "$link" ] && [ ! -e "$link" ]; then
        pkexec=$(find_tool pkexec) || return 0
        command -v update-alternatives >/dev/null 2>&1 || return 0
        say "/usr/bin/sudo is a link that points nowhere; repairing it with: pkexec update-alternatives --auto sudo"
        "$pkexec" update-alternatives --auto sudo || say "the repair did not work; trying the other elevators"
    fi
    return 0
}

# True when members/<name>.json is a final record of this run: the elevated run wrote it.
own_final_record() {
    local file="$usb/members/$name.json"
    [ -f "$file" ] && grep -qxF "  \"run_id\": \"$run_id\"," "$file" && grep -qxF '  "final": true,' "$file"
}

# Runs this script again as root through the first elevator that works, and ends the run itself when the elevated
# run left a final record of its own. Otherwise it returns with the elevate step failed, and finalize writes
# the record.
elevate_and_wait() {
    local tool path rc=0 found=0 tried="" detail
    parent=1
    current_step=elevate
    repair_sudo
    if [ -z "$account" ] || [ "$account" = root ] || ! [[ $account =~ $user_re ]]; then
        detail="elevation failed: no account to set up (run it with bash from the account the agent will use)"
    else
        for tool in sudo sudo-rs sudo.ws pkexec; do
            path=$(find_tool "$tool") || continue
            found=1
            tried=$tool
            say "elevating with $tool..."
            rc=0
            "$path" bash "$script" --for-user "$account" --run-id "$run_id" || rc=$?
            case $rc in 126 | 127) continue ;; esac
            break
        done
        if [ "$found" = 0 ]; then
            detail="elevation failed: no sudo, sudo-rs, sudo.ws or pkexec found"
        else
            detail="elevation failed: $tried exited $rc, and the elevated run left no final record"
        fi
    fi
    if [ "$found" = 1 ] && own_final_record; then
        finalized=1
        say "the elevated run is done: members/$name.json is final"
        exit "$rc"
    fi
    current_step=""
    add_step elevate failed "$detail"
    say "elevate: failed, $detail"
}

# ----------------------------------------------------------------------------------------------- the send

# hub_urls (one per line) and hub_token become what hub.txt holds: its url lines that are a plain http or https
# address with a host and an optional port, and its first token line that fits. The file is read line by line and
# never evaluated; a line of any other kind, and a line end of CR LF, change nothing.
read_hub_file() {
    local line
    hub_urls=""; hub_token=""
    while IFS= read -r line || [ -n "$line" ]; do
        line=${line%$'\r'}
        case $line in
            url=*)
                if [[ ${line#url=} =~ $hub_url_re ]]; then hub_urls+="${line#url=}"$'\n'; fi
                ;;
            token=*)
                if [ -z "$hub_token" ] && [[ ${line#token=} =~ $token_re ]]; then hub_token=${line#token=}; fi
                ;;
        esac
    done < "$1"
}

# Sets delivery_status and delivery_detail before the final write. A record that cannot be sent is failed at once,
# with the reason, so that the drive copy is written once; a record that can be sent is pending until the send ends.
plan_delivery() {
    hub_curl=""
    if [ ! -f "$usb/hub.txt" ]; then delivery_status=failed; delivery_detail="no hub.txt"; return 0; fi
    if [ ! -r "$usb/hub.txt" ]; then delivery_status=failed; delivery_detail="hub.txt cannot be read"; return 0; fi
    if ! hub_curl=$(find_tool curl); then hub_curl=""; delivery_status=failed; delivery_detail="no curl"; return 0; fi
    read_hub_file "$usb/hub.txt"
    if [ -z "$hub_token" ]; then delivery_status=failed; delivery_detail="no valid token line in hub.txt"; return 0; fi
    if [ -z "$hub_urls" ]; then delivery_status=failed; delivery_detail="no url line in hub.txt"; return 0; fi
    delivery_status=pending
    delivery_detail=""
}

# Posts the final record, with delivery null, to each url of hub.txt in turn, and stops at the first 200. It ends
# with delivery_status sent (the url) or failed (the result of each url). A stop during the send leaves the drive
# copy as it is, pending.
send_record() {
    local body="$state/body.json" keep_status=$delivery_status keep_detail=$delivery_detail
    local url code rc result results="" sep=""
    delivery_status=""; delivery_detail=""
    build_record true
    delivery_status=$keep_status; delivery_detail=$keep_detail
    printf '%s\n' "$REC" > "$body"
    trap 'rm -rf "$state"; exit 130' INT TERM HUP
    while IFS= read -r url; do
        [ -n "$url" ] || continue
        say "sending the record to $url"
        rc=0
        code=$("$hub_curl" -s -o /dev/null -w '%{http_code}' -X POST --connect-timeout 5 --max-time 20 \
            -H "X-Fleet-Token: $hub_token" -H 'Content-Type: application/json' --data-binary "@$body" \
            "$url/v1/usb-record" < /dev/null 2> /dev/null) || rc=$?
        if [ "$rc" -eq 0 ] && [ "$code" = 200 ]; then
            delivery_status=sent
            delivery_detail=$url
            break
        fi
        if [ "$rc" -ne 0 ]; then result="$url curl exit $rc"; else result="$url HTTP ${code:-000}"; fi
        results+="$sep$result"
        sep='; '
    done <<< "$hub_urls"
    trap - INT TERM HUP
    rm -f "$body"
    if [ "$delivery_status" != sent ]; then
        cut_detail "$results"
        delivery_status=failed
        delivery_detail=$J
    fi
}

finalize() {
    local rc=$? i
    set +e
    trap - INT TERM HUP
    [ "$finalized" = 0 ] || return 0
    finalized=1
    if [ "$main_done" != 1 ]; then
        main_failed=1
        [ "$interrupted" = 1 ] || say "stopped by an unexpected error (exit $rc)"
    fi
    if [ "$parent" = 1 ]; then skip_root_steps; fi
    plan_delivery
    write_record true
    if [ "$delivery_status" = pending ]; then
        send_record
        write_record true
    fi
    echo
    for ((i = 0; i < ${#step_ids[@]}; i++)); do
        printf '  %-13s %s%s\n' "${step_ids[i]}" "${step_status[i]}" "${step_detail[i]:+, ${step_detail[i]}}"
    done
    if [ "$os" = macos ]; then
        echo "On this Mac, also turn on 'Allow full disk access for remote users' under Remote Login's (i) button."
    fi
    if [ "$delivery_status" = sent ]; then
        echo "Sent the record to the hub: $delivery_detail. A copy is on the drive at $usb/members/$name.json."
    else
        echo "Wrote $usb/members/$name.json. The hub did not get the record (${delivery_detail:-no result}); eject the drive before you unplug it, then take it back to the hub machine and run the import there."
    fi
    [ -z "$state" ] || rm -rf "$state"
    if [ "$interrupted" = 1 ]; then exit 130; fi
    if record_ok true; then exit 0; fi
    exit 1
}

parse_args() {
    while [ $# -gt 0 ]; do
        case $1 in
            --for-user | --run-id)
                [ $# -ge 2 ] || { say "$1 needs a value"; exit 2; }
                if [ "$1" = --for-user ]; then for_user=$2; else run_id=$2; fi
                shift 2
                ;;
            *) say "unknown argument: $1"; exit 2 ;;
        esac
    done
    if [ -n "$run_id" ] && ! [[ $run_id =~ ^[a-z0-9]{8,32}$ ]]; then say "--run-id is not a run id: $run_id"; exit 2; fi
}

main() {
    local raw="" id
    parse_args "$@"
    usb="$(cd "$(dirname "$0")" && pwd)"
    script="$usb/$(basename "$0")"
    state="$(mktemp -d)"
    # The main shell's process id; the Ctrl+C tests in scripts/tests/test_fleet_usb.py signal it.
    export FLEET_SETUP_PID=$$
    [ -n "$run_id" ] || make_run_id
    case "$(uname -s)" in
        Linux) os=linux ;;
        Darwin) os=macos ;;
        *) say "this script covers macOS and Linux only"; exit 1 ;;
    esac
    case $os in
        linux) raw="$(hostname -s 2>/dev/null || true)" ;;
        macos) raw="$(scutil --get LocalHostName 2>/dev/null || true)" ;;
    esac
    name="$(name_rule "$raw")"
    resolve_account
    user="${account:-$(id -un 2>/dev/null || true)}"
    [[ $user =~ $record_user_re ]] || user=unknown
    trap finalize EXIT
    trap 'mark_interrupted; exit 130' INT TERM HUP
    checkpoint
    if [ "$(id -u)" -ne 0 ]; then
        elevate_and_wait
        main_done=1
        return 0
    fi
    for id in $RUN_STEPS; do run_step "$id"; done
    collect_tools || true
    main_done=1
}

if [ "${BASH_SOURCE[0]}" = "$0" ]; then main "$@"; fi
