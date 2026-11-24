"""B34: each review page in the collections tree shows the review status its sidecars give.

A review page that was reverted as 'timestamp-only' while its decisions had changed shows
items open that a sidecar has decided (found 2026-11-23 on NCT03739203 and NCT04304508). The
page embeds `D.review_status`; corrections.review_status() derives the same counts from the
extracted/ folder. Skips when no collections checkout is present.
"""

import json
import re

import pytest

from soa_tables import config
from soa_tables.corrections import review_status


def _pages():
    for collection in sorted(c for c in config.COLLECTIONS if c != "fixtures"):
        for protocol_id in config.list_extractable_protocols(collection):
            page = config.get_extracted_dir(protocol_id, collection) / f"{protocol_id}_review.html"
            if page.exists():
                yield pytest.param(page, id=f"{collection}/{protocol_id}")


@pytest.mark.parametrize("page", list(_pages()))
def test_review_page_status_matches_the_sidecars(page):
    text = page.read_text(encoding="utf-8")
    m = re.search(r"\bconst D = ", text)
    assert m, f"{page.name}: no embedded D"
    d, _ = json.JSONDecoder().raw_decode(text, m.end())
    status = review_status(page.parent)
    assert d["review_status"] == {k: status[k] for k in ("total", "open", "decided")}
