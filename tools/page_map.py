"""Derive the PDF-page → document-page map for each study's `_soa.pdf`, and flag what needs eyes.

Extraction agents must never read a page number off a printed page footer. Measured across the 22
protocols of `usdm_data`: one protocol's footer runs one LOWER than the document page, another's
runs one HIGHER, one prints a protocol number (5020) instead of a page number, and 15 print nothing
at all. So the map has to be computed and handed to the agent.

The trap this script exists for
------------------------------
The obvious rule — anchor the excerpt at its last page, `doc_page(pdf i) = B - (N - i)` — is WRONG
whenever the excerpt carries extra pages at the BACK, and it fails silently: every page number in
the extraction shifts by a constant and nothing downstream notices. **The manifest's `soa_pages`
describes the SoA TABLE pages, not the excerpt.** An excerpt can carry context at either end:
a cover or section-intro page at the front, or an appendix, flow chart or notes page at the back.
Only the content says which. Four of 22 protocols had back matter; two were extracted against a
shifted map and had to be re-run.

So this script does NOT guess. Where the excerpt has more pages than the declared range, it prints
both candidate mappings, shows the first and last lines of the pages in question, and asks for a
decision. Confirm by writing the answer into the manifest or by passing --front / --back.

Rendered pages (--render)
-------------------------
For each decided study, --render writes `<protocol>/<STUDY>_soa_pages/pNN.png` — one PNG per
PDF page at RENDER_DPI — plus a `pages.json` manifest. A caption strip is APPENDED BELOW the
page bitmap carrying the computed document page number: an addition to the canvas, never an
overprint, so the page bitmap itself stays verbatim pdftoppm output. The stamp repeats the
map; when a map decision changes, re-run --render so stamp and map cannot drift apart.
The review page consumes these images and pages.json. Extraction input stays the PDF plus
PAGEMAP.md — stamped images are human-facing.

Physical pages (--physical)
---------------------------
The document page is the numbering the transcript uses (from the declared SoA range in
studies_protocols.xlsx). It is not always the page's position in the file of record
(`<STUDY>.pdf`, sha256 in register.csv): measured 2026-11-21, it runs one or two lower in 14 of
the 22 usdm_data protocols. --physical adds `physical_page` to every pages.json entry: the one
page of the file of record within doc_page ± PHYSICAL_WINDOW whose text equals the excerpt
page's text (whitespace normalised), or, for a page without text, whose 20-dpi grey bitmap is
equal. No match or more than one stops before that study's pages.json is written.
physical_page is for the RDF's Page IRIs (documents/identity.md: a Page is a physical page of the
file of record); the transcript keeps the document page.

Usage:
    python3 tools/page_map.py --collection usdm_data                 # report, decide nothing
    python3 tools/page_map.py --collection usdm_data --write         # write blind/<STUDY>/PAGEMAP.md
    python3 tools/page_map.py --collection usdm_data --render        # write <protocol>/<STUDY>_soa_pages/
    python3 tools/page_map.py --collection usdm_data --back NCT04184622 --back NCT03637764
    python3 tools/page_map.py --collection usdm_data --study NCT03637764 --write   # named studies only
    python3 tools/page_map.py --collection usdm_data --physical      # add physical_page to pages.json
"""

import argparse
import functools
import json
import os
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from soa_tables import config  # noqa: E402

RENDER_DPI = 150         # extraction-grade; the review page scales down in HTML
STRIP_PT = 18            # caption strip height in points, scaled by RENDER_DPI
PHYSICAL_WINDOW = 3      # --physical looks for the page within doc_page ± this
NOTE = ("document page = the page number the transcript uses (table page_start/page_end, source_page), "
        "from the declared SoA range in studies_protocols.xlsx; printed page footers are not used. "
        "physical_page = the same page's position in the file of record (<study>.pdf), added by "
        "tools/page_map.py --physical. The caption strip below each page bitmap is synthetic; "
        "the page bitmap above it is verbatim pdftoppm output.")


def pdf_pages(pdf):
    out = subprocess.run(["pdfinfo", str(pdf)], capture_output=True, text=True).stdout
    m = re.search(r"^Pages:\s+(\d+)", out, re.M)
    return int(m.group(1)) if m else 0


