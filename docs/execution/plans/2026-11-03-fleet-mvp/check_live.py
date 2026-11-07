#!/usr/bin/env python3
"""Plan-local verifier for the live ACs of the fleet MVP: AC-20, AC-21 and AC-31.

Modes: firewall-before, firewall, member, avkit-tools, av-kit, --selftest.
It writes only under RECEIPTS_DIR, apart from the two firewall records it keeps in FLEET_OPS_REPORTS.
FLEET_LAN is the subnet the hub's rule allows, in CIDR form, and FLEET_MEMBER is the member's fleet name.
Each mode gathers its evidence, then a pure function lists the problems, which is what --selftest feeds.
"""
from __future__ import annotations

import ipaddress
import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
FLEET_PY = ROOT / ".agent" / "fleet" / "fleet.py"
RULE_NAME = "Fleet hub 8770"
AVKIT = "P:/av-kit"
AVKIT_COMMANDS = ("setup", "check-py", "check-ui", "check-mcp")
RECORD_MARK = "MEMBER-RECORD "
RECORD_FIELDS = ("collector", "collector_start", "profiles", "inbound")

FIREWALL_RECORD_PS = r"""
$ErrorActionPreference = 'Stop'
$rules = @(Get-NetFirewallRule -DisplayName '%s' -ErrorAction SilentlyContinue | ForEach-Object {
    $a = $_ | Get-NetFirewallAddressFilter
    $p = $_ | Get-NetFirewallPortFilter
    @{ enabled = [string]$_.Enabled; direction = [string]$_.Direction; action = [string]$_.Action
       profile = [string]$_.Profile; protocol = [string]$p.Protocol; port = [string]$p.LocalPort
       remote = @($a.RemoteAddress | ForEach-Object { [string]$_ }) }
})
$plex = @(Get-NetFirewallRule | Where-Object { $_.DisplayName -like 'Plex*' -and $_.Direction -eq 'Inbound' } | ForEach-Object {
    @{ name = $_.DisplayName; enabled = [string]$_.Enabled; action = [string]$_.Action; profile = [string]$_.Profile }
})
$smb = @(Get-NetFirewallRule -Name 'FPS-SMB-In-TCP' -ErrorAction SilentlyContinue | ForEach-Object { [string]$_.Enabled })
$record = @{
    profiles = @(Get-NetFirewallProfile | Sort-Object Name | ForEach-Object { "$($_.Name)=$($_.Enabled)" })
    network = @(Get-NetConnectionProfile | Sort-Object InterfaceAlias | ForEach-Object { "$($_.InterfaceAlias)=$($_.NetworkCategory)" })
    rule = $rules; plex = $plex; smb = $smb
}
$record | ConvertTo-Json -Depth 5 -Compress
""" % RULE_NAME


