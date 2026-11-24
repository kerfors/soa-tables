"""
RDF — the facts of one consolidated protocol as TriG, and back to JSON (soa-tables step 4).

Fact model: schemas/rdf/soa-tables-facts.shacl.ttl (terms and closed shapes). IRIs: soa_tables/identity.py
(documents/identity.md). One TriG file per protocol, one named graph = the transcription IRI {M}/soa-tables-v1.

Inputs (one protocol folder):
  resolved tables         rows, columns, annotations, cells as printed; table page range; printed activity names
  consolidated JSON       the cross-table items (STORED fields below)
  extraction              source_page per activity row (the .verified.json where present)
  corrections sidecar     the decisions (when present)
  {protocol}.pdf          the file of record: its sha256 names the file, the pages and every element
  {protocol}_soa_pages/pages.json   physical_page per document page: Page IRIs and st:pageNumber name the
                          physical page of the file of record (tools/page_map.py --physical)
Match items come from visualize.build_matches_model, the function behind the consolidated page.

Round trip (consolidated JSON -> RDF -> JSON): every consolidated field is STORED (in the RDF), DERIVED (rebuilt on
the way back) or OUT (not compared); a field on none of the lists stops canonical(). JSON ids are replaced by minted
local ids on both sides.
"""

import json
import re
import subprocess
from contextlib import contextmanager
from decimal import Decimal
from pathlib import Path

import rdflib
from rdflib import RDF, XSD, Dataset, Literal, Namespace, URIRef

from soa_tables import config
from soa_tables import identity as I
from soa_tables import visualize as V
from soa_tables.consolidate import UnifiedAnnotation as ConsolidatedAnnotation
from soa_tables.consolidation_corrections import corrections_path

ST = Namespace(I.BASE + "terms/")
PROV = Namespace("http://www.w3.org/ns/prov#")
SHAPES = Path(config.REPO_ROOT) / "schemas" / "rdf" / "soa-tables-facts.shacl.ttl"
HEX40 = re.compile(r"[0-9a-f]{40}")


# =============================================================================
# Inputs
# =============================================================================

def load_inputs(soa: Path, sha256: str = None) -> dict:
    """Everything one protocol's graph is built from. soa: the protocol's soa-tables folder.

    sha256: the file of record's hash when the file is not local (a clone without the full PDFs; the tests take it
    from register.csv). Without it the file of record must be present and is hashed here.
    """
    soa = Path(soa)
    pid = soa.parent.name
    pdf = soa.parent / f"{pid}.pdf"
    if sha256 is None:
        if not pdf.is_file():
            raise FileNotFoundError(f"{pid}: file of record {pdf} not found")
        sha256 = I.sha256_file(pdf)
    resolved_files = sorted((soa / "resolved").glob("*_resolved.json"))
    consolidated_file = soa / "consolidated" / f"{pid}_consolidated.json"
    extraction_files = []
    for raw in sorted((soa / "extracted").glob("*_extraction.json")):
        verified = raw.with_name(raw.stem + ".verified.json")
        extraction_files.append(verified if verified.exists() else raw)
    sidecar = corrections_path(soa / "consolidated", pid)
    pages_file = soa.parent / f"{pid}_soa_pages" / "pages.json"
    resolved = [json.loads(f.read_text()) for f in resolved_files]
    consolidated = json.loads(consolidated_file.read_text())
    extractions = [json.loads(f.read_text()) for f in extraction_files]
    corrections_doc = json.loads(sidecar.read_text()) if sidecar.exists() else None
    physical = {e["doc_page"]: e["physical_page"] for e in json.loads(pages_file.read_text())["pages"]}
    row_names = {(r["table_metadata"]["table_number"], a["activity_id"]): a["activity_name"]
                 for r in resolved for a in r["activities"]}
    items = V.build_matches_model(consolidated, row_names, corrections_doc)["items"]
    inputs = (resolved_files + [consolidated_file] + extraction_files + ([sidecar] if sidecar.exists() else [])
              + [pages_file])
    return {"protocol_id": pid, "pdf": pdf, "sha256": sha256, "resolved": resolved, "consolidated": consolidated,
            "extractions": extractions, "corrections_doc": corrections_doc, "items": items, "physical": physical,
            "input_paths": inputs}


def row_pages(resolved: list, extractions: list) -> dict:
    """{(table_number, row_position): source_page} for every resolved activity row, from the extraction."""
    pages = {}
    for e in extractions:
        t = e["table_metadata"]["table_number"]
        for a in e["activities"]:
            pages[(t, a["row_position"])] = a["source_page"]
    out = {}
    for r in resolved:
        t = r["table_metadata"]["table_number"]
        for a in r["activities"]:
            key = (t, a["row_position"])
            if key not in pages:
                raise ValueError(f"table {t} row {a['row_position']}: no source_page in the extraction")
            out[key] = pages[key]
    return out


def _git(repo: Path, *args) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True,
                          text=True).stdout.strip()


def collections_commit(input_paths: list) -> str:
    """The collections HEAD the inputs were read at. Every input must be tracked and unchanged."""
    repo = Path(input_paths[0]).parent
    top = Path(_git(repo, "rev-parse", "--show-toplevel"))
    rel = [str(Path(p).resolve().relative_to(top.resolve())) for p in input_paths]
    tracked = set(_git(top, "ls-files", "--", *rel).splitlines())
    if set(rel) - tracked:
        raise ValueError(f"inputs not tracked in {top}: {sorted(set(rel) - tracked)}")
    dirty = _git(top, "status", "--porcelain", "--", *rel)
    if dirty:
        raise ValueError(f"inputs changed since HEAD in {top}:\n{dirty}")
    return _git(top, "rev-parse", "HEAD")


