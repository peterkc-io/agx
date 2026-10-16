#!/usr/bin/env python3
"""Join the logs of the attempts selected by the shard manifest audit."""

import argparse
from collections.abc import Mapping
import json
import os
from pathlib import Path
import re


MANIFEST_NAME = re.compile(r"shard-manifest-(\d+)(?:-attempt-(\d+))?\.json")


def latest_attempts(
    manifests: Mapping[str, str], total: int, run_id: str, commit_sha: str,
) -> dict[int, int]:
    """Match ci_test_shard_summary.py's valid, newest-per-shard rule."""
    attempts = {}
    for name, contents in sorted(manifests.items()):
        match = MANIFEST_NAME.fullmatch(name)
        if not match:
            continue
        shard, attempt = int(match[1]), int(match[2] or 1)
        if not 1 <= shard <= total or attempt < 1:
            continue
        try:
            manifest = json.loads(contents)
        except ValueError:
            continue
        if not isinstance(manifest, dict):
            continue
        recorded_attempt = manifest.get("run_attempt", 1)
        if (
            type(manifest.get("shard")) is not int
            or manifest["shard"] != shard
            or type(manifest.get("total")) is not int
            or manifest["total"] != total
            or type(recorded_attempt) is not int
            or recorded_attempt != attempt
            or (run_id and manifest.get("run_id") != run_id)
            or (commit_sha and manifest.get("commit_sha") != commit_sha)
        ):
            continue
        attempts[shard] = max(attempts.get(shard, 0), attempt)
    return attempts


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifests", type=Path, required=True)
    parser.add_argument("--logs", type=Path, required=True)
    parser.add_argument("--total", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.total < 1:
        parser.error("--total must be positive")

    manifests = {}
    for path in args.manifests.glob("shard-manifest-*.json"):
        try:
            manifests[path.name] = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            # The audit rejects unreadable manifests; they cannot be picked.
            continue
    attempts = latest_attempts(
        manifests, args.total, os.environ.get("GITHUB_RUN_ID", ""),
        os.environ.get("GITHUB_SHA", ""),
    )
    with args.output.open("w", encoding="utf-8") as output:
        for shard in range(1, args.total + 1):
            attempt = attempts.get(shard)
            if attempt is None:
                output.write(
                    f"MISSING shard {shard} attempt unknown (no manifest)\n"
                )
                continue
            output.write(f"=== shard {shard} attempt {attempt} ===\n")
            log = args.logs / f"shard-{shard}-attempt-{attempt}.log"
            try:
                contents = log.read_text(encoding="utf-8", errors="replace")
            except OSError:
                output.write(f"MISSING shard {shard} attempt {attempt}\n")
                continue
            output.write(contents)
            if contents and not contents.endswith("\n"):
                output.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
