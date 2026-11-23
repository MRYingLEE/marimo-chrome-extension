const assert = require("node:assert/strict");
const { readFileSync } = require("node:fs");
const { join } = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

function element() {
  const listeners = new Map();
  return {
    disabled: false,
    textContent: "",
    value: "",
    files: [],
    addEventListener(type, listener) {
      listeners.set(type, listener);
    },
    dispatch(type) {
      return listeners.get(type)();
    },
    click() {},
  };
}

async function setup(storage) {
  const open = element();
  const file = element();
  const download = element();
  const status = element();
  const frame = {
    src: "",
    contentWindow: { postMessage() {} },
  };
  const elements = {
    iframe: frame,
    "#open": open,
    "#file": file,
    "#download": download,
    "#status": status,
  };
  let onMessage;
  const context = {
    chrome: { storage: { local: storage } },
    document: { querySelector: (selector) => elements[selector] },
    window: {
      addEventListener: (_, listener) => {
        onMessage = listener;
      },
    },
    console: { error() {} },
  };
  vm.runInNewContext(
    readFileSync(join(__dirname, "panel.js"), "utf8"),
    context,
  );
  await new Promise(setImmediate);
  return {
    open,
    file,
    download,
    status,
    frame,
    message(data) {
      onMessage({ source: frame.contentWindow, origin: "null", data });
    },
  };
}

test("serializes saves before replacing the notebook and ignores old saves", async () => {
  const firstWrite = deferred();
  const writes = [];
  const panel = await setup({
    get: async () => ({}),
    set: (value) => {
      writes.push({ ...value.notebook });
      return writes.length === 1 ? firstWrite.promise : Promise.resolve();
    },
    remove: async () => {},
  });
  panel.message({ type: "ready" });
  panel.message({ type: "save", code: "old edit" });
  panel.file.files = [{ name: "new.py", text: async () => "new notebook" }];
  const opening = panel.file.dispatch("change");
  await new Promise(setImmediate);
  panel.message({ type: "save", code: "late old edit" });
  assert.deepEqual(writes, [{ code: "old edit", filename: "notebook.py" }]);
  firstWrite.resolve();
  await opening;
  assert.deepEqual(writes, [
    { code: "old edit", filename: "notebook.py" },
    { code: "new notebook", filename: "new.py" },
  ]);
  assert.equal(panel.frame.src, "sandbox/index.html");
  assert.equal(panel.open.disabled, true);
  panel.message({ type: "ready" });
  assert.equal(panel.open.disabled, false);
});

test("keeps and saves the latest old edit when opening fails", async () => {
  const failedWrite = deferred();
  const writes = [];
  const panel = await setup({
    get: async () => ({}),
    set: (value) => {
      writes.push({ ...value.notebook });
      return writes.length === 1 ? failedWrite.promise : Promise.resolve();
    },
    remove: async () => {},
  });
  panel.message({ type: "ready" });
  panel.file.files = [{ name: "new.py", text: async () => "new notebook" }];
  const opening = panel.file.dispatch("change");
  await new Promise(setImmediate);
  panel.message({ type: "save", code: "latest old edit" });
  failedWrite.reject(new Error("storage failed"));
  await opening;
  await new Promise(setImmediate);
  assert.deepEqual(writes, [
    { code: "new notebook", filename: "new.py" },
    { code: "latest old edit", filename: "notebook.py" },
  ]);
  assert.match(panel.status.textContent, /Could not open/);
  assert.equal(panel.open.disabled, false);
});

test("does not start with the seed when reading stored data fails", async () => {
  const panel = await setup({
    get: async () => {
      throw new Error("storage failed");
    },
    set: async () => {},
    remove: async () => {},
  });
  assert.equal(panel.frame.src, "");
  assert.match(panel.status.textContent, /Could not load stored data/);
});

test("keeps the current notebook when the selected file cannot be read", async () => {
  const writes = [];
  const panel = await setup({
    get: async () => ({}),
    set: async (value) => writes.push(value),
    remove: async () => {},
  });
  panel.message({ type: "ready" });
  panel.file.files = [
    {
      name: "new.py",
      text: async () => {
        throw new Error("read failed");
      },
    },
  ];
  await panel.file.dispatch("change");
  assert.deepEqual(writes, []);
  assert.match(panel.status.textContent, /Could not open/);
  assert.equal(panel.open.disabled, false);
  assert.equal(panel.download.disabled, false);
});

test("reports a failed save and continues processing later writes", async () => {
  const writes = [];
  const panel = await setup({
    get: async () => ({}),
    set: async (value) => {
      writes.push({ ...value.notebook });
      if (writes.length === 1) {
        throw new Error("storage failed");
      }
    },
    remove: async () => {},
  });
  panel.message({ type: "save", code: "first" });
  await new Promise(setImmediate);
  assert.match(panel.status.textContent, /Could not save notebook/);
  panel.message({ type: "save", code: "second" });
  await new Promise(setImmediate);
  assert.deepEqual(writes, [
    { code: "first", filename: "notebook.py" },
    { code: "second", filename: "notebook.py" },
  ]);
  assert.equal(panel.status.textContent, "");
});
