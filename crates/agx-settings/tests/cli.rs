//! Real agx commands must write only the overlay.

use std::path::PathBuf;
use std::process::{Command, Output};

use serde_json::{json, Value};

struct Fixture {
    root: tempfile::TempDir,
    agent: PathBuf,
    base: Vec<u8>,
}

impl Fixture {
    fn new(base: &Value) -> Self {
        let root = tempfile::tempdir().unwrap();
        let agent = root.path().join("agent");
        std::fs::create_dir_all(&agent).unwrap();
        let bytes = format!("{}\n", serde_json::to_string_pretty(base).unwrap()).into_bytes();
        std::fs::write(agent.join("settings.json"), &bytes).unwrap();
        Self {
            root,
            agent,
            base: bytes,
        }
    }

    fn run(&self, args: &[&str]) -> Output {
        Command::new(env!("CARGO_BIN_EXE_agx"))
            .args(args)
            .current_dir(self.root.path())
            .env_clear()
            .env("HOME", self.root.path())
            .env("TMPDIR", self.root.path())
            .env("TZ", "UTC")
            .env("DO_NOT_TRACK", "1")
            .env("PRIME_AGENT_CODING_AGENT_DIR", &self.agent)
            .env("AGX_PROCESS", "1")
            .env("PATH", std::env::var("PATH").unwrap())
            .output()
            .unwrap()
    }

    fn assert_base(&self) {
        assert_eq!(
            std::fs::read(self.agent.join("settings.json")).unwrap(),
            self.base
        );
    }

    fn overlay(&self) -> Value {
        serde_json::from_slice(&std::fs::read(self.agent.join("settings-agx.json")).unwrap())
            .unwrap()
    }
}

#[test]
fn settings_agx_mcp_add_get_list_replace_and_remove() {
    let f = Fixture::new(&json!({"theme":"base"}));
    let add = f.run(&[
        "mcp",
        "add",
        "server",
        "--cwd",
        "/fake",
        "--env",
        "CHILD=SOURCE",
        "--",
        "fake-mcp",
        "arg",
    ]);
    f.assert_base();
    assert!(
        add.status.success(),
        "{}",
        String::from_utf8_lossy(&add.stderr)
    );
    assert_eq!(
        f.overlay(),
        json!({"mcpServers":{"server":{"type":"stdio","command":"fake-mcp","args":["arg"],"cwd":"/fake","env":{"CHILD":{"env":"SOURCE"}}}}})
    );
    let get = f.run(&["mcp", "get", "server"]);
    let list = f.run(&["mcp", "list"]);
    f.assert_base();
    assert!(get.status.success());
    assert!(list.status.success());
    assert!(String::from_utf8_lossy(&get.stdout).contains("server: stdio"));
    assert!(String::from_utf8_lossy(&list.stdout).contains("server: stdio"));
    let replaced = f.run(&[
        "mcp",
        "add",
        "server",
        "--force",
        "--url",
        "https://example.invalid/mcp",
        "--bearer-token-env-var",
        "TOKEN",
    ]);
    f.assert_base();
    assert!(
        replaced.status.success(),
        "{}",
        String::from_utf8_lossy(&replaced.stderr)
    );
    let get = f.run(&["mcp", "get", "server"]);
    assert!(String::from_utf8_lossy(&get.stdout).contains("server: http"));
    let removed = f.run(&["mcp", "remove", "server"]);
    f.assert_base();
    assert!(
        removed.status.success(),
        "{}",
        String::from_utf8_lossy(&removed.stderr)
    );
    assert_eq!(f.overlay(), json!({"mcpServers":{"server":null}}));
    let get = f.run(&["mcp", "get", "server"]);
    f.assert_base();
    assert!(!get.status.success());
}

#[test]
fn settings_agx_mcp_remove_an_inherited_server() {
    let f = Fixture::new(
        &json!({"theme":"base", "mcpServers":{"inherited":{"type":"http","url":"https://example.invalid/mcp"},"keep":{"type":"stdio","command":"fake-mcp"}}}),
    );
    let removed = f.run(&["mcp", "remove", "inherited"]);
    f.assert_base();
    assert!(
        removed.status.success(),
        "{}",
        String::from_utf8_lossy(&removed.stderr)
    );
    assert_eq!(f.overlay(), json!({"mcpServers":{"inherited":null}}));
    let list = f.run(&["mcp", "list"]);
    f.assert_base();
    assert!(list.status.success());
    assert!(!String::from_utf8_lossy(&list.stdout).contains("inherited"));
    assert!(String::from_utf8_lossy(&list.stdout).contains("keep: stdio"));
}

#[test]
fn settings_agx_mcp_refuses_a_malformed_overlay() {
    let f = Fixture::new(
        &json!({"mcpServers":{"inherited":{"type":"http","url":"https://example.invalid/mcp"}}}),
    );
    let corrupt = b"{ invalid\n";
    std::fs::write(f.agent.join("settings-agx.json"), corrupt).unwrap();
    let list = f.run(&["mcp", "list"]);
    let removed = f.run(&["mcp", "remove", "inherited"]);
    f.assert_base();
    assert!(list.status.success());
    assert!(String::from_utf8_lossy(&list.stdout).contains("inherited: http"));
    assert!(!removed.status.success());
    assert!(String::from_utf8_lossy(&removed.stderr).contains("settings-agx.json"));
    assert_eq!(
        std::fs::read(f.agent.join("settings-agx.json")).unwrap(),
        corrupt
    );
}

#[test]
fn settings_agx_mcp_replaces_only_one_inherited_server() {
    let f = Fixture::new(
        &json!({"mcpServers":{"inherited":{"type":"stdio","command":"fake-mcp","args":["old"],"cwd":"/old"},"keep":{"type":"http","url":"https://example.invalid/keep"}}}),
    );
    let replaced = f.run(&[
        "mcp",
        "add",
        "inherited",
        "--force",
        "--url",
        "https://example.invalid/new",
        "--oauth",
    ]);
    f.assert_base();
    assert!(
        replaced.status.success(),
        "{}",
        String::from_utf8_lossy(&replaced.stderr)
    );
    assert_eq!(
        f.overlay(),
        json!({"mcpServers":{"inherited":{"type":"http","command":null,"args":null,"cwd":null,"url":"https://example.invalid/new","oauth":true}}})
    );
    let list = f.run(&["mcp", "list"]);
    f.assert_base();
    assert!(list.status.success());
    assert!(String::from_utf8_lossy(&list.stdout).contains("inherited: http"));
    assert!(String::from_utf8_lossy(&list.stdout).contains("keep: http"));
}
