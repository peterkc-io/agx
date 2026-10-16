# Upstream seams

This ledger compares the working tree or selected commit with `upstream/main`.
The foundation base is `c24ac227f11f552ed1d3fa8ebc7d916937d7f6bc`.

```sh
python3 scripts/agx/check_seams.py
python3 scripts/agx/check_seams.py --revision HEAD
python3 scripts/agx/test_check_seams.py
```

The checker rejects missing rows and stale unchanged-file rows. Files under the
fork-owned paths of PLAN FR-023 need no row; every other changed or added file does. Verification names below identify the
checks for each seam; the worker report carries observed results. Linux CI is
lead-owned. Windows runtime behavior is not checked on the macOS host.

The old three installer-download scenarios are unreachable in agx and are
replaced by three no-network refusal scenarios through Cargo's existing test
target. The fork deletes or newly ignores no other test. Upstream #3522 removes the
Decision API and its tests; the user chose that removal, with no replacement
coverage because the feature is no longer present. The remaining Linux-only
test file retains its Linux coverage. Its macOS code exclusion is distinct
from accepted host failures. The prerequisite platform adjustments remain.

Upstream PR #3339 is merged in the recorded upstream-first base
`2ee7e623a70d8ccd9c72ffc6c4f25be2cc1bc02d`. Its shutdown-close coverage is
retained with the existing Linux prerequisite guards.

On this macOS host, the known baseline failures are ten pa-tui platform-key or
clipboard cases and two pa-types Unix-socket length cases. The current run has
eight of those pa-tui failures and the same two pa-types failures; neither
clipboard case fails now. The user also accepts
`refinement::tests::concurrent_update_harness_state_writes_all_land` as a host
failure here: it intermittently times out on the harness lock on both the fork
and exact upstream, likely after upstream #3380 added durable sync. This is not
a D-17 flake waiver. The refinement test must pass in both Linux CI carriers;
a failure in either carrier stops upstream-first.

