/* Copyright 2026 Marimo. All rights reserved. */

import { describe, expect, it, vi } from "vitest";
import { InMemoryStorage } from "../storage/storage";

describe("InMemoryStorage", () => {
  it("seeds from the snapshot and mirrors writes to the sink", () => {
    const onWrite = vi.fn();
    const storage = new InMemoryStorage({ a: "1" }, onWrite);

    expect(storage.getItem("a")).toBe("1");

    storage.setItem("b", "2");
    storage.removeItem("a");

    expect(storage.getItem("a")).toBeNull();
    expect(onWrite.mock.calls).toEqual([
      ["b", "2"],
      ["a", null],
    ]);
  });

  it("reports every stored key as removed on clear", () => {
    const onWrite = vi.fn();
    const storage = new InMemoryStorage({ a: "1", b: "2" }, onWrite);

    storage.clear();

    expect(storage.length).toBe(0);
    expect(onWrite.mock.calls).toEqual([
      ["a", null],
      ["b", null],
    ]);
  });

  it("works without a sink", () => {
    const storage = new InMemoryStorage();

    storage.setItem("key", "value");

    expect(storage.getItem("key")).toBe("value");
  });
});