def page_text(pdf, i, layout=True):
    cmd = ["pdftotext"] + (["-layout"] if layout else []) + ["-f", str(i), "-l", str(i), str(pdf), "-"]
    return subprocess.run(cmd, capture_output=True, text=True).stdout


# Running headers repeat on every page and say nothing about which page this is; the deciding
# evidence is the first line of real content (a section heading, an appendix title, a table caption).
BOILERPLATE = re.compile(r"^(confidential|clinical (study )?protocol|amended clinical|protocol\s|"
                         r"page \d+|.{0,3}$)", re.I)


def first_lines(pdf, i, n=3):
    lines = [l.strip() for l in page_text(pdf, i).splitlines() if l.strip()]
    meaty = [l for l in lines if not BOILERPLATE.match(l)]
    return (meaty or lines)[:n]


def parse_soa_pages(value):
    """soa_pages -> [(first, last), ...]: "13-18" -> [(13, 18)]; "5" -> [(5, 5)];
    "16-18,85-87" -> [(16, 18), (85, 87)] where the SoA tables sit apart in the document.

    Ranges in document order, none reversed, none overlapping or touching the one before
    (touching ranges are one range). Anything else stops.
    """
    spans = []
    for part in str(value).split(","):
        part = part.strip()
        a, b = (int(x) for x in part.split("-")) if "-" in part else (int(part), int(part))
        if b < a or (spans and a <= spans[-1][1] + 1):
            raise ValueError(f"soa_pages {value!r}: range {part!r} is reversed or not after the one before")
        spans.append((a, b))
    return spans


def read_manifest(collection):
    """(nct_id -> [(first_doc_page, last_doc_page), ...]) from the collection's studies_protocols.xlsx.

    One range for most studies; several where the declared soa_pages lists more (parse_soa_pages).
    """
    import openpyxl
    root = Path(config.COLLECTIONS[collection])
    book = openpyxl.load_workbook(root.parent / "studies_protocols.xlsx")
    sheet = book["protocols"]
    header = [c.value for c in sheet[1]]
    out = {}
    for row in sheet.iter_rows(min_row=2, values_only=True):
        r = dict(zip(header, row))
        if not r.get("nct_id") or not r.get("soa_pages"):
            continue
        out[r["nct_id"]] = parse_soa_pages(r["soa_pages"])
    return out, root


