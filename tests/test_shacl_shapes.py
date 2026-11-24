"""
Fact model shapes (schemas/rdf/soa-tables-facts.shacl.ttl): the file agrees with itself, and the shapes accept a
small valid graph and reject graphs that break one rule each.

Step-4 check of the soa-tables plan. The shapes file is the single source of the fact model (terms + shapes, written
by hand). Its rules: every node shape closed with rdf:type ignored, sh:class names declared classes only, shared row
properties written out in both row shapes. The negative cases are checked by the constraint and path that fail, not
by message text.
"""
from pathlib import Path

import pytest

rdflib = pytest.importorskip("rdflib")
pyshacl = pytest.importorskip("pyshacl")

from rdflib import RDF, RDFS, Graph, Namespace  # noqa: E402

SHAPES_FILE = Path(__file__).resolve().parents[1] / "schemas" / "rdf" / "soa-tables-facts.shacl.ttl"
ST = Namespace("https://kerfors.github.io/soa-tables/id/terms/")
SH = Namespace("http://www.w3.org/ns/shacl#")
SHARED_ROW_PROPERTIES = (ST.rowPosition, ST.inTable, ST.onPage)


@pytest.fixture(scope="module")
def shapes():
    return Graph().parse(SHAPES_FILE, format="turtle")


def node_shapes(g):
    return list(g.subjects(RDF.type, SH.NodeShape))


def property_shapes(g, node_shape):
    return list(g.objects(node_shape, SH.property))


def rdf_list(g, head):
    out = []
    while head != RDF.nil:
        out.append(g.value(head, RDF.first))
        head = g.value(head, RDF.rest)
    return out


# ---------------------------------------------------------------- the file agrees with itself

def test_every_class_has_one_shape_and_every_shape_a_declared_class(shapes):
    classes = set(shapes.subjects(RDF.type, RDFS.Class))
    targets = [shapes.value(s, SH.targetClass) for s in node_shapes(shapes)]
    assert len(targets) == len(set(targets)), "a class has more than one shape"
    assert set(targets) == classes


def test_every_property_used_is_declared_and_every_declared_property_used(shapes):
    declared = set(shapes.subjects(RDF.type, RDF.Property))
    used = {shapes.value(p, SH.path) for s in node_shapes(shapes) for p in property_shapes(shapes, s)}
    used_st = {p for p in used if str(p).startswith(str(ST))}
    assert used_st - declared == set(), "used in a shape, not declared"
    assert declared - used_st == set(), "declared, used in no shape"
    assert used - used_st == {rdflib.URIRef("http://www.w3.org/ns/prov#wasDerivedFrom")}


def test_sh_class_names_declared_classes_only(shapes):
    classes = set(shapes.subjects(RDF.type, RDFS.Class))
    assert set(shapes.objects(None, SH["class"])) - classes == set()


def test_every_node_shape_is_closed_and_ignores_rdf_type_only(shapes):
    for s in node_shapes(shapes):
        assert shapes.value(s, SH.closed) == rdflib.Literal(True), s
        assert rdf_list(shapes, shapes.value(s, SH.ignoredProperties)) == [RDF.type], s


def test_row_shapes_agree_on_shared_properties(shapes):
    def shared(cls):
        shape = shapes.value(predicate=SH.targetClass, object=cls)
        out = {}
        for p in property_shapes(shapes, shape):
            path = shapes.value(p, SH.path)
            if path in SHARED_ROW_PROPERTIES:
                out[path] = sorted((str(k), str(v)) for k, v in shapes.predicate_objects(p))
        return out
    activity, prop = shared(ST.SourceActivityRow), shared(ST.SourcePropertyRow)
    assert set(activity) == set(SHARED_ROW_PROPERTIES)
    min_count = (str(SH.minCount), "1")
    assert min_count in activity[ST.onPage] and min_count not in prop[ST.onPage]
    prop[ST.onPage] = sorted(prop[ST.onPage] + [min_count])
    assert activity == prop


# ---------------------------------------------------------------- behaviour on small graphs

