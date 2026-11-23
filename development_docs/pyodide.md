# marimo + pyodide

## Running the frontend against the latest deploy on PyPi

```bash
cd frontend
PYODIDE=true VITE_WASM_MARIMO_PREBUILT_WHEEL=true pnpm dev
```

## Running the frontend against a local backend

```bash
# build once
uv build
# server and watch for changes
uv run pyodide/build_and_serve.py
# in another terminal
cd frontend
PYODIDE=true pnpm dev
```

## Offline runtime

`marimo export html-wasm --offline` produces a page that loads Pyodide and
packages from the same export, with no CDN or `wasm.marimo.app` requests. The
export resolves packages in [`bundle_wasm_runtime`](../marimo/_export/offline.py),
which loads Pyodide in Chromium at export time and does not run cells. It
writes:

- `pyodide/`: the Pyodide distribution.
- `packages/`: the resolved wheels, plus `packages/index/` for micropip.
- `lockfile/`: a Pyodide lockfile that includes `marimo-base`.

The page points `data-pyodide-index-url`, `data-pyodide-lockfile-url`, and
`data-pypi-index-url` at these relative paths. The worker in
[`bootstrap.ts`](../frontend/src/core/wasm/worker/bootstrap.ts) uses those
URLs, so the CDN and `wasm.marimo.app` fallbacks are not reached. The
trade-off is that only packages bundled at export time can be imported.

### Chrome extension

The [Chrome extension](chrome_extension.md) runs this offline export inside
its sandboxed page. `packages/chrome-extension/scripts/build.py` exports a
seed notebook with `--offline`. Its PEP 723 dependencies decide what is bundled.
`--pypi-index-url` points at a loopback index that serves the `marimo-base`
wheel built from the checkout, so the bundled runtime matches the frontend. The
post-processed output is `dist/sandbox/`. Nothing in the bundle needs the
network at runtime. The sandbox CSP does not restrict connections (it sets no
`connect-src`), so this is a property of the bundle, not something the CSP
enforces. A package outside the bundled set fails to install, because micropip
only sees the vendored index.
