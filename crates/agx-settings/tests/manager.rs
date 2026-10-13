//! File-backed settings contract for the agx overlay.

use std::io::{BufRead, BufReader, Write};
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};

use pa_core::settings::SettingsManager;
use serde_json::{json, Value};

struct Fixture {
    _root: tempfile::TempDir,
    cwd: PathBuf,
    agent: PathBuf,
    base: Vec<u8>,
}

impl Fixture {
    fn new(base: &Value) -> Self {
        let root = tempfile::tempdir().unwrap();
        let cwd = root.path().join("cwd");
        let agent = root.path().join("agent");
        std::fs::create_dir_all(cwd.join(".prime/agent")).unwrap();
        std::fs::create_dir_all(&agent).unwrap();
        let bytes = format!("{}\n", serde_json::to_string_pretty(base).unwrap()).into_bytes();
        std::fs::write(agent.join("settings.json"), &bytes).unwrap();
        Self {
            _root: root,
            cwd,
            agent,
            base: bytes,
        }
    }

    fn overlay(&self, value: &Value) {
        std::fs::write(self.agent.join("settings-agx.json"), value.to_string()).unwrap();
    }

    fn manager(&self) -> SettingsManager {
        SettingsManager::create(&self.cwd, &self.agent)
    }

    fn assert_base(&self) {
        assert_eq!(
            std::fs::read(self.agent.join("settings.json")).unwrap(),
            self.base
        );
    }

    fn document(&self) -> Value {
        serde_json::from_slice(&std::fs::read(self.agent.join("settings-agx.json")).unwrap())
            .unwrap()
    }
}

#[test]
fn settings_three_layers_keep_the_project_merge() {
    let f =
        Fixture::new(&json!({"theme":"base", "compaction":{"enabled":true,"reserveTokens":100}}));
    f.overlay(&json!({"theme":"overlay", "compaction":{"reserveTokens":200}}));
    std::fs::write(
        f.cwd.join(".prime/agent/settings.json"),
        json!({"theme":"project", "compaction":{"enabled":false}}).to_string(),
    )
    .unwrap();
    let manager = f.manager();
    f.assert_base();
    assert_eq!(
        manager.global_raw(),
        Some(&json!({"theme":"overlay", "compaction":{"enabled":true,"reserveTokens":200}}))
    );
    assert_eq!(manager.get_theme(), Some("project"));
    assert_eq!(
        manager
            .settings()
            .compaction
            .as_ref()
            .unwrap()
            .reserve_tokens,
        Some(200)
    );
    assert!(!manager.get_compaction_enabled());
}

#[test]
fn settings_writes_only_changed_nested_paths() {
    let f = Fixture::new(
        &json!({"theme":"base", "retry":{"enabled":true,"provider":{"maxRetryDelayMs":600}},"extensions":["opaque"]}),
    );
    let mut manager = f.manager();
    manager.set_retry_enabled(false).unwrap();
    f.assert_base();
    assert_eq!(f.document(), json!({"retry":{"enabled":false}}));
    assert_eq!(
        manager.global_raw(),
        Some(
            &json!({"theme":"base", "retry":{"enabled":false,"provider":{"maxRetryDelayMs":600}},"extensions":["opaque"]})
        )
    );
}

#[test]
fn settings_absent_overlay_keys_follow_a_later_base_edit() {
    let mut f = Fixture::new(&json!({"theme":"base", "defaultModel":"old"}));
    let mut manager = f.manager();
    manager.set_theme("overlay".into()).unwrap();
    f.assert_base();
    f.base = b"{\n  \"theme\": \"upstream-new\", \"defaultModel\": \"new\"\n}\n".to_vec();
    std::fs::write(f.agent.join("settings.json"), &f.base).unwrap();
    manager.reload().unwrap();
    f.assert_base();
    assert_eq!(manager.get_theme(), Some("overlay"));
    assert_eq!(manager.get_default_model(), Some("new"));
    assert_eq!(f.document(), json!({"theme":"overlay"}));
}

