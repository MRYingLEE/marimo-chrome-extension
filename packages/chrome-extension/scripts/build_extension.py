# Copyright 2026 Marimo. All rights reserved.
"""Build an MV3 extension from an `html-wasm --offline` export.

Option B delays app startup until the side panel sends the seed notebook.
Option A remains available to reproduce the spike.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
from pathlib import Path
from urllib.parse import unquote

from build_wheels import ROOT

PACKAGE = Path(__file__).resolve().parents[1]
INLINE_SCRIPT = re.compile(
    r"<script\b(?![^>]*\s+src\s*=)[^>]*>(?P<body>.*?)</script>",
    re.DOTALL | re.IGNORECASE,
)
MODULE_SCRIPT = re.compile(
    r"""<script\b(?=[^>]*\s+type=["']module["'])"""
    r"""[^>]*\s+src=["'](?P<src>[^"']+)["'][^>]*>\s*</script>"""
)
MARIMO_CODE = re.compile(
    r"(<marimo-code\b[^>]*>)(.*?)(</marimo-code>)", re.DOTALL
)
FILE_WARNING = "window.location.protocol === 'file:'"
ICONS = {
    "16": "favicon-16x16.png",
    "32": "favicon-32x32.png",
    "192": "android-chrome-192x192.png",
}
# HTML-WASM exports generate their own runtime config, ignoring user settings.
AUTO_INSTANTIATE = True


def externalize_inline_scripts(
    html: str, directory: Path, *, auto_instantiate: bool | None = None
) -> str:
    count = 0
    configured = False

    def replace(match: re.Match[str]) -> str:
        nonlocal count, configured
        body = match.group("body")
        if FILE_WARNING in body:
            return ""
        if auto_instantiate is not None and (
            'Object.defineProperty(window, "__MARIMO_MOUNT_CONFIG__"' in body
        ):
            body, changes = re.subn(
                r'("auto_instantiate"\s*:\s*)(?:true|false)',
                lambda m: m[1] + json.dumps(auto_instantiate),
                body,
            )
            if changes != 1 or configured:
                raise ValueError(
                    "Expected one mount config auto_instantiate setting"
                )
            configured = True
        count += 1
        name = f"inline-{count}.js"
        (directory / name).write_text(body, encoding="utf-8")
        return f'<script src="./{name}"></script>'

    html = INLINE_SCRIPT.sub(replace, html)
    if auto_instantiate is not None and not configured:
        raise ValueError("Missing marimo mount config")
    return html


def add_handshake(html: str, page_dir: Path, out_dir: Path) -> str:
    modules = list(MODULE_SCRIPT.finditer(html))
    code = MARIMO_CODE.search(html)
    if len(modules) != 1 or code is None:
        raise ValueError(
            "Expected one module entrypoint and a <marimo-code> element"
        )
    module = modules[0]
    boot = (PACKAGE / "boot.js").read_text(encoding="utf-8")
    (page_dir / "boot.js").write_text(
        boot.replace('"__ENTRYPOINT__"', json.dumps(module["src"])),
        encoding="utf-8",
    )
    panel = (PACKAGE / "panel.js").read_text(encoding="utf-8")
    # Keep any dependency rewrites from the offline exporter.
    (out_dir / "panel.js").write_text(
        panel.replace('"__SEED__"', json.dumps(unquote(code[2].strip()))),
        encoding="utf-8",
    )
    html = MODULE_SCRIPT.sub('<script defer src="./boot.js"></script>', html)
    return MARIMO_CODE.sub(r"\1\3", html, count=1)


def manifest(option: str) -> dict[str, object]:
    csp = {
        "extension_pages": "script-src 'self' 'wasm-unsafe-eval'; object-src 'self'",
    }
    base: dict[str, object] = {
        "manifest_version": 3,
        "name": "marimo",
        "version": "0.0.1",
        "permissions": ["sidePanel", "storage", "unlimitedStorage"],
        "background": {"service_worker": "background.js", "type": "module"},
        "side_panel": {"default_path": "sidepanel.html"},
        "icons": ICONS,
        "action": {"default_title": "Open marimo", "default_icon": ICONS},
        "content_security_policy": csp,
    }
    if option == "b":
        base["sandbox"] = {"pages": ["sandbox/index.html"]}
        csp["sandbox"] = (
            "sandbox allow-scripts allow-forms allow-popups "
            "allow-modals; script-src 'self' 'unsafe-inline' "
            "'unsafe-eval' 'wasm-unsafe-eval' blob: data:; "
            "worker-src 'self' blob: data:; object-src 'self'"
        )
    return base


def build(export_dir: Path, out_dir: Path, option: str = "b") -> None:
    if out_dir.exists():
        shutil.rmtree(out_dir)
    # Option B serves the page and its assets from the sandbox directory.
    page_dir = out_dir / "sandbox" if option == "b" else out_dir
    shutil.copytree(export_dir, page_dir)
    index = page_dir / "index.html"
    html = externalize_inline_scripts(
        index.read_text(encoding="utf-8"),
        page_dir,
        auto_instantiate=AUTO_INSTANTIATE if option == "b" else None,
    )
    if option == "a":
        index.unlink()
        (page_dir / "sidepanel.html").write_text(html, encoding="utf-8")
    else:
        index.write_text(
            add_handshake(html, page_dir, out_dir), encoding="utf-8"
        )
        shutil.copyfile(PACKAGE / "sidepanel.html", out_dir / "sidepanel.html")
    shutil.copyfile(PACKAGE / "spike-script.js", page_dir / "spike-script.js")
    shutil.copyfile(PACKAGE / "background.js", out_dir / "background.js")
    for icon in ICONS.values():
        shutil.copyfile(ROOT / "marimo" / "_static" / icon, out_dir / icon)
    (out_dir / "manifest.json").write_text(
        json.dumps(manifest(option), indent=2), encoding="utf-8"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("export_dir", type=Path)
    parser.add_argument("out_dir", type=Path)
    parser.add_argument("--option", choices=["a", "b"], default="b")
    args = parser.parse_args()
    build(args.export_dir, args.out_dir, args.option)
