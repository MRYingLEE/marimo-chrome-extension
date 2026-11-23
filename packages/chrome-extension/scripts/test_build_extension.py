# Copyright 2026 Marimo. All rights reserved.
from html.parser import HTMLParser
from pathlib import Path

from build_extension import build


class Scripts(HTMLParser):
    def __init__(self, path: Path) -> None:
        super().__init__()
        self.sources: list[str | None] = []
        self.feed(path.read_text(encoding="utf-8"))

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        if tag == "script":
            self.sources.append(dict(attrs).get("src"))


def test_sandbox_export_uses_only_external_scripts_and_defers_entrypoint(
    tmp_path: Path,
) -> None:
    export = tmp_path / "export"
    export.mkdir()
    (export / "index.html").write_text(
        """<!doctype html>
        <script data-marimo="true">
        Object.defineProperty(window, "__MARIMO_MOUNT_CONFIG__", {
          value: Object.freeze({"config": {"runtime": {"auto_instantiate": false}}}),
        });
        </script>
        <script type="module" crossorigin src="./assets/main.js"></script>
        <script>if (window.location.protocol === 'file:') alert('warning');</script>
        <marimo-code hidden="">print%281%29</marimo-code>
        """,
        encoding="utf-8",
    )

    dist = tmp_path / "dist"
    build(export, dist, "b")

    sandbox = dist / "sandbox"
    assert Scripts(sandbox / "index.html").sources == [
        "./inline-1.js",
        "./boot.js",
    ]
    assert Scripts(dist / "sidepanel.html").sources == ["./panel.js"]
    assert '"auto_instantiate": true' in (sandbox / "inline-1.js").read_text(
        encoding="utf-8"
    )
    assert 'import("./assets/main.js")' in (sandbox / "boot.js").read_text(
        encoding="utf-8"
    )
