"""Give the hub machine an SSH admin connection to new machines through a USB drive.

``prepare <folder>`` makes the hub's admin key if it is missing, then copies the public key and the member
scripts to a folder on the drive. On each machine, the human runs the script for its system from the drive; it
writes ``members/<name>.json`` there. ``import <folder>`` reads those records back on the hub machine, pins
each host key, writes each machine's entry in the hub user's SSH config and tests the connection.

The private key, the addresses and the host keys stay in the hub user's ``~/.ssh``. Nothing on the drive is
secret, and the repository holds no host.
"""

from __future__ import annotations

import argparse
import ipaddress
import json
import os
import re
import shutil
import socket
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
MEMBER_FILES = ("setup-windows.ps1", "setup-unix.sh", "Setup Windows.cmd", "Setup Mac.command",
                "Setup Linux.desktop", "README.md")
# cmd.exe wants CRLF line ends, and bash fails on a CR at a line's end.
CRLF_SUFFIXES = (".cmd",)
LF_SUFFIXES = (".sh", ".command", ".desktop")
KEY_NAME = "fleet_ed25519"
CONFIG_NAME = "fleet_config"
INCLUDE = f"Include {CONFIG_NAME}"

NAME = re.compile(r"[a-z0-9][a-z0-9-]{0,62}\Z")
USER = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_. -]{0,63}\Z")
HOST_KEY = re.compile(r"ssh-ed25519 [A-Za-z0-9+/]+={0,2}\Z")
SYSTEMS = ("windows", "macos", "linux")
# Each system's check that the session has full access: an elevated administrator, or sudo with no password.
ADMIN_CHECK = {
    "windows": "([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent())"
               ".IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)",
    "macos": "sudo -n true 2>/dev/null && echo True || echo False",
    "linux": "sudo -n true 2>/dev/null && echo True || echo False",
}


def ssh_dir() -> Path:
    return Path.home() / ".ssh"


def write_text(path: Path, text: str) -> None:
    """Replace the file in one step, with LF line ends."""
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(text.encode("utf-8"))
    os.replace(tmp, path)


def tool(name: str) -> str:
    found = shutil.which(name)
    if not found:
        sys.exit(f"fleet-usb: {name} is not on PATH")
    return found


def prepare(folder: Path) -> int:
    key = ssh_dir() / KEY_NAME
    if not key.exists():
        ssh_dir().mkdir(exist_ok=True)
        subprocess.run([tool("ssh-keygen"), "-q", "-t", "ed25519", "-N", "", "-C", "fleet-admin", "-f", str(key)],
                       check=True)
        print(f"Made the hub's admin key: {key}")
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "members").mkdir(exist_ok=True)
    for name in MEMBER_FILES:
        data = (HERE / name).read_bytes()
        if name.endswith(CRLF_SUFFIXES + LF_SUFFIXES):
            data = data.replace(b"\r\n", b"\n")
        if name.endswith(CRLF_SUFFIXES):
            data = data.replace(b"\n", b"\r\n")
        (folder / name).write_bytes(data)
    public = " ".join(key.with_suffix(".pub").read_text(encoding="ascii").split()[:3])
    (folder / "hub.pub").write_bytes(f"{public}\n".encode("ascii"))
    fingerprint = subprocess.run([tool("ssh-keygen"), "-lf", str(folder / "hub.pub")],
                                 capture_output=True, text=True, check=True).stdout.strip()
    print(f"Prepared {folder}")
    print(f"Hub key: {fingerprint}")
    print("Each machine's script prints the key it installs. It must match this line.")
    return 0


def read_record(path: Path) -> dict:
    """One machine's record from the drive, checked field by field."""
    try:
        record = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as e:
        raise ValueError(f"unreadable: {e}") from None
    if not isinstance(record, dict) or record.get("v") != 1:
        raise ValueError("not a v1 record")
    name, user, system = record.get("name"), record.get("user"), record.get("os")
    port, key, addresses = record.get("port"), record.get("host_key"), record.get("addresses")
    if not (isinstance(name, str) and NAME.match(name)):
        raise ValueError(f"bad name {name!r}")
    if not (isinstance(user, str) and USER.match(user)):
        raise ValueError(f"bad user {user!r}")
    if system not in SYSTEMS:
        raise ValueError(f"bad os {system!r}")
    if not (isinstance(port, int) and 0 < port < 65536):
        raise ValueError(f"bad port {port!r}")
    if not (isinstance(key, str) and HOST_KEY.match(key)):
        raise ValueError("bad host_key")
    if isinstance(addresses, str):
        addresses = [addresses]
    if not (isinstance(addresses, list) and addresses):
        raise ValueError("no addresses")
    try:
        addresses = [str(ipaddress.IPv4Address(a)) for a in addresses]
    except (ValueError, TypeError):
        raise ValueError(f"bad addresses {addresses!r}") from None
    return {"name": name, "user": user, "os": system, "port": port, "host_key": key, "addresses": addresses}


