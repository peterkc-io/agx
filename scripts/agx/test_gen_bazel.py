#!/usr/bin/env python3
"""Cargo-target mapping and read-only drift checks for Bazel generation."""

import copy
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

import gen_bazel


def target(name, kind, path, *, test=True, doctest=False):
    return {"name": name, "kind": [kind], "src_path": "/repo/" + path,
            "edition": "2021", "test": test, "doctest": doctest}


def fixture():
    library = target("demo", "lib", "crates/demo/src/lib.rs", doctest=True)
    package = {
        "id": "demo-id", "name": "demo", "version": "1.2.3",
        "manifest_path": "/repo/crates/demo/Cargo.toml",
        "dependencies": [{"name": "tempfile", "kind": "dev"}],
        "targets": [
            library,
            target("demo-cli", "bin", "crates/demo/src/main.rs"),
            target("integration", "test", "crates/demo/tests/integration.rs"),
            target("redirected", "test", "crates/demo/tests/fork/updates.rs"),
            target("cross", "test", "crates/demo/../other/tests/cross.rs"),
            target("compile", "example", "crates/demo/examples/compile.rs",
                   test=False),
            target("tested", "example", "crates/demo/examples/tested.rs"),
        ],
    }
    other = {
        "id": "other-id", "name": "other", "version": "1.2.3",
        "manifest_path": "/repo/crates/other/Cargo.toml",
        "dependencies": [],
        # Cargo metadata omits tests for an autotests=false package.
        "targets": [target("other", "lib", "crates/other/src/lib.rs")],
    }
    metadata = {"workspace_root": "/repo",
                "workspace_members": ["demo-id", "other-id"],
                "packages": [package, other]}
    sources = ["crates/demo/src/lib.rs", "crates/demo/src/main.rs",
               "crates/demo/tests/integration.rs",
               "crates/demo/tests/fork/updates.rs",
               "crates/demo/tests/installer_update_e2e.rs",
               "crates/demo/examples/compile.rs",
               "crates/demo/examples/tested.rs",
               "crates/other/src/lib.rs", "crates/other/tests/cross.rs"]
    return metadata, sources