def code_commit() -> str:
    """The soa-tables HEAD; the code and the fact model must be unchanged."""
    repo = Path(config.REPO_ROOT)
    dirty = _git(repo, "status", "--porcelain", "--", "soa_tables", "schemas")
    if dirty:
        raise ValueError(f"soa-tables code or schemas changed since HEAD:\n{dirty}")
    return _git(repo, "rev-parse", "HEAD")


# =============================================================================
# JSON -> RDF
# =============================================================================

def _decimal(x) -> Literal:
    """A non-integer number, exact (rdflib writes xsd:double with 7 digits)."""
    return Literal(Decimal(repr(float(x))), datatype=XSD.decimal)


def _datetime(s: str) -> Literal:
    """xsd:dateTime with the lexical form as written (rdflib would rewrite Z as +00:00)."""
    return Literal(s, datatype=XSD.dateTime, normalize=False)


def _string(s: str) -> Literal:
    """A plain literal (RDF 1.1: xsd:string). An explicit ^^xsd:string would not equal the plain values in the
    shapes' sh:in lists."""
    return Literal(s)


def build_dataset(inp: dict, collections_commit: str, code_commit: str) -> Dataset:
    """One protocol's facts as a Dataset with one named graph (the transcription)."""
    for name, value in (("collections_commit", collections_commit), ("code_commit", code_commit)):
        if not HEX40.fullmatch(value):
            raise ValueError(f"{name} is not a 40-character commit: {value!r}")
    resolved, cons, doc = inp["resolved"], inp["consolidated"], inp["corrections_doc"]
    minted = I.mint_all(resolved, cons, inp["items"], doc)
    tables, xm = minted["tables"], minted["consolidated"]
    pages = row_pages(resolved, inp["extractions"])

    m = I.file_iri(inp["sha256"])
    tiri = I.transcription_iri(m)
    ds = Dataset()
    for prefix, ns in (("st", ST), ("prov", PROV), ("xsd", XSD),
                       ("e", Namespace(tiri + "/")), ("page", Namespace(m + "/page/"))):
        ds.bind(prefix, ns)
    g = ds.graph(URIRef(tiri))

    def el(local_id: str) -> URIRef:
        return URIRef(I.element_iri(m, local_id))

    def page(n: int) -> URIRef:
        """n: the document page the transcript uses; the Page is its physical page in the file of record."""
        if n not in inp["physical"]:
            raise ValueError(f"document page {n}: no pages.json entry")
        p = inp["physical"][n]
        node = URIRef(I.page_iri(m, p))
        g.add((node, RDF.type, ST.Page))
        g.add((node, ST.pageNumber, Literal(p)))
        g.add((node, ST.inFile, URIRef(m)))
        return node

    def add(s, p, o):
        g.add((s, p, o))

    # file, study, transcription
    study = URIRef(I.study_iri(cons["protocol_id"]))
    add(URIRef(m), RDF.type, ST.File)
    add(URIRef(m), ST.sha256, _string(m.rsplit("/", 1)[1]))
    add(study, RDF.type, ST.Study)
    add(study, ST.studyKey, _string(cons["protocol_id"]))
    t_node = URIRef(tiri)
    meta = cons["consolidation_metadata"]
    add(t_node, RDF.type, ST.Transcription)
    add(t_node, ST.ofFile, URIRef(m))
    add(t_node, ST.aboutStudy, study)
    add(t_node, ST.consolidatedAt, _datetime(meta["consolidated_at"]))
    add(t_node, ST.consolidator, _string(meta["consolidator"]))
    add(t_node, ST.schemaVersion, _string(cons["schema_version"]))
    add(t_node, ST.collectionsCommit, _string(collections_commit))
    add(t_node, ST.codeCommit, _string(code_commit))

    # source tables, rows, columns, annotations, cells
    source_tables = {st["table_num"]: st for st in meta["source_tables"]}
    ref_of_row = {(ref["table_num"], ref["activity_id"]): ref
                  for ua in cons["unified_activities"] for ref in ua["source_refs"]}

    def decision(ref_or_hint) -> URIRef:
        return el(minted["decisions"][ref_or_hint["decision"]["correction_id"]])

    for r in resolved:
        tm = r["table_metadata"]
        t = tm["table_number"]
        mt = tables[t]
        st = source_tables[t]
        tn = el(mt["table"])
        add(tn, RDF.type, ST.SourceTable)
        add(tn, ST.tableNumber, Literal(t))
        add(tn, ST.tableType, _string(st["table_type"]))
        for key, term in (("table_title", ST.title), ("table_purpose", ST.purpose), ("track_label", ST.trackLabel)):
            if st.get(key) is not None:
                add(tn, term, _string(st[key]))
        add(tn, ST.firstPage, page(tm["page_start"]))
        add(tn, ST.lastPage, page(tm["page_end"]))

        for a in r["activities"]:
            node = el(mt["rows"][a["activity_id"]])
            add(node, RDF.type, ST.SourceActivityRow)
            add(node, ST.rowPosition, Literal(a["row_position"]))
            add(node, ST.inTable, tn)
            add(node, ST.onPage, page(pages[(t, a["row_position"])]))
            add(node, ST.name, _string(a["activity_name"]))
            ref = ref_of_row.get((t, a["activity_id"]))
            if ref is not None:
                add(node, ST.matchStatus, _string(ref["match_status"]))
                add(node, ST.matchConfidence, _decimal(ref["match_confidence"]))
                if "decision" in ref:
                    add(node, ST.matchDecision, decision(ref))

        bands = [(h.get("hierarchical_level"), h["property_name"], h["property_type"])
                 for h in st["property_hierarchy"]]
        for p in r["schedule_properties"]:
            band = (p.get("hierarchical_level"), p["property_name"], p["property_type"])
            if bands.count(band) != 1:
                raise ValueError(f"table {t} {p['property_id']}: {bands.count(band)} entries of the consolidated "
                                 f"property_hierarchy match {band}, need 1")
            node = el(mt["rows"][p["property_id"]])
            add(node, RDF.type, ST.SourcePropertyRow)
            add(node, ST.rowPosition, Literal(p["row_position"]))
            add(node, ST.inTable, tn)
            if band[0] is not None:
                add(node, ST.level, Literal(band[0]))
            add(node, ST.propertyType, _string(band[2]))
            add(node, ST.propertyName, _string(band[1]))
            add(node, ST.hierarchyPosition, Literal(bands.index(band) + 1))
        if len(bands) != len(r["schedule_properties"]):
            raise ValueError(f"table {t}: {len(bands)} consolidated bands, {len(r['schedule_properties'])} rows")

        for c in r["schedule_columns"]:
            node = el(mt["columns"][c["column_id"]])
            add(node, RDF.type, ST.SourceColumn)
            add(node, ST.columnPosition, Literal(c["column_position"]))
            add(node, ST.inTable, tn)
        for a in r["annotations"]:
            node = el(mt["annotations"][a["annotation_id"]])
            add(node, RDF.type, ST.SourceAnnotation)
            add(node, ST.marker, _string(a["annotation_marker"]))
            add(node, ST.inTable, tn)
        for c in r["activity_schedule"]:
            node = el(mt["cells"][(c["activity_id"], c["column_id"])])
            add(node, RDF.type, ST.SourceCell)
            add(node, ST.row, el(mt["rows"][c["activity_id"]]))
            add(node, ST.column, el(mt["columns"][c["column_id"]]))
            add(node, ST.value, _string(c["cell_value"]))

    # unified activities
    for ua in cons["unified_activities"]:
        node = el(xm["activities"][ua["xact_id"]])
        add(node, RDF.type, ST.UnifiedActivity)
        add(node, ST.name, _string(ua["activity_name"]))
        if ua["parent_xact_id"] is not None:
            add(node, ST.parent, el(xm["activities"][ua["parent_xact_id"]]))
        add(node, ST.parentName, _string(ua["parent_name"]))
        add(node, ST.hierarchyLevel, Literal(ua["hierarchy_level"]))
        add(node, ST.displayOrder, Literal(ua["display_order"]))
        add(node, ST.qualifiedKey, _string(ua["qualified_key"]))
        add(node, ST.isSectionHeader, Literal(ua["is_section_header"]))
        if "is_redacted" in ua:
            add(node, ST.isRedacted, Literal(ua["is_redacted"]))
        add(node, ST.matchStatus, _string(ua["match_status"]))
        add(node, ST.matchConfidence, _decimal(ua["match_confidence"]))
        for ref in ua["source_refs"]:
            add(node, ST.member, el(tables[ref["table_num"]]["rows"][ref["activity_id"]]))

    # unified properties: members by consolidation's key (option C)
    members = I.unified_property_members(resolved)
    for p in cons["property_hierarchy"]:
        node = el(minted["properties"][p["property_id"]])
        add(node, RDF.type, ST.UnifiedProperty)
        if p.get("hierarchical_level") is not None:
            add(node, ST.level, Literal(p["hierarchical_level"]))
        add(node, ST.propertyType, _string(p["property_type"]))
        add(node, ST.propertyName, _string(p["property_name"]))
        for t, _, prop_id in members[I.property_key(p)]:
            add(node, ST.member, el(tables[t]["rows"][prop_id]))

    # unified columns and their property values
    col_member = {}
    for seg in cons["timeline_segments"].values():
        for c in seg:
            node = el(xm["columns"][c["xcol_id"]])
            add(node, RDF.type, ST.UnifiedColumn)
            add(node, ST.compositeLabel, _string(c["composite_label"]))
            add(node, ST.segment, _string(c["segment"]))
            if c.get("population_track") is not None:
                add(node, ST.populationTrack, _string(c["population_track"]))
            for n, pv in enumerate(c["property_values"], 1):
                pnode = el(minted["property_values"][(c["xcol_id"], n)])
                add(node, ST.propertyValue, pnode)
                add(pnode, RDF.type, ST.ColumnPropertyValue)
                add(pnode, ST.position, Literal(n))
                if pv.get("level") is not None:
                    add(pnode, ST.level, Literal(pv["level"]))
                add(pnode, ST.propertyType, _string(pv["property_type"]))
                add(pnode, ST.propertyName, _string(pv["property_name"]))
                add(pnode, ST.value, _string(pv["value"]))
            for s in c["source_columns"]:
                add(node, ST.member, el(tables[s["table_num"]]["columns"][s["column_id"]]))
                col_member[(c["xcol_id"], s["table_num"])] = s["column_id"]
            for w in c.get("within", []):
                add(node, ST.withinColumn, el(xm["columns"][w["xcol_id"]]))

    # consolidated cells: one source value each, derived from that table's cell
    row_member = {(ua["xact_id"], ref["table_num"]): ref["activity_id"]
                  for ua in cons["unified_activities"] for ref in ua["source_refs"]}
    for c in cons["schedule_matrix"]:
        node = el(xm["cells"][(c["xact_id"], c["xcol_id"])])
        add(node, RDF.type, ST.ConsolidatedCell)
        add(node, ST.activity, el(xm["activities"][c["xact_id"]]))
        add(node, ST.column, el(xm["columns"][c["xcol_id"]]))
        add(node, ST.value, _string(c["consolidated_value"]))
        if len(c["source_values"]) != 1:
            raise ValueError(f"cell {c['xact_id']} x {c['xcol_id']}: {len(c['source_values'])} source values, need 1")
        t = int(next(iter(c["source_values"])))
        source = (row_member[(c["xact_id"], t)], col_member[(c["xcol_id"], t)])
        add(node, PROV.wasDerivedFrom, el(tables[t]["cells"][source]))

    # unified annotations and their document references
    for an in cons["unified_annotations"]:
        node = el(xm["annotations"][an["xannot_id"]])
        add(node, RDF.type, ST.UnifiedAnnotation)
        add(node, ST.annotationType, _string(an["annotation_type"]))
        add(node, ST.text, _string(an["annotation_text"]))
        for key, term in (("placeholder_reason", ST.placeholderReason), ("review_note", ST.reviewNote),
                          ("annotation_scope", ST.annotationScope)):
            if key in an:
                add(node, term, _string(an[key]))
        for o in an["source_occurrences"]:
            add(node, ST.occurrence, el(tables[o["table_num"]]["annotations"][o["annotation_id"]]))
        for x in an["referenced_xacts"]:
            add(node, ST.refersToActivity, el(xm["activities"][x]))
        for x in an["referenced_xcols"]:
            add(node, ST.refersToColumn, el(xm["columns"][x]))
        for x in an["referenced_props"]:
            add(node, ST.refersToProperty, el(minted["properties"][x]))
        for cr in an["cell_references"]:
            add(node, ST.refersToCell, el(xm["cells"][(cr["xact_id"], cr["xcol_id"])]))
        for n, ref in enumerate(an.get("document_references", []), 1):
            dnode = el(minted["document_references"][(an["xannot_id"], n)])
            add(node, ST.documentReference, dnode)
            add(dnode, RDF.type, ST.DocumentReference)
            add(dnode, ST.position, Literal(n))
            add(dnode, ST.referenceKind, _string(ref["kind"]))
            add(dnode, ST.target, _string(ref["target"]))
            if "table_num" in ref:
                add(dnode, ST.tableNumber, Literal(ref["table_num"]))

    # matches (visualize.build_matches_model items) and decisions (sidecar entries)
    def row_iri(r: dict) -> URIRef:
        return el(tables[r["table_number"]]["rows"][r["activity_id"]])

    for item, mid in zip(inp["items"], minted["matches"]):
        node = el(mid)
        add(node, RDF.type, ST.Match)
        add(node, ST.matchedRow, row_iri(item["source"]))
        add(node, ST.matchedRow, row_iri(item["target"]))
        add(node, ST.matchKind, _string(item["kind"]))
        if item["score"] is not None:
            add(node, ST.score, _decimal(item["score"]))
        add(node, ST.reviewStatus, _string("decided" if item["decision"] else "open"))
        if item["decision"]:
            add(node, ST.decidedBy, decision(item))
    ua_of_row = {(ref["table_num"], ref["activity_id"]): ua["xact_id"]
                 for ua in cons["unified_activities"] for ref in ua["source_refs"]}
    # 'within' names columns by (table_number, column_position)
    at_position = {(s["table_num"], s["column_position"]): (c["xcol_id"], s["column_id"])
                   for seg in cons["timeline_segments"].values() for c in seg for s in c["source_columns"]}
    for e in (doc["corrections"] if doc else []):
        node = el(minted["decisions"][e["id"]])
        add(node, RDF.type, ST.Decision)
        add(node, ST.op, _string(e["op"]))
        src, tgt = e["source"], e["target"]
        if e["op"] == "within":
            add(node, ST.decisionSource, el(tables[src["table_number"]]["columns"][
                at_position[(src["table_number"], src["column_position"])][1]]))
            add(node, ST.decisionTarget, el(xm["columns"][at_position[(tgt["table_number"], tgt["column_position"])][0]]))
        else:
            add(node, ST.decisionSource,
                row_iri(src) if "activity_id" in src else el(tables[src["table_number"]]["table"]))
            if e["op"] == "refines":
                add(node, ST.decisionTarget, el(xm["activities"][ua_of_row[(tgt["table_number"], tgt["activity_id"])]]))
            else:
                add(node, ST.decisionTarget, row_iri(tgt))
        if "reason" in e:
            add(node, ST.reason, _string(e["reason"]))
        if "by" in e:
            add(node, ST.decidedByPerson, _string(e["by"]))
        if "at" in e:
            add(node, ST.decidedAt, _datetime(e["at"]))
    return ds


