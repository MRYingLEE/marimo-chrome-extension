# Design: marimo in a Chrome side panel

Status: proposal. Phase 1 (the spike) is done and chose option B, see [Spike](#spike).
Nothing else is implemented yet.

Goal: run a Pyodide-based marimo notebook in the Chrome side panel, fully
in the browser, with no marimo server and no network access at runtime.

## Decisions

| Topic | Decision |
| --- | --- |
| Browsers | Chromium family (Chrome, Edge), Manifest V3, `chrome.sidePanel` |
| Distribution | Unpacked (developer load). Web Store is out of scope for now. |
| Runtime delivery | Bundle Pyodide, the marimo wheel, and packages. No CDN at runtime. |
| Notebook source | A bundled demo notebook, plus opening a local `.py` file |
| Default view | Edit mode |

## What already exists

- **WASM page generation.** `wasm_notebook_template` in
  [`marimo/_templates.py`](../marimo/_templates.py) turns the built frontend
  into a WASM page. It fills the mount config and adds `<marimo-wasm>` plus
  `<marimo-code>`. `marimo export html-wasm` uses it. Note that `PYODIDE=true`
  in [`frontend/vite.config.mts`](../frontend/vite.config.mts) only affects the
  dev server, not `vite build`.
- **Offline runtime.** `marimo export html-wasm --offline` calls
  `bundle_wasm_runtime` in [`marimo/_export/offline.py`](../marimo/_export/offline.py).
  It vendors `pyodide/`, `packages/`, and `lockfile/` next to the page and
  points `data-pyodide-*` attributes at them. It resolves packages for one
  specific notebook by running Pyodide in Playwright Chromium at build time.
- **Runtime.** [`bridge.ts`](../frontend/src/core/wasm/bridge.ts) starts a
  module worker ([`worker.ts`](../frontend/src/core/wasm/worker/worker.ts)).
  The worker's [`bootstrap.ts`](../frontend/src/core/wasm/worker/bootstrap.ts)
  loads Pyodide from `data-pyodide-index-url`, falling back to jsdelivr.
  `marimo-base` comes from the lockfile.
- **Notebook source.** [`store.ts`](../frontend/src/core/wasm/store.ts) defines
  `notebookFileStore`, a `CompositeFileStore`. Its order is mount config, then
  `<marimo-code>`, then the URL. The first non-empty store wins, and
  `saveFile` writes to all stores. `insert(index, store)` adds a store.

## The main constraint: MV3 CSP

Chrome does not let `extension_pages` CSP go beyond
`script-src 'self' 'wasm-unsafe-eval'; object-src 'self'`
([docs](https://developer.chrome.com/docs/extensions/reference/manifest/content-security-policy)).
WebAssembly is allowed. These are blocked, and each one affects marimo today:

| Blocked | Where marimo hits it |
| --- | --- |
| Inline `<script>` | `frontend/index.html` (`__resizeIframe`, `__MARIMO_MOUNT_CONFIG__`) and `wasm_notebook_template` (export context, `file:` warning) |
| Inline event handlers | `onload="__resizeIframe(this)"` in output formatters (`marimo/_output/formatting.py`, bokeh, leafmap, pyecharts, ipython) |
| `eval` / `new Function` | Vega expression compiling (Altair charts). Vega does not use `vega-interpreter` in marimo today. Possibly other renderers. |
| `blob:` / remote module imports | anywidget ESM in `frontend/src/plugins/impl/anywidget/widget-binding.ts` |
| Scripts inside `srcdoc` iframes | `srcdoc` iframes inherit the parent CSP, so HTML outputs that carry scripts break |

Pyodide must also work with only `'wasm-unsafe-eval'`. The spike must confirm
this.

### Hosting options (decided by the spike)

**A. Side panel is a normal extension page.**
- Pros: full `chrome.*` APIs, IndexedDB, and same-origin workers.
- Cons: the strict CSP above. The build must move inline scripts into files,
  and some outputs break unless the frontend changes. Examples are Vega with
  its CSP interpreter, and replacing inline `onload` handlers.

**B. Side panel is a thin extension page that embeds a sandboxed page**
(`manifest.sandbox.pages`) in an iframe.
- Pros: the sandbox CSP can allow `'unsafe-inline' 'unsafe-eval'`, so outputs
  work as they do on the web.
- Cons: the sandbox has an opaque origin. It has no `chrome.*` APIs, so the
  parent must handle storage through `postMessage`. IndexedDB and
  `localStorage` probably throw, which breaks `WasmFileSystem` persistence.
  `new Worker(chrome-extension://…)` is cross-origin, so workers would have to
  be built from blobs.

Prefer A if the spike shows the broken outputs can be fixed with small, general
frontend changes that are also useful for strict-CSP web deployments. Otherwise
use B.

## Architecture (option A shown)

```
toolbar action ─► background service worker
                   - sidePanel.setPanelBehavior({ openPanelOnActionClick: true })
side panel ─► sidepanel.html  (output of `marimo export html-wasm --offline`, post-processed)
               ├─ boot.js         (was the inline scripts; reads the notebook from chrome.storage)
               ├─ assets/…        (frontend build)
               ├─ pyodide/ packages/ lockfile/   (offline runtime)
               └─ module worker ─► Pyodide ─► marimo-base from packages/
```

### Build pipeline (`packages/chrome-extension`)

A new pnpm workspace package (the `packages/*` glob already covers it).

1. Build the frontend into `marimo/_static` and the marimo wheel from this
   checkout. The bundled `marimo-base` must match the frontend version. The
   default lockfile pins a released `marimo-base`, so the spike must find how to
   pin the local wheel. Local-wheel support is in `marimo/_export/local_wheels.py`.
2. Run `marimo export html-wasm seed.py --mode edit --offline -o dist/`.
   `seed.py` is the bundled demo notebook. Its PEP 723 dependencies decide
   which packages are bundled.
3. Post-process `dist/` for the CSP. Move each inline `<script>` into a file
   loaded with `<script src>`, and drop the `file:` warning. A test asserts that
   no inline scripts remain.
4. Add `manifest.json`, the background worker, and icons.

`dist/` is loaded unpacked through `chrome://extensions`. Do not add an
extension bundler such as `@crxjs/vite-plugin`. The repo's
`minimumReleaseAge` policy in `pnpm-workspace.yaml` would need an exemption,
and the pipeline above does not need one.

### Notebook source and saving

- Add an extension file store backed by `chrome.storage.local`. It holds the
  current notebook's code and filename.
- Insert it at index 0 of `notebookFileStore` so it wins over `<marimo-code>`.
  The seed notebook then acts only as the first-run default.
- `chrome.storage` is async and the mount config is read synchronously.
  `boot.js` should therefore await storage before it loads the main module.
- To open a notebook, use `<input type="file" accept=".py">` in the panel and
  write the result into the store. To save, download a `.py` file.
- Enable this only when the page is an extension page, for example with a
  `data-host="chrome-extension"` attribute on `<marimo-wasm>`. Do not sniff
  `globalThis.chrome`.
- Request the `unlimitedStorage` permission. Pyodide's IndexedDB filesystem and
  large notebooks can exceed the default quota.

### Manifest (sketch)

```json
{
  "manifest_version": 3,
  "name": "marimo",
  "permissions": ["sidePanel", "storage", "unlimitedStorage"],
  "background": { "service_worker": "background.js", "type": "module" },
  "side_panel": { "default_path": "sidepanel.html" },
  "action": { "default_title": "Open marimo" },
  "content_security_policy": {
    "extension_pages": "script-src 'self' 'wasm-unsafe-eval'; object-src 'self'"
  }
}
```

## Known limitations

- Only bundled packages work. A notebook that opens a package outside the
  seed set fails, because there is no network fallback by design.
- There is no terminal, no server-side AI, and no real filesystem. The
  virtual filesystem persists in IndexedDB.
- The side panel is narrow. The edit layout must be checked at 320 to 500 px.
- The bundle is large (tens of MB). Pyodide loads every time the panel opens,
  and it reloads when the panel is closed.

## Phases

1. **Spike (go/no-go).** Export the seed notebook with `--offline` and load it
   as option A. Record what works:
   - Pyodide boots with only `'wasm-unsafe-eval'`.
   - The worker starts.
   - A cell runs.
   - `mo.ui` widgets work.
   - An Altair chart renders.
   - An anywidget renders.
   - `mo.Html` with a script renders.
   - The IndexedDB filesystem persists.

   If key items fail, try the same with option B. Write the results into this
   document and choose an option.
2. **Extension shell.** Package, build script, manifest, background worker,
   CSP post-processing.
3. **Notebook I/O.** Extension file store, opening a file, saving by download.
4. **CSP fixes.** Only for option A, and only general fixes that also help
   strict-CSP web hosting.
5. **Tests and docs.**
   - Unit tests (Vitest) for the file store and the HTML post-processor.
   - One Playwright test that launches Chromium with `--load-extension=dist`,
     opens `sidepanel.html` directly, and runs a cell.
   - A short section in `development_docs/pyodide.md`.

## Spike

Date: 2026-11-23. Playwright Chromium (build 1255, `channel="chromium"`, headless),
Pyodide from the bundled export, Playwright's `--load-extension`. The
side panel cannot be driven by Playwright, so each run opens
`chrome-extension://<id>/sidepanel.html` in a tab. That page is the same document
the side panel hosts, with the same CSP.

Seed notebook: [`packages/chrome-extension/seed.py`](../packages/chrome-extension/seed.py).
Scripts, all under `packages/chrome-extension/scripts/`:
`build_wheels.py`, `local_index.py`, `build_extension.py`, `run_spike.py`.

### Pinning the local wheel (answers the open question in "Build pipeline")

`marimo export html-wasm --offline` always installs `marimo-base==<exporter's
__version__>` from the package index first, so a local wheel with the same
version as a released one is shadowed by PyPI. The pipeline that works:

1. `build_wheels.py` builds `marimo` (with the frontend) and `marimo-base`
   wheels from this checkout, both versioned `<version>+chromeext`.
2. Install the `marimo` wheel into the environment that runs the exporter, so
   `__version__` is the local version.
3. `local_index.py` serves the `marimo-base` wheel and proxies every other
   project to PyPI. Pass it as `--pypi-index-url http://127.0.0.1:<port>`.

The exported lockfile then contains `marimo-base 0.25.2+chromeext` and
`__MARIMO_MOUNT_CONFIG__.version` is the same, so the runtime matches the
frontend. The export is 58 MB (Pyodide, 52 packages).

### Results

The same checklist ran against the plain web export (served over HTTP) as a
baseline, option A, and option B. The panel for B is a thin extension page with
the export in a sandboxed iframe.

| Item | Web baseline | A: extension page | B: sandboxed page |
| --- | --- | --- | --- |
| Extension loads, service worker runs | n/a | pass | pass |
| Pyodide boots with only `'wasm-unsafe-eval'`, worker starts, cell runs | pass | pass | pass (needs `worker-src data: blob:`) |
| `mo.ui` slider | pass | pass | pass |
| Altair chart (Vega expression) | pass | **fail** | pass |
| anywidget | pass | **fail** | pass |
| `mo.Html` with `<script src>` | pass | pass | pass |
| `mo.iframe` with an inline script | pass | **fail** | pass |
| Inline `onload` handler (`__resizeIframe`) | pass | **fail** | **fail** |
| Pyodide FS persists in IndexedDB across reload | pass | pass | **fail** |

CSP errors seen in A:

- `[react-vega] Error creating view: EvalError: Evaluating a string as
  JavaScript violates ... 'unsafe-eval' is not an allowed source of script`.
- `Failed to fetch dynamically imported module: data:text/javascript;base64,...`
  (anywidget ESM).
- `Executing inline script violates ... script-src 'self' 'wasm-unsafe-eval'`
  and `Executing inline event handler violates ...` (the `mo.iframe` `srcdoc`
  and its `onload`).

Errors seen in B:

- `Creating a worker from 'data:application/javascript,import ...' violates the
  following Content Security Policy directive` with the default sandbox CSP.
  marimo's cross-origin worker fallback uses a `data:` URL, so the sandbox CSP
  needs `worker-src 'self' blob: data:` and `script-src ... blob: data:`.
- `SecurityError: Failed to read the 'localStorage' property ... sandboxed and
  lacks the 'allow-same-origin' flag`. marimo falls back to in-memory storage
  and the panel works.
- `Blocked a frame with origin "null" from accessing a cross-origin frame`.
  `__resizeIframe` reads `contentWindow.document`, so `mo.iframe` does not
  auto-size.
- Adding `allow-same-origin` to the sandbox CSP makes Chrome refuse to load the
  extension, so B cannot get IndexedDB that way.

Other findings:

- Wasm edit mode does not run cells on load (`auto_instantiate` is false). The
  panel needs a "run all" or an `auto_instantiate` setting in the mount config.
- marimo ignores inline `<script>` in `mo.Html`, on the web too. Only
  `<script src>` loads. `mo.iframe` is the supported way to run inline scripts.
- Pyodide's IDBFS is synced only on file operations, not on cell writes.
  `WasmFileSystem.mountFS` already uses an in-memory FS when `origin === "null"`,
  which is what B hits.
- Not tested: whether `ast: true` in the Vega embed options (it uses
  `vega-interpreter`, already a transitive dependency through `vega-embed`)
  fixes Altair in A. Even if it does, it would not help anywidget or
  `mo.iframe`.

### Decision

**Option B**, the sandboxed page. A fails on anywidget and `mo.iframe` because
both need to execute code that only exists at runtime. MV3 `extension_pages`
CSP cannot allow `data:`, `blob:` or `unsafe-eval`, so no frontend change can
fix them. The decision rule needs fixes that are small and general, and these
are not. A Vega interpreter fix would only cover one of the four failures.

B costs us IndexedDB. The sandbox has an opaque origin, so Pyodide uses its
in-memory filesystem and files written by cells are lost when the panel
closes. Phase 3 must therefore add a persistence bridge: the parent extension
page owns storage and the sandbox talks to it through `postMessage`. The
notebook source already goes through the parent (`chrome.storage.local`), so
that part is on the plan. Persisting arbitrary files under `/marimo` is new work
and can start as "not supported".

Consequences for the design above:

- The architecture diagram changes: `sidepanel.html` is a thin page that embeds
  the export at `sandbox/index.html`, listed under `manifest.sandbox.pages`.
- `boot.js` and `chrome.storage` move to the parent. The file store in the
  sandbox is a `postMessage` client.
- The manifest needs a `sandbox` CSP with `'unsafe-inline' 'unsafe-eval'
  blob: data:` and `worker-src 'self' blob: data:`.
- Phase 4 shrinks. Only the `__resizeIframe` height fix (use
  `postMessage` instead of reading `contentWindow.document`) remains, and it is
  cosmetic.

## Out of scope (for now)

- Chrome Web Store publishing (review, remote-code policy, listing).
- Firefox and Safari.
- Interaction with the open web page, such as content scripts or reading page
  data into a notebook.
- Installing packages from PyPI at runtime.
