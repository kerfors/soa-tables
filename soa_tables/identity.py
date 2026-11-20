"""
Identity — mint IRIs for Layers 1-3 from printed position, by code (documents/identity.md).

IRI templates ({B} = base, {M} = the protocol file's IRI):
  file           {B}sha256/{hex}          hex = SHA-256 of the file of record, 64 lowercase characters
  page           {M}/page/{n}             n = physical page, from 1
  element        {M}/{producer}/{localId}
  transcription  {M}/{producer}           names the graph of one transcription of one file
  study          {B}study/{studyKey}      NCT id, or the collection key when there is none

Local ids (one transcription of one file):
  table t01 | row t01-r026 | column t01-c005 | cell t01-r026-c005 | annotation t01-n-{marker}[-r016]
  cross-table: u-{local id of the member in the lowest table} | consolidated cell m-{row anchor}-{column anchor}
  unified property u-{earliest member row} | column property value {column}-v01 | document reference {note}-d01
  match match-{row}--{row} (sorted) | decision decision-{sidecar entry id}

Minting fails on a number that does not fit its width and on two elements with the same local id.
"""

import hashlib
import re

BASE = "https://kerfors.github.io/soa-tables/id/"
PRODUCER = "soa-tables-v1"

SEGMENT = re.compile(r"[A-Za-z0-9._-]+")
HEX64 = re.compile(r"[0-9a-f]{64}")
TABLE_WIDTH, POSITION_WIDTH = 2, 3
PART_WIDTH = 2


# =============================================================================
# IRIs
# =============================================================================

def segment(s: str) -> str:
    if not SEGMENT.fullmatch(s):
        raise ValueError(f"not a valid IRI segment (allowed: A-Z a-z 0-9 . _ -): {s!r}")
    return s


