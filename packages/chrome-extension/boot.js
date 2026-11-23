let started = false;

async function onMessage(event) {
  const message = event.data;
  if (
    event.source !== parent ||
    typeof message?.code !== "string" ||
    typeof message.filename !== "string"
  ) {
    return;
  }
  if (started || message.type !== "init") {
    return;
  }
  started = true;
  // Set before the entrypoint loads, because marimo reads its storage at import.
  window.marimoParentStorage = {
    snapshot: message.storage ?? {},
    write: (key, value) =>
      parent.postMessage({ type: "storage", key, value }, "*"),
  };
  document.querySelector("marimo-code").textContent = encodeURIComponent(
    message.code,
  );
  await import("__ENTRYPOINT__");
}

window.addEventListener("message", onMessage);
parent.postMessage({ type: "ready" }, "*");