#[test]
fn settings_malformed_overlay_is_reported_ignored_and_not_written() {
    let f = Fixture::new(&json!({"theme":"base", "defaultModel":"old"}));
    let corrupt = b"{ not json\n";
    std::fs::write(f.agent.join("settings-agx.json"), corrupt).unwrap();
    let mut manager = f.manager();
    let reported = !manager.errors().is_empty();
    let rejected = manager.set_default_model("new".into()).is_err();
    f.assert_base();
    assert_eq!(
        std::fs::read(f.agent.join("settings-agx.json")).unwrap(),
        corrupt
    );
    assert!(reported);
    assert!(rejected);
    assert_eq!(manager.get_theme(), Some("base"));
}

#[test]
fn settings_write_rereads_and_refuses_newly_corrupt_overlay() {
    let f = Fixture::new(&json!({"retry":{"enabled":true}}));
    f.overlay(&json!({"theme":"overlay"}));
    let mut manager = f.manager();
    let corrupt = b"[broken";
    std::fs::write(f.agent.join("settings-agx.json"), corrupt).unwrap();
    let rejected = manager.set_retry_enabled(false).is_err();
    f.assert_base();
    assert_eq!(
        std::fs::read(f.agent.join("settings-agx.json")).unwrap(),
        corrupt
    );
    assert!(rejected);
}

#[test]
fn settings_clearing_an_inherited_value_writes_null() {
    let f = Fixture::new(&json!({"enabledModels":["base/*"],"theme":"base"}));
    let mut manager = f.manager();
    manager.set_enabled_models(None).unwrap();
    f.assert_base();
    assert_eq!(f.document(), json!({"enabledModels":null}));
    assert_eq!(manager.get_enabled_models(), None);
    assert_eq!(manager.global_raw(), Some(&json!({"theme":"base"})));
    let reopened = manager.reopen();
    assert_eq!(reopened.get_enabled_models(), None);
    f.assert_base();
}

#[test]
fn settings_project_null_does_not_remove_an_overlay_value() {
    let f = Fixture::new(&json!({"theme":"base"}));
    f.overlay(&json!({"theme":"overlay"}));
    std::fs::write(f.cwd.join(".prime/agent/settings.json"), "{\"theme\":null}").unwrap();
    let manager = f.manager();
    f.assert_base();
    assert_eq!(manager.get_theme(), Some("overlay"));
}

#[test]
fn settings_field_writers_keep_existing_tombstones() {
    let f = Fixture::new(&json!({"enabledModels":["base/*"],"packages":["old"],"skills":["old"]}));
    f.overlay(&json!({"enabledModels":null}));
    let mut manager = f.manager();
    manager.set_packages(vec![json!("local")]);
    manager.set_global_resource_array("skills", vec!["custom".into()]);
    f.assert_base();
    assert_eq!(
        f.document(),
        json!({"enabledModels":null,"packages":["local"],"skills":["custom"]})
    );
    assert_eq!(
        manager.global_raw(),
        Some(&json!({"packages":["local"],"skills":["custom"]}))
    );
}

#[test]
fn settings_project_writes_keep_their_existing_path_and_meaning() {
    let f = Fixture::new(&json!({"theme":"base"}));
    f.overlay(&json!({"theme":"overlay"}));
    let mut manager = f.manager();
    manager.set_project_packages(vec![json!("project")]);
    f.assert_base();
    assert_eq!(f.document(), json!({"theme":"overlay"}));
    let project: Value =
        serde_json::from_slice(&std::fs::read(f.cwd.join(".prime/agent/settings.json")).unwrap())
            .unwrap();
    assert_eq!(project, json!({"packages":["project"]}));
    assert_eq!(manager.get_theme(), Some("overlay"));
}

#[test]
fn settings_merge_patch_accepts_json_values_and_removes_object_keys() {
    for (overlay, expected) in [
        (
            json!({"factory":{"enabled":null},"extensions":["opaque-overlay"]}),
            json!({"factory":{"extra":1},"extensions":["opaque-overlay"]}),
        ),
        (
            json!({"factory":null}),
            json!({"extensions":["opaque-base"]}),
        ),
        (json!([1, 2]), json!([1, 2])),
        (json!(null), json!(null)),
    ] {
        let f = Fixture::new(
            &json!({"factory":{"enabled":true,"extra":1},"extensions":["opaque-base"]}),
        );
        f.overlay(&overlay);
        let manager = f.manager();
        f.assert_base();
        assert_eq!(manager.global_raw(), Some(&expected), "overlay {overlay}");
    }
}

