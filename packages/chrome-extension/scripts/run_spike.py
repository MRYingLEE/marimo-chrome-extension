# Copyright 2026 Marimo. All rights reserved.
"""Run the spike checklist against an unpacked extension in Chromium.

Loads the extension with `--load-extension`, opens `sidepanel.html` as a tab
(the side panel itself cannot be driven by Playwright), runs each checklist
item, and prints a JSON report with pass/fail and the CSP errors seen.

Pass a URL instead of an extension directory to run the same checklist against
a plain web page (the baseline).

Usage: python run_spike.py <extension_dir | url> [--option {a,b}]
       [--screenshot png]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import tempfile
from pathlib import Path
from typing import Any

from playwright.async_api import (
    BrowserContext,
    FrameLocator,
    Page,
    async_playwright,
)

BOOT_TIMEOUT_MS = 180_000
STEP_TIMEOUT_MS = 20_000
BOOT_CHECK = "Pyodide boots, worker starts, cell runs"


class Report:
    def __init__(self) -> None:
        self.results: dict[str, dict[str, Any]] = {}
        self.console: list[str] = []
        self.history: list[str] = []

    def log(self, message: str) -> None:
        self.console.append(message)
        self.history.append(message)

    async def check(self, name: str, fn: Any) -> None:
        try:
            await fn()
            self.results[name] = {"pass": True}
        except Exception as error:  # noqa: BLE001
            first_line = str(error).strip().splitlines()[0][:200]
            self.results[name] = {"pass": False, "error": first_line}

    def csp_errors(self) -> list[str]:
        needles = ("Content Security Policy", "Refused to", "unsafe-eval")
        return sorted(
            {m[:300] for m in self.history if any(n in m for n in needles)}
        )


async def wait_for_kernel(report: Report) -> None:
    for _ in range(BOOT_TIMEOUT_MS // 500):
        if any("id: initialized" in m for m in report.console):
            return
        await asyncio.sleep(0.5)
    raise TimeoutError("kernel did not initialize")


async def launch(extension: Path | None, profile: Path) -> BrowserContext:
    playwright = await async_playwright().start()
    if extension is None:
        return await playwright.chromium.launch_persistent_context(
            str(profile), channel="chromium", headless=True
        )
    return await playwright.chromium.launch_persistent_context(
        str(profile),
        channel="chromium",
        headless=True,
        args=[
            f"--disable-extensions-except={extension}",
            f"--load-extension={extension}",
        ],
    )


async def extension_id(context: BrowserContext) -> str:
    worker = (
        context.service_workers[0]
        if context.service_workers
        else await context.wait_for_event("serviceworker")
    )
    return worker.url.split("/")[2]


def root_of(page: Page, option: str) -> Page | FrameLocator:
    return page.frame_locator("iframe") if option == "b" else page


async def persistence(
    page: Page, root: Page | FrameLocator, report: Report, url: str
) -> None:
    async def first_run() -> None:
        await root.get_by_text(
            "run count persisted on disk: 1"
        ).first.wait_for(timeout=STEP_TIMEOUT_MS)

    await report.check("filesystem cell writes file", first_run)
    await asyncio.sleep(3)

    async def after_reload() -> None:
        report.console.clear()
        await page.goto(url)
        await wait_for_kernel(report)
        await root.locator('[data-testid="run-button"]').last.click()
        await root.get_by_text(
            "run count persisted on disk: 2"
        ).first.wait_for(timeout=BOOT_TIMEOUT_MS)

    await report.check(
        "IndexedDB filesystem persists across reload", after_reload
    )


async def run(
    target: str, option: str, screenshot: Path | None
) -> dict[str, Any]:
    is_url = target.startswith("http")
    extension = None if is_url else Path(target).resolve()
    report = Report()
    with tempfile.TemporaryDirectory(prefix="spike-profile-") as profile:
        context = await launch(extension, Path(profile))
        if not is_url:
            ext_id = await extension_id(context)
            report.results["extension loads (service worker)"] = {"pass": True}
        page = await context.new_page()
        page.on("console", lambda m: report.log(m.text))
        page.on("pageerror", lambda e: report.log(f"pageerror: {e}"))
        url = (
            target if is_url else f"chrome-extension://{ext_id}/sidepanel.html"
        )
        await page.goto(url)
        root = root_of(page, option)

        async def cell_runs() -> None:
            await wait_for_kernel(report)
            # Wasm edit mode does not run cells on load.
            await root.locator('[data-testid="run-button"]').last.click()
            await root.get_by_text("slider value: 3").first.wait_for(
                timeout=STEP_TIMEOUT_MS * 3
            )

        async def slider() -> None:
            handle = root.get_by_role("slider").first
            await handle.focus()
            await handle.press("ArrowRight")
            await root.get_by_text("slider value: 4").first.wait_for(
                timeout=STEP_TIMEOUT_MS
            )

        async def altair() -> None:
            await root.locator(
                ".vega-embed svg path.role-mark, .vega-embed canvas"
            ).first.wait_for(timeout=STEP_TIMEOUT_MS)

        async def anywidget() -> None:
            button = root.locator("#spike-anywidget").first
            await button.wait_for(timeout=STEP_TIMEOUT_MS)
            await button.click()
            await root.get_by_text("count is 1").first.wait_for(
                timeout=STEP_TIMEOUT_MS
            )

        async def html_script() -> None:
            await root.get_by_text("external script ran").first.wait_for(
                timeout=STEP_TIMEOUT_MS
            )

        async def iframe_script() -> None:
            inner = root.frame_locator("iframe[srcdoc]").first
            await inner.get_by_text("iframe script ran").wait_for(
                timeout=STEP_TIMEOUT_MS
            )

        async def iframe_resize() -> None:
            # `__resizeIframe` grows the iframe from 100px to fit its content.
            iframe = root.locator("iframe[srcdoc]").first
            for _ in range(STEP_TIMEOUT_MS // 250):
                height = await iframe.evaluate("e => e.style.height")
                if height not in ("", "100px"):
                    return
                await asyncio.sleep(0.25)
            raise AssertionError(f"iframe was not resized: {height!r}")

        await report.check(BOOT_CHECK, cell_runs)
        if report.results[BOOT_CHECK]["pass"]:
            await report.check("mo.ui slider", slider)
            await report.check("Altair chart renders", altair)
            await report.check("anywidget renders and syncs", anywidget)
            await report.check("mo.Html <script src> runs", html_script)
            await report.check("mo.iframe inline script runs", iframe_script)
            await report.check(
                "inline onload handler runs (iframe resize)", iframe_resize
            )
            await persistence(page, root, report, url)
        if screenshot:
            await page.screenshot(path=str(screenshot))
        report.results["_csp_errors"] = {"errors": report.csp_errors()}
        report.results["_all_console_errors"] = {
            "errors": sorted({m[:300] for m in report.history if "rror" in m})[
                :30
            ]
        }
        await context.close()
    return report.results


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("target")
    parser.add_argument("--option", choices=["a", "b"], default="a")
    parser.add_argument("--screenshot", type=Path)
    args = parser.parse_args()
    results = asyncio.run(run(args.target, args.option, args.screenshot))
    print(json.dumps(results, indent=2))
