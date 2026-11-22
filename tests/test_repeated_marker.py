"""B32: a marker printed for several notes in one table binds each note where its own
marker_locations put it. NCT03861273 marks every row note '*'; before this, each '*' note bound to
every cell, row and header carrying '*'."""

from soa_tables.resolve import build_annotation_crossrefs


def loc(kind, row, col=None):
    return {"table_number": 1, "location_type": kind, "row_position": row,
            **({"column_position": col} if col else {})}


def test_repeated_marker_binds_by_marker_locations():
    properties = [{"row_position": 1, "annotation_markers": ""}]
    grid = [{"row_position": 1, "column_position": 3, "annotation_markers": "*"}]
    activities = [{"row_position": 2, "annotation_markers": ""},
                  {"row_position": 3, "annotation_markers": "*"},
                  {"row_position": 4, "annotation_markers": "a"}]
    schedule = [{"row_position": 2, "column_position": 2, "annotation_markers": "*"},
                {"row_position": 4, "column_position": 2, "annotation_markers": "a"}]
    annotations = [
        {"annotation_marker": "*", "annotation_type": "footnote", "annotation_text": "Header note.",
         "marker_locations": [loc("schedule_cell", 1, 3)]},
        {"annotation_marker": "*", "annotation_type": "footnote", "annotation_text": "Cell note.",
         "marker_locations": [loc("schedule_cell", 2, 2)]},
        {"annotation_marker": "*", "annotation_type": "footnote", "annotation_text": "Row note.",
         "marker_locations": [loc("activity_name", 3)]},
        {"annotation_marker": "a", "annotation_type": "footnote", "annotation_text": "Unique marker.",
         "marker_locations": [loc("schedule_cell", 4, 2)]},
    ]
    resolved, *_ = build_annotation_crossrefs(annotations, properties, grid, activities, schedule, "table-001")
    refs = [a["referenced_elements"] for a in resolved]
    assert refs[0] == {"property_ids": [], "column_ids": ["col-003"], "activity_ids": [],
                       "cell_references": []}
    assert refs[1] == {"property_ids": [], "column_ids": [], "activity_ids": [],
                       "cell_references": [{"activity_id": "act-001", "column_id": "col-002"}]}
    assert refs[2] == {"property_ids": [], "column_ids": [], "activity_ids": ["act-002"],
                       "cell_references": []}
    # A marker used once binds by marker string, as before.
    assert refs[3]["cell_references"] == [{"activity_id": "act-003", "column_id": "col-002"}]
