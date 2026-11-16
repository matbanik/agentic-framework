"""Give the hub machine an SSH admin connection to new machines through a USB drive.

``prepare <folder>`` makes the hub's admin key if it is missing, then copies the public key and the member
scripts to a folder on the drive. On each machine, the human runs the script for its system from the drive; it
writes ``members/<name>.json`` there. ``import <folder>`` reads those records back on the hub machine, pins
each host key, writes each machine's entry in the hub user's SSH config and tests the connection.

``prepare`` also writes ``hub.txt`` (the hub's URLs and a token), so a machine on the network can send its record
to the hub: ``receive <folder>`` takes those records into the same ``members/`` folder, and ``import`` reads them
as it reads the drive's.

With ``--rustdesk-host`` and a key, ``prepare`` also downloads the latest RustDesk release for the six platforms
to ``rustdesk/`` on the drive and writes ``rustdesk.txt`` (the version, the server and a sha256 for each file), so
a machine with a screen can install RustDesk from the drive. ``import`` then sets each machine's RustDesk
password over SSH, from a file in the hub user's ``~/.ssh``; the password never appears in a command line, an
output line or a file other than that one.

The private key, the addresses and the host keys stay in the hub user's ``~/.ssh``, with the token. The drive
holds the token (the hub file), so keep the drive with the person who runs the kit. The repository holds no host.
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import http.client
import ipaddress
import json
import os
import re
import secrets
import shutil
import socket
import socketserver
import subprocess
import sys
import tempfile
import time
import urllib.request
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, HTTPServer
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
# Record v2 (the USB kit plan's Record v2 definition): its keys, ids and limits.
V2_KEYS = frozenset(("v", "run_id", "final", "name", "os", "user", "ok", "steps", "tools", "gui", "session_type",
                     "rustdesk_id", "port", "host_key", "addresses", "delivery"))
RUN_ID = re.compile(r"[a-z0-9]{8,32}\Z")
RUSTDESK_ID = re.compile(r"[0-9]{6,12}\Z")
STEP_IDS = ("elevate", "account", "packages", "ssh_server", "firewall", "hub_key", "admin_rights", "linger",
            "homebrew", "pwsh", "uv", "claude", "codex", "tool_links", "rustdesk", "host_key")
STEP_STATUSES = ("ok", "failed", "skipped")
TOOL_IDS = ("git", "python", "pwsh", "uv", "claude", "codex", "rustdesk")
SESSION_TYPES = ("x11", "wayland", "tty", "windows", "macos", "unknown")
DELIVERY_STATUSES = ("pending", "sent", "failed")
DETAIL_MAX = 300
TOOL_VERSION_MAX = 200
# Network write-back (the USB kit plan's WP-K4): the Hub file, its token and the receiver's one route.
TOKEN_NAME = "fleet_usb_token"
TOKEN = re.compile(r"[A-Za-z0-9_-]{32,64}\Z")
HUB_URL = re.compile(r"https?://[A-Za-z0-9.-]+(?::([0-9]{1,5}))?\Z")
RECEIVE_PORT = 8771
ROUTE = "/v1/usb-record"
MAX_BODY = 65536
DRAIN_MAX = 1 << 20  # what the receiver reads and drops from a request that it refuses before reading it
# RustDesk on the members (the USB kit plan's WP-K5): the release to download, the server to give each member and
# the password that import sets.
RUSTDESK_RELEASE_URL = "https://api.github.com/repos/rustdesk/rustdesk/releases/latest"
RUSTDESK_URL_PREFIX = "https://github.com/"
RUSTDESK_TAG = re.compile(r"v?([0-9]+\.[0-9]+\.[0-9]+)\Z")
RUSTDESK_DIGEST = re.compile(r"sha256:([0-9a-f]{64})\Z")
# One asset for each platform that the kit installs on, in the order that rustdesk.txt lists them.
RUSTDESK_ASSETS = (
    ("windows", re.compile(r"rustdesk-[0-9.]+-x86_64\.msi")),
    ("linux x86_64 (deb)", re.compile(r"rustdesk-[0-9.]+-x86_64\.deb")),
    ("linux aarch64 (deb)", re.compile(r"rustdesk-[0-9.]+-aarch64\.deb")),
    ("linux x86_64 (rpm)", re.compile(r"rustdesk-[0-9.]+-0\.x86_64\.rpm")),
    ("macos x86_64", re.compile(r"rustdesk-[0-9.]+-x86_64\.dmg")),
    ("macos aarch64", re.compile(r"rustdesk-[0-9.]+-aarch64\.dmg")),
)
# The host lands in a command line on each member, so it is a name or an address with an optional port, no more.
RUSTDESK_HOST = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,252}(?::([0-9]{1,5}))?")
RUSTDESK_KEY = re.compile(r"[A-Za-z0-9+/=]{40,64}")
RUSTDESK_PASSWORD = re.compile(r"[A-Za-z0-9_-]{8,64}\Z")
RUSTDESK_SAVED = "fleet_rustdesk.json"
FETCH_TIMEOUT = 60  # seconds that one network call may take
FETCH_MAX = 512 * 1024 * 1024  # the most that one answer may hold
SSH_TIMEOUT = 60
# The remote command that sets the RustDesk password: it reads the password from standard input, so no command line
# on the member (and no process list) ever holds it. The password file holds only A-Z a-z 0-9 _ -, so $pw needs no quotes.
RUSTDESK_PASSWORD_COMMAND = {
    "linux": "bash -c 'IFS= read -r pw; sudo -n rustdesk --password $pw'",
    "macos": "bash -c 'IFS= read -r pw; sudo -n /Applications/RustDesk.app/Contents/MacOS/RustDesk --password $pw'",
    "windows": "$p = [Console]::In.ReadLine(); & 'C:\\Program Files\\RustDesk\\rustdesk.exe' --password $p | Out-Null; "
               "exit $LASTEXITCODE",
}
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


def check_hub_url(url: str) -> str:
    """One --hub-url value, without a trailing slash: http(s)://host or host:port, nothing else."""
    cleaned = url.rstrip("/")
    found = HUB_URL.match(cleaned)
    if not found or (found.group(1) and int(found.group(1)) > 65535):
        sys.exit(f"fleet-usb: --hub-url {url!r} is not a URL of the form http://host:port")
    return cleaned


