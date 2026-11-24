"""
Human decisions on cross-table matches (the Layer 3 sidecar).

Consolidation matches activities across a protocol's tables by name. Whether two
rows are the same activity is a judgement a name score cannot make, so a reviewer's
decision lives in a sidecar next to the consolidated file,
`consolidated/{NCTID}_consolidation_corrections.json`, and `consolidate` reads it
before matching. It is the Layer 3 analogue of the extraction corrections sidecar.

Every entry names source rows, never unified-activity ids (`xact_id` is a counter
in processing order and changes when the input changes). A row is
`{table_number, activity_id, activity_name}`; `activity_name` is carried as a
check and must equal the row's name in the resolved table. A column ('within'
only) is `{table_number, column_position, composite_label}`, `composite_label`
the check.

Ops (fail fast on anything stale):
    keep    -- consolidation's result for the pair stands: `source` stays merged
               with `target`, or stays separate from its near match `target`
    split   -- `source` is taken out of the unified activity it shares with
               `target` and becomes an activity of its own
    merge   -- `source` joins the unified activity of `target`
    refines -- `source` (a row, or a whole table given as `{table_number}`)
               details the row `target`; nothing is merged
    within  -- `source` (a column of a subsidiary table) is a timepoint taken
               within the visit of `target` (a column of a main_soa table);
               nothing is merged. A column without an entry is unknown.
"""
from pathlib import Path
from typing import Dict, List, Tuple

OPS = ("keep", "split", "merge", "refines", "within")

# 'within': the table type each side must be in.
WITHIN_TABLE_TYPES = {"source": "subsidiary", "target": "main_soa"}

# What the consolidated view's draft puts where the reviewer must write.
DRAFT_PLACEHOLDERS = {"reason": "<why>", "by": "<reviewer>"}


def corrections_path(consolidated_dir: Path, protocol_id: str) -> Path:
    return consolidated_dir / f"{protocol_id}_consolidation_corrections.json"


def _check_row(cid: str, side: str, row: dict, tables: Dict[int, dict]) -> None:
    """The row must exist in a consolidated (non-reference) table under the stated name."""
    num = row["table_number"]
    if num not in tables:
        raise ValueError(f"Consolidation correction {cid}: {side} table {num} is not a table of this protocol")
    if tables[num]["table_metadata"]["table_type"] == "reference":
        raise ValueError(f"Consolidation correction {cid}: {side} table {num} is a reference table (not consolidated)")
    if "activity_id" not in row:
        return
    hits = [a for a in tables[num]["activities"] if a["activity_id"] == row["activity_id"]]
    if len(hits) != 1:
        raise ValueError(f"Consolidation correction {cid}: {side} row T{num} {row['activity_id']} hit {len(hits)} activities (expected 1)")
    if hits[0]["activity_name"] != row["activity_name"]:
        raise ValueError(
            f"Consolidation correction {cid}: {side} row T{num} {row['activity_id']} is named "
            f"'{hits[0]['activity_name']}', the entry says '{row['activity_name']}'")


def _check_column(cid: str, side: str, col: dict, tables: Dict[int, dict]) -> None:
    """The column must be a data column of a table of the type 'within' takes on this side, under the stated label."""
    num = col["table_number"]
    if num not in tables:
        raise ValueError(f"Consolidation correction {cid}: {side} table {num} is not a table of this protocol")
    ttype = tables[num]["table_metadata"]["table_type"]
    if ttype != WITHIN_TABLE_TYPES[side]:
        raise ValueError(
            f"Consolidation correction {cid}: 'within' {side} table {num} is {ttype}, not {WITHIN_TABLE_TYPES[side]}")
    hits = [c for c in tables[num]["schedule_columns"]
            if c["column_position"] == col["column_position"] and not c.get("is_label_column", False)]
    if len(hits) != 1:
        raise ValueError(
            f"Consolidation correction {cid}: {side} column T{num} position {col['column_position']} hit "
            f"{len(hits)} data columns (expected 1)")
    if hits[0].get("composite_label", "") != col["composite_label"]:
        raise ValueError(
            f"Consolidation correction {cid}: {side} column T{num} position {col['column_position']} is labelled "
            f"'{hits[0].get('composite_label', '')}', the entry says '{col['composite_label']}'")


def index_corrections(doc: dict, protocol_id: str,
                      tables: Dict[int, dict]) -> Tuple[Dict[Tuple[int, str], dict], List[dict], List[dict]]:
    """Check a consolidation sidecar against the resolved tables.

    Returns (decisions, refinements, withins): decisions maps a source row
    (table_number, activity_id) to its keep / split / merge entry — one decision
    per source row; refinements is the list of `refines` entries and withins the
    list of `within` entries, both in file order.
    """
    if doc["protocol_id"] != protocol_id:
        raise ValueError(f"Consolidation corrections are for '{doc['protocol_id']}', not '{protocol_id}'")
    decisions: Dict[Tuple[int, str], dict] = {}
    refinements: List[dict] = []
    withins: List[dict] = []
    within_pairs = {}
    seen_ids = set()
    for c in doc["corrections"]:
        cid = c["id"]
        if cid in seen_ids:
            raise ValueError(f"Consolidation correction {cid}: id is not unique")
        seen_ids.add(cid)
        op = c["op"]
        if op not in OPS:
            raise ValueError(f"Consolidation correction {cid}: unknown op '{op}'")
        for name, placeholder in DRAFT_PLACEHOLDERS.items():
            if c[name] == placeholder:
                raise ValueError(
                    f"Consolidation correction {cid}: '{name}' is still the draft placeholder '{placeholder}'")
        source, target = c["source"], c["target"]
        is_column = ["column_position" in source, "column_position" in target]
        if op == "within" and is_column != [True, True]:
            raise ValueError(
                f"Consolidation correction {cid}: 'within' takes columns (table_number, column_position, "
                f"composite_label) as 'source' and 'target'")
        if op != "within" and any(is_column):
            raise ValueError(f"Consolidation correction {cid}: only 'within' takes columns")
        if op == "within":
            if source["table_number"] == target["table_number"]:
                raise ValueError(
                    f"Consolidation correction {cid}: source and target are both in table {source['table_number']}")
            _check_column(cid, "source", source, tables)
            _check_column(cid, "target", target, tables)
            pair = (source["table_number"], source["column_position"],
                    target["table_number"], target["column_position"])
            if pair in within_pairs:
                raise ValueError(
                    f"Consolidation correction {cid}: 'within' pair T{pair[0]} position {pair[1]} -> T{pair[2]} "
                    f"position {pair[3]} is already stated ({within_pairs[pair]})")
            within_pairs[pair] = cid
            withins.append(c)
            continue
        if "activity_id" not in target:
            raise ValueError(f"Consolidation correction {cid}: 'target' must be a row (table_number, activity_id, activity_name)")
        if "activity_id" not in source and op != "refines":
            raise ValueError(f"Consolidation correction {cid}: only 'refines' takes a whole table as 'source'")
        if source["table_number"] == target["table_number"]:
            raise ValueError(f"Consolidation correction {cid}: source and target are both in table {source['table_number']}")
        _check_row(cid, "source", source, tables)
        _check_row(cid, "target", target, tables)
        if op == "refines":
            refinements.append(c)
            continue
        key = (source["table_number"], source["activity_id"])
        if key in decisions:
            raise ValueError(
                f"Consolidation correction {cid}: source row T{key[0]} {key[1]} already has a decision ({decisions[key]['id']})")
        decisions[key] = c
    return decisions, refinements, withins
