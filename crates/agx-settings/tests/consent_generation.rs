//! The overlay is part of consent metadata, including metadata failures.

use super::ConsentGeneration;

#[test]
fn settings_overlay_changes_the_consent_generation() {
    let root = tempfile::tempdir().unwrap();
    let cwd = root.path().join("cwd");
    let agent = root.path().join("agent");
    std::fs::create_dir_all(&cwd).unwrap();
    std::fs::create_dir_all(&agent).unwrap();
    let base = agent.join("settings.json");
    std::fs::write(&base, b"{\"agentTraces\":{\"enabled\":true}}\n").unwrap();
    let base_bytes = std::fs::read(&base).unwrap();
    let before = ConsentGeneration::read(&cwd, &agent);
    let overlay = agent.join("settings-agx.json");
    std::fs::write(&overlay, b"{\"agentTraces\":{\"enabled\":false}}\n").unwrap();
    let added = ConsentGeneration::read(&cwd, &agent);
    assert_eq!(std::fs::read(&base).unwrap(), base_bytes);
    assert_ne!(added, before);
    std::fs::remove_file(overlay).unwrap();
    assert_eq!(ConsentGeneration::read(&cwd, &agent), before);
    assert_eq!(std::fs::read(&base).unwrap(), base_bytes);
}

#[test]
#[cfg(unix)]
fn settings_overlay_metadata_error_is_not_a_valid_consent_snapshot() {
    let root = tempfile::tempdir().unwrap();
    let cwd = root.path().join("cwd");
    let agent = root.path().join("agent");
    std::fs::create_dir_all(&cwd).unwrap();
    std::fs::create_dir_all(&agent).unwrap();
    let base = agent.join("settings.json");
    std::fs::write(&base, b"{\"agentTraces\":{\"enabled\":true}}\n").unwrap();
    let base_bytes = std::fs::read(&base).unwrap();
    std::os::unix::fs::symlink("settings-agx.json", agent.join("settings-agx.json")).unwrap();
    let generation = ConsentGeneration::read(&cwd, &agent);
    assert_eq!(std::fs::read(&base).unwrap(), base_bytes);
    assert!(generation.0.iter().any(Result::is_err));
}
