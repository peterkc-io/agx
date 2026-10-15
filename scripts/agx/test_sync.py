"""Local Git and fake-GitHub rejection tests for the fork sync job."""

import base64
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


SCRIPT = Path(__file__).with_name("sync.py").resolve()
# Distinct fake values, never real tokens.
SYNC_TOKEN = "fake-agx-sync-token-1111"
GITHUB_TOKEN = "fake-github-token-2222"
REAL_GIT = shutil.which("git")
FAKE_GH = r"""#!/usr/bin/env python3
import json
import os
from pathlib import Path
import sys
from urllib.parse import parse_qs, urlsplit

with open(os.environ["CREDENTIAL_LOG"], "a") as stream:
    stream.write(json.dumps({
        "tool": "gh", "args": sys.argv[1:],
        "credential": os.environ.get("GH_TOKEN"),
        "sync_env": "AGX_SYNC_TOKEN" in os.environ,
    }) + "\n")
path = Path(os.environ["FAKE_GH_STATE"])
state = json.loads(path.read_text())
args = sys.argv[1:]
assert args[0] == "api", args
method = args[args.index("--method") + 1]
endpoint = args[args.index("--method") + 2]
payload = json.load(sys.stdin) if "--input" in args else None
state["calls"].append({
    "args": args, "method": method, "endpoint": endpoint, "payload": payload,
})
url = urlsplit(endpoint)
route = url.path.split("/", 3)[3]
query = parse_qs(url.query)
result = None
if method == "GET":
    if route == "pulls" and query["state"] == ["closed"]:
        if state.get("closed_pr_read_failure"):
            path.write_text(json.dumps(state))
            print("closed PR list read failed on page 2", file=sys.stderr)
            sys.exit(1)
        assert "--paginate" in args and "--slurp" in args
        path.write_text(json.dumps(state))
        print(json.dumps(state.get("closed_pr_pages", [[]])))
        sys.exit(0)
    if route == "pulls":
        result = [
            pr for pr in state["prs"] if pr["state"] == query["state"][0]
            and pr["base"] == query["base"][0]
            and pr["head"] == query["head"][0]
        ]
    elif route == "labels":
        result = state["labels"]
    elif route.startswith("commits/") and route.endswith("/statuses"):
        result = state["statuses"].get(route.split("/")[1], [])
    elif route.startswith("issues/") and route.endswith("/comments"):
        result = state["comments"]
    elif route == "actions/workflows":
        result = {"workflows": state["workflows"]}
    else:
        raise AssertionError(route)
    if "--slurp" in args:
        result = [result]
elif route == "pulls":
    result = {
        **payload, "head": "tester:upstream",
        "number": len(state["prs"]) + 1, "state": "open", "labels": [],
    }
    state["prs"].append(result)
elif route == "labels":
    assert not any(
        label["name"] == payload["name"] for label in state["labels"]
    )
    result = payload
    state["labels"].append(result)
elif route.endswith("/labels"):
    result = [{"name": name} for name in payload["labels"]]
    state["prs"][0]["labels"].extend(result)
elif route.endswith("/comments"):
    result = {"id": len(state["comments"]) + 1, **payload}
    state["comments"].append(result)
elif route.startswith("issues/comments/"):
    result = next(
        comment for comment in state["comments"]
        if comment["id"] == int(route.split("/")[2])
    )
    result.update(payload)
elif route.startswith("statuses/"):
    state["statuses"].setdefault(route.split("/")[1], []).insert(0, payload)
    result = payload
elif route.endswith("/disable"):
    assert method == "PUT"
    workflow = next(
        workflow for workflow in state["workflows"]
        if workflow["id"] == int(route.split("/")[2])
    )
    assert workflow["state"] == "active"
    workflow["state"] = "disabled_manually"
else:
    raise AssertionError((method, route))
path.write_text(json.dumps(state))
if result is not None:
    print(json.dumps(result))
"""
FAKE_GIT = r"""#!/usr/bin/env python3
import base64
import json
import os
import subprocess
import sys
with open(os.environ["GIT_CALLS"], "a") as stream:
    stream.write(json.dumps(sys.argv[1:]) + "\n")
credential = None
for value in os.environ.values():
    if value.startswith("AUTHORIZATION: basic "):
        credential = base64.b64decode(value.split()[-1]).decode()
        credential = credential.removeprefix("x-access-token:")
with open(os.environ["CREDENTIAL_LOG"], "a") as stream:
    stream.write(json.dumps({
        "tool": "git", "args": sys.argv[1:], "credential": credential,
        "github_env": "GH_TOKEN" in os.environ,
        "sync_env": "AGX_SYNC_TOKEN" in os.environ,
    }) + "\n")
sys.exit(subprocess.run([os.environ["REAL_GIT"], *sys.argv[1:]]).returncode)
"""


class SyncTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.upstream = self.root / "upstream.git"
        self.fork = self.root / "fork.git"
        self.seed = self.root / "seed"
        self.checkout = self.root / "checkout"
        self.state_path = self.root / "gh-state.json"
        self.git_calls = self.root / "git-calls.jsonl"
        self.credential_log = self.root / "credentials.jsonl"
        self.home = self.root / "home"
        self.home.mkdir()
        self.output_path = self.root / "outputs"
        self.git(self.root, "init", "--bare", str(self.upstream))
        self.git(self.root, "init", "--bare", str(self.fork))
        self.git(self.root, "init", "-b", "main", str(self.seed))
        self.git(self.seed, "config", "user.name", "Sync test")
        self.git(self.seed, "config", "user.email", "test@example.invalid")
        self.base = self.commit("conflict.txt", "base\n")
        self.git(self.seed, "push", str(self.upstream), "HEAD:main")
        self.git(self.seed, "push", str(self.fork),
                 "HEAD:main", "HEAD:upstream")
        self.git(self.root, "clone", "--branch", "main",
                 str(self.fork), str(self.checkout))
        self.bin = self.root / "bin"
        self.bin.mkdir()
        for name, code in (("gh", FAKE_GH), ("git", FAKE_GIT)):
            executable = self.bin / name
            executable.write_text(code)
            executable.chmod(0o755)
        self.save_state({
            "prs": [], "labels": [], "comments": [], "statuses": {},
            "workflows": [], "calls": [],
        })
        excluded_env = {
            "GITHUB_EVENT_NAME", "AGX_SYNC_SCHEDULE",
            "GH_TOKEN", "GITHUB_TOKEN", "AGX_SYNC_TOKEN",
        }
        self.env = {
            key: value for key, value in os.environ.items()
            if key not in excluded_env
        }
        self.env.update(
            PATH=f"{self.bin}{os.pathsep}{os.environ['PATH']}",
            REAL_GIT=REAL_GIT, GIT_CALLS=str(self.git_calls),
            CREDENTIAL_LOG=str(self.credential_log), HOME=str(self.home),
            AGX_SYNC_TOKEN=SYNC_TOKEN, GH_TOKEN=GITHUB_TOKEN,
            FAKE_GH_STATE=str(self.state_path),
            GITHUB_OUTPUT=str(self.output_path),
        )

    def git(self, cwd, *args):
        result = subprocess.run(
            [REAL_GIT, *args], cwd=cwd, capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout.strip()

    def commit(self, path, text):
        target = self.seed / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)
        self.git(self.seed, "add", path)
        self.git(self.seed, "commit", "-m", "test change")
        return self.git(self.seed, "rev-parse", "HEAD")

    def upstream_change(self, path="upstream.txt", text="upstream\n"):
        head = self.commit(path, text)
        self.git(self.seed, "push", str(self.upstream), "HEAD:main")
        return head

    def state(self):
        return json.loads(self.state_path.read_text())

    def save_state(self, state):
        self.state_path.write_text(json.dumps(state))

    def writes(self):
        return [
            call for call in self.state()["calls"] if call["method"] != "GET"
        ]

    def pushes(self):
        if not self.git_calls.exists():
            return []
        return [args for line in self.git_calls.read_text().splitlines()
                if (args := json.loads(line))[0] == "push"]

    def sync(self, *args, env=None, success=True):
        self.output_path.write_text("")
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "--repo", "tester/agx",
             "--upstream", str(self.upstream), *args],
            cwd=self.checkout, env=self.env | (env or {}),
            capture_output=True, text=True,
        )
        if success:
            self.assertEqual(result.returncode, 0, result.stderr)
        return result

    def assert_credentials_separated(self):
        """Only the upstream push gets AGX_SYNC_TOKEN (FR-044)."""
        records = [json.loads(line)
                   for line in self.credential_log.read_text().splitlines()]
        for record in records:
            with self.subTest(call=record["args"][:2]):
                self.assertFalse(record["sync_env"])
                if record["tool"] == "gh":
                    self.assertEqual(record["credential"], GITHUB_TOKEN)
                elif record["args"][0] == "push":
                    self.assertEqual(record["credential"], SYNC_TOKEN)
                    self.assertFalse(record["github_env"])
                else:
                    self.assertIsNone(record["credential"])
        return records

    def assert_not_disclosed(self, result):
        """Neither token is in output or any saved Git config or file."""
        secrets = [SYNC_TOKEN, GITHUB_TOKEN, base64.b64encode(
            f"x-access-token:{SYNC_TOKEN}".encode()).decode()]
        for secret in secrets:
            self.assertNotIn(secret, result.stdout + result.stderr)
        for top in (self.fork, self.upstream, self.checkout, self.home):
            for path in top.rglob("*"):
                if path.is_file():
                    data = path.read_bytes()
                    for secret in secrets:
                        self.assertNotIn(secret.encode(), data, path)

    def outputs(self):
        return dict(
            line.split("=", 1)
            for line in self.output_path.read_text().splitlines()
        )

    def open_pr(self):
        return {
            "number": 7, "state": "open", "base": "main",
            "head": "tester:upstream", "labels": [],
        }

    def test_behind_fast_forwards_once(self):
        head = self.upstream_change()
        result = self.sync()
        self.assert_not_disclosed(result)
        self.assertEqual(
            self.git(self.fork, "rev-parse", "upstream"), head,
        )
        self.assertEqual(self.pushes(), [[
            "push", "--no-follow-tags", "origin",
            f"{head}:refs/heads/upstream",
        ]])
        self.assertEqual(len(self.state()["prs"]), 1)
        self.assertEqual(
            self.state()["prs"][0]["title"], "chore: sync upstream main",
        )
        self.assertIn("merge commit", self.state()["prs"][0]["body"])
        self.assertEqual(self.outputs(), {"head": head, "run-gates": "true"})
        records = self.assert_credentials_separated()
        self.assertTrue(any(r["tool"] == "gh" for r in records))
        self.assertEqual(
            [r["args"] for r in records if r["credential"] == SYNC_TOKEN],
            self.pushes(),
        )
        self.assertNotIn(SYNC_TOKEN, self.git_calls.read_text())

    def test_missing_token_fails_before_any_write(self):
        self.upstream_change()
        for value in (None, ""):
            with self.subTest(token=value):
                env = dict(self.env)
                if value is None:
                    del env["AGX_SYNC_TOKEN"]
                else:
                    env["AGX_SYNC_TOKEN"] = value
                self.output_path.write_text("")
                result = subprocess.run(
                    [sys.executable, str(SCRIPT), "--repo", "tester/agx",
                     "--upstream", str(self.upstream)],
                    cwd=self.checkout, env=env,
                    capture_output=True, text=True,
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("AGX_SYNC_TOKEN", result.stderr)
                self.assertEqual(self.pushes(), [])
                self.assertEqual(self.writes(), [])

    def test_rejected_push_makes_no_pr_or_status(self):
        self.upstream_change()
        state = self.state()
        state["workflows"] = [{
            "id": 1, "path": ".github/workflows/ci.yml", "state": "active",
        }]
        self.save_state(state)
        hook = self.fork / "hooks" / "pre-receive"
        hook.write_text("#!/bin/sh\necho rejected by test >&2\nexit 1\n")
        hook.chmod(0o755)
        result = self.sync(success=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("AGX_SYNC_TOKEN", result.stderr)
        self.assertEqual(len(self.pushes()), 1)
        self.assertEqual(
            self.git(self.fork, "rev-parse", "upstream"), self.base,
        )
        self.assertEqual(self.state()["prs"], [])
        self.assertEqual(self.state()["statuses"], {})
        self.assertEqual([
            call for call in self.writes()
            if not call["endpoint"].endswith("/disable")
        ], [])
        self.assert_credentials_separated()
        self.assert_not_disclosed(result)

    def test_equal_rerun_has_no_push_or_github_write(self):
        head = self.upstream_change(
            "crates/pa-types/src/session.rs", "format\n",
        )
        state = self.state()
        state["workflows"] = [{
            "id": 1, "path": ".github/workflows/ci.yml", "state": "active",
        }]
        self.save_state(state)
        self.sync()
        self.sync("--post-status", "success", "--head", head)
        self.assertEqual(self.state()["statuses"][head], [{
            "context": "agx/sync-gates", "state": "success",
            "description": "checks passed",
        }])
        push_count, write_count = len(self.pushes()), len(self.writes())
        self.sync()
        self.assertEqual(len(self.pushes()), push_count)
        self.assertEqual(len(self.writes()), write_count)
        self.assertEqual(len(self.state()["prs"]), 1)
        self.assertEqual(self.outputs()["run-gates"], "false")

    def test_diverged_mirror_rejects_all_writes(self):
        divergent = self.commit("mirror-only.txt", "mirror\n")
        self.git(self.seed, "push", str(self.fork), "HEAD:upstream")
        self.git(self.seed, "reset", "--hard", self.base)
        self.upstream_change()
        state = self.state()
        state["workflows"] = [{
            "id": 1, "path": ".github/workflows/ci.yml", "state": "active",
        }]
        self.save_state(state)
        result = self.sync(success=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("cannot fast-forward", result.stderr)
        self.assertEqual(
            self.git(self.fork, "rev-parse", "upstream"), divergent,
        )
        self.assertEqual(self.pushes(), [])
        self.assertEqual(self.writes(), [])
        self.assertEqual(self.state()["prs"], [])
        self.assertEqual(self.state()["statuses"], {})

    def test_existing_pr_is_reused(self):
        self.upstream_change()
        state = self.state()
        state["prs"] = [self.open_pr()]
        self.save_state(state)
        self.sync()
        self.assertEqual(self.state()["prs"], [self.open_pr()])
        self.assertEqual(self.writes(), [])

    def test_format_notice_is_edited_across_syncs(self):
        first_path = "crates/pa-core/src/session/nested/state.rs"
        second_path = "crates/pa-core/src/auth/storage.rs"
        self.upstream_change(first_path, "format one\n")
        self.sync()
        comment_id = self.state()["comments"][0]["id"]
        self.upstream_change(second_path, "format two\n")
        self.sync()
        state = self.state()
        self.assertEqual(
            [label["name"] for label in state["labels"]], ["format-change"],
        )
        self.assertEqual(
            state["prs"][0]["labels"], [{"name": "format-change"}],
        )
        self.assertEqual(len(state["comments"]), 1)
        self.assertEqual(state["comments"][0]["id"], comment_id)
        self.assertEqual(
            state["comments"][0]["body"],
            "<!-- agx:format-change -->\n"
            "Format-sensitive paths changed in this sync PR:\n\n"
            f"- `{second_path}`\n- `{first_path}`",
        )
        edits = [call for call in self.writes() if call["method"] == "PATCH"]
        self.assertEqual(len(edits), 1)
        before = len(self.writes())
        self.sync()
        self.assertEqual(len(self.writes()), before)

    def test_conflict_posts_failure_without_gates_and_disables_workflows(self):
        self.commit("conflict.txt", "fork\n")
        self.git(self.seed, "push", str(self.fork), "HEAD:main")
        self.git(self.seed, "reset", "--hard", self.base)
        head = self.upstream_change("conflict.txt", "upstream\n")
        state = self.state()
        state["workflows"] = [{
            "id": 1, "path": ".github/workflows/ci.yml", "state": "active",
        }]
        self.save_state(state)
        result = self.sync()
        self.assertIn("CONFLICT", result.stdout)
        self.assertEqual(self.outputs()["run-gates"], "false")
        self.assertEqual(self.state()["statuses"][head], [{
            "context": "agx/sync-gates", "state": "failure",
            "description": "conflict",
        }])
        self.assertEqual(
            self.state()["workflows"][0]["state"], "disabled_manually",
        )
        before = len(self.writes())
        self.sync()
        self.assertEqual(len(self.writes()), before)

    def test_schedule_off_exits_before_commands(self):
        self.upstream_change()
        for value in (None, "off", "ON"):
            with self.subTest(value=value):
                env = {"GITHUB_EVENT_NAME": "schedule"}
                if value is not None:
                    env["AGX_SYNC_SCHEDULE"] = value
                result = self.sync(env=env)
                self.assertIn("Scheduled sync disabled", result.stdout)
                self.assertEqual(self.pushes(), [])
                self.assertEqual(self.state()["calls"], [])
                self.assertFalse(self.git_calls.exists())
                self.assertEqual(self.outputs()["run-gates"], "false")

    def test_manual_and_enabled_schedule_run(self):
        self.upstream_change()
        self.sync(env={"GITHUB_EVENT_NAME": "workflow_dispatch"})
        self.assertEqual(len(self.pushes()), 1)
        self.assertEqual(len(self.state()["prs"]), 1)
        self.sync(env={
            "GITHUB_EVENT_NAME": "schedule", "AGX_SYNC_SCHEDULE": "on",
        })
        self.assertEqual(self.outputs()["run-gates"], "true")

    def test_workflow_disable_is_selective(self):
        state = self.state()
        state["workflows"] = [
            {"id": 1, "path": ".github/workflows/ci.yml", "state": "active"},
            {"id": 2, "path": ".github/workflows/agx-ci.yml",
             "state": "active"},
            {"id": 3, "path": ".github/workflows/agx-sync.yml",
             "state": "active"},
            {"id": 4, "path": ".github/workflows/release.yml",
             "state": "disabled_manually"},
            {"id": 5, "path": ".github/workflows/agx-old.yaml",
             "state": "active"},
        ]
        self.save_state(state)
        self.sync()
        self.assertEqual([call["endpoint"] for call in self.writes()], [
            "repos/tester/agx/actions/workflows/1/disable",
            "repos/tester/agx/actions/workflows/5/disable"])
        self.assertEqual(
            [workflow["state"] for workflow in self.state()["workflows"]],
            ["disabled_manually", "active", "active", "disabled_manually",
             "disabled_manually"],
        )
        before = len(self.writes())
        self.sync()
        self.assertEqual(len(self.writes()), before)

    def test_final_status_skips_gates_and_post(self):
        head = self.upstream_change()
        texts = {"success": "checks passed", "failure": "checks failed"}
        for final in ("success", "failure"):
            with self.subTest(final=final):
                state = self.state()
                state["prs"] = [self.open_pr()]
                state["statuses"][head] = [
                    {"context": "other/check", "state": "success"},
                    {"context": "agx/sync-gates", "state": final,
                     "description": texts[final]},
                ]
                self.save_state(state)
                self.sync()
                before = len(self.writes())
                self.assertEqual(self.outputs()["run-gates"], "false")
                self.sync("--post-status", final, "--head", head)
                self.assertEqual(len(self.writes()), before)

    def test_rerun_gates_replace_a_failure_once(self):
        head = self.upstream_change()
        self.sync("--post-status", "failure", "--head", head)
        self.sync("--post-status", "success", "--head", head)
        self.sync("--post-status", "success", "--head", head)
        self.sync("--post-status", "failure", "--head", head)
        # Newest first, as the GitHub statuses API returns them.
        self.assertEqual(
            [s["state"] for s in self.state()["statuses"][head]],
            ["failure", "success", "failure"],
        )

    def test_post_check_failure_and_reject_invalid_head(self):
        head = self.upstream_change()
        self.sync("--post-status", "failure", "--head", head)
        self.assertEqual(self.state()["statuses"][head], [{
            "context": "agx/sync-gates", "state": "failure",
            "description": "checks failed",
        }])
        before = len(self.writes())
        result = self.sync(
            "--post-status", "success", "--head", "main", success=False,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("full commit SHA", result.stderr)
        self.assertEqual(len(self.writes()), before)

    def closed_sync_pr(self, number, branch, head, merged_at,
                       head_repo="tester/agx"):
        self.git(self.seed, "push", str(self.fork),
                 f"{head}:refs/pull/{number}/head")
        return {
            "number": number, "state": "closed", "base": {"ref": "main"},
            "head": {
                "ref": branch,
                "repo": {"full_name": head_repo} if head_repo else None,
            },
            "merged_at": merged_at,
        }

    def test_squashed_sync_pr_refuses_all_writes(self):
        head = self.upstream_change()
        self.git(self.seed, "checkout", "-b", "squashed", self.base)
        self.git(self.seed, "merge", "--squash", "main")
        self.git(self.seed, "commit", "-m", "squashed sync")
        self.commit("fork.txt", "later fork change\n")
        self.git(self.seed, "push", str(self.fork), "HEAD:main")
        for branch in ("upstream", "upstream-main", "sync/2026-10-14"):
            with self.subTest(branch=branch):
                state = self.state()
                state["closed_pr_pages"] = [[self.closed_sync_pr(
                    12, branch, head, "2026-10-14T12:00:00Z",
                )]]
                state["workflows"] = [{
                    "id": 1, "path": ".github/workflows/ci.yml",
                    "state": "active",
                }]
                self.save_state(state)
                result = self.sync(success=False)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("PR #12", result.stderr)
                self.assertIn("SYNC.md", result.stderr)
                self.assertIn("recovery", result.stderr)
                self.assertIn("no GitHub writes made", result.stderr)
                self.assertEqual(self.pushes(), [])
                self.assertEqual(self.writes(), [])

    def test_merge_commit_sync_passes_with_advanced_mirror(self):
        head = self.upstream_change()
        self.git(self.seed, "checkout", "-b", "fork-main", self.base)
        self.commit("fork.txt", "fork\n")
        self.git(self.seed, "merge", "--no-ff", "main", "-m", "sync merge")
        self.git(self.seed, "push", str(self.fork), "HEAD:main")
        self.git(self.seed, "checkout", "main")
        advanced = self.upstream_change("next.txt", "next upstream\n")
        self.git(self.seed, "push", str(self.fork), "HEAD:upstream")
        state = self.state()
        state["closed_pr_pages"] = [[self.closed_sync_pr(
            12, "upstream", head, "2026-10-14T12:00:00Z",
        )]]
        self.save_state(state)
        result = self.sync()
        self.assertIn("PR #12", result.stdout)
        self.assertIn("main contains its head", result.stdout)
        self.assertEqual(self.pushes(), [])
        self.assertEqual(self.outputs(), {
            "head": advanced, "run-gates": "true",
        })

    def test_no_merged_sync_pr_passes(self):
        head = self.upstream_change()
        state = self.state()
        state["closed_pr_pages"] = [[
            self.closed_sync_pr(12, "upstream", head, None),
            self.closed_sync_pr(
                13, "agx/feature", head, "2026-10-14T12:00:00Z",
            ),
        ]]
        self.save_state(state)
        self.sync()
        self.assertEqual(len(self.pushes()), 1)
        self.assertEqual(self.outputs()["run-gates"], "true")

    def test_merged_sync_named_pr_from_another_repo_is_ignored(self):
        head = self.upstream_change()
        state = self.state()
        state["closed_pr_pages"] = [[
            self.closed_sync_pr(
                12, "upstream", self.base, "2026-10-14T12:00:00Z",
            ),
            self.closed_sync_pr(
                13, "sync/2026-10-15", head, "2026-10-15T12:00:00Z",
                head_repo="contributor/agx",
            ),
            self.closed_sync_pr(
                14, "upstream", head, "2026-10-15T13:00:00Z",
                head_repo=None,
            ),
        ]]
        self.save_state(state)
        result = self.sync()
        self.assertIn("PR #12", result.stdout)
        self.assertEqual(len(self.pushes()), 1)

    def test_newer_closed_unmerged_pr_is_ignored(self):
        head = self.upstream_change()
        state = self.state()
        state["closed_pr_pages"] = [[
            self.closed_sync_pr(
                12, "upstream", self.base, "2026-10-14T12:00:00Z",
            ),
            self.closed_sync_pr(13, "sync/2026-10-15", head, None),
        ]]
        self.save_state(state)
        result = self.sync()
        self.assertIn("PR #12", result.stdout)
        self.assertEqual(len(self.pushes()), 1)

    def test_latest_merged_sync_on_second_page_refuses_all_writes(self):
        head = self.upstream_change()
        state = self.state()
        # The latest merge has neither the highest number nor the last
        # position, so only selection by merged_at finds it.
        state["closed_pr_pages"] = [
            [self.closed_sync_pr(
                14, "upstream", self.base, "2026-10-13T12:00:00Z",
            )],
            [
                self.closed_sync_pr(
                    12, "sync/2026-10-14", head, "2026-10-14T12:00:00Z",
                ),
                self.closed_sync_pr(
                    11, "upstream", self.base, "2026-10-12T12:00:00Z",
                ),
            ],
        ]
        state["workflows"] = [{
            "id": 1, "path": ".github/workflows/ci.yml", "state": "active",
        }]
        self.save_state(state)
        result = self.sync(success=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("PR #12", result.stderr)
        self.assertIn("SYNC.md", result.stderr)
        self.assertIn("recovery", result.stderr)
        self.assertIn("no GitHub writes made", result.stderr)
        self.assertEqual(self.pushes(), [])
        self.assertEqual(self.writes(), [])

    def test_failed_closed_pr_list_refuses_all_writes(self):
        self.upstream_change()
        state = self.state()
        state["closed_pr_read_failure"] = True
        state["workflows"] = [{
            "id": 1, "path": ".github/workflows/ci.yml", "state": "active",
        }]
        self.save_state(state)
        result = self.sync(success=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("read", result.stderr)
        self.assertIn("SYNC.md", result.stderr)
        self.assertIn("recovery", result.stderr)
        self.assertIn("no GitHub writes made", result.stderr)
        self.assertEqual(self.pushes(), [])
        self.assertEqual(self.writes(), [])

    def test_main_already_contains_upstream_creates_no_pr(self):
        self.sync()
        self.assertEqual(self.pushes(), [])
        self.assertEqual(self.writes(), [])
        self.assertEqual(self.state()["prs"], [])
        self.assertEqual(self.outputs()["run-gates"], "false")


if __name__ == "__main__":
    unittest.main()
