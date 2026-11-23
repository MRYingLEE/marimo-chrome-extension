# Copyright 2026 Marimo. All rights reserved.
"""Build `marimo` and `marimo-base` wheels from this checkout.

Both wheels get the same local version (`<version>+chromeext`), so that:

* the full `marimo` wheel (with the built frontend in `marimo/_static`) can be
  installed in the environment that runs `marimo export html-wasm`, and
* the exporter's `__version__` names a `marimo-base` that only the local index
  (see `local_index.py`) can serve, so the bundled runtime always matches the
  frontend. A released `marimo-base` with the same version would not.

Requires the frontend to be built already (`make fe`). The repo's
pyproject.toml is never modified; the build happens in a temporary copy.

Usage: python build_wheels.py <out_dir>
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
LOCAL_SEGMENT = "chromeext"
IGNORED = (
    ".git",
    ".venv",
    "node_modules",
    "frontend",
    "docs",
    "examples",
    "tests",
    "packages",
    "dist",
)


def _uv_build(cwd: Path, out_dir: Path, env: dict[str, str] | None) -> None:
    subprocess.run(
        ["uv", "build", "--wheel", "--out-dir", str(out_dir)],
        cwd=cwd,
        env=env,
        check=True,
    )


def main(out_dir: Path, *, env: dict[str, str] | None = None) -> None:
    import tomlkit

    if not (ROOT / "marimo" / "_static" / "index.html").exists():
        sys.exit("marimo/_static is missing. Run `make fe` first.")
    out_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="marimo-wheels-") as tmp:
        src = Path(tmp) / "src"
        shutil.copytree(
            ROOT,
            src,
            # Only prune top-level directories: `marimo/_runtime/packages`
            # must survive.
            ignore=lambda directory, _names: (
                IGNORED if Path(directory) == ROOT else ()
            ),
        )
        pyproject = src / "pyproject.toml"
        text = pyproject.read_text(encoding="utf-8")
        text, count = re.subn(
            r'^version = "([^"]+)"',
            rf'version = "\1+{LOCAL_SEGMENT}"',
            text,
            count=1,
            flags=re.MULTILINE,
        )
        assert count == 1, "version line not found in pyproject.toml"
        pyproject.write_text(text, encoding="utf-8")

        _uv_build(src, out_dir, env)

        data = tomlkit.loads(pyproject.read_text(encoding="utf-8"))
        data["project"]["name"] = "marimo-base"
        backend = data["tool"]["uv"]["build-backend"]
        excluded = [
            str(item.relative_to(src))
            for item in (src / "marimo" / "_static").iterdir()
            if item.name != "index.html"
        ] + ["marimo/_lsp"]
        backend["wheel-exclude"] = [
            *backend.get("wheel-exclude", []),
            *excluded,
        ]
        backend["source-exclude"] = excluded
        pyproject.write_text(tomlkit.dumps(data), encoding="utf-8")
        _uv_build(src, out_dir, env)


if __name__ == "__main__":
    main(Path(sys.argv[1]))
