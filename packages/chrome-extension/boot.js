async function initialize(event) {
  const message = event.data;
  if (
    event.source !== parent ||
    message?.type !== "init" ||
    typeof message.code !== "string" ||
    typeof message.filename !== "string"
  ) {
    return;
  }
  window.removeEventListener("message", initialize);
  document.querySelector("marimo-code").textContent = encodeURIComponent(
    message.code,
  );
  await import("__ENTRYPOINT__");
}

window.addEventListener("message", initialize);
parent.postMessage({ type: "ready" }, "*");
