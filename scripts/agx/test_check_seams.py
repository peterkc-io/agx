#!/usr/bin/env python3
"""Standard-library tests for exact seam set comparison."""

from pathlib import Path
import subprocess
import tempfile
import unittest

import check_seams


class SeamChecks(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.repo = Path(self.temp.name)
        self.git("init", "--quiet")
        (self.repo / "one.rs").write_text("upstream one\n")
        (self.repo / "two.rs").write_text("upstream two\n")
        self.git("add", "one.rs", "two.rs")
        # A Git tree has the same diff interface without fixture identities.
        self.base = self.git("write-tree").strip()
        self.ledger = self.repo / "SEAMS.md"
        self.write_rows([])

    def git(self, *args):
        return subprocess.check_output(
            ["git", "-C", str(self.repo), *args], text=True,
        )

    def write_rows(self, names):
        self.ledger.write_text(
            "| Upstream file | Reason | Verification |\n"
            "| --- | --- | --- |\n" + "".join(
                f"| `{name}` | required fork change | focused check |\n"
                for name in names
            )
        )

    def test_exact_changed_set_passes(self):
        (self.repo / "one.rs").write_text("fork one\n")
        self.write_rows(["one.rs"])
        self.assertEqual(check_seams.check(
            self.repo, self.base, self.ledger,
        ), ([], [], 1))

    def test_missing_row_names_changed_file(self):
        (self.repo / "two.rs").write_text("fork two\n")
        self.assertEqual(check_seams.check(
            self.repo, self.base, self.ledger,
        ), (["two.rs"], [], 1))

    def test_unchanged_row_is_stale(self):
        self.write_rows(["one.rs"])
        self.assertEqual(check_seams.check(
            self.repo, self.base, self.ledger,
        ), ([], ["one.rs"], 0))

    def test_deletion_requires_a_row(self):
        (self.repo / "one.rs").unlink()
        self.assertEqual(check_seams.check(
            self.repo, self.base, self.ledger,
        ), (["one.rs"], [], 1))

    def test_added_file_outside_fork_paths_requires_a_row(self):
        (self.repo / "fork.rs").write_text("fork addition\n")
        self.git("add", "fork.rs")
        self.assertEqual(check_seams.check(
            self.repo, self.base, self.ledger,
        ), (["fork.rs"], [], 1))

    def test_added_files_under_fork_owned_paths_need_no_row(self):
        for name in [
            "crates/agx-identity/src/lib.rs", "docs/fork/FEATURES.md",
            "scripts/agx/sync.py", ".github/workflows/agx-ci.yml",
            ".github/AGX_VOUCHED.td",
        ]:
            path = self.repo / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("fork-owned\n")
            self.git("add", name)
        self.assertEqual(check_seams.check(
            self.repo, self.base, self.ledger,
        ), ([], [], 0))

    def test_empty_agx_stems_are_fork_owned(self):
        for name in ("crates/agx-/src/lib.rs", ".github/workflows/agx-.yml"):
            path = self.repo / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("fork-owned\n")
            self.git("add", name)
        self.assertEqual(check_seams.check(
            self.repo, self.base, self.ledger,
        ), ([], [], 0))

    def test_similar_names_outside_fork_paths_require_rows(self):
        names = ["crates/agx.rs", ".github/workflows/ci.yml", "docs/forked.md"]
        for name in names:
            path = self.repo / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("fork addition\n")
            self.git("add", name)
        self.assertEqual(check_seams.check(
            self.repo, self.base, self.ledger,
        ), (sorted(names), [], 3))

    def test_exact_kernel_test_path_is_fork_owned(self):
        path = self.repo / "prime-agent-runtime/test/test_agx_settings.py"
        path.parent.mkdir(parents=True)
        path.write_text("baseline bytes\n")
        self.git("add", str(path.relative_to(self.repo)))
        base = self.git("write-tree").strip()
        path.write_text("fork bytes\n")
        self.assertEqual(check_seams.check(
            self.repo, base, self.ledger,
        ), ([], [], 0))

    def test_other_runtime_tests_still_need_a_row(self):
        path = self.repo / "prime-agent-runtime/test/test_factory.py"
        path.parent.mkdir(parents=True)
        path.write_text("baseline bytes\n")
        self.git("add", str(path.relative_to(self.repo)))
        base = self.git("write-tree").strip()
        path.write_text("changed bytes\n")
        self.assertEqual(check_seams.check(
            self.repo, base, self.ledger,
        ), (["prime-agent-runtime/test/test_factory.py"], [], 1))

    def test_duplicate_row_is_rejected(self):
        self.write_rows(["one.rs", "one.rs"])
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            check_seams.ledger_rows(self.ledger)


if __name__ == "__main__":
    unittest.main()
