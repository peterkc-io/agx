#!/usr/bin/env python3
"""Fast-forward the upstream mirror and manage the standing sync PR."""

import argparse
import base64
import fnmatch
import json
import os
from pathlib import Path
import re
import subprocess
import sys


CONTEXT = "agx/sync-gates"
MARKER = "<!-- agx:format-change -->"
FORMAT_FILES = {
    "crates/pa-types/src/session.rs",
    "crates/pa-core/src/auth/storage.rs",
    "crates/pa-core/src/models/custom.rs",
    "crates/pa-core/src/mcp/connection_store.rs",
    "prime-agent-runtime/src/rlm/harness.py",
}
FORMAT_DIRS = ("crates/pa-core/src/session/", "crates/pa-core/src/settings/")


def run(args, *, input_text=None, allowed=(0,), env=None):
    result = subprocess.run(
        args, input=input_text, capture_output=True, text=True, env=env,
    )
    if result.returncode not in allowed:
        raise RuntimeError(
            f"{args[0]} {args[1]} failed ({result.returncode}): "
            f"{result.stderr.strip() or result.stdout.strip()}"
        )
    return result


def git(*args, allowed=(0,), env=None):
    return run(["git", *args], allowed=allowed, env=env)


def push_mirror(remote, head, token):
    """Push upstream with AGX_SYNC_TOKEN, the only write that uses it.

    GITHUB_TOKEN cannot push commits that change .github/workflows/. The
    token reaches only this git process, through its environment, never
    argv or a config file.
    """
    env = {
        key: value for key, value in os.environ.items()
        if key not in ("GH_TOKEN", "GITHUB_TOKEN")
    }
    env["GIT_TERMINAL_PROMPT"] = "0"
    index = int(env.get("GIT_CONFIG_COUNT", "0"))
    basic = base64.b64encode(f"x-access-token:{token}".encode()).decode()
    env.update({
        "GIT_CONFIG_COUNT": str(index + 1),
        f"GIT_CONFIG_KEY_{index}": "http.https://github.com/.extraheader",
        f"GIT_CONFIG_VALUE_{index}": f"AUTHORIZATION: basic {basic}",
    })
    try:
        git("push", "--no-follow-tags", remote,
            f"{head}:refs/heads/upstream", env=env)
    except RuntimeError as error:
        raise RuntimeError(
            "upstream push rejected; check that AGX_SYNC_TOKEN is "
            "unexpired with Contents and Workflows write on this repository. "
            f"No PR change or status made. {error}"
        ) from None


def api(repo, endpoint, *, method="GET", payload=None, pages=False):
    args = ["gh", "api", "--method", method, f"repos/{repo}/{endpoint}"]
    if pages:
        args.extend(["--paginate", "--slurp"])
    if payload is not None:
        args.extend(["--input", "-"])
    input_text = json.dumps(payload) if payload is not None else None
    output = run(args, input_text=input_text).stdout
    return json.loads(output) if output.strip() else None


def list_items(repo, endpoint):
    return [item for page in api(repo, endpoint, pages=True) for item in page]


def has_final_status(repo, head):
    return any(
        status["context"] == CONTEXT
        and status["state"] in ("success", "failure")
        for status in list_items(repo, f"commits/{head}/statuses?per_page=100")
    )


def post_status(repo, head, state, description):
    # A rerun of the gates may replace the latest result, never repeat it.
    # The statuses API lists the newest status first.
    latest = next((
        status for status
        in list_items(repo, f"commits/{head}/statuses?per_page=100")
        if status["context"] == CONTEXT
    ), None)
    if latest and (latest["state"], latest.get("description")) == (
        state, description,
    ):
        print(f"{CONTEXT} {state} ({description}) exists for {head}; "
              "nothing posted.")
        return
    api(repo, f"statuses/{head}", method="POST", payload={
        "context": CONTEXT, "state": state, "description": description,
    })
    print(f"Posted {CONTEXT}: {state} ({description}) on {head}.")


