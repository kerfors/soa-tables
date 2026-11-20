"""
Identity rule (documents/identity.md): IRIs minted by code from printed position.

Step-2 check of the soa-tables plan: for every protocol with resolved + consolidated JSON, in every registered
collection (the banked fixtures included), minting twice from the same input gives the same set of local ids, and no
two elements share a local id. Reads the committed files; runs no pipeline step.
"""
import json
from pathlib import Path

import pytest

from soa_tables import config
from soa_tables import identity as I


def discover_cases():
    cases = []
    for collection, protocols_dir in config.COLLECTIONS.items():
        if not Path(protocols_dir).is_dir():
            continue
        for d in sorted(p for p in Path(protocols_dir).iterdir() if p.is_dir() and not p.name.startswith(".")):
            soa = d / "SoA2USDM"
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
