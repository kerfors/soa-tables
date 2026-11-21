"""
RDF interface (soa_tables/rdf.py; fact model schemas/rdf/soa-tables-facts.shacl.ttl): step-4 checks of the
soa-tables plan, written before the code ran.

Per protocol with a consolidated JSON in the collections (the fixtures hold no file of record, so they are no case):
  P1 consolidated JSON -> TriG -> JSON gives the canonical JSON back; a field on no list (STORED, DERIVED, OUT) stops
  P2 the graph conforms to the closed shapes
  P3 two builds give byte-identical TriG; every element IRI is a minted local id, and every minted id is used
  P4 open / total matches in the graph = the consolidated page's (visualize.build_matches_model) = review_stats
  P5 every activity row has one page, inside its table's page range; property rows have none
P8, per collection: every protocol folder without a consolidated JSON has an excluded_reason in studies_protocols.xlsx.
The commits pinned on the transcription are fixed strings here; rdf.build_trig reads them from git.
Step 5 (section at the end): register.csv at the collections repo root, and the committed TriG per protocol.
"""
import copy
import functools
import shutil
import subprocess
from pathlib import Path

import pytest

rdflib = pytest.importorskip("rdflib")
pyshacl = pytest.importorskip("pyshacl")

from rdflib import RDF, Graph  # noqa: E402

from soa_tables import config  # noqa: E402
from soa_tables import identity as I  # noqa: E402
from soa_tables import rdf as R  # noqa: E402

ST = R.ST
SH = rdflib.Namespace("http://www.w3.org/ns/shacl#")
COMMITS = ("a" * 40, "b" * 40)


def discover_cases():
    cases = []
    for collection, protocols_dir in config.COLLECTIONS.items():
        if collection == "fixtures" or not Path(protocols_dir).is_dir():
            continue
        for d in sorted(p for p in Path(protocols_dir).iterdir() if p.is_dir() and not p.name.startswith(".")):
            if (d / "soa-tables" / "consolidated" / f"{d.name}_consolidated.json").exists():
                cases.append((collection, d.name, d / "soa-tables"))
    return cases


CASES = discover_cases()
IDS = [f"{c}/{p}" for c, p, _ in CASES]


def case_inputs(soa: Path) -> dict:
    """load_inputs with the file of record when it is local, else with the sha256 register.csv records for it."""
    pid = soa.parent.name
    if (soa.parent / f"{pid}.pdf").is_file():
        return R.load_inputs(soa)
    return R.load_inputs(soa, sha256=register_by_key()[(soa.parents[2].name, pid)]["sha256"])


@functools.lru_cache(maxsize=None)
def built(soa: Path):
    inp = case_inputs(soa)
    ds = R.build_dataset(inp, *COMMITS)
    minted = I.mint_all(inp["resolved"], inp["consolidated"], inp["items"], inp["corrections_doc"])
    return inp, ds, R.to_trig(ds), minted


@pytest.fixture(scope="module")
def shapes():
    return Graph().parse(R.SHAPES, format="turtle")


def all_local_ids(minted: dict) -> set:
    ids = set(minted["matches"])
    for m in minted["tables"].values():
        ids.add(m["table"])
        for k in ("rows", "columns", "annotations", "cells"):
            ids.update(m[k].values())
    for k in ("activities", "columns", "annotations", "cells"):
        ids.update(minted["consolidated"][k].values())
    for k in ("properties", "property_values", "document_references", "decisions"):
        ids.update(minted[k].values())
    return ids


# ---------------------------------------------------------------- P1-P5 per protocol

@pytest.mark.parametrize("case", CASES, ids=IDS)
def test_p1_round_trip(case):
    inp, _, trig, minted = built(case[2])
    original = R.canonical(inp["consolidated"], inp["resolved"], minted)
    rebuilt = R.graph_to_json(R.parse_trig(trig))
    assert original == rebuilt, R.differences(original, rebuilt)


@pytest.mark.parametrize("case", CASES, ids=IDS)
def test_p2_graph_conforms_to_the_shapes(case, shapes):
    _, ds, _, _ = built(case[2])
    conforms, results, text = pyshacl.validate(R.transcription_graph(ds), shacl_graph=shapes, inference="none")
    assert conforms, text[:2000]


