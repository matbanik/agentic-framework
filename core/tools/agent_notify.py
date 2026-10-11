"""Stop notifier — email the human when an agent session stops.

Purpose
-------
A long agent session can stop for many reasons: it finished, it needs a
decision, it waits for a permission prompt, it hit a hard stop, or the harness
failed. This module sends one short email for each such stop so the human does
not have to watch the terminal. It is the single implementation behind every
harness: the Claude Code stop gate calls ``on_stop``; the ``Notification`` and
``StopFailure`` hooks, Codex ``notify`` and the Cursor ``stop`` hook call the
``hook`` action; other harnesses call ``send`` by hand.

The module uses the Python standard library only, has no project name, drive
letter or address in it, and ships byte-identical in the framework template.

Settings (the notify home)
--------------------------
The notify home is the first that is set: ``--home``, ``AGENT_NOTIFY_HOME``,
``$AGENT_MODEL_REGISTRY_HOME/notify``, ``~/.agent/notify``. It holds:

- ``notify.json`` — committed defaults (no address, ``enabled`` false);
- ``notify.local.json`` — this machine's addresses and ``enabled``;
- ``notify.off`` — an empty file whose presence turns every email off;
- ``state/`` — the log, the delivery ledger, pending files and the dry-run
  outbox.

The SMTP password is never in a file: ``setup`` stores it in the Windows
Credential Manager (generic credential ``agent-notify:smtp:<user>``), else in
``keyring``; the env variable ``AGENT_NOTIFY_SMTP_PASSWORD`` is the last
fallback. The env variable ``AGENT_NOTIFY=off`` turns everything off (every
dispatched child session sets it).

Classes and suppression
-----------------------
Each stop gets one class of ``STOP_CLASSES`` from the first matching rule of
``classify_explain``. The off switches write nothing at all. After them, the
event and class switches, the per-session gap, the dedupe window, the hourly
and daily caps, the authentication backoff and a missing credential each skip
the send and write one log line naming the limit.

Actions (``python agent_notify.py <action>``)
---------------------------------------------
``hook``, ``deliver``, ``send``, ``test-send``, ``setup`` and ``status``; see
``_parser``. ``hook`` and ``deliver`` never print on stdout and always exit 0.
"""

from __future__ import annotations

import argparse
import contextlib
import copy
import datetime as _dt
import email.policy
import email.utils
import getpass
import hashlib
import importlib
import json
import os
import re
import smtplib
import ssl
import subprocess
import sys
import threading
import time
import types
from email.message import EmailMessage
from pathlib import Path

STOP_CLASSES = ("done", "decision", "approval", "waiting", "blocked", "error")
GAP_BYPASS_CLASSES = ("done", "decision", "blocked", "error")

# Probe-1 (task.md Probe Record, 2026-10-10): a detached child of the Stop hook
# survives the hook's exit, so the stop gate hands delivery to a child process.
DELIVERY_MODE = "detached"
DELIVERY_BUDGET_S = 8
LOCK_WAIT_S: float = 2
LOCK_STALE_S = 30
LOCK_NAME = "state.lock"
OUTCOME_LOCK_WAIT_S = 0.5
DETACHED_PROCESS = 0x00000008
CREATE_NO_WINDOW = 0x08000000
PENDING_STALE_S = 600
LEDGER_RETENTION_S = 25 * 3600
BODY_CAP_BYTES = 2048
TEXT_CAP_CHARS = 64 * 1024
TRANSCRIPT_TAIL_BYTES = 64 * 1024
GIT_TIMEOUT_S = 2.0
# The real working directory of a detached ``deliver`` worker. Notes and
# pending files hold only the masked directory (R2-F1), so the worker gets
# the real one from its process environment and uses it for git only.
WORKDIR_ENV = "AGENT_NOTIFY_WORKDIR"
CRED_TARGET_PREFIX = "agent-notify:smtp:"
KEYRING_SERVICE = "agent-notify:smtp"
CRED_TYPE_GENERIC = 1
CRED_PERSIST_LOCAL_MACHINE = 2

EVENT_KEYS = ("stop", "permission_prompt", "idle_prompt", "stop_failure")
SMTP_KEYS = ("host", "port", "starttls", "user", "timeout_s")

# Mirrors the schema file notify.v1.schema.json at every level (pinned by test).
CONFIG_KEYS: dict[str, tuple[str, ...] | None] = {
    "version": None,
    "enabled": None,
    "events": EVENT_KEYS,
    "classes": STOP_CLASSES,
    "smtp": SMTP_KEYS,
    "from": None,
    "to": None,
    "subject_prefix": None,
    "excerpt_chars": None,
    "min_gap_s": None,
    "dedupe_window_s": None,
    "auth_backoff_s": None,
    "hourly_cap": None,
    "daily_cap": None,
    "dry_run": None,
    "log_dir": None,
}

DEFAULTS: dict[str, object] = {
    "version": 1,
    "enabled": False,
    "events": {
        "stop": True,
        "permission_prompt": True,
        "idle_prompt": False,
        "stop_failure": True,
    },
    "classes": {name: True for name in STOP_CLASSES},
    "smtp": {
        "host": "smtp.gmail.com",
        "port": 587,
        "starttls": True,
        "user": None,
        "timeout_s": 5,
    },
    "from": None,
    "to": None,
    "subject_prefix": "[agent]",
    "excerpt_chars": 600,
    "min_gap_s": 300,
    "dedupe_window_s": 120,
    "auth_backoff_s": 1800,
    "hourly_cap": 20,
    "daily_cap": 200,
    "dry_run": False,
    "log_dir": None,
}

_INT_RANGES: dict[str, tuple[int, int]] = {
    "version": (1, 1),
    "excerpt_chars": (0, 2000),
    "min_gap_s": (0, 86400),
    "dedupe_window_s": (0, 86400),
    "auth_backoff_s": (0, 86400),
    "hourly_cap": (1, 100),
    "daily_cap": (1, 1000),
    "smtp.port": (1, 65535),
    "smtp.timeout_s": (1, 30),
}
_BOOL_KEYS = frozenset(
    {"enabled", "dry_run", "smtp.starttls"}
    | {f"events.{k}" for k in EVENT_KEYS}
    | {f"classes.{k}" for k in STOP_CLASSES}
)
_REQUIRED_WHEN_ENABLED = ("to", "from", "smtp.user")
_SUBJECT_PREFIX_MAX = 20
_TO_MAX = 5

_CHECKPOINT_RE = re.compile(
    r"Checkpoint saved for \S+?\. Status: ([A-Za-z][A-Za-z-]*)\."
)
_COMPLETED_RE = re.compile(r"^\s*\U0001f550\s*Completed:")
_SECRET_KEYS = (
    r"smtp[_-]?password|app[_-]?password|client[_-]?secret|access[_-]?key"
    r"|api[_-]?key|password|passwd|pwd|secret|token"
)
_R1_AUTH_HEADER = re.compile(
    r"(?im)\b(proxy-authorization|authorization)\s*[:=]\s*[^\r\n]*"
)
_R2_SCHEME_TOKEN = re.compile(
    r"(?i)\b(bearer|basic|token)\s+(?!\[redacted\])[A-Za-z0-9._~+/=-]{8,}"
)
_R3_QUOTED = re.compile(
    r"(?i)([\"']?)(?<![A-Za-z0-9])(" + _SECRET_KEYS + r")\1(\s*[:=]\s*)"
    r"(\"[^\"\n]*\"|'[^'\n]*')"
)
_R4_UNQUOTED = re.compile(
    r"(?i)(?<![A-Za-z0-9])(" + _SECRET_KEYS + r")\s*[:=]\s*"
    r"(?!\[redacted\]|\"\[redacted\]\")[^\r\n,;}]+"
)
_R5_APP_PASSWORD = re.compile(r"\b[a-z]{4}( [a-z]{4}){3}\b")
_R6_LONG_RUN = re.compile(r"[A-Za-z0-9+/=]{32,}")
_ADDRESS = re.compile(r"[A-Za-z0-9._%+'-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+")
_UNSAFE_NAME = re.compile(r"[^A-Za-z0-9-]")
_WHITESPACE = re.compile(r"\s+")

