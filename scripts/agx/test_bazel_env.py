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
                    "AGX_BAZEL_AGX", "AGX_BAZEL_DAEMON",
                    "AGX_BAZEL_PACKAGE", "AGX_BAZEL_SOURCE_ROOT",
                    "AGX_BAZEL_CARGO_LAYOUT"):
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
            "from pathlib import Path; "
            "home = Path(os.environ['HOME']); "
            "assert home.parent == Path('/tmp').resolve(); "
            "assert len(home.name) == 4; "
            "assert os.environ['HOME'] == os.environ['TMPDIR']; "
            "assert len(os.environ['TMPDIR']) < 30; "
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
            "assert Path(os.environ['PRIME_AGENT_KERNEL_PYTHON']) == core; "
            "home = Path(os.environ['HOME']); "
            "layout = home / '.prime/agent/kernel-venv-agx/bin/python'; "
            "assert core.samefile(e2e) and layout.samefile(core); "
            "print(home)"
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(Path(result.stdout.strip()).exists())

    def test_kernel_test_may_remove_home_layout_without_masking_success(self):
        self.executable("kernel/bin/python3", "exit 0")
        (self.runfiles / "_main/kernel/bin/python").symlink_to("python3")
        self.env.update(AGX_BAZEL_KERNEL="1",
                        AGX_BAZEL_KERNEL_PREFIX="kernel")
        result = self.wrapper(
            "import os; from pathlib import Path; "
            "(Path(os.environ['HOME']) / "
            "'.prime/agent/kernel-venv-agx').unlink()"
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_fixed_source_root_survives_a_cwd_change(self):
        self.env["AGX_BAZEL_SOURCE_ROOT"] = "1"
        source = self.runfiles / "_main/crates/demo/fixture"
        source.parent.mkdir(parents=True)
        source.write_text("declared")
        result = self.wrapper(
            "import os; from pathlib import Path; "
            "os.chdir(os.environ['TMPDIR']); "
            "assert Path('/tmp/agx-bazel-src/crates/demo/fixture')"
            ".read_text() == 'declared'"
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(Path("/tmp/agx-bazel-src").is_symlink())

    def test_bundled_python_skill_is_discovered_and_importable(self):
        source = self.runfiles / "_main/skills/demo/src/demo_skill.py"
        source.parent.mkdir(parents=True)
        source.write_text("VALUE = 42\n")
        self.env["AGX_BAZEL_PACKAGE"] = "1"
        # No -I: kernel skill discovery intentionally inherits PYTHONPATH.
        result = subprocess.run(
            [sys.executable, "-I", "-B", str(WRAPPER),
             sys.executable, "-B", "-c",
             "import os, demo_skill; from pathlib import Path; "
             "assert demo_skill.VALUE == 42; "
             "assert os.environ['AGX_PROCESS'] == '1'; "
             "assert (Path(os.environ['PI_PACKAGE_DIR']) / 'skills')"
             ".is_dir()"],
            env=self.env, capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_missing_declared_skills_fails_before_test(self):
        self.env["AGX_BAZEL_PACKAGE"] = "1"
        result = self.wrapper("raise SystemExit('must not run')")
        self.assertEqual(result.returncode, 1)
        self.assertIn("Missing declared bundled Python skills", result.stderr)

    def test_cargo_process_image_layout(self):
        binary = self.executable("test", 'printf "%s" "$0"')
        self.env["AGX_BAZEL_CARGO_LAYOUT"] = "1"
        result = subprocess.run(
            [sys.executable, "-I", "-B", str(WRAPPER), str(binary)],
            env=self.env, capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("/target/debug/test", result.stdout)
        self.assertFalse(Path(result.stdout).exists())

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