def computed_hub_urls() -> list[str]:
    """http://<address>:8771 for each IPv4 address of this machine, without loopback and link-local ones."""
    try:
        found = socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET)
    except OSError:
        return []
    urls: list[str] = []
    for item in found:
        address = ipaddress.IPv4Address(item[4][0])
        url = f"http://{address}:{RECEIVE_PORT}"
        if not (address.is_loopback or address.is_link_local) and url not in urls:
            urls.append(url)
    return urls


def read_token(path: Path) -> str:
    """The token in the file, or stop with the file's name when it holds anything else."""
    token = path.read_text(encoding="ascii", errors="replace").strip()
    if not TOKEN.match(token):
        sys.exit(f"fleet-usb: {path} does not hold a token (32 to 64 characters of A-Z a-z 0-9 _ -); "
                 "delete the file to make a new one")
    return token


def hub_token() -> str:
    """The hub's token from ~/.ssh/fleet_usb_token, made there (mode 600 on POSIX) when the file is missing."""
    path = ssh_dir() / TOKEN_NAME
    if path.exists():
        return read_token(path)
    token = secrets.token_urlsafe(32)
    ssh_dir().mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as handle:
        handle.write(f"{token}\n".encode("ascii"))
    return token


def check_rustdesk_host(host: str, where: str) -> str:
    """The RustDesk server's host (a name or an address, with an optional port), or stop naming ``where``."""
    found = RUSTDESK_HOST.fullmatch(host)
    if not found or (found.group(1) and not 0 < int(found.group(1)) <= 65535):
        sys.exit(f"fleet-usb: {where} is not a host name or address with an optional :port")
    return host


def check_rustdesk_key(key: str, where: str) -> str:
    """The RustDesk server's public key, or stop naming ``where``. The value itself is never echoed."""
    if not RUSTDESK_KEY.fullmatch(key):
        sys.exit(f"fleet-usb: {where} is not a RustDesk key (40 to 64 characters of A-Z a-z 0-9 + / =)")
    return key


def read_saved_server(path: Path) -> dict[str, str]:
    """The saved RustDesk server (host and key, either may be missing), or stop naming the file."""
    try:
        saved = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as e:
        sys.exit(f"fleet-usb: {path} is not readable ({e}); fix it or delete it")
    if not isinstance(saved, dict) or not set(saved) <= {"host", "key"} or not all(isinstance(v, str) for v in saved.values()):
        sys.exit(f"fleet-usb: {path} must be a JSON object with only the strings host and key; fix it or delete it")
    if "host" in saved:
        check_rustdesk_host(saved["host"], f"the host in {path}")
    if "key" in saved:
        check_rustdesk_key(saved["key"], f"the key in {path}")
    return saved