_CURSOR_STATUS = {"completed": "done", "aborted": "waiting", "error": "error"}


class ConfigError(Exception):
    """A notify config file has an unknown key, a wrong type or an out-of-range value."""

    def __init__(self, file: str, key: str) -> None:
        super().__init__(f"{file}: {key}")
        self.file = file
        self.key = key


class _Ctx:
    """The resolved notify home, its merged config and its state directory."""

    def __init__(self, home: Path, cfg: dict[str, object]) -> None:
        self.home = home
        self.cfg = cfg
        log_dir = cfg.get("log_dir")
        self.state = (
            Path(log_dir) if isinstance(log_dir, str) and log_dir else home / "state"
        )


# ── Small helpers ───────────────────────────────────────────────────────


def _now() -> float:
    """Wall-clock seconds; one seam for the ledger, pending ages and timestamps."""
    return time.time()


def _iso(t: float) -> str:
    return _dt.datetime.fromtimestamp(t, _dt.timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def _stamp(t: float) -> str:
    return _dt.datetime.fromtimestamp(t, _dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _block(cfg: dict[str, object], name: str) -> dict[str, object]:
    value = cfg.get(name)
    return value if isinstance(value, dict) else {}


def _int(cfg: dict[str, object], name: str) -> int:
    value = cfg.get(name)
    if isinstance(value, bool) or not isinstance(value, int):
        default = DEFAULTS[name]
        return default if isinstance(default, int) else 0
    return value


def _str_or_none(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _dotted(cfg: dict[str, object], key: str) -> object:
    if "." in key:
        block, sub = key.split(".", 1)
        return _block(cfg, block).get(sub)
    return cfg.get(key)


def _to_list(cfg: dict[str, object]) -> list[str]:
    value = cfg.get("to")
    if isinstance(value, list):
        return [a for a in value if isinstance(a, str) and a]
    return []


def _warn(text: str) -> None:
    """One line on stderr; never on stdout, which a hook host may read as a decision."""
    with contextlib.suppress(OSError, ValueError, AttributeError):
        sys.stderr.write(f"agent_notify: {text}\n")


def _open_excl(path: Path) -> int:
    return os.open(
        path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0), 0o600
    )


def _write_new(directory: Path, names: list[str], data: bytes) -> Path:
    """Write ``data`` to the first of ``names`` that does not exist yet."""
    directory.mkdir(parents=True, exist_ok=True)
    for name in names:
        path = directory / name
        try:
            fd = _open_excl(path)
        except FileExistsError:
            continue
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        return path
    raise OSError(f"no free file name in {directory}")


def _unique_names(stem: str, suffix: str, insert_before: str = "") -> list[str]:
    tail = f"-{insert_before}" if insert_before else ""
    return [f"{stem}{tail}{suffix}"] + [
        f"{stem}-{n}{tail}{suffix}" for n in range(1, 100)
    ]


# ── Home and config ─────────────────────────────────────────────────────


def resolve_home(arg: str | None) -> Path:
    """The notify home: ``--home``, AGENT_NOTIFY_HOME, the registry home's ``notify``, ``~/.agent/notify``."""
    if arg:
        return Path(arg)
    env_home = os.environ.get("AGENT_NOTIFY_HOME")
    if env_home:
        return Path(env_home)
    registry = os.environ.get("AGENT_MODEL_REGISTRY_HOME")
    if registry:
        return Path(registry) / "notify"
    return Path(os.path.expanduser("~")) / ".agent" / "notify"


def _check_value(file: str, key: str, value: object) -> None:
    """Raise ConfigError when ``value`` does not fit the schema rule of ``key``."""
    if key in _BOOL_KEYS:
        if not isinstance(value, bool):
            raise ConfigError(file, key)
        return
    if key in _INT_RANGES:
        low, high = _INT_RANGES[key]
        if (
            isinstance(value, bool)
            or not isinstance(value, int)
            or not low <= value <= high
        ):
            raise ConfigError(file, key)
        return
    if key in ("from", "smtp.host", "smtp.user"):
        if not isinstance(value, str) or not value:
            raise ConfigError(file, key)
        return
    if key == "subject_prefix":
        if not isinstance(value, str) or len(value) > _SUBJECT_PREFIX_MAX:
            raise ConfigError(file, key)
        return
    if key == "log_dir":
        if value is not None and (not isinstance(value, str) or not value):
            raise ConfigError(file, key)
        return
    if key == "to":
        if (
            not isinstance(value, list)
            or not 1 <= len(value) <= _TO_MAX
            or not all(isinstance(a, str) and a for a in value)
        ):
            raise ConfigError(file, key)
        return
    raise ConfigError(file, key)


def load_config(home: Path) -> dict[str, object]:
    """Defaults, then ``notify.json``, then ``notify.local.json`` (one level deep for nested blocks)."""
    cfg = copy.deepcopy(DEFAULTS)
    last: str | None = None
    for name in ("notify.json", "notify.local.json"):
        path = home / name
        if not path.is_file():
            continue
        last = name
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise ConfigError(name, "<json>") from exc
        if not isinstance(doc, dict):
            raise ConfigError(name, "<root>")
        for key, value in doc.items():
            if key not in CONFIG_KEYS:
                raise ConfigError(name, str(key))
            subkeys = CONFIG_KEYS[key]
            if subkeys is None:
                _check_value(name, key, value)
                cfg[key] = value
                continue
            if not isinstance(value, dict):
                raise ConfigError(name, key)
            for sub, sub_value in value.items():
                dotted = f"{key}.{sub}"
                if sub not in subkeys:
                    raise ConfigError(name, dotted)
                _check_value(name, dotted, sub_value)
            target = cfg.get(key)
            if isinstance(target, dict):
                target.update(value)
    if last is None:
        raise ConfigError("notify.json", "<missing>")
    if cfg.get("enabled") is True:
        for key in _REQUIRED_WHEN_ENABLED:
            if _dotted(cfg, key) is None:
                raise ConfigError(last, key)
    return cfg


def _kill_switch(home: Path) -> str | None:
    if os.environ.get("AGENT_NOTIFY", "").strip().lower() == "off":
        return "env AGENT_NOTIFY=off"
    if (home / "notify.off").exists():
        return "notify.off"
    return None


def _open(home_arg: str | None, ignore_enabled: bool = False) -> _Ctx | None:
    """Apply the off switches and load the config; None means "send nothing"."""
    if os.environ.get("AGENT_NOTIFY", "").strip().lower() == "off":
        return None
    home = resolve_home(home_arg)
    if not (home / "notify.json").is_file():
        return None
    if (home / "notify.off").exists():
        return None
    try:
        cfg = load_config(home)
    except ConfigError as exc:
        _log(
            home / "state",
            {"outcome": "config_invalid", "file": exc.file, "key": exc.key},
        )
        return None
    if cfg.get("enabled") is not True and not ignore_enabled:
        return None
    return _Ctx(home, cfg)


# ── Log ─────────────────────────────────────────────────────────────────


def _log(state: Path, fields: dict[str, object]) -> None:
    """Append one JSON line to ``notify.log.jsonl``; it never holds an address or the excerpt."""
    line = {"ts": _iso(_now()), **fields}
    data = (json.dumps(line, ensure_ascii=False) + "\n").encode("utf-8")
    try:
        state.mkdir(parents=True, exist_ok=True)
        flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND | getattr(os, "O_BINARY", 0)
        fd = os.open(state / "notify.log.jsonl", flags, 0o600)
        try:
            os.write(fd, data)
        finally:
            os.close(fd)
    except OSError as exc:
        _warn(f"log write failed ({type(exc).__name__})")


def _line(note: dict[str, object], outcome: str, **extra: object) -> dict[str, object]:
    session = note.get("session")
    return {
        "outcome": outcome,
        "event": note.get("event"),
        "class": note.get("class"),
        "rule": note.get("rule"),
        "session8": session[:8] if isinstance(session, str) else None,
        "harness": note.get("harness"),
        **extra,
    }


def _skip(
    ctx: _Ctx,
    note: dict[str, object],
    outcome: str,
    limit_name: str,
    configured: object,
    observed: object,
    window: object,
) -> str:
    _log(
        ctx.state,
        _line(
            note,
            outcome,
            limit_name=limit_name,
            configured_value=configured,
            observed_value=observed,
            window=window,
        ),
    )
    return outcome


# ── Classifier ──────────────────────────────────────────────────────────


def _transcript_text(path: Path) -> str:
    """The text of the last assistant entry with text in the tail of a JSONL transcript."""
    try:
        with path.open("rb") as fh:
            fh.seek(0, os.SEEK_END)
            size = fh.tell()
            fh.seek(max(0, size - TRANSCRIPT_TAIL_BYTES))
            tail = fh.read().decode("utf-8", errors="replace")
    except OSError:
        return ""
    for raw in reversed(tail.splitlines()):
        try:
            entry = json.loads(raw)
        except ValueError:
            continue
        if not isinstance(entry, dict) or entry.get("type") != "assistant":
            continue
        message = entry.get("message")
        content = message.get("content") if isinstance(message, dict) else None
        if isinstance(content, str):
            text = content
        elif isinstance(content, list):
            text = "\n".join(
                part["text"]
                for part in content
                if isinstance(part, dict)
                and part.get("type") == "text"
                and isinstance(part.get("text"), str)
            )
        else:
            text = ""
        if text.strip():
            return text
    return ""


def _assistant_text(payload: dict[str, object]) -> str:
    """``last_assistant_message`` when non-empty, else the transcript's last assistant text."""
    value = payload.get("last_assistant_message")
    if isinstance(value, str) and value.strip():
        return value[-TEXT_CAP_CHARS:]
    transcript = payload.get("transcript_path")
    if isinstance(transcript, str) and transcript:
        return _transcript_text(Path(transcript))[-TEXT_CAP_CHARS:]
    return ""


def classify_explain(
    event: str, payload: object, gate: dict[str, object] | None
) -> tuple[str, int]:
    """Return ``(class, rule)`` for a stop; the first matching rule wins (plan Component A item 3)."""
    data = payload if isinstance(payload, dict) else {}
    if event == "StopFailure":
        return "error", 1
    if event == "Notification":
        kind = data.get("notification_type")
        if kind == "permission_prompt":
            return "approval", 2
        if kind == "idle_prompt":
            return "waiting", 3
    signal = gate if isinstance(gate, dict) else {}
    if signal.get("decision") == "release":
        return "blocked", 4
    if signal.get("kind") == "released":
        reason = signal.get("release_reason")
        if reason in ("round-cap", "reviewer-unavailable"):
            return "blocked", 5
        if reason in ("human-gate", "handback"):
            return "decision", 6
    if signal.get("kind") == "rows_complete":
        return "done", 7
    text = _assistant_text(data)
    statuses = _CHECKPOINT_RE.findall(text)
    if statuses:
        status = statuses[-1].lower()
        if status == "blocked":
            return "blocked", 8
        if status in ("ready-for-review", "complete"):
            return "done", 8
    if ("⛔" in text and "HARD STOP" in text) or "rounds without approval" in text:
        return "blocked", 9
    lines = [
        line.strip()
        for line in text.splitlines()
        if line.strip() and not _COMPLETED_RE.match(line)
    ]
    if lines and lines[-1].endswith("?"):
        return "waiting", 10
    return "waiting", 11


def classify(event: str, payload: object, gate: dict[str, object] | None) -> str:
    """The class of a stop (see ``classify_explain``)."""
    return classify_explain(event, payload, gate)[0]


# ── Redaction and masking ───────────────────────────────────────────────


def redact(text: str) -> str:
    """Remove secret values (rules r1–r6); the key names stay so the reader sees what was removed."""
    out = _R1_AUTH_HEADER.sub(r"\1: [redacted]", text)
    out = _R2_SCHEME_TOKEN.sub(r"\1 [redacted]", out)
    out = _R3_QUOTED.sub(lambda m: f'{m[1]}{m[2]}{m[1]}{m[3]}"[redacted]"', out)
    out = _R4_UNQUOTED.sub(r"\1=[redacted]", out)
    out = _R5_APP_PASSWORD.sub("[redacted]", out)
    return _R6_LONG_RUN.sub("[redacted]", out)


def excerpt(text: str, n: int) -> str:
    """The last ``n`` characters of ``text`` (the end of a reply holds the question or the result)."""
    if n <= 0:
        return ""
    return text[-n:]


def mask_address(address: str) -> str:
    """``first-char***@first-domain-char***``; the only form of an address outside a sent message."""
    local, sep, domain = address.strip().partition("@")
    if not sep:
        return f"{local[:1]}***" if local else "***"
    return f"{local[:1]}***@{domain[:1]}***"


def _known_addresses(cfg: dict[str, object]) -> list[str]:
    """The configured sender, recipients and SMTP identity that hold an ``@``."""
    found = [
        _str_or_none(cfg.get("from")),
        _str_or_none(_block(cfg, "smtp").get("user")),
    ]
    found.extend(_to_list(cfg))
    return [a.strip() for a in found if a and "@" in a]


def mask_addresses(text: str, known: list[str] | None = None) -> str:
    """``text`` with every address masked: the ``known`` ones in any letter case, then any address-shaped run."""
    out = text
    for address in sorted(set(known or ()), key=len, reverse=True):
        masked = mask_address(address)
        out = re.sub(re.escape(address), lambda _m: masked, out, flags=re.IGNORECASE)
    return _ADDRESS.sub(lambda m: mask_address(m.group(0)), out)


# ── Credentials ─────────────────────────────────────────────────────────


def _cred_api() -> types.SimpleNamespace:
    """ctypes bindings for advapi32 CredReadW / CredWriteW / CredFree (Windows only)."""
    import ctypes
    from ctypes import wintypes

    class FILETIME(ctypes.Structure):
        _fields_ = [
            ("dwLowDateTime", wintypes.DWORD),
            ("dwHighDateTime", wintypes.DWORD),
        ]

    class CREDENTIALW(ctypes.Structure):
        _fields_ = [
            ("Flags", wintypes.DWORD),
            ("Type", wintypes.DWORD),
            ("TargetName", wintypes.LPWSTR),
            ("Comment", wintypes.LPWSTR),
            ("LastWritten", FILETIME),
            ("CredentialBlobSize", wintypes.DWORD),
            ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)),
            ("Persist", wintypes.DWORD),
            ("AttributeCount", wintypes.DWORD),
            ("Attributes", ctypes.c_void_p),
            ("TargetAlias", wintypes.LPWSTR),
            ("UserName", wintypes.LPWSTR),
        ]

    advapi = getattr(ctypes, "WinDLL")("advapi32", use_last_error=True)
    read = advapi.CredReadW
    read.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.POINTER(ctypes.POINTER(CREDENTIALW)),
    ]
    read.restype = wintypes.BOOL
    write = advapi.CredWriteW
    write.argtypes = [ctypes.POINTER(CREDENTIALW), wintypes.DWORD]
    write.restype = wintypes.BOOL
    free = advapi.CredFree
    free.argtypes = [ctypes.c_void_p]
    free.restype = None
    return types.SimpleNamespace(
        ctypes=ctypes, CREDENTIALW=CREDENTIALW, read=read, write=write, free=free
    )


