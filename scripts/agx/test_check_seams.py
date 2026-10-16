#!/usr/bin/env python3
"""Standard-library tests for exact seam set comparison."""

from contextlib import redirect_stderr, redirect_stdout
import io
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

    def test_build_bazel_in_upstream_crate_is_fork_owned(self):
        path = self.repo / "crates/pa-core/BUILD.bazel"
        path.parent.mkdir(parents=True)
        path.write_text("# fork-owned\n")
        self.git("add", "crates/pa-core/BUILD.bazel")
        self.assertEqual(check_seams.check(
            self.repo, self.base, self.ledger,
        ), ([], [], 0))

    def test_bazel_root_files_are_fork_owned(self):
        for name in ("MODULE.bazel", "MODULE.bazel.lock", ".bazelrc",
                     ".bazelversion", "agx.just", "BUILD.bazel"):
            with self.subTest(name=name):
                (self.repo / name).write_text("# fork-owned\n")
                self.git("add", name)
                self.assertEqual(check_seams.check(
                    self.repo, self.base, self.ledger,
                ), ([], [], 0))

    def test_duplicate_row_is_rejected(self):
        self.write_rows(["one.rs", "one.rs"])
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            check_seams.ledger_rows(self.ledger)

    def stack_git(self, *args):
        return self.git(
            "-c", "user.name=Seam test",
            "-c", "user.email=test@example.invalid",
            "-c", "commit.gpgsign=false", *args,
        )

    def make_stack(self):
        self.stack_git("commit", "--quiet", "-m", "upstream base")
        base = self.git("rev-parse", "HEAD").strip()
        self.git("branch", "-m", "fork-base")
        self.git("checkout", "--quiet", "-b", "upstream")
        (self.repo / "one.rs").write_text("upstream at first cut\n")
        self.git("add", "one.rs")
        self.stack_git("commit", "--quiet", "-m", "upstream one")
        (self.repo / "cut.rs").write_text("upstream cut\n")
        self.git("add", "cut.rs")
        self.stack_git("commit", "--quiet", "-m", "upstream cut")
        cut = self.git("rev-parse", "HEAD").strip()
        (self.repo / "two.rs").write_text("later upstream change\n")
        self.git("add", "two.rs")
        self.stack_git("commit", "--quiet", "-m", "later upstream")
        self.git("checkout", "--quiet", "-b", "main", base)
        owned = self.repo / "docs/fork/FEATURES.md"
        owned.parent.mkdir(parents=True)
        owned.write_text("fork feature\n")
        self.git("add", "docs/fork/FEATURES.md")
        self.stack_git("commit", "--quiet", "-m", "fork feature")
        self.git("checkout", "--quiet", "-b", "sync/layer-1")
        self.stack_git("merge", "--quiet", "--no-ff", cut, "-m", "layer 1")
        (self.repo / "one.rs").write_text("fork seam\n")
        self.git("add", "one.rs")
        self.stack_git("commit", "--quiet", "-m", "fork seam")
        self.write_rows(["one.rs"])

    def run_upstream_check(self, *args):
        output, errors = io.StringIO(), io.StringIO()
        with redirect_stdout(output), redirect_stderr(errors):
            code = check_seams.main([
                "--repo", str(self.repo), "--ledger", str(self.ledger),
                "--upstream", "upstream", *args,
            ])
        return code, output.getvalue(), errors.getvalue()

    def test_upstream_base_follows_two_layer_stack_and_partial_main(self):
        self.make_stack()
        code, output, errors = self.run_upstream_check()
        self.assertEqual((code, errors), (0, ""))
        self.assertIn("all 1 changed files", output)
        self.git("checkout", "--quiet", "-b", "sync/layer-2")
        self.stack_git(
            "merge", "--quiet", "--no-ff", "upstream", "-m", "layer 2",
        )
        for revision in ((), ("--revision", "sync/layer-1")):
            with self.subTest(revision=revision):
                code, output, errors = self.run_upstream_check(*revision)
                self.assertEqual((code, errors), (0, ""))
                self.assertIn("all 1 changed files", output)
        self.git("checkout", "--quiet", "main")
        self.stack_git(
            "merge", "--quiet", "--no-ff", "sync/layer-1", "-m", "land 1",
        )
        code, output, errors = self.run_upstream_check()
        self.assertEqual((code, errors), (0, ""))
        self.assertIn("all 1 changed files", output)

    def test_upstream_base_rejects_unlisted_layer_edit(self):
        self.make_stack()
        (self.repo / "two.rs").write_text("unlisted fork edit\n")
        code, output, errors = self.run_upstream_check()
        self.assertEqual((code, output), (1, ""))
        self.assertIn("Missing seam row: two.rs", errors)
        self.git("add", "two.rs")
        self.stack_git("commit", "--quiet", "-m", "unlisted edit")
        code, output, errors = self.run_upstream_check("--revision", "HEAD")
        self.assertEqual((code, output), (1, ""))
        self.assertIn("Missing seam row: two.rs", errors)

    def test_upstream_merge_base_failure_is_visible(self):
        self.stack_git("commit", "--quiet", "-m", "fork base")
        output, errors = io.StringIO(), io.StringIO()
        with redirect_stdout(output), redirect_stderr(errors):
            code = check_seams.main([
                "--repo", str(self.repo), "--ledger", str(self.ledger),
                "--upstream", "missing-upstream",
            ])
        self.assertEqual(code, 1)
        error = errors.getvalue()
        self.assertIn("Seam check failed: git merge-base failed:", error)
        self.assertIn("missing-upstream", error)

    def test_explicit_base_and_upstream_are_mutually_exclusive(self):
        with redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as error:
                check_seams.main(["--base", "HEAD", "--upstream", "upstream"])
        self.assertEqual(error.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