PREFIXES = """\
@prefix st: <https://kerfors.github.io/soa-tables/id/terms/> .
@prefix prov: <http://www.w3.org/ns/prov#> .
@prefix : <https://kerfors.github.io/soa-tables/id/sha256/aa/soa-tables-v1/> .
@prefix f: <https://kerfors.github.io/soa-tables/id/sha256/> .
"""

VALID = {
    "file": 'f:aa a st:File ; st:sha256 "' + "a" * 64 + '" .',
    "page": ":p3 a st:Page ; st:pageNumber 3 ; st:inFile f:aa .",
    "t01": ':t01 a st:SourceTable ; st:tableNumber 1 ; st:tableType "main_soa" ; st:firstPage :p3 ; st:lastPage :p3 .',
    "t02": ':t02 a st:SourceTable ; st:tableNumber 2 ; st:tableType "track" ; st:firstPage :p3 ; st:lastPage :p3 .',
    "row1": (':t01-r001 a st:SourceActivityRow ; st:name "Vital signs" ; st:rowPosition 1 ; st:inTable :t01 ;'
             ' st:onPage :p3 ; st:matchStatus "exact" .'),
    "row2": ':t02-r001 a st:SourceActivityRow ; st:name "Vital signs, weight" ; st:rowPosition 1 ; st:inTable :t02 ; st:onPage :p3 .',
    "ua": (':u-t01-r001 a st:UnifiedActivity ; st:name "Vital signs" ; st:hierarchyLevel 0 ; st:displayOrder 1 ;'
           ' st:isSectionHeader false ; st:parentName "" ; st:matchStatus "exact" ; st:member :t01-r001 .'),
    "decision": ':decision-ccorr-001 a st:Decision ; st:op "keep" ; st:decisionSource :t02-r001 ; st:decisionTarget :t01-r001 .',
    "match": (':match-t01-r001--t02-r001 a st:Match ; st:matchedRow :t01-r001 , :t02-r001 ; st:matchKind "separate" ;'
              ' st:reviewStatus "decided" ; st:decidedBy :decision-ccorr-001 .'),
}


def graph(**changes):
    parts = {**VALID, **changes}
    return Graph().parse(data=PREFIXES + "\n".join(v for v in parts.values() if v), format="turtle")


def validate(shapes, data):
    conforms, results, _ = pyshacl.validate(data, shacl_graph=shapes, inference="none")
    found = {(results.value(r, SH.resultPath), results.value(r, SH.sourceConstraintComponent))
             for r in results.subjects(RDF.type, SH.ValidationResult)}
    return conforms, found


def test_valid_graph_conforms(shapes):
    assert validate(shapes, graph()) == (True, set())


def test_property_row_without_page_conforms(shapes):
    data = graph(extra=(':t01-r003 a st:SourcePropertyRow ; st:rowPosition 3 ; st:inTable :t01 ;'
                        ' st:propertyType "epoch" ; st:propertyName "Epoch" ; st:hierarchyPosition 1 .'))
    assert validate(shapes, data) == (True, set())


def test_table_level_refines_conforms(shapes):
    data = graph(decision=':decision-ccorr-001 a st:Decision ; st:op "refines" ; st:decisionSource :t02 ;'
                          ' st:decisionTarget :u-t01-r001 .')
    assert validate(shapes, data) == (True, set())


WITHIN = {
    "t02": ':t02 a st:SourceTable ; st:tableNumber 2 ; st:tableType "subsidiary" ; st:firstPage :p3 ; st:lastPage :p3 .',
    "cols": (':t01-c004 a st:SourceColumn ; st:columnPosition 4 ; st:inTable :t01 .\n'
             ':t02-c002 a st:SourceColumn ; st:columnPosition 2 ; st:inTable :t02 .\n'
             ':u-t01-c004 a st:UnifiedColumn ; st:compositeLabel "Cycle 1 / D1" ; st:segment "main" ; st:member :t01-c004 .\n'
             ':u-t02-c002 a st:UnifiedColumn ; st:compositeLabel "Cycle 1 / D1 / SOI" ; st:segment "subsidiary" ;'
             ' st:member :t02-c002 ; st:withinColumn :u-t01-c004 .'),
    "decision2": ':decision-ccorr-002 a st:Decision ; st:op "within" ; st:decisionSource :t02-c002 ; st:decisionTarget :u-t01-c004 .',
}


