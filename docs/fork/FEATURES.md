# agx features and fixes

agx adds separate runtime state, read-only upstream settings, and forced-off
telemetry and trace uploads to Prime Agent. This list covers the code at
[63b60e348][snapshot], not inherited upstream features or planned plugins.

Upstream adoption was checked on 2026-10-13 against [d592d5e77][upstream-snapshot].
“Not proposed” means no covering proposal was found in the upstream PRs and
issues checked. Fork-specific choices can stay different from upstream.
An adopted fix stays listed until the next sync removes the fork's copy.

Each `AGX-` ID names one feature or fix. Keep the IDs when wording or status changes.
“Added in agx” records the first implementation commit. The CI source has its
own history.

## Runtime and settings

| ID | Feature or fix | Why it matters | Fork commits | Changed upstream files or behavior | Added in agx | Upstream status |
| --- | --- | --- | --- | --- | --- | --- |
| AGX-001 | Separate `agx` command and version name. | Keep `prime-agent` installed and choose which program to run. | [1ec56e169][identity], [9b96e7aa5][rename] | CLI binary name, help and version output. [CLI manifest][cli-manifest] | [1ec56e169][identity] | Not proposed. |
| AGX-002 | Separate daemon sockets, Windows pipes and kernel environment. Recognized upstream socket paths are refused. | agx cannot connect to or replace a daemon in an upstream socket directory. | [1ec56e169][identity], [b9bb00512][isolation-fix], [9b96e7aa5][rename] | Daemon and transport endpoints, default kernel environment and socket checks. [Policy source][identity-source] | [1ec56e169][identity] | Not proposed. |
| AGX-003 | Fresh processes clear inherited upstream runtime and process-role variables. Bash and kernel children drop internal roles. | Starting one product from the other does not inherit the wrong daemon or worker role. | [1ec56e169][identity], [9b96e7aa5][rename] | Startup, bash-tool and kernel process environments. [Policy source][identity-source] | [1ec56e169][identity] | Not proposed. |
| AGX-004 | `agx update`, its aliases and TUI `/update` refuse automatic installation and show local update instructions. | An update request cannot install upstream over agx. | [1ec56e169][identity], [9b96e7aa5][rename] | CLI and TUI update dispatch, before installer requests. [Update command][update-source] | [1ec56e169][identity] | Not proposed. |
| AGX-005 | Release usage telemetry stays off despite saved or environment opt-ins. No build has a telemetry network endpoint. | Fork usage is not sent to Prime Intellect. | [1ec56e169][identity], [b9bb00512][isolation-fix] | Telemetry switch and client endpoint. [Telemetry source][telemetry-source] | [1ec56e169][identity] | Not proposed. |
| AGX-006 | Automatic and manual trace uploads stay off, including forced single-file and upload-all requests. | Shared trace settings cannot upload agx sessions to Prime Intellect. | [1ec56e169][identity], [217f1fbbe][upstream-merge] | Public trace upload and continuous-upload paths, CLI and TUI sharing controls. [Upload source][trace-source] | [1ec56e169][identity] | Not proposed. |
| <a id="agx-007"></a>AGX-007 | Global edits go to `settings-agx.json`, over the read-only `settings.json` base. A `null` removes an inherited key. | Change or remove inherited settings, including MCP servers, without editing upstream's settings file. | [e29276e27][overlay], [63b60e348][overlay-tests] | Global settings and MCP persistence, factory readers, consent refresh and CLI fixtures. [Overlay source][overlay-source] | [e29276e27][overlay] | Not proposed. |
| AGX-008 | The Unix local installer stages an agx bundle and launcher without replacing upstream's installation. | Build and update agx from a verified checkout while keeping upstream intact. | [1ec56e169][identity], [9b96e7aa5][rename] | Native packer's binary-name option and fork-owned installer. [Installer source][installer-source] | [1ec56e169][identity] | Not proposed. |

### Limits that affect daily use

- Sessions, authentication and base settings still use upstream's shared formats
  and agent directory. Only agx global settings writes use the overlay.
- Overlay writes keep unrelated settings from other writers. Malformed overlays
  are reported and ignored on reads. Writes refuse them without rewriting the file.
  Project settings keep upstream's merge rules. Both factory readers use the overlay.
- Socket refusal recognizes upstream's standard socket directories and Windows
  pipe prefix. It does not detect an upstream daemon configured at an unrelated path.
- Release builds never write `telemetry.jsonl`. Debug builds retain local usage
  counting and write that mirror for tests when telemetry is enabled. No build
  sends those events. The shared `telemetry.json` installation ID can still be
  created. Use a temporary agent directory for debug testing.
- The installer supports Unix, not Windows installation. Windows pipe separation
  is in the source, but its runtime behavior was not checked on the Mac.
- Updates require a newly verified checkout and the [local installer][install-doc].

## Build and maintenance

The test-only fixes below improve build and regression checks. They do not add
new session behavior. Linux-only tests stay available on Linux.

