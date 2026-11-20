# Identity: how soa-tables names what it transcribes

Status: decided 2026-11-20 (step 2 of the soa-tables plan). Supersedes `global-identifiers.md` for Layers 1–3.

## Why a rule

The ids in the JSON today (`act-015`, `col-003`, `xact-042`, …) are positions in lists and counters. They are
deterministic: the same input gives the same ids. But they are not identity:

- a consolidation correction (merge, split) renumbers the cross-table ids of activities it does not touch;
- a re-extraction renumbers rows, annotations and cross-table ids when rows are added, dropped or read in another order.

Measured on the published collections (2026-11-20): two runs on the same input gave identical output; with and without
consolidation corrections, 55 of 607 cross-table activities kept their members but changed id; between two extraction
sweeps of the same 45 tables, 34 activity rows, 57 annotations and 186 cross-table items were renumbered.

IRIs are therefore minted from what is printed and where, by code, never by the model.

## What an IRI is built from

| Node | IRI |
|---|---|
| File (Manifestation) | `{B}sha256/{hex}` |
| Page | `{M}/page/{n}` |
| Transcript element | `{M}/soa-tables-v{k}/{localId}` |
| Study | `{B}study/{studyKey}` |

- `{B}` is the base: `https://w3id.org/people/kerfors/soa-tables/`; until that is registered,
  `https://kerfors.github.io/soa-tables/id/`. Terms (classes, properties) live under the same base.
- `{hex}` is the SHA-256 of the protocol's file of record, all 64 characters, lowercase: the file as published,
  not a personal or annotated copy. `{M}` is that file's IRI.
- Nothing under `{M}` changes, because the bytes cannot. A new protocol version is a new file and a new `{M}`.
  "Same document, another version" is said in the register, not in an IRI.
- `{n}` is the physical page in the file, from 1.
- `{studyKey}` is the NCT id; for a study without one, the collection key (for example `CDISC_Pilot`).
- `soa-tables-v{k}` is the producer segment. `k` starts at 1 and changes only on a deliberate re-transcription
  (see below).

## Local ids

Every local id is built from printed position within one transcription of one file. Segments use only
`A-Za-z0-9._-`; numbers are zero-padded to fixed width (table 2 digits, row and column 3 digits). Minting fails if a
number does not fit, or if two elements get the same local id.

| Element | localId | From |
|---|---|---|
| Table | `t01` | table number |
| Activity or property row | `t01-r026` | printed `row_position` (rows and property rows share one numbering) |
| Column | `t01-c005` | printed `column_position` |
| Cell | `t01-r026-c005` | row + column |
| Annotation | `t01-n-{marker}` | printed marker |

Annotations:
- A marker character outside `A-Za-z0-9._-` is written as `x` + its Unicode code point in lowercase hex: `*` → `x2a`,
  `#` → `x23`, `£` → `xa3`. A marker of several characters is written character by character.
- Where a marker is printed for more than one note in the same table, the local id adds the first row the note is
  marked on: `t01-n-x2a-r016`. Minting fails if that is still not unique.

Why these survive corrections: printed positions are unique within a table; a Layer-1 correction that adds a row
gives it its own `row_position`, and one that removes a row leaves a gap. Nothing is renumbered.

## Cross-table items

A unified activity, column or annotation is named after its member in the lowest-numbered table, prefixed `u-`:
`u-t01-r026`, `u-t01-c005`, `u-t01-n-a`. A consolidated schedule cell joins its activity and column:
`m-t01-r026-t02-c004`.

- A row split off by a correction becomes the anchor of its own item.
- A merge keeps the anchor of the lower table.
- An item whose members do not change keeps its IRI, whatever happens to other items.

## Redacted rows

A row whose printed name is a redaction placeholder ("CCI", flagged `is_redacted`) has no printed identity. It is
named by its row like any other row and keeps the flag. Such a row is never matched across tables automatically
(only an explicit `merge` correction joins it), and its IRI is not stable across re-extraction: a redacted row in one
transcription and a redacted row in another are not claimed to be the same.

## Re-extraction

A re-extraction is a new transcription of the same file. Its printed positions are mostly, not always, the same
(between two sweeps, 94.5 % of matched activity rows kept their position).

- Anything that points at an element (a correction, a review decision, a mapping) carries the element's label as
  well as its IRI, and is checked against the current label before use; a mismatch stops the run.
- When a re-extraction is adopted on purpose, the producer segment goes up (`soa-tables-v2`) and an explicit
  old → new map is written, made by matching on labels and printed values, with unmatched elements listed for review.

## Checks

- Mint twice from the same input: the same set of IRIs.
- Mint for all collections: no two elements share a local id under the same `{M}`.