def _cred_read(target: str) -> str | None:
    """The generic credential ``target`` from the Windows Credential Manager, else None."""
    if os.name != "nt":
        return None
    try:
        api = _cred_api()
        ctypes = api.ctypes
        pcred = ctypes.POINTER(api.CREDENTIALW)()
        if not api.read(target, CRED_TYPE_GENERIC, 0, ctypes.byref(pcred)):
            return None
        try:
            cred = pcred.contents
            blob = ctypes.string_at(cred.CredentialBlob, cred.CredentialBlobSize)
            return blob.decode("utf-16-le") or None
        finally:
            api.free(pcred)
    except (OSError, AttributeError, ValueError, UnicodeDecodeError):
        return None


def _keyring() -> types.ModuleType | None:
    try:
        return importlib.import_module("keyring")
    except ImportError:
        return None


def _cred_write(target: str, user: str, password: str) -> bool:
    """Store the password: Windows Credential Manager on Windows, else ``keyring``."""
    if os.name == "nt":
        try:
            api = _cred_api()
            ctypes = api.ctypes
            blob = password.encode("utf-16-le")
            buffer = (ctypes.c_ubyte * len(blob)).from_buffer_copy(blob)
            cred = api.CREDENTIALW()
            cred.Type = CRED_TYPE_GENERIC
            cred.TargetName = target
            cred.UserName = user
            cred.CredentialBlobSize = len(blob)
            cred.CredentialBlob = ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte))
            cred.Persist = CRED_PERSIST_LOCAL_MACHINE
            return bool(api.write(ctypes.byref(cred), 0))
        except (OSError, AttributeError, ValueError):
            return False
    keyring = _keyring()
    if keyring is None:
        return False
    try:
        keyring.set_password(KEYRING_SERVICE, user, password)
    except Exception as exc:  # noqa: BLE001 - keyring backends raise their own error types
        _warn(f"keyring store failed ({type(exc).__name__})")
        return False
    return True


