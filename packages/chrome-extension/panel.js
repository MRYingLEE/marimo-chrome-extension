const seed = "__SEED__";
const KEY = "notebook";
const UI_PREFIX = "ui:";
const SAVE_ERROR = "Could not save notebook. Your changes may be lost.";
const UI_STORAGE_ERROR = "Could not save panel settings.";
const frame = document.querySelector("iframe");
const openButton = document.querySelector("#open");
const fileInput = document.querySelector("#file");
const downloadButton = document.querySelector("#download");
const status = document.querySelector("#status");

let notebook = { code: seed, filename: "notebook.py" };
// The sandbox's UI storage (localStorage is blocked there), mirrored to
// chrome.storage.local under `UI_PREFIX` keys.
let uiStorage = new Map();
let reloading = false;
let pendingOldCode = null;
let storageWrites = Promise.resolve();

function isNotebook(value) {
  return typeof value?.code === "string" && typeof value.filename === "string";
}

function writeStorage(operation) {
  const write = storageWrites.then(operation, operation);
  storageWrites = write;
  return write;
}

function persist(value) {
  return writeStorage(() => chrome.storage.local.set({ [KEY]: value }));
}

function reportError(message, error) {
  console.error(message, error);
  status.textContent = message;
}

function clearError(message) {
  if (status.textContent === message) {
    status.textContent = "";
  }
}

function writeUiStorage(key, value) {
  if (value === null) {
    uiStorage.delete(key);
    return writeStorage(() => chrome.storage.local.remove(UI_PREFIX + key));
  }
  if (typeof value !== "string") {
    return;
  }
  uiStorage.set(key, value);
  return writeStorage(() =>
    chrome.storage.local.set({ [UI_PREFIX + key]: value }),
  );
}

async function restore() {
  try {
    const stored = await chrome.storage.local.get(null);
    if (isNotebook(stored[KEY])) {
      notebook = { code: stored[KEY].code, filename: stored[KEY].filename };
    }
    uiStorage = new Map(
      Object.entries(stored)
        .filter(
          ([key, value]) =>
            key.startsWith(UI_PREFIX) && typeof value === "string",
        )
        .map(([key, value]) => [key.slice(UI_PREFIX.length), value]),
    );
  } catch (error) {
    reportError(
      "Could not load stored data. Reload the panel to retry.",
      error,
    );
    return;
  }
  downloadButton.disabled = false;
  frame.src = "sandbox/index.html";
}

window.addEventListener("message", (event) => {
  if (event.source !== frame.contentWindow || event.origin !== "null") {
    return;
  }
  const message = event.data;
  if (message?.type === "ready") {
    reloading = false;
    pendingOldCode = null;
    openButton.disabled = false;
    downloadButton.disabled = false;
    // The sandbox has an opaque origin, so it cannot be targeted by URL.
    frame.contentWindow.postMessage(
      {
        type: "init",
        code: notebook.code,
        filename: notebook.filename,
        storage: Object.fromEntries(uiStorage),
      },
      "*",
    );
  } else if (message?.type === "save" && typeof message.code === "string") {
    if (reloading) {
      pendingOldCode = message.code;
      return;
    }
    notebook = { code: message.code, filename: notebook.filename };
    persist(notebook).then(
      () => clearError(SAVE_ERROR),
      (error) => reportError(SAVE_ERROR, error),
    );
  } else if (message?.type === "storage" && typeof message.key === "string") {
    writeUiStorage(message.key, message.value)?.then(
      () => clearError(UI_STORAGE_ERROR),
      (error) => reportError(UI_STORAGE_ERROR, error),
    );
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
  openButton.disabled = true;
  downloadButton.disabled = true;
  try {
    const code = await file.text();
    const opened = { code, filename: file.name };
    reloading = true;
    await persist(opened);
    notebook = opened;
    frame.src = "sandbox/index.html";
  } catch (error) {
    reloading = false;
    if (pendingOldCode !== null) {
      notebook = { code: pendingOldCode, filename: notebook.filename };
      pendingOldCode = null;
      persist(notebook).then(
        () => clearError(SAVE_ERROR),
        (saveError) => reportError(SAVE_ERROR, saveError),
      );
    }
    openButton.disabled = false;
    downloadButton.disabled = false;
    reportError(
      "Could not open the notebook. The current notebook was kept.",
      error,
    );
  }
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
