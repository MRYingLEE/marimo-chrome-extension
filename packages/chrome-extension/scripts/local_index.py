# Copyright 2026 Marimo. All rights reserved.
"""A tiny PyPI "simple" index for `marimo export html-wasm --offline`.

It serves the local `marimo-base` wheel built by `build_wheels.py` and proxies
every other project to pypi.org. Pass it to the exporter with
`--pypi-index-url http://127.0.0.1:<port>`.

Usage: python local_index.py <wheel_dir> [port]
"""

from __future__ import annotations

import html
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import quote, unquote
from urllib.request import Request, urlopen

PYPI_SIMPLE = "https://pypi.org/simple"


def make_handler(wheel_dir: Path) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def _send(self, body: bytes, content_type: str) -> None:
            self.send_response(200)
            self.send_header("content-type", content_type)
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:
            path = unquote(self.path.split("?", 1)[0])
            parts = [part for part in path.split("/") if part]
            if len(parts) == 2 and parts[0] == "files":
                wheel = wheel_dir / parts[1]
                if wheel.is_file():
                    self._send(wheel.read_bytes(), "application/octet-stream")
                    return
            elif (
                len(parts) == 1 and parts[0].replace("_", "-") == "marimo-base"
            ):
                links = "".join(
                    f'<a href="/files/{quote(wheel.name)}">'
                    f"{html.escape(wheel.name)}</a>\n"
                    for wheel in wheel_dir.glob("marimo_base-*.whl")
                )
                self._send(f"<!doctype html>{links}".encode(), "text/html")
                return
            elif len(parts) == 1:
                upstream = Request(
                    f"{PYPI_SIMPLE}/{parts[0]}/",
                    headers={"accept": "text/html"},
                )
                try:
                    with urlopen(upstream, timeout=60) as response:
                        self._send(response.read(), "text/html")
                        return
                except OSError:
                    pass
            self.send_error(404)

        def log_message(self, format: str, *args: object) -> None:
            return

    return Handler


if __name__ == "__main__":
    port = int(sys.argv[2]) if len(sys.argv) > 2 else 8765
    server = ThreadingHTTPServer(
        ("127.0.0.1", port), make_handler(Path(sys.argv[1]))
    )
    print(f"Serving on http://127.0.0.1:{port}", flush=True)
    server.serve_forever()
