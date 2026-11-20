# RDF interface: the consolidated facts as TriG

Status: built 2026-11-20 (step 4 of the soa-tables plan). The model is
[`schemas/rdf/soa-tables-facts.shacl.ttl`](../schemas/rdf/soa-tables-facts.shacl.ttl): the `st:` terms and one closed
node shape per class, written by hand. IRIs follow [`identity.md`](identity.md). Code: `soa_tables/rdf.py`.

The JSON files stay the documents of record of the pipeline. The RDF is the interface for programs: the same facts as
the consolidated JSON, with minted IRIs instead of positional ids, page provenance and review status as data.
Transcript, not interpretation: no USDM, no CDISC terms.

## What one TriG file holds

One file per protocol, one named graph per transcription. The graph name is the transcription IRI
`{M}/soa-tables-v1`, where `{M}` = `{B}sha256/{hex}` of the protocol file of record (see identity.md).
The Transcription node carries the file and study it is about, `consolidatedAt`, `consolidator`, `schemaVersion`, and
two pins: `collectionsCommit` (the data repository commit of the inputs) and `codeCommit` (the soa-tables commit).

Built from one protocol folder:

| Input | Gives |
|---|---|
| resolved tables | rows, columns, annotations and cells as printed; table page range; printed activity names |
| consolidated JSON | the cross-table items |
| extraction (`.verified.json` where present) | the page of each activity row |
| consolidation corrections sidecar (when present) | the decisions |
| `{protocol}.pdf` | the file of record: its sha256 names the file, its pages and every element |

Match items come from `visualize.build_matches_model`, the function behind the consolidated page, so the RDF and the
page agree on the pairs as well as on "n open of N".

## Classes

| Class | Local id | What it is |
|---|---|---|
| File | `{B}sha256/{hex}` | the protocol file of record |
| Page | `{M}/page/{n}` | a physical page of the file |
| Study | `{B}study/{key}` | NCT id, or the collection key where there is none |
| Transcription | `{M}/soa-tables-v1` | one transcription of one file; names the graph |
| SourceTable | `t01` | a printed SoA table, with first and last page |
| SourceActivityRow | `t01-r026` | an activity row as printed, with its page |
| SourcePropertyRow | `t01-r003` | a header band row (level, type, name) |
| SourceColumn | `t01-c005` | a printed column |
| SourceAnnotation | `t01-n-a` | a printed note marker in a table |
| SourceCell | `t01-r026-c005` | a cell value as printed |
| UnifiedActivity | `u-…` | an activity across tables; `member` = its source rows |
| UnifiedProperty | `u-t01-r003` | a header band across tables |
| UnifiedColumn | `u-…` | a column across tables, with segment and property values |
| ColumnPropertyValue | `u-…-v01` | one header value of a unified column, by position |
| ConsolidatedCell | `m-…` | a cell of the consolidated matrix; `prov:wasDerivedFrom` its source cell |
| UnifiedAnnotation | `u-…` | a note across tables, with its occurrences and what it refers to |
| DocumentReference | `u-…-d01` | what a note's text points at, as printed |
| Match | `match-{row}--{row}` | a pair of rows consolidation merged, split or kept separate; review status |
| Decision | `decision-{entry}` | a sidecar entry (keep, split, merge, refines) with reason, person and time |

Element IRIs are `{M}/soa-tables-v1/{localId}`. Terms live under `{B}terms/` (prefix `st:`); the only external term is
`prov:wasDerivedFrom`. `{B}` is `https://kerfors.github.io/soa-tables/id/` until the w3id base is registered.

Literals: strings are plain literals; non-integer numbers `xsd:decimal` (exact); dateTimes as written, not normalised.
Values from a closed list are plain strings checked with `sh:in`, as in the JSON Schemas.

## STORED, DERIVED, OUT

Every field of the consolidated JSON is on exactly one list; a field on none stops the round trip.

- **STORED** (in the RDF): the printed and decided facts — tables, rows, columns, cells, notes, the cross-table
  items and their members, parent name, qualified key, composite label, match status and confidence, near matches,
  refines, decisions. Full list in the `rdf.py` docstring and `canonical()`.
- **DERIVED** (rebuilt by `rdf.graph_to_json` on the way back, then compared): counts, `refined_by`, name variations,
  the segment key, segment and column order, source_refs order, near-match direction, display markers.
- **OUT** (not in the RDF, not compared): the stats blocks and per-table counts, `compression_percent`,
  `corrections_applied`, the empty `review_queue`, `schema_name`, and the two items in the next section.

Derived rules:
- Reading order of tables is consolidation's: the main SoA first, then the others except reference tables, each by
  number. source_refs and name variations follow it.
- Segments are ordered by their lowest anchor (table, column position); columns within a segment by anchor.
- A near match runs from the row in the later-read table to the first member of the other unified activity.

## Not in it

- `property_comment`: the extractor's reasoning for a property, model prose about the transcript, not the transcript.
  (`table_purpose` is in.)
- The Layer-1 `review_items` (calls made during extraction, with alternatives). They stay in the extraction JSON
  and the review page.
- A page for property rows. The extraction gives a header band no page; `onPage` is optional on SourcePropertyRow
  and the table's `firstPage` and `lastPage` bound it. Activity rows always have one.

## Build and check

```
python -m soa_tables.rdf <collection> <protocol_id> -o <protocol_id>_facts.trig
```

Needs the file of record (`{protocol}.pdf`, not in the public data repository) in the protocol folder. The build
reads both pins from git and refuses when an input (resolved, consolidated, extraction, sidecar) is untracked or
changed, or when `soa_tables/` or `schemas/` has uncommitted changes. Same inputs and commits give a byte-identical
file.

Tests (need `rdflib`, a runtime dependency, and `pyshacl` from the `test` extra; otherwise they skip):
- `tests/test_shacl_shapes.py`: the shapes file is consistent; valid and broken graphs pass and fail as expected.
- `tests/test_rdf.py`, per consolidated protocol in the collections checkout: round trip back to the consolidated
  JSON (P1); conforms to the closed shapes (P2); two builds byte-identical, every element IRI minted by
  `identity.mint_all` (P3); open / total matches equal the page (P4); every activity row on one page inside its
  table's range (P5); decisions equal the sidecar. Per collection: a folder without a consolidated file has an
  `excluded_reason` (P8). Plus failure tests for a missing file of record, a field on no list and bad commits.

Per-protocol TriG files are not published yet; they will live beside the other outputs in the collections repository.
