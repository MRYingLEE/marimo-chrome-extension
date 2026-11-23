# Copyright 2026 Marimo. All rights reserved.
"""Build a throwaway MV3 extension from an `html-wasm --offline` export.

Option A: the side panel is the export itself, served as an extension page.
Option B: the side panel is a thin page that embeds the export in a sandboxed
page (`manifest.sandbox.pages`).

Inline scripts are moved into files, because MV3 extension pages and sandboxed
pages both forbid inline `<script>` unless the sandbox CSP allows it. The
`file:` warning is dropped.

Usage: python build_extension.py <export_dir> <out_dir> --option {a,b}
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
from pathlib import Path

INLINE_SCRIPT = re.compile(
    r"<script(?P<attrs>(?![^>]*\bsrc=)[^>]*)>(?P<body>.*?)</script>",
    re.DOTALL,
)
FILE_WARNING = "window.location.protocol === 'file:'"

BACKGROUND_JS = """\
chrome.sidePanel.setPanelBehavior({ openPanelOnActionClick: true });
"""

# Option B: the parent page only hosts the sandboxed page.
PANEL_B_HTML = """\
<!doctype html>
<html>
  <body style="margin:0">
    <iframe src="sandbox/index.html" style="border:0;width:100%;height:100vh"></iframe>
  </body>
</html>
"""


def externalize_inline_scripts(html: str, directory: Path) -> str:
    count = 0

    def replace(match: re.Match[str]) -> str:
        nonlocal count
        body = match.group("body")
        if FILE_WARNING in body:
            return ""
        count += 1
        name = f"inline-{count}.js"
        (directory / name).write_text(body, encoding="utf-8")
        return f'<script src="./{name}"></script>'

    return INLINE_SCRIPT.sub(replace, html)


def manifest(option: str) -> dict[str, object]:
    base: dict[str, object] = {
        "manifest_version": 3,
        "name": "marimo spike",
        "version": "0.0.1",
        "permissions": ["sidePanel", "storage", "unlimitedStorage"],
        "background": {"service_worker": "background.js"},
        "side_panel": {"default_path": "sidepanel.html"},
        "action": {"default_title": "Open marimo"},
        "content_security_policy": {
            "extension_pages": "script-src 'self' 'wasm-unsafe-eval'; object-src 'self'"
        },
    }
    if option == "b":
        base["sandbox"] = {"pages": ["sandbox/index.html"]}
        base["content_security_policy"] = {
            **base["content_security_policy"],  # type: ignore[dict-item]
            "sandbox": (
                "sandbox allow-scripts allow-forms allow-popups "
                "allow-modals; script-src 'self' 'unsafe-inline' "
                "'unsafe-eval' 'wasm-unsafe-eval' blob: data:; "
                "worker-src 'self' blob: data:; object-src 'self'"
            ),
        }
    return base


def build(export_dir: Path, out_dir: Path, option: str) -> None:
    if out_dir.exists():
        shutil.rmtree(out_dir)
    # Option B serves the page and its assets from the sandbox directory.
    page_dir = out_dir / "sandbox" if option == "b" else out_dir
    shutil.copytree(export_dir, page_dir)
    index = page_dir / "index.html"
    html = externalize_inline_scripts(
        index.read_text(encoding="utf-8"), page_dir
    )
    if option == "a":
        index.unlink()
        (page_dir / "sidepanel.html").write_text(html, encoding="utf-8")
    else:
        index.write_text(html, encoding="utf-8")
        (out_dir / "sidepanel.html").write_text(PANEL_B_HTML, encoding="utf-8")
    shutil.copy(Path(__file__).parents[1] / "spike-script.js", page_dir)
    (out_dir / "background.js").write_text(BACKGROUND_JS, encoding="utf-8")
    (out_dir / "manifest.json").write_text(
        json.dumps(manifest(option), indent=2), encoding="utf-8"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("export_dir", type=Path)
    parser.add_argument("out_dir", type=Path)
    parser.add_argument("--option", choices=["a", "b"], required=True)
    args = parser.parse_args()
    build(args.export_dir, args.out_dir, args.option)
