# Upstream sync procedure

This procedure takes upstream Prime Agent changes into agx. It is written for the
owner of the standing sync PR: `pi-agx` until the handoff to `pi-agx-upstream`,
or a person doing the same work. It assumes you can read Rust and use `git` and
`gh`. It does not assume you know how the sync job was designed.

```text
1 sync job runs (nightly when enabled, or manual dispatch)
    checks the last merged sync PR before any GitHub write
    fast-forwards upstream, opens or updates PR "chore: sync upstream main"
    posts agx/sync-gates on the upstream head
        |
2 read the PR and its status
    success ............... go to 5
    failure ............... go to 4 (failed checks)
    failure "conflict" .... go to 3
    format-change label ... also do the format check (2a) before any merge
        |
3 resolve on a sync/<date> branch cut from main, never on upstream
        |
4 local checks, fork CI, known-flake rule
        |
5 USER GO: merge with a merge commit
        |
6 after the merge: FEATURES.md adoption, workflow check, friction notes
```

The mirror branch was called `upstream-main` until the rename decided on 2026-10-14.

## Rules that apply to every sync

- Never commit to `upstream`. It mirrors upstream `main` exactly. A ruleset
  blocks force-pushes and deletion.
- Never use GitHub's "Resolve conflicts" or "Update branch" buttons. They commit
  to `upstream` or rebase the wrong side.
- PRs from `upstream`, `sync/<date>` or a layer branch `sync/<date>-<n>` land
  with a merge commit. `main` must contain upstream's commits, or the next sync
  refuses to write.
- Every other PR lands with a squash merge: one commit, subject from the PR title,
  empty body. The repository allows merge and squash, not rebase merges. GitHub
  cannot enforce the method per PR; check the source before merging.
- PR titles and commit subjects use Conventional Commit form. The standing PR is
  `chore: sync upstream main`. A conflict-resolution PR is
  `chore: merge upstream <short SHA> into main`; its branch's merge commit is
  `chore: merge upstream <short SHA> into sync/<date>`.
- Merging into `main` needs the user's go each time.
- Before you change upstream code to fix an upstream defect, run the upstream-fix
  check: `git fetch origin`, then `git log <base>..origin/upstream -- <files>`,
  then search upstream PRs and issues. If upstream already has a fix, stop and
  report it.

## 1. The sync job

`.github/workflows/agx-sync.yml` runs `scripts/agx/sync.py`. Each run:

1. fetches the fork and upstream, and refuses a diverged mirror;
2. reads every page of closed PRs into `main`, ignores unmerged PRs, and selects
   the most recently merged PR from the mirror or a `sync/<date>` branch;