def resolve_rustdesk(host: str | None, key: str | None, key_file: Path | None) -> tuple[dict[str, str] | None, bool]:
    """The RustDesk server for this run, and whether it differs from the saved one.

    Each value comes from its option, else from ``~/.ssh/fleet_rustdesk.json``. With neither value anywhere, the run
    has no RustDesk server (None). One value without the other stops the run. Nothing is written here.
    """
    path = ssh_dir() / RUSTDESK_SAVED
    saved = read_saved_server(path) if path.exists() else {}
    given: dict[str, str] = {}
    if host is not None:
        given["host"] = check_rustdesk_host(host, "--rustdesk-host")
    where = "--rustdesk-key"
    if key_file is not None:
        where = "--rustdesk-key-file"
        try:
            key = key_file.read_text(encoding="ascii").strip()
        except (OSError, UnicodeDecodeError) as e:
            sys.exit(f"fleet-usb: --rustdesk-key-file {key_file} is not readable: {e}")
    if key is not None:
        given["key"] = check_rustdesk_key(key, where)
    server = {**saved, **given}
    if not server:
        return None, False
    for field, option in (("host", "--rustdesk-host"), ("key", "--rustdesk-key")):
        if field not in server:
            sys.exit(f"fleet-usb: RustDesk needs a host and a key; {option} is missing and {path} does not hold it")
    return server, server != saved


def fetch(url: str) -> bytes:
    """The body that the URL answers, at most FETCH_MAX bytes. Any failure raises OSError or HTTPException."""
    request = urllib.request.Request(url, headers={"User-Agent": "fleet-usb"})
    with urllib.request.urlopen(request, timeout=FETCH_TIMEOUT) as response:
        data = response.read(FETCH_MAX + 1)
    if len(data) > FETCH_MAX:
        raise OSError(f"{url} answered more than {FETCH_MAX} bytes")
    return data


def read_release(raw: bytes) -> tuple[str, list[dict]]:
    """The version and the assets of a GitHub release answer, or ValueError. A bad release is refused as a whole.

    The tag must be x.y.z (a leading v is dropped), the release must not be a prerelease, every download URL must
    be on https://github.com/ and a digest, where an asset has one, must be ``sha256:<64 hex digits>``.
    """
    try:
        release = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as e:
        raise ValueError(f"the answer is not JSON ({e})") from None
    if not isinstance(release, dict):
        raise ValueError("the answer is not a JSON object")
    tag = release.get("tag_name")
    found = RUSTDESK_TAG.fullmatch(tag) if isinstance(tag, str) else None
    if not found:
        raise ValueError(f"the tag {tag!r} is not a version number")
    if release.get("prerelease") is not False:
        raise ValueError(f"release {tag} is a prerelease or does not say")
    assets = release.get("assets")
    if not isinstance(assets, list):
        raise ValueError("the release holds no list of assets")
    for asset in assets:
        if not isinstance(asset, dict) or not isinstance(asset.get("name"), str):
            raise ValueError("an asset has no name")
        url = asset.get("browser_download_url")
        if not isinstance(url, str) or not url.startswith(RUSTDESK_URL_PREFIX):
            raise ValueError(f"the download URL of {asset['name']} is not on {RUSTDESK_URL_PREFIX}")
        digest = asset.get("digest")
        if digest is not None and not (isinstance(digest, str) and RUSTDESK_DIGEST.fullmatch(digest)):
            raise ValueError(f"the digest of {asset['name']} is not sha256:<64 hex digits>")
    return found.group(1), assets


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def store_asset(target: Path, data: bytes) -> None:
    """Put the bytes at the target in one step, so a stop never leaves a cut-short file under the asset's name."""
    tmp = target.with_name(target.name + ".tmp")
    try:
        tmp.write_bytes(data)
        os.replace(tmp, target)
    finally:
        tmp.unlink(missing_ok=True)


