"""pages.json physical_page: on every entry; where the file of record is local, the page whose text (or, for a
page without text, 20-dpi grey bitmap) equals the excerpt page — the rule tools/page_map.py --physical writes by.

The presence check runs on any checkout of the collections; the file-of-record check skips per protocol where the
full PDF is not local (gitignored), as test_register_sha256_equals_the_local_file_of_record does.
"""

import json
import sys
from pathlib import Path

import pytest

from soa_tables import config

sys.path.insert(0, str(config.REPO_ROOT / "tools"))
import page_map  # noqa: E402


def pages_files():
    out = []
    for collection, protocols in config.COLLECTIONS.items():
        if collection == "fixtures" or not Path(protocols).is_dir():
            continue
        out += sorted(Path(protocols).glob("*/*_soa_pages/pages.json"))
    return out


PAGES = pages_files()
IDS = [f"{p.parents[3].name}/{p.parents[1].name}" for p in PAGES]


def test_pages_json_found():
    if not PAGES:
        pytest.skip("collections not checked out")


@pytest.mark.parametrize("pages_json", PAGES, ids=IDS)
def test_every_entry_has_a_physical_page(pages_json):
    for e in json.loads(pages_json.read_text())["pages"]:
        assert isinstance(e.get("physical_page"), int) and e["physical_page"] >= 1, e


@pytest.mark.parametrize("pages_json", PAGES, ids=IDS)
def test_physical_page_is_the_page_of_the_file_of_record(pages_json):
    proto = pages_json.parents[1]
    pid = proto.name
    full = proto / f"{pid}.pdf"
    if not full.is_file():
        pytest.skip("no local file of record (full PDFs are gitignored)")
    soa = proto / f"{pid}_soa.pdf"
    for e in json.loads(pages_json.read_text())["pages"]:
        text = page_map._norm_text(soa, e["pdf_page"])
        if text:
            assert page_map._norm_text(full, e["physical_page"]) == text, e
        else:
            assert page_map._bitmap(full, e["physical_page"]) == page_map._bitmap(soa, e["pdf_page"]), e