@pytest.mark.parametrize("case", CASES, ids=IDS)
def test_p3_two_builds_identical_and_every_iri_minted(case):
    inp, ds, trig, minted = built(case[2])
    assert R.to_trig(R.build_dataset(case_inputs(case[2]), *COMMITS)) == trig
    g = R.transcription_graph(ds)
    prefix = str(g.identifier) + "/"
    elements = {str(s)[len(prefix):] for s in g.subjects() if str(s).startswith(prefix)}
    assert elements == all_local_ids(minted)


@pytest.mark.parametrize("case", CASES, ids=IDS)
def test_p4_open_matches_equal_the_page(case):
    inp, ds, _, _ = built(case[2])
    status = [str(o) for o in R.transcription_graph(ds).objects(None, ST.reviewStatus)]
    page = (sum(1 for i in inp["items"] if not i["decision"]), len(inp["items"]))
    stats = inp["consolidated"]["consolidation_metadata"]["review_stats"]
    assert (status.count("open"), len(status)) == page == (stats["open"], stats["total"])


@pytest.mark.parametrize("case", CASES, ids=IDS)
def test_p5_every_activity_row_has_one_page_in_its_table_range(case):
    _, ds, _, _ = built(case[2])
    g = R.transcription_graph(ds)

    def number(page):
        return int(g.value(page, ST.pageNumber))

    rows = list(g.subjects(RDF.type, ST.SourceActivityRow))
    assert rows
    for row in rows:
        pages = list(g.objects(row, ST.onPage))
        table = g.value(row, ST.inTable)
        assert len(pages) == 1, row
        assert number(g.value(table, ST.firstPage)) <= number(pages[0]) <= number(g.value(table, ST.lastPage)), row
    assert [row for row in g.subjects(RDF.type, ST.SourcePropertyRow) if list(g.objects(row, ST.onPage))] == []


@pytest.mark.parametrize("case", CASES, ids=IDS)
def test_decisions_equal_the_sidecar(case):
    """Op, reason, by and at as the sidecar writes them (at keeps its Z through TriG)."""
    inp, _, trig, minted = built(case[2])
    doc = inp["corrections_doc"]
    if not doc:
        pytest.skip("no consolidation corrections")
    g = R.transcription_graph(R.parse_trig(trig))
    m = str(g.identifier).rsplit("/", 1)[0]
    for e in doc["corrections"]:
        node = rdflib.URIRef(I.element_iri(m, minted["decisions"][e["id"]]))
        assert str(g.value(node, ST.op)) == e["op"]
        assert str(g.value(node, ST.reason)) == e["reason"]
        assert str(g.value(node, ST.decidedByPerson)) == e["by"]
        assert str(g.value(node, ST.decidedAt)) == e["at"]


# ---------------------------------------------------------------- P8 per collection

@pytest.mark.parametrize("collection", sorted(c for c in config.COLLECTIONS if c != "fixtures"
                                              and Path(config.COLLECTIONS[c]).is_dir()))
def test_p8_folder_without_consolidated_file_has_excluded_reason(collection):
    openpyxl = pytest.importorskip("openpyxl")
    protocols = Path(config.COLLECTIONS[collection])
    rows = list(openpyxl.load_workbook(protocols.parent / "studies_protocols.xlsx", read_only=True)["studies"]
                .iter_rows(values_only=True))
    header = rows[0]
    reason = {r[header.index("nct_id")]: r[header.index("excluded_reason")] for r in rows[1:]}
    missing = [d.name for d in sorted(protocols.iterdir()) if d.is_dir() and not d.name.startswith(".")
               and not (d / "soa-tables" / "consolidated" / f"{d.name}_consolidated.json").exists()]
    assert [p for p in missing if not reason.get(p)] == []


# ---------------------------------------------------------------- failures

def first_case():
    if not CASES:
        pytest.skip("collections not checked out")
    return CASES[0]


def test_missing_file_of_record_stops(tmp_path):
    soa = tmp_path / "NCT00000000" / "soa-tables"
    soa.mkdir(parents=True)
    with pytest.raises(FileNotFoundError, match="file of record"):
        R.load_inputs(soa)


