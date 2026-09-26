"""Review output must survive the real adapter, schema gate and ledger loader."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import subprocess
import sys

import pytest
from jsonschema import Draft202012Validator

TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))
import review_ledger

SCHEMA = TOOLS.parent / '.agent/schemas/review-verdict.schema.v2.json'
ADAPTER = TOOLS / 'adapt_output_schema.py'


def verdict(check):
    return dict(schema_version='review-verdict.v2', date='2026-09-26',
                review_mode='execution', loop_id='pipeline-fixture', round=1,
                target_plan='plan.md', agent='reviewer', requested_verbosity='standard',
                verdict='approved', summary='Fixture verification',
                intent_anchor='Verify review output survives the actual consumer pipeline.',
                intent_achieved='yes', findings=[], checklist_results=[check])


MANUAL = dict(check='citation audit', result='pass', procedure='Compare all citations',
              observer='human reviewer', exit_code=None, evidence='Eight citations matched')
COMMAND = dict(check='tests', result='pass', command='python -m pytest',
               exit_code=0, evidence='25 tests passed')


@pytest.mark.parametrize('check,accepted', [
    (MANUAL, True), (COMMAND, True),
    ({k:v for k,v in MANUAL.items() if k != 'observer'}, False),
    (MANUAL | {'exit_code': 0}, False),
    ({k:v for k,v in COMMAND.items() if k != 'exit_code'}, False),
    (COMMAND | {'exit_code': None}, False),
])
def test_real_adapter_and_consumers(tmp_path, check, accepted):
    original = verdict(copy.deepcopy(check))
    # Strict output fills unused optional properties with synthetic nulls.
    raw = copy.deepcopy(original)
    for name in ('command', 'procedure', 'observer'):
        raw['checklist_results'][0].setdefault(name, None)
    path, backup = tmp_path/'verdict.json', tmp_path/'raw.json'
    raw_bytes = (json.dumps(raw, indent=2)+'\n').encode()
    path.write_bytes(raw_bytes)
    result = subprocess.run([sys.executable, str(ADAPTER), 'strip-nulls', str(path),
                             '--schema', str(SCHEMA), '--raw-copy', str(backup)],
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    assert backup.read_bytes() == raw_bytes
    normalized = json.loads(path.read_text())
    if accepted:
        assert normalized == original
    validator = Draft202012Validator(json.loads(SCHEMA.read_text(encoding='utf-8')))
    assert validator.is_valid(normalized) is accepted
    if accepted:
        assert review_ledger.load_verdict(path) == original
    else:
        with pytest.raises(review_ledger.Refuse):
            review_ledger.load_verdict(path)


def test_schema_null_semantics_and_fail_closed(tmp_path):
    schema = tmp_path/'schema.json'
    schema.write_text(json.dumps({'type':'object', 'properties': {
        'nullable': {'type':['string','null']},
        'optional': {'type':'string'}, 'required': {'type':'string'}},
        'required':['required'], 'additionalProperties':False}))
    document = tmp_path/'document.json'
    document.write_text(json.dumps({'nullable':None,'optional':None,'required':None,'unknown':None}))
    result = subprocess.run([sys.executable,str(ADAPTER),'strip-nulls',str(document),
                             '--schema',str(schema)],capture_output=True,text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(document.read_text()) == {'nullable':None,'required':None,'unknown':None}
    # Missing schema cannot fall back to stripping legitimate data.
    before = document.read_bytes()
    result = subprocess.run([sys.executable,str(ADAPTER),'strip-nulls',str(document),
                             '--schema',str(tmp_path/'missing.json')],capture_output=True,text=True)
    assert result.returncode == 3
    assert document.read_bytes() == before


def test_command_missing_exit_rejected_before_normalization():
    bad = verdict({k:v for k,v in COMMAND.items() if k != 'exit_code'})
    validator = Draft202012Validator(json.loads(SCHEMA.read_text(encoding='utf-8')))
    assert not validator.is_valid(bad)
