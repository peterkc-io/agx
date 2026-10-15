#!/usr/bin/env python3
"""Standard-library tests for failed-test discovery in Cargo logs."""

import unittest

import rerun_failed


class FailedTests(unittest.TestCase):
    def test_csi_prefixes_do_not_hide_failed_tests(self):
        for prefix in ("\x1b[>4;0m", "\x1b[?25l", "\x1b[31m", "\x1b[1 q"):
            with self.subTest(prefix=repr(prefix)):
                log = (
                    "Running unittests src/lib.rs "
                    "(target/debug/deps/test-abc)\n"
                    f"{prefix}test tests::broken ... FAILED\x1b[0m\n"
                    f"{prefix}test tests::passing ... ok\n"
                    f"{prefix}test tests::ignored ... ignored\n"
                )
                self.assertEqual(rerun_failed.failed_tests(log), [(
                    "target/debug/deps/test-abc", "tests::broken",
                    "src/lib.rs",
                )])

    def test_lines_without_a_failure_stay_unmatched(self):
        log = (
            "\x1b[>4;0mtest tests::passing ... ok\n"
            "\x1b[?25ltest tests::ignored ... ignored\n"
            "\x1b[31mnot a test failure\n"
        )
        self.assertEqual(rerun_failed.failed_tests(log), [])


if __name__ == "__main__":
    unittest.main()
