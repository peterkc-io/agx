#!/usr/bin/env python3
"""Run agx's kernel bootstrap and retain a relocatable interpreter prefix."""

from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


def main() -> int:
    uv, agx, manifest, output = (
        Path(arg).resolve() for arg in sys.argv[1:]
    )
    with tempfile.TemporaryDirectory() as temp:
        work = Path(temp)
        env = {"PATH": str(uv.parent) + ":/usr/bin:/bin",
               "HOME": temp, "TMPDIR": temp, "TZ": "UTC",
               "UV_CACHE_DIR": str(work / "cache"), "UV_NO_CONFIG": "1",
               "UV_PYTHON_INSTALL_DIR": str(work / "pythons"),
               "PI_PACKAGE_DIR": str(manifest.parent.parent),
               "AGX_PROCESS": "1", "DO_NOT_TRACK": "1",
               "PYTHONNOUSERSITE": "1", "PYTHONDONTWRITEBYTECODE": "1"}
        subprocess.run([str(agx), "--prime-agent-bootstrap"],
                       env=env, check=True)
        venv = work / ".prime/agent/kernel-venv-agx"
        python = (venv / "bin/python").resolve(strict=True)
        # A venv's python link and pyvenv.cfg contain build-action paths.
        # Keep the self-contained base Python instead, then overlay the venv's
        # non-editable packages. CPython finds its stdlib next to the binary.
        shutil.copytree(python.parent.parent, output, symlinks=True,
                        dirs_exist_ok=True)
        sites = list((venv / "lib").glob("python*/site-packages"))
        if len(sites) != 1:
            raise RuntimeError("Expected one bootstrap site-packages "
                               "directory")
        shutil.copytree(sites[0], output / sites[0].relative_to(venv),
                        symlinks=True, dirs_exist_ok=True)
        if not (output / "bin/python").exists():
            (output / "bin/python").symlink_to("python3")
        subprocess.run([str(output / "bin/python"), "-B", "-c",
                        "import rlm.repl, dill"],
                       env=env, check=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