def to_trig(ds: Dataset) -> str:
    return ds.serialize(format="trig")


def build_trig(soa: Path) -> str:
    """The TriG of one protocol folder, pinned to the collections HEAD and the soa-tables HEAD."""
    inp = load_inputs(soa)
    return to_trig(build_dataset(inp, collections_commit(inp["input_paths"]), code_commit()))


# =============================================================================
# RDF -> JSON
# =============================================================================

@contextmanager
def _lexical_literals():
    """Parse with literals as written (no rewriting of dateTime Z, decimals, ...)."""
    before = rdflib.NORMALIZE_LITERALS
    rdflib.NORMALIZE_LITERALS = False
    try:
        yield
    finally:
        rdflib.NORMALIZE_LITERALS = before


def parse_trig(text: str) -> Dataset:
    ds = Dataset()
    with _lexical_literals():
        ds.parse(data=text, format="trig")
    return ds


def transcription_graph(ds: Dataset):
    """The one named graph of a dataset."""
    graphs = [g for g in ds.graphs() if len(g) and g.identifier != rdflib.graph.DATASET_DEFAULT_GRAPH_ID]
    if len(graphs) != 1:
        raise ValueError(f"need exactly one named graph with triples, found {len(graphs)}")
    return graphs[0]


def processing_order(table_types: dict) -> list:
    """Table numbers in the order consolidation reads them: main_soa tables first, then the rest except
    reference, each by number (consolidate.consolidate_protocol)."""
    return sorted((t for t, ty in table_types.items() if ty != "reference"),
                  key=lambda t: (table_types[t] != "main_soa", t))


