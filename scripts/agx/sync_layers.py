#!/usr/bin/env python3
"""Print upstream sync layer cuts without changing Git refs."""

import argparse
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[2]
LAYER_LIMIT = 140


def git(repo, *args):
    result = subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True,
    )
    if result.returncode:
        raise RuntimeError(
            f"git {' '.join(args)} failed: "
            f"{result.stderr.decode(errors='replace').strip()}"
        )
    return result.stdout


def layer_cuts(repo, base, head):
    base = git(
        repo, "rev-parse", "--verify", "--end-of-options",
        f"{base}^{{commit}}",
    ).decode().strip()
    head = git(
        repo, "rev-parse", "--verify", "--end-of-options",
        f"{head}^{{commit}}",
    ).decode().strip()
    cut = git(repo, "merge-base", base, head).decode().strip()
    commits = git(
        repo, "rev-list", "--first-parent", "--reverse", f"{cut}..{head}",
    ).decode().splitlines()
    layers = []
    start = 0
    while start < len(commits):
        chosen = None
        for index in range(start, len(commits)):
            paths = git(
                repo, "diff", "--name-only", "--no-renames", "-z",
                cut, commits[index], "--",
            ).split(b"\0")
            count = sum(
                1 for path in paths if path and not path.endswith(b".lock")
            )
            if index == start:
                next_count = count
            # A later revert can fit even after an earlier overflow.
            if count <= LAYER_LIMIT:
                chosen = (index, count)
        if chosen is None:
            chosen = (start, next_count)
        index, count = chosen
        cut = commits[index]
        layers.append((cut, count))
        start = index + 1
    return layers


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=ROOT)
    parser.add_argument("--base", default="origin/main")
    parser.add_argument("--head", default="origin/upstream")
    args = parser.parse_args(argv)
    try:
        layers = layer_cuts(args.repo, args.base, args.head)
    except (OSError, RuntimeError) as error:
        print(f"Sync layer check failed: {error}", file=sys.stderr)
        return 1
    print(
        "Upstream-only estimates of reviewable files; "
        "conflict resolutions and fork fixes are not included."
    )
    if not layers:
        print("No layer needed: the upstream head is already in the base.")
    for number, (cut, count) in enumerate(layers, 1):
        marker = " (over limit)" if count > LAYER_LIMIT else ""
        print(f"Layer {number}: {cut} estimate {count} files{marker}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