def load_password(user: str | None) -> str | None:
    """Credential store, then ``keyring``, then env AGENT_NOTIFY_SMTP_PASSWORD; first found wins."""
    if user:
        stored = _cred_read(CRED_TARGET_PREFIX + user)
        if stored:
            return stored
        keyring = _keyring()
        if keyring is not None:
            try:
                value = keyring.get_password(KEYRING_SERVICE, user)
            except Exception:  # noqa: BLE001 - keyring backends raise their own error types
                value = None
            if isinstance(value, str) and value:
                return value
    env_value = os.environ.get("AGENT_NOTIFY_SMTP_PASSWORD")
    return env_value or None


# ── Notes (one stop, ready to deliver) ──────────────────────────────────


def _workdir(payload: dict[str, object]) -> str:
    """The real working directory of a stop; never stored, used only to ask git for the branch."""
    cwd = payload.get("cwd")
    return cwd if isinstance(cwd, str) and cwd else os.getcwd()


def _make_note(
    ctx: _Ctx,
    *,
    harness: str,
    event: str,
    event_key: str | None,
    payload: dict[str, object],
    cls: str,
    rule: object,
    reason: str = "",
    task_file: str | None = None,
    open_rows: int | None = None,
) -> dict[str, object]:
    """Everything delivery needs; addresses are masked in every string, secrets redacted in the excerpt and reason."""
    known = _known_addresses(ctx.cfg)
    session = payload.get("session_id")
    text = _assistant_text(payload).strip()
    clean = redact(mask_addresses(text, known))
    short = excerpt(clean, _int(ctx.cfg, "excerpt_chars"))
    session_value = session if isinstance(session, str) and session else "unknown"
    return {
        "harness": harness,
        "event": event,
        "event_key": event_key,
        "session": mask_addresses(session_value, known),
        "cwd": mask_addresses(_workdir(payload), known),
        "excerpt": short,
        "truncated": len(short) < len(clean),
        "reason": redact(mask_addresses(reason or "", known)),
        "task_file": mask_addresses(task_file, known) if task_file else task_file,
        "open_rows": open_rows,
        "class": cls,
        "rule": rule,
    }


def _digest(note: dict[str, object]) -> str:
    """The dedupe digest; its own ledger field, never passed through redaction."""
    data = f"{note.get('class')}\n{note.get('excerpt')}".encode()
    return hashlib.sha256(data).hexdigest()[:16]


# ── State: lock, ledger, backoff ────────────────────────────────────────


def _lock_acquire(state: Path, wait_s: float) -> bool:
    """Take ``state.lock`` with O_CREAT|O_EXCL; a lock older than LOCK_STALE_S is removed."""
    lock = state / LOCK_NAME
    deadline = time.monotonic() + wait_s
    while True:
        try:
            fd = _open_excl(lock)
        except (FileExistsError, PermissionError):
            try:
                if time.time() - lock.stat().st_mtime > LOCK_STALE_S:
                    lock.unlink()
                    continue
            except FileNotFoundError:
                continue
            except OSError:
                pass
            if time.monotonic() >= deadline:
                return False
            time.sleep(0.02)
            continue
        with contextlib.suppress(OSError):
            os.write(fd, str(os.getpid()).encode())
        os.close(fd)
        return True


def _lock_release(state: Path) -> None:
    with contextlib.suppress(FileNotFoundError):
        (state / LOCK_NAME).unlink()


def _read_ledger(state: Path, now: float) -> list[dict[str, object]]:
    path = state / "sent.jsonl"
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return []
    except OSError as exc:
        _warn(f"ledger read failed ({type(exc).__name__})")
        return []
    out: list[dict[str, object]] = []
    for line in raw.splitlines():
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        t = entry.get("t") if isinstance(entry, dict) else None
        if isinstance(t, (int, float)) and now - t < LEDGER_RETENTION_S:
            out.append(entry)
    return out


