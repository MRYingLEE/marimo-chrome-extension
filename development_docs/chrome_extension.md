# Design: marimo in a Chrome side panel

Status: all five phases are implemented. The [spike](#spike) chose option B.
The extension restores the notebook from `chrome.storage.local`, opens local
`.py` files, saves by download, and auto-sizes `mo.iframe` outputs. Phase 5
added Vitest coverage for the parent save store and the offline runtime notes
in [`pyodide.md`](pyodide.md).

Goal: run a Pyodide-based marimo notebook in the Chrome side panel, fully
in the browser, without a marimo server or a runtime network dependency.

## Decisions

| Topic | Decision |
| --- | --- |
| Browsers | Chromium family (Chrome, Edge), Manifest V3, `chrome.sidePanel` |
| Distribution | Unpacked (developer load). Web Store is out of scope for now. |
| Runtime delivery | Bundle Pyodide, the marimo wheel, and packages. No CDN at runtime. |
| Notebook source | A bundled demo notebook, plus opening a local `.py` file |
| Default view | Edit mode |

## Install the extension

[Download the extension (v0.0.4)](../packages/chrome-extension/marimo-chrome-extension-0.0.4.zip?raw=1),
then extract the archive to a folder. In Chrome or Edge, open
`chrome://extensions` or `edge://extensions`, enable **Developer mode**, and
select **Load unpacked**. Choose the extracted folder containing
`manifest.json`, then open marimo from the extensions toolbar. Keep the folder
in place while the extension is installed.

The extension runs notebooks locally but does not block notebook network
access. Only open trusted notebooks.

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
| Inline `<script>` | `frontend/index.html` (`__MARIMO_MOUNT_CONFIG__`) and `wasm_notebook_template` (export context, `file:` warning). The `__resizeIframe` script was removed in phase 4. |
| Inline event handlers | The `onload="__resizeIframe(this)"` attribute in output formatters was removed in phase 4. The iframe height reporter is an inline `<script>` in the iframe content, see [Iframe resizing](#iframe-resizing). |
| `eval` / `new Function` | Vega expression compiling (Altair charts). Vega does not use `vega-interpreter` in marimo today. Possibly other renderers. |
| `blob:` / remote module imports | anywidget ESM in `frontend/src/plugins/impl/anywidget/widget-binding.ts` |
| Scripts inside `srcdoc` iframes | `srcdoc` iframes inherit the parent CSP, so HTML outputs that carry scripts break |

Pyodide must also work with only `'wasm-unsafe-eval'`. The spike must confirm
this.

### Hosting options (decided by the spike: B)

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
  `localStorage` throw, which breaks `WasmFileSystem` persistence. marimo
  already falls back to in-memory storage, and workers start through its
  existing `data:` wrapper once the sandbox CSP allows it.

The rule was: prefer A if the broken outputs can be fixed with small, general
frontend changes that also help strict-CSP web deployments. They cannot (see
[Spike](#spike)), so the extension uses B.

## Architecture (option B)

```
toolbar action ─► background service worker
                   - sidePanel.setPanelBehavior({ openPanelOnActionClick: true })
side panel ─► sidepanel.html  (extension page, strict CSP, has chrome.* APIs)
               ├─ panel.js    (the only code that uses chrome.*: restores the notebook
               │               from chrome.storage.local, or the seed; saves; downloads)
               └─ <iframe src="sandbox/index.html">
                    sandboxed page (opaque origin, relaxed CSP, no chrome.*)
                    output of `marimo export html-wasm --offline`, post-processed
                    ├─ boot.js         (waits for the parent's notebook, then loads the app)
                    ├─ inline-N.js     (the export's former inline scripts)
                    ├─ assets/…        (frontend build)
                    ├─ pyodide/ packages/ lockfile/   (offline runtime)
                    └─ module worker ─► Pyodide ─► marimo-base from packages/
```

The two pages talk only through `postMessage`. The sandbox owns everything
that executes notebook output. The parent owns persistence and is the only
place that calls `chrome.*`.

Messages. The parent accepts a message only when `event.source` is its iframe
and `event.origin` is `"null"`. The sandbox accepts a message only when
`event.source` is its parent and the payload has the expected string fields:

| Direction | Message | Purpose |
| --- | --- | --- |
| sandbox → parent | `ready` | `boot.js` is loaded and waits for the notebook |
| parent → sandbox | `init { code, filename }` | Sent once per sandbox load. The notebook from `chrome.storage.local`, or the seed |
| sandbox → parent | `save { code }` | The notebook changed, so the parent stores it |
When a user opens a file, the parent persists it and reloads the sandbox
directly. The new sandbox receives the file in its `init` message.

### Iframe resizing

Output iframes (for example `mo.iframe`) cannot be measured from the parent,
because the sandbox's opaque origin blocks `contentWindow.document`. Instead,
each iframe's content posts its height to its parent window:

- The reporter is an inline `<script>` appended to the iframe's HTML by
  [`src_or_src_doc`](../marimo/_output/formatters/utils.py). It posts
  `{ type: "marimo:iframe-height", height }` with target origin `"*"`, because
  a sandboxed child has an opaque origin. It reports on `ResizeObserver` and
  on `load`. The `load` report covers frames the browser has not rendered yet.
- The receiver is `registerIframeHeightListener` in
  [`iframe-height.ts`](../frontend/src/utils/iframe-height.ts). It runs in the
  sandbox page, because that is the window whose child iframes post to it. It
  accepts a message only when `event.source` is the `contentWindow` of an
  iframe in the document, and when the payload passes a zod schema (a number
  from 0 to 100000). It then sets that iframe's height. `panel.js` is not a
  receiver, because it only sees messages from its own sandbox frame.
- The reporter grows the iframe but never shrinks it. Once the iframe is as
  tall as its content, nothing is reported, so a later decrease in content
  height leaves the iframe at its larger size.

### Build pipeline (`packages/chrome-extension`)

A private pnpm workspace package with no npm dependencies. With the development
Python environment active, run from the repository root:

```sh
make fe && make py
python -B packages/chrome-extension/scripts/build.py
```

1. Build `marimo` and `marimo-base` wheels at the same `<version>+chromeext`
   version using a temporary copy of the checkout, then install the `marimo`
   wheel and Playwright into an isolated exporter venv.
2. Start a loopback package index for the local `marimo-base` and run
   `marimo export html-wasm seed.py --mode edit --offline --pypi-index-url ...`
   into a temporary export directory. The seed's PEP 723 dependencies decide
   which packages are bundled. The build downloads Chromium into temporary
   storage unless `PLAYWRIGHT_BROWSERS_PATH` points to an existing installation.
3. Post-process the export into `dist/sandbox/` for the CSP. Move each inline
   `<script>` into a file loaded with `<script src>`, and drop the `file:`
   warning. The sandbox page does allow inline scripts, but external files keep
   the extension auditable and the two pages consistent. The post-processor
   also replaces the main `<script type="module">` with `boot.js`, which
   imports it after the handshake. The post-processor sets `AUTO_INSTANTIATE`
   in the generated mount config so the seed runs in edit mode without a click.
   This is a build-time setting, not a change to the editor's default.
4. Add `sidepanel.html` and `panel.js`, `manifest.json`, the background worker,
   and icons.

`dist/` is loaded unpacked through `chrome://extensions`. Do not add an
extension bundler such as `@crxjs/vite-plugin`. The repo's
`minimumReleaseAge` policy in `pnpm-workspace.yaml` would need an exemption,
and the pipeline above does not need one.

To update the distributable archive after rebuilding, run:

```sh
cd packages/chrome-extension/dist
zip -FS -X -r ../marimo-chrome-extension-0.0.4.zip .
```

With pytest and Playwright installed in the development environment
(`python -m playwright install chromium`), run:

```sh
python -m pytest packages/chrome-extension/scripts/test_build_extension.py
node --test packages/chrome-extension/panel.test.cjs
python packages/chrome-extension/scripts/run_spike.py \
  packages/chrome-extension/dist --shell-only
```

### Notebook source and saving

- Phase 3 keeps the code and filename in `chrome.storage.local` under the
  key `notebook`, as `{ code, filename }`. On startup `panel.js` reads that
  key and falls back to the bundled seed when nothing valid is stored.
- The mount config is read synchronously, so the sandbox's `boot.js` writes
  the received code into `<marimo-code>` (URL-encoded, as the export does)
  before it imports the main module. Reading therefore does not go through
  a frontend store.
- Saving uses a write-only `FileStore` in the frontend
  ([`createParentSaveFileStore`](../frontend/src/core/wasm/store.ts)). Its
  `saveFile` posts `save { code }` to the parent, and its `readFile` returns
  `null` synchronously. It is inserted at index 0 of `notebookFileStore` only
  when `<marimo-wasm data-host="chrome-extension">` is set, which the build
  adds to the sandbox page. Detection uses the attribute, not
  `globalThis.chrome`, which does not exist in the sandbox. The store never
  returns code, so read precedence and ordinary WASM exports are unchanged.
  Do not make this store async, because a `Promise<null>` is truthy and would
  win in `CompositeFileStore.readFile`.
- Autosave is forced on for this host. WASM exports set
  `save.autosave = "off"` ([`exporter.py`](../marimo/_export/exporter.py)),
  and the static Save button is hidden at the 500 px sidepanel width.
  `bridge.ts` therefore sets `autosave: "after_delay"` on `userConfigAtom`
  only for `data-host="chrome-extension"`, which the autosave hook reads.
- The parent opens a file from `<input type="file" accept=".py">`, rejects
  other extensions, stores the result, and reloads the sandbox. The Download
  button saves the latest autosaved source as a Blob with the notebook's
  filename.
- Storage writes are serialized within a panel. While replacing a notebook,
  saves from the old sandbox cannot overwrite the new file. If the replacement
  fails, the latest received old save is retained. Storage and file errors
  are shown in the panel; a failed storage read does not start with the seed.
- The manifest requests `unlimitedStorage` for large notebooks.
- Files written by cells are not persisted in the first version. The sandbox
  uses Pyodide's in-memory filesystem, as marimo already does for opaque
  origins. A later change could mirror `/marimo` through the same bridge.


### Manifest (sketch)

```json
{
  "manifest_version": 3,
  "name": "marimo",
  "permissions": ["sidePanel", "storage", "unlimitedStorage"],
  "background": { "service_worker": "background.js", "type": "module" },
  "side_panel": { "default_path": "sidepanel.html" },
  "action": { "default_title": "Open marimo" },
  "sandbox": { "pages": ["sandbox/index.html"] },
  "content_security_policy": {
    "extension_pages": "script-src 'self' 'wasm-unsafe-eval'; object-src 'self'",
    "sandbox": "sandbox allow-scripts allow-forms allow-popups allow-modals; script-src 'self' 'unsafe-inline' 'unsafe-eval' 'wasm-unsafe-eval' blob: data:; worker-src 'self' blob: data:; object-src 'self'"
  }
}
```

The sandbox CSP is the one the spike verified. Do not add `allow-same-origin`:
Chrome then refuses to load the extension. The sandboxed page can load its own
extension files, but it cannot use `chrome.*`, so the sandbox must not rely on
`chrome.runtime`.

## Known limitations

- Only bundled packages work. A notebook that opens a package outside the
  seed set fails, because there is no network fallback by design.
- There is no terminal, no server-side AI, and no real filesystem. The
  virtual filesystem is in memory, so files written by cells are lost when the
  panel closes. The notebook source itself persists in `chrome.storage.local`.
- Opening a file replaces the stored notebook. There is no undo, and there is
  no multi-notebook support.
- Download uses the latest autosaved source; a very recent edit may not yet be
  included. Closing the panel before autosave runs can also lose recent edits.
  Separate open panels do not coordinate writes to the shared notebook.
- `mo.iframe` and other iframe outputs auto-size through a `postMessage` from
  the iframe's content (see [Iframe resizing](#iframe-resizing)). Limits:
  they grow but do not shrink, and the reporter is an inline script, so under
  a strict-CSP host (one without `'unsafe-inline'`) it is blocked and the
  iframe keeps its initial height. The `ipython` formatter's `html.url` case
  passes a URL, not HTML, so no reporter is injected and it does not resize.
  The old handler resized it only for same-origin documents, and the TODO in
  that formatter already noted it did not work. Hosts that defined their own
  `window.__resizeIframe` no longer get it called.
- Notebook output can run arbitrary script with `unsafe-eval` inside the
  sandbox. It cannot reach `chrome.*` or the extension's storage, which is the
  point of B, but it can send messages to the parent bridge (including notebook
  and UI storage writes) and access the network. Only open trusted notebooks.
- The edit layout was checked at 320, 400, and 500 px by opening the panel
  document in Chromium. The notebook and seed chart fit, but the left icon
  rail takes up a noticeable share of the 320 px viewport. Code wraps more
  often, and the floating controls overlap the right edge of cells while
  scrolling. These editor layout issues are unchanged.
- The bundle is large (tens of MB). Pyodide loads every time the panel opens,
  and it reloads when the panel is closed.

## Phases

1. **Spike (done).** Chose option B. See [Spike](#spike).
2. **Extension shell (done).** Package, build script, `sidepanel.html` and `panel.js`
   (iframe plus handshake with a hard-coded seed), sandbox manifest, background
   worker, CSP post-processing including `boot.js`. Promote the spike scripts
   (`build_wheels.py`, `local_index.py`, `build_extension.py`) into the
   package build. Includes pytest coverage for the post-processor and an
   unpacked Chromium smoke check for automatic seed execution.
3. **Notebook I/O (done).** `chrome.storage.local` persistence in the parent,
   the `init`, `save`, `open`, and `reload` messages, the write-only file store
   in the frontend, the `.py` picker, and saving by download. See
   [Notebook source and saving](#notebook-source-and-saving).
4. **Sandbox polish (done).** Iframe outputs report their height with
   `postMessage` instead of `__resizeIframe` reading `contentWindow.document`.
   The inline `onload` handlers and the `index.html` resizer were removed.
   See [Iframe resizing](#iframe-resizing) and
   [Phase 4 checks](#phase-4-checks-option-b-unpacked-chromium).
5. **Tests and docs (done).**
   - Unit tests (Vitest) for the file store, in `store.test.ts` and the
     `data-host` insertion in `bridge.test.ts`.
   - A section in [`pyodide.md`](pyodide.md) on the offline runtime and the
     extension's use of it.

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
  lacks the 'allow-same-origin' flag`. Fixed: the editor's `PanelGroup`s in
  `app-chrome.tsx` take `availableStorage`, so `react-resizable-panels` never
  reads `localStorage` in the sandbox. `availableStorage` tries localStorage,
  then sessionStorage, then the parent bridge (see Phase 4), then in-memory.
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

### Phase 3 checks (option B, unpacked Chromium)

`run_spike.py dist --option b` on the phase 3 build. Each run uses a new
profile. The phase 3 checks all pass:

| Check | Result |
| --- | --- |
| First run falls back to the bundled seed | pass |
| Opens a local `.py` file | pass |
| Edit is saved to `chrome.storage.local` | pass |
| Edit is restored after reload | pass |
| Download saves the current source with its filename | pass |

Phase 2-era checks in the same run: the slider step fails (timeout waiting for
`slider value: 4`), the inline `onload` iframe resize fails (as in the spike
table), and "filesystem cell writes file" fails (timeout waiting for
`run count persisted on disk: 1`). The IndexedDB check passes. At
`de4497d78`, the same harness gives the same results for the slider, iframe
resize, and filesystem checks. These failures predate phase 3. The slider
result contradicts the B column above. Its cause is not yet known.

Console output in B: the `localStorage` `SecurityError` from
`react-resizable-panels`, and `Blocked a frame with origin "null"`. Both are
known and do not affect the phase 3 checks.

### Phase 4 checks (option B, unpacked Chromium)

`run_spike.py dist --option b` (full) and `run_spike.py dist --shell-only`
on the phase 4 build. Run without `--option b`, the default option A panel
fails at the cell run, as in the spike table.

| Check | Result |
| --- | --- |
| Extension loads, service worker runs | pass |
| Pyodide boots, worker starts, cell runs | pass |
| `mo.iframe` resizes to content (new: the 100 px iframe grows to its 900 px content) | pass |
| `mo.ui` slider, Altair chart, anywidget, `<script src>`, `mo.iframe` inline script | pass |
| IndexedDB filesystem persists across reload | pass |
| Phase 3 notebook I/O (seed fallback, open, save, restore, download) | pass |
| Filesystem cell writes file | fail (timeout). This check failed before phase 3 too. |

No CSP errors are reported. After the panel storage fix and the build fixes
(the export no longer bundles the uv cache as a local wheel, and the unused
`gradient`/`noise` preloads are removed), a fresh profile's console has no
error messages. The `[iframe]` info logs are expected in the embedded context.

The panel saves the notebook to `chrome.storage.local`, and restore prefers
that copy over the embedded seed.

UI state (sidebar, panel layout) persists through a storage bridge. The sandbox
has no `localStorage` or `indexedDB`, so `boot.js` sets
`window.marimoParentStorage` before importing marimo. It holds a snapshot of
the `ui:` keys from `init.storage`, and its writes go to the panel as
`{ type: "storage", key, value }`. `panel.js` mirrors each write to
`chrome.storage.local` under `ui:<key>`. A `null` value removes the key. The
bridge is read at marimo's import time, so the snapshot must be sent in `init`. A profile saved by an older build can keep
a stale PEP 723 dependency (such as `uv-cache==…`), which makes every load fail
with `Failed to load packages from micropip`. Rebuilding does not replace the
stored notebook. Remove the extension or clear its storage to reset it.

Vitest covers the listener (`iframe-height.test.ts`), and the Python formatter
and template tests pass. Two gaps remain. The check runs only in headless
Chromium. While debugging, a child iframe in headless Chromium did not run
`requestAnimationFrame`, so its `ResizeObserver` never fired. The reporter
therefore also reports on `load`. Whether the side panel in headed Chrome
behaves the same way is not verified. Under a strict-CSP web host, the inline
reporter is blocked, which is a known limit above.

Option A fails on anywidget and `mo.iframe` because
both need to execute code that only exists at runtime. MV3 `extension_pages`
CSP cannot allow `data:`, `blob:` or `unsafe-eval`, so no frontend change can
fix them. The decision rule needs fixes that are small and general, and these
are not. A Vega interpreter fix would only cover one of the four failures.

B costs us IndexedDB. The sandbox has an opaque origin, so `localStorage`,
`sessionStorage`, and `indexedDB` all throw `SecurityError` there, including in
the Pyodide worker. Pyodide therefore uses its in-memory filesystem, and files
written by cells are lost when the panel closes. UI state is bridged to
`chrome.storage.local` (see Phase 4). Phase 3 therefore added a persistence bridge: the parent extension
page owns storage and the sandbox talks to it through `postMessage`. The
notebook source goes through the parent (`chrome.storage.local`). Persisting
arbitrary files under `/marimo` is new work and is still not supported.

The design sections above are written for B. Notable changes from the first
proposal: the notebook is read through `<marimo-code>` instead of a store at
index 0, and Phase 4 shrank to the iframe resize fix.

## Out of scope (for now)

- Chrome Web Store publishing (review, remote-code policy, listing).
- Firefox and Safari.
- Interaction with the open web page, such as content scripts or reading page
  data into a notebook.
- Installing packages from PyPI at runtime.
