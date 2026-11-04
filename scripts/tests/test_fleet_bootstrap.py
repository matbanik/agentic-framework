"""AC-16 to AC-19 of the fleet MVP plan: open routes, bootstrap files, publish and check, the template."""
from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
from fleet_harness import FLEET_PY, Hub, fleet, run_cli  # noqa: E402

TEMPLATE = FLEET_PY.parent / "bootstrap.md"
ROUTE_VALUES = {"id": "0" * 32, "sha256": "0" * 64, "name": "demo"}
MANIFEST = {"v": 1, "project": "demo", "requires": ["python"], "commands": {"test": [["python", "-V"]]}}


@pytest.fixture
def hub(tmp_path):
    h = Hub(tmp_path)
    h.start()
    yield h
    h.close()


def route_call(template: str) -> tuple[str, str]:
    method, path = template.split(" ", 1)
    return method, re.sub(r"<(\w+)>", lambda m: ROUTE_VALUES[m.group(1)], path)


def pairing_fields(hub) -> dict:
    lines = hub.stdout_path.read_text(errors="replace").splitlines()
    line = next(ln for ln in lines if ln.startswith("fleet-pairing "))
    return dict(part.split("=", 1) for part in line.split()[1:])


def write_manifest(repo: Path, manifest) -> Path:
    (repo / ".agent").mkdir(parents=True, exist_ok=True)
    text = manifest if isinstance(manifest, str) else json.dumps(manifest)
    (repo / ".agent" / "fleet.json").write_text(text, encoding="utf-8")
    return repo


def last_json(r) -> dict:
    return json.loads(r.stdout.strip().splitlines()[-1])


# AC-16: only the open routes work with no key


def test_ac16_open_routes_are_real_routes():
    assert set(fleet.OPEN_ROUTES) <= set(fleet.ROUTES)


@pytest.mark.parametrize("template", sorted(set(fleet.ROUTES) - set(fleet.OPEN_ROUTES)))
def test_ac16_every_other_route_needs_a_key(hub, template):
    method, path = route_call(template)
    status, reply = hub.request(method, path, {} if method != "GET" else None)
    assert (status, reply["error"]) == (401, "unauthorized")


def test_ac16_open_routes_work_with_no_key(hub):
    for template in sorted(fleet.OPEN_ROUTES):
        method, path = route_call(template)
        body = {"name": "opened", "key_sha256": "a" * 64} if method == "POST" else None
        assert hub.request(method, path, body)[0] == 200, template


def test_ac16_a_member_cannot_call_orchestrator_routes(hub):
    key = hub.pair("local").key()
    only_orchestrator = [t for t, (roles, _) in fleet.ROUTES.items() if roles == ("orchestrator",)]
    assert only_orchestrator
    for template in only_orchestrator:
        method, path = route_call(template)
        status, reply = hub.request(method, path, {} if method != "GET" else None, key=key)
        assert (status, reply["error"]) == (403, "role_not_allowed"), template


# AC-17: bootstrap files match the pairing line


def test_ac17_served_files_match_the_pairing_line(hub):
    fields = pairing_fields(hub)
    assert fields["url"] == hub.url() and fields["pin"] == hub.pin()
    for route, field in (("fleet.py", "fleet_py"), ("bootstrap.md", "bootstrap_md")):
        status, data = hub.request("GET", f"/bootstrap/{route}")
        assert status == 200
        assert hashlib.sha256(data).hexdigest() == fields[field]
    assert hashlib.sha256(FLEET_PY.read_bytes()).hexdigest() == fields["fleet_py"]
    assert hashlib.sha256(TEMPLATE.read_bytes()).hexdigest() == fields["bootstrap_md"]


def test_ac17_the_hub_saves_the_pairing_line(hub):
    saved = (hub.hub_dir / "pairing.txt").read_text(encoding="utf-8").strip()
    printed = [ln for ln in hub.stdout_path.read_text(errors="replace").splitlines() if ln.startswith("fleet-pairing ")]
    assert printed[-1] == saved