def sync_rustdesk(folder: Path, server: dict[str, str]) -> bool:
    """Put the latest release's assets in ``rustdesk/`` and write ``rustdesk.txt``. True when nothing failed.

    A file on the drive whose sha256 equals the release's digest is kept; any other file is downloaded again,
    and so is every file of a release that gives no digest. A download that fails or does not match its digest
    is left out of ``rustdesk.txt`` and reported. A platform with no asset is reported and left out; that is not
    a failure. When the release cannot be used, an old ``rustdesk.txt`` is removed, so a member never installs an
    older release under a newer server.
    """
    listing = folder / "rustdesk.txt"
    try:
        version, assets = read_release(fetch(RUSTDESK_RELEASE_URL))
    except (OSError, http.client.HTTPException, ValueError) as e:
        listing.unlink(missing_ok=True)
        print(f"rustdesk: the latest release is not usable ({e}); rustdesk.txt is not written")
        return False
    store = folder / "rustdesk"
    store.mkdir(exist_ok=True)
    lines = [f"version={version}", f"host={server['host']}", f"key={server['key']}"]
    ok = True
    for label, pattern in RUSTDESK_ASSETS:
        asset = next((a for a in assets if pattern.fullmatch(a["name"])), None)
        if asset is None:
            print(f"rustdesk: release {version} holds no asset for {label}; a member of that kind skips RustDesk")
            continue
        name = asset["name"]
        want = RUSTDESK_DIGEST.fullmatch(asset["digest"]).group(1) if asset.get("digest") else None
        target = store / name
        try:
            if want and target.is_file() and file_sha256(target) == want:
                have = want
            else:
                data = fetch(asset["browser_download_url"])
                have = hashlib.sha256(data).hexdigest()
                if want and have != want:
                    raise ValueError(f"the download's sha256 is not the release's digest ({have} against {want})")
                store_asset(target, data)
        except (OSError, http.client.HTTPException, ValueError) as e:
            print(f"rustdesk: {name} is left out: {e}")
            ok = False
            continue
        lines.append(f"file={name} {have}")
    write_text(listing, "".join(f"{line}\n" for line in lines))
    print(f"rustdesk: release {version} for {server['host']}, {len(lines) - 3} of {len(RUSTDESK_ASSETS)} files in {store}")
    return ok


def prepare(folder: Path, hub_urls: list[str] | None = None, rustdesk_host: str | None = None,
            rustdesk_key: str | None = None, rustdesk_key_file: Path | None = None) -> int:
    urls = [check_hub_url(u) for u in hub_urls] if hub_urls else computed_hub_urls()
    server, server_changed = resolve_rustdesk(rustdesk_host, rustdesk_key, rustdesk_key_file)
    token = hub_token()
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
    write_text(folder / "hub.txt", "".join(f"url={u}\n" for u in urls) + f"token={token}\n")
    if server and server_changed:
        write_text(ssh_dir() / RUSTDESK_SAVED, json.dumps(server, indent=2) + "\n")
    # A RustDesk failure never stops the rest of prepare: the SSH part of the kit works without it.
    rustdesk_ok = sync_rustdesk(folder, server) if server else True
    fingerprint = subprocess.run([tool("ssh-keygen"), "-lf", str(folder / "hub.pub")],
                                 capture_output=True, text=True, check=True).stdout.strip()
    print(f"Prepared {folder}")
    print(f"Hub key: {fingerprint}")
    print("Each machine's script prints the key it installs. It must match this line.")
    for url in urls:
        print(f"Each machine sends its record to: {url}")
    if not urls:
        print("No usable hub address was found, so hub.txt holds no URL and the machines only write to the drive. "
              f"Pass --hub-url http://<hub address>:{RECEIVE_PORT} to name one.")
    if not server:
        print("No RustDesk server is set, so the machines do not install RustDesk. Pass --rustdesk-host and "
              "--rustdesk-key (or --rustdesk-key-file) to set one.")
    print(f"To take the sent records, run: fleet_usb.py receive {folder}")
    return 0 if rustdesk_ok else 1


def read_record(path: Path) -> dict:
    """One machine's record from the drive, checked field by field: Record v1, or Record v2 (a checkpoint too)."""
    try:
        record = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as e:
        raise ValueError(f"unreadable: {e}") from None
    if not isinstance(record, dict) or record.get("v") not in (1, 2) or isinstance(record.get("v"), bool):
        raise ValueError("not a v1 or v2 record")
    if record["v"] == 2:
        return read_v2(record)
    name, user, system = record.get("name"), record.get("user"), record.get("os")
    port, key, addresses = record.get("port"), record.get("host_key"), record.get("addresses")
    check_identity(name, user, system)
    if not (isinstance(port, int) and not isinstance(port, bool) and 0 < port < 65536):
        raise ValueError(f"bad port {port!r}")
    if not (isinstance(key, str) and HOST_KEY.match(key)):
        raise ValueError("bad host_key")
    if isinstance(addresses, str):
        addresses = [addresses]
    if not (isinstance(addresses, list) and addresses):
        raise ValueError("no addresses")
    return {"v": 1, "name": name, "user": user, "os": system, "port": port, "host_key": key,
            "addresses": check_addresses(addresses)}


