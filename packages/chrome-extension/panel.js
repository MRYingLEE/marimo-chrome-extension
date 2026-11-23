const seed = "__SEED__";
const KEY = "notebook";
const frame = document.querySelector("iframe");
const openButton = document.querySelector("#open");
const fileInput = document.querySelector("#file");
const downloadButton = document.querySelector("#download");
const status = document.querySelector("#status");

let notebook = { code: seed, filename: "notebook.py" };
// Set from `open` until the reloaded sandbox reports `ready`. Saves in that
// window come from the notebook being replaced, so they must not be stored.
let reloading = false;

function isNotebook(value) {
  return typeof value?.code === "string" && typeof value.filename === "string";
}

function persist() {
  return chrome.storage.local.set({ [KEY]: notebook });
}

async function restore() {
  try {
    const { [KEY]: stored } = await chrome.storage.local.get(KEY);
    if (isNotebook(stored)) {
      notebook = { code: stored.code, filename: stored.filename };
    }
  } catch (error) {
    console.error("Could not read the stored notebook; using the seed", error);
  }
  frame.src = "sandbox/index.html";
}

window.addEventListener("message", (event) => {
  if (event.source !== frame.contentWindow || event.origin !== "null") {
    return;
  }
  const message = event.data;
  if (message?.type === "ready") {
    reloading = false;
    openButton.disabled = false;
    // The sandbox has an opaque origin, so it cannot be targeted by URL.
    frame.contentWindow.postMessage(
      { type: "init", code: notebook.code, filename: notebook.filename },
      "*",
    );
  } else if (message?.type === "reload") {
    if (reloading) {
      frame.src = "sandbox/index.html";
    }
  } else if (message?.type === "save" && typeof message.code === "string") {
    if (reloading) {
      return;
    }
    notebook = { code: message.code, filename: notebook.filename };
    persist();
  }
});

openButton.addEventListener("click", () => fileInput.click());

fileInput.addEventListener("change", async () => {
  const file = fileInput.files[0];
  fileInput.value = "";
  if (!file) {
    return;
  }
  if (!file.name.toLowerCase().endsWith(".py")) {
    status.textContent = "Choose a .py file.";
    return;
  }
  status.textContent = "";
  const code = await file.text();
  notebook = { code, filename: file.name };
  reloading = true;
  await persist();
  frame.contentWindow.postMessage(
    { type: "open", code, filename: file.name },
    "*",
  );
});

downloadButton.addEventListener("click", () => {
  const url = URL.createObjectURL(
    new Blob([notebook.code], { type: "text/x-python" }),
  );
  const link = document.createElement("a");
  link.href = url;
  link.download = notebook.filename;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 0);
});

restore();
