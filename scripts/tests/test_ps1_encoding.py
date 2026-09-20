#!/usr/bin/env python3
"""Packaging gate: shipped PowerShell scripts must be ASCII or UTF-8 BOM.

PS 5.1 without a BOM decodes as the system ANSI code page, so a UTF-8 em-dash
becomes a ParserError instead of a comment or string. This runner refuses any
core/**/*.ps1 that is neither pure ASCII nor prefixed with EF BB BF.

First stdout line is OK:/REFUSE:/USAGE:/FAIL-CLOSED:. Exit 0/1/2/3.
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BOM = b"\xef\xbb\xbf"


def _out(kind: str, msg: str, code: int) -> int:
    print(f"{kind}: {msg}")
    return code


def is_ascii_or_bom(data: bytes) -> bool:
    if data.startswith(BOM):
        return True
    try:
        data.decode("ascii")
        return True
    except UnicodeDecodeError:
        return False


def shipped_ps1() -> list[Path]:
    core = ROOT / "core"
    return sorted(p for p in core.rglob("*.ps1") if p.is_file())


def check_tree() -> list[str]:
    bad: list[str] = []
    files = shipped_ps1()
    if not files:
        return ["no core/**/*.ps1 found"]
    for path in files:
        data = path.read_bytes()
        if not is_ascii_or_bom(data):
            bad.append(str(path.relative_to(ROOT)).replace("\\", "/"))
    return bad


def prove_negative_oracle() -> str | None:
    """A BOM-less em-dash file must be refused. If the helper accepts it, the gate is a lie."""
    planted = "Write-Output \u2014\n".encode("utf-8")
    if is_ascii_or_bom(planted):
        return "negative oracle: BOM-less em-dash was accepted"
    return None


def _parse_only(exe: str, script: Path) -> tuple[int, str]:
    # Parser API: no execution of the script body, so missing PromptText cannot
    # hide a parse failure by exiting usage first.
    probe = (
        "$e=$null; $t=$null; "
        "[void][System.Management.Automation.Language.Parser]::ParseFile("
        f"'{script.as_posix()}', [ref]$t, [ref]$e); "
        "if ($e -and $e.Count) { $e | ForEach-Object { $_.ToString() }; exit 1 }; "
        "exit 0"
    )
    r = subprocess.run(
        [exe, "-NoProfile", "-NonInteractive", "-Command", probe],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    text = (r.stdout or "") + (r.stderr or "")
    return r.returncode, text


def instantiate_wrapper_copy(dest: Path) -> Path:
    src = ROOT / "core" / "tools" / "Invoke-CodexDispatch.ps1"
    text = src.read_text(encoding="utf-8")
    repl = {
        "{{PROJECT_NAME}}": "adoptprobe",
        "{{PROJECT_NAME_TITLE}}": "Adoptprobe",
        "{{PROJECT_NAME_UPPER}}": "ADOPTPROBE",
        "{{PROJECT_ROOT}}": dest.parent.as_posix(),
        "{{RECEIPTS_DIR}}": (dest.parent / "receipts").as_posix(),
        "{{REPO_URL}}": "example.invalid/adopt/probe",
    }
    for token, value in repl.items():
        text = text.replace(token, value)
    dest.write_text(text, encoding="ascii")
    return dest


def usage_not_parsererror(exe: str, script: Path) -> str | None:
    r = subprocess.run(
        [exe, "-NoProfile", "-NonInteractive", "-File", str(script)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    blob = ((r.stdout or "") + (r.stderr or "")).lower()
    if "parsererror" in blob.replace(" ", ""):
        return f"{exe} ParserError on instantiated wrapper: {blob[:240]}"
    if r.returncode == 0:
        return f"{exe} exited 0 with no PromptText (want usage/nonzero)"
    if "prompttext" not in blob and "promptfile" not in blob and "usage" not in blob:
        return f"{exe} missing-PromptText did not reach usage: {blob[:240]}"
    return None


def main() -> int:
    argparse.ArgumentParser(description=__doc__).parse_args()
    try:
        oracle = prove_negative_oracle()
        if oracle:
            return _out("REFUSE", oracle, 1)
        bad = check_tree()
        if bad:
            return _out("REFUSE", "BOM-less non-ASCII: " + ", ".join(bad), 1)

        errs: list[str] = []
        with tempfile.TemporaryDirectory(prefix="ps1-enc-") as tmp:
            tmp_p = Path(tmp)
            wrapped = instantiate_wrapper_copy(tmp_p / "Invoke-CodexDispatch.ps1")
            data = wrapped.read_bytes()
            if not is_ascii_or_bom(data):
                errs.append("instantiated wrapper is not ASCII")
            pwsh = shutil.which("pwsh")
            ps51 = shutil.which("powershell")
            if not pwsh and not ps51:
                return _out("FAIL-CLOSED", "neither pwsh nor powershell on PATH", 3)
            for exe in (ps51, pwsh):
                if not exe:
                    continue
                code, text = _parse_only(exe, wrapped)
                if code != 0:
                    errs.append(f"{exe} parse failed: {text[:240]}")
                err = usage_not_parsererror(exe, wrapped)
                if err:
                    errs.append(err)
        if errs:
            return _out("REFUSE", "; ".join(errs), 1)
        n = len(shipped_ps1())
        return _out("OK", f"{n} core/**/*.ps1 ASCII-or-BOM; wrapper parse-only + usage", 0)
    except OSError as exc:
        return _out("FAIL-CLOSED", str(exc), 3)


if __name__ == "__main__":
    raise SystemExit(main())
