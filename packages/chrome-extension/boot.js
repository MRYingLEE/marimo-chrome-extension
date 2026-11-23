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
  // The parent stores the opened file before it sends `open`, so the reloaded
  // page receives it through `init`. The sandbox cannot reload itself: its
  // opaque origin may not navigate to extension resources, so the parent does.
  if (message.type === "open") {
    parent.postMessage({ type: "reload" }, "*");
    return;
  }
  if (started || message.type !== "init") {
    return;
  }
  started = true;
  // Set before the entrypoint loads, because marimo reads its storage at import.
  window.marimoParentStorage = {
    snapshot: message.storage ?? {},
    write: (key, value) => parent.postMessage({ type: "storage", key, value }, "*"),
  };
  document.querySelector("marimo-code").textContent = encodeURIComponent(
    message.code,
  );
  await import("__ENTRYPOINT__");
}

window.addEventListener("message", onMessage);
parent.postMessage({ type: "ready" }, "*");