def graph_to_json(ds: Dataset) -> dict:
    """Rebuild the canonical consolidated JSON from one transcription graph: STORED fields read, DERIVED fields
    computed. Ids are the minted local ids; the shape is canonical() 's."""
    g = transcription_graph(ds)
    tiri = str(g.identifier)
    prefix = tiri + "/"

    def lid(node) -> str:
        s = str(node)
        if not s.startswith(prefix):
            raise ValueError(f"{s} is not an element of {tiri}")
        return s[len(prefix):]

    def of_type(cls):
        return sorted(g.subjects(RDF.type, cls), key=str)

    def one(s, p):
        vals = list(g.objects(s, p))
        if len(vals) != 1:
            raise ValueError(f"{s} {p}: {len(vals)} values, need 1")
        return vals[0]

    def opt(s, p):
        vals = list(g.objects(s, p))
        if len(vals) > 1:
            raise ValueError(f"{s} {p}: {len(vals)} values, need at most 1")
        return vals[0] if vals else None

    def val(lit):
        return None if lit is None else lit.toPython()

    def num(lit):
        return None if lit is None else float(lit.toPython())

    t_node = URIRef(tiri)
    study = one(t_node, ST.aboutStudy)

    # tables and source rows
    table_num = {s: int(one(s, ST.tableNumber)) for s in of_type(ST.SourceTable)}
    table_types = {table_num[s]: str(one(s, ST.tableType)) for s in table_num}
    order = processing_order(table_types)
    rank = {t: i for i, t in enumerate(order)}
    rows = {}
    for s in of_type(ST.SourceActivityRow):
        dec = opt(s, ST.matchDecision)
        rows[s] = {"table": table_num[one(s, ST.inTable)], "row_position": int(one(s, ST.rowPosition)),
                   "name": str(one(s, ST.name)), "status": val(opt(s, ST.matchStatus)),
                   "confidence": num(opt(s, ST.matchConfidence)), "decision": dec}
    decisions = {s: {"op": str(one(s, ST.op)), "source": one(s, ST.decisionSource),
                     "target": one(s, ST.decisionTarget)} for s in of_type(ST.Decision)}

    def decision_ref(node) -> dict:
        return {"correction_id": lid(node), "op": decisions[node]["op"]}

    # unified activities
    uas = of_type(ST.UnifiedActivity)
    ua_of_row = {}
    ua_members = {}
    for u in uas:
        ms = sorted(g.objects(u, ST.member), key=lambda r: (rank[rows[r]["table"]], rows[r]["row_position"]))
        ua_members[u] = ms
        for r in ms:
            ua_of_row[r] = u
    ua_name = {u: str(one(u, ST.name)) for u in uas}
    extra = {u: {"near_matches": [], "refines": [], "refined_by": []} for u in uas}
    for s in of_type(ST.Match):
        if str(one(s, ST.matchKind)) != "separate":
            continue
        a, b = sorted(g.objects(s, ST.matchedRow), key=lambda r: rank[rows[r]["table"]])
        source_ua, target_ua = ua_of_row[b], ua_of_row[a]
        if ua_members[target_ua][0] != a:
            raise ValueError(f"near match {lid(s)}: {lid(a)} is not the first member of {lid(target_ua)}")
        dec = opt(s, ST.decidedBy)
        extra[source_ua]["near_matches"].append({
            "xact_id": lid(target_ua), "activity_name": ua_name[target_ua], "score": num(opt(s, ST.score)),
            "table_num": rows[b]["table"], **({"decision": decision_ref(dec)} if dec is not None else {})})
    table_refines = {}
    for d, e in decisions.items():
        if e["op"] != "refines":
            continue
        target = e["target"]
        if e["source"] in rows:
            source_ua = ua_of_row[e["source"]]
            extra[source_ua]["refines"].append({"xact_id": lid(target), "correction_id": lid(d)})
            extra[target]["refined_by"].append({"xact_id": lid(source_ua), "correction_id": lid(d)})
        else:
            t = table_num[e["source"]]
            table_refines.setdefault(t, []).append({"xact_id": lid(target), "correction_id": lid(d)})
            extra[target]["refined_by"].append({"table_num": t, "correction_id": lid(d)})

    activities = []
    for u in uas:
        parent = opt(u, ST.parent)
        refs = []
        for r in ua_members[u]:
            x = rows[r]
            refs.append({"table_id": I.table_id(x["table"]), "table_num": x["table"], "activity_id": lid(r),
                         "row_position": x["row_position"], "match_status": x["status"],
                         "match_confidence": x["confidence"],
                         **({"decision": decision_ref(x["decision"])} if x["decision"] is not None else {})})
        variations = []
        for r in ua_members[u]:
            if rows[r]["name"] not in variations:
                variations.append(rows[r]["name"])
        redacted = opt(u, ST.isRedacted)
        activities.append({
            "xact_id": lid(u), "activity_name": ua_name[u],
            "parent_name": str(one(u, ST.parentName)),
            "parent_xact_id": lid(parent) if parent is not None else None,
            "hierarchy_level": int(one(u, ST.hierarchyLevel)), "display_order": int(one(u, ST.displayOrder)),
            "qualified_key": str(one(u, ST.qualifiedKey)), "is_section_header": bool(one(u, ST.isSectionHeader)),
            **({"is_redacted": bool(redacted)} if redacted is not None else {}),
            **{k: sorted(v, key=_sort_key) for k, v in extra[u].items() if v},
            "source_refs": refs, "name_variations": variations,
            "match_status": str(one(u, ST.matchStatus)), "match_confidence": num(one(u, ST.matchConfidence)),
            "table_count": len({x["table_num"] for x in refs})})
    activities.sort(key=lambda a: a["display_order"])

    # source tables
    bands = {}
    for s in of_type(ST.SourcePropertyRow):
        level = opt(s, ST.level)
        bands.setdefault(table_num[one(s, ST.inTable)], []).append(
            (int(one(s, ST.hierarchyPosition)), {"hierarchical_level": val(level),
                                                 "property_name": str(one(s, ST.propertyName)),
                                                 "property_type": str(one(s, ST.propertyType))}))
    source_tables = []
    for s, t in sorted(table_num.items(), key=lambda x: x[1]):
        positions = sorted(bands.get(t, []), key=lambda x: x[0])
        if [p for p, _ in positions] != list(range(1, len(positions) + 1)):
            raise ValueError(f"table {t}: hierarchy positions {[p for p, _ in positions]}")
        track = opt(s, ST.trackLabel)
        source_tables.append({
            "table_id": lid(s), "table_num": t, "table_type": table_types[t],
            "table_title": str(one(s, ST.title)), "table_purpose": str(one(s, ST.purpose)),
            "track_label": None if track is None else str(track),
            "property_hierarchy": [b for _, b in positions],
            **({"refines": sorted(table_refines[t], key=_sort_key)} if t in table_refines else {})})

    # unified properties
    properties = []
    for s in of_type(ST.UnifiedProperty):
        properties.append({"property_id": lid(s), "hierarchical_level": val(opt(s, ST.level)),
                           "property_name": str(one(s, ST.propertyName)),
                           "property_type": str(one(s, ST.propertyType))})

    # unified columns: segments in order of their first column, columns in order of their anchor
    # 'within': st:withinColumn is the fact, the Decision with op 'within' names it; the two must agree
    ucols = of_type(ST.UnifiedColumn)
    ucol_of_member = {m: s for s in ucols for m in g.objects(s, ST.member)}
    within_decision = {(ucol_of_member[e["source"]], e["target"]): d
                       for d, e in decisions.items() if e["op"] == "within"}
    stated = {(s, o) for s in ucols for o in g.objects(s, ST.withinColumn)}
    if stated != set(within_decision):
        diff = sorted((lid(a), lid(b)) for a, b in stated ^ set(within_decision))
        raise ValueError(f"st:withinColumn and the 'within' decisions disagree: {diff}")
    within_of, contains_of = {}, {}
    for (a, b), d in within_decision.items():
        within_of.setdefault(a, []).append({"xcol_id": lid(b), "correction_id": lid(d)})
        contains_of.setdefault(b, []).append({"xcol_id": lid(a), "correction_id": lid(d)})

    columns = []
    for s in ucols:
        sources = sorted(({"table_id": I.table_id(table_num[one(c, ST.inTable)]),
                           "table_num": table_num[one(c, ST.inTable)], "column_id": lid(c),
                           "column_position": int(one(c, ST.columnPosition))}
                          for c in g.objects(s, ST.member)), key=lambda c: (c["table_num"], c["column_position"]))
        values = sorted(g.objects(s, ST.propertyValue), key=lambda v: int(one(v, ST.position)))
        if [int(one(v, ST.position)) for v in values] != list(range(1, len(values) + 1)):
            raise ValueError(f"{lid(s)}: property value positions not 1..n")
        track = opt(s, ST.populationTrack)
        columns.append({
            "xcol_id": lid(s), "composite_label": str(one(s, ST.compositeLabel)), "segment": str(one(s, ST.segment)),
            "population_track": None if track is None else str(track),
            "property_values": [{"level": val(opt(v, ST.level)), "property_name": str(one(v, ST.propertyName)),
                                 "property_type": str(one(v, ST.propertyType)), "value": str(one(v, ST.value))}
                                for v in values],
            "source_columns": sources,
            **({"within": sorted(within_of[s], key=_sort_key)} if s in within_of else {}),
            **({"contains": sorted(contains_of[s], key=_sort_key)} if s in contains_of else {})})
    columns.sort(key=lambda c: (c["source_columns"][0]["table_num"], c["source_columns"][0]["column_position"]))
    segments = {}
    for c in columns:
        segments.setdefault(c["segment"], []).append(c)

    # consolidated cells
    cell_rc = {}
    matrix = []
    for s in of_type(ST.ConsolidatedCell):
        source = one(s, PROV.wasDerivedFrom)
        row = one(source, ST.row)
        cell_rc[s] = (lid(one(s, ST.activity)), lid(one(s, ST.column)))
        matrix.append({"xact_id": cell_rc[s][0], "xcol_id": cell_rc[s][1],
                       "consolidated_value": str(one(s, ST.value)),
                       "source_values": {str(rows[row]["table"]): str(one(source, ST.value))}})
    matrix.sort(key=lambda c: (c["xact_id"], c["xcol_id"]))

    # unified annotations
    annotations = []
    for s in of_type(ST.UnifiedAnnotation):
        occ = sorted(({"table_num": table_num[one(o, ST.inTable)], "marker": str(one(o, ST.marker)),
                       "annotation_id": lid(o)} for o in g.objects(s, ST.occurrence)), key=_sort_key)
        refs = sorted(g.objects(s, ST.documentReference), key=lambda d: int(one(d, ST.position)))
        doc_refs = [{"kind": str(one(d, ST.referenceKind)), "target": str(one(d, ST.target)),
                     **({"table_num": int(opt(d, ST.tableNumber))} if opt(d, ST.tableNumber) is not None else {})}
                    for d in refs]
        markers = ConsolidatedAnnotation(xannot_id="", annotation_type="", annotation_text="", normalized_text="",
                                         source_occurrences=occ).get_display_markers()
        annotations.append({
            "xannot_id": lid(s), "annotation_type": str(one(s, ST.annotationType)),
            "annotation_text": str(one(s, ST.text)), "display_markers": markers, "source_occurrences": occ,
            "referenced_xacts": sorted(lid(x) for x in g.objects(s, ST.refersToActivity)),
            "referenced_xcols": sorted(lid(x) for x in g.objects(s, ST.refersToColumn)),
            "referenced_props": sorted(lid(x) for x in g.objects(s, ST.refersToProperty)),
            "cell_references": sorted(({"xact_id": cell_rc[c][0], "xcol_id": cell_rc[c][1]}
                                       for c in g.objects(s, ST.refersToCell)), key=_sort_key),
            "occurrence_count": len(occ),
            **{key: str(opt(s, term)) for key, term in (("annotation_scope", ST.annotationScope),
                                                        ("placeholder_reason", ST.placeholderReason),
                                                        ("review_note", ST.reviewNote)) if opt(s, term) is not None},
            **({"document_references": doc_refs} if doc_refs else {})})

    return {
        "protocol_id": str(one(study, ST.studyKey)),
        "schema_version": str(one(t_node, ST.schemaVersion)),
        "consolidation_metadata": {"consolidated_at": str(one(t_node, ST.consolidatedAt)),
                                   "consolidator": str(one(t_node, ST.consolidator)),
                                   "source_tables": source_tables},
        "property_hierarchy": sorted(properties, key=_sort_key),
        "unified_activities": activities,
        "timeline_segments": [[k, cols] for k, cols in segments.items()],
        "schedule_matrix": matrix,
        "unified_annotations": sorted(annotations, key=lambda a: a["xannot_id"]),
    }


