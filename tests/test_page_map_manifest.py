"""tools/page_map.py: soa_pages as one range or several comma-separated ranges (parse_soa_pages), and every
collection's studies_protocols.xlsx parses under it."""

import sys
from pathlib import Path

import pytest

from soa_tables import config

sys.path.insert(0, str(config.REPO_ROOT / "tools"))
import page_map  # noqa: E402


@pytest.mark.parametrize("value, spans", [
    ("13-18", [(13, 18)]),
    ("5", [(5, 5)]),
    (5, [(5, 5)]),
    ("16-18,85-87", [(16, 18), (85, 87)]),
    (" 16-18 , 85-87 ", [(16, 18), (85, 87)]),
    ("3,9-10,40", [(3, 3), (9, 10), (40, 40)]),
])
def test_parse_soa_pages(value, spans):
    assert page_map.parse_soa_pages(value) == spans


@pytest.mark.parametrize("value", ["18-16", "85-87,16-18", "16-18,17-20", "16-18,19-20", "16-18,", "a-b"])
def test_parse_soa_pages_refuses(value):
    with pytest.raises(ValueError):
        page_map.parse_soa_pages(value)


def collections():
    return sorted(c for c, p in config.COLLECTIONS.items()
                  if c != "fixtures" and (Path(p).parent / "studies_protocols.xlsx").is_file())


def test_collections_found():
    if not collections():
        pytest.skip("collections not checked out")


@pytest.mark.parametrize("collection", collections())
def test_every_manifest_parses(collection):
    pytest.importorskip("openpyxl")
    manifest, _ = page_map.read_manifest(collection)
    for study, spans in manifest.items():
        assert spans and all(a <= b for a, b in spans), study
