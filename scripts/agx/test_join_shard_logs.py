#!/usr/bin/env python3
"""Tests for the joined shard log artifact."""

import json
import os
from pathlib import Path
import tempfile
import unittest

import join_shard_logs


class JoinShardLogs(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.manifests = self.root / "manifests"
        self.logs = self.root / "logs"
        self.manifests.mkdir()
        self.logs.mkdir()
        self.output = self.root / "cargo-test.log"

    def manifest(self, shard, attempt=1, filename=None, **overrides):
        manifest = {
            "shard": shard, "total": 8, "run_attempt": attempt,
            "run_id": os.environ.get("GITHUB_RUN_ID", "run"),
            "commit_sha": os.environ.get("GITHUB_SHA", "sha"),
        }
        manifest.update(overrides)
        name = filename or f"shard-manifest-{shard}-attempt-{attempt}.json"
        (self.manifests / name).write_text(json.dumps(manifest))

    def log(self, shard, attempt=1):
        (self.logs / f"shard-{shard}-attempt-{attempt}.log").write_text(
            f"output {shard}/{attempt}\n"
        )

    def join(self):
        self.assertEqual(join_shard_logs.main([
            "--manifests", str(self.manifests), "--logs", str(self.logs),
            "--total", "8", "--output", str(self.output),
        ]), 0)
        return self.output.read_text()

    def test_all_present_in_shard_order(self):
        for shard in range(8, 0, -1):
            self.manifest(shard)
            self.log(shard)
        self.assertEqual(self.join(), "".join(
            f"=== shard {shard} attempt 1 ===\noutput {shard}/1\n"
            for shard in range(1, 9)
        ))

    def test_mixed_attempts_use_only_each_picked_log(self):
        for shard in range(1, 9):
            self.manifest(shard)
            self.log(shard)
        self.manifest(8, 2)
        self.log(8, 2)
        self.assertEqual(self.join(), "".join(
            f"=== shard {shard} attempt 1 ===\noutput {shard}/1\n"
            for shard in range(1, 8)
        ) + "=== shard 8 attempt 2 ===\noutput 8/2\n")

    def test_missing_picked_log_does_not_use_older_log(self):
        for shard in range(1, 9):
            self.manifest(shard)
            self.log(shard)
        self.manifest(8, 2)
        self.assertEqual(self.join(), "".join(
            f"=== shard {shard} attempt 1 ===\noutput {shard}/1\n"
            for shard in range(1, 8)
        ) + "=== shard 8 attempt 2 ===\nMISSING shard 8 attempt 2\n")

    def test_no_manifest_is_marked_missing_even_with_a_log(self):
        self.log(1)
        self.assertEqual(self.join(), "".join(
            f"MISSING shard {shard} attempt unknown (no manifest)\n"
            for shard in range(1, 9)
        ))

    def test_numeric_attempts_legacy_name_and_invalid_manifests(self):
        self.manifest(1, filename="shard-manifest-1.json")
        self.log(1)
        self.manifest(2, 2)
        self.log(2, 2)
        self.manifest(2, 10)
        self.log(2, 10)
        self.manifest(2, 11, total=7)
        self.manifest(True, 12, filename="shard-manifest-2-attempt-12.json")
        self.manifest(2, 13, run_attempt="13")
        self.manifest(9)
        self.manifest(3, 0)
        (self.manifests / "shard-manifest-2-attempt-14.json").write_text("[")
        (self.manifests / "shard-manifest-2-attempt-15.json").write_text("[]")
        (self.manifests / "shard-manifest-2-attempt-16.json").write_text("{}")
        text = self.join()
        self.assertEqual(text, (
            "=== shard 1 attempt 1 ===\noutput 1/1\n"
            "=== shard 2 attempt 10 ===\noutput 2/10\n"
        ) + "".join(
            f"MISSING shard {shard} attempt unknown (no manifest)\n"
            for shard in range(3, 9)
        ))

    def test_wrong_identity_is_not_picked(self):
        manifests = {
            "shard-manifest-1-attempt-1.json": json.dumps({
                "shard": 1, "total": 1, "run_id": "run", "commit_sha": "sha",
            }),
            "shard-manifest-1-attempt-2.json": json.dumps({
                "shard": 1, "total": 1, "run_attempt": 2,
                "run_id": "other", "commit_sha": "sha",
            }),
            "shard-manifest-1-attempt-3.json": json.dumps({
                "shard": 1, "total": 1, "run_attempt": 3,
                "run_id": "run", "commit_sha": "other",
            }),
        }
        self.assertEqual(join_shard_logs.latest_attempts(
            manifests, 1, "run", "sha",
        ), {1: 1})


if __name__ == "__main__":
    unittest.main()
