# Copyright 2026 Marimo. All rights reserved.
from __future__ import annotations

import marimo._output.data.data as mo_data
from marimo._runtime.context.types import (
    ContextNotInitializedError,
    get_context,
)

# Must post the same type as IFRAME_HEIGHT_MESSAGE_TYPE in
# frontend/src/utils/iframe-height.ts. The target origin is "*" because a
# sandboxed child has an opaque origin; the payload is only a number.
# Reporting on `load` as well as on resize covers frames that the browser has
# not rendered yet, where the ResizeObserver's first callback never runs.
_IFRAME_HEIGHT_REPORTER = """<script>
(function () {
  var root = document.documentElement;
  function report() {
    if (root.scrollHeight === root.clientHeight) {
      return;
    }
    var hasHorizontalScrollbar = root.scrollWidth > root.clientWidth;
    parent.postMessage(
      {
        type: "marimo:iframe-height",
        height: root.scrollHeight + (hasHorizontalScrollbar ? 20 : 0),
      },
      "*"
    );
  }
  new ResizeObserver(report).observe(root);
  window.addEventListener("load", report);
})();
</script>"""


def src_or_src_doc(html_content: str) -> dict[str, str]:
    """
    Depending if virtual files are supported,
    return the appropriate src or srcdoc attribute for an iframe.

    So, we use `srcdoc` when not running a server (e.g. an html export).

    The content reports its height to the parent window, which resizes the
    iframe to fit.
    """
    html_content = f"{html_content}{_IFRAME_HEIGHT_REPORTER}"

    try:
        ctx = get_context()
    except ContextNotInitializedError:
        # If no context, return srcdoc
        return {"srcdoc": html_content}

    if ctx.virtual_files_supported:
        html_file = mo_data.html(html_content)
        return {"src": html_file.url}
    else:
        return {"srcdoc": html_content}
