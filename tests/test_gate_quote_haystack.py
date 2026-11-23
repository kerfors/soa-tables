"""tools/gate.py quote check (B19): the extraction's own prose is not evidence for a quote."""

import importlib
import sys

import pytest

from soa_tables import config

sys.path.insert(0, str(config.REPO_ROOT / "tools"))


@pytest.fixture
def gate():
    sys.modules.pop("gate", None)
    yield importlib.import_module("gate")
    sys.modules.pop("gate", None)


def test_prose_keys_are_left_out(gate):
    data = {
        "table_metadata": {"table_title": "Schedule of Activities", "notes": "agent note"},
        "schedule_properties": [{"property_name": "Week", "property_comment": "agent reasoning"}],
        "review_items": [{"call_made": "Row 'A / B' is typed week", "alternative": "other"}],
        "extraction_metadata": {"extractor": "agent"},
        "annotations": [{"annotation_text": "Printed note.", "marker_locations": [{"note": "agent"}]}],
    }
    acc = []
    gate.transcribed_strings(data, acc)
    assert acc == ["Schedule of Activities", "Week", "Printed note."]


def test_json_strings_still_reads_everything(gate):
    acc = []
    gate.json_strings({"review_items": [{"call_made": "x"}], "notes": "y"}, acc)
    assert acc == ["x", "y"]