# =============================================================================
# Canonical consolidated JSON (the round trip compares this)
# =============================================================================

def _sort_key(x) -> str:
    return json.dumps(x, sort_keys=True)


# Every consolidated field, per object: STORED + DERIVED (compared), OUT (dropped). A field on neither stops.
FIELDS = {
    "root": ({"protocol_id", "schema_version", "consolidation_metadata", "property_hierarchy",
              "unified_activities", "timeline_segments", "schedule_matrix", "unified_annotations"},
             {"schema_name", "review_queue", "review_items"}),
    "metadata": ({"consolidated_at", "consolidator", "source_tables"},
                 {"match_stats", "review_stats", "annotation_stats", "compression_percent", "corrections_applied",
                  "source_activity_count", "unified_activity_count"}),
    "source_table": ({"table_id", "table_num", "table_type", "table_title", "table_purpose", "track_label",
                      "property_hierarchy", "refines"},
                     {"activity_count", "column_count", "annotation_count"}),
    "table_band": ({"hierarchical_level", "property_name", "property_type"}, {"property_comment"}),
    "property": ({"property_id", "hierarchical_level", "property_name", "property_type"}, {"property_comment"}),
    "activity": ({"xact_id", "activity_name", "parent_name", "parent_xact_id", "hierarchy_level", "display_order",
                  "qualified_key", "is_section_header", "is_redacted", "near_matches", "refines", "refined_by",
                  "source_refs", "name_variations", "match_status", "match_confidence", "table_count"}, set()),
    "source_ref": ({"table_id", "table_num", "activity_id", "row_position", "match_status", "match_confidence",
                    "decision"}, set()),
    "decision": ({"correction_id", "op"}, set()),
    "near_match": ({"xact_id", "activity_name", "score", "table_num", "decision"}, set()),
    "refines": ({"xact_id", "correction_id"}, set()),
    "refined_by": ({"xact_id", "table_num", "correction_id"}, set()),
    "column": ({"xcol_id", "composite_label", "segment", "population_track", "property_values",
                "source_columns", "within", "contains"}, set()),
    "within": ({"xcol_id", "correction_id"}, set()),
    "contains": ({"xcol_id", "correction_id"}, set()),
    "property_value": ({"level", "property_name", "property_type", "value"}, set()),
    "source_column": ({"table_id", "table_num", "column_id", "column_position"}, set()),
    "cell": ({"xact_id", "xcol_id", "consolidated_value", "source_values"}, set()),
    "annotation": ({"xannot_id", "annotation_type", "annotation_text", "display_markers", "source_occurrences",
                    "referenced_xacts", "referenced_xcols", "referenced_props", "cell_references",
                    "occurrence_count", "annotation_scope", "document_references", "placeholder_reason",
                    "review_note"}, set()),
    "occurrence": ({"table_num", "marker", "annotation_id"}, set()),
    "cell_reference": ({"xact_id", "xcol_id"}, set()),
    "document_reference": ({"kind", "target", "table_num"}, set()),
}


