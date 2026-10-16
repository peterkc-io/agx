#!/usr/bin/env python3
"""Check the upstream seam ledger against a Git base and working tree."""

import argparse
import os
from pathlib import Path
import re
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[2]
FORK_OWNED_FILES = {
    ".github/AGX_VOUCHED.td",
    ".github/README.md",
    "prime-agent-runtime/test/test_agx_settings.py",
}
FORK_OWNED_DIRS = ("docs/fork/", "docs/plugins/", "plugins/", "scripts/agx/")
FORK_OWNED_PATTERN = re.compile(r"crates/agx-[^/]*/.+|\.github/workflows/agx-[^/]*\.yml")


def fork_owned(name):
    return (
        name in FORK_OWNED_FILES
        or name.startswith(FORK_OWNED_DIRS)
        or FORK_OWNED_PATTERN.fullmatch(name) is not None
    )


def git_names(repo, *args):
    result = subprocess.run(
        ["git", "-C", str(repo), *args], check=True, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return {os.fsdecode(name) for name in result.stdout.split(b"\0") if name}


def ledger_rows(path):
    rows = set()
    for number, line in enumerate(path.read_text().splitlines(), 1):
        if not line.startswith("|"):
            continue
        cells = [cell.strip() for cell in line.split("|")[1:-1]]
        if cells == ["Upstream file", "Reason", "Verification"]:
            continue
        if cells and all(re.fullmatch(r":?-+:?", cell) for cell in cells):
            continue
        if len(cells) != 3 or not all(cells):
            raise ValueError(f"Invalid seam table row at line {number}")
        name = cells[0].removeprefix("`").removesuffix("`")
        if name in rows:
            raise ValueError(f"Duplicate seam row: {name}")
        rows.add(name)
    return rows


def check(repo, base, ledger, revision=None):
    args = ["diff", "--no-renames", "--name-only", "-z", base]
    if revision:
        args.append(revision)
    changed = {name for name in git_names(repo, *args, "--") if not fork_owned(name)}
    rows = ledger_rows(ledger)
    return sorted(changed - rows), sorted(rows - changed), len(changed)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=ROOT)
    bases = parser.add_mutually_exclusive_group()
    bases.add_argument("--base", default="upstream/main")
    bases.add_argument("--upstream", help="use the revision's upstream merge base")
    parser.add_argument("--revision", help="compare a commit instead of working tree")
    parser.add_argument("--ledger", type=Path)
    args = parser.parse_args(argv)
    ledger = args.ledger or args.repo / "docs/fork/SEAMS.md"
    try:
        base = args.base
        if args.upstream is not None:
            base = subprocess.check_output(
                ["git", "-C", str(args.repo), "merge-base",
                 args.revision or "HEAD", args.upstream],
                stderr=subprocess.PIPE, text=True,
            ).strip()
        missing, stale, count = check(
            args.repo, base, ledger, args.revision,
        )
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        print(f"Seam check failed: {error}", file=sys.stderr)
        return 1
    for name in missing:
        print(f"Missing seam row: {name}", file=sys.stderr)
    for name in stale:
        print(f"Stale seam row: {name}", file=sys.stderr)
    if missing or stale:
        return 1
    print(f"Seam ledger matches all {count} changed files outside fork-owned paths.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
