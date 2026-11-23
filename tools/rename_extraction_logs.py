"""Rename the extractor's reports to the name of prompt 3.9.5 (B20), content untouched.

    python tools/rename_extraction_logs.py <collections-root>      # dry run: list what would change
    python tools/rename_extraction_logs.py <collections-root> --apply

In every <collection>/protocols/<pid>/soa-tables/extracted/ folder:
  '<stem>_uncertainty_report.md' / '.txt'  ->  '<stem>_extraction_log.md' / '.txt'   (git mv)
  '<stem>_uncertainty_report.html'         ->  removed (git rm); the index step renders
                                               '<stem>_extraction_log.html' from the .md
The collections root must be inside a git work tree with no uncommitted changes. A target that
already exists stops the run before anything is changed. Regenerate the HTML afterwards.
"""

import subprocess
import sys
from pathlib import Path

OLD, NEW = "_uncertainty_report", "_extraction_log"


def plan(root: Path) -> tuple[list[tuple[Path, Path]], list[Path]]:
    moves, removals = [], []
    for ext_dir in sorted(root.glob("*/protocols/*/soa-tables/extracted")):
        for f in sorted(ext_dir.glob(f"*{OLD}.*")):
            stem, suffix = f.name.rsplit(OLD, 1)
            if suffix == ".html":
                removals.append(f)
            elif suffix in (".md", ".txt"):
                moves.append((f, ext_dir / f"{stem}{NEW}{suffix}"))
            else:
                raise SystemExit(f"unexpected file: {f}")
    return moves, removals


def main(argv: list[str]) -> None:
    if len(argv) not in (2, 3) or (len(argv) == 3 and argv[2] != "--apply"):
        raise SystemExit(__doc__)
    root = Path(argv[1]).resolve()
    if not root.is_dir():
        raise SystemExit(f"not a directory: {root}")
    git = ["git", "-C", str(root)]
    dirty = subprocess.run(git + ["status", "--porcelain"], capture_output=True, text=True, check=True).stdout
    if dirty.strip():
        raise SystemExit(f"uncommitted changes under {root}:\n{dirty}")

    moves, removals = plan(root)
    clash = [dst for _, dst in moves if dst.exists()]
    if clash:
        raise SystemExit("target exists:\n" + "\n".join(str(p) for p in clash))

    for src, dst in moves:
        print(f"mv  {src.relative_to(root)} -> {dst.name}")
    for f in removals:
        print(f"rm  {f.relative_to(root)}")
    print(f"{len(moves)} renamed, {len(removals)} removed" + ("" if len(argv) == 3 else " (dry run)"))
    if len(argv) == 2:
        return

    for src, dst in moves:
        subprocess.run(git + ["mv", str(src), str(dst)], check=True)
    if removals:
        subprocess.run(git + ["rm", "-q"] + [str(f) for f in removals], check=True)


if __name__ == "__main__":
    main(sys.argv)
