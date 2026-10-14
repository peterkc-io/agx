# Upstream sync procedure

This procedure takes upstream Prime Agent changes into agx. It is written for the
owner of the standing sync PR: `pi-agx` until the handoff to `pi-agx-upstream`,
or a person doing the same work. It assumes you can read Rust and use `git` and
`gh`. It does not assume you know how the sync job was designed.

```text
1 sync job runs (nightly when enabled, or manual dispatch)
    fast-forwards upstream-main, opens or updates PR "Sync upstream main"
    posts agx/sync-gates on the upstream head
        |
2 read the PR and its status
    success ............... go to 5
    failure ............... go to 4 (failed checks)
    failure "conflict" .... go to 3
    format-change label ... also do the format check (2a) before any merge
        |
3 resolve on a sync/<date> branch cut from main, never on upstream-main
        |
4 local checks, fork CI, known-flake rule
        |
5 USER GO: merge with a merge commit
        |
6 after the merge: FEATURES.md adoption, workflow check, friction notes
```

## Rules that apply to every sync

- Never commit to `upstream-main`. It mirrors upstream `main` exactly. A ruleset
  blocks force-pushes and deletion.
- Never use GitHub's "Resolve conflicts" or "Update branch" buttons. They commit
  to `upstream-main` or rebase the wrong side.
- Land every sync with a merge commit. The repository allows only merge commits.
  `main` must contain upstream's commits, or the next fast-forward and ancestry
  checks fail.
- Merging into `main` needs the user's go each time.
- Before you change upstream code to fix an upstream defect, run the upstream-fix
  check: `git log <base>..upstream/main -- <files>`, then search upstream PRs and
  issues. If upstream already has a fix, stop and report it.

## 1. The sync job

`.github/workflows/agx-sync.yml` runs `scripts/agx/sync.py`. Each run:

1. fetches the fork and upstream;
2. fast-forwards `upstream-main` to upstream `main` with `AGX_SYNC_TOKEN`;
3. opens the PR "Sync upstream main" (`upstream-main` into `main`), or reuses the
   open one;
4. adds the `format-change` label and a comment when format-sensitive paths
   changed;
5. checks for a merge conflict and posts `agx/sync-gates` `failure` `conflict`, or
   runs the fork CI on `main` merged with the upstream head and posts `success` or
   `failure`;
6. disables every enabled workflow whose file is not `.github/workflows/agx-*.yml`.

A run with nothing new changes nothing.

Start a run by hand:

```sh
gh workflow run agx-sync.yml -R peterkc-io/agx --ref main
```

