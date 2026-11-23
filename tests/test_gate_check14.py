"""tools/gate.py check 14 on a mixed-version corpus (B27): SOA_TABLES_ACCEPTED_PROMPTS lists prompt
versions reported INFO instead of FAIL; unset keeps the strict rule; a missing model still FAILs."""

import importlib
import json
import sys

import pytest

from soa_tables import config

sys.path.insert(0, str(config.REPO_ROOT / "tools"))

FIXTURE = (config.REPO_ROOT / "tests" / "fixtures" / "protocols" / "NCT03637764" / "soa-tables"
           / "extracted" / "NCT03637764_Table_01_extraction.json")


def load_gate(monkeypatch, accepted):
    if accepted is None:
        monkeypatch.delenv("SOA_TABLES_ACCEPTED_PROMPTS", raising=False)
    else:
        monkeypatch.setenv("SOA_TABLES_ACCEPTED_PROMPTS", accepted)
    sys.modules.pop("gate", None)
    return importlib.import_module("gate")


@pytest.fixture(autouse=True)
def drop_gate():
    yield
    sys.modules.pop("gate", None)


def check14(gate, tmp_path, prompt_version, model="claude-opus-5-5"):
    data = json.loads(FIXTURE.read_text())
    data["extraction_metadata"]["prompt_version"] = prompt_version
    if model is None:
        data["extraction_metadata"].pop("model", None)
    else:
        data["extraction_metadata"]["model"] = model
    path = tmp_path / FIXTURE.name
    path.write_text(json.dumps(data))
    schema = json.loads(gate.SCHEMA.read_text())
    findings, _ = gate.check_table(path, schema, {})
    return [(level, msg) for name, level, msg in findings if name == "14 provenance"]


def test_repo_prompt_passes(monkeypatch, tmp_path):
    gate = load_gate(monkeypatch, None)
    assert check14(gate, tmp_path, gate.PROMPT_VERSION) == []


def test_old_version_fails_when_unset(monkeypatch, tmp_path):
    gate = load_gate(monkeypatch, None)
    assert [lvl for lvl, _ in check14(gate, tmp_path, "3.8.1")] == ["FAIL"]


def test_listed_version_is_info(monkeypatch, tmp_path):
    gate = load_gate(monkeypatch, "3.8.1, 3.9.4")
    assert check14(gate, tmp_path, "3.8.1") == [
        ("INFO", "prompt_version='3.8.1' accepted by SOA_TABLES_ACCEPTED_PROMPTS")]


def test_unlisted_version_still_fails(monkeypatch, tmp_path):
    gate = load_gate(monkeypatch, "3.8.1")
    assert [lvl for lvl, _ in check14(gate, tmp_path, "3.9.3")] == ["FAIL"]


def test_missing_model_fails_even_when_listed(monkeypatch, tmp_path):
    gate = load_gate(monkeypatch, "3.8.1")
    found = check14(gate, tmp_path, "3.8.1", model=None)
    assert ("FAIL", "model not stamped — run tools/stamp_model.py") in found


def test_malformed_env_value_exits(monkeypatch):
    with pytest.raises(SystemExit, match="not a prompt version"):
        load_gate(monkeypatch, "3.8.1,latest")
