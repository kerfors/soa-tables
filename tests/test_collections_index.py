"""Root index of the collections repo (soa_tables.collections_index): the Data section and its links.

Runs against the collections checkout (register.csv at its root); skips without it.
"""

import csv
import re

import pytest

from soa_tables import config
from soa_tables.collections_index import generate_collections_index_html

ROOT = config.COLLECTIONS_ROOT.parent
needs_collections = pytest.mark.skipif(not (ROOT / "register.csv").is_file(), reason="collections not checked out")


@needs_collections
def test_data_section_relative_links_resolve():
    html = generate_collections_index_html()
    assert "<h2>Data</h2>" in html
    rel = [h for h in re.findall(r'href="([^"]+)"', html) if not h.startswith(("http://", "https://", "#"))]
    assert "register.csv" in rel and "LICENSE-CONTENT" in rel
    assert [h for h in rel if not (ROOT / h).is_file()] == []


@needs_collections
def test_trig_path_rule_on_the_page_holds_for_every_registered_protocol():
    rows = list(csv.DictReader((ROOT / "register.csv").open(encoding="utf-8")))
    assert rows
    for r in rows:
        if r["excluded_reason"]:
            continue
        key = r["protocol_key"]
        assert (ROOT / "collections" / r["collection"] / "protocols" / key / "soa-tables" / "rdf"
                / f"{key}_facts.trig").is_file(), r