def _keep(obj: dict, kind: str) -> dict:
    compared, out = FIELDS[kind]
    unknown = set(obj) - compared - out
    if unknown:
        raise ValueError(f"{kind}: field(s) on no list (STORED, DERIVED, OUT): {sorted(unknown)}")
    return {k: v for k, v in obj.items() if k in compared}


def canonical(consolidated: dict, resolved: list, minted: dict) -> dict:
    """The consolidated JSON with OUT fields dropped, JSON ids replaced by minted local ids, and lists without a
    meaningful order sorted. minted: identity.mint_all(...)."""
    tables, xm = minted["tables"], minted["consolidated"]
    table_of_id = {r["table_metadata"]["table_id"]: r["table_metadata"]["table_number"] for r in resolved}
    acts, cols, notes, props = xm["activities"], xm["columns"], xm["annotations"], minted["properties"]

    def tid(table_id: str, table_num: int) -> str:
        if table_of_id[table_id] != table_num:
            raise ValueError(f"{table_id} is table {table_of_id[table_id]}, not {table_num}")
        return tables[table_num]["table"]

    def dec(d: dict) -> dict:
        d = _keep(d, "decision")
        return {"correction_id": minted["decisions"][d["correction_id"]], "op": d["op"]}

    root = _keep(consolidated, "root")
    meta = _keep(root["consolidation_metadata"], "metadata")
    source_tables = []
    for st in meta["source_tables"]:
        st = _keep(st, "source_table")
        st["table_id"] = tid(st["table_id"], st["table_num"])
        st["property_hierarchy"] = [_keep(b, "table_band") for b in st["property_hierarchy"]]
        if "refines" in st:
            st["refines"] = sorted(({"xact_id": acts[x["xact_id"]], "correction_id": minted["decisions"][
                x["correction_id"]]} for x in map(lambda r: _keep(r, "refines"), st["refines"])), key=_sort_key)
        source_tables.append(st)
    meta["source_tables"] = sorted(source_tables, key=lambda s: s["table_num"])

    activities = []
    for ua in root["unified_activities"]:
        ua = _keep(ua, "activity")
        ua["xact_id"] = acts[ua["xact_id"]]
        if ua["parent_xact_id"] is not None:
            ua["parent_xact_id"] = acts[ua["parent_xact_id"]]
        refs = []
        for ref in ua["source_refs"]:
            ref = _keep(ref, "source_ref")
            ref["table_id"] = tid(ref["table_id"], ref["table_num"])
            ref["activity_id"] = tables[ref["table_num"]]["rows"][ref["activity_id"]]
            if "decision" in ref:
                ref["decision"] = dec(ref["decision"])
            refs.append(ref)
        ua["source_refs"] = refs
        if "near_matches" in ua:
            near = []
            for h in ua["near_matches"]:
                h = _keep(h, "near_match")
                h["xact_id"] = acts[h["xact_id"]]
                if "decision" in h:
                    h["decision"] = dec(h["decision"])
                near.append(h)
            ua["near_matches"] = sorted(near, key=_sort_key)
        for key in ("refines", "refined_by"):
            if key in ua:
                rel = []
                for x in ua[key]:
                    x = _keep(x, key)
                    if "xact_id" in x:
                        x["xact_id"] = acts[x["xact_id"]]
                    x["correction_id"] = minted["decisions"][x["correction_id"]]
                    rel.append(x)
                ua[key] = sorted(rel, key=_sort_key)
        activities.append(ua)
    activities.sort(key=lambda a: a["display_order"])

    segments = []
    for key, seg in root["timeline_segments"].items():
        out = []
        for c in seg:
            c = _keep(c, "column")
            c["xcol_id"] = cols[c["xcol_id"]]
            c["property_values"] = [_keep(v, "property_value") for v in c["property_values"]]
            sources = []
            for s in c["source_columns"]:
                s = _keep(s, "source_column")
                s["table_id"] = tid(s["table_id"], s["table_num"])
                s["column_id"] = tables[s["table_num"]]["columns"][s["column_id"]]
                sources.append(s)
            c["source_columns"] = sources
            for k in ("within", "contains"):
                if k in c:
                    c[k] = sorted(({"xcol_id": cols[x["xcol_id"]], "correction_id": minted["decisions"][
                        x["correction_id"]]} for x in map(lambda r: _keep(r, k), c[k])), key=_sort_key)
            out.append(c)
        segments.append([key, out])

    matrix = []
    for c in root["schedule_matrix"]:
        c = _keep(c, "cell")
        c["xact_id"], c["xcol_id"] = acts[c["xact_id"]], cols[c["xcol_id"]]
        matrix.append(c)
    matrix.sort(key=lambda c: (c["xact_id"], c["xcol_id"]))

    annotations = []
    for an in root["unified_annotations"]:
        an = _keep(an, "annotation")
        an["xannot_id"] = notes[an["xannot_id"]]
        occ = []
        for o in an["source_occurrences"]:
            o = _keep(o, "occurrence")
            o["annotation_id"] = tables[o["table_num"]]["annotations"][o["annotation_id"]]
            occ.append(o)
        an["source_occurrences"] = sorted(occ, key=_sort_key)
        an["referenced_xacts"] = sorted(acts[x] for x in an["referenced_xacts"])
        an["referenced_xcols"] = sorted(cols[x] for x in an["referenced_xcols"])
        an["referenced_props"] = sorted(props[x] for x in an["referenced_props"])
        an["cell_references"] = sorted(({"xact_id": acts[r["xact_id"]], "xcol_id": cols[r["xcol_id"]]}
                                        for r in map(lambda r: _keep(r, "cell_reference"), an["cell_references"])),
                                       key=_sort_key)
        if "document_references" in an:
            an["document_references"] = [_keep(r, "document_reference") for r in an["document_references"]]
        annotations.append(an)

    properties = []
    for p in root["property_hierarchy"]:
        p = _keep(p, "property")
        p["property_id"] = props[p["property_id"]]
        properties.append(p)

    return {
        "protocol_id": root["protocol_id"],
        "schema_version": root["schema_version"],
        "consolidation_metadata": meta,
        "property_hierarchy": sorted(properties, key=_sort_key),
        "unified_activities": activities,
        "timeline_segments": segments,
        "schedule_matrix": matrix,
        "unified_annotations": sorted(annotations, key=lambda a: a["xannot_id"]),
    }