def render_study_pages(pdf, study, pages, declared_last, out_dir):
    """Render pNN.png per PDF page plus pages.json, with a caption strip below the page bitmap.

    The strip carries the COMPUTED document page number — the page's sequence position in the
    source protocol PDF — because printed footers are unreliable (see module docstring). It is
    appended to the canvas below the page; the page bitmap itself stays verbatim.
    """
    from PIL import Image, ImageDraw, ImageFont
    out_dir.mkdir(parents=True, exist_ok=True)
    n = len(pages)
    strip_px = round(STRIP_PT * RENDER_DPI / 72)
    font = ImageFont.load_default(size=round(strip_px * 0.55))
    entries = []
    for i, doc in enumerate(pages, start=1):
        name = f"p{i:02d}.png"
        subprocess.run(["pdftoppm", "-png", "-r", str(RENDER_DPI), "-f", str(i), "-l", str(i),
                        "-singlefile", str(pdf), str(out_dir / name[:-4])],
                       capture_output=True, check=True)
        page = Image.open(out_dir / name).convert("RGB")
        canvas = Image.new("RGB", (page.width, page.height + strip_px), "#e8edf3")
        canvas.paste(page, (0, 0))
        draw = ImageDraw.Draw(canvas)
        draw.line([(0, page.height), (page.width, page.height)], fill="#1F4788", width=2)
        label = f"{study}  ·  SoA excerpt PDF page {i}/{n}  ·  document page {doc}"
        if doc > declared_last:
            label += "  (beyond the declared SoA range)"
        draw.text((strip_px // 2, page.height + strip_px // 2), label,
                  fill="#1F4788", font=font, anchor="lm")
        canvas.save(out_dir / name)
        entries.append({"pdf_page": i, "doc_page": doc, "file": name,
                        "width_px": canvas.width, "height_px": canvas.height,
                        "page_height_px": page.height})
    (out_dir / "pages.json").write_text(json.dumps(
        {"study": study, "dpi": RENDER_DPI, "strip_px": strip_px,
         "note": NOTE,
         "pages": entries}, indent=2) + "\n")


@functools.lru_cache(maxsize=None)
def _norm_text(pdf, i):
    return re.sub(r"\s+", " ", page_text(pdf, i, layout=False)).strip()


@functools.lru_cache(maxsize=None)
def _bitmap(pdf, i):
    return subprocess.run(["pdftoppm", "-q", "-r", "20", "-gray", "-f", str(i), "-l", str(i), str(pdf)],
                          capture_output=True, check=True).stdout


def add_physical_pages(study, soa_pdf, full_pdf, pages_json):
    """Write physical_page into every entry of pages_json (see module docstring). Returns {pdf_page: physical}."""
    doc = json.loads(pages_json.read_text())
    n_full = pdf_pages(full_pdf)
    found = {}
    for e in doc["pages"]:
        lo, hi = max(1, e["doc_page"] - PHYSICAL_WINDOW), min(n_full, e["doc_page"] + PHYSICAL_WINDOW)
        text = _norm_text(soa_pdf, e["pdf_page"])
        if text:
            hits = [j for j in range(lo, hi + 1) if _norm_text(full_pdf, j) == text]
        else:
            ref = _bitmap(soa_pdf, e["pdf_page"])
            hits = [j for j in range(lo, hi + 1) if not _norm_text(full_pdf, j) and _bitmap(full_pdf, j) == ref]
        if len(hits) != 1:
            sys.exit(f"{study}: excerpt page {e['pdf_page']} (document page {e['doc_page']}): "
                     f"{len(hits)} matching pages in {full_pdf.name} {lo}-{hi} {hits} — pages.json not written")
        found[e["pdf_page"]] = hits[0]
    entries = []
    for e in doc["pages"]:
        out = {"pdf_page": e["pdf_page"], "doc_page": e["doc_page"], "physical_page": found[e["pdf_page"]]}
        out.update({k: v for k, v in e.items() if k not in out})
        entries.append(out)
    doc["note"] = NOTE
    doc["pages"] = entries
    pages_json.write_text(json.dumps(doc, indent=2) + "\n")
    return found


def physical(args):
    manifest, root = read_manifest(args.collection)
    unknown = sorted(set(args.study) - set(manifest))
    if unknown:
        sys.exit(f"--study not in the {args.collection} manifest: {', '.join(unknown)}")
    for study in sorted(manifest):
        if args.study and study not in args.study:
            continue
        pages_json = root / study / f"{study}_soa_pages" / "pages.json"
        if not pages_json.exists():
            print(f"  {study:<14} no pages.json — skipped")
            continue
        full_pdf = root / study / f"{study}.pdf"
        if not full_pdf.exists():
            sys.exit(f"{study}: file of record {full_pdf} not found — pages.json not written")
        found = add_physical_pages(study, root / study / f"{study}_soa.pdf", full_pdf, pages_json)
        docs = {e["pdf_page"]: e["doc_page"] for e in json.loads(pages_json.read_text())["pages"]}
        shifts = sorted({found[i] - docs[i] for i in found})
        print(f"  {study:<14} {len(found):>2} page(s)  physical - document: {shifts}")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--collection", default="usdm_data")
    ap.add_argument("--blind", default=os.environ.get("SOA_TABLES_BLIND", "blind"))
    ap.add_argument("--write", action="store_true", help="write blind/<STUDY>/PAGEMAP.md")
    ap.add_argument("--render", action="store_true",
                    help=f"write <protocol>/<STUDY>_soa_pages/pNN.png at {RENDER_DPI} dpi + pages.json")
    ap.add_argument("--front", action="append", default=[], help="extra pages are at the FRONT")
    ap.add_argument("--back", action="append", default=[], help="extra pages are at the BACK")
    ap.add_argument("--explicit", default=None, help='JSON {"STUDY": [63,64,72,78]} for a non-contiguous excerpt')
    ap.add_argument("--study", action="append", default=[],
                    help="map only this study (repeatable); default: every study in the manifest (item 20d)")
    ap.add_argument("--physical", action="store_true",
                    help="add physical_page (position in the file of record) to every pages.json entry")
    args = ap.parse_args()
    if args.physical:
        return physical(args)

    explicit = json.loads(Path(args.explicit).read_text()) if args.explicit else {}
    manifest, root = read_manifest(args.collection)
    undecided = []

    unknown = sorted(set(args.study) - set(manifest))
    if unknown:
        sys.exit(f"--study not in the {args.collection} manifest: {', '.join(unknown)}")
    for study, spans in sorted(manifest.items()):
        a, b = spans[0][0], spans[-1][1]
        if args.study and study not in args.study:
            continue
        pdf = root / study / f"{study}_soa.pdf"
        if not pdf.exists():
            print(f"  {study:<14} no _soa.pdf — skipped")
            continue
        n = pdf_pages(pdf)
        declared_pages = [p for first, last in spans for p in range(first, last + 1)]
        declared = len(declared_pages)
        extra = n - declared

        if study in explicit:
            pages, how = explicit[study], "explicit (non-contiguous excerpt)"
        elif len(spans) > 1:
            if extra != 0:
                sys.exit(f"{study}: {len(spans)} declared ranges ({declared} pages) "
                         f"but the excerpt has {n} PDF pages")
            pages, how = declared_pages, f"{len(spans)} declared ranges; excerpt == declared ranges"
        elif extra == 0:
            pages, how = [a + i for i in range(n)], "contiguous; excerpt == declared range"
        elif extra < 0:
            pages, how = None, f"NON-CONTIGUOUS: {n} PDF pages for a declared span of {declared}"
        elif study in args.front:
            pages, how = [b - (n - 1 - i) for i in range(n)], f"{extra} extra page(s) at the FRONT"
        elif study in args.back:
            pages, how = [a + i for i in range(n)], f"{extra} extra page(s) at the BACK"
        else:
            pages, how = None, f"{extra} extra page(s) — front or back NOT decided"

        print(f"  {study:<14} pdf {n:>2}p  declared {a}-{b:<5} {how}")
        if pages is None:
            undecided.append(study)
            front = [b - (n - 1 - i) for i in range(n)]
            back = [a + i for i in range(n)]
            print(f"      if FRONT: doc {front[0]}-{front[-1]}   if BACK: doc {back[0]}-{back[-1]}")
            for i in (1, n):
                print(f"      pdf p{i}: {' | '.join(first_lines(pdf, i, 2))[:110]}")
            continue

        if args.write:
            d = Path(args.blind) / study
            d.mkdir(parents=True, exist_ok=True)
            lines = [f"# {study} — PDF page → document page", "",
                     f"This excerpt has {n} PDF page(s). {how}.", "",
                     "| PDF page | document page |", "|---:|---:|"]
            lines += [f"| {i + 1} | {p} |" + ("  ← beyond the declared SoA range" if p > b else "")
                      for i, p in enumerate(pages)]
            lines += ["", "Use the **document page** number in `table_metadata.page_start` / `page_end`",
                      "and in every activity's `source_page`. Do NOT read page numbers off the printed",
                      "page footers — in this corpus footers have been measured running one lower than",
                      "the document page, one higher, and in one case showing a protocol number instead.",
                      "This table is authoritative.", ""]
            (d / "PAGEMAP.md").write_text("\n".join(lines))

        if args.render:
            render_study_pages(pdf, study, pages, b, root / study / f"{study}_soa_pages")
            print(f"      rendered {len(pages)} page(s) → {study}_soa_pages/")

    if undecided:
        print(f"\n{len(undecided)} study(ies) need a decision before extraction: {', '.join(undecided)}")
        print("Read the pages shown above, then re-run with --front/--back (or --explicit for a")
        print("non-contiguous excerpt). Guessing here shifts every page number in the extraction.")
        return 1
    print("\nall studies mapped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
