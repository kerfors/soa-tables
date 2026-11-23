"""Bands below the table frame are not candidate rows (B10).

A row band can be closed by a line outside the table — a hyperlink underline in the footnotes
(NCT04304508 p.14) or the page-footer rule (NCT03283098 p.32). page_grid's frame_bottom is
where the table's vertical rules end; the row audit files a short unmatched band under it as
below_frame instead of on_page_not_extracted. Negative control: NCT04627038 p.12, where a
full-width redaction bar breaks every vertical rule and real rows follow under it.

Needs the gitignored _soa.pdf excerpts; skipped without them, like the other PDF tests.
"""
import shutil

import pytest

from soa_tables import config
from soa_tables.row_audit import FRAME_TOL_PT, audit_protocol, normalise, read_page

POPPLER = all(shutil.which(tool) for tool in ("pdftoppm", "pdftotext", "pdfinfo"))


def soa_pdf(protocol_id, collection):
    pdf = config.find_soa_pdf(protocol_id, collection) if POPPLER else None
    if pdf is None:
        pytest.skip(f"needs poppler and {protocol_id}_soa.pdf")
    return pdf


def band(read, text):
    rows = [r for r in read.rows if any(normalise(text) in normalise(t) for t in r.texts)]
    assert len(rows) == 1, f"{len(rows)} bands print {text!r}"
    return rows[0]


def below(read, row):
    return row.y0 >= read.frame_bottom - FRAME_TOL_PT


def test_footnote_underline_band_is_below_the_frame():
    read = read_page(soa_pdf("NCT04304508", "misc_studies"), 4)
    assert not below(read, band(read, "Genetics"))
    assert below(read, band(read, "most recent"))


def test_page_footer_band_is_below_the_frame():
    read = read_page(soa_pdf("NCT03283098", "usdm_data"), 1)
    assert not below(read, band(read, "Concomitant Medications"))
    assert below(read, band(read, "Footnotes displayed"))


def test_rows_under_a_redaction_bar_stay_in_the_frame():
    read = read_page(soa_pdf("NCT04627038", "cpmp"), 4)
    assert not below(read, band(read, "Participant returns"))


def test_audit_files_the_band_as_below_frame():
    soa_pdf("NCT04304508", "misc_studies")
    table2 = next(t for t in audit_protocol("NCT04304508", "misc_studies")["tables"]
                  if t["table_number"] == 2)
    assert [b["text"] for b in table2["below_frame"]] == ["most recent"]
    assert table2["on_page_not_extracted"] == []
