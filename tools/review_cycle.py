"""Review cycle for one collection: rebuild, keep only real changes, two commits (B12, B13, B34).

Usage:  python tools/review_cycle.py rebuild <collection> [PROTOCOL ...]
        python tools/review_cycle.py commit-data -m MESSAGE
        python tools/review_cycle.py trig [--no-test]
        python tools/review_cycle.py test
        python tools/review_cycle.py commit-trig -m MESSAGE

rebuild      Runs the 01_batch.ipynb steps (ApplyCorrections, Resolve, Consolidate, ReviewPage,
             Visualize) for the protocols (none given: every extractable protocol of the collection),
             then the collection index and the root index. Classifies every file the run changed:
             timestamp-only (identical once the timestamps below are masked) is restored with
             `git restore`; everything else is kept and reported, field by field for JSON and
             for JSON embedded in HTML. Stops there.
commit-data  Commits your edits (files that were dirty before rebuild) and the kept files.
trig         Writes <protocol>_facts.trig for each protocol (python -m soa_tables.rdf), shows the
             quad diff against HEAD, then runs pytest (unless --no-test). Stops there.
test         Runs pytest only (after `trig --no-test`).
commit-trig  Commits the TriG files, once pytest has passed against the current commits.

Timestamp-only is shown, not assumed: a file is restored only when its masked compare is
empty. The list of timestamps is closed on purpose — an unknown timestamp makes the file a real
change, so a file can be kept by mistake but never reverted by mistake.

Never, on its own: push; `git add -A`; edit sidecars or the manifest; run the next step;
restore a file that has a real change; touch files outside the collection (except the root
index.html, which the pipeline writes).

State between steps: <collections repo>/.git/review_cycle.json (never tracked).
Commit messages are used as given (no trailer is added). If the repo has no user.name (the
Cowork VM), commits use -c user.name/-c user.email for Kerstin Forsberg; no config is changed.
"""

import argparse
import difflib
import json
import os
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from soa_tables import config  # noqa: E402

# Closed list: keys whose value is a run timestamp, and text patterns that carry one.
TS_KEYS = {"resolved_at", "consolidated_at", "generated_at", "audited_at"}
TS_KEY_TEXT = re.compile(r'("(?:' + "|".join(sorted(TS_KEYS)) + r')"\s*:\s*)"[^"]*"')
TS_GENERATED_TEXT = re.compile(
    r"(?i)(generated\s+)\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:[+-]\d{2}:\d{2}|Z| UTC)?")
# The key rendered as an HTML field, e.g. consolidated_at</td><td><span class="data">2026-…
TS_KEY_HTML = re.compile(
    r"(\b(?:" + "|".join(sorted(TS_KEYS)) + r")(?:\s*<[^>]+>\s*)+)"
    r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:[+-]\d{2}:\d{2}|Z)?")
EMBEDDED = re.compile(r"\b(?:const|var|let)\s+([A-Za-z_$][\w$]*)\s*=\s*(?=[\[{])")
MASK = "<ts>"

# Files the pipeline writes. Dirty before `rebuild` means an earlier run was neither committed
# nor restored, and rebuild refuses to start.
GENERATED_SUFFIXES = ("_resolved.json", "_viewer.html", "_consolidated.json", "_consolidated.html",
                      "_review.html", ".verified.json", "index.html", "_facts.trig")

DETAIL_CAP = 25
FALLBACK_IDENTITY = ["-c", "user.name=Kerstin Forsberg", "-c", "user.email=kerfors@users.noreply.github.com"]


class CycleError(Exception):
    pass


# ---------------------------------------------------------------- git

def git(repo: Path, *args, check=True) -> str:
    r = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)
    if check and r.returncode != 0:
        raise CycleError(f"git {' '.join(args)} failed: {r.stderr.strip()}")
    return r.stdout


def collections_top() -> Path:
    return Path(git(config.COLLECTIONS_ROOT, "rev-parse", "--show-toplevel").strip())


def dirty(repo: Path, *paths) -> dict:
    """{path: status} for every changed or untracked file (porcelain v1, paths relative to repo)."""
    out = git(repo, "status", "--porcelain=v1", "-z", "--untracked-files=all", "--", *paths)
    result = {}
    for entry in out.split("\0"):
        if entry:
            result[entry[3:]] = entry[:2]
    return result


def head_text(repo: Path, path: str):
    r = subprocess.run(["git", "-C", str(repo), "show", f"HEAD:{path}"], capture_output=True)
    return r.stdout.decode("utf-8") if r.returncode == 0 else None


