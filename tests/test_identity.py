"""
Identity rule (documents/identity.md): IRIs minted by code from printed position.

Step-2 check of the soa-tables plan: for every protocol with resolved + consolidated JSON, in every registered
collection (the banked fixtures included), minting twice from the same input gives the same set of local ids, and no
two elements share a local id. Reads the committed files; runs no pipeline step.
"""
import copy
import json
from pathlib import Path

import pytest

from soa_tables import config
from soa_tables import identity as I
from soa_tables import visualize as V
from soa_tables.consolidation_corrections import corrections_path


def discover_cases():
    cases = []
    for collection, protocols_dir in config.COLLECTIONS.items():
        if not Path(protocols_dir).is_dir():
            continue
        for d in sorted(p for p in Path(protocols_dir).iterdir() if p.is_dir() and not p.name.startswith(".")):
            soa = d / "soa-tables"
            if (list((soa / "resolved").glob("*_resolved.json"))
                    and list((soa / "consolidated").glob("*_consolidated.json"))):
                cases.append((collection, d.name, soa))
    return cases


CASES = discover_cases()


def load(soa: Path):
    resolved = [json.loads(f.read_text()) for f in sorted((soa / "resolved").glob("*_resolved.json"))]
    consolidated = json.loads(next((soa / "consolidated").glob("*_consolidated.json")).read_text())
    return resolved, consolidated


@pytest.mark.parametrize("case", CASES, ids=[f"{c}/{p}" for c, p, _ in CASES])
def test_mints_the_same_set_twice_without_collisions(case):
    _, _, soa = case
    resolved, consolidated = load(soa)
    first = I.mint_protocol(resolved, consolidated)
    second = I.mint_protocol(*load(soa))
    assert first, "no local ids minted"
    assert first == second


def test_every_local_id_is_an_iri_segment():
    for _, _, soa in CASES:
        for lid in I.mint_protocol(*load(soa)):
            I.segment(lid)


def test_repeated_marker_gets_its_first_row():
    """NCT03861273 prints '*' and '#' for several notes per table (cell_gene_therapy; needs the collections)."""
    hits = [soa for c, p, soa in CASES if p == "NCT03861273"]
    if not hits:
        pytest.skip("NCT03861273 not present (collections not checked out)")
    resolved, _ = load(hits[0])
    ids = set().union(*(I.mint_table(r)["annotations"].values() for r in resolved))
    assert any(i.startswith("t01-n-x2a-r") for i in ids)
    assert any(i.startswith("t01-n-x23-r") for i in ids)


def test_marker_segment():
    assert I.marker_segment("c18_2") == "c18_2"
    assert I.marker_segment("*") == "x2a"
    assert I.marker_segment("#") == "x23"
    assert I.marker_segment("£") == "xa3"
    with pytest.raises(ValueError):
        I.marker_segment("")


def test_padding_fails_when_a_number_does_not_fit():
    assert I.row_id(1, 26) == "t01-r026"
    assert I.column_id(2, 5) == "t02-c005"
    assert I.cell_id(1, 26, 5) == "t01-r026-c005"
    with pytest.raises(ValueError):
        I.table_id(100)
    with pytest.raises(ValueError):
        I.row_id(1, 1000)
    with pytest.raises(ValueError):
        I.row_id(1, 0)


def test_iri_templates():
    hexdigest = I.sha256_file(Path(config.REPO_ROOT) / "LICENSE")
    m = I.file_iri(hexdigest)
    assert m == f"{I.BASE}sha256/{hexdigest}"
    assert I.page_iri(m, 53) == f"{m}/page/53"
    assert I.element_iri(m, "t01-r026") == f"{m}/soa-tables-v1/t01-r026"
    assert I.study_iri("CDISC_Pilot") == f"{I.BASE}study/CDISC_Pilot"
    with pytest.raises(ValueError):
        I.file_iri(hexdigest.upper())
    with pytest.raises(ValueError):
        I.file_iri(hexdigest[:63])


# =============================================================================
# New kinds: unified property, parts of an item, review items, transcription
# =============================================================================

def load_all(soa: Path):
    """resolved, consolidated, match items and sidecar, read as visualize reads them for the matches section."""
    resolved, consolidated = load(soa)
    row_names = {(r["table_metadata"]["table_number"], a["activity_id"]): a["activity_name"]
                 for r in resolved for a in r["activities"]}
    sidecar = corrections_path(soa / "consolidated", soa.parent.name)
    corrections_doc = json.loads(sidecar.read_text()) if sidecar.exists() else None
    items = V.build_matches_model(consolidated, row_names, corrections_doc)["items"]
    return resolved, consolidated, items, corrections_doc


