# Design: marimo in a Chrome side panel

Status: proposal. Nothing here is implemented yet.

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

## Out of scope (for now)

- Chrome Web Store publishing (review, remote-code policy, listing).
- Firefox and Safari.
- Interaction with the open web page, such as content scripts or reading page
  data into a notebook.
- Installing packages from PyPI at runtime.
