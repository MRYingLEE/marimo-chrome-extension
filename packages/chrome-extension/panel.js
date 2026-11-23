const seed = "__SEED__";
const frame = document.querySelector("iframe");

window.addEventListener("message", (event) => {
  if (
    event.source !== frame.contentWindow ||
    event.origin !== "null" ||
    event.data?.type !== "ready"
  ) {
    return;
  }
  // The sandbox has an opaque origin, so it cannot be targeted by URL.
  frame.contentWindow.postMessage(
    { type: "init", code: seed, filename: "notebook.py" },
    "*",
  );
});
frame.src = "sandbox/index.html";