def all_ids(minted: dict) -> list:
    ids = []
    for m in minted["tables"].values():
        ids.append(m["table"])
        for k in ("rows", "columns", "annotations", "cells"):
            ids.extend(m[k].values())
    for k in ("activities", "columns", "annotations", "cells"):
        ids.extend(minted["consolidated"][k].values())
    for k in ("properties", "property_values", "document_references", "decisions"):
        ids.extend(minted[k].values())
    return ids + minted["matches"]


@pytest.mark.parametrize("case", CASES, ids=[f"{c}/{p}" for c, p, _ in CASES])
def test_mint_all_twice_without_collisions_and_old_ids_unchanged(case):
    _, _, soa = case
    resolved, consolidated, items, doc = load_all(soa)
    first = I.mint_all(resolved, consolidated, items, doc)
    assert first == I.mint_all(*load_all(soa))
    ids = all_ids(first)
    assert len(ids) == len(set(ids))
    new = (len(first["properties"]) + len(first["property_values"]) + len(first["document_references"])
           + len(first["matches"]) + len(first["decisions"]))
    old = I.mint_protocol(resolved, consolidated)
    assert old <= set(ids) and len(ids) == len(old) + new
    assert set(first["properties"]) == {p["property_id"] for p in consolidated["property_hierarchy"]}
    assert len(first["property_values"]) == sum(len(c["property_values"])
                                                for seg in consolidated["timeline_segments"].values() for c in seg)
    assert len(first["document_references"]) == sum(len(a.get("document_references", []))
                                                    for a in consolidated["unified_annotations"])
    assert len(first["matches"]) == len(items)
    assert len(first["decisions"]) == (len(doc["corrections"]) if doc else 0)
    for lid in ids:
        I.segment(lid)


def first_case_with(predicate):
    for _, _, soa in CASES:
        loaded = load_all(soa)
        if predicate(*loaded):
            return loaded
    pytest.skip("no protocol with that feature present")


def test_unified_property_id_that_does_not_name_its_anchor_stops_minting():
    resolved, consolidated, items, doc = first_case_with(lambda r, c, i, d: c["property_hierarchy"])
    broken = copy.deepcopy(consolidated)
    broken["property_hierarchy"][0]["property_id"] = "prop-999"
    with pytest.raises(ValueError, match="does not name its anchor"):
        I.mint_all(resolved, broken, items, doc)


def test_unified_property_without_member_stops_minting():
    resolved, consolidated, items, doc = first_case_with(lambda r, c, i, d: c["property_hierarchy"])
    broken = copy.deepcopy(consolidated)
    broken["property_hierarchy"].append({**broken["property_hierarchy"][0], "property_id": "prop-998",
                                          "hierarchical_level": 99})
    with pytest.raises(ValueError, match="keys differ"):
        I.mint_all(resolved, broken, items, doc)


def test_two_matches_on_the_same_pair_stop_minting():
    resolved, consolidated, items, doc = first_case_with(lambda r, c, i, d: i)
    with pytest.raises(ValueError, match="matches"):
        I.mint_all(resolved, consolidated, items + [dict(items[0], source=items[0]["target"],
                                                          target=items[0]["source"])], doc)


def test_part_and_review_ids():
    assert I.property_value_id("u-t01-c005", 1) == "u-t01-c005-v01"
    assert I.document_reference_id("u-t01-n-a", 3) == "u-t01-n-a-d03"
    with pytest.raises(ValueError):
        I.property_value_id("u-t01-c005", 100)
    with pytest.raises(ValueError):
        I.document_reference_id("u-t01-n-a", 0)
    assert I.match_id("t02-r004", "t01-r012") == "match-t01-r012--t02-r004"
    assert I.match_id("t01-r012", "t02-r004") == "match-t01-r012--t02-r004"
    with pytest.raises(ValueError):
        I.match_id("t01-r012", "t01-r012")
    assert I.decision_id("ccorr-003") == "decision-ccorr-003"
    with pytest.raises(ValueError):
        I.decision_id("ccorr 003")


def test_transcription_iri():
    m = I.file_iri("0" * 64)
    assert I.transcription_iri(m) == f"{m}/soa-tables-v1"
    assert I.element_iri(m, "t01").startswith(I.transcription_iri(m) + "/")
