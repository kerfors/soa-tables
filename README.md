# soa-tables

> LLM extraction with mechanical verification, and a programmatic pipeline for transforming Schedule of Activities (SoA) tables from clinical trial protocols into structured, fully traceable data. Claude extracts; mechanical checks re-derive the grid from the PDF; a domain expert reviews the evidence and adjudicates through auditable corrections; Python handles resolution, consolidation, and visualization.

**Start here:** [kerfors.github.io/soa-tables](https://kerfors.github.io/soa-tables/) — the schemas on one page.

This repository is the **product**: the Python package, JSON schemas, prompts, notebooks, and design documents. Protocol collections — the derived extraction outputs and their visualizations — live in a **separate data repository**, [`soa-tables-collections`](https://github.com/kerfors/soa-tables-collections), so that code and data version independently and a public code repo stays free of protocol PDFs.

**Scope: transcript, not interpretation.** soa-tables stops at the consolidated SoA: what the tables print, reviewed against the pages. What the SoA *means* — a USDM document, CDISC terms for its activities — is left to consumers of the consolidated output. soa-tables was split out of [soa2usdm](https://github.com/kerfors/soa2usdm) (at commit `dc343b5`, 2026-11-09), which now holds the USDM Instantiation side. The collections were regenerated into soa-tables-collections; [soa2usdm-collections](https://github.com/kerfors/soa2usdm-collections) is frozen at `cdecda08`.

The approach originated in the PHUSE EU Connect 2025 paper [*From Schedules of Activities (SoA) to USDM: Automating Protocol Extraction Using Large Language Models*](https://phuse.s3.eu-central-1.amazonaws.com/Archive/2025/Connect/EU/Hamburg/PAP_ML08.pdf) (Forsberg & Ulander). The workflow has evolved substantially since — see [A Two-Year Journey](#a-two-year-journey) below.

## Architecture

Three processing layers:

| Step | Question | How | Scope |
|------|----------|-----|-------|
| **1. Extraction** | What does this table show? | Claude + mechanical verification + human review | per table |
| **2. Resolution** | What precisely is in it? | Programmatic (Python) | per table |
| **3. Consolidation** | What was the protocol expressing? | Programmatic (Python) | per protocol |

Layer 1 runs as a single non-interactive Claude pass (PDF→JSON): the model extracts, re-derives the mark matrix mechanically from the PDF (bbox column-binning on text-layer grids, rule-line detection on scanned ones), and ends with an uncertainty report that surfaces every judgement call for human review. Human fixes flow through an auditable corrections sidecar — the raw extraction is never overwritten. Layers 2–3 are pure Python, producing consolidated structured data and HTML visualizations; an independent row audit compares extracted rows against what the source pages actually print. The cross-table matches made by consolidation are reviewed in the consolidated view and decided through a per-protocol consolidation sidecar, which consolidation reads before matching.

The core processing logic lives in the `soa_tables/` package; a batch notebook (`01_batch.ipynb`) provides the execution wrapper across protocol collections.

See [`documents/soa-tables-schema-architecture.md`](documents/soa-tables-schema-architecture.md) for the full design rationale and [`documents/background-and-challenges.md`](documents/background-and-challenges.md) for project history and the key extraction challenges that shaped this architecture.

The consolidated SoA has two interfaces: HTML pages for people, and RDF for programs — one TriG file per protocol, the same facts as the consolidated JSON with IRIs minted from the file of record ([`documents/identity.md`](documents/identity.md)). See [`documents/rdf-interface.md`](documents/rdf-interface.md); the fact model is [`schemas/rdf/soa-tables-facts.shacl.ttl`](schemas/rdf/soa-tables-facts.shacl.ttl).

## Repositories

| Repo | Contents |
|------|----------|
| **soa-tables** (this repo) | Package, schemas, prompts, notebooks, documents, regression fixtures |
| [**soa-tables-collections**](https://github.com/kerfors/soa-tables-collections) | Protocol collections: SoA pages and extraction inputs, derived resolution/consolidation outputs, HTML visualizations and RDF (TriG) per protocol (GitHub Pages). No full protocol PDFs. |
| [**soa2usdm-collections**](https://github.com/kerfors/soa2usdm-collections) | Frozen at `cdecda08`: its Layer 1–3 outputs are superseded by soa-tables-collections; keeps the Towards CDISC outputs |
| [**soa2usdm**](https://github.com/kerfors/soa2usdm) | Consumer: USDM Instantiation from a consolidated SoA; also, for now, the early Towards CDISC work |

The two repos are designed to sit side by side:

```
parent/
├── soa-tables/               # this repo
└── soa-tables-collections/   # data repo
```

The package discovers collections at `../soa-tables-collections/collections/` by default. Override with the `SOA_TABLES_COLLECTIONS` environment variable to point anywhere.

Cloning **soa-tables** alone is fully functional: the regression suite runs against fixtures shipped in `tests/fixtures/`, so tests pass with no collections checkout present. To build your own collection, clone `soa-tables-collections` (or start an empty one with the same layout) and work through protocols with the notebooks.

## Structure

```
soa-tables/
├── schemas/
│   ├── soa-table-extraction.schema.json     # Layer 1
│   ├── soa-table-corrections.schema.json    # Layer 1 corrections sidecar
│   ├── soa-table-resolved.schema.json       # Layer 2
│   ├── soa-tables-consolidated.schema.json  # Layer 3
│   ├── soa-consolidation-corrections.schema.json  # Layer 3 corrections sidecar (match decisions)
│   └── rdf/soa-tables-facts.shacl.ttl       # RDF fact model: terms + closed shapes (hand-written)
│
├── prompts/
│   ├── EXTRACTION_WORKFLOW_GUIDE.md          # How to run extraction and the pipeline
│   └── PDF_TO_JSON_PROMPT.md                 # Layer 1 extraction, single pass
│
├── documents/
│   ├── soa-tables-schema-architecture.md     # Three-layer design rationale
│   ├── background-and-challenges.md          # Project history and key challenges
│   ├── soa_table_type_definitions.md         # Table classification (taxonomy)
│   ├── re-extraction-acceptance-checklist.md # Re-extraction criteria and promotion gate
│   ├── re-extraction-baseline*.json          # Machine baseline and mined claims (tools/)
│   ├── identity.md                           # How elements are named: IRIs from the file of record
│   ├── rdf-interface.md                      # The consolidated facts as TriG: content, build, checks
│   ├── backlog.md                            # Open work, numbered B1 onward
│   └── *.md                                  # Design notes (annotation model, identifiers)
│
├── docs/                             # Published on GitHub Pages: kerfors.github.io/soa-tables
│   ├── index.html                   # Landing page: the infographic and the repository
│   └── schema-chain.html            # Infographic of the schemas (generated by tools/build_explainer.py)
│
├── soa_tables/                       # Core Python package
│   ├── config.py                    # Paths, collection discovery
│   ├── base.py                      # PipelineStepBase
│   ├── errors.py                    # Error collection
│   ├── analytics.py                 # Metrics and timing
│   ├── corrections.py               # ApplyCorrectionsStep (raw + corrections)
│   ├── resolve.py                   # ResolveStep (Layer 2)
│   ├── references.py                # document_references: what an annotation text points at, as printed
│   ├── consolidate.py               # ConsolidateStep (Layer 3)
│   ├── consolidation_corrections.py # Consolidation sidecar: keep / split / merge / refines
│   ├── visualize.py                 # Consolidated HTML, with the 'Matches across tables' review section
│   ├── index_generator.py           # Collection index page; renders reports, refreshes nav
│   ├── collections_index.py         # Root index across collections
│   ├── nav.py                       # Shared navigation for all generated pages
│   ├── page_grid.py                 # Rule-line cell geometry (vector + raster)
│   ├── row_audit.py                 # RowAuditStep — extracted rows vs the pages
│   ├── review_page.py               # ReviewPageStep — the extraction on its source pages
│   ├── identity.py                  # Mints local ids and IRIs (documents/identity.md)
│   └── rdf.py                       # Consolidated facts → TriG and back (documents/rdf-interface.md)
│
├── tools/                           # Re-extraction harness and the infographic generator (tools/README.md)
│
├── notebooks/
│   ├── 00_download_extract.ipynb    # Download PDFs, extract SoA pages, scaffold folders
│   └── 01_batch.ipynb               # Batch processing across a collection
│
├── tests/
│   ├── test_pipeline_regression.py  # Golden-output regression over discovered protocols
│   ├── test_page_geometry.py        # Cell geometry + row audit, incl. negative controls
│   ├── test_review_items.py         # review_items; decided via sidecar
│   ├── test_review_page.py          # Review page: model, tiled-table column map
│   ├── test_consolidation_corrections.py  # Consolidation sidecar: ops, stale entries, the matches view
│   ├── test_document_references.py  # document_references on annotations
│   ├── test_placeholders.py         # Placeholder annotations: schemas, consolidation, pages
│   ├── test_identity.py             # Minting: deterministic, no collisions
│   ├── test_rdf.py                  # RDF: round trip, shapes, identical builds, pages, matches
│   ├── test_shacl_shapes.py         # The shapes file, valid and broken graphs
│   └── fixtures/                    # Golden protocols (JSON only), negative controls, pages — tests run standalone
│
└── pyproject.toml
```

## Running It

**Layer 1 — Extraction (Claude):**
Attach the prompt file + your data to a new Claude conversation. See [`prompts/EXTRACTION_WORKFLOW_GUIDE.md`](prompts/EXTRACTION_WORKFLOW_GUIDE.md) for the full workflow.

**Layers 2–3 — Resolution, Consolidation & Visualization (Python):**
The `soa_tables/` package implements all processing steps. Use `01_batch.ipynb` to run across a protocol collection — set `COLLECTION` in the config cell and execute.

**Checking extractions against the source pages (Python):**
`soa-tables-row-audit --collection <name>` compares every extracted activity row against the rows its SoA pages actually print, and writes `row_audit.json` to the collection root. Needs poppler (`pdftoppm`, `pdftotext`, `pdfinfo`) and the `bands` extra: `pip install -e '.[bands]'`.

**Reviewing an extraction (HTML):**
`ReviewPageStep` (run by `01_batch.ipynb`, or `soa-tables-review-page <NCTID> --collection <name>`) writes `{NCTID}_review.html` in `extracted/`: the source pages (pre-rendered at ingest into `{NCTID}_soa_pages/` by `tools/page_map.py --render`, each stamped below the page bitmap with its document page number) with the extracted rows, marks, notes, decisions (`review_items`, open or decided with the corrections that decided them) and cross-table folds drawn where they refer to, linked both ways with the extracted table. It shows nothing that is not already in the pipeline's files and writes nothing — a decision only drafts an entry for the corrections sidecar. Same requirements as the row audit.

The review page is a proof of concept with two aims: to envision what a user interface for a review user could look like — worklist (`review_items`), evidence, and the sidecar write path in one place — and to showcase the traceability the pipeline already carries: every highlight is an existing extraction field drawn at the position on the source page it refers to. It also lays groundwork for the consumers that interpret the SoA: any claim about what an SoA table expresses should be checkable against a printed page in seconds, which is why the page images are pre-rendered and stamped at ingest.

**Reviewing cross-table matches (HTML):**
The consolidated view (`{NCTID}_consolidated.html`) has a section *Matches across tables*. It lists the rows consolidation merged on name similarity and the near matches it kept separate. A reviewer decides each one: `keep`, `split` or `merge`; `refines` states that a table or a row details a row of another table without being merged. The view drafts the entries for `consolidated/{NCTID}_consolidation_corrections.json` and writes nothing. Consolidation reads the sidecar before matching and stops on a stale entry. The collection index shows the state per protocol ('matches: n open of N'). The review page's *Across tables* tab shows the matched rows on their source pages; the decision is made in the consolidated view.

**Building the RDF (Python):**
`python -m soa_tables.rdf <collection> <protocol_id> -o <protocol_id>_facts.trig` writes one protocol's facts as TriG. It needs the protocol PDF (the file of record) in the protocol folder, and refuses when its inputs or the code have uncommitted changes, since the file is pinned to both commits. See [`documents/rdf-interface.md`](documents/rdf-interface.md).

## Key Design Decisions

**Errors collected, not raised.** Steps continue on errors — partial success matters when one table out of four has issues.

**Verification before propagation.** No extraction reaches the pipeline unreviewed. The mechanism has changed four times — Excel checkpoint (2025), then mechanical mark-check plus uncertainty report, then an independent row audit on top, then a review page that draws the extraction on its source pages and turns the report's open decisions into data (`review_items`, decided through the corrections sidecar) — but the invariant has not: catch errors before they propagate into downstream JSON.

**Re-derive, don't eyeball.** The mark matrix is reconstructed mechanically from PDF geometry and diffed against the model's visual read — on dense grids this has caught merged-span errors that human Excel verification missed. Provenance fields record *how* each interpreted value was derived: a re-derivable method, not a confidence number.

**Claude as product, not API.** Layer 1 runs in Claude's product surface — first chat conversations, now Claude Cowork — not through an API integration. Cowork opened new possibilities: file access and code execution inside the extraction session are exactly what make mechanical self-verification possible, since the same session that reads the table re-derives the mark matrix from the PDF. While both the models and the workflow are changing this fast, an API solution would have frozen an earlier workflow shape into code and meant rebuilding harness plumbing the product provides — and improves — for free. An API path stays open once the workflow stabilizes.

**One file per table, then integrate.** Each table gets its own extraction/resolution file. Consolidation handles cross-table logic.

**Raw + corrections, never overwrite.** A verified extraction is the raw extraction plus a corrections sidecar applied deterministically — the original model output is preserved and every change is auditable. Layer 3 follows the same rule: decisions on cross-table matches are kept in a consolidation sidecar, not written into the consolidated output.

**Traceability throughout.** Every element traces from consolidated output back through resolved and extracted to PDF page and row position.

## A Two-Year Journey

This work spans roughly two years (2024–2026) of rapid LLM advancement, and the workflow changed shape with it. It began with automated multi-pass extraction, whose output could not be verified. The [2025 PHUSE paper](https://phuse.s3.eu-central-1.amazonaws.com/Archive/2025/Connect/EU/Hamburg/PAP_ML08.pdf) drew the consequence: a two-conversation workflow with a human-verified Excel checkpoint between PDF and JSON. Better models then made a third shape possible — a single non-interactive pass whose verification is engineered in rather than performed live: a mechanical mark-check re-derived from the PDF, an uncertainty report in place of interactive gates, a programmatic row audit, and an auditable corrections sidecar. Claude Cowork made this third shape practical — file access and code execution inside the extraction session itself. The human moved from guiding the extraction to reviewing its evidence.

Each model generation brought material improvements in vision understanding, table structure recognition, and semantic reasoning. All pipeline steps use the latest available Claude model. See [`documents/background-and-challenges.md`](documents/background-and-challenges.md) for the fuller history.

## License

Code is licensed under the [MIT License](LICENSE). Documentation and schemas are shared under [CC-BY-4.0](https://creativecommons.org/licenses/by/4.0/).

## Author

Kerstin Forsberg — information architect specializing in clinical data standards. Built iteratively with Claude (Anthropic).