def check_identity(name: object, user: object, system: object) -> None:
    if not (isinstance(name, str) and NAME.match(name)):
        raise ValueError(f"bad name {name!r}")
    if not (isinstance(user, str) and USER.match(user)):
        raise ValueError(f"bad user {user!r}")
    if system not in SYSTEMS:
        raise ValueError(f"bad os {system!r}")


def check_addresses(addresses: list) -> list[str]:
    try:
        return [str(ipaddress.IPv4Address(a)) for a in addresses]
    except (ValueError, TypeError):
        raise ValueError(f"bad addresses {addresses!r}") from None


def read_v2(record: dict) -> dict:
    """Record v2 of the USB kit plan: exactly its keys, each checked, and the rules that tie them together."""
    if set(record) != V2_KEYS:
        extra, missing = sorted(set(record) - V2_KEYS), sorted(V2_KEYS - set(record))
        raise ValueError(f"v2 keys: unknown {extra}, missing {missing}")
    run_id, final, ok = record["run_id"], record["final"], record["ok"]
    if not (isinstance(run_id, str) and RUN_ID.match(run_id)):
        raise ValueError(f"bad run_id {run_id!r}")
    if not isinstance(final, bool) or not isinstance(ok, bool):
        raise ValueError("final and ok must be booleans")
    check_identity(record["name"], record["user"], record["os"])
    steps = check_steps(record["steps"])
    if ok and (not final or any(s["status"] == "failed" for s in steps)):
        raise ValueError("ok is true, but the run is not final or a step failed")
    check_tools(record["tools"])
    if not isinstance(record["gui"], bool):
        raise ValueError("bad gui")
    if record["session_type"] not in SESSION_TYPES:
        raise ValueError(f"bad session_type {record['session_type']!r}")
    rustdesk_id = record["rustdesk_id"]
    if rustdesk_id is not None and not (isinstance(rustdesk_id, str) and RUSTDESK_ID.match(rustdesk_id)):
        raise ValueError(f"bad rustdesk_id {rustdesk_id!r}")
    port, key, addresses = record["port"], record["host_key"], record["addresses"]
    if port is not None and not (isinstance(port, int) and not isinstance(port, bool) and 0 < port < 65536):
        raise ValueError(f"bad port {port!r}")
    if key is not None and not (isinstance(key, str) and HOST_KEY.match(key)):
        raise ValueError("bad host_key")
    if not isinstance(addresses, list):
        raise ValueError("bad addresses")
    addresses = check_addresses(addresses)
    if any(s["step"] == "host_key" and s["status"] == "ok" for s in steps) and not (port and key and addresses):
        raise ValueError("the host_key step is ok, but the record holds no port, host key or address")
    delivery = check_delivery(record["delivery"])
    return {"v": 2, "run_id": run_id, "final": final, "ok": ok, "name": record["name"], "user": record["user"],
            "os": record["os"], "steps": steps, "tools": record["tools"], "gui": record["gui"],
            "session_type": record["session_type"], "rustdesk_id": rustdesk_id, "port": port, "host_key": key,
            "addresses": addresses, "delivery": delivery}


def check_steps(steps: object) -> list[dict]:
    if not isinstance(steps, list):
        raise ValueError("bad steps")
    seen: set[str] = set()
    for item in steps:
        if not (isinstance(item, dict) and set(item) == {"step", "status", "detail"}):
            raise ValueError(f"bad step entry {item!r}")
        if item["step"] not in STEP_IDS or item["step"] in seen:
            raise ValueError(f"unknown or repeated step {item['step']!r}")
        seen.add(item["step"])
        if item["status"] not in STEP_STATUSES:
            raise ValueError(f"bad step status {item['status']!r}")
        if not (isinstance(item["detail"], str) and len(item["detail"]) <= DETAIL_MAX):
            raise ValueError(f"bad detail for step {item['step']}")
    return steps


def check_tools(tools: object) -> None:
    if not isinstance(tools, dict) or any(
            key not in TOOL_IDS or not isinstance(value, str) or len(value) > TOOL_VERSION_MAX
            for key, value in tools.items()):
        raise ValueError("bad tools")