def _write_ledger(state: Path, entries: list[dict[str, object]]) -> None:
    path = state / "sent.jsonl"
    tmp = state / f"sent.jsonl.{os.getpid()}.{threading.get_ident()}.tmp"
    data = "".join(json.dumps(e, ensure_ascii=False) + "\n" for e in entries)
    tmp.write_text(data, encoding="utf-8")
    os.replace(tmp, path)


def _append_outcome(state: Path, note: dict[str, object], outcome: str) -> None:
    """The delivery outcome as its own ledger line, under a short best-effort lock."""
    if not _lock_acquire(state, OUTCOME_LOCK_WAIT_S):
        return
    try:
        line = {
            "t": _now(),
            "kind": "outcome",
            "session": note.get("session"),
            "outcome": outcome,
        }
        flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND | getattr(os, "O_BINARY", 0)
        fd = os.open(state / "sent.jsonl", flags, 0o600)
        try:
            os.write(fd, (json.dumps(line, ensure_ascii=False) + "\n").encode("utf-8"))
        finally:
            os.close(fd)
    except OSError as exc:
        _warn(f"ledger append failed ({type(exc).__name__})")
    finally:
        _lock_release(state)


def _backoff_since(state: Path) -> float | None:
    try:
        doc = json.loads((state / "backoff.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    t = doc.get("t") if isinstance(doc, dict) else None
    return float(t) if isinstance(t, (int, float)) and not isinstance(t, bool) else None


def _write_backoff(state: Path) -> None:
    try:
        tmp = state / f"backoff.json.{os.getpid()}.tmp"
        tmp.write_text(json.dumps({"t": _now()}), encoding="utf-8")
        os.replace(tmp, state / "backoff.json")
    except OSError as exc:
        _warn(f"backoff write failed ({type(exc).__name__})")


def _ledger_skip(
    ctx: _Ctx,
    note: dict[str, object],
    entries: list[dict[str, object]],
    now: float,
    test: bool,
) -> str | None:
    """Gap, dedupe, hourly and daily checks against the ledger; the skip outcome or None."""
    cfg = ctx.cfg
    cls = note.get("class")
    session = note.get("session")
    attempted = [
        e
        for e in entries
        if e.get("kind") == "attempted" and isinstance(e.get("t"), (int, float))
    ]

    def age(e: dict[str, object]) -> float:
        t = e.get("t")
        return now - float(t) if isinstance(t, (int, float)) else float("inf")

    if not test and cls not in GAP_BYPASS_CLASSES:
        gap = _int(cfg, "min_gap_s")
        same = [age(e) for e in attempted if e.get("session") == session]
        if same and min(same) < gap:
            return _skip(
                ctx, note, "min_gap", "min_gap_s", gap, int(min(same)), "session"
            )
    if not test:
        window = _int(cfg, "dedupe_window_s")
        digest = _digest(note)
        hits = [
            age(e)
            for e in attempted
            if e.get("session") == session
            and e.get("class") == cls
            and e.get("digest") == digest
            and age(e) < window
        ]
        if hits:
            return _skip(
                ctx,
                note,
                "dedupe",
                "dedupe_window_s",
                window,
                int(min(hits)),
                "session+class",
            )
    hourly = _int(cfg, "hourly_cap")
    in_hour = sum(1 for e in attempted if age(e) < 3600)
    if in_hour >= hourly:
        return _skip(ctx, note, "hourly_cap", "hourly_cap", hourly, in_hour, "3600s")
    daily = _int(cfg, "daily_cap")
    in_day = sum(1 for e in attempted if age(e) < 86400)
    if in_day >= daily:
        return _skip(ctx, note, "daily_cap", "daily_cap", daily, in_day, "86400s")
    return None


def _backoff_skip(ctx: _Ctx, note: dict[str, object], now: float) -> str | None:
    since = _backoff_since(ctx.state)
    window = _int(ctx.cfg, "auth_backoff_s")
    if since is not None and now - since < window:
        return _skip(
            ctx,
            note,
            "auth_backoff",
            "auth_backoff_s",
            window,
            int(now - since),
            "global",
        )
    return None


# ── Message ─────────────────────────────────────────────────────────────


def _git_branch(cwd: str, deadline: float) -> str:
    remaining = min(GIT_TIMEOUT_S, deadline - time.monotonic())
    if remaining <= 0:
        return "unknown"
    try:
        result = subprocess.run(
            ["git", "-C", cwd, "rev-parse", "--abbrev-ref", "HEAD"],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=remaining,
            creationflags=CREATE_NO_WINDOW if os.name == "nt" else 0,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    branch = result.stdout.strip()
    if result.returncode != 0 or not branch:
        return "unknown"
    return _WHITESPACE.sub("-", branch)


def _body(
    ctx: _Ctx, note: dict[str, object], branch: str, t: float
) -> tuple[str, bool]:
    """The plain-text body, at most BODY_CAP_BYTES; the excerpt is cut from the front to fit."""
    cwd = str(note.get("cwd") or "")
    project = Path(cwd).name or "unknown"
    session = str(note.get("session") or "")
    lines = [
        f"Project: {project}",
        f"Directory: {cwd}",
        f"Branch: {branch}",
        f"Harness: {note.get('harness')}",
        f"Session: {session[:8]}",
        f"Class: {note.get('class')}",
    ]
    reason = note.get("reason")
    if isinstance(reason, str) and reason:
        lines.append(f"Reason: {reason}")
    task_file = note.get("task_file")
    if isinstance(task_file, str) and task_file:
        lines.append(f"Task: {task_file}")
        lines.append(f"Open rows: {note.get('open_rows')}")
    when = _dt.datetime.fromtimestamp(t).astimezone().strftime("%Y-%m-%d %H:%M %z")
    lines.append(f"Time: {when}")
    lines.append(f"Log: {ctx.state / 'notify.log.jsonl'}")
    head = "\n".join(lines) + "\n\n"
    text = str(note.get("excerpt") or "")
    truncated = bool(note.get("truncated"))
    budget = (
        BODY_CAP_BYTES - 1 - len(head.encode("utf-8"))
    )  # set_content adds a final newline
    if budget < 0:
        head = head.encode("utf-8")[: BODY_CAP_BYTES - 1].decode(
            "utf-8", errors="ignore"
        )
        return head, True
    raw = text.encode("utf-8")
    if len(raw) > budget:
        text = raw[len(raw) - budget :].decode("utf-8", errors="ignore")
        truncated = True
    return head + text, truncated


def _message(
    ctx: _Ctx, note: dict[str, object], branch: str, *, masked: bool, test: bool
) -> tuple[EmailMessage, bool]:
    cfg = ctx.cfg
    t = _now()
    cwd = str(note.get("cwd") or "")
    project = _WHITESPACE.sub("-", Path(cwd).name or "unknown")
    hhmm = _dt.datetime.fromtimestamp(t).strftime("%H:%M")
    prefix = cfg.get("subject_prefix")
    subject = f"{prefix if isinstance(prefix, str) else '[agent]'} {project} | {str(note.get('class')).upper()} | {branch} | {hhmm}"
    if test:
        subject += " (test)"
    sender = _str_or_none(cfg.get("from")) or ""
    recipients = _to_list(cfg)
    body, truncated = _body(ctx, note, branch, t)
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = mask_address(sender) if masked else sender
    msg["To"] = ", ".join(mask_address(a) if masked else a for a in recipients)
    msg["Date"] = email.utils.formatdate(t, localtime=True)
    msg.set_content(body)
    return msg, truncated


def _write_eml(ctx: _Ctx, msg: EmailMessage, cls: str) -> Path:
    data = msg.as_bytes(policy=email.policy.default)
    names = _unique_names(_stamp(_now()), ".eml", insert_before=cls)
    return _write_new(ctx.state / "outbox", names, data)


def _smtp_send(
    cfg: dict[str, object],
    msg: EmailMessage,
    password: str,
    deadline: float,
    cancelled: threading.Event,
    result: dict[str, str],
) -> None:
    """One SMTP attempt; runs in a daemon thread so the caller can enforce the total deadline."""
    smtp = _block(cfg, "smtp")
    host = str(smtp.get("host") or "")
    port_value = smtp.get("port")
    port = port_value if isinstance(port_value, int) else 587
    timeout_value = smtp.get("timeout_s")
    timeout_s = float(timeout_value) if isinstance(timeout_value, int) else 5.0
    user = str(smtp.get("user") or "")
    stage = "connect"

    def step_timeout(conn: smtplib.SMTP) -> None:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("delivery budget spent")
        value = max(0.1, min(timeout_s, remaining))
        conn.timeout = value
        sock = getattr(conn, "sock", None)
        if sock is not None:
            sock.settimeout(value)

    try:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("delivery budget spent")
        conn = smtplib.SMTP(host, port, timeout=min(timeout_s, remaining))
        try:
            if smtp.get("starttls") is not False:
                if cancelled.is_set():
                    return
                stage = "starttls"
                step_timeout(conn)
                conn.starttls(context=ssl.create_default_context())
            if cancelled.is_set():
                return
            stage = "login"
            step_timeout(conn)
            conn.login(user, password)
            if cancelled.is_set():
                return
            stage = "send"
            step_timeout(conn)
            conn.send_message(
                msg, from_addr=_str_or_none(cfg.get("from")), to_addrs=_to_list(cfg)
            )
            result["outcome"] = "sent"
            with contextlib.suppress(Exception):
                conn.quit()
        finally:
            with contextlib.suppress(Exception):
                conn.close()
    except smtplib.SMTPAuthenticationError:
        result["outcome"] = "auth_failed"
    except TimeoutError:
        result["outcome"] = "timeout"
    except Exception as exc:  # noqa: BLE001 - every other failure is reported by class name only
        result["outcome"] = "tls_error" if stage == "starttls" else "smtp_error"
        result["error"] = type(exc).__name__


def _load_password_within(user: str | None, deadline: float) -> tuple[str | None, bool]:
    """``load_password`` in a daemon thread bounded by ``deadline``: (password, timed_out).

    A store that hangs past the deadline is abandoned; its late result is never read.
    """
    result: dict[str, object] = {}

    def run() -> None:
        try:
            result["value"] = load_password(user)
        except Exception as exc:  # noqa: BLE001 - re-raised in the caller's thread below
            result["error"] = exc

    worker = threading.Thread(target=run, name="agent-notify-credential", daemon=True)
    worker.start()
    worker.join(max(0.0, deadline - time.monotonic()))
    if worker.is_alive():
        return None, True
    error = result.get("error")
    if isinstance(error, Exception):
        raise error
    value = result.get("value")
    return (value if isinstance(value, str) else None), False


def _credential(
    ctx: _Ctx, note: dict[str, object], user: str | None, deadline: float
) -> tuple[str | None, str | None]:
    """(password, None), or (None, outcome) after logging ``timeout`` or ``credential_missing``."""
    password, timed_out = _load_password_within(user, deadline)
    if timed_out:
        _log(ctx.state, _line(note, "timeout", stage="credential"))
        return None, "timeout"
    if not password:
        return None, _skip(
            ctx,
            note,
            "credential_missing",
            "credential",
            "store|keyring|env",
            None,
            None,
        )
    return password, None


def _deliver_smtp(
    cfg: dict[str, object], msg: EmailMessage, password: str, deadline: float
) -> tuple[str, str | None]:
    cancelled = threading.Event()
    result: dict[str, str] = {}
    worker = threading.Thread(
        target=_smtp_send,
        args=(cfg, msg, password, deadline, cancelled, result),
        name="agent-notify-smtp",
        daemon=True,
    )
    worker.start()
    worker.join(max(0.0, deadline - time.monotonic()))
    if worker.is_alive():
        cancelled.set()
        return "timeout", None
    return result.get("outcome", "smtp_error"), result.get("error")


# ── Delivery pipeline ───────────────────────────────────────────────────


def _process(
    ctx: _Ctx,
    note: dict[str, object],
    *,
    test: bool = False,
    dry_flag: bool = False,
    workdir: str | None = None,
) -> str:
    """Suppression checks, ledger reservation, then one dry-run file or one SMTP attempt.

    ``workdir`` is the real directory for the branch lookup; the note holds only
    the masked one, which git cannot open when it held an address.
    """
    deadline = time.monotonic() + DELIVERY_BUDGET_S
    cfg = ctx.cfg
    cls = str(note.get("class"))
    if not test:
        key = note.get("event_key")
        if isinstance(key, str) and _block(cfg, "events").get(key) is False:
            return _skip(ctx, note, "event_disabled", f"events.{key}", False, key, None)
        if _block(cfg, "classes").get(cls) is False:
            return _skip(
                ctx, note, "class_disabled", f"classes.{cls}", False, cls, None
            )
    dry = (
        dry_flag
        or cfg.get("dry_run") is True
        or os.environ.get("AGENT_NOTIFY_DRY_RUN", "").strip() == "1"
    )
    user = _str_or_none(_block(cfg, "smtp").get("user"))
    password: str | None = None
    now = _now()
    ctx.state.mkdir(parents=True, exist_ok=True)
    locked = _lock_acquire(ctx.state, LOCK_WAIT_S)
    if locked:
        try:
            entries = _read_ledger(ctx.state, now)
            skipped = _ledger_skip(ctx, note, entries, now, test)
            if skipped is None and not dry:
                skipped = _backoff_skip(ctx, note, now)
            if skipped is not None:
                return skipped
            if not dry:
                password, stopped = _credential(ctx, note, user, deadline)
                if stopped is not None:
                    return stopped
            entries.append(
                {
                    "t": now,
                    "kind": "attempted",
                    "session": note.get("session"),
                    "class": cls,
                    "digest": _digest(note),
                    "test": test,
                }
            )
            _write_ledger(ctx.state, entries)
        finally:
            _lock_release(ctx.state)
    else:
        _log(ctx.state, _line(note, "state_lock_timeout"))
        if not dry:
            skipped = _backoff_skip(ctx, note, now)
            if skipped is not None:
                return skipped
            password, stopped = _credential(ctx, note, user, deadline)
            if stopped is not None:
                return stopped
    git_dir = workdir if workdir is not None else str(note.get("cwd") or "")
    branch = mask_addresses(_git_branch(git_dir, deadline), _known_addresses(cfg))
    error: str | None = None
    if dry:
        msg, truncated = _message(ctx, note, branch, masked=True, test=test)
        _write_eml(ctx, msg, cls)
        outcome = "dry_run"
    else:
        msg, truncated = _message(ctx, note, branch, masked=False, test=test)
        outcome, error = _deliver_smtp(cfg, msg, password or "", deadline)
        if outcome == "auth_failed":
            _write_backoff(ctx.state)
    extra: dict[str, object] = {}
    if error:
        extra["error"] = error
    if truncated:
        extra["excerpt_truncated"] = True
    _log(ctx.state, _line(note, outcome, **extra))
    if locked:
        _append_outcome(ctx.state, note, outcome)
    return outcome


def _write_pending(ctx: _Ctx, note: dict[str, object]) -> Path:
    session = str(note.get("session") or "unknown")
    stem = f"{_stamp(_now())}-{_UNSAFE_NAME.sub('_', session[:8])}"
    data = json.dumps({"created": _now(), "note": note}, ensure_ascii=False).encode(
        "utf-8"
    )
    return _write_new(ctx.state / "pending", _unique_names(stem, ".json"), data)


def on_stop(
    payload: object,
    decision: str,
    reason: str,
    kind: str,
    open_rows: int | None,
    task_file: str | None,
    release_reason: str | None = None,
) -> None:
    """Called by the stop gate for every Claude Code stop; never raises."""
    ctx: _Ctx | None = None
    try:
        ctx = _open(None)
        if ctx is None:
            return
        data = payload if isinstance(payload, dict) else {}
        event = data.get("hook_event_name")
        event = event if isinstance(event, str) and event else "Stop"
        gate: dict[str, object] = {
            "decision": decision,
            "kind": kind,
            "release_reason": release_reason,
        }
        cls, rule = classify_explain(event, data, gate)
        note = _make_note(
            ctx,
            harness="claude",
            event=event,
            event_key="stop_failure" if event == "StopFailure" else "stop",
            payload=data,
            cls=cls,
            rule=rule,
            reason=reason,
            task_file=task_file,
            open_rows=open_rows,
        )
        workdir = _workdir(data)
        if DELIVERY_MODE == "detached":
            pending = _write_pending(ctx, note)
            argv = [
                sys.executable,
                str(Path(__file__).resolve()),
                "deliver",
                str(pending),
            ]
            try:
                _spawn(argv, DETACHED_PROCESS if os.name == "nt" else 0, workdir)
            except BaseException:
                with contextlib.suppress(OSError):
                    pending.unlink()
                raise
        else:
            _process(ctx, note, workdir=workdir)
    except Exception as exc:  # noqa: BLE001 - the stop hook must never fail because of email
        if ctx is not None:
            _log(ctx.state, {"outcome": "internal_error", "error": type(exc).__name__})


def _spawn(argv: list[str], creationflags: int, workdir: str | None = None) -> None:
    """Start the detached ``deliver`` worker with null stdio; ``workdir`` goes in its environment, never in a file."""
    env = dict(os.environ)
    env.pop(WORKDIR_ENV, None)
    if workdir:
        env[WORKDIR_ENV] = workdir
    if os.name == "nt":
        subprocess.Popen(  # noqa: S603 - argv is this interpreter and this file
            argv,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
            creationflags=creationflags,
            env=env,
        )
    else:
        subprocess.Popen(  # noqa: S603 - argv is this interpreter and this file
            argv,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
            start_new_session=True,
            env=env,
        )


# ── Harness payloads ────────────────────────────────────────────────────


def _read_stdin() -> str:
    stream = sys.stdin
    if stream is None:
        return ""
    buffer = getattr(stream, "buffer", None)
    if buffer is not None:
        return buffer.read().decode("utf-8", errors="replace")
    return stream.read()


def _unsupported(ctx: _Ctx, harness: str, event: object) -> None:
    _log(
        ctx.state,
        {"outcome": "event_unsupported", "event": str(event)[:64], "harness": harness},
    )


def _harness_note(
    ctx: _Ctx, harness: str, data: dict[str, object]
) -> tuple[dict[str, object], str] | None:
    """One harness payload as (note, real directory); None (logged) for an event this module does not handle."""
    if harness == "codex":
        if data.get("type") != "agent-turn-complete":
            _unsupported(ctx, harness, data.get("type"))
            return None
        payload: dict[str, object] = {
            "session_id": data.get("thread-id"),
            "cwd": data.get("cwd"),
            "last_assistant_message": data.get("last-assistant-message"),
        }
        cls, rule = classify_explain("Stop", payload, None)
        note = _make_note(
            ctx,
            harness=harness,
            event="Stop",
            event_key="stop",
            payload=payload,
            cls=cls,
            rule=rule,
        )
        return note, _workdir(payload)
    if harness == "cursor":
        if data.get("hook_event_name") != "stop":
            _unsupported(ctx, harness, data.get("hook_event_name"))
            return None
        status = data.get("status")
        roots = data.get("workspace_roots")
        payload = {
            "session_id": data.get("conversation_id"),
            "cwd": roots[0] if isinstance(roots, list) and roots else None,
        }
        cls = (
            _CURSOR_STATUS.get(status, "waiting")
            if isinstance(status, str)
            else "waiting"
        )
        note = _make_note(
            ctx,
            harness=harness,
            event="stop",
            event_key="stop",
            payload=payload,
            cls=cls,
            rule="cursor-status",
        )
        return note, _workdir(payload)
    event = data.get("hook_event_name")
    if event == "Notification":
        kind = data.get("notification_type")
        if kind not in ("permission_prompt", "idle_prompt"):
            _unsupported(ctx, harness, f"Notification:{kind}")
            return None
        key = str(kind)
    elif event == "StopFailure":
        key = "stop_failure"
    elif event == "Stop":
        key = "stop"
    else:
        _unsupported(ctx, harness, event)
        return None
    cls, rule = classify_explain(str(event), data, None)
    note = _make_note(
        ctx,
        harness=harness,
        event=str(event),
        event_key=key,
        payload=data,
        cls=cls,
        rule=rule,
    )
    return note, _workdir(data)


# ── CLI actions ─────────────────────────────────────────────────────────


def _cmd_hook(args: argparse.Namespace) -> int:
    ctx: _Ctx | None = None
    try:
        ctx = _open(args.home)
        if ctx is None:
            return 0
        harness = args.harness
        raw = (
            (args.payload[-1] if args.payload else "")
            if harness == "codex"
            else _read_stdin()
        )
        try:
            data = json.loads(raw)
        except ValueError:
            data = None
        if not isinstance(data, dict):
            _log(ctx.state, {"outcome": "payload_invalid", "harness": harness})
            return 0
        found = _harness_note(ctx, harness, data)
        if found is not None:
            note, workdir = found
            _process(ctx, note, dry_flag=args.dry_run, workdir=workdir)
    except Exception as exc:  # noqa: BLE001 - a hook must never fail because of email
        if ctx is not None:
            _log(ctx.state, {"outcome": "internal_error", "error": type(exc).__name__})
    return 0


def _cmd_deliver(args: argparse.Namespace) -> int:
    pending = Path(args.pending)
    ctx: _Ctx | None = None
    try:
        ctx = _open(args.home)
        if ctx is None:
            return 0
        try:
            doc = json.loads(pending.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            doc = None
        created = doc.get("created") if isinstance(doc, dict) else None
        note = doc.get("note") if isinstance(doc, dict) else None
        if not isinstance(created, (int, float)) or not isinstance(note, dict):
            _log(ctx.state, {"outcome": "payload_invalid", "harness": "deliver"})
            return 0
        if _now() - created > PENDING_STALE_S:
            _log(ctx.state, _line(note, "pending_stale", age_s=int(_now() - created)))
            return 0
        _process(ctx, note, dry_flag=args.dry_run, workdir=_deliver_workdir(ctx, note))
    except Exception as exc:  # noqa: BLE001 - the detached worker has no one to report to
        if ctx is not None:
            _log(ctx.state, {"outcome": "internal_error", "error": type(exc).__name__})
    finally:
        with contextlib.suppress(OSError):
            pending.unlink()
    return 0


def _deliver_workdir(ctx: _Ctx, note: dict[str, object]) -> str | None:
    """The real directory from the worker environment, only when it masks to the note directory."""
    value = os.environ.get(WORKDIR_ENV)
    if not value:
        return None
    if mask_addresses(value, _known_addresses(ctx.cfg)) != note.get("cwd"):
        return None
    return value


def _cmd_send(args: argparse.Namespace) -> int:
    ctx = _open(args.home)
    if ctx is None:
        return 0
    payload: dict[str, object] = {
        "session_id": "manual",
        "cwd": os.getcwd(),
        "last_assistant_message": args.text,
    }
    note = _make_note(
        ctx,
        harness="manual",
        event="manual",
        event_key=None,
        payload=payload,
        cls=args.cls,
        rule=None,
    )
    _process(ctx, note, dry_flag=args.dry_run, workdir=_workdir(payload))
    return 0


def _cmd_test_send(args: argparse.Namespace) -> int:
    ctx = _open(args.home, ignore_enabled=True)
    if ctx is None:
        print(
            "test-send: no usable notify home (missing notify.json, invalid config, or switched off)"
        )
        return 1
    missing = [key for key in _REQUIRED_WHEN_ENABLED if _dotted(ctx.cfg, key) is None]
    if missing:
        print(f"test-send: set {', '.join(missing)} in notify.local.json first")
        return 1
    payload: dict[str, object] = {
        "session_id": "test-send",
        "cwd": os.getcwd(),
        "last_assistant_message": "This is a test message from agent_notify. Delivery works.",
    }
    note = _make_note(
        ctx,
        harness="manual",
        event="test-send",
        event_key=None,
        payload=payload,
        cls="done",
        rule=None,
    )
    outcome = _process(
        ctx, note, test=True, dry_flag=args.dry_run, workdir=_workdir(payload)
    )
    print(f"test-send: {outcome} (log: {ctx.state / 'notify.log.jsonl'})")
    return 0 if outcome in ("sent", "dry_run") else 1


def _cmd_setup(args: argparse.Namespace) -> int:
    user = args.user
    if not user:
        with contextlib.suppress(ConfigError):
            user = _str_or_none(
                _block(load_config(resolve_home(args.home)), "smtp").get("user")
            )
    if not user:
        print("setup: no SMTP user; pass --user <sender address>", file=sys.stderr)
        return 1
    secret = getpass.getpass(f"App password for {mask_address(user)} (input hidden): ")
    secret = "".join(secret.split())  # Google shows app passwords in groups of four
    if not secret:
        print("setup: empty password; nothing stored", file=sys.stderr)
        return 1
    if not _cred_write(CRED_TARGET_PREFIX + user, user, secret):
        print(
            "setup: the credential store refused the password; nothing stored",
            file=sys.stderr,
        )
        return 1
    print(f"setup: credential stored for {mask_address(user)}")
    return 0


def _masked_config(cfg: dict[str, object]) -> dict[str, object]:
    out = copy.deepcopy(cfg)
    sender = out.get("from")
    if isinstance(sender, str):
        out["from"] = mask_address(sender)
    recipients = out.get("to")
    if isinstance(recipients, list):
        out["to"] = [mask_address(a) if isinstance(a, str) else a for a in recipients]
    smtp = out.get("smtp")
    if isinstance(smtp, dict) and isinstance(smtp.get("user"), str):
        smtp["user"] = mask_address(smtp["user"])
    return out


def _cmd_status(args: argparse.Namespace) -> int:
    home = resolve_home(args.home)
    print(f"home: {home}")
    if not (home / "notify.json").is_file():
        print("notify.json: missing")
        return 1
    print(f"off switch: {_kill_switch(home) or 'none'}")
    try:
        cfg = load_config(home)
    except ConfigError as exc:
        print(f"config: invalid ({exc.file}: {exc.key})")
        return 1
    ctx = _Ctx(home, cfg)
    print("config: " + json.dumps(_masked_config(cfg), indent=2, ensure_ascii=False))
    user = _str_or_none(_block(cfg, "smtp").get("user"))
    print(f"credential: {'present' if load_password(user) else 'missing'}")
    now = _now()
    attempted = [
        e for e in _read_ledger(ctx.state, now) if e.get("kind") == "attempted"
    ]

    def within(seconds: int) -> int:
        return sum(
            1
            for e in attempted
            if isinstance(e.get("t"), (int, float))
            and now - float(str(e.get("t"))) < seconds
        )

    print(
        f"caps: hour {within(3600)}/{_int(cfg, 'hourly_cap')}"
        f" day {within(86400)}/{_int(cfg, 'daily_cap')}"
    )
    log_path = ctx.state / "notify.log.jsonl"
    try:
        tail = log_path.read_text(encoding="utf-8").splitlines()[-5:]
    except OSError:
        tail = []
    print(f"log: {log_path}")
    for line in tail:
        print(f"  {line}")
    return 0


def _parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--home",
        help="notify home (default: AGENT_NOTIFY_HOME, registry home, ~/.agent/notify)",
    )
    common.add_argument(
        "--dry-run", action="store_true", help="write outbox/*.eml instead of sending"
    )
    parser = argparse.ArgumentParser(
        prog="agent_notify", description="Email the human when an agent stops."
    )
    sub = parser.add_subparsers(dest="action", required=True)
    hook = sub.add_parser(
        "hook", parents=[common], help="handle one harness hook payload"
    )
    hook.add_argument(
        "--harness", choices=("claude", "codex", "cursor"), default="claude"
    )
    hook.add_argument("payload", nargs="*", help="Codex notify JSON (last argument)")
    deliver = sub.add_parser(
        "deliver", parents=[common], help="detached worker for one pending file"
    )
    deliver.add_argument("pending")
    send = sub.add_parser("send", parents=[common], help="send one message by hand")
    send.add_argument("--class", dest="cls", choices=STOP_CLASSES, required=True)
    send.add_argument("--text", required=True)
    sub.add_parser(
        "test-send", parents=[common], help="send one test message, even when disabled"
    )
    setup = sub.add_parser(
        "setup", parents=[common], help="store the SMTP app password"
    )
    setup.add_argument("--user", help="SMTP user (default: smtp.user from the config)")
    sub.add_parser(
        "status",
        parents=[common],
        help="show the home, config, credential and recent log",
    )
    return parser


_ACTIONS = {
    "hook": _cmd_hook,
    "deliver": _cmd_deliver,
    "send": _cmd_send,
    "test-send": _cmd_test_send,
    "setup": _cmd_setup,
    "status": _cmd_status,
}


def main(argv: list[str] | None = None) -> int:
    """CLI entry point; ``hook`` and ``deliver`` always return 0."""
    args_list = list(sys.argv[1:] if argv is None else argv)
    quiet = bool(args_list) and args_list[0] in ("hook", "deliver")
    try:
        args = _parser().parse_args(args_list)
    except SystemExit as exc:
        if quiet:
            return 0
        return exc.code if isinstance(exc.code, int) else 2
    return _ACTIONS[args.action](args)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