def need(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise SystemExit(f"set {name}")
    return value


def rule_remotes(lan: str) -> set[str]:
    """The two forms Windows can report the subnet in: CIDR, and address/mask."""
    net = ipaddress.ip_network(lan)
    return {str(net), f"{net.network_address}/{net.netmask}"}


def rule_record(which: str) -> Path:
    return Path(need("FLEET_OPS_REPORTS")) / f"fleet-hub-rule-{which}.txt"


def receipts() -> Path:
    path = Path(os.environ["RECEIPTS_DIR"])
    path.mkdir(parents=True, exist_ok=True)
    return path


def firewall_record() -> dict:
    r = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", FIREWALL_RECORD_PS],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    if r.returncode != 0:
        raise SystemExit(f"firewall record failed: {r.stderr}")
    return json.loads(r.stdout)


def fleet_cli(*args: str) -> tuple[int, dict | None]:
    r = subprocess.run(
        [sys.executable, str(FLEET_PY), *args], capture_output=True, text=True, encoding="utf-8",
        errors="replace", stdin=subprocess.DEVNULL,
    )
    lines = r.stdout.strip().splitlines()
    if not lines:
        print(f"fleet.py {' '.join(args)} exited {r.returncode}: {r.stderr.strip()}")
    return r.returncode, json.loads(lines[-1]) if lines else None


def git_lines(*args: str) -> list[str]:
    r = subprocess.run(["git", "-C", AVKIT, *args], capture_output=True, text=True, check=True)
    return r.stdout.splitlines()


def before_problems(record: dict) -> list[str]:
    problems = []
    if record["rule"]:
        problems.append(f"the rule {RULE_NAME} exists before it was created")
    if not any(n.endswith("=Private") for n in record["network"]):
        problems.append("no network is on the Private profile, so the rule would not apply")
    return problems


def firewall_problems(before: dict, after: dict, remotes: set[str]) -> list[str]:
    problems = []
    rules = after["rule"]
    if len(rules) != 1:
        problems.append(f"expected one rule named {RULE_NAME}, found {len(rules)}")
    for rule in rules:
        expected = {
            "enabled": "True", "direction": "Inbound", "action": "Allow", "profile": "Private",
            "protocol": "TCP", "port": "8770",
        }
        for field, value in expected.items():
            if rule[field] != value:
                problems.append(f"rule {field} is {rule[field]}, expected {value}")
        if len(rule["remote"]) != 1 or rule["remote"][0] not in remotes:
            problems.append(f"rule remote address is {rule['remote']}")
    if before["profiles"] != after["profiles"]:
        problems.append(f"firewall profiles changed: {before['profiles']} -> {after['profiles']}")
    if not any(r["enabled"] == "True" and r["action"] == "Allow" and r["profile"] == "Any" for r in after["plex"]):
        problems.append("no enabled Plex inbound allow on profile Any")
    if after["smb"] != ["True"]:
        problems.append(f"FPS-SMB-In-TCP is {after['smb']}")
    return problems


def parse_records(report: str) -> list[dict]:
    return [json.loads(ln[len(RECORD_MARK):]) for ln in report.splitlines() if ln.startswith(RECORD_MARK)]


def member_problems(name: str, status: dict | None, wait_code: int, wait: dict | None, records: list[dict]) -> list[str]:
    problems = []
    row = next((m for m in (status or {}).get("members", []) if m["name"] == name), None)
    if not row:
        problems.append(f"status does not list {name}")
    else:
        if row["state"] != "approved" or not row["online"]:
            problems.append(f"{name} is {row['state']}, online={row['online']}")
        if not (row["capabilities"] or {}).get("python"):
            problems.append(f"{name}'s capability report has no python")
    if wait_code != 0 or not wait or wait.get("state") != "completed":
        problems.append(f"ping did not complete: exit {wait_code}, {wait}")
    elif not (wait.get("capabilities") or {}).get("python"):
        problems.append("the ping result has no capability report")
    if len(records) < 2:
        problems.append(f"expected before and after records from member-record.ps1, found {len(records)}")
    else:
        for field in RECORD_FIELDS:
            if records[0][field] != records[-1][field]:
                problems.append(f"{field} changed on {name}: {records[0][field]} -> {records[-1][field]}")
        if records[-1]["probe"] != "401":
            problems.append(f"the keyless probe from {name} returned {records[-1]['probe']}, expected 401")
    return problems


def tools_problems(name: str, status: dict | None, requires: list[str]) -> list[str]:
    row = next((m for m in (status or {}).get("members", []) if m["name"] == name), None)
    if not row:
        return [f"status does not list {name}"]
    caps = row["capabilities"] or {}
    return [f"{tool} has no version on {name}" for tool in requires if not caps.get(tool)]


def avkit_problems(runs: dict[str, tuple[dict, dict]], before: list[str], after: list[str], refs: list[str]) -> list[str]:
    problems = []
    for name in AVKIT_COMMANDS:
        if name not in runs:
            problems.append(f"{name}: no receipt")
            continue
        snapshot, result = runs[name]
        if result["state"] == "rejected":
            problems.append(f"{name}: rejected, {result.get('reason')}")
        for field in ("exit_code", "log", "tree"):
            if result.get(field) is None:
                problems.append(f"{name}: no {field}")
        if result.get("tree") != snapshot["tree"]:
            problems.append(f"{name}: tree {result.get('tree')} differs from the snapshot's {snapshot['tree']}")
    if refs:
        problems.append(f"refs/fleet is not empty: {refs}")
    if before != after:
        problems.append(f"branches or worktrees changed: {before} -> {after}")
    return problems


def report(problems: list[str]) -> int:
    for p in problems:
        print(f"FAIL {p}")
    print("ok" if not problems else f"{len(problems)} problem(s)")
    return 1 if problems else 0


def cmd_firewall_before() -> int:
    record = firewall_record()
    rule_record("before").write_text(json.dumps(record, indent=1), encoding="utf-8")
    print(json.dumps(record))
    return report(before_problems(record))


def cmd_firewall() -> int:
    remotes = rule_remotes(need("FLEET_LAN"))
    before = json.loads(rule_record("before").read_text(encoding="utf-8"))
    after = firewall_record()
    rule_record("after").write_text(json.dumps(after, indent=1), encoding="utf-8")
    print(json.dumps(after))
    return report(firewall_problems(before, after, remotes))


def cmd_member() -> int:
    name = need("FLEET_MEMBER")
    out = receipts()
    _, status = fleet_cli("status")
    (out / "fleet-live-member-status.json").write_text(json.dumps(status), encoding="utf-8")
    _, sent = fleet_cli("send", name, "ping")
    wait_code, wait = fleet_cli("wait", (sent or {}).get("task", "none"), "--timeout", "60")
    (out / "fleet-live-member-wait.json").write_text(json.dumps(wait), encoding="utf-8")
    print(json.dumps({"status": status, "wait_exit": wait_code, "wait": wait}))
    report_file = out / "member-bootstrap-report.txt"
    records = parse_records(report_file.read_text(encoding="utf-8", errors="replace"))
    return report(member_problems(name, status, wait_code, wait, records))


def cmd_avkit_tools() -> int:
    manifest = json.loads(Path(AVKIT, ".agent", "fleet.json").read_text(encoding="utf-8"))
    _, status = fleet_cli("status")
    print(json.dumps(status))
    return report(tools_problems(need("FLEET_MEMBER"), status, manifest["requires"]))


def avkit_lists() -> list[str]:
    return git_lines("branch", "--list") + git_lines("worktree", "list")


def cmd_avkit() -> int:
    out = receipts()
    runs = {}
    for name in AVKIT_COMMANDS:
        snapshot, result = out / f"fleet-avkit-{name}-run.json", out / f"fleet-avkit-{name}.json"
        if snapshot.exists() and result.exists():
            runs[name] = (json.loads(snapshot.read_text(encoding="utf-8")), json.loads(result.read_text(encoding="utf-8")))
            print(name, json.dumps(runs[name][1]))
    before = (out / "fleet-avkit-before.txt").read_text(encoding="utf-8").splitlines()
    return report(avkit_problems(runs, before, avkit_lists(), git_lines("for-each-ref", "refs/fleet")))


def selftest() -> int:
    good_rule = {
        "enabled": "True", "direction": "Inbound", "action": "Allow", "profile": "Private", "protocol": "TCP",
        "port": "8770", "remote": ["192.0.2.0/255.255.255.0"],
    }
    remotes = rule_remotes("192.0.2.0/24")
    name = "member-1"
    plex = [{"name": "Plex", "enabled": "True", "action": "Allow", "profile": "Any"}]
    before = {"profiles": ["Private=False"], "network": ["Wi-Fi=Private"], "rule": [], "plex": plex, "smb": ["True"]}
    after = {**before, "rule": [good_rule]}
    online = {"name": name, "state": "approved", "online": True, "capabilities": {"python": "3.14", "uv": "0.9"}}
    status = {"members": [online]}
    wait = {"state": "completed", "capabilities": {"python": "3.14"}}
    record = {"collector": "Running", "collector_start": "Automatic", "profiles": ["Private=False"], "inbound": 354, "probe": "401"}
    snapshot = {"tree": "a" * 40}
    result = {"state": "completed", "exit_code": 0, "log": "b" * 64, "tree": "a" * 40}
    runs = {name: (snapshot, result) for name in AVKIT_COMMANDS}

    good = {
        "firewall-before": before_problems(before),
        "firewall": firewall_problems(before, after, remotes),
        "member": member_problems(name, status, 0, wait, [record, record]),
        "avkit-tools": tools_problems(name, status, ["python", "uv"]),
        "av-kit": avkit_problems(runs, ["* main"], ["* main"], []),
    }
    bad = {
        "firewall-before rule exists": before_problems(after),
        "firewall-before no private network": before_problems({**before, "network": ["Wi-Fi=Public"]}),
        "firewall absent": firewall_problems(before, before, remotes),
        "firewall two rules": firewall_problems(before, {**after, "rule": [good_rule, good_rule]}, remotes),
        "firewall remote any": firewall_problems(before, {**after, "rule": [{**good_rule, "remote": ["Any"]}]}, remotes),
        "firewall public": firewall_problems(before, {**after, "rule": [{**good_rule, "profile": "Private, Public"}]}, remotes),
        "firewall profiles": firewall_problems(before, {**after, "profiles": ["Private=True"]}, remotes),
        "firewall plex": firewall_problems(before, {**after, "plex": [{**plex[0], "enabled": "False"}]}, remotes),
        "firewall smb": firewall_problems(before, {**after, "smb": ["False"]}, remotes),
        "member not listed": member_problems(name, {"members": []}, 0, wait, [record, record]),
        "member offline": member_problems(name, {"members": [{**online, "online": False}]}, 0, wait, [record, record]),
        "member pending": member_problems(name, {"members": [{**online, "state": "pending"}]}, 0, wait, [record, record]),
        "member no report": member_problems(name, {"members": [{**online, "capabilities": None}]}, 0, wait, [record, record]),
        "member ping failed": member_problems(name, status, 5, {"state": "submitted"}, [record, record]),
        "member one record": member_problems(name, status, 0, wait, [record]),
        "member collector": member_problems(name, status, 0, wait, [record, {**record, "collector": "Stopped"}]),
        "member profiles": member_problems(name, status, 0, wait, [record, {**record, "profiles": ["Private=True"]}]),
        "member inbound": member_problems(name, status, 0, wait, [record, {**record, "inbound": 355}]),
        "member probe": member_problems(name, status, 0, wait, [record, {**record, "probe": "200"}]),
        "avkit-tools missing": tools_problems(name, status, ["python", "node"]),
        "av-kit missing": avkit_problems({}, [], [], []),
        "av-kit rejected": avkit_problems({**runs, "setup": (snapshot, {**result, "state": "rejected"})}, [], [], []),
        "av-kit no log": avkit_problems({**runs, "setup": (snapshot, {**result, "log": None})}, [], [], []),
        "av-kit tree": avkit_problems({**runs, "setup": (snapshot, {**result, "tree": "c" * 40})}, [], [], []),
        "av-kit refs": avkit_problems(runs, [], [], ["refs/fleet/snap/x"]),
        "av-kit branch": avkit_problems(runs, ["* main"], ["* main", "other"], []),
    }
    failures = [f"good sample failed {k}: {v}" for k, v in good.items() if v]
    failures += [f"bad sample passed: {k}" for k, v in bad.items() if not v]
    parsed = parse_records(f"noise\n{RECORD_MARK}{json.dumps(record)}\n")
    if parsed != [record]:
        failures.append("parse_records")
    if not re.search(RULE_NAME, FIREWALL_RECORD_PS):
        failures.append("the record script does not name the rule")
    for f in failures:
        print(f"FAIL {f}")
    print(f"selftest {'ok' if not failures else 'FAILED'}: {len(good)} good samples, {len(bad)} bad samples")
    return 1 if failures else 0


MODES = {
    "firewall-before": cmd_firewall_before,
    "firewall": cmd_firewall,
    "member": cmd_member,
    "avkit-tools": cmd_avkit_tools,
    "av-kit": cmd_avkit,
    "--selftest": selftest,
}


def main() -> int:
    if len(sys.argv) != 2 or sys.argv[1] not in MODES:
        print(f"usage: check_live.py {{{','.join(MODES)}}}")
        return 2
    return MODES[sys.argv[1]]()


if __name__ == "__main__":
    raise SystemExit(main())