@pytest.mark.parametrize(
    "path",
    [
        "/bootstrap/../hub/hub.key",
        "/bootstrap/..%2fhub%2fhub.key",
        "/bootstrap/hub.db",
        "/bootstrap/orchestrator.key",
        "/bootstrap/hub.key",
        "/bootstrap/",
    ],
)
def test_ac17_other_bootstrap_paths_are_not_found(hub, path):
    secrets = [(hub.hub_dir / n).read_bytes() for n in ("hub.key", "orchestrator.key")]
    status, reply = hub.request("GET", path)
    assert status == 404
    text = json.dumps(reply).encode()
    assert not any(s in text for s in secrets)


# AC-18: publish, then check


def test_ac18_publish_then_check_lists_missing_tools(hub, tmp_path):
    member = hub.pair("local")
    repo = write_manifest(tmp_path / "repo", {**MANIFEST, "requires": ["python", "git"]})
    r = hub.cli("publish", "--repo", str(repo))
    assert r.returncode == 0, r.stdout + r.stderr
    assert last_json(r)["project"] == "demo"

    # With no PATH, python is still this interpreter and git cannot be found.
    r = run_cli(member.home, "check", "--project", "demo", env={"PATH": ""})
    assert r.returncode == 6, r.stdout + r.stderr
    out = last_json(r)
    assert out["missing"] == ["git"]
    assert out["capabilities"]["python"] and out["capabilities"]["git"] is None


def test_ac18_check_passes_when_nothing_is_missing(hub, tmp_path):
    member = hub.pair("local")
    hub.cli("publish", "--repo", str(write_manifest(tmp_path / "repo", MANIFEST)))
    r = run_cli(member.home, "check", "--project", "demo")
    assert r.returncode == 0, r.stdout + r.stderr
    assert last_json(r)["missing"] == []


def test_ac18_check_with_no_project_needs_no_hub(tmp_path):
    r = run_cli(tmp_path, "check")
    assert r.returncode == 0, r.stdout + r.stderr
    out = last_json(r)
    assert set(out["capabilities"]) == set(fleet.CAPABILITY_TOOLS)
    assert "missing" not in out


def test_ac18_check_on_the_hub_machine_uses_the_orchestrator_key(hub, tmp_path):
    hub.cli("publish", "--repo", str(write_manifest(tmp_path / "repo", MANIFEST)))
    r = hub.cli("check", "--project", "demo")
    assert r.returncode == 0, r.stdout + r.stderr


def test_ac18_check_does_not_end_a_running_members_session(hub):
    member = hub.pair("local")
    client = member.hello()
    assert run_cli(member.home, "check").returncode == 0
    status, _ = fleet.hub_request(client, "POST", "/v1/heartbeat", {})
    assert status == 200


def test_ac18_latest_publish_wins(hub, tmp_path):
    repo = tmp_path / "repo"
    hub.cli("publish", "--repo", str(write_manifest(repo, MANIFEST)))
    before = hub.rows()
    newer = {**MANIFEST, "requires": ["python", "git"]}
    assert hub.cli("publish", "--repo", str(write_manifest(repo, newer))).returncode == 0
    assert hub.rows() == before + 1
    status, reply = hub.request("GET", "/v1/projects/demo", key=hub.client().key)
    assert (status, reply) == (200, newer)


def test_ac18_unknown_project_is_not_found(hub):
    status, reply = hub.request("GET", "/v1/projects/nothing", key=hub.client().key)
    assert (status, reply["error"]) == (404, "not_found")
    r = hub.cli("check", "--project", "nothing")
    assert r.returncode == 2
    assert "not_found" in r.stderr


@pytest.mark.parametrize(
    "bad, code",
    [
        ({**MANIFEST, "extra": 1}, "bad_manifest:unknown_key:extra"),
        ({**MANIFEST, "commands": {}}, "bad_manifest:commands"),
        ({**MANIFEST, "commands": {"go": [["git", "status"]]}}, "bad_manifest:forbidden_command:git"),
        ({**MANIFEST, "project": "other"}, "bad_manifest:project_mismatch"),
    ],
)
def test_ac18_invalid_manifest_is_refused_with_no_row(hub, bad, code):
    before = hub.rows()
    status, reply = hub.request("PUT", "/v1/projects/demo", bad, key=hub.client().key)
    assert (status, reply["error"]) == (422, code)
    assert hub.rows() == before