def check_delivery(delivery: object) -> dict | None:
    if delivery is None:
        return None
    if not (isinstance(delivery, dict) and set(delivery) == {"status", "detail"}
            and delivery["status"] in DELIVERY_STATUSES and isinstance(delivery["detail"], str)
            and len(delivery["detail"]) <= DETAIL_MAX):
        raise ValueError(f"bad delivery {delivery!r}")
    return delivery


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


def ssh_run(name: str, command: str, stdin: str | None = None) -> subprocess.CompletedProcess:
    """Run one remote command on the member and return the finished process, with text output.

    ``stdin`` goes to the remote command as bytes, so a Windows hub adds no CR to its line end. A call that gets
    no answer in SSH_TIMEOUT seconds returns exit code 255 and says so on stderr.
    """
    argv = [tool("ssh"), name, command]
    try:
        done = subprocess.run(argv, input=None if stdin is None else stdin.encode("utf-8"),
                              capture_output=True, timeout=SSH_TIMEOUT)
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(argv, 255, "", f"no answer in {SSH_TIMEOUT} s")
    return subprocess.CompletedProcess(argv, done.returncode, done.stdout.decode("utf-8", errors="replace"),
                                       done.stderr.decode("utf-8", errors="replace"))


def rustdesk_password(path: Path) -> str:
    """The member's RustDesk password from its file, made there (mode 600 on POSIX) when the file is missing.

    Raises ValueError, naming the file and never its content, when the file holds anything but a password.
    """
    if path.exists():
        password = path.read_text(encoding="ascii", errors="replace").strip()
        if not RUSTDESK_PASSWORD.match(password):
            raise ValueError(f"{path} does not hold a password (8 to 64 characters of A-Z a-z 0-9 _ -); "
                             "delete the file to make a new one")
        return password
    password = secrets.token_urlsafe(18)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as handle:
        handle.write(f"{password}\n".encode("ascii"))
    return password


def set_rustdesk_password(name: str, system: str, rustdesk_id: str) -> tuple[str, bool]:
    """Set the member's RustDesk password over SSH. Returns the text for the member's output line and a failure flag.

    The password is the one in ``~/.ssh/<name>-rustdesk-password.txt``. It reaches the member on standard input,
    and no output line, error text or command holds it.
    """
    path = ssh_dir() / f"{name}-rustdesk-password.txt"
    try:
        password = rustdesk_password(path)
        done = ssh_run(name, RUSTDESK_PASSWORD_COMMAND[system], password + "\n")
    except (OSError, ValueError) as e:
        return f", rustdesk: password not set ({e})", True
    if done.returncode != 0:
        tail = ((done.stderr or "").strip().splitlines() or ["no output"])[-1].replace(password, "***")
        return f", rustdesk: password not set (exit {done.returncode}: {tail})", True
    return f", rustdesk: id {rustdesk_id}, password in {path}", False


def run_summary(record: dict) -> str:
    """The run's result in one phrase: ok, failed: <ids of the failed steps>, or incomplete after <last step>."""
    steps = record["steps"]
    if not record["final"]:
        return f"incomplete after {steps[-1]['step']}" if steps else "incomplete before the first step"
    if record["ok"]:
        return "ok"
    failed = [s["step"] for s in steps if s["status"] == "failed"]
    return "failed: " + (", ".join(failed) or "no step named")


def delivery_summary(record: dict) -> str:
    delivery = record["delivery"]
    return f"delivery {delivery['status'] if delivery else 'none'}"