def sha256_file(path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def file_iri(hexdigest: str, base: str = BASE) -> str:
    if not HEX64.fullmatch(hexdigest):
        raise ValueError(f"not a lowercase 64-character sha256: {hexdigest!r}")
    return f"{base}sha256/{hexdigest}"


def page_iri(m: str, n: int) -> str:
    return f"{m}/page/{positive(n)}"


def element_iri(m: str, local_id: str, producer: str = PRODUCER) -> str:
    return f"{m}/{segment(producer)}/{segment(local_id)}"


def transcription_iri(m: str, producer: str = PRODUCER) -> str:
    return f"{m}/{segment(producer)}"


def study_iri(study_key: str, base: str = BASE) -> str:
    return f"{base}study/{segment(study_key)}"


# =============================================================================
# Local ids
# =============================================================================

def positive(n: int) -> int:
    if not isinstance(n, int) or isinstance(n, bool) or n < 1:
        raise ValueError(f"not a positive integer: {n!r}")
    return n


def padded(n: int, width: int) -> str:
    s = str(positive(n))
    if len(s) > width:
        raise ValueError(f"{n} does not fit in {width} digits")
    return s.zfill(width)


def table_id(t: int) -> str:
    return f"t{padded(t, TABLE_WIDTH)}"


def row_id(t: int, row_position: int) -> str:
    return f"{table_id(t)}-r{padded(row_position, POSITION_WIDTH)}"


def column_id(t: int, column_position: int) -> str:
    return f"{table_id(t)}-c{padded(column_position, POSITION_WIDTH)}"


def cell_id(t: int, row_position: int, column_position: int) -> str:
    return f"{row_id(t, row_position)}-c{padded(column_position, POSITION_WIDTH)}"


def marker_segment(marker: str) -> str:
    """A printed marker as an IRI segment: allowed characters as printed, any other as x + code point (hex)."""
    if not marker:
        raise ValueError("empty annotation marker")
    return "".join(c if SEGMENT.fullmatch(c) else f"x{ord(c):x}" for c in marker)


def annotation_id(t: int, marker: str, first_row: int | None = None) -> str:
    base = f"{table_id(t)}-n-{marker_segment(marker)}"
    return base if first_row is None else f"{base}-r{padded(first_row, POSITION_WIDTH)}"


def unified_id(member_local_id: str) -> str:
    return f"u-{member_local_id}"


def consolidated_cell_id(row_anchor: str, column_anchor: str) -> str:
    return f"m-{row_anchor}-{column_anchor}"


def property_value_id(column_local_id: str, n: int) -> str:
    """The n-th value (from 1) in a unified column's property_values."""
    return f"{column_local_id}-v{padded(n, PART_WIDTH)}"


def document_reference_id(annotation_local_id: str, n: int) -> str:
    """The n-th entry (from 1) in a unified annotation's document_references."""
    return f"{annotation_local_id}-d{padded(n, PART_WIDTH)}"


def match_id(row_a: str, row_b: str) -> str:
    if row_a == row_b:
        raise ValueError(f"a match needs two rows, got {row_a} twice")
    a, b = sorted((row_a, row_b))
    return f"match-{a}--{b}"


def decision_id(entry_id: str) -> str:
    return f"decision-{segment(entry_id)}"


# =============================================================================
# Minting from resolved and consolidated JSON
# =============================================================================

def _unique(pairs, what: str) -> dict:
    """[(json id, local id)] -> {json id: local id}; fails on a repeated json id or local id."""
    out, seen = {}, {}
    for jid, lid in pairs:
        if jid in out:
            raise ValueError(f"{what}: id {jid} appears twice")
        if lid in seen:
            raise ValueError(f"{what}: {jid} and {seen[lid]} both mint {lid}")
        out[jid] = lid
        seen[lid] = jid
    return out


def mint_table(resolved: dict) -> dict:
    """Local ids for one resolved table: {'table': id, 'rows': {...}, 'columns': {...}, 'annotations': {...},
    'cells': {...}}, keyed by the JSON ids (activity_id / property_id, column_id, annotation_id,
    (activity_id, column_id))."""
    t = resolved["table_metadata"]["table_number"]
    where = f"table {t}"
    rows = _unique([(a["activity_id"], row_id(t, a["row_position"])) for a in resolved["activities"]]
                   + [(p["property_id"], row_id(t, p["row_position"])) for p in resolved["schedule_properties"]],
                   f"{where} rows")
    columns = _unique([(c["column_id"], column_id(t, c["column_position"])) for c in resolved["schedule_columns"]],
                      f"{where} columns")
    per_marker = {}
    for a in resolved["annotations"]:
        per_marker.setdefault(a["annotation_marker"], []).append(a)
    pairs = []
    for marker, notes in per_marker.items():
        for a in notes:
            if len(notes) == 1:
                pairs.append((a["annotation_id"], annotation_id(t, marker)))
                continue
            marked = [loc["row_position"] for loc in a.get("marker_locations", [])
                      if loc.get("table_number") == t and loc.get("row_position") is not None]
            if not marked:
                raise ValueError(f"{where}: marker {marker!r} repeats and {a['annotation_id']} is marked on no row")
            pairs.append((a["annotation_id"], annotation_id(t, marker, min(marked))))
    annotations = _unique(pairs, f"{where} annotations")
    act_row = {a["activity_id"]: a["row_position"] for a in resolved["activities"]}
    col_pos = {c["column_id"]: c["column_position"] for c in resolved["schedule_columns"]}
    cells = _unique([((c["activity_id"], c["column_id"]),
                      cell_id(t, act_row[c["activity_id"]], col_pos[c["column_id"]]))
                     for c in resolved["activity_schedule"]], f"{where} cells")
    return {"table": table_id(t), "rows": rows, "columns": columns, "annotations": annotations, "cells": cells}


def _anchor(members, local, what: str, uid: str, several_in_table: bool = False) -> str:
    """members: [(table_num, json id)]; local: {table_num: {json id: local id}}. The member in the lowest table.
    several_in_table: annotations are unified by identical text, so one table can hold several members (the same
    note under two markers); the one whose local id sorts first is the anchor. Elsewhere one member per table."""
    low = min(t for t, _ in members)
    in_low = sorted(local[low][j] for t, j in members if t == low)
    if len(in_low) != 1 and not several_in_table:
        raise ValueError(f"{what} {uid}: {len(in_low)} members in its lowest table {low}, need 1")
    return in_low[0]


def mint_consolidated(consolidated: dict, tables: dict) -> dict:
    """Local ids for one consolidated protocol. tables: {table_number: mint_table(...) result}.
    Returns {'activities': {xact_id: id}, 'columns': {xcol_id: id}, 'annotations': {xannot_id: id},
    'cells': {(xact_id, xcol_id): id}}."""
    rows = {t: m["rows"] for t, m in tables.items()}
    cols = {t: m["columns"] for t, m in tables.items()}
    notes = {t: m["annotations"] for t, m in tables.items()}
    acts = _unique([(ua["xact_id"], unified_id(_anchor([(r["table_num"], r["activity_id"]) for r in ua["source_refs"]],
                                                       rows, "unified activity", ua["xact_id"])))
                    for ua in consolidated["unified_activities"]], "unified activities")
    columns = _unique([(c["xcol_id"], unified_id(_anchor([(s["table_num"], s["column_id"]) for s in c["source_columns"]],
                                                         cols, "unified column", c["xcol_id"])))
                       for seg in consolidated["timeline_segments"].values() for c in seg], "unified columns")
    annotations = _unique([(an["xannot_id"], unified_id(_anchor(
        [(s["table_num"], s["annotation_id"]) for s in an["source_occurrences"]],
        notes, "unified annotation", an["xannot_id"], several_in_table=True)))
        for an in consolidated["unified_annotations"]], "unified annotations")
    cells = _unique([((c["xact_id"], c["xcol_id"]),
                      consolidated_cell_id(acts[c["xact_id"]][2:], columns[c["xcol_id"]][2:]))
                     for c in consolidated["schedule_matrix"]], "consolidated cells")
    return {"activities": acts, "columns": columns, "annotations": annotations, "cells": cells}


def mint_protocol(resolved_tables: list, consolidated: dict) -> set:
    """Every local id of one protocol (tables and consolidated), as one set; fails on any collision."""
    tables = {}
    for r in resolved_tables:
        m = mint_table(r)
        t = r["table_metadata"]["table_number"]
        if t in tables:
            raise ValueError(f"table {t} appears twice")
        tables[t] = m
    cons = mint_consolidated(consolidated, tables)
    ids = []
    for m in tables.values():
        ids.append(m["table"])
        for k in ("rows", "columns", "annotations", "cells"):
            ids.extend(m[k].values())
    for k in ("activities", "columns", "annotations", "cells"):
        ids.extend(cons[k].values())
    if len(ids) != len(set(ids)):
        dup = sorted({i for i in ids if ids.count(i) > 1})[:5]
        raise ValueError(f"local ids minted more than once: {dup}")
    return set(ids)


# =============================================================================
# Unified properties, parts of an item, review items (documents/identity.md)
# =============================================================================

CLASH_ID = re.compile(r"(.+)-t([0-9]+)")


def property_key(p: dict):
    """consolidate.ColumnConsolidator's key for a property row: its level, or q_{type}_{name} without level."""
    level = p.get("hierarchical_level")
    return level if level is not None else f"q_{p.get('property_type', 'other')}_{p.get('property_name', '')}"


def unified_property_members(resolved_tables: list) -> dict:
    """{property key: [(table_number, row_position, property_id)], earliest first}, over every property row of
    every resolved table."""
    members = {}
    for r in resolved_tables:
        t = r["table_metadata"]["table_number"]
        for p in r["schedule_properties"]:
            members.setdefault(property_key(p), []).append((t, p["row_position"], p["property_id"]))
    return {k: sorted(v) for k, v in members.items()}


def mint_properties(resolved_tables: list, consolidated: dict, tables: dict) -> dict:
    """{unified property_id: u-{anchor row}} for the consolidated property_hierarchy. tables: {table_number:
    mint_table(...) result}. Anchor = the member with the earliest (table, row). Stops when the unified keys and
    the member keys differ, or a property_id does not name its anchor: a plain id is the anchor row's own
    property_id; a clash id '{id}-t{n}' has the anchor's own id and n = the anchor table."""
    members = unified_property_members(resolved_tables)
    root = {}
    for p in consolidated["property_hierarchy"]:
        k = property_key(p)
        if k in root:
            raise ValueError(f"unified properties {root[k]} and {p['property_id']} share key {k!r}")
        root[k] = p["property_id"]
    if set(root) != set(members):
        raise ValueError(f"unified property keys and member keys differ: {sorted(map(str, set(root) ^ set(members)))}")
    pairs = []
    for k, pid in root.items():
        t, _, own = members[k][0]
        clash = CLASH_ID.fullmatch(pid)
        if (clash.groups() != (own, str(t))) if clash else (pid != own):
            raise ValueError(f"unified property {pid} (key {k!r}) does not name its anchor: table {t}, {own}")
        pairs.append((pid, unified_id(tables[t]["rows"][own])))
    return _unique(pairs, "unified properties")


def mint_parts(consolidated: dict, cons: dict) -> dict:
    """Parts of an item, numbered by position from 1. cons: mint_consolidated(...) result.
    Returns {'property_values': {(xcol_id, n): id}, 'document_references': {(xannot_id, n): id}}."""
    values = _unique([((c["xcol_id"], n), property_value_id(cons["columns"][c["xcol_id"]], n))
                      for seg in consolidated["timeline_segments"].values() for c in seg
                      for n in range(1, len(c["property_values"]) + 1)], "column property values")
    refs = _unique([((an["xannot_id"], n), document_reference_id(cons["annotations"][an["xannot_id"]], n))
                    for an in consolidated["unified_annotations"]
                    for n in range(1, len(an.get("document_references", [])) + 1)], "document references")
    return {"property_values": values, "document_references": refs}


def mint_review(match_items: list, corrections_doc, tables: dict) -> dict:
    """match_items: visualize.build_matches_model(...)['items'] (source and target rows by table_number and
    activity_id); corrections_doc: the consolidation corrections sidecar, or None. tables: {table_number:
    mint_table(...) result}. Returns {'matches': [id per item, in item order], 'decisions': {entry id: id}}.
    Two items on the same pair of rows stop minting."""
    def row(r):
        return tables[r["table_number"]]["rows"][r["activity_id"]]
    matches = [match_id(row(it["source"]), row(it["target"])) for it in match_items]
    _unique(list(enumerate(matches)), "matches (item index)")
    entries = corrections_doc["corrections"] if corrections_doc else []
    decisions = _unique([(e["id"], decision_id(e["id"])) for e in entries], "decisions")
    return {"matches": matches, "decisions": decisions}


def mint_all(resolved_tables: list, consolidated: dict, match_items: list, corrections_doc) -> dict:
    """Every local id of one protocol, by kind: mint_protocol's kinds plus unified properties, parts of an item and
    review items. Fails on any collision across all of them. Returns {'tables': {table_number: mint_table
    result}, 'consolidated': mint_consolidated result, 'properties', 'property_values', 'document_references',
    'matches', 'decisions'}."""
    ids = list(mint_protocol(resolved_tables, consolidated))
    tables = {r["table_metadata"]["table_number"]: mint_table(r) for r in resolved_tables}
    cons = mint_consolidated(consolidated, tables)
    out = {"tables": tables, "consolidated": cons,
           "properties": mint_properties(resolved_tables, consolidated, tables),
           **mint_parts(consolidated, cons), **mint_review(match_items, corrections_doc, tables)}
    for k in ("properties", "property_values", "document_references", "decisions"):
        ids.extend(out[k].values())
    ids.extend(out["matches"])
    if len(ids) != len(set(ids)):
        dup = sorted({i for i in ids if ids.count(i) > 1})[:5]
        raise ValueError(f"local ids minted more than once: {dup}")
    return out