#[test]
fn settings_two_processes_preserve_different_changed_keys() {
    let f = Fixture::new(&json!({"theme":"base", "defaultModel":"old", "retry":{"enabled":true}}));
    let executable = std::env::current_exe().unwrap();
    let mut children = Vec::new();
    for key in ["model", "retry"] {
        let mut child = Command::new(&executable)
            .args(["--exact", "settings_process_writer", "--nocapture"])
            .env("AGX_SETTINGS_TEST_AGENT", &f.agent)
            .env("AGX_SETTINGS_TEST_CWD", &f.cwd)
            .env("AGX_SETTINGS_TEST_KEY", key)
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .spawn()
            .unwrap();
        let mut output = BufReader::new(child.stdout.take().unwrap());
        let mut ready = false;
        for _ in 0..20 {
            let mut line = String::new();
            assert_ne!(output.read_line(&mut line).unwrap(), 0);
            if line.trim() == "READY" {
                ready = true;
                break;
            }
        }
        assert!(ready);
        children.push((child, output));
    }
    for (child, _) in &mut children {
        child.stdin.take().unwrap().write_all(b"GO\n").unwrap();
    }
    for (mut child, _) in children {
        let status = child.wait().unwrap();
        assert!(status.success(), "child writer failed: {status}");
    }
    f.assert_base();
    assert_eq!(
        f.document(),
        json!({"defaultModel":"new", "retry":{"enabled":false}})
    );
    assert_eq!(
        f.manager().global_raw(),
        Some(&json!({"theme":"base","defaultModel":"new","retry":{"enabled":false}}))
    );
}

#[test]
fn settings_process_writer() {
    let Ok(agent) = std::env::var("AGX_SETTINGS_TEST_AGENT") else {
        return;
    };
    let cwd = std::env::var("AGX_SETTINGS_TEST_CWD").unwrap();
    let base = std::fs::read(Path::new(&agent).join("settings.json")).unwrap();
    let mut manager = SettingsManager::create(cwd, &agent);
    println!("READY");
    std::io::stdout().flush().unwrap();
    let mut go = String::new();
    std::io::stdin().read_line(&mut go).unwrap();
    assert_eq!(go.trim(), "GO");
    match std::env::var("AGX_SETTINGS_TEST_KEY").unwrap().as_str() {
        "model" => manager.set_default_model("new".into()).unwrap(),
        "retry" => manager.set_retry_enabled(false).unwrap(),
        unexpected => panic!("unexpected writer {unexpected}"),
    }
    assert_eq!(
        std::fs::read(Path::new(&agent).join("settings.json")).unwrap(),
        base
    );
}

#[test]
fn settings_refinement_factory_enabled_case_table() {
    let cases: Value = serde_json::from_str(include_str!("factory_cases.json")).unwrap();
    for case in cases.as_array().unwrap() {
        let root = tempfile::tempdir().unwrap();
        let base = root.path().join("settings.json");
        for (key, filename) in [("base", "settings.json"), ("overlay", "settings-agx.json")] {
            let path = root.path().join(filename);
            if let Some(content) = case[key].as_str() {
                std::fs::write(path, content).unwrap();
            } else if case[key].is_object() {
                assert_eq!(case[key], json!({"directory":true}));
                std::fs::create_dir(path).unwrap();
            } else {
                assert!(case[key].is_null());
            }
        }
        let before = std::fs::read(&base).ok();
        let before_directory = base.is_dir();
        let observed = pa_core::refinement::factory_enabled(root.path());
        assert_eq!(std::fs::read(&base).ok(), before, "{}", case["name"]);
        assert_eq!(base.is_dir(), before_directory, "{}", case["name"]);
        assert_eq!(
            observed,
            case["expected"].as_bool().unwrap(),
            "{}",
            case["name"]
        );
    }
}
