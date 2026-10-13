//! agx lock fixtures; the TypeScript fixtures keep their base settings path.

use std::path::{Path, PathBuf};

fn settings_path(sandbox: &Path) -> PathBuf {
    sandbox.join("agent").join("settings-agx.json")
}

pub fn lock_path(sandbox: &Path) -> PathBuf {
    settings_path(sandbox).with_extension("json.lock")
}

pub fn seed_stale_lock_file(sandbox: &Path) {
    let path = lock_path(sandbox);
    std::fs::write(&path, "pre-compat flock artifact").expect("seed stale lock file");
    super::age(&path);
}

pub fn seed_stale_lock_dir(sandbox: &Path) {
    let path = lock_path(sandbox);
    std::fs::create_dir(&path).expect("seed stale lock directory");
    super::age(&path);
}

pub fn assert_settings_has_server(sandbox: &Path, name: &str) {
    let content =
        std::fs::read_to_string(settings_path(sandbox)).expect("settings-agx.json written");
    let value: serde_json::Value =
        serde_json::from_str(&content).expect("settings-agx.json parses");
    assert!(
        value
            .get("mcpServers")
            .and_then(|servers| servers.get(name))
            .is_some(),
        "settings-agx.json must contain server {name}: {content}"
    );
}