def identity(repo: Path) -> list:
    return [] if git(repo, "config", "user.name", check=False).strip() else FALLBACK_IDENTITY


def check_code_clean():
    d = dirty(REPO, "soa_tables", "schemas")
    if d:
        raise CycleError("soa-tables has uncommitted changes in soa_tables/ or schemas/ "
                         f"(the TriG pins the code commit): {sorted(d)}")


# ---------------------------------------------------------------- classification

def mask(obj):
    if isinstance(obj, dict):
        return {k: (MASK if k in TS_KEYS else mask(v)) for k, v in obj.items()}
    if isinstance(obj, list):
        return [mask(v) for v in obj]
    return obj


def mask_text(text: str) -> str:
    text = TS_KEY_TEXT.sub(r'\1"' + MASK + '"', text)
    text = TS_KEY_HTML.sub(r"\1" + MASK, text)
    return TS_GENERATED_TEXT.sub(r"\1" + MASK, text)


def split_embedded(text: str):
    """Return (remainder, [(name, obj)]): every `const X = {...}` / `[...]` that parses as JSON is
    taken out of the text and replaced by <<X>>; JavaScript that is not JSON stays in the text."""
    decoder = json.JSONDecoder()
    blobs, parts, pos = [], [], 0
    for m in EMBEDDED.finditer(text):
        if m.start() < pos:
            continue
        try:
            obj, end = decoder.raw_decode(text, m.end())
        except json.JSONDecodeError:
            continue
        parts.append(text[pos:m.end()])
        parts.append(f"<<{m.group(1)}>>")
        blobs.append((m.group(1), obj))
        pos = end
    parts.append(text[pos:])
    return "".join(parts), blobs


def short(value) -> str:
    s = json.dumps(value, ensure_ascii=False) if not isinstance(value, str) else repr(value)
    return s if len(s) <= 80 else s[:77] + "..."


def json_diff(old, new, path="$"):
    """Yield one line per difference. Lists of equal length are compared item by item; lists of
    different length are reported as items removed / added (as a multiset)."""
    if type(old) is not type(new):
        yield f"{path}: {short(old)} → {short(new)}"
    elif isinstance(old, dict):
        for k in old.keys() | new.keys():
            if k not in new:
                yield f"{path}.{k}: removed ({short(old[k])})"
            elif k not in old:
                yield f"{path}.{k}: added ({short(new[k])})"
            elif old[k] != new[k]:
                yield from json_diff(old[k], new[k], f"{path}.{k}")
    elif isinstance(old, list):
        if len(old) == len(new):
            for i, (a, b) in enumerate(zip(old, new)):
                if a != b:
                    yield from json_diff(a, b, f"{path}[{i}]")
        else:
            a = Counter(json.dumps(x, sort_keys=True) for x in old)
            b = Counter(json.dumps(x, sort_keys=True) for x in new)
            removed, added = a - b, b - a
            yield (f"{path}: {len(old)} → {len(new)} items "
                   f"(−{sum(removed.values())}, +{sum(added.values())})")
            for s in list(removed.elements())[:3]:
                yield f"{path}: − {short(json.loads(s))}"
            for s in list(added.elements())[:3]:
                yield f"{path}: + {short(json.loads(s))}"
    elif old != new:
        yield f"{path}: {short(old)} → {short(new)}"


def excerpt(old: str, new: str, context=40):
    """The differing middle of two long lines, with some context on each side."""
    p = 0
    while p < min(len(old), len(new)) and old[p] == new[p]:
        p += 1
    s = 0
    while s < min(len(old), len(new)) - p and old[-1 - s] == new[-1 - s]:
        s += 1
    lead = "…" if p > context else ""
    a, b = old[max(0, p - context):len(old) - s], new[max(0, p - context):len(new) - s]
    tail = old[len(old) - s:][:context]
    cut = lambda x: x if len(x) <= 120 else x[:117] + "..."
    return f"- {lead}{cut(a)}{tail}…", f"+ {lead}{cut(b)}{tail}…"


def text_diff(old: str, new: str):
    a, b = old.splitlines(), new.splitlines()
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if op == "equal":
            continue
        if op == "replace" and i2 - i1 == j2 - j1:
            for x, y in zip(a[i1:i2], b[j1:j2]):
                if len(x) > 160 or len(y) > 160:
                    yield from excerpt(x.strip(), y.strip())
                else:
                    yield f"-{x}"
                    yield f"+{y}"
            continue
        for x in a[i1:i2]:
            yield "-" + (x if len(x) <= 160 else x[:157] + "...")
        for y in b[j1:j2]:
            yield "+" + (y if len(y) <= 160 else y[:157] + "...")


