"""B20: the extractor's report is '<pid>[_<name>]_extraction_log.md'. For one release the old name
'_uncertainty_report.md' is still read (B36); either way the page is rendered to, and linked as,
'_extraction_log.html', and the new name wins where both exist."""

import pytest

from soa_tables import config
from soa_tables.index_generator import discover_protocol_outputs
from soa_tables.nav import discover_siblings


@pytest.fixture
def extracted(tmp_path, monkeypatch):
    monkeypatch.setitem(config.COLLECTIONS, "tmpc", tmp_path)
    ext = tmp_path / "P1" / "soa-tables" / "extracted"
    ext.mkdir(parents=True)
    return ext


def test_new_name_rendered_and_linked(extracted):
    (extracted / "P1_extraction_log.md").write_text("# new\n")
    out = discover_protocol_outputs("P1", "tmpc")
    assert out["report_file"] == "P1/soa-tables/extracted/P1_extraction_log.html"
    assert (extracted / "P1_extraction_log.html").exists()
    assert discover_siblings("P1", "tmpc")["logs"] == [(None, "soa-tables/extracted/P1_extraction_log.html")]


def test_old_name_rendered_under_new_name(extracted):
    (extracted / "P1_uncertainty_report.md").write_text("# old\n")
    out = discover_protocol_outputs("P1", "tmpc")
    assert out["report_file"] == "P1/soa-tables/extracted/P1_extraction_log.html"
    assert not (extracted / "P1_uncertainty_report.html").exists()
    assert discover_siblings("P1", "tmpc")["logs"] == [(None, "soa-tables/extracted/P1_extraction_log.html")]


def test_new_name_wins_over_old(extracted):
    (extracted / "P1_uncertainty_report.md").write_text("# old\n")
    (extracted / "P1_extraction_log.md").write_text("# new\n")
    discover_protocol_outputs("P1", "tmpc")
    assert "new" in (extracted / "P1_extraction_log.html").read_text()


def test_further_logs_both_names(extracted):
    (extracted / "P1_extraction_log.md").write_text("# own\n")
    (extracted / "P1_flowcharts_uncertainty_report.md").write_text("# old extra\n")
    (extracted / "P1_second_extraction_log.md").write_text("# new extra\n")
    out = discover_protocol_outputs("P1", "tmpc")
    assert out["extra_reports"] == [
        ("flowcharts", "P1/soa-tables/extracted/P1_flowcharts_extraction_log.html"),
        ("second", "P1/soa-tables/extracted/P1_second_extraction_log.html"),
    ]
    assert discover_siblings("P1", "tmpc")["logs"] == [
        (None, "soa-tables/extracted/P1_extraction_log.html"),
        ("flowcharts", "soa-tables/extracted/P1_flowcharts_extraction_log.html"),
        ("second", "soa-tables/extracted/P1_second_extraction_log.html"),
    ]