| Upstream file | Reason | Verification |
| --- | --- | --- |
| `Cargo.lock` | Record the local agx identity and settings crate dependencies. | Locked workspace build; dependency versions unchanged. |
| `Cargo.toml` | Add fork-owned identity and JSON settings workspace crates. | Workspace fmt, clippy, and build. |
| `crates/pa-cli/Cargo.toml` | Name the binary agx; register fork update refusals and real settings-command tests. | No-network update tests; agx settings command tests; workspace checks. |
| `crates/pa-cli/src/client_traces.rs` | Report trace sharing unsupported and off. | Four client-trace tests and public no-request trace test; legacy protocol coverage retained. |
| `crates/pa-cli/src/client_update.rs` | Refuse agx updates before retained upstream Homebrew and managed-update paths. | Fork update refusal and actual TUI error-exit scenario. |
| `crates/pa-cli/src/config.rs` | Name the app agx; reject resolved upstream socket paths. | Four config tests, including both namespaces and all sources. |
| `crates/pa-cli/src/daemon_client.rs` | macOS setsockopt after peer close returns EINVAL; set READ_POLL once. | Four daemon-client tests; closing-reason test 50/50. |
| `crates/pa-cli/src/daemon_command.rs` | Apply socket precedence before guarded resolution. | CLI daemon parser tests and explicit socket rejection scenario. |
| `crates/pa-cli/src/daemon_discovery/mod.rs` | `current_state_root`: exit with the socket rejection error before any socket use, because the fork resolver returns a `Result` (FR-013). | Release build; daemon_discovery_e2e; status with an upstream socket path refused. |
| `crates/pa-cli/src/daemon_mode.rs` | Propagate socket rejection before starting a supervisor. | Config tests and live socket coexistence scenario. |
| `crates/pa-cli/src/installer_update.rs` | Refuse agx installer execution before retained upstream Homebrew and update code. | Three fork-owned no-network update scenarios. |
| `crates/pa-cli/src/interactive_mode.rs` | Propagate guarded socket resolution. | Config tests and live socket coexistence scenario. |
| `crates/pa-cli/src/interactive_mode/daemon.rs` | Reject upstream sockets before stale-daemon checks or replacement. | Socket unit tests and live coexistence scenario. |
| `crates/pa-cli/src/lib.rs` | Prefix version output with agx. | Local install version check. |
| `crates/pa-cli/src/main.rs` | Initialize fork lineage (`initialize_process`) before threading or dispatch. | Seven identity tests; bare release runtime and native venv override regression. |
| `crates/pa-cli/src/print_runtime.rs` | Propagate socket rejection before opening or leasing a session. | Socket source tests and print-session fixture. |
| `crates/pa-cli/src/public_command.rs` | Block update and alias before any installer requests. | Three fork update refusal tests. |
| `crates/pa-cli/tests/acp_config_option_e2e.rs` | Use Cargo executable agx in the existing fixture. | CLI integration target compilation and Linux suites (lead-owned). |
| `crates/pa-cli/tests/acp_mode_e2e.rs` | Use agx executable and default kernel discovery; retain ACP protocol identity. | ACP targets in Linux CI (lead-owned). |
| `crates/pa-cli/tests/agents_view_anchor_e2e.rs` | Use Cargo executable agx in the existing fixture. | CLI integration target compilation and Linux suites (lead-owned). |
| `crates/pa-cli/tests/agents_view_flash_e2e.rs` | Use Cargo executable agx in the existing fixture. | CLI integration target compilation and Linux suites (lead-owned). |
| `crates/pa-cli/tests/agents_view_refusal_panel_e2e.rs` | Use Cargo executable agx in the existing fixture. | CLI integration target compilation and Linux suites (lead-owned). |
| `crates/pa-cli/tests/agents_view_reply_e2e.rs` | Use Cargo executable agx in the existing fixture. | CLI integration target compilation and Linux suites (lead-owned). |
| `crates/pa-cli/tests/agents_view_search_e2e.rs` | Use Cargo executable agx in the existing fixture. | CLI integration target compilation and Linux suites (lead-owned). |
| `crates/pa-cli/tests/agents_view_subagents_e2e.rs` | Use Cargo executable agx in the existing fixture. | CLI integration target compilation and Linux suites (lead-owned). |
| `crates/pa-cli/tests/chat_agents_chat_roundtrip_e2e.rs` | Use Cargo executable agx in the existing fixture. | CLI integration target compilation and Linux suites (lead-owned). |
| `crates/pa-cli/tests/clipboard_auth_commands_e2e.rs` | Use Cargo executable agx in the existing fixture. | CLI integration target compilation and Linux suites (lead-owned). |
| `crates/pa-cli/tests/continue_guard_e2e.rs` | Use Cargo executable agx in the existing fixture. | CLI integration target compilation and Linux suites (lead-owned). |
| `crates/pa-cli/tests/daemon_commands_e2e.rs` | Use Cargo executable agx in the existing fixture. | CLI integration target compilation and Linux suites (lead-owned). |
| `crates/pa-cli/tests/daemon_discovery_e2e.rs` | Use Cargo executable agx in the existing fixture; `run_cli_state_env` marks the CLI as an agx child so an env-pinned socket survives startup isolation (FR-010), and removes the other variables that startup isolation clears; the shutdown-scope fixture uses an `agx-<uid>` socket dir, because agx refuses `prime-agent-<uid>` (FR-013). | daemon_discovery_e2e (8 tests) and Linux suites (lead-owned). |
| `crates/pa-cli/tests/differential_cli.rs` | Normalize only the fork executable/version identity in the existing comparison. | Differential CLI corpus with its configured upstream oracle. |
| `crates/pa-cli/tests/dock_scope_exit_focus_e2e.rs` | Use Cargo executable agx in the existing fixture. | CLI integration target compilation and Linux suites (lead-owned). |
| `crates/pa-cli/tests/eval_composition_e2e.rs` | Use Cargo executable agx in the existing fixture. | CLI integration target compilation and Linux suites (lead-owned). |
| `crates/pa-cli/tests/export_live_differential.rs` | Use Cargo executable agx in the existing fixture. | CLI integration target compilation and Linux suites (lead-owned). |
| `crates/pa-cli/tests/export_share_e2e.rs` | Use Cargo executable agx in the existing fixture. | CLI integration target compilation and Linux suites (lead-owned). |
| `crates/pa-cli/tests/interactive_daemon_e2e.rs` | Use agx executable; Linux-only test code, upstream CI is Linux-only. | Linux integration suite; six termios tests are compiled out on macOS. |
| `crates/pa-cli/tests/interactive_fork_e2e.rs` | Use Cargo executable agx in the existing fixture. | CLI integration target compilation and Linux suites (lead-owned). |
| `crates/pa-cli/tests/kitty_early_typing_e2e.rs` | macOS portability; upstream CI is Linux-only. | Native focused terminal checks; Linux baseline comparison (lead-owned). |
| `crates/pa-cli/tests/kitty_exit_routes_e2e/main.rs` | macOS portability; upstream CI is Linux-only. | Native focused terminal checks; Linux baseline comparison (lead-owned). |
| `crates/pa-cli/tests/kitty_release_handoff_e2e.rs` | macOS portability; upstream CI is Linux-only. | Native focused terminal checks; Linux baseline comparison (lead-owned). |
| `crates/pa-cli/tests/kitty_verdict_time_e2e.rs` | macOS portability; upstream CI is Linux-only. | Native focused terminal checks; Linux baseline comparison (lead-owned). |
| `crates/pa-cli/tests/lock_compat_e2e.rs` | Use agx; test overlay locks (FR-019), keeping TS base-file cases. | CLI lock integration tests and Linux suites. |
| `crates/pa-cli/tests/settings_mcp_save.rs` | Use agx; read MCP saves from `settings-agx.json` and keep `settings.json` byte-identical; an unparseable base no longer blocks the overlay write (user decision 2026-10-14). | settings_mcp_save tests. |
| `crates/pa-daemon/tests/kernel_harness_env_e2e.rs` | Discover the fork default kernel venv; mark the test supervisor as agx so its lost-exit override survives startup isolation. | kernel_harness_env_e2e explicit run; Linux suites. |
| `crates/pa-daemon/tests/launch_env_e2e.rs` | `kernel_python`, `spawn_supervisor`: discover the fork default kernel venv; mark the test supervisor as agx so its lost-exit override survives startup isolation. | launch_env_e2e explicit run; Linux suites. |
| `crates/pa-cli/tests/mcp_view_e2e.rs` | Use Cargo executable agx in the existing fixture. | CLI integration target compilation and Linux suites (lead-owned). |
| `crates/pa-cli/tests/package_e2e.rs` | Use Cargo executable agx in the existing fixture. | CLI integration target compilation and Linux suites (lead-owned). |
| `crates/pa-cli/tests/package_resources_e2e.rs` | Use Cargo executable agx in the existing fixture. | CLI integration target compilation and Linux suites (lead-owned). |
| `crates/pa-cli/tests/packaged_layout_e2e.rs` | Use Cargo executable agx and its version prefix, preserving hostile-env isolation. | Exact hostile packaged-layout regression and lead-owned Linux CI. |
| `crates/pa-cli/tests/print_runtime_e2e.rs` | Use Cargo executable agx in the existing fixture. | CLI integration target compilation and Linux suites (lead-owned). |
| `crates/pa-cli/tests/rpc_mode_e2e.rs` | Use Cargo executable agx in the existing fixture. | CLI integration target compilation and Linux suites (lead-owned). |
| `crates/pa-cli/tests/slow_drain_exit_guard_e2e.rs` | macOS portability; upstream CI is Linux-only. | Native focused terminal checks; Linux baseline comparison (lead-owned). |
| `crates/pa-cli/tests/subagent_panel_nav_e2e.rs` | Use Cargo executable agx in the existing fixture. | CLI integration target compilation and Linux suites (lead-owned). |
| `crates/pa-cli/tests/subagent_panel_nested_count_e2e.rs` | Use Cargo executable agx in the existing fixture. | CLI integration target compilation and Linux suites (lead-owned). |
| `crates/pa-cli/tests/telemetry_command_e2e.rs` | Use agx; read the overlay and assert no base-file creation (FR-019). | Original telemetry command round-trip and opt-out assertions. |
| `crates/pa-cli/tests/terminal_state_differential_e2e/harness.rs` | macOS portability; upstream CI is Linux-only. | Native focused terminal checks; Linux baseline comparison (lead-owned). |
| `crates/pa-cli/tests/termios_process_exit_e2e.rs` | Linux-only test code; upstream CI is Linux-only. | Linux integration suite (lead-owned). |
| `crates/pa-cli/tests/view_switch_latency_e2e.rs` | Use Cargo executable agx in the existing fixture. | CLI integration target compilation and Linux suites (lead-owned). |
| `crates/pa-cli/tests/windows_runtime_triage_e2e.rs` | Use agx executable; mark test supervisor (FR-010) to preserve lost-exit override; Linux-only prctl backstop, upstream CI is Linux-only. | Linux integration suite; Windows triage path unchanged. |
| `crates/pa-core/src/agent_traces.rs` | Add the fork-owned public upload guard test module. | Recording test has a reachable HTTP positive control. |
| `crates/pa-core/src/agent_traces/continuous.rs` | Refuse production fork continuous uploads; include overlay metadata in consent generation and preserve error results. | Retained upstream trace suite; red/green fork consent-generation tests; installed release trace refusal. |
| `crates/pa-core/src/agent_traces/tests.rs` | Keep legacy protocol tests on private carried upstream machinery. | Legacy trace unit tests and separate public guard test. |
| `crates/pa-core/src/agent_traces/upload.rs` | Disable every public single-file upload before requests, including forced options. | Recording fake returns Disabled with zero requests. |
| `crates/pa-core/src/agent_traces/upload_all.rs` | Disable public upload-all before payload collection or requests; retain private protocol coverage. | Recording fake for upload-all and legacy protocol tests. |
| `crates/pa-core/src/kernel/bootstrap/venv/layout.rs` | `kernel_venv_dir` and `xdg_kernel_venv_dir` use the fork `kernel-venv-agx` names, so agx exports no venv variable to its children. | venv_dir_honors_override; kernel environment scenario; native library suite. |
| `crates/pa-core/src/kernel/bootstrap/venv/tests.rs` | `venv_dir_honors_override` expects the fork default name. | Native library suite. |
| `crates/pa-core/src/tools/fork_bash_tests.rs` | Added fork test module: the actual bash tool spawn strips internal roles. | Fork test in the workspace suite. |
| `crates/pa-core/src/agent_traces/fork_tests.rs` | Added fork test module for the public trace upload guard. | Fork test in the workspace suite. |
| `crates/pa-core/src/session_engine/telemetry/fork_tests.rs` | Added fork test module for the release telemetry switch. | Fork test in the workspace suite. |
| `crates/pa-core/tests/agx_kernel_journal.rs` | Added fork test: the kernel keeps pa-core's orphan-journal variable name (PLAN D-26). | Workspace test suite. |
| `crates/pa-cli/src/fork/config_tests.rs` | Added fork test module for upstream socket refusal in config. | Fork test in the workspace suite. |
| `crates/pa-cli/tests/fork/updates.rs` | Added fork test module: update commands refuse without network requests. | Replacement installer-update test target. |
| `crates/pa-core/src/kernel/manager/startup.rs` | Remove internal role variables at the kernel spawn; keep only the orphan-journal path (PLAN D-26). | Actual session ipython environment inspection; explicit orphan_journal_e2e run; agx_kernel_journal name test. |
| `crates/pa-core/src/session_engine/telemetry/status.rs` | Force release off before env/settings; endpoint None in every build; read the debug persistence assertion from the overlay. | Release-rule and retained debug telemetry tests; overlay tests. |
| `crates/pa-core/src/tools/bash_local.rs` | Remove internal role variables immediately before bash spawn. | Actual BashOperations spawn and session kernel bash-helper environment inspection. |
| `crates/pa-core/tests/abort_kernel_cell.rs` | Discover the fork default kernel venv without adding skips. | Linux kernel integration suites after agx bootstrap (lead-owned). |
| `crates/pa-core/tests/kernel_capture_freshness.rs` | Discover the fork default kernel venv without adding skips. | Linux kernel integration suites after agx bootstrap (lead-owned). |
| `crates/pa-core/tests/kernel_lifecycle.rs` | Discover the fork default kernel venv without adding skips. | Linux kernel integration suites after agx bootstrap (lead-owned). |
| `crates/pa-core/tests/kernel_prewarm.rs` | Discover the fork default kernel venv without adding skips. | Linux kernel integration suites after agx bootstrap (lead-owned). |
| `crates/pa-core/tests/kernel_python_skills_unavailable.rs` | Discover the fork default kernel venv without adding skips. | Linux kernel integration suites after agx bootstrap (lead-owned). |
| `crates/pa-core/tests/kernel_restore_guards.rs` | Discover the fork default kernel venv without adding skips. | Linux kernel integration suites after agx bootstrap (lead-owned). |
| `crates/pa-core/tests/kernel_mcp_settle.rs` | Discover the fork default kernel venv without adding skips. | Linux kernel integration suites after agx bootstrap (lead-owned). |
| `crates/pa-core/tests/kernel_startup_memo.rs` | Discover the fork default kernel venv without adding skips. | Linux kernel integration suites after agx bootstrap (lead-owned). |
| `crates/pa-core/tests/kernel_snapshot_resume.rs` | Discover the fork default kernel venv without adding skips. | Linux kernel integration suites after agx bootstrap (lead-owned). |
| `crates/pa-core/tests/kernel_stop_revive.rs` | Discover the fork default kernel venv without adding skips. | Linux kernel integration suites after agx bootstrap (lead-owned). |
| `crates/pa-core/tests/kernel_teardown.rs` | Discover the fork default kernel venv without adding skips. | Linux kernel integration suites after agx bootstrap (lead-owned). |
| `crates/pa-core/tests/turn_boundary_kernel.rs` | Discover the fork default kernel venv without adding skips. | Linux kernel integration suites after agx bootstrap (lead-owned). |
| `crates/pa-daemon/src/agent_engine/tests/abort.rs` | Discover the fork default kernel venv without adding skips. | Linux kernel integration suites after agx bootstrap (lead-owned). |
| `crates/pa-daemon/src/branch_navigation.rs` | Trace fork tests assert agx's no-marker behavior (FR-016). | pa-daemon trace_fork_tests; pa-core continuous slot tests. |
| `crates/pa-daemon/src/platform/paths.rs` | Separate Unix directory (`socket_dir_for`, including the short-path fallback) and Windows pipe namespaces; retain the upstream real-UID helper. | Fork-namespace real-UID assertion and socket unit tests. |
| `crates/pa-daemon/src/socket.rs` | Refuse upstream sockets before bind, unlink, or stale cleanup. | Socket guard units and live coexistence scenario. |
| `crates/pa-daemon/tests/abort_kernel_e2e.rs` | Discover the fork default kernel venv without adding skips. | Linux kernel integration suites after agx bootstrap (lead-owned). |
| `crates/pa-daemon/tests/agent_family_e2e.rs` | Discover the fork default kernel venv without adding skips. | Linux kernel integration suites after agx bootstrap (lead-owned). |
| `crates/pa-daemon/tests/herdr_pane_e2e.rs` | Discover the fork default kernel venv without adding skips. | Linux kernel integration suites after agx bootstrap (lead-owned). |
| `crates/pa-daemon/tests/idle_passivation_e2e.rs` | Discover the fork default kernel venv without adding skips. | Linux kernel integration suites after agx bootstrap (lead-owned). |
| `crates/pa-daemon/tests/kernel_dispose_e2e.rs` | Discover the fork default kernel venv without adding skips. | Linux kernel integration suites after agx bootstrap (lead-owned). |
| `crates/pa-daemon/tests/mcp_catalog_e2e.rs` | Discover the fork default kernel venv without adding skips. | Linux kernel integration suites after agx bootstrap (lead-owned). |
| `crates/pa-daemon/tests/mcp_product_path_e2e.rs` | Discover the fork default kernel venv without adding skips. | Linux kernel integration suites after agx bootstrap (lead-owned). |
| `crates/pa-daemon/tests/peer_messaging_e2e.rs` | Discover the fork default kernel venv without adding skips. | Linux kernel integration suites after agx bootstrap (lead-owned). |
| `crates/pa-daemon/tests/readoption_wake_e2e.rs` | Discover the fork default kernel venv without adding skips. | Linux kernel integration suites after agx bootstrap (lead-owned). |
| `crates/pa-daemon/tests/replacement_kernel_e2e.rs` | Discover the fork default kernel venv without adding skips. | Linux kernel integration suites after agx bootstrap (lead-owned). |
| `crates/pa-daemon/tests/rlm_children_parent_death_e2e.rs` | Discover the fork default kernel venv without adding skips. | Linux kernel integration suites after agx bootstrap (lead-owned). |
| `crates/pa-daemon/tests/rlm_children_replacement_e2e.rs` | Discover the fork default kernel venv without adding skips. | Linux kernel integration suites after agx bootstrap (lead-owned). |
| `crates/pa-daemon/tests/rlm_quiescence_barrier_e2e.rs` | Discover the fork default kernel venv without adding skips. | Linux kernel integration suites after agx bootstrap (lead-owned). |
| `crates/pa-daemon/tests/steer_boundary_batch_e2e.rs` | Discover the fork default kernel venv without adding skips. | Linux kernel integration suites after agx bootstrap (lead-owned). |
| `crates/pa-tui/src/interactive/run.rs` | Return typed agx update refusal through terminal cleanup before retained prompt soft errors. | Actual TUI update error-exit restores terminal state. |
| `crates/pa-tui/src/session_ui/commands.rs` | Raise the typed update rejection with local install instructions. | TUI update dispatch tests and actual error-exit scenario. |
| `crates/pa-tui/src/session_ui/share.rs` | Report disabled trace sharing before login or upload. | TUI trace dispatch and recording public trace tests. |
| `crates/pa-tui/src/traces.rs` | Expose unsupported trace capability with an upstream-compatible default. | TUI trace tests with carried generic fixtures. |
| `crates/pa-tui/src/update_command.rs` | Expose update unavailability with an upstream-compatible default. | TUI update tests and actual disabled-command exit. |
| `crates/pa-types/Cargo.toml` | Depend on the fork-owned identity helpers. | Locked workspace build. |
| `crates/pa-types/src/lib.rs` | Expose one fork identity helper module to current callers. | Workspace target compilation and helper unit tests. |
| `crates/pa-types/src/platform/transport.rs` | Refuse upstream endpoints at six connect/bind boundaries. | Socket guard tests; native transport fixtures. |
| `scripts/package_release.py` | Add a binary-name option while preserving upstream defaults. | Local packer and atomic installer tests. |
| `crates/pa-core/Cargo.toml` | Use the fork JSON settings crate and register its host-settings tests. | Locked settings tests; workspace clippy/build. |
| `crates/pa-core/src/settings/manager.rs` | Delegate file-backed base/overlay loading, changed-path writes (`save_global` ahead of upstream's field-level write), reload/reopen, and global field persistence; adapt factory write assertion. | AC-008 settings tests; retained memory/project semantics. |
| `crates/pa-core/src/settings/storage.rs` | Add the overlay path constructor; reuse the existing lock/reread and fsync-enabled atomic write unchanged. | AC-008 concurrency; overlay fsync unit test; storage tests. |
| `crates/pa-core/src/settings/merge.rs` | Expose fork RFC 7396 patch operation; retain upstream project deep_merge unchanged. | AC-008 JSON-value and project-null tests. |
| `crates/pa-core/src/settings/mod.rs` | Export the CLI global overlay-storage boundary. | AC-008 real MCP command tests. |
| `crates/pa-cli/src/mcp_command.rs` | Read effective global JSON and adapt the existing mutation callback to changed overlay paths, including inherited removal. | AC-008 add/get/list/replace/remove and malformed refusal. |
| `prime-agent-runtime/src/rlm/factory.py` | Apply the stdlib RFC 7396 overlay before factory.enabled; support a missing base and retain unreadable-base refusal. | AC-028 kernel overlay tests; upstream factory/harness tests. |
| `prime-agent-runtime/src/rlm/harness.py` | `_require_refinements_enabled` applies the `settings-agx.json` overlay before it reads `harnessRefinements`, as `factory_enabled` does (FR-018, FR-043). | test_agx_settings.py `AgxHarnessRefinements`; upstream test_harness.py. |
| `crates/pa-core/src/packages/manager.rs` | Read global-write assertions from the overlay; assert project installs create neither global document. | Package unit tests; unchanged project path. |
| `crates/pa-cli/src/client_settings.rs` | Read persisted client-setting assertions from the overlay without removing any assertions. | Client-settings unit tests. |
| `crates/pa-core/src/refinement/mod.rs` | factory gate reads the agx overlay like the kernel (FR-043) | refinement factory_enabled overlay tests; test_agx_settings.py |
| `crates/pa-core/src/agent_traces/continuous/tests.rs` | Remove the overlay after the consent snapshot instead of the now-read-only base; retain all existing intent/delivery assertions. | settings race trace test; full agent_traces unit check. |
| `crates/pa-cli/tests/print_inline_subagents_e2e.rs` | Use the agx binary in the new inline-subagent verifier; discover the fork default kernel venv. | Inline print e2e; workspace checks. |
| `crates/pa-daemon/tests/orphan_journal_e2e.rs` | Mark the new test supervisor as agx so workers use fork runtime paths; discover the fork default kernel venv. | Orphan journal e2e; workspace checks. |
| `crates/pa-daemon/tests/rlm_child_usage_attribution_e2e.rs` | Mark the new test supervisor as agx so workers use fork runtime paths; discover the fork default kernel venv. | Child usage attribution e2e; workspace checks. |
| `crates/pa-cli/tests/exit_backfill_pty_e2e.rs` | macOS portability; upstream CI is Linux-only. | Native focused terminal checks; Linux baseline comparison (lead-owned). |