def classify(path: str, old, new):
    """Return ('timestamp-only' | 'real', [detail lines]). old/new are text or None (absent)."""
    if old is None:
        return "real", ["new file"]
    if new is None:
        return "real", ["deleted"]
    if path.endswith(".json"):
        o, n = mask(json.loads(old)), mask(json.loads(new))
        return ("timestamp-only", []) if o == n else ("real", list(json_diff(o, n)))
    if path.endswith((".html", ".js")):
        o_rest, o_blobs = split_embedded(old)
        n_rest, n_blobs = split_embedded(new)
        details = []
        if [b[0] for b in o_blobs] != [b[0] for b in n_blobs]:
            details.append(f"embedded JSON: {[b[0] for b in o_blobs]} → {[b[0] for b in n_blobs]}")
        else:
            for (name, o), (_, n) in zip(o_blobs, n_blobs):
                details.extend(json_diff(mask(o), mask(n), name))
        details.extend(text_diff(mask_text(o_rest), mask_text(n_rest)))
        return ("timestamp-only", []) if not details else ("real", details)
    details = list(text_diff(mask_text(old), mask_text(new)))
    return ("timestamp-only", []) if not details else ("real", details)


# ---------------------------------------------------------------- TriG

def trig_diff(old: str, new: str):
    """Quad diff: non-blank quads added/removed per predicate, single-value changes shown as
    old → new, and blank-node triples compared per graph by isomorphism."""
    from rdflib import BNode, Dataset, Graph
    from rdflib.compare import isomorphic

    def load(text):
        ds = Dataset()
        ds.parse(data=text, format="trig")
        ground, blank = set(), {}
        for s, p, o, g in ds.quads((None, None, None, None)):
            g = getattr(g, "identifier", g)
            if isinstance(s, BNode) or isinstance(o, BNode):
                blank.setdefault(g, Graph()).add((s, p, o))
            else:
                ground.add((s, p, o, g))
        return ds.namespace_manager, ground, blank

    nm, o_ground, o_blank = load(old)
    _, n_ground, n_blank = load(new)
    removed, added = o_ground - n_ground, n_ground - o_ground
    lines = [f"non-blank quads: {len(o_ground)} → {len(n_ground)} (−{len(removed)}, +{len(added)})"]

    def qn(term):
        try:
            return term.n3(nm)
        except Exception:
            return str(term)

    by_sp_old, by_sp_new = {}, {}
    for s, p, o, g in removed:
        by_sp_old.setdefault((s, p, g), []).append(o)
    for s, p, o, g in added:
        by_sp_new.setdefault((s, p, g), []).append(o)
    changed = [k for k in by_sp_old if len(by_sp_old[k]) == 1 and len(by_sp_new.get(k, [])) == 1]
    for k in sorted(changed, key=str)[:10]:
        lines.append(f"  {qn(k[0])} {qn(k[1])}: {qn(by_sp_old[k][0])} → {qn(by_sp_new[k][0])}")
    changed = set(changed)
    rest_removed = Counter(qn(p) for s, p, o, g in removed if (s, p, g) not in changed)
    rest_added = Counter(qn(p) for s, p, o, g in added if (s, p, g) not in changed)
    for p in sorted(rest_removed.keys() | rest_added.keys()):
        lines.append(f"  {p}: −{rest_removed[p]}, +{rest_added[p]}")
    if not (o_blank or n_blank):
        lines.append("blank-node triples: none")
    for g in sorted(o_blank.keys() | n_blank.keys(), key=str):
        a, b = o_blank.get(g, Graph()), n_blank.get(g, Graph())
        same = isomorphic(a, b)
        lines.append(f"blank-node triples in {qn(g)}: {len(a)} → {len(b)}, "
                     f"{'isomorphic (unchanged)' if same else 'CHANGED'}")
    return lines


# ---------------------------------------------------------------- state

def state_path(top: Path) -> Path:
    return top / ".git" / "review_cycle.json"


def load_state(top: Path) -> dict:
    p = state_path(top)
    if not p.exists():
        raise CycleError("no review cycle in progress (run `rebuild` first)")
    return json.loads(p.read_text())


def save_state(top: Path, state: dict):
    state_path(top).write_text(json.dumps(state, indent=2) + "\n")


def trig_path(protocol_id: str, collection: str) -> Path:
    return config.get_soa_tables_folder(protocol_id, collection) / "rdf" / f"{protocol_id}_facts.trig"


# ---------------------------------------------------------------- steps

