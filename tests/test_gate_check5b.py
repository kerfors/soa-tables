"""tools/gate.py check 5b (B46 d): a pointer printed over a whole column or a whole row."""

import importlib
import json
import sys

import pytest

from soa_tables import config

sys.path.insert(0, str(config.REPO_ROOT / "tools"))

# NCT03637764 Table 1 prints 'See ... Flow Chart' across every data column of rows 28-30;
# the banked fixture keeps them as schedule entries (the shape before the §5 rule).
FIXTURE = (config.REPO_ROOT / "tests" / "fixtures" / "protocols" / "NCT03637764" / "soa-tables"
           / "extracted" / "NCT03637764_Table_01_extraction.json")


@pytest.fixture
def gate():
    sys.modules.pop("gate", None)
    yield importlib.import_module("gate")
    sys.modules.pop("gate", None)


def check5b(gate, tmp_path, data):
    path = tmp_path / FIXTURE.name
    path.write_text(json.dumps(data))
    schema = json.loads(gate.SCHEMA.read_text())
    findings, _ = gate.check_table(path, schema, {})
    return [(level, msg.split(":")[0]) for name, level, msg in findings if name == "5b pointer span"]


def test_whole_row_pointers_are_flagged(gate, tmp_path):
    assert check5b(gate, tmp_path, json.loads(FIXTURE.read_text())) == [
        ("CHECK", "row 28"), ("CHECK", "row 29"), ("CHECK", "row 30")]


def test_repeated_text_that_is_not_a_pointer_is_not_flagged(gate, tmp_path):
    data = json.loads(FIXTURE.read_text())
    for e in data["activity_schedule"]:
        if e["row_position"] in (28, 29, 30):
            e["cell_value"] = "Ongoing"
    assert check5b(gate, tmp_path, data) == []


def test_a_pointer_down_a_whole_column_is_flagged(gate, tmp_path):
    data = json.loads(FIXTURE.read_text())
    col = 2
    rows = [a["row_position"] for a in data["activities"] if not a.get("is_section_header")]
    data["activity_schedule"] = [e for e in data["activity_schedule"] if e["column_position"] != col]
    data["activity_schedule"] += [{"table_number": 1, "row_position": r, "column_position": col,
                                   "cell_value": "Refer to the country amendment", "source_range": ""}
                                  for r in rows]
    assert ("CHECK", f"column {col}") in check5b(gate, tmp_path, data)
