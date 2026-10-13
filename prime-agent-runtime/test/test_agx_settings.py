"""Kernel-side settings overlay contract, with an isolated agent directory."""

import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from rlm import factory


class AgxSettings(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.agent = Path(temporary.name)
        self.base = self.agent / "settings.json"
        self.overlay = self.agent / "settings-agx.json"
        environment = patch.dict(
            os.environ,
            {"PRIME_AGENT_CODING_AGENT_DIR": str(self.agent)},
        )
        environment.start()
        self.addCleanup(environment.stop)

    def check_gate(self, expected):
        before = self.base.read_bytes() if self.base.exists() else None
        self.assertIs(factory.factory_enabled(), expected)
        after = self.base.read_bytes() if self.base.exists() else None
        self.assertEqual(after, before)

    def test_factory_case_table_matches_the_rust_gate(self):
        table = (
            Path(__file__).resolve().parents[2]
            / "crates/agx-settings/tests/factory_cases.json"
        )
        cases = json.loads(table.read_text())
        for case in cases:
            with self.subTest(case=case["name"]):
                paths = (("base", self.base), ("overlay", self.overlay))
                for key, path in paths:
                    if path.is_dir():
                        path.rmdir()
                    else:
                        path.unlink(missing_ok=True)
                    content = case[key]
                    if isinstance(content, str):
                        path.write_text(content)
                    elif isinstance(content, dict):
                        self.assertEqual(content, {"directory": True})
                        path.mkdir()
                    else:
                        self.assertIsNone(content)
                before = (
                    self.base.read_bytes() if self.base.is_file() else None
                )
                before_directory = self.base.is_dir()
                self.assertIs(factory.factory_enabled(), case["expected"])
                after = self.base.read_bytes() if self.base.is_file() else None
                self.assertEqual(after, before)
                self.assertEqual(self.base.is_dir(), before_directory)

    def test_missing_overlay_reads_only_the_base(self):
        self.base.write_text('{"factory":{"enabled":true}}\n')
        self.check_gate(True)
        self.base.write_text('{"factory":{"enabled":false}}\n')
        self.check_gate(False)

    def test_overlay_turns_the_factory_on(self):
        self.base.write_text('{"factory":{"enabled":false,"extra":1}}\n')
        self.overlay.write_text('{"factory":{"enabled":true}}\n')
        self.check_gate(True)

    def test_missing_base_is_supported(self):
        self.overlay.write_text('{"factory":{"enabled":true}}\n')
        self.check_gate(True)
        self.assertFalse(self.base.exists())

    def test_overlay_null_removes_the_inherited_enabled_key(self):
        self.base.write_text('{"factory":{"enabled":true,"extra":1}}\n')
        self.overlay.write_text('{"factory":{"enabled":null}}\n')
        self.check_gate(False)
        self.overlay.write_text('{"factory":null}\n')
        self.check_gate(False)

    def test_malformed_overlay_keeps_the_base_value(self):
        self.base.write_text('{"factory":{"enabled":true}}\n')
        self.overlay.write_text('{ invalid\n')
        before = self.overlay.read_bytes()
        self.check_gate(True)
        self.assertEqual(self.overlay.read_bytes(), before)

    def test_wrong_typed_and_replacing_overlay_values_stay_disabled(self):
        self.base.write_text('{"factory":{"enabled":true}}\n')
        for overlay in (
            {"factory": "enabled"},
            {"factory": {"enabled": 1}},
            {"factory": {"enabled": "true"}},
            [],
            None,
        ):
            with self.subTest(overlay=overlay):
                self.overlay.write_text(json.dumps(overlay))
                self.check_gate(False)

    def test_unreadable_and_malformed_base_stay_disabled(self):
        self.overlay.write_text('{"factory":{"enabled":true}}\n')
        self.base.mkdir()
        self.assertIs(factory.factory_enabled(), False)
        self.assertTrue(self.base.is_dir())
        self.base.rmdir()
        self.base.write_text('{ invalid\n')
        self.check_gate(False)


if __name__ == "__main__":
    unittest.main()
