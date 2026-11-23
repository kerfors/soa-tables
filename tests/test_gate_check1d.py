"""tools/gate.py check 1d (B39): one activity or property row per row_position in a table."""

import importlib
import json
import sys

import pytest

from soa_tables import config

sys.path.insert(0, str(config.REPO_ROOT / "tools"))

FIXTURE = (config.REPO_ROOT / "tests" / "fixtures" / "protocols" / "NCT03637764" / "soa-tables"
           / "extracted" / "NCT03637764_Table_01_extraction.json")


@pytest.fixture
def gate():
    sys.modules.pop("gate", None)
    yield importlib.import_module("gate")
    sys.modules.pop("gate", None)


def check1d(gate, tmp_path, data):
    path = tmp_path / FIXTURE.name
    path.write_text(json.dumps(data))
    schema = json.loads(gate.SCHEMA.read_text())
    findings, _ = gate.check_table(path, schema, {})
    return [(level, msg) for name, level, msg in findings if name == "1d rows"]


def test_fixture_passes(gate, tmp_path):
    assert check1d(gate, tmp_path, json.loads(FIXTURE.read_text())) == []


def test_two_activities_on_one_row_fail(gate, tmp_path):
    data = json.loads(FIXTURE.read_text())
    a, b = data["activities"][0], data["activities"][1]
    b["row_position"] = a["row_position"]
    assert check1d(gate, tmp_path, data) == [
        ("FAIL", f"row_position held by more than one activity/property row: [{a['row_position']}]")]


def test_activity_on_a_property_row_fails(gate, tmp_path):
    data = json.loads(FIXTURE.read_text())
    r = data["schedule_properties"][0]["row_position"]
    data["activities"][0]["row_position"] = r
    assert check1d(gate, tmp_path, data) == [
        ("FAIL", f"row_position held by more than one activity/property row: [{r}]")]
