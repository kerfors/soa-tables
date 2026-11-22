"""B22: a consolidated JSON that cannot be read fails the index step instead of being skipped silently
(the index row lost its stats and nothing reported it)."""

import json

import pytest

from soa_tables import config
from soa_tables.index_generator import discover_protocol_outputs


@pytest.fixture
def protocol(tmp_path, monkeypatch):
    monkeypatch.setitem(config.COLLECTIONS, "tmpc", tmp_path)
    soa = tmp_path / "P1" / "soa-tables"
    (soa / "consolidated").mkdir(parents=True)
    return soa


def test_index_stats_unreadable_consolidated_json_raises(protocol):
    (protocol / "consolidated" / "P1_consolidated.html").write_text("<html></html>\n")
    (protocol / "consolidated" / "P1_consolidated.json").write_text("{not json\n")
    with pytest.raises(json.JSONDecodeError):
        discover_protocol_outputs("P1", "tmpc")

