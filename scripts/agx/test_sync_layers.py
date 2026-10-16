#!/usr/bin/env python3
"""Read-only sync layer estimates against temporary Git histories."""

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


SCRIPT = Path(__file__).with_name("sync_layers.py").resolve()
HEADER = (
    "Upstream-only estimates of reviewable files; "
    "conflict resolutions and fork fixes are not included."
)


class SyncLayersTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.repo = Path(self.temp.name)
        self.clock = 1_700_000_000
        self.git("init", "--quiet", "-b", "main")
        self.base = self.commit({"seed.txt": "seed\n"})
        self.git("branch", "base", self.base)

    def git(self, *args, env=None):
        return subprocess.check_output(
            ["git", "-C", str(self.repo), *args], text=True,
            stderr=subprocess.PIPE, env=env,
        ).strip()

    def dated(self):
        # Distinct dates keep Git's commit order fixed across runs.
        self.clock += 60
        date = f"@{self.clock} +0000"
        return dict(os.environ, GIT_AUTHOR_DATE=date, GIT_COMMITTER_DATE=date)

    def commit(self, changes):
        for name, text in changes.items():
            path = self.repo / name
            if text is None:
                path.unlink()
            else:
                path.write_text(text)
        self.git("add", "-A")
        self.git(
            "-c", "user.name=Layer test",
            "-c", "user.email=test@example.invalid",
            "-c", "commit.gpgsign=false", "commit", "--quiet", "-m", "test",
            env=self.dated(),
        )
        return self.git("rev-parse", "HEAD")

    def run_layers(self, base="base", head="HEAD"):
        before = self.git("for-each-ref")
        try:
            return subprocess.run(
                [sys.executable, "-I", "-B", str(SCRIPT),
                 "--repo", str(self.repo), "--base", base, "--head", head],
                capture_output=True, text=True,
            )
        finally:
            self.assertEqual(self.git("for-each-ref"), before)

    def assert_layers(self, expected):
        result = self.run_layers()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, "")
        self.assertEqual(result.stdout.splitlines(), [HEADER, *expected])

    def test_under_limit_is_one_layer(self):
        head = self.commit({f"file-{n}": "new\n" for n in range(3)})
        self.assert_layers([f"Layer 1: {head} estimate 3 files"])

    def test_two_layers_choose_farthest_fitting_commit(self):
        self.commit({f"file-{n}": "new\n" for n in range(100)})
        cut = self.commit({f"file-{n}": "new\n" for n in range(100, 140)})
        head = self.commit({"last.txt": "last\n"})
        self.assert_layers([
            f"Layer 1: {cut} estimate 140 files",
            f"Layer 2: {head} estimate 1 files",
        ])

    def test_revert_after_overflow_uses_later_cut(self):
        self.commit({f"file-{n}": "new\n" for n in range(100)})
        self.commit({f"file-{n}": "new\n" for n in range(100, 150)})
        head = self.commit({f"file-{n}": None for n in range(100, 150)})
        self.assert_layers([f"Layer 1: {head} estimate 100 files"])

    def test_rename_counts_as_two_paths(self):
        (self.repo / "seed.txt").rename(self.repo / "renamed.txt")
        head = self.commit({})
        self.assert_layers([f"Layer 1: {head} estimate 2 files"])

    def test_large_commit_gets_its_own_over_limit_layer(self):
        cut = self.commit({f"file-{n}": "new\n" for n in range(141)})
        head = self.commit({"last.txt": "last\n"})
        self.assert_layers([
            f"Layer 1: {cut} estimate 141 files (over limit)",
            f"Layer 2: {head} estimate 1 files",
        ])

    def test_lock_file_does_not_push_layer_over_limit(self):
        self.commit({f"file-{n}": "new\n" for n in range(140)})
        head = self.commit({"Cargo.lock": "lock\n"})
        self.assert_layers([f"Layer 1: {head} estimate 140 files"])

    def test_cuts_follow_the_first_parent_chain(self):
        first = self.commit({f"main-{n}": "new\n" for n in range(10)})
        self.git("checkout", "--quiet", "-b", "side")
        side = self.commit({f"side-{n}": "new\n" for n in range(100)})
        self.commit({f"side-{n}": "new\n" for n in range(100, 200)})
        self.git("checkout", "--quiet", "main")
        self.git(
            "-c", "user.name=Layer test",
            "-c", "user.email=test@example.invalid",
            "-c", "commit.gpgsign=false",
            "merge", "--quiet", "--no-ff", "-m", "merge side", "side",
            env=self.dated(),
        )
        merge = self.git("rev-parse", "HEAD")
        head = self.commit({"last.txt": "last\n"})
        # A cut at the side commit (110 files) would fit, but it is not on
        # the first-parent chain, so the merge forms its own layer.
        self.assertNotIn(side, self.git("rev-list", "--first-parent", "HEAD"))
        self.assert_layers([
            f"Layer 1: {first} estimate 10 files",
            f"Layer 2: {merge} estimate 200 files (over limit)",
            f"Layer 3: {head} estimate 1 files",
        ])

    def test_head_already_in_base_needs_no_layer(self):
        self.commit({"later.txt": "later\n"})
        result = self.run_layers(base="HEAD", head="base")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), [
            HEADER,
            "No layer needed: the upstream head is already in the base.",
        ])

    def test_unknown_ref_fails_and_names_ref(self):
        for base, head in (("missing-base", "HEAD"), ("base", "missing-head")):
            with self.subTest(base=base, head=head):
                result = self.run_layers(base, head)
                self.assertNotEqual(result.returncode, 0)
                missing = base if base.startswith("missing") else head
                self.assertIn(missing, result.stderr)
                self.assertEqual(result.stdout, "")


if __name__ == "__main__":
    unittest.main()