def format_notice(repo, pr, main, head):
    base = git("merge-base", main, head).stdout.strip()
    changed = git("diff", "--name-only", "-z", base, head).stdout.split("\0")
    paths = sorted(
        path for path in changed
        if path in FORMAT_FILES or path.startswith(FORMAT_DIRS)
    )
    if not paths:
        return
    if not any(label["name"] == "format-change" for label in pr["labels"]):
        labels = list_items(repo, "labels?per_page=100")
        if not any(label["name"] == "format-change" for label in labels):
            api(repo, "labels", method="POST", payload={
                "name": "format-change", "color": "d93f0b",
                "description": "Sync changes a format-sensitive path",
            })
        api(repo, f"issues/{pr['number']}/labels", method="POST", payload={
            "labels": ["format-change"],
        })
    body = MARKER + "\nFormat-sensitive paths changed in this sync PR:\n\n"
    body += "\n".join(f"- `{path}`" for path in paths)
    comments = list_items(repo, f"issues/{pr['number']}/comments?per_page=100")
    marked = [
        comment for comment in comments
        if MARKER in comment["body"].splitlines()
    ]
    if len(marked) > 1:
        raise RuntimeError(
            "Multiple format-change marker comments; refusing to add another."
        )
    if not marked:
        api(repo, f"issues/{pr['number']}/comments",
            method="POST", payload={"body": body})
    elif marked[0]["body"] != body:
        api(repo, f"issues/comments/{marked[0]['id']}",
            method="PATCH", payload={"body": body})


def disable_upstream_workflows(repo):
    pages = api(repo, "actions/workflows?per_page=100", pages=True)
    for page in pages:
        for workflow in page["workflows"]:
            if workflow["state"] == "active" and not fnmatch.fnmatchcase(
                workflow["path"], ".github/workflows/agx-*.yml"
            ):
                api(repo, f"actions/workflows/{workflow['id']}/disable",
                    method="PUT")
                print(f"Disabled upstream workflow: {workflow['path']}")


def check_last_sync(repo, remote):
    recovery = "See docs/fork/SYNC.md#recover-a-squashed-sync for recovery"
    try:
        prs = list_items(repo, "pulls?state=closed&base=main&per_page=100")
    except (RuntimeError, OSError, json.JSONDecodeError) as error:
        raise RuntimeError(
            f"Cannot read the complete closed PR list. {recovery}; "
            "no GitHub writes made"
        ) from error
    merged = [
        pr for pr in prs if pr["merged_at"] and (
            pr["head"]["ref"] in ("upstream", "upstream-main")
            or pr["head"]["ref"].startswith("sync/")
        )
    ]
    if not merged:
        return
    pr = max(merged, key=lambda pr: pr["merged_at"])
    number = pr["number"]
    try:
        git("fetch", "--no-tags", remote,
            f"+refs/pull/{number}/head:refs/agx-sync/last-sync")
        ancestry = git(
            "merge-base", "--is-ancestor", "refs/agx-sync/last-sync",
            "refs/agx-sync/main", allowed=(0, 1),
        )
    except (RuntimeError, OSError) as error:
        raise RuntimeError(
            f"Cannot check merged sync PR #{number}. {recovery}; "
            "no GitHub writes made"
        ) from error
    if ancestry.returncode:
        raise RuntimeError(
            f"main does not contain merged sync PR #{number}'s head. "
            f"{recovery}; no GitHub writes made"
        )
    print(f"Checked merged sync PR #{number}: main contains its head.")