def test_field_on_no_list_stops():
    inp, _, _, minted = built(first_case()[2])
    broken = copy.deepcopy(inp["consolidated"])
    broken["unified_activities"][0]["new_field"] = 1
    with pytest.raises(ValueError, match="on no list"):
        R.canonical(broken, inp["resolved"], minted)


def test_commit_must_be_40_hex():
    inp, _, _, _ = built(first_case()[2])
    with pytest.raises(ValueError, match="40-character commit"):
        R.build_dataset(inp, "HEAD", COMMITS[1])


def test_numbers_and_datetimes_keep_their_lexical_form():
    ds = rdflib.Dataset()
    g = ds.graph(rdflib.URIRef("https://example.org/g"))
    s = rdflib.URIRef("https://example.org/s")
    g.add((s, ST.score, R._decimal(0.8666666666666667)))
    g.add((s, ST.decidedAt, R._datetime("2026-10-04T08:20:00Z")))
    back = R.transcription_graph(R.parse_trig(R.to_trig(ds)))
    assert float(back.value(s, ST.score).toPython()) == 0.8666666666666667
    assert str(back.value(s, ST.decidedAt)) == "2026-10-04T08:20:00Z"


def test_collections_commit_needs_tracked_unchanged_inputs(tmp_path):
    if shutil.which("git") is None:
        pytest.skip("git not on PATH")

    def git(*args):
        subprocess.run(["git", "-C", str(tmp_path), "-c", "user.name=t", "-c", "user.email=t@t", *args],
                       check=True, capture_output=True)

    git("init", "-q")
    tracked = tmp_path / "a.json"
    tracked.write_text("{}")
    git("add", "a.json")
    git("commit", "-q", "-m", "a")
    assert len(R.collections_commit([tracked])) == 40
    untracked = tmp_path / "b.json"
    untracked.write_text("{}")
    with pytest.raises(ValueError, match="not tracked"):
        R.collections_commit([tracked, untracked])
    tracked.write_text("[]")
    with pytest.raises(ValueError, match="changed since HEAD"):
        R.collections_commit([tracked])


# ---------------------------------------------------------------- step 5: register and committed TriG
# Run against the collections, no case on the fixtures. The register tests skip only when the collections root has
# no register.csv; the TriG tests skip only when no TriG is built at all. Once one TriG exists, every check runs and
# a partial build fails.

REGISTER = config.COLLECTIONS_ROOT.parent / "register.csv"
REGISTER_COLUMNS = ["collection", "protocol_key", "study_iri", "sha256", "file_iri", "source_file", "source_url",
                    "excluded_reason"]
TRIGS = sorted(config.COLLECTIONS_ROOT.glob("*/protocols/*/soa-tables/rdf/*_facts.trig"))
TRIG_IDS = [f"{t.parents[4].name}/{t.parents[2].name}" for t in TRIGS]


@functools.lru_cache(maxsize=None)
def register_rows():
    import csv
    if not CASES:
        pytest.skip("collections not checked out")
    if not REGISTER.is_file():
        pytest.skip(f"no register.csv at {REGISTER.parent}")
    with REGISTER.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        assert reader.fieldnames == REGISTER_COLUMNS
        return tuple(reader)


def register_by_key():
    return {(r["collection"], r["protocol_key"]): r for r in register_rows()}


def protocol_folders():
    return {(c, d.name) for c, protocols in config.COLLECTIONS.items() if c != "fixtures" and Path(protocols).is_dir()
            for d in Path(protocols).iterdir() if d.is_dir() and not d.name.startswith(".")}


def test_register_one_row_per_protocol_folder():
    rows = register_rows()
    keys = [(r["collection"], r["protocol_key"]) for r in rows]
    assert len(keys) == len(set(keys)), "a protocol is listed twice"
    folders = protocol_folders()
    assert sorted(folders - set(keys)) == [], "protocol folders without a register row"
    # A folder that holds only gitignored files is absent on a clone: such a row must be an excluded one.
    assert sorted(k for k in set(keys) - folders if not register_by_key()[k]["excluded_reason"]) == []


def test_register_iris_are_minted_from_the_row():
    for r in register_rows():
        assert len(r["sha256"]) == 64 and set(r["sha256"]) <= set("0123456789abcdef"), r["protocol_key"]
        assert r["file_iri"] == I.file_iri(r["sha256"]), r["protocol_key"]
        assert r["study_iri"] == I.study_iri(r["protocol_key"]), r["protocol_key"]


