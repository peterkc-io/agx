#!/usr/bin/env python3
"""Give each Bazel test private state and declared interpreter/binary paths."""

from contextlib import ExitStack
import os
from pathlib import Path
import signal
import shutil
import subprocess
import sys
import uuid
from typing import Mapping, Sequence


BIN_DIR = Path("/tmp/agx-bazel-bin")


def runfile(path: str, env: Mapping[str, str]) -> Path:
    candidate = Path(path)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise RuntimeError("Expected a declared runfiles-relative path: "
                           f"{path}")
    candidate = (Path(env["RUNFILES_DIR"]) / env["TEST_WORKSPACE"]
                 / candidate)
    return candidate.resolve()


def validate_kernel(env: Mapping[str, str]) -> None:
    for name in ("PA_CORE_KERNEL_PYTHON", "PA_E2E_KERNEL_PYTHON"):
        value = env.get(name)
        if not value or not os.access(value, os.X_OK):
            raise RuntimeError(f"Missing override interpreter: {name}")
    layout = (Path(env["HOME"]) / ".prime/agent/kernel-venv-agx"
              / "bin/python")
    if not os.access(layout, os.X_OK):
        raise RuntimeError(f"Missing HOME kernel venv layout: {layout}")


def run_test(command: Sequence[str], source_env: Mapping[str, str]) -> int:
    env = dict(source_env)
    command = [str(Path(command[0]).absolute()), *command[1:]]
    with ExitStack() as cleanup:
        # Deep Bazel TEST_TMPDIR paths overflow Unix socket addresses.
        # Four characters also fit macOS's canonical /private/tmp prefix.
        for _ in range(16):
            home = (Path("/tmp") / uuid.uuid4().hex[:4]).resolve()
            try:
                home.mkdir()
                break
            except FileExistsError:
                continue
        else:
            raise RuntimeError("Cannot allocate a short test temporary dir")
        cleanup.callback(shutil.rmtree, home)
        env.update(HOME=str(home), TMPDIR=str(home), PYTHONNOUSERSITE="1",
                   PYTHONDONTWRITEBYTECODE="1")
        if env.get("AGX_BAZEL_SOURCE_ROOT") == "1":
            source = Path("/tmp/agx-bazel-src")
            source.symlink_to(runfile(".", env), target_is_directory=True)
            cleanup.callback(source.unlink)
        if env.get("AGX_BAZEL_CARGO_LAYOUT") == "1":
            # hold_refusal recognizes Cargo's target/debug process image.
            executable = home / "target/debug" / Path(command[0]).name
            executable.parent.mkdir(parents=True)
            shutil.copy2(command[0], executable)
            command[0] = str(executable)
        if env.get("AGX_BAZEL_PACKAGE") == "1":
            package = runfile(".", env)
            env.update(PI_PACKAGE_DIR=str(package), AGX_PROCESS="1")
            skill_paths = sorted((package / "skills").glob("*/src"))
            if not skill_paths:
                raise RuntimeError("Missing declared bundled Python skills")
            env["PYTHONPATH"] = os.pathsep.join(
                str(path) for path in skill_paths)
        if env.get("AGX_BAZEL_KERNEL") == "1":
            prefix = runfile(env["AGX_BAZEL_KERNEL_PREFIX"], env)
            python = prefix / "bin/python3"
            if not os.access(python, os.X_OK):
                raise RuntimeError("Missing override interpreter for "
                                   f"PA_CORE_KERNEL_PYTHON / "
                                   f"PA_E2E_KERNEL_PYTHON: {python}")
            venv = home / ".prime/agent/kernel-venv-agx"
            venv.parent.mkdir(parents=True, exist_ok=True)
            venv.symlink_to(prefix, target_is_directory=True)
            env.update(PA_CORE_KERNEL_PYTHON=str(python),
                       PA_E2E_KERNEL_PYTHON=str(python),
                       PRIME_AGENT_KERNEL_PYTHON=str(python))
            validate_kernel(env)
        binaries = {name: env[key] for name, key in (
            ("agx", "AGX_BAZEL_AGX"),
            ("pa-daemon", "AGX_BAZEL_DAEMON"),
        ) if key in env}
        if binaries:
            try:
                BIN_DIR.mkdir()
            except FileExistsError as error:
                raise RuntimeError(f"{BIN_DIR} already exists; "
                                   "test /tmp is not isolated") from error
            cleanup.callback(BIN_DIR.rmdir)
            for name, path in binaries.items():
                binary = runfile(path, env)
                if not binary.is_file() or not os.access(binary, os.X_OK):
                    raise RuntimeError(f"Missing declared runfiles binary "
                                       f"{name}: {binary}")
                link = BIN_DIR / name
                link.symlink_to(binary)
                cleanup.callback(link.unlink)
        child = subprocess.Popen(command, env=env)
        # Forward Bazel's timeout/cancellation so the normal cleanup runs.
        def forward_signal(signum, _frame):
            child.send_signal(signum)

        previous = {}
        for signum in (signal.SIGTERM, signal.SIGINT):
            previous[signum] = signal.signal(signum, forward_signal)
        try:
            return child.wait()
        finally:
            for signum, handler in previous.items():
                signal.signal(signum, handler)
            if child.poll() is None:
                child.terminate()
                child.wait()


def main() -> int:
    try:
        return run_test(sys.argv[1:], os.environ)
    except (OSError, RuntimeError, KeyError) as error:
        print(f"Bazel test environment: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