3. fetches that PR's `refs/pull/<number>/head` and checks that `main` contains it;
   no such PR passes, but an incomplete PR-list read or missing ancestry fails
   before any GitHub write (see [recovery](#recover-a-squashed-sync));
4. fast-forwards `upstream` to upstream `main` with `AGX_SYNC_TOKEN`;
5. opens the PR "chore: sync upstream main" (`upstream` into `main`), or reuses
   the open one;
6. adds the `format-change` label and a comment when format-sensitive paths
   changed;
7. checks for a merge conflict and posts `agx/sync-gates` `failure` `conflict`, or
   runs the fork CI on `main` merged with the upstream head and posts `success` or
   `failure`;
8. disables every enabled workflow whose file is not `.github/workflows/agx-*.yml`.

Only the pushing job uses Environment `agx-sync`. Only the mirror push receives
`AGX_SYNC_TOKEN`; every other GitHub write uses `GITHUB_TOKEN`. The workflow
grants `GITHUB_TOKEN` `contents: read`, not `write`. The status job runs only
after successful preparation, so an ancestry refusal cannot post a status.

A run with nothing new makes no push, PR, label or status change. It still
disables any enabled workflow that is not `agx-*`.

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
gh pr list -R peterkc-io/agx --head upstream
gh api repos/peterkc-io/agx/commits/<upstream head>/statuses \
  --jq '[.[] | select(.context == "agx/sync-gates") | {state, description}]'
```

Fetch first (`git fetch origin`), then read the upstream commits the PR brings in
(`git log origin/main..origin/upstream`).
Look for changes to files listed in [SEAMS.md](SEAMS.md) and for upstream work
that may cover an agx feature in [FEATURES.md](FEATURES.md).

### 2a. Format-change check

The `format-change` label means upstream changed code that reads or writes the
shared `~/.prime/agent` store: sessions, settings, auth, custom models, MCP
connections or the kernel harness. agx and `prime-agent` share that store, so a
format change can make one program misread data the other wrote.

When the label is set, hold the merge and test both programs on a copy:

1. Build `agx` from the sync result and `prime-agent` from `origin/upstream`.
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
git merge --no-ff -m "chore: merge upstream <short SHA> into sync/<YYYY-MM-DD>" origin/upstream
```

Resolve each conflict inside the seam that [SEAMS.md](SEAMS.md) lists for that
file. Keep each seam to about 30 changed lines. Stop and ask when a conflict needs
a change outside a listed seam.

**Cargo.lock:** take upstream's file, then let Cargo make the smallest update
needed by the fork.

```sh
git checkout origin/upstream -- Cargo.lock
cargo metadata --format-version 1 > /dev/null   # online; never --offline
git diff origin/upstream -- Cargo.lock
```

Review the diff: keep only the smallest fork-required update. Never run
`cargo generate-lockfile` or `cargo update`, and never bump registry versions.
If registry versions change, stop.

**New upstream test files** may need a fork change only of these kinds (7 and 8 approved on 2026-10-16):

1. the binary name, for example `CARGO_BIN_EXE_agx`;
2. `cfg(target_os = "linux")` on a test that expects Linux;
3. `AGX_PROCESS=1` on a test supervisor;
4. the settings path `settings-agx.json` in a test;
5. the ioctl cast `libc::c_ulong::from(libc::TIOCSCTTY)`;
6. the kernel venv path `kernel-venv-agx` in a test's interpreter discovery;
7. `AGX_PROCESS=1` on a test's CLI invocation that passes `PRIME_AGENT_DAEMON_SOCKET`
   or another variable agx clears at startup, after scrubbing unrelated startup-cleared
   and `PRIME_AGENT_INTERNAL_*` variables;
8. an `agx-<uid>` socket dir in place of a `prime-agent-<uid>` dir in a test fixture.

Any other change to a new upstream test file needs the user's decision. Search
new test files for `kernel-venv/`: a test that cannot find its interpreter often
returns early and still reports "passed".

**SEAMS.md:** add, change or remove rows so the ledger matches the result.
Every changed file outside the fork-owned paths needs a row. In its Reason cell,
name the touched function or item and the reason. Remove rows for unchanged files.
Then run:

```sh
python3 scripts/agx/check_seams.py --base origin/upstream
```

Commit the resolved merge with
`git commit -m "chore: merge upstream <short SHA> into sync/<date>"`
(signed, hooks on). Push the branch and open a PR into `main` titled
`chore: merge upstream <short SHA> into main`; the fork CI runs on PRs into
`main`. The PR text names the upstream head it takes in.

### 3a. Build a stacked sync

The nightly sync job stays unchanged. It keeps the standing PR from `upstream`,
its label and its `agx/sync-gates` status. A one-layer sync with no conflict may
still land as the standing PR.

For a larger sync, build plain stacked PRs. Each layer contains upstream merge
commits, and each layer must pass CI on its own.

```text
1 estimate cuts -> 2 build layers -> 3 count final files before pushing
                                           |
4 open stacked PRs -> 5 USER GO for each merge, bottom-up
                                           |
6 preserve history -> 7 compare the top layer with the upstream baseline
```

1. Run the layer helper:

   ```sh
   python3 scripts/agx/sync_layers.py --base origin/main --head origin/upstream
   ```

   It reads Git only. It makes no network call and changes no ref. Its counts
   are upstream-only estimates, not final PR counts. They exclude `*.lock` and
   count a rename as two paths. Each cut is the farthest first-parent commit
   that fits within 140 files, even if an earlier commit exceeds 140. If no
   later cut fits, the next commit forms its own layer, marked `over limit`.
   Conflict resolutions and fork fixes are not included in these estimates.

2. Cut `sync/<date>-1` from `main`. Cut each later `sync/<date>-<n>` from the
   layer below it. Merge the helper's cut commit with `git merge --no-ff` and
   title the merge commit
   `chore: merge upstream <short SHA> into sync/<date>-<n>`.
   Resolve conflicts and apply fork fixes in the first layer that needs them.
   Follow the conflict and seam rules above. Each layer must pass CI on its own.
   The seam check uses the newest upstream commit that the layer contains:

   ```sh
   python3 scripts/agx/check_seams.py --upstream origin/upstream
   ```

3. Before pushing a layer, count its final reviewable files. Use the three-dot
   comparison that GitHub shows, against the layer below it (`main` for layer 1):

   ```sh
   python3 - '<layer below>...<layer head>' <<'EOF'
   import subprocess, sys
   paths = subprocess.run(
       ["git", "diff", "--name-only", "--no-renames", "-z", sys.argv[1]],
       check=True, stdout=subprocess.PIPE,
   ).stdout.split(b"\0")
   print(sum(1 for path in paths if path and not path.endswith(b".lock")))
   EOF
   ```

   A wrong ref makes `git diff` fail, and the command then stops with an error
   instead of printing a count.

   If the count exceeds 150 and the layer holds more than one upstream commit,
   rebuild it from an earlier cut before anything is pushed. If the layer holds
   one upstream commit and exceeds 150, stop before pushing and ask the user to
   choose cubic-only review or a changed layer. This stop applies whether or not
   the helper marked the layer `over limit`. For cubic-only review, the PR must
   say that CodeRabbit cannot review it.

4. Open PR n with base layer n-1. Layer 1 has base `main`. Use the title
   `chore: merge upstream <short SHA> into main (layer <n> of <m>)`.

5. Land the layers bottom-up, one at a time, with a merge commit and the user's
   go for each merge. Use `gh pr merge <number> -R peterkc-io/agx --merge`, never
   squash. The repository deletes each merged branch, and GitHub moves the next
   PR's base to `main`. That base change starts a new `agx-ci` run. Before each merge,
   check that the PR's base is now `main` and that `agx-ci` passed on its current
   merge candidate. A title or body edit also starts an `agx-ci` run, but its
   `make check` job is skipped. The checks list shows it as skipped, yet GitHub
   counts a skipped job as passing for required checks and merging. A base change
   keeps the same head SHA, so an older run on the old base can also look like a
   pass. Use only a run that started after the lower layer merged and whose
   `make check` job ran:

   ```sh
   gh run list -R peterkc-io/agx --workflow agx-ci.yml --branch <layer branch> \
     --json databaseId,headSha,createdAt,conclusion
   gh run view <run id> -R peterkc-io/agx --json jobs
   ```

   Its `createdAt` must be later than the lower layer's merge time, and its
   `make check` job must not be skipped. If no such run exists, ask the user
   before you close and reopen the PR. Reopening sends the `reopened` event,
   which starts a run.
   Read whether CodeRabbit reviewed the PR or reported it skipped. Record a skip;
   do not retry it.

6. Never rebase, squash or use "Update branch" on a layer. Do not use
   `gh stack rebase` or `gh stack sync`. These operations rewrite the history
   that the next sync needs. If a layer was squashed by mistake, stop and follow
   [Recover a squashed sync](#recover-a-squashed-sync). Never reset `main`.

7. Compare the ignored-test set with the upstream baseline once, for the top
   layer. Its tree holds the whole upstream head. Follow the baseline procedure
   in [Checks](#4-checks).

### Recover a squashed sync

If preparation says `main` does not contain a merged sync PR's head, stop normal
sync work. Do not bypass the check. It may mean a sync PR was squash-merged.
Confirm the named PR and get the user's go for recovery. If the closed-PR list
could not be read completely, fix that read failure and rerun preparation;
do not guess which PR was latest.

With the user's go, create a new `sync/<date>` branch from the current `main`.
Fetch the offending PR's head, not the current mirror head: GitHub retains the
PR ref even if its source branch is gone.

```sh
git fetch origin
git switch -c sync/<YYYY-MM-DD> origin/main
git fetch --no-tags origin refs/pull/<number>/head
git merge --no-ff -m "chore: merge upstream <short SHA> into sync/<YYYY-MM-DD>" FETCH_HEAD
```

If no later fork PR changed the same lines, this merge has no conflicts.
Otherwise follow the conflict procedure above and keep the later fork changes.
Stop for the user's decision if a conflict is unclear. Never reset `main`,
force-push it or overwrite a fork change.

Run the checks and land this as a sync PR with a merge commit and the sync title
above, with the user's go. Recovery is complete only when the next sync run
passes the ancestry check and reports the checked PR and that `main` contains
its head.

## 4. Checks

**Local (macOS).** Run checks under `env -i` with a fixed `PATH`, `TZ=UTC`,
`TMPDIR=/private/tmp` and a private temporary `HOME`. Keep the installed Rust
toolchain: pass `CARGO_HOME` and `RUSTUP_HOME` from your real home and put the
Cargo `bin` directory on `PATH`. For example:

```sh
CHECK_HOME=$(mktemp -d /private/tmp/agx-check.XXXX)
RUST_CARGO_HOME="${CARGO_HOME:-$HOME/.cargo}"
RUST_RUSTUP_HOME="${RUSTUP_HOME:-$HOME/.rustup}"
env -i HOME="$CHECK_HOME" CARGO_HOME="$RUST_CARGO_HOME" RUSTUP_HOME="$RUST_RUSTUP_HOME" \
  PATH="$RUST_CARGO_HOME/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin" \
  TZ=UTC TMPDIR=/private/tmp cargo test --locked -p <changed-crate> --lib
```

Use that environment for each command. Remove the private home after the checks.
Use `--locked` on Cargo commands that accept it. Limit each crate run to 900
seconds and each single test to 300 seconds; a timeout is a failure, not a flake
or a pass.

- `cargo fmt --all --check`
- `cargo clippy --locked --workspace --all-targets -- -D warnings`
- `cargo build --locked --release --workspace`
- unit tests of the changed crates and the fork's own tests
- the scenario checks for the changed fork behavior, using temporary state,
  never the real shared store
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
`.github/workflows/agx-ci.yml` and `scripts/agx/rerun_failed.py` from the current
`main` on top of the recorded upstream SHA, and push it as a
`wip/agx-upstream-<sha>` branch. The old `agx/ci` template is retired.
The seam step skips only branch runs named `wip/agx-upstream-*`, for both push
and manual dispatch. It still runs on normal fork branches, `main`, PR merge
refs and tags, including a tag named `wip/agx-upstream-x`.
Keep the baseline branch to the recorded upstream SHA plus those two CI files;
a green run is baseline evidence for that SHA only.
The ignored tests must match; every other test must pass, except a known flake.
Delete the `wip/**` branch after the comparison; its run log stays on GitHub.

### Known-flake rule

When an upstream test whose code agx does not change fails, run it alone 20 times.
At least 15 passes records it as a known flake; it does not block the sync.
Formatting, Clippy and the release build must still pass, and the test run must
complete. More than 5 failures, a test in code agx changes, or a different
failure text stops the sync for a decision.

The CI helper `scripts/agx/rerun_failed.py` finds failed tests even when result
lines start with ANSI CSI sequences, including `ESC[>4;0m` and `ESC[?25l`.
It reports rerun counts but leaves the job failed; apply the rule above.
If a failed run yields no failed test, inspect the log and rerun the affected
tests by hand; missing rerun evidence is not a pass.

Current known flakes:

- pa-core
  `session_engine::request_timing::payload::tests::concurrent_producers_drop_at_the_reserve_when_the_queue_is_full`:
  22 of 24 passes alone; seen on macOS.
- pa-cli `suspend_signal_e2e` `ctrl_g_hands_the_terminal_to_the_external_editor`:
  PTY timeout; 20 of 20 passes alone.
- pa-cli `clipboard_auth_commands_e2e` `tui_traces_upload_all_sweeps_with_live_progress`:
  supervisor connect refused during setup; 20 of 20 passes alone.
- pa-daemon `stop_escalation_e2e`
  `a_hung_worker_is_killed_within_the_escalation_window_and_its_lease_frees`:
  the routed kill to a stopped worker was answered with success instead of a
  timeout; 20 of 20 passes alone (Linux CI, 2026-10-15).

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
   code covers, read the upstream code, not only the PR title. Full adoption:
   remove the fork's copy and its table row in this sync, then record the retired
   feature ID, upstream PR and version in prose in `FEATURES.md` (as for AGX-014).
   Partial adoption: keep the row and say what remains.
2. **Workflows.** Only `agx-*` workflows may be enabled:

   ```sh
   gh workflow list -R peterkc-io/agx --all
   gh run list -R peterkc-io/agx --branch upstream
   ```

   A new upstream workflow can run once on the `upstream` push before the job
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