def test_ac18_a_manifest_holding_a_secret_value_is_refused(hub):
    secret = "gh" + "p_" + "abcdef"
    before = hub.rows()
    bad = {**MANIFEST, "commands": {"test": [["python", secret]]}}
    status, reply = hub.request("PUT", "/v1/projects/demo", bad, key=hub.client().key)
    assert (status, reply["error"]) == (422, "secret_in_message")
    assert hub.rows() == before


def test_ac18_publish_refusals_exit_2_before_any_row(hub, tmp_path):
    before = hub.rows()
    missing = hub.cli("publish", "--repo", str(tmp_path / "no-repo"))
    assert missing.returncode == 2 and "no_manifest" in missing.stderr
    broken = hub.cli("publish", "--repo", str(write_manifest(tmp_path / "broken", "{not json")))
    assert broken.returncode == 2 and "bad_manifest:bad_json" in broken.stderr
    forbidden = {**MANIFEST, "commands": {"go": [["GIT.EXE", "status"]]}}
    r = hub.cli("publish", "--repo", str(write_manifest(tmp_path / "forbid", forbidden)))
    assert r.returncode == 2 and "bad_manifest:forbidden_command:git" in r.stderr
    assert hub.rows() == before


# AC-19: the template's shape


def section(text: str, heading: str) -> str:
    match = re.search(rf"^## {heading}\s*$(.*?)(?=^## |\Z)", text, re.M | re.S)
    assert match, f"no heading {heading}"
    return match.group(1)


def template_problems(text: str) -> list[str]:
    problems = []
    stops = {}
    for stop in fleet.BOOTSTRAP_STOPS:
        marker = f"STOP FOR HUMAN: {stop}"
        if marker not in text:
            problems.append(f"missing {marker}")
        stops[stop] = text.find(marker)
    for word, stop in (("pair", "run-pair"), ("approve", "run-approve")):
        first = re.search(rf"\b{word}\b", text)
        if first and (stops[stop] < 0 or first.start() < stops[stop]):
            problems.append(f"{word} appears before its stop line")
    for heading in ("Windows", "Linux", "macOS"):
        if not re.search(rf"^## {heading}\s*$", text, re.M):
            problems.append(f"no heading {heading}")
    for heading in ("Linux", "macOS"):
        match = re.search(rf"^## {heading}\s*$(.*?)(?=^## |\Z)", text, re.M | re.S)
        if match and match.group(1).strip():
            problems.append(f"{heading} has steps")
    if re.search(r"\bP:[\\/]", text):
        problems.append("a P: path")
    if "must never read `member.json`" not in text:
        problems.append("no sentence forbidding member.json")
    return problems


def test_ac19_the_template_has_its_shape():
    assert template_problems(TEMPLATE.read_text(encoding="utf-8")) == []


@pytest.mark.parametrize("stop", fleet.BOOTSTRAP_STOPS)
def test_ac19_the_checker_sees_a_removed_stop_line(stop):
    text = TEMPLATE.read_text(encoding="utf-8")
    assert template_problems(text.replace(f"STOP FOR HUMAN: {stop}", "continue")) != []


def test_ac19_the_checker_sees_the_other_breaks():
    text = TEMPLATE.read_text(encoding="utf-8")
    assert template_problems("`fleet.py pair`\n" + text)
    assert template_problems("`fleet.py approve`\n" + text)
    assert template_problems(text.replace("## macOS", "## macOS\n\n1. Install it.\n"))
    assert template_problems(text + "\nSee P:/somewhere.\n")
    assert template_problems(text.replace("must never read", "may read"))


def test_ac19_the_template_names_the_firewall_rule_and_the_update_steps():
    text = TEMPLATE.read_text(encoding="utf-8")
    assert fleet.FIREWALL_RULE in text
    assert "hash" in section(text, "Update")