def differences(a, b, path: str = "", out=None, limit: int = 20) -> list:
    """Paths where two canonical JSON values differ (at most `limit`)."""
    out = [] if out is None else out
    if len(out) >= limit:
        return out
    if isinstance(a, dict) and isinstance(b, dict):
        for k in sorted(set(a) | set(b), key=str):
            if k not in a or k not in b:
                out.append(f"{path}.{k}: only in {'rebuilt' if k in b else 'original'}")
            else:
                differences(a[k], b[k], f"{path}.{k}", out, limit)
    elif isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            out.append(f"{path}: length {len(a)} vs {len(b)}")
        for i, (x, y) in enumerate(zip(a, b)):
            differences(x, y, f"{path}[{i}]", out, limit)
    elif a != b or type(a) is not type(b):
        out.append(f"{path}: {a!r} vs {b!r}")
    return out[:limit]


# =============================================================================
# Command line
# =============================================================================

def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(description="Write one protocol's facts as TriG.")
    ap.add_argument("collection")
    ap.add_argument("protocol_id")
    ap.add_argument("-o", "--output", required=True, type=Path)
    args = ap.parse_args(argv)
    args.output.write_text(build_trig(config.get_soa_tables_folder(args.protocol_id, args.collection)))


if __name__ == "__main__":
    main()
