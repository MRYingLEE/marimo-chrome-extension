# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "altair",
#     "anywidget",
#     "marimo",
# ]
# ///

import marimo

__generated_with = "0.25.2"
app = marimo.App()


@app.cell
def _():
    import marimo as mo

    return (mo,)


@app.cell
def _(mo):
    mo.md("""
    # marimo side panel spike

    Each cell below covers one item of the spike checklist.
    """)
    return


@app.cell
def _():
    # 1. A plain cell
    1 + 1
    return


@app.cell
def _(mo):
    # 2. mo.ui widget
    slider = mo.ui.slider(1, 10, value=3, label="n")
    slider
    return (slider,)


@app.cell
def _(mo, slider):
    mo.md(f"slider value: **{slider.value}**")
    return


@app.cell
def _(slider):
    # 3. Altair chart (Vega expressions need eval under a strict CSP)
    import altair as alt
    import pandas as pd

    df = pd.DataFrame(
        {"x": range(slider.value * 3), "y": range(slider.value * 3)}
    )
    alt.Chart(df).mark_point().encode(
        x="x", y="y", tooltip=["x", "y"]
    ).transform_filter("datum.x >= 0").interactive()
    return


@app.cell
def _(mo):
    # 4. Minimal anywidget (ESM is loaded from a blob: URL by marimo)
    import anywidget
    import traitlets

    class CounterWidget(anywidget.AnyWidget):
        _esm = """
        function render({ model, el }) {
          const button = document.createElement("button");
          button.id = "spike-anywidget";
          button.style.cssText =
            "padding: 6px 14px; font-size: 14px; border-radius: 6px; " +
            "border: 1px solid #888; background: #f4f4f5; color: #111; cursor: pointer;";
          const update = () => {
            button.textContent = `count is ${model.get("value")}`;
          };
          button.addEventListener("click", () => {
            model.set("value", model.get("value") + 1);
            model.save_changes();
          });
          model.on("change:value", update);
          update();
          el.appendChild(button);
        }
        export default { render };
        """
        value = traitlets.Int(0).tag(sync=True)

    mo.ui.anywidget(CounterWidget())
    return


@app.cell
def _(mo):
    # 5. mo.Html with a script. marimo ignores inline scripts here and only
    # loads `<script src>`, so the script is a file next to the page.
    mo.Html(
        """
        <div id="spike-html-script">script has not run</div>
        <script src="./spike-script.js"></script>
        """
    )
    return


@app.cell
def _(mo):
    # 6. mo.iframe is the documented way to run inline scripts. The iframe
    # reports its content height via postMessage, so the page fits it to the
    # content; the 100px starting height is what the check expects to grow.
    mo.iframe(
        '<div id="spike-iframe" style="height:900px">script has not run</div>'
        "<script>document.getElementById('spike-iframe').textContent ="
        "'iframe script ran';</script>",
        height="100px",
    )
    return


@app.cell
def _(mo):
    # 7. Virtual filesystem persistence. /marimo is mounted on IndexedDB, which
    # the worker only syncs on file operations, so sync explicitly here.
    from pathlib import Path

    import pyodide_js
    from pyodide.ffi import create_proxy

    path = Path("/marimo/spike_counter.txt")
    count = int(path.read_text()) + 1 if path.exists() else 1
    path.write_text(str(count))
    pyodide_js.FS.syncfs(False, create_proxy(lambda error: None))
    mo.md(f"run count persisted on disk: **{count}**")
    return


if __name__ == "__main__":
    app.run()