def cmd_rebuild(args):
    from soa_tables.analytics import Analytics
    from soa_tables.collections_index import CollectionsIndexStep
    from soa_tables.consolidate import ConsolidateStep
    from soa_tables.corrections import ApplyCorrectionsStep
    from soa_tables.errors import Errors
    from soa_tables.index_generator import IndexGeneratorStep
    from soa_tables.resolve import ResolveStep
    from soa_tables.review_page import ReviewPageStep
    from soa_tables.visualize import VisualizeStep

    collection = args.collection
    if collection not in config.COLLECTIONS or collection == "fixtures":
        raise CycleError(f"unknown collection {collection!r}")
    extractable = config.list_extractable_protocols(collection)
    protocols = args.protocols or extractable
    unknown = [p for p in protocols if p not in extractable]
    if unknown:
        raise CycleError(f"not extractable protocols in {collection}: {unknown}")

    check_code_clean()
    top = collections_top()
    coll_rel = str(config.get_collection_path(collection).resolve().relative_to(top))
    before = dirty(top)
    outside = [p for p in before if not p.startswith(coll_rel + "/")]
    if outside:
        raise CycleError(f"dirty files outside {coll_rel}: {sorted(outside)}")
    leftover = [p for p in before if p.endswith(GENERATED_SUFFIXES)]
    if leftover:
        raise CycleError(f"generated files are already dirty (an earlier run was neither committed "
                         f"nor restored): {sorted(leftover)}")

    steps = [ApplyCorrectionsStep, ResolveStep, ConsolidateStep, ReviewPageStep, VisualizeStep]
    for protocol_id in protocols:
        errors = Errors()
        data = {"source": {"protocol_id": protocol_id, "collection": collection}}
        for step_class in steps:
            data[step_class.step_name] = step_class(errors, Analytics()).execute(data)
        if errors.has_errors():
            msgs = "\n".join(f"  [{e.step}] {e.message}" for e in errors.all)
            raise CycleError(f"{protocol_id}: {errors.count()} error(s) — the tree has regenerated "
                             f"files, nothing restored:\n{msgs}")
        print(f"rebuilt {protocol_id}")
    for result in (IndexGeneratorStep(Errors(), Analytics()).execute({"source": {"collection": collection}}),
                   CollectionsIndexStep(Errors(), Analytics()).execute({})):
        if result.get("status") != "success":
            raise CycleError(f"index generation failed: {result.get('error', 'unknown')}")

    after = dirty(top)
    changed = sorted(p for p in after if p not in before)
    timestamp_only, real = [], {}
    for path in changed:
        new_file = top / path
        kind, details = classify(path, head_text(top, path),
                                 new_file.read_text(encoding="utf-8") if new_file.exists() else None)
        if kind == "timestamp-only":
            timestamp_only.append(path)
        else:
            real[path] = details
    if timestamp_only:
        git(top, "restore", "--", *timestamp_only)
        still = [p for p in timestamp_only if p in dirty(top)]
        if still:
            raise CycleError(f"git restore left files dirty: {still}")

    save_state(top, {"collection": collection, "protocols": protocols, "edits": sorted(before),
                     "real": sorted(real), "restored": timestamp_only,
                     "data_commit": None, "trig": [], "pytest": None, "done": False})

    print(f"\n{collection}: {', '.join(protocols)}")
    print(f"\nYour edits (dirty before the run, committed as they are): {len(before)}")
    for p in sorted(before):
        print(f"  {before[p]} {p}")
    print(f"\nTimestamp-only (masked compare empty, restored): {len(timestamp_only)}")
    for p in timestamp_only:
        print(f"  {p}")
    print(f"\nReal changes (kept): {len(real)}")
    for p, details in real.items():
        print(f"  {p}{'   [outside the collection]' if not p.startswith(coll_rel + '/') else ''}")
        for d in details[:DETAIL_CAP]:
            print(f"      {d}")
        if len(details) > DETAIL_CAP:
            print(f"      … {len(details) - DETAIL_CAP} more")
    print("\nNext: review the real changes, then  review_cycle.py commit-data -m MESSAGE")


def cmd_commit_data(args):
    top = collections_top()
    state = load_state(top)
    if state["data_commit"] or state["done"]:
        raise CycleError("the data of this cycle is already committed")
    expected = set(state["edits"]) | set(state["real"])
    if not expected:
        raise CycleError("nothing to commit: no edits and no real changes")
    now = set(dirty(top))
    if now != expected:
        raise CycleError(f"dirty files differ from the rebuild report — "
                         f"extra: {sorted(now - expected)}, missing: {sorted(expected - now)}")
    git(top, "add", "--", *sorted(expected))
    git(top, *identity(top), "commit", "-q", "-m", args.message)
    state["data_commit"] = git(top, "rev-parse", "HEAD").strip()
    save_state(top, state)
    print(git(top, "log", "--stat", "--format=%h %s", "-1"))
    print("Next: review_cycle.py trig")