| ID | Feature or fix | Why it matters | Fork commits | Changed upstream files or behavior | Added in agx | Upstream status |
| --- | --- | --- | --- | --- | --- | --- |
| AGX-009 | An upstream change inventory and checker reject unlisted changes and rows for unchanged files. | See what must be reviewed when taking in upstream changes. | [1ec56e169][identity], [217f1fbbe][upstream-merge], [e29276e27][overlay], [63b60e348][overlay-tests] | Fork-owned [change inventory][seams] and [checker][seam-checker]. | [1ec56e169][identity] | Not proposed. |
| AGX-010 | Fork CI checks format, Clippy, workspace tests and release builds on Linux. It bootstraps the kernel and saves test logs. | Check the complete fork on Linux even when local development uses macOS. | `985d650fb`, `bc22c2cd8` | Fork-owned [workflow](../../.github/workflows/agx-ci.yml) and [failed-test helper](../../scripts/agx/rerun_failed.py). | `985d650fb` | Not proposed. |
| AGX-011 | Terminal test helpers use macOS-compatible ioctl types and handle the absent Linux-only termios field. | The existing terminal regression tests compile on macOS. | [2106901fd][terminal-fix] | `kitty_*`, `slow_drain_exit_guard_e2e.rs` and [terminal-state test helper][terminal-source]. | [2106901fd][terminal-fix] | Not proposed. |
| AGX-012 | Linux-only `prctl`, terminal and `/proc` test code is guarded by the target OS. | macOS builds no longer compile unavailable Linux APIs. Linux still runs the tests. | [1de78b14e][linux-fix], [1ec56e169][identity], [217f1fbbe][upstream-merge] | `interactive_daemon_e2e.rs`, `termios_process_exit_e2e.rs` and `windows_runtime_triage_e2e.rs`. [Linux-only test target][linux-source] | [1de78b14e][linux-fix] | Not proposed. |
| AGX-013 | The daemon client sets its read timeout once at connection, not again after the peer closes. | On macOS, a close reports the daemon's reason instead of a socket-option error. | [484e73718][timeout-fix] | [Daemon client][timeout-source] connection and read loop. | [484e73718][timeout-fix] | Not proposed. |
| AGX-014 | The telemetry mirror test holds the shared environment lock across its awaits. | Other tests cannot change opt-out variables while this test checks event delivery. | [164f6d231][mirror-fix] | [Telemetry mirror test][mirror-source]. No production telemetry change. | [164f6d231][mirror-fix] | Adopted in upstream [PR #3520][mirror-upstream] at [f14db8553][mirror-upstream-commit]. Still carried until the next sync. |
| AGX-015 | The worker-recovery test marks its supervisor as an agx child so its test override reaches the workers. | The recovery test exercises the lost-exit case instead of losing its setup during startup isolation. | [8392a0d69][triage-fix] | [Windows-runtime recovery test][triage-source]. No production recovery change. | [8392a0d69][triage-fix] | Not proposed. |

### CI location and adoption

The fork CI files are fork-owned and run on demand.

A sync reviewer confirms adoption by reading upstream code, not only a PR title.
Partial adoption keeps the row and names what remains. Full adoption names the
upstream PR and commit or version, then prompts removal of the fork's copy.
This document links existing upstream work; it does not create an upstream proposal.

[snapshot]: https://github.com/peterkc-io/agx/commit/63b60e348bc111fc93ff49e2ed135905e6cec967
[upstream-snapshot]: https://github.com/PrimeIntellect-ai/prime-agent/commit/d592d5e7746408fe9097541af96d3239e263f7a1
[identity]: https://github.com/peterkc-io/agx/commit/1ec56e169a8668d249620f8f926e6cfdfc744a90
[rename]: https://github.com/peterkc-io/agx/commit/9b96e7aa58f5f17b001892d90934d87041972665
[isolation-fix]: https://github.com/peterkc-io/agx/commit/b9bb00512d7d6c1deafa71aa10ac2b31d643252b
[upstream-merge]: https://github.com/peterkc-io/agx/commit/217f1fbbecf2bf933c2684b6fd21f2c7baf9229e
[overlay]: https://github.com/peterkc-io/agx/commit/e29276e274f17c04e28e668feaac1e45082a705d
[overlay-tests]: https://github.com/peterkc-io/agx/commit/63b60e348bc111fc93ff49e2ed135905e6cec967
[terminal-fix]: https://github.com/peterkc-io/agx/commit/2106901fdf15ef57353ea727a090084ceeb23c64
[linux-fix]: https://github.com/peterkc-io/agx/commit/1de78b14e2fc6ec52b5752f94a7bb55cb1b0cc23
[timeout-fix]: https://github.com/peterkc-io/agx/commit/484e7371815a5bd59c47696dc384272eb06c83c8
[mirror-fix]: https://github.com/peterkc-io/agx/commit/164f6d231aa14f56be91aee8fa861e26e7af91fb
[triage-fix]: https://github.com/peterkc-io/agx/commit/8392a0d6917017273212f808410fa08c3fe9df40
[mirror-upstream]: https://github.com/PrimeIntellect-ai/prime-agent/pull/3520
[mirror-upstream-commit]: https://github.com/PrimeIntellect-ai/prime-agent/commit/f14db8553a3852c22dbcfcdc0392616b37127ee5
[cli-manifest]: ../../crates/pa-cli/Cargo.toml
[identity-source]: ../../crates/agx-identity/src/lib.rs
[update-source]: ../../crates/pa-cli/src/public_command.rs
[telemetry-source]: ../../crates/pa-core/src/session_engine/telemetry/status.rs
[trace-source]: ../../crates/pa-core/src/agent_traces/upload.rs
[overlay-source]: ../../crates/agx-settings/README.md
[installer-source]: ../../scripts/agx/install_local.py
[install-doc]: INSTALL.md
[seams]: SEAMS.md
[seam-checker]: ../../scripts/agx/check_seams.py
[terminal-source]: ../../crates/pa-cli/tests/terminal_state_differential_e2e/harness.rs
[linux-source]: ../../crates/pa-cli/tests/termios_process_exit_e2e.rs
[timeout-source]: ../../crates/pa-cli/src/daemon_client.rs
[mirror-source]: ../../crates/pa-core/src/session_engine/telemetry/tests.rs
[triage-source]: ../../crates/pa-cli/tests/windows_runtime_triage_e2e.rs
