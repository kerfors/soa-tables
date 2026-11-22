# soa-tables backlog

Open work on soa-tables, numbered B1 onward. Opened 2026-11-22 at soa-tables 534d793 (prompt 3.9.4, pytest 1,264
passed / 29 skipped). Numbers are stable: an item keeps its number when done, and new items get the next number.
Status is `open`, or `done` with the commit that closed it.

Sources:
1. **B1–B15**: learnings from adding three protocols to misc_studies (NCT04304508, NCT02701985, NCT03739203), and from
   comparing NCT04304508 with its USDM file from Protocol Explorer.
2. **B16–B30**: open items carried over from soa2usdm's
   [`documents/inventory-improvements.md`](https://github.com/kerfors/soa2usdm/blob/dc343b5/documents/inventory-improvements.md)
   at the split commit dc343b5 (2026-11-09), which was not moved into soa-tables. Each names its item there
   ("inv 30" = item 30). Read the original item for evidence and sketch; the soa2usdm file stays as history.
3. **B31 onward**: found while working through this list.

## A. Prompt and taxonomy — next prompt revision (target 3.9.5)
Same approach as 3.9.x: a call the reviewer decided becomes a rule, so a fresh extraction no longer raises it. Every
prompt edit: version bump, `tools/redaction/apply_redactions.py` re-run (fails if a logged span no longer matches), gate
check 14 then requires the new version on new runs only.

| # | Status | Rule | Evidence | Where in the prompt |
|---|---|---|---|---|
| B1 | open | **A note that names activity rows binds to those rows** (by text match), and only to the rows it names. | NCT04304508 T2 D4: the sampling-times paragraph below Table 1–1 named PK, PD and biomarker sampling → bound to rows 3–6, not Genetics; marker n, not g. | §6 "Binding by what a note names": new sub-case between "names specific visits or columns" and "names no specific element". |
| B2 | open | **A qualifier header row gets no level**: a row the label column presents as a qualifier of the row above (parenthesised label, "Duration") is `hierarchical_level: null` even where one of its cells names a sub-band, when another header row (visit) already tells those columns apart. | NCT04304508 T1 D1: "(Duration)" under "Study periods"; the "Early termination (ET)" cell over Visit 12a did not make it a level. The existing rule ("a row whose values follow from another header row … null", from inv 22e) was not applied by the agent. | §4 "hierarchical_level" — sharpen the existing sentence with this case. |
| B3 | open | **A modality / visit-attribute row gets no level** when a visit row tells every column apart: site / phone / in-person rows (`modality`), fasting and similar (`visit_attribute`, inv 16). | NCT04304508 T1 D3 ("Visit type": site / ☎); NCT05051579 "Fasting Visit" (null). Two consistent cases. | §4, next to the condition-band rule. |
| B4 | open | **Keep printed line breaks in multi-line header cells**: a ruled header cell that prints two lines keeps them as `\n` in `cell_value` (as `property_name_source.cell_value` already does for row labels). The row stays one row. | NCT04304508 T1 D2: "Week [W] / Study day and allowed deviations" kept as one row (decided), but cell values are joined with a space ("W2 15±4"), so week and day ± window cannot be separated without guessing. The Protocol Explorer comparison shows the windows are exactly what the USDM side lost. Related: inv 22j "line breaks inside annotation_text" (§4 Whitespace covers names, header values and track_label only). | §4 Whitespace / §3 header bands. Check first: does any code (resolve, consolidate, visualize, rdf, review page, row audit) strip or mis-render `\n` in grid cell values? |
| B5 | open | *Look before writing a rule:* **full-height merged text blocks**. NCT03739203 T2 (Table 4): the grey "Refer to Global Protocol or Country-Specific Amendment for Visit 1/2 Procedures" blocks became 50 repeated text cells (every row × visit columns 1–2) under the vertical-merge rule. A block covering a whole column may be a note on the schedule column instead. | First look at the consolidated view and the review page for NCT03739203; decide whether a rule is needed. | — |
| B16 | open | **Banner that captions the header row below it** (inv 33): a band across all data columns naming the header row directly below, whose label cell is empty, is that row's `property_name`, not a header row. | NCT03283098 Tables 1a–1c, fixed by sidecars. Acceptance: blind re-extraction of NCT03283098 reproduces the sidecar result. | §3. |
| B17 | open | **Horizontal header spans repeat the value over the covered columns** (inv 27c; all 98 published spans do, item 23e) — one sentence. | — | §3. |
| B18 | open | **Excel leftovers** (inv 31a): header line "Use the v2.x flow when a human-editable Excel checkpoint is wanted", attachments line "Read the XLSX skill only if…", §7 "review against the per-table resolved HTML" (the review page took its place). | Still in 3.9.4 (lines 4, 8, 190). | Header, attachments line, §7. |
| B19 | open | **Verbatim quotes in the report, no composition** (inv 26f): the gate already checks the parts around '…'; composed quotes (two printed notes joined) are the remaining CHECKs. One §7 sentence. | NCT04677179 report. | §7. |
| B20 | open | **Name of the extractor's report: "extraction log"** (inv 8; decided 2026-11-22). Today: file `{NCTID}_uncertainty_report.md`, page title "Extraction log", prompt §7 "uncertainty report", gate glob on the file name. Rename to `{NCTID}_extraction_log.md` / `.html` in one prompt version (file rename script, markdown content untouched; index accepting both names for one release). | The review page is where decisions are taken; this file is the extractor's account of the run (provenance). "Uncertainty report" named its old role as review surface. | Prompt §7, gate, index, workflow guide. |

Candidates recorded but not proposed: the "new open calls outside every rule" of inv 22j / 25j / 26d (tile row
numbering, category row numbering, '(Day Relative to C1D1)', visit-listing notes, two-row CCI box, note naming an
unmarked visit). Each needs a decision before it can be a rule.

Acceptance (proposal): blind re-extraction of NCT04304508 (B1–B4), NCT05051579 (B3 — its other decisions must not
move) and NCT03283098 (B16), discarded, not promoted. Pass: the decided calls are not raised; the outcome equals the
decided `.verified.json` except the B4 line breaks; gate 0 FAIL. Existing corpus not re-extracted (as inv 21h).

## B. Extraction schema

| # | Status | Change | Notes |
|---|---|---|---|
| B21 | open | Remove `extraction_metadata.verification.excel_file` / `excel_verified` and the "source/Excel" wording in `row_position` (inv 31b). | Removing fields is not additive: check the corpus for use first; schema version bump; `tools/build_explainer.py` after a schema change. |

## C. Code — package and review page

| # | Status | File | Change | Notes |
|---|---|---|---|---|
| B9 | open | `soa_tables/consolidate.py` | Header rows with no level stay in their print position among the levelled rows in `property_hierarchy` / timeline `property_values`; level governs the hierarchy only. | **The rest of inv 30**: that item (done 2026-10-02) put level-less rows in print order *among themselves*, but still after all levelled rows (NCT04304508 T1 now lists Duration and Visit type after Week). Size first: count protocols with a level-less row between levelled rows; each changes consolidated JSON + viewer + TriG (rebuild, 2-commit pin), possibly golden fixtures. |
| B10 | open | `soa_tables/row_audit.py` | Do not count text printed below the table frame as an unextracted row. Options: stop at the frame's bottom rule, or drop bands whose text matches an annotation of that table. | **The rest of inv 20e** ("on p.22 it reads footnote lines a/b below the grid as two rows"; the label-column part is done — `label_columns` in row_audit.json). New case: NCT04304508 p.15 "most recent". Needs a negative control; `tools/baseline.py` numbers may move. |
| B11 | open | `soa_tables/review_page.py` | Decisions panel: show decisions on other tables ("3 (+1 in Table 2)"), or list all protocol decisions grouped by table. | NCT04304508 D4 sat on Table 2 and looked missing. |
| B22 | done | `soa_tables/index_generator.py:273`, `soa_tables/visualize.py:1635` | Silent `except Exception: pass` → propagate or log as a step error (inv 13). | Still present on 534d793. Done by removing both: the error reaches the step's outer handler (logged, `status: failed`). In visualize.py it made no difference — a later loop (row names) already read the same resolved files unguarded. |
| B23 | open | `soa_tables/review_page.py` | Follow-ups inv 7a (the "take the alternative" draft for a note-scope call should list all entries: rebind `marker_locations` and clear `annotation_markers` on rows leaving the binding), 7d (`page_grid.merged_cells` misses dashed rules), 29a (drawn marks — arrows as graphics — not checked; reuse the dark-pixel test), 29b (column mapping on NCT03637764 p.22), 29c (presence only, not value). | 7c (round trip via GitHub web editor + Action) parked — "only once the page has been used for real on a multi-table protocol"; misc_studies now has three such protocols. |
| B24 | open | `soa_tables/consolidate.py` / tests | Cross-table binding conflict detector reports source-faithful variation (inv 27a: NCT02291289 `xannot-022`, data correct). Test list or detector filter. | Small. |
| B25 | open | Consolidation | **Nesting for `subsidiary` tables** (inv 32b): finer timepoints within a main visit — the column-side counterpart of `refines`, a human statement (sidecar op to design). | NCT04304508 Table 1–1 is a fresh case: Day 1 (Visit 2), Week 4 (Visit 4: predose, 0.5–1.5 h, 2–4 h), Week 4 or later (4–12 h), Week 26 (Visit 8)/ET — today only row-side `refines` is recorded. Medium; design first. Also inv 32b′ (coarser columns over the same period, NCT05020015). |

## D. Tools, gate and packaging

| # | Status | File | Change | Notes |
|---|---|---|---|---|
| B6 | done 23f1268 | `tools/dryrun.py` | Create `<pid>/soa-tables/extracted/` when missing (brand-new protocol). | Failed with FileNotFoundError at `build_scratch`; worked around with an empty folder. |
| B26 | done 23f1268 | `tools/dryrun.py` | Take only staged studies that have a protocol folder in `SOA_TABLES_COLLECTION`; print the skipped (inv 12, same filter as `promote_dryrun.py`). | Still takes every folder in STAGING (line 135). Do with B6. |
| B7 | open | `notebooks/00_download_extract.ipynb` | `extract_soa` accepts the comma-separated ranges (`16-18,85-87`); reuse `page_map.parse_soa_pages`. | Notebooks are run by hand; cell change only. |
| B8 | done a77f8c5 | `tools/page_map.py` | Report line prints the declared ranges, not first–last ("declared 16-87"). | Cosmetic; stdout only. |
| B27 | open | `tools/gate.py` | Check 14 on a mixed-version corpus (inv 21c): an accepted-versions list or an env override, so calibration on published tables does not FAIL 14 on every table. | Matters for calibration and acceptance runs. |
| B28 | open | `tools/promote_dryrun.py` | Hard-codes the sweep-1 promotion (`RETIRE` / `KEEP`, "Phase 3" docstring) — take the lists from arguments or a small JSON per run (inv 27b). | Small to medium. |
| B29 | open | `tools/gate.py` / new check | Page-break defects (inv 17): (a) a mark-free row at a page top whose label continues the last row of the previous page; (b) reprinted header values that disagree across pages. | Small to medium. |
| B31 | done 9c02057 | `pyproject.toml` | Add `jsonschema` to the `test` extra: four test modules (and `tools/gate.py`) import it, so a fresh `pip install .[test]` fails at collection. | Found setting up a fresh venv on 534d793. |

## E. Ops and routine

| # | Status | Item |
|---|---|---|
| B12 | open | A small script for the review cycle: rebuild the protocol(s) → revert timestamp-only files → commit → `rdf.build_trig` → pytest → commit. Every review change needs two collections commits (TriG pins the data commit). |
| B13 | open | Write into the routine: revert timestamp-only regenerations (`resolved_at`, `consolidated_at`, `generated`, `audited_at`, root index footer) with `git restore` before a data commit. |
| B14 | open | Manifest rule for `sponsor`: **as printed on the document** (decided 2026-11-22), not the current AACT lead sponsor — the document is the file of record. To do: write the rule where the manifest is described, and correct NCT03739203 (document Allergan; AbbVie, from AACT, is written now); check the other protocols for the same mismatch. |
| B15 | open | `tools/README.md`: one paragraph on new protocols with no baseline (the cell_gene_therapy / misc_studies method: no blinding, unredacted prompt); today it describes only the re-extraction harness. |
| B30 | done 371bacc | The backlog lives in the repo (`documents/backlog.md`), as soa2usdm kept `inventory-improvements.md`. |

## Not carried over (soa2usdm items outside soa-tables, or settled)
- Done before the split (inherited): inv 1, 2, 4, 5, 6, 9, 10, 11, 14, 15, 16, 18, 19, 23, 24, 28; the parts of 20, 21,
  22, 25, 26 that concern soa-tables, except those listed above. Inv 21b settled by the inv 25a sidecars.
- Done in soa-tables since the split: inv 34 (redacted rows no longer match across tables, 31d5b5a).
- Closed by decision: inv 3 (resolving references to section text is not Layers 1–3); inv 21h (published conventions
  not backfilled).
- Consumer side, not soa-tables: inv 21f (study-level glossary from the abbreviation block), inv 21g (transpose
  row-oriented sampling tables after resolve, into the USDM shape), inv 32c (sequence and branching — timeline anchors /
  SoA patterns, after Layer 3), and the activity-inventory items (the inventory left soa-tables on 2026-11-20).

## Confirmed — keep as is (no item)
- Transcript, not interpretation: in both USDM comparisons (SoA Workbench on NCT01797120, Protocol Explorer on
  NCT04304508), wherever the grids differ the protocol supports soa-tables.
- What only soa-tables keeps — footnotes bound to cells, per-cell qualifiers, within-visit timepoint tables, visit
  modality, windows as printed — is what both USDM files lost.
- Schedule column order plus header rows is the reliable key; Protocol Explorer's encounter links and Timing values were
  wrong while its instance order was right.