def run_pytest(top: Path, state: dict):
    r = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"],
                       cwd=REPO, capture_output=True, text=True)
    lines = r.stdout.strip().splitlines()
    summary = lines[-1] if lines else r.stderr.strip()[-300:]
    if r.returncode != 0:
        print("\n".join(lines[-40:]))
    state["pytest"] = {"passed": r.returncode == 0, "summary": summary,
                       "code_commit": git(REPO, "rev-parse", "HEAD").strip(),
                       "collections_head": git(top, "rev-parse", "HEAD").strip(),
                       "trig_dirty": sorted(dirty(top))}
    save_state(top, state)
    print(f"pytest: {summary}")
    if r.returncode != 0:
        raise CycleError("pytest failed")


def cmd_trig(args):
    top = collections_top()
    state = load_state(top)
    if not state["data_commit"] or state["done"]:
        raise CycleError("commit the data first (commit-data)")
    if git(top, "rev-parse", "HEAD").strip() != state["data_commit"]:
        raise CycleError("collections HEAD is not the data commit of this cycle")
    check_code_clean()
    if dirty(top):
        raise CycleError(f"collections tree is not clean: {sorted(dirty(top))}")
    written = []
    for protocol_id in state["protocols"]:
        out = trig_path(protocol_id, state["collection"])
        rel = str(out.resolve().relative_to(top))
        subprocess.run([sys.executable, "-m", "soa_tables.rdf", state["collection"], protocol_id,
                        "-o", str(out)], cwd=REPO, check=True)
        old = head_text(top, rel)
        print(f"\n{rel}")
        if old is None:
            print("  new file")
        else:
            for line in trig_diff(old, out.read_text(encoding="utf-8")):
                print(f"  {line}")
        written.append(rel)
    state["trig"] = written
    state["pytest"] = None
    save_state(top, state)
    if not args.no_test:
        print()
        run_pytest(top, state)
        print("\nNext: review_cycle.py commit-trig -m MESSAGE")
    else:
        print("\nNext: review_cycle.py test")


def cmd_test(args):
    top = collections_top()
    state = load_state(top)
    if not state["trig"]:
        raise CycleError("run trig first")
    run_pytest(top, state)
    print("\nNext: review_cycle.py commit-trig -m MESSAGE")


def cmd_commit_trig(args):
    top = collections_top()
    state = load_state(top)
    if not state["trig"] or state["done"]:
        raise CycleError("no TriG to commit in this cycle (run trig)")
    pt = state["pytest"]
    now = sorted(dirty(top))
    if not (pt and pt["passed"]):
        raise CycleError("pytest has not passed in this cycle")
    if (pt["code_commit"] != git(REPO, "rev-parse", "HEAD").strip()
            or pt["collections_head"] != git(top, "rev-parse", "HEAD").strip()
            or pt["trig_dirty"] != now):
        raise CycleError("commits or dirty files changed since pytest ran — run test again")
    trig_dirty = [p for p in state["trig"] if p in now]
    if set(now) - set(state["trig"]):
        raise CycleError(f"dirty files other than the TriG: {sorted(set(now) - set(state['trig']))}")
    if not trig_dirty:
        raise CycleError("the TriG files are unchanged")
    git(top, "add", "--", *trig_dirty)
    git(top, *identity(top), "commit", "-q", "-m", args.message)
    state["done"] = True
    save_state(top, state)
    print(git(top, "log", "--stat", "--format=%h %s", "-1"))
    print("Cycle done. Push from your terminal.")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("rebuild")
    p.add_argument("collection")
    p.add_argument("protocols", nargs="*")
    p.set_defaults(func=cmd_rebuild)
    p = sub.add_parser("commit-data")
    p.add_argument("-m", "--message", required=True)
    p.set_defaults(func=cmd_commit_data)
    p = sub.add_parser("trig")
    p.add_argument("--no-test", action="store_true")
    p.set_defaults(func=cmd_trig)
    p = sub.add_parser("test")
    p.set_defaults(func=cmd_test)
    p = sub.add_parser("commit-trig")
    p.add_argument("-m", "--message", required=True)
    p.set_defaults(func=cmd_commit_trig)
    args = ap.parse_args(argv)
    try:
        args.func(args)
    except CycleError as e:
        print(f"review_cycle: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