def test_register_sha256_equals_the_local_file_of_record():
    checked = 0
    for (collection, key), r in register_by_key().items():
        pdf = Path(config.COLLECTIONS[collection]) / key / f"{key}.pdf"
        if pdf.is_file():
            assert I.sha256_file(pdf) == r["sha256"], key
            checked += 1
    if not checked:
        pytest.skip("no local file of record (full PDFs are gitignored)")


def test_register_excluded_rows_have_no_transcription():
    for (collection, key), r in register_by_key().items():
        soa = Path(config.COLLECTIONS[collection]) / key / "soa-tables"
        has = (soa / "consolidated" / f"{key}_consolidated.json").exists()
        assert has != bool(r["excluded_reason"]), f"{key}: consolidated file and excluded_reason must exclude each other"


def test_trig_built_for_every_transcription():
    if not TRIGS:
        pytest.skip("no TriG built")
    built_for = {(t.parents[4].name, t.parents[2].name) for t in TRIGS}
    expected = {(c, p) for c, p, _ in CASES}
    assert built_for == expected
    assert {k for k, r in register_by_key().items() if not r["excluded_reason"]} == expected


def _pins(g):
    t = g.identifier
    return str(g.value(t, ST.collectionsCommit)), str(g.value(t, ST.codeCommit))


@pytest.mark.parametrize("trig", TRIGS, ids=TRIG_IDS)
def test_committed_trig_parses_conforms_and_round_trips(trig, shapes):
    soa = trig.parents[1]
    g = R.transcription_graph(R.parse_trig(trig.read_text(encoding="utf-8")))
    conforms, _, text = pyshacl.validate(g, shacl_graph=shapes, inference="none")
    assert conforms, text[:2000]
    inp = case_inputs(soa)
    minted = I.mint_all(inp["resolved"], inp["consolidated"], inp["items"], inp["corrections_doc"])
    original = R.canonical(inp["consolidated"], inp["resolved"], minted)
    rebuilt = R.graph_to_json(R.parse_trig(trig.read_text(encoding="utf-8")))
    assert original == rebuilt, R.differences(original, rebuilt)


@pytest.mark.parametrize("trig", TRIGS, ids=TRIG_IDS)
def test_committed_trig_equals_a_fresh_build(trig):
    soa = trig.parents[1]
    text = trig.read_text(encoding="utf-8")
    pins = _pins(R.transcription_graph(R.parse_trig(text)))
    assert R.to_trig(R.build_dataset(case_inputs(soa), *pins)) == text


@pytest.mark.parametrize("trig", TRIGS, ids=TRIG_IDS)
def test_committed_trig_file_is_the_registered_file_of_record(trig):
    g = R.transcription_graph(R.parse_trig(trig.read_text(encoding="utf-8")))
    key = (trig.parents[4].name, trig.parents[2].name)
    assert str(g.value(g.identifier, ST.ofFile)) == register_by_key()[key]["file_iri"]


@pytest.mark.parametrize("trig", TRIGS, ids=TRIG_IDS)
def test_committed_trig_pins_hold(trig):
    soa = trig.parents[1]
    collections_pin, code_pin = _pins(R.transcription_graph(R.parse_trig(trig.read_text(encoding="utf-8"))))
    inputs = case_inputs(soa)["input_paths"]
    top = Path(R._git(soa, "rev-parse", "--show-toplevel"))
    rel = [str(Path(p).resolve().relative_to(top.resolve())) for p in inputs]
    git = lambda repo, *a: subprocess.run(["git", "-C", str(repo), *a], capture_output=True, text=True)
    assert git(top, "merge-base", "--is-ancestor", collections_pin, "HEAD").returncode == 0, \
        f"collectionsCommit {collections_pin} is not an ancestor of the collections HEAD"
    assert git(top, "diff", "--quiet", collections_pin, "HEAD", "--", *rel).returncode == 0, \
        "an input changed since the pinned collections commit"
    assert git(top, "status", "--porcelain", "--", *rel).stdout == "", "an input has uncommitted changes"
    assert git(config.REPO_ROOT, "merge-base", "--is-ancestor", code_pin, "HEAD").returncode == 0, \
        f"codeCommit {code_pin} is not in the soa-tables history"
