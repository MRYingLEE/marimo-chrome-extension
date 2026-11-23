# Copyright 2026 Marimo. All rights reserved.
"""Build the unpacked extension after `make fe && make py`."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

from build_extension import PACKAGE, build
from build_wheels import main as build_wheels
from local_index import local_index


def main() -> None:
    with (
        TemporaryDirectory(prefix="marimo-chrome-extension-") as directory,
        TemporaryDirectory(prefix="marimo-chrome-extension-uv-") as uv_cache,
    ):
        tmp = Path(directory)
        home = tmp / "home"
        home.mkdir()
        env = {
            key: value
            for key, value in os.environ.items()
            if not key.startswith("MARIMO_") and key != "PYTHONPATH"
        }
        env.update(
            HOME=str(home),
            PATH=os.pathsep.join(
                (str(Path(sys.executable).parent), env["PATH"])
            ),
            PYTHONDONTWRITEBYTECODE="1",
            UV_CACHE_DIR=uv_cache,
            UV_PYTHON=sys.executable,
            XDG_CACHE_HOME=str(home / ".cache"),
            XDG_CONFIG_HOME=str(home / ".config"),
            XDG_DATA_HOME=str(home / ".local" / "share"),
        )

        def run(*command: str) -> None:
            subprocess.run(command, cwd=tmp, env=env, check=True)

        wheels = tmp / "wheels"
        build_wheels(wheels, env=env)
        (wheel,) = wheels.glob("marimo-*.whl")
        exporter = tmp / "exporter"
        run("uv", "venv", "--python", sys.executable, str(exporter))
        python = str(
            exporter
            / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        )
        run(
            "uv",
            "pip",
            "install",
            "--python",
            python,
            str(wheel),
            "playwright",
        )

        if not env.get("PLAYWRIGHT_BROWSERS_PATH"):
            env["PLAYWRIGHT_BROWSERS_PATH"] = str(tmp / "chromium")
            run(
                python,
                "-m",
                "playwright",
                "install",
                "--only-shell",
                "chromium",
            )

        seed = tmp / "seed.py"
        shutil.copyfile(PACKAGE / seed.name, seed)
        export = tmp / "export"
        with local_index(wheels) as index:
            run(
                python,
                "-m",
                "marimo",
                "export",
                "html-wasm",
                seed.name,
                "--mode",
                "edit",
                "--offline",
                "--pypi-index-url",
                index,
                "-o",
                str(export),
            )

        built = tmp / "dist"
        build(export, built)
        dist = PACKAGE / "dist"
        if dist.exists():
            shutil.rmtree(dist)
        shutil.move(built, dist)
        sys.stdout.write(f"Load unpacked from {dist}\n")


if __name__ == "__main__":
    main()