def reachable(addresses: list[str], port: int) -> str | None:
    for address in addresses:
        try:
            with socket.create_connection((address, port), timeout=2):
                return address
        except OSError:
            continue
    return None


def render_config(members: dict) -> str:
    lines = ["# Written by fleet_usb.py import. Each machine's entry is rewritten on its next import.", ""]
    for name in sorted(members):
        m = members[name]
        user = f'"{m["user"]}"' if " " in m["user"] else m["user"]
        lines += [
            f"Host {name}",
            f"    HostName {m['address']}",
            f"    User {user}",
            f"    Port {m['port']}",
            f"    IdentityFile ~/.ssh/{KEY_NAME}",
            "    IdentitiesOnly yes",
            f"    HostKeyAlias {name}",
            "    UserKnownHostsFile ~/.ssh/fleet_known_hosts",
            "    StrictHostKeyChecking yes",
            "    BatchMode yes",
            "    ConnectTimeout 10",
            "",
        ]
    return "\n".join(lines)


def include_config() -> bool:
    """Put the Include line first in ~/.ssh/config, so the fleet's entries apply. Returns True when it wrote."""
    main = ssh_dir() / "config"
    text = main.read_text(encoding="utf-8") if main.exists() else ""
    if any(line.strip().lower() == INCLUDE.lower() for line in text.splitlines()):
        return False
    write_text(main, f"{INCLUDE}\n\n{text}" if text else f"{INCLUDE}\n")
    return True


def test_connection(name: str, system: str) -> str:
    try:
        r = subprocess.run([tool("ssh"), name, ADMIN_CHECK[system]], capture_output=True, text=True, timeout=60)
    except subprocess.TimeoutExpired:
        return "no answer in 60 s"
    if r.returncode != 0:
        tail = (r.stderr.strip().splitlines() or ["no output"])[-1]
        return f"failed (exit {r.returncode}): {tail}"
    return "full access" if r.stdout.strip().endswith("True") else "connected, without full access"


def import_records(folder: Path, test: bool) -> int:
    paths = sorted((folder / "members").glob("*.json"))
    if not paths:
        print(f"No records in {folder / 'members'}")
        return 1
    if not (ssh_dir() / KEY_NAME).exists():
        sys.exit("fleet-usb: the hub's admin key is missing; run prepare first")
    state_path = ssh_dir() / "fleet_members.json"
    members = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else {}
    imported, failed = [], 0
    for path in paths:
        try:
            record = read_record(path)
        except ValueError as e:
            print(f"{path.name}: skipped, {e}")
            failed += 1
            continue
        name = record["name"]
        address = reachable(record["addresses"], record["port"])
        old = members.get(name)
        if old and old["host_key"] != record["host_key"]:
            print(f"{name}: its host key changed since the last import; the drive's key is pinned now")
        members[name] = {"os": record["os"], "user": record["user"], "port": record["port"],
                         "address": address or record["addresses"][0], "host_key": record["host_key"]}
        imported.append((name, address))
    write_text(state_path, json.dumps(members, indent=2) + "\n")
    write_text(ssh_dir() / CONFIG_NAME, render_config(members))
    write_text(ssh_dir() / "fleet_known_hosts", "".join(f"{n} {m['host_key']}\n" for n, m in sorted(members.items())))
    if include_config():
        print(f"Added '{INCLUDE}' to the top of {ssh_dir() / 'config'}")
    for name, address in imported:
        if not address:
            print(f"{name}: recorded, but port {members[name]['port']} answers at none of its addresses")
            failed += 1
            continue
        result = test_connection(name, members[name]["os"]) if test else "not tested"
        print(f"{name}: ssh {name} -> {members[name]['user']}@{address}, {result}")
        if test and result != "full access":
            failed += 1
    return 1 if failed else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("prepare", help="Copy the hub's public key and the member scripts to a folder on the drive")
    p.add_argument("folder", type=Path)
    i = sub.add_parser("import", help="Pin and connect each machine recorded on the drive")
    i.add_argument("folder", type=Path)
    i.add_argument("--no-test", action="store_true", help="Write the SSH entries without connecting")
    args = parser.parse_args(argv)
    if args.command == "prepare":
        return prepare(args.folder)
    return import_records(args.folder, test=not args.no_test)


if __name__ == "__main__":
    sys.exit(main())