def import_records(folder: Path, test: bool) -> int:
    """Pin and connect each recorded machine. One line per record; the exit code is 1 when any record fell short.

    A v2 record counts as a failure when its run failed or stopped early, whether or not it holds a host key, and
    the delivery status never changes the result. A record without a host key is reported and skipped.
    """
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
        # v1 records have no run result: they print as before. A v2 record's line starts with its run result.
        lead = f"{name}: " if record["v"] == 1 else f"{name}: {run_summary(record)}, {delivery_summary(record)}, "
        if record["v"] == 2 and not record["ok"]:
            failed += 1
        if not (record["port"] and record["host_key"] and record["addresses"]):
            print(f"{lead}not imported, the record holds no host key")
            continue
        address = reachable(record["addresses"], record["port"])
        old = members.get(name)
        if old and old["host_key"] != record["host_key"]:
            print(f"{name}: its host key changed since the last import; the drive's key is pinned now")
        members[name] = {"os": record["os"], "user": record["user"], "port": record["port"],
                         "address": address or record["addresses"][0], "host_key": record["host_key"]}
        imported.append((name, address, lead, record.get("rustdesk_id")))
    write_text(state_path, json.dumps(members, indent=2) + "\n")
    write_text(ssh_dir() / CONFIG_NAME, render_config(members))
    write_text(ssh_dir() / "fleet_known_hosts", "".join(f"{n} {m['host_key']}\n" for n, m in sorted(members.items())))
    if include_config():
        print(f"Added '{INCLUDE}' to the top of {ssh_dir() / 'config'}")
    for name, address, lead, rustdesk_id in imported:
        if not address:
            print(f"{lead}recorded, but port {members[name]['port']} answers at none of its addresses")
            failed += 1
            continue
        result = test_connection(name, members[name]["os"]) if test else "not tested"
        # The RustDesk password is set only where the session has full access and the member reported its id.
        rustdesk, rustdesk_failed = ("", False)
        if test and result == "full access" and rustdesk_id:
            rustdesk, rustdesk_failed = set_rustdesk_password(name, members[name]["os"], rustdesk_id)
        print(f"{lead}ssh {name} -> {members[name]['user']}@{address}, {result}{rustdesk}")
        if (test and result != "full access") or rustdesk_failed:
            failed += 1
    return 1 if failed else 0


class ReceiveHandler(BaseHTTPRequestHandler):
    """The receiver's one route, ``POST /v1/usb-record``. Every other method and path gets 404."""

    server_version = "fleet-usb"
    timeout = 10  # seconds that a client may stall; the receiver answers one request at a time

    def log_message(self, format: str, *args: object) -> None:
        """No access log: a refusal prints one line to stderr (``refuse``) and an accepted record one to stdout."""

    def __getattr__(self, name: str):
        if name.startswith("do_"):  # BaseHTTPRequestHandler answers an unknown method 501; the plan says 404
            return self.answer_not_found
        raise AttributeError(name)

    def reply(self, code: int, payload: dict) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def declared_length(self) -> int | None:
        """The Content-Length header as a number, or None when it is missing or is not a plain number."""
        text = self.headers.get("Content-Length", "")
        return int(text) if text.isascii() and text.isdigit() and len(text) <= 12 else None

    def refuse(self, code: int, reason: str, drain: bool = True) -> None:
        """Answer, say so on stderr (never the token), and drop the body that the client still sends."""
        self.reply(code, {"error": reason})
        print(f"fleet-usb: refused {code} from {self.client_address[0]}: {reason}", file=sys.stderr, flush=True)
        length = self.declared_length()
        if drain and length:
            try:  # closing a socket with unread data resets the connection and can lose the answer
                self.rfile.read(min(length, DRAIN_MAX))
            except OSError:
                pass

    def answer_not_found(self) -> None:
        self.refuse(404, "no such route")

    def do_POST(self) -> None:
        if self.path != ROUTE:
            return self.refuse(404, "no such route")
        supplied = self.headers.get("X-Fleet-Token", "")
        if not hmac.compare_digest(supplied.encode("utf-8"), self.server.token.encode("ascii")):
            return self.refuse(403, "the token is missing or wrong")
        length = self.declared_length()
        if length is None or length > MAX_BODY:
            return self.refuse(413, f"Content-Length is missing or above {MAX_BODY}")
        try:
            body = self.rfile.read(length)
        except OSError:
            return self.refuse(408, "the body did not arrive in time", drain=False)
        try:
            record = self.server.take(body)
        except ValueError as e:
            return self.refuse(422, str(e)[:DETAIL_MAX])
        except OSError as e:
            return self.refuse(500, f"the record could not be stored: {e}"[:DETAIL_MAX])
        print(f"{record['name']} {record['os']}: {run_summary(record)}, rustdesk_id {record['rustdesk_id'] or 'none'}, "
              f"run_id={record['run_id']}", flush=True)
        self.reply(200, {"ok": True})