def prepare(repo, remote, upstream):
    # Remove the token from this process, so only the push can receive it.
    token = os.environ.pop("AGX_SYNC_TOKEN", "")
    if not token:
        raise RuntimeError(
            "AGX_SYNC_TOKEN is not set (environment agx-sync secret); "
            "no GitHub writes made."
        )
    git("fetch", "--no-tags", remote,
        "+refs/heads/main:refs/agx-sync/main",
        "+refs/heads/upstream:refs/agx-sync/mirror")
    git("fetch", "--no-tags", upstream,
        "+refs/heads/main:refs/agx-sync/upstream")
    main = git("rev-parse", "refs/agx-sync/main").stdout.strip()
    mirror = git("rev-parse", "refs/agx-sync/mirror").stdout.strip()
    head = git("rev-parse", "refs/agx-sync/upstream").stdout.strip()
    ancestry = git("merge-base", "--is-ancestor", mirror, head, allowed=(0, 1))
    if ancestry.returncode:
        raise RuntimeError(
            "upstream cannot fast-forward to upstream main; "
            "no GitHub writes made."
        )

    check_last_sync(repo, remote)

    # The ancestry checks permit writes. Disable workflows even on conflict.
    try:
        if mirror != head:
            push_mirror(remote, head, token)
        owner = repo.split("/")[0]
        prs = list_items(
            repo, f"pulls?state=open&base=main&head={owner}:upstream"
            "&per_page=100",
        )
        if len(prs) > 1:
            raise RuntimeError(
                "Multiple standing sync PRs; refusing to create another."
            )
        included = git(
            "merge-base", "--is-ancestor", head, main, allowed=(0, 1),
        )
        if included.returncode == 0:
            print("main contains upstream; no PR or gates needed.")
            return head, False
        if not prs:
            prs = [api(repo, "pulls", method="POST", payload={
                "base": "main", "head": "upstream",
                "title": "chore: sync upstream main",
                "body": "Standing upstream sync PR. Review the sync checks "
                        "and merge with a merge commit.",
            })]
        format_notice(repo, prs[0], main, head)
        if has_final_status(repo, head):
            print(f"Final {CONTEXT} status already exists; gates skipped.")
            return head, False
        merge = git("merge-tree", "--write-tree", main, head, allowed=(0, 1))
        if merge.returncode:
            print(merge.stdout, end="")
            post_status(repo, head, "failure", "conflict")
            return head, False
        print(f"Run sync gates on main merged with {head}.")
        return head, True
    finally:
        disable_upstream_workflows(repo)


def outputs(head="", *, run_gates=False):
    if path := os.environ.get("GITHUB_OUTPUT"):
        with Path(path).open("a", encoding="utf-8") as stream:
            stream.write(f"head={head}\nrun-gates={str(run_gates).lower()}\n")


def main():
    if (os.environ.get("GITHUB_EVENT_NAME") == "schedule"
            and os.environ.get("AGX_SYNC_SCHEDULE") != "on"):
        print("Scheduled sync disabled: AGX_SYNC_SCHEDULE is not exactly "
              "'on'; no GitHub writes made.")
        outputs()
        return 0
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY"))
    parser.add_argument("--remote", default="origin")
    parser.add_argument(
        "--upstream",
        default="https://github.com/PrimeIntellect-ai/prime-agent.git",
    )
    parser.add_argument("--post-status", choices=("success", "failure"))
    parser.add_argument("--head")
    args = parser.parse_args()
    if not args.repo:
        parser.error("--repo or GITHUB_REPOSITORY is required")
    if args.post_status:
        if not args.head or not re.fullmatch(
            r"[0-9a-f]{40}|[0-9a-f]{64}", args.head,
        ):
            parser.error("--post-status needs --head with a full commit SHA")
        description = ("checks passed" if args.post_status == "success"
                       else "checks failed")
        post_status(args.repo, args.head, args.post_status, description)
    else:
        head, run_gates = prepare(args.repo, args.remote, args.upstream)
        outputs(head, run_gates=run_gates)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (RuntimeError, OSError, json.JSONDecodeError) as error:
        print(f"sync error: {error}", file=sys.stderr)
        sys.exit(1)