def test_within_conforms(shapes):
    assert validate(shapes, graph(**WITHIN)) == (True, set())


def test_within_column_to_a_source_column_fails(shapes):
    broken = {**WITHIN, "cols": WITHIN["cols"].replace("st:withinColumn :u-t01-c004", "st:withinColumn :t01-c004")}
    conforms, found = validate(shapes, graph(**broken))
    assert not conforms
    assert found == {(ST.withinColumn, SH.ClassConstraintComponent)}


BROKEN = {
    "op not in list": (
        {"decision": ':decision-ccorr-001 a st:Decision ; st:op "drop" ; st:decisionSource :t02-r001 ; st:decisionTarget :t01-r001 .'},
        (ST.op, SH.InConstraintComponent)),
    "match status not in list": (
        {"row1": (':t01-r001 a st:SourceActivityRow ; st:name "Vital signs" ; st:rowPosition 1 ; st:inTable :t01 ;'
                  ' st:onPage :p3 ; st:matchStatus "wrong" .')},
        (ST.matchStatus, SH.InConstraintComponent)),
    "sha256 not 64 hex": (
        {"file": 'f:aa a st:File ; st:sha256 "xyz" .'},
        (ST.sha256, SH.PatternConstraintComponent)),
    "match with one row": (
        {"match": (':match-t01-r001--t02-r001 a st:Match ; st:matchedRow :t01-r001 ; st:matchKind "separate" ;'
                   ' st:reviewStatus "decided" ; st:decidedBy :decision-ccorr-001 .')},
        (ST.matchedRow, SH.MinCountConstraintComponent)),
    "decision source is a unified activity": (
        {"decision": ':decision-ccorr-001 a st:Decision ; st:op "keep" ; st:decisionSource :u-t01-r001 ; st:decisionTarget :t01-r001 .'},
        (ST.decisionSource, SH.OrConstraintComponent)),
    "row without page": (
        {"extra": ':t09-r001 a st:SourceActivityRow ; st:name "ECG" ; st:rowPosition 1 ; st:inTable :t01 .'},
        (ST.onPage, SH.MinCountConstraintComponent)),
    "row without printed name": (
        {"row2": ':t02-r001 a st:SourceActivityRow ; st:rowPosition 1 ; st:inTable :t02 ; st:onPage :p3 .'},
        (ST.name, SH.MinCountConstraintComponent)),
    "property outside the shape (closed)": (
        {"extra": ":t01-r001 st:somethingElse 1 ."},
        (ST.somethingElse, SH.ClosedConstraintComponent)),
    "activity property on a property row (closed)": (
        {"extra": (':t01-r003 a st:SourcePropertyRow ; st:rowPosition 3 ; st:inTable :t01 ; st:onPage :p3 ;'
                   ' st:propertyType "epoch" ; st:propertyName "Epoch" ; st:hierarchyPosition 1 ; st:matchStatus "new" .')},
        (ST.matchStatus, SH.ClosedConstraintComponent)),
    "unified activity without parent name": (
        {"ua": (':u-t01-r001 a st:UnifiedActivity ; st:name "Vital signs" ; st:hierarchyLevel 0 ; st:displayOrder 1 ;'
                ' st:isSectionHeader false ; st:matchStatus "exact" ; st:member :t01-r001 .')},
        (ST.parentName, SH.MinCountConstraintComponent)),
    "match kind not in list": (
        {"match": (':match-t01-r001--t02-r001 a st:Match ; st:matchedRow :t01-r001 , :t02-r001 ; st:matchKind "near_match" ;'
                   ' st:reviewStatus "decided" ; st:decidedBy :decision-ccorr-001 .')},
        (ST.matchKind, SH.InConstraintComponent)),
}


@pytest.mark.parametrize("name", list(BROKEN))
def test_broken_graph_fails_on_its_rule_only(shapes, name):
    changes, expected = BROKEN[name]
    conforms, found = validate(shapes, graph(**changes))
    assert not conforms
    assert found == {expected}