class GeneratorTests(unittest.TestCase):
    def setUp(self):
        self.metadata, self.sources = fixture()

    def test_cargo_mapping_including_doctest_and_two_examples(self):
        generated = gen_bazel.generate(self.metadata, {}, self.sources)
        text = generated["crates/demo/BUILD.bazel"]
        self.assertEqual(text.count("rust_library("), 1)
        self.assertEqual(text.count("rust_binary("), 3)
        self.assertEqual(text.count("rust_test("), 6)
        self.assertEqual(text.count("rust_doc_test("), 1)
        for name in ["demo", "demo-cli", "lib_test__demo",
                     "bin_test__demo-cli", "test__integration",
                     "test__redirected", "test__cross", "doc__demo",
                     "example__compile", "example__tested",
                     "example_test__tested"]:
            self.assertIn('name = "' + name + '"', text)
        self.assertNotIn('name = "example_test__compile"', text)
        self.assertNotIn('name = "test__installer_update_e2e"', text)
        self.assertIn('//crates/demo:tests/fork/updates.rs', text)
        self.assertIn('//crates/other:tests/cross.rs', text)
        self.assertNotIn(':../', text)
        self.assertIn('version = "1.2.3"', text)
        self.assertIn('normal_dev = True', text)
        self.assertNotIn('test__cross', generated["crates/other/BUILD.bazel"])

    def test_dormant_files_do_not_create_targets(self):
        generated = gen_bazel.generate(self.metadata, {}, self.sources)
        self.assertNotIn('name = "test__installer_update_e2e"',
                         generated["crates/demo/BUILD.bazel"])

    def test_required_features_names_target_and_writes_nothing(self):
        self.metadata["packages"][0]["targets"][0]["required-features"] = ["x"]
        with self.assertRaisesRegex(
                ValueError, "demo:demo.*required-features"):
            gen_bazel.generate(self.metadata, {}, self.sources)

    def test_overrides_inputs_environment_and_kernel_mark(self):
        overrides = {"targets": {"//crates/demo:test__integration": {
            "reason": "fixture:1 reads extra input",
            "data": ["//:fixture"], "compile_data": ["//:included"],
            "env": {"RUNTIME": "yes"},
            "rustc_env": {"COMPILE": "yes"}, "kernel": True,
        }}}
        before = copy.deepcopy((self.metadata, overrides, self.sources))
        text = gen_bazel.generate(self.metadata, overrides, self.sources)[
            "crates/demo/BUILD.bazel"]
        for expected in ['data = ["//:fixture"]',
                         'compile_data = ["//:included"]',
                         '"RUNTIME": "yes"', '"COMPILE": "yes"',
                         '"agx-kernel"']:
            self.assertIn(expected, text)
        self.assertEqual((self.metadata, overrides, self.sources), before)

    def test_unused_override_fails_visibly(self):
        with self.assertRaisesRegex(ValueError, "absent targets.*missing"):
            gen_bazel.generate(self.metadata, {"targets": {
                "//crates/demo:missing": {"data": []},
            }}, self.sources)

    def test_differences_name_every_missing_extra_and_stale_file(self):
        expected = {"missing/BUILD.bazel": "one", "stale/BUILD.bazel": "two"}
        actual = {"extra/BUILD.bazel": "three", "stale/BUILD.bazel": "old"}
        before = copy.deepcopy((expected, actual))
        self.assertEqual(gen_bazel.differences(expected, actual), [
            "Extra: extra/BUILD.bazel", "Missing: missing/BUILD.bazel",
            "Stale: stale/BUILD.bazel",
        ])
        self.assertEqual((expected, actual), before)

    def test_cargo_path_patches_are_third_party_builds(self):
        manifest = ("[workspace]\nmembers=[]\n"
                    "[patch.crates-io]\n"
                    'patched = { path = "vendor/renamed" }\n'
                    '[patch."https://registry.example/index"]\n'
                    "another = { version = '1', path = 'local/another' }\n"
                    "remote = { git = 'https://example/repo' }\n"
                    "[dependencies]\n"
                    'first_party = { path = "crates/member" }\n')
        directories = gen_bazel.cargo_patch_dirs(manifest)
        self.assertEqual(directories, ["vendor/renamed", "local/another"])
        self.assertEqual(gen_bazel.first_party_builds([
            "BUILD.bazel", "vendor/renamed/BUILD.bazel",
            "local/another/BUILD.bazel", "crates/member/BUILD.bazel",
            "vendor/renamed-other/BUILD.bazel", "unused/BUILD.bazel",
        ], directories), {
            "BUILD.bazel", "crates/member/BUILD.bazel",
            "vendor/renamed-other/BUILD.bazel", "unused/BUILD.bazel",
        })

    def test_unsupported_or_escaping_patch_paths_fail(self):
        for entry in ['bad = { path = "../outside" }',
                      'bad = { path = "/absolute" }',
                      'bad = { path = "" }', 'bad = {']:
            with self.subTest(entry=entry):
                with self.assertRaises(ValueError):
                    gen_bazel.cargo_patch_dirs("[patch.crates-io]\n" + entry)

    def test_check_does_not_write_on_disk(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "scripts/agx").mkdir(parents=True)
            shutil.copy2(gen_bazel.__file__, root / "scripts/agx/gen_bazel.py")
            (root / "scripts/agx/bazel_overrides.json").write_text("{}")
            (root / "Cargo.toml").write_text(
                '[workspace]\nmembers=["crates/fixture"]\n'
                '[patch.crates-io]\n'
                'patched = { path = "vendor/renamed" }\n'
            )
            vendor = root / "vendor/renamed"
            (vendor / "src").mkdir(parents=True)
            (vendor / "Cargo.toml").write_text(
                '[package]\nname="patched"\nversion="0.1.0"\n'
            )
            (vendor / "src/lib.rs").write_text("pub fn native() {}\n")
            (vendor / "BUILD.bazel").write_text("# native third-party rule\n")
            crate = root / "crates/fixture"
            (crate / "src").mkdir(parents=True)
            (crate / "Cargo.toml").write_text(
                '[package]\nname="fixture"\nversion="0.1.0"\n'
                'edition="2021"\n'
            )
            (crate / "src/lib.rs").write_text(
                '/// ```\n/// assert_eq!(2 + 2, 4);\n/// ```\n'
                'pub fn value() -> u8 { 4 }\n'
            )
            subprocess.run(["git", "init", "--quiet", str(root)], check=True)
            subprocess.run(["cargo", "generate-lockfile"], cwd=root,
                           check=True, capture_output=True)
            command = ["python3", "scripts/agx/gen_bazel.py"]
            generated = subprocess.run(command, cwd=root, capture_output=True,
                                       text=True)
            self.assertEqual(generated.returncode, 0, generated.stderr)
            build = crate / "BUILD.bazel"
            original = build.read_bytes()
            cases = ("missing", "stale", "extra", "new test")
            for case in cases:
                with self.subTest(case=case):
                    build.write_bytes(original)
                    extra = root / "unused/BUILD.bazel"
                    new_test = crate / "tests/new.rs"
                    if case == "missing":
                        build.unlink()
                    elif case == "stale":
                        build.write_bytes(original + b"# manual edit\n")
                    elif case == "extra":
                        extra.parent.mkdir(exist_ok=True)
                        extra.write_text("# extra\n")
                    else:
                        new_test.parent.mkdir(exist_ok=True)
                        new_test.write_text("#[test] fn works() {}\n")
                    before = {str(p.relative_to(root)): p.read_bytes()
                              for p in (build, extra, new_test) if p.exists()}
                    result = subprocess.run(command + ["--check"], cwd=root,
                                            capture_output=True, text=True)
                    self.assertEqual(result.returncode, 1, result.stdout)
                    self.assertIn("BUILD.bazel", result.stderr)
                    after = {str(p.relative_to(root)): p.read_bytes()
                             for p in (build, extra, new_test) if p.exists()}
                    self.assertEqual(after, before)
                    for path in (extra, new_test):
                        if path.exists():
                            path.unlink()


if __name__ == "__main__":
    unittest.main()