class ReceiveServer(HTTPServer):
    """Holds what the handler needs: the members folder, the token and the names written so far."""

    # On Windows, SO_REUSEADDR lets a second process take a port that is in use; on POSIX it only allows a restart.
    allow_reuse_address = os.name != "nt"

    def __init__(self, address: tuple[str, int], members: Path, token: str):
        HTTPServer.__init__(self, address, ReceiveHandler)
        self.members, self.token, self.names = members, token, set()

    def server_bind(self) -> None:
        socketserver.TCPServer.server_bind(self)  # HTTPServer's own bind looks up the bind address's name
        self.server_name, self.server_port = self.server_address[:2]

    def take(self, body: bytes) -> dict:
        """Check the body as a record (through a temp file), then move it to ``members/<name>.json``."""
        handle, tmp = tempfile.mkstemp(prefix=".recv-", suffix=".tmp", dir=self.members)
        try:
            with os.fdopen(handle, "wb") as out:
                out.write(body)
            record = read_record(Path(tmp))
            if record["v"] != 2:
                raise ValueError("the receiver takes v2 records only")
            os.replace(tmp, self.members / f"{record['name']}.json")
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise
        self.names.add(record["name"])
        return record


def receive(folder: Path, port: int, bind: str, count: int | None, timeout: float | None,
            started: Callable[[int], None] | None = None) -> int:
    """Take records over HTTP into ``<folder>/members`` until ``count`` names were written or ``timeout`` s passed.

    ``started`` is called with the port once the receiver listens (the port is chosen when ``port`` is 0). The
    exit code is 0 when it took at least one record and 1 when it took none.
    """
    token_path = ssh_dir() / TOKEN_NAME
    if not token_path.exists():
        sys.exit(f"fleet-usb: {token_path} is missing; run prepare first")
    token = read_token(token_path)
    members = folder / "members"
    members.mkdir(parents=True, exist_ok=True)
    server = ReceiveServer((bind, port), members, token)
    server.timeout = 0.25  # how often the loop looks at count and timeout
    listening = server.server_address[1]
    print(f"Listening on {bind}:{listening}, writing to {members}", flush=True)
    if started:
        started(listening)
    end = None if timeout is None else time.monotonic() + timeout
    try:
        while (count is None or len(server.names) < count) and (end is None or time.monotonic() < end):
            server.handle_request()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    print(f"received {len(server.names)}", flush=True)
    return 0 if server.names else 1


def number(kind: type, low: float, high: float | None, what: str) -> Callable[[str], float]:
    """An argparse type for a number of ``kind`` from ``low`` up to ``high`` (None: no upper limit)."""
    def parse(text: str):
        try:
            value = kind(text)
        except ValueError:
            raise argparse.ArgumentTypeError(f"{what} must be a number, not {text!r}") from None
        if value < low or (high is not None and value > high):
            limit = f" and {high} or less" if high is not None else ""
            raise argparse.ArgumentTypeError(f"{what} must be {low} or more{limit}")
        return value
    return parse


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("prepare", help="Copy the hub's public key and the member scripts to a folder on the drive")
    p.add_argument("folder", type=Path)
    p.add_argument("--hub-url", action="append", metavar="URL",
                   help=f"A URL where members send their record (repeatable); the default is http://<address>:"
                        f"{RECEIVE_PORT} for each address of this machine")
    p.add_argument("--rustdesk-host", metavar="HOST",
                   help="The RustDesk ID server that members use (a name or address, optional :port); saved in "
                        f"~/.ssh/{RUSTDESK_SAVED}, so later runs can leave it out")
    key_group = p.add_mutually_exclusive_group()
    key_group.add_argument("--rustdesk-key", metavar="KEY", help="The ID server's public key (saved with the host)")
    key_group.add_argument("--rustdesk-key-file", metavar="FILE", type=Path,
                           help="A file that holds the ID server's public key (id_ed25519.pub)")
    r = sub.add_parser("receive", help="Take the records that members send over the network")
    r.add_argument("folder", type=Path)
    r.add_argument("--port", type=number(int, 0, 65535, "--port"), default=RECEIVE_PORT)
    r.add_argument("--bind", default="0.0.0.0")
    r.add_argument("--count", type=number(int, 1, None, "--count"), help="Stop after this many machines")
    r.add_argument("--timeout", type=number(float, 0.001, None, "--timeout"), help="Stop after this many seconds")
    i = sub.add_parser("import", help="Pin and connect each machine recorded on the drive")
    i.add_argument("folder", type=Path)
    i.add_argument("--no-test", action="store_true", help="Write the SSH entries without connecting")
    args = parser.parse_args(argv)
    if args.command == "prepare":
        return prepare(args.folder, args.hub_url, args.rustdesk_host, args.rustdesk_key, args.rustdesk_key_file)
    if args.command == "receive":
        return receive(args.folder, args.port, args.bind, args.count, args.timeout)
    return import_records(args.folder, test=not args.no_test)


if __name__ == "__main__":
    sys.exit(main())
