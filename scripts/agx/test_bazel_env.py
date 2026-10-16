#!/usr/bin/env python3
"""Exercise P-20 discovery and D-43 runfiles links through the real wrapper."""

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


WRAPPER = Path(__file__).parent / "bazel/test_env.py"
BIN_DIR = Path("/tmp/agx-bazel-bin")


class TestEnvironmentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.home = self.root / "home"
        self.home.mkdir()
        self.runfiles = self.root / "runfiles"
        (self.runfiles / "_main").mkdir(parents=True)
        self.env = dict(os.environ, TEST_TMPDIR=str(self.home),
                        RUNFILES_DIR=str(self.runfiles),
                        TEST_WORKSPACE="_main")
        for key in ("AGX_BAZEL_KERNEL", "AGX_BAZEL_KERNEL_PREFIX",
                    "AGX_BAZEL_AGX", "AGX_BAZEL_DAEMON"):
            self.env.pop(key, None)

    def executable(self, relative, body):
        path = self.runfiles / "_main" / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("#!/bin/sh\nset -eu\n" + body + "\n")
        path.chmod(0o755)
        return path

    def wrapper(self, code):
        return subprocess.run(
            [sys.executable, "-I", "-B", str(WRAPPER),
             sys.executable, "-I", "-B", "-c", code],
            env=self.env, capture_output=True, text=True, timeout=30,
        )

    def test_private_home_and_tmpdir_and_exit_status(self):
        result = self.wrapper(
            "import os; "
            "assert os.environ['HOME'] == os.environ['TEST_TMPDIR']; "
            "assert os.environ['TMPDIR'] == os.environ['TEST_TMPDIR']; "
            "raise SystemExit(7)"
        )
        self.assertEqual(result.returncode, 7, result.stderr)

    def test_kernel_both_discovery_paths(self):
        self.executable("kernel/bin/python3", "exit 0")
        (self.runfiles / "_main/kernel/bin/python").symlink_to("python3")
        self.env.update(AGX_BAZEL_KERNEL="1",
                        AGX_BAZEL_KERNEL_PREFIX="kernel")
        result = self.wrapper(
            "import os; from pathlib import Path; "
            "core = Path(os.environ['PA_CORE_KERNEL_PYTHON']); "
            "e2e = Path(os.environ['PA_E2E_KERNEL_PYTHON']); "
            "home = Path(os.environ['HOME']); "
            "layout = home / '.prime/agent/kernel-venv-agx/bin/python'; "
            "assert core.samefile(e2e) and layout.samefile(core)"
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse((self.home / ".prime/agent/kernel-venv-agx")
                         .is_symlink())

    def test_missing_override_interpreter_fails_wrapper(self):
        self.env.update(AGX_BAZEL_KERNEL="1",
                        AGX_BAZEL_KERNEL_PREFIX="missing")
        result = self.wrapper("raise SystemExit('must not run')")
        self.assertEqual(result.returncode, 1)
        self.assertIn("Missing override interpreter", result.stderr)
        self.assertIn("PA_CORE_KERNEL_PYTHON", result.stderr)
        self.assertIn("PA_E2E_KERNEL_PYTHON", result.stderr)

    def test_missing_home_layout_fails_wrapper(self):
        # A usable override alone cannot hide the missing HOME discovery path.
        self.executable("kernel/bin/python3", "exit 0")
        self.env.update(AGX_BAZEL_KERNEL="1",
                        AGX_BAZEL_KERNEL_PREFIX="kernel")
        result = self.wrapper("raise SystemExit('must not run')")
        self.assertEqual(result.returncode, 1)
        self.assertIn("Missing HOME kernel venv layout", result.stderr)

    def test_binary_pair_and_start_after_cwd_change(self):
        self.assertFalse(BIN_DIR.exists(), "D-43 /tmp is already in use")
        agx = self.executable("cli/agx", 'printf agx')
        daemon = self.executable("daemon/pa-daemon", 'printf daemon')
        self.env.update(AGX_BAZEL_AGX="cli/agx",
                        AGX_BAZEL_DAEMON="daemon/pa-daemon")
        result = self.wrapper(
            "import os, subprocess; from pathlib import Path; "
            "pair = Path('/tmp/agx-bazel-bin'); "
            f"assert (pair / 'agx').resolve() == Path({str(agx)!r}); "
            f"assert (pair / 'pa-daemon').resolve() == Path({str(daemon)!r}); "
            "os.chdir(os.environ['TEST_TMPDIR']); "
            "assert subprocess.check_output([str(pair / 'agx')]) == b'agx'; "
            "assert subprocess.check_output([str(pair / 'pa-daemon')]) "
            "== b'daemon'"
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(BIN_DIR.exists())

    def test_missing_runfiles_binary_fails_and_cleans_links(self):
        self.assertFalse(BIN_DIR.exists(), "D-43 /tmp is already in use")
        self.executable("cli/agx", "exit 0")
        self.env.update(AGX_BAZEL_AGX="cli/agx",
                        AGX_BAZEL_DAEMON="missing")
        result = self.wrapper("raise SystemExit('must not run')")
        self.assertEqual(result.returncode, 1)
        self.assertIn("Missing declared runfiles binary pa-daemon",
                      result.stderr)
        self.assertFalse(BIN_DIR.exists())

    def test_host_binary_path_is_rejected(self):
        self.assertFalse(BIN_DIR.exists(), "D-43 /tmp is already in use")
        self.env["AGX_BAZEL_AGX"] = sys.executable
        result = self.wrapper("raise SystemExit('must not run')")
        self.assertEqual(result.returncode, 1)
        self.assertIn("Expected a declared runfiles-relative path",
                      result.stderr)
        self.assertFalse(BIN_DIR.exists())

    def test_existing_fixed_directory_fails_without_removing_it(self):
        BIN_DIR.mkdir()
        self.addCleanup(BIN_DIR.rmdir)
        self.env["AGX_BAZEL_AGX"] = "not-needed"
        result = self.wrapper("raise SystemExit('must not run')")
        self.assertEqual(result.returncode, 1)
        self.assertIn("already exists", result.stderr)
        self.assertIn("/tmp is not isolated", result.stderr)
        self.assertTrue(BIN_DIR.is_dir())

    def test_child_failure_still_removes_links(self):
        self.assertFalse(BIN_DIR.exists(), "D-43 /tmp is already in use")
        self.executable("cli/agx", "exit 0")
        self.env["AGX_BAZEL_AGX"] = "cli/agx"
        result = self.wrapper("raise SystemExit(9)")
        self.assertEqual(result.returncode, 9, result.stderr)
        self.assertFalse(BIN_DIR.exists())


if __name__ == "__main__":
    unittest.main()