A scheduled run does nothing unless the repository variable `AGX_SYNC_SCHEDULE`
is exactly `on` (see [Schedule](#schedule)).

If the job fails with an error that names `AGX_SYNC_TOKEN`, it made no PR change
and posted no status. See [Rotate the token](#rotate-agx_sync_token).

## 2. Review the standing PR

```sh
gh pr list -R peterkc-io/agx --head upstream-main
gh api repos/peterkc-io/agx/commits/<upstream head>/statuses \
  --jq '[.[] | select(.context == "agx/sync-gates") | {state, description}]'
```

Read the upstream commits the PR brings in (`git log origin/main..origin/upstream-main`).
Look for changes to files listed in [SEAMS.md](SEAMS.md) and for upstream work
that may cover an agx feature in [FEATURES.md](FEATURES.md).

### 2a. Format-change check

The `format-change` label means upstream changed code that reads or writes the
shared `~/.prime/agent` store: sessions, settings, auth, custom models, MCP
connections or the kernel harness. agx and `prime-agent` share that store, so a
format change can make one program misread data the other wrote.

When the label is set, hold the merge and test both programs on a copy:

1. Build `agx` from the sync result and `prime-agent` from `origin/upstream-main`.
2. Copy the store to a temporary home. The copy holds credentials: keep it on
   this machine and delete it afterwards.

   ```sh
   T=$(mktemp -d /private/tmp/agx-format.XXXX)
   mkdir -p "$T/.prime"
   cp -R ~/.prime/agent "$T/.prime/agent"
   ```

3. With `HOME=$T`, start a session with each program, then list and resume the
   session the other program wrote. Change one global setting with each program
   and read it back with the other.
4. Merge only when both programs read each other's sessions and settings. If not,
   stop and report the format change to the user.

Never point a test at the real `~/.prime/agent`.

## 3. Resolve conflicts on a sync branch

```sh
git fetch origin
git switch -c sync/<YYYY-MM-DD> origin/main
git merge --no-ff origin/upstream-main
```

Resolve each conflict inside the seam that [SEAMS.md](SEAMS.md) lists for that
file. Keep each seam to about 30 changed lines. Stop and ask when a conflict needs
a change outside a listed seam.

**Cargo.lock:** take upstream's file, then let Cargo add only the fork crates.

```sh
git checkout origin/upstream-main -- Cargo.lock
cargo metadata --format-version 1 > /dev/null   # online; never --offline
git diff origin/upstream-main -- Cargo.lock
```

The diff must show only agx crate entries (about 8 lines). Never run
`cargo generate-lockfile` or `cargo update`. If registry versions change, stop.

**New upstream files** may need a fork change only of these kinds:

1. the binary name, for example `CARGO_BIN_EXE_agx`;
2. a Linux-only `cfg(target_os = "linux")` guard;
3. `AGX_PROCESS=1` on a test supervisor;
4. the settings path `settings-agx.json` in a test;
5. the ioctl cast `libc::c_ulong::from(libc::TIOCSCTTY)`;
6. the kernel venv path `kernel-venv-agx` in a test's interpreter discovery.

Any other change to a new upstream file needs the user's decision. Search new test
files for `kernel-venv/`: a test that cannot find its interpreter often returns
early and still reports "passed".

**SEAMS.md:** add, change or remove rows so the ledger matches the result, then:

```sh
python3 scripts/agx/check_seams.py --base origin/upstream-main
```

Commit the merge with `git commit` (signed, hooks on). Push the branch and open a
PR into `main`; the fork CI runs on PRs into `main`. The PR text names the
upstream head it takes in.

## 4. Checks

**Local (macOS).** Run with `env -i`, `TZ=UTC`, `TMPDIR=/private/tmp` and a
temporary `HOME`, with `--locked`, and stop any run that exceeds 900 seconds per
crate or 300 seconds per single test:

- `cargo fmt --all --check`
- `cargo clippy --workspace --all-targets -- -D warnings`
- `cargo build --release`
- unit tests of the changed crates and the fork's own tests
- `python3 -I -B -m unittest discover -s scripts/agx -p 'test_*.py'`

These tests fail on macOS hosts and pass on Linux; Linux CI decides them:

- pa-tui: `agents_view::tests::reply::the_reply_hints_follow_the_target_state`,
  `hotkeys::tests::guide_renders_default_keys`,
  `hotkeys::tests::guide_renders_disabled_binding_with_empty_key_cell`,
  `hotkeys::tests::guide_renders_user_overrides`,
  `keybindings::tests::formats_key_text`,
  `model_picker::tests::scope_toggles_between_the_scoped_list_and_the_catalog`,
  `provider_auth::tests::the_api_key_prompt_renders_the_ts_login_dialog_frame`,
  `session_ui::stream::streaming_tray_hint_tests::the_hint_names_the_follow_up_key_over_a_draft`
- pa-types: `platform::transport::tests::over_limit_paths_bind_connect_and_land_in_place`,
  `platform::transport::tests::paths_at_the_limit_bind_directly`
- pa-core: `refinement::tests::concurrent_update_harness_state_writes_all_land`;
  `kernel_startup_memo` `dispose_after_a_kill_waits_the_doomed_boot`
- `interactive_daemon_e2e` reads `/proc` and runs only on Linux.

**Fork CI (Linux).** Compare the sync PR's run with a baseline run on the same
upstream head without fork changes. To make one, commit only
`.github/workflows/agx-ci.yml` and `scripts/agx/rerun_failed.py` from `main` on
top of `origin/upstream-main` and push it as a `wip/agx-upstream-<sha>` branch.
The ignored tests must match; every other test must pass, except a known flake.
Delete the `wip/**` branch after the comparison; its run log stays on GitHub.

### Known-flake rule

When an upstream test whose code agx does not change fails, run it alone 20 times.
At least 15 passes records it as a known flake; it does not block the sync.
Formatting, Clippy and the release build must still pass, and the test run must
complete. More than 5 failures, a test in code agx changes, or a different
failure text stops the sync for a decision.

The CI helper `scripts/agx/rerun_failed.py` misses failed tests whose result line
starts with the escape sequence `ESC[>4;0m`. When it reports no failed test after
a failure, rerun those tests by hand.

Current known flakes:

- pa-core
  `session_engine::request_timing::payload::tests::concurrent_producers_drop_at_the_reserve_when_the_queue_is_full`:
  22 of 24 passes alone; seen on macOS.
- pa-cli `suspend_signal_e2e` `ctrl_g_hands_the_terminal_to_the_external_editor`:
  PTY timeout; 20 of 20 passes alone.
- pa-cli `clipboard_auth_commands_e2e` `tui_traces_upload_all_sweeps_with_live_progress`:
  supervisor connect refused during setup; 20 of 20 passes alone.

Add an entry when a test qualifies. Remove it when upstream fixes the test.

## 5. Merge

With the user's go, merge the PR with a merge commit:

```sh
gh pr merge <number> -R peterkc-io/agx --merge
```

When `main` contains the upstream head, GitHub marks the standing PR merged. If it
stays open, close it with a comment that names the sync PR.

## 6. After the merge

1. **Feature list.** For each [FEATURES.md](FEATURES.md) row that the new upstream
   code covers, read the upstream code, not only the PR title. Full adoption: name
   the upstream PR and commit or version, and remove the fork's copy. Partial
   adoption: keep the row and say what remains.
2. **Workflows.** Only `agx-*` workflows may be enabled:

   ```sh
   gh workflow list -R peterkc-io/agx --all
   gh run list -R peterkc-io/agx --branch upstream-main
   ```

   A new upstream workflow can run once on the `upstream-main` push before the job
   disables it. Read the permissions of any new upstream workflow. Disabling a
   workflow by hand needs the user's go:
   `gh workflow disable <file> -R peterkc-io/agx`.
3. **Friction.** Record what was unclear or slow in this procedure in Beads issue
   `pi-rgbi.3`, then fix this file.

## Schedule

The nightly run is off until the user grants it. With the user's grant:

```sh
gh variable set AGX_SYNC_SCHEDULE --body on -R peterkc-io/agx
```

To stop the nightly run:

```sh
gh variable delete AGX_SYNC_SCHEDULE -R peterkc-io/agx
```

Record each grant or revocation in Beads issue `pi-rgbi.3`.

## Rotate AGX_SYNC_TOKEN

The token expires after 90 days. Replace it before then. Only the user handles
the token; agents never read, print or store its value.

1. Create a fine-grained token: resource owner `peterkc-io` (not the personal
   account), only the repository `peterkc-io/agx`, Contents and Workflows "Read
   and write", 90 days.
2. Store it in the environment, not as a repository secret:

   ```sh
   gh secret set AGX_SYNC_TOKEN --env agx-sync -R peterkc-io/agx
   ```

3. Dispatch one run (needs the user's go) and confirm the job passes its push step.
4. Delete the old token.

A token whose resource owner is the personal account fails the push with
`Permission to peterkc-io/agx.git denied`.
