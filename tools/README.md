# Re-extraction harness

Tooling for re-extracting a collection's Layer 1 with fresh agents and deciding, mechanically,
whether the result may replace what is already there. Written for the `usdm_data` sweep of
2026-08-17; used again for sweep 2 (2026-09-26/27) and the prompt 3.9.x acceptance runs.

Nothing here decides whether a delta is *acceptable*. It reports what the delta is, and refuses to
guess where guessing would be silent.

| script | what it does |
|---|---|
| `page_map.py` | derives the PDF-page → document-page map per study; **refuses to guess** where the excerpt has extra pages; `--study` limits it to named studies |
| `gate.py` | per-table promotion gate: schema, private-use characters, orphans, marker agreement, containment, typing, page coverage, merged ranges, baseline deltas, marker bindings, review items vs report, provenance, quote fidelity; `--partial` when only some tables of a study are staged |
| `dryrun.py` | the two gate steps that need the corpus rather than the staging area — row audit, and the deterministic layers — in a throwaway scratch collection |
| `promote_dryrun.py` | rehearses the whole promotion (install, retire/keep sidecars, rebuild, regenerate the published index pages) so it can be checked before anything real is touched |
| `audit_blinding.py` | reads the subagent transcripts and reports tool calls that reached outside the blind tree, or into memory, Project knowledge or past chats |
| `stamp_model.py` | writes `extraction_metadata.model` into staged extractions from the run setting; refuses to overwrite a different value |
| `baseline.py` | regenerates `documents/re-extraction-baseline.json` from the accepted corpus with the gate's and the row audit's own code; same corpus, same bytes |
| `verify_mined.py` | checks `documents/re-extraction-baseline-mined.json`: key sets, and every `evidence_quote` verbatim in its extraction log |
| `redaction/` | `apply_redactions.py` + `REDACTIONS.json`: the redacted prompt and taxonomy for the blind tree (step 2) |

Paths come from the environment: `SOA_TABLES_REPO`, `SOA_TABLES_COLLECTIONS`, `SOA_TABLES_COLLECTION`,
`SOA_TABLES_STAGING`, `SOA_TABLES_BLIND`, `SOA_TABLES_CALIB`, `SOA_TABLES_SCRATCH`, `SOA_TABLES_SIDECARS`,
`SOA_TABLES_BASELINE` (default `documents/re-extraction-baseline.json`; misc_studies has its own).

## The method, in the order it has to happen

**1. Blind the extractors physically, not by instruction.** Move the corpus, both repo clones, the
acceptance checklist, the machine baseline, the calibration tree, the scratch pipeline and *this
directory* out of the tree the agents can see, for the duration of the fan-out. `gate.py` carries
corpus counts in its own calibration comments; a scratch collection is a full copy of the corpus.
Give each agent only `blind/<STUDY>/` — the PDF and its `PAGEMAP.md` — plus a redacted copy of the
prompt, taxonomy and schema. Where the agent transcripts are available, audit them with
`audit_blinding.py`; sweep 2 runs without them (checklist §9).

