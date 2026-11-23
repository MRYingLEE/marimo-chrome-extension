/* Copyright 2026 Marimo. All rights reserved. */

import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { registerIframeHeightListener } from "../iframe-height";

function createIframe(): HTMLIFrameElement {
  const iframe = document.createElement("iframe");
  document.body.append(iframe);
  return iframe;
}

function heightsOf(iframes: HTMLIFrameElement[]): string[] {
  return iframes.map((iframe) => iframe.style.height);
}

function dispatchFrom(source: MessageEventSource | null, data: unknown): void {
  window.dispatchEvent(new MessageEvent("message", { data, source }));
}

beforeEach(() => {
  document.body.replaceChildren();
  registerIframeHeightListener();
});

afterEach(() => {
  document.body.replaceChildren();
});

describe("registerIframeHeightListener", () => {
  it("sets the height of the iframe that sent the report", () => {
    const iframe = createIframe();

    dispatchFrom(iframe.contentWindow, {
      type: "marimo:iframe-height",
      height: 240,
    });

    expect(heightsOf([iframe])).toEqual(["240px"]);
  });

  it("rounds fractional heights up to whole pixels", () => {
    const iframe = createIframe();

    dispatchFrom(iframe.contentWindow, {
      type: "marimo:iframe-height",
      height: 240.2,
    });

    expect(heightsOf([iframe])).toEqual(["241px"]);
  });

  it("resizes only the iframe matching the sender", () => {
    const first = createIframe();
    const second = createIframe();

    dispatchFrom(second.contentWindow, {
      type: "marimo:iframe-height",
      height: 300,
    });

    expect(heightsOf([first, second])).toEqual(["", "300px"]);
  });

  it.each([
    ["the page window itself", () => window],
    ["no source", () => null],
  ])("ignores a valid report from %s", (_label, getSource) => {
    const iframe = createIframe();

    dispatchFrom(getSource(), { type: "marimo:iframe-height", height: 240 });

    expect(heightsOf([iframe])).toEqual([""]);
  });

  it("ignores a valid report from an iframe removed from the page", () => {
    const removed = createIframe();
    const removedWindow = removed.contentWindow;
    removed.remove();
    const kept = createIframe();

    dispatchFrom(removedWindow, { type: "marimo:iframe-height", height: 240 });

    expect(heightsOf([kept])).toEqual([""]);
  });

  it.each([
    ["null data", null],
    ["a string", "240"],
    ["an unknown type", { type: "marimo:other", height: 240 }],
    ["a missing height", { type: "marimo:iframe-height" }],
    ["a string height", { type: "marimo:iframe-height", height: "240" }],
    ["a NaN height", { type: "marimo:iframe-height", height: Number.NaN }],
    [
      "an infinite height",
      { type: "marimo:iframe-height", height: Number.POSITIVE_INFINITY },
    ],
    ["a negative height", { type: "marimo:iframe-height", height: -1 }],
    ["a height above the cap", { type: "marimo:iframe-height", height: 100_001 }],
  ])("ignores a report with %s", (_label, data) => {
    const iframe = createIframe();

    dispatchFrom(iframe.contentWindow, data);

    expect(heightsOf([iframe])).toEqual([""]);
  });
});