**2. Redact the instructions.** The shipped prompt and taxonomy contain worked examples that name
real protocols *and give away their answers* — a table's classification, a restoration's activity
and mark counts, the verdict on a containment pair a gate check is about to re-ask. Generalise those
spans: keep the rule, strip the study identity and the numbers. The log and the script are in
`tools/redaction/` (outside the agents' tree, step 1). Re-run `apply_redactions.py` after every
prompt or taxonomy edit; it fails if a span does not match once or an identifier survives.

**3. Compute the page map; do not derive it from footers.** See `page_map.py`'s docstring. Printed
footers were measured running one lower than the document page in one protocol and one higher in
another, with a protocol number instead of a page number in a third.

**4. Calibrate every check against the ACCEPTED corpus before trusting it — and then run a negative
control.** Copy the signed-off extractions into a `calib/` tree, point `gate.py` at it and require
**0 FAIL**: anything that fails there would fail a *perfect* re-extraction. Four checks were
miscalibrated on first write and each was caught this way. But calibration only proves a check does
not false-positive. Whether it fires at all needs the opposite test — point it at output you know
is broken. A binding check written for a specific collapse passed silently *on that very collapse*
because it read its expected value off the wrong object; only the negative control found it.
Two caveats since prompt 3.9.0: check 14 FAILs on every table extracted under an older prompt
version, and check 12 takes its binding baseline from CALIB's raw files — give it the published
`.verified.json` copies renamed `*_extraction.json`, or tables fixed by sidecar FAIL.

**5. Rehearse the promotion in a scratch collection** with `promote_dryrun.py`, then compare the
real rebuild against the rehearsal by timestamp-scrubbed corpus hash. Identical hashes are what let
a test suite run in one environment vouch for a rebuild done in another.

## Traps that cost real time

- **`op: add` is a bare append.** `corrections.apply_corrections` does `arr.append(c["set"])` — no
  match key, no dedup. Retire or empty every sidecar whose content the re-extraction now produces
  natively, *before* the pipeline runs, or it silently duplicates.
- **Stale derived artefacts walk back in.** `Consolidate` reads `resolved/`, so a resolved JSON for
  a table the re-extraction no longer produces reappears in the consolidated output and inflates the
  table count. Clear `resolved/` and `consolidated/`, not just `extracted/`.
- **Pinned expectation tables must be keyed by collection AND protocol.** The regression suite runs
  over the live collection *and* the banked fixtures. Keyed by protocol alone, re-pinning after a
  sweep silently moves a frozen control.
- **A checker artefact reads exactly like a fabricated quote.** Inspect the failures before
  reporting a fidelity number: a quote-matching regex that resumes after a closing quote will score
  the prose *between* two quotations as a third quotation.
- **Marker bindings can vanish without any check firing.** `resolve` links an annotation to its
  element through the row's `annotation_markers`; the shipped detector reports only *partial*
  disagreement, so when both sides are empty nothing is partial. `gate.py` check 12 compares the
  count of distinct markers carried on rows against the baseline.

## Other tools in this directory

Not part of the re-extraction harness.

| script | what it does |
|---|---|
| `build_explainer.py` | builds `docs/schema-chain.html`, the infographic of the schemas, from `schemas/*.json` and `explainer_schema_chain.template.html`; every field path the page names is checked against its schema, and a path that no longer exists stops the build. Run it after a schema change |
| `review_cycle.py` | the review cycle after a review decision: rebuild, restore timestamp-only files, data commit, TriG + pytest, TriG commit — see below |

## Review cycle (after a review decision)

Every review change ends in two collections commits: the data commit (sidecars and the regenerated files)
and the TriG commit, because the TriG pins the data commit (`st:collectionsCommit`) and the code commit
(`st:codeCommit`, soa-tables HEAD). `review_cycle.py` runs it in four calls with two stops:

```
python tools/review_cycle.py rebuild <collection> [PROTOCOL ...]   # stop: read the report
python tools/review_cycle.py commit-data -m "..."
python tools/review_cycle.py trig                                  # stop: read the quad diff and pytest
python tools/review_cycle.py commit-trig -m "..."
```

`rebuild` runs the `01_batch.ipynb` steps and both index pages (no protocol given: every extractable
protocol of the collection), then compares every changed file with HEAD with the run timestamps masked:
`resolved_at`, `consolidated_at`, `generated_at`, `audited_at` (as JSON keys, in JSON embedded in HTML,
and as rendered HTML fields) and `generated <time>` in page text. A file whose masked compare is empty is
restored with `git restore`; every other file is kept and reported field by field. Timestamp-only is shown,
not assumed (B34): a page with real changes is never reverted. The list of timestamps is closed on purpose
— a new timestamp makes files show up as real changes until it is added to the script.

`trig` writes `<protocol>_facts.trig`, prints an rdflib quad diff against HEAD (non-blank quads per
predicate, pinned values old → new, blank-node triples by isomorphism) and runs pytest; `trig --no-test`
followed by `test` splits that when a call has little time. `commit-trig` refuses unless pytest passed
against the current commits. `tests/test_review_status_committed.py` checks that every review page shows
the review status its sidecars give.

The script never pushes, never uses `git add -A`, never edits sidecars, and never runs the next step by
itself. Edits made before `rebuild` (sidecars, manifest) go into the data commit as they are; `rebuild`
refuses if generated files are already dirty, or if files outside the collection are. Where the repo has no
git identity (the Cowork VM), commits use `-c user.name/-c user.email`; no config is changed.
