/* Copyright 2026 Marimo. All rights reserved. */

import z from "zod";

/**
 * Posted by the reporter script injected into iframe outputs.
 * Must match the reporter in `marimo/_output/formatters/utils.py`.
 */
export const IFRAME_HEIGHT_MESSAGE_TYPE = "marimo:iframe-height";

const MAX_IFRAME_HEIGHT = 100_000;

const iframeHeightMessage = z.object({
  type: z.literal(IFRAME_HEIGHT_MESSAGE_TYPE),
  height: z.number().min(0).max(MAX_IFRAME_HEIGHT),
});

// Matching on `event.source` identifies the sender without reading its
// document, which is blocked for opaque-origin (sandboxed) frames.
function findIframeBySource(
  source: MessageEventSource | null,
): HTMLIFrameElement | undefined {
  if (!source) {
    return undefined;
  }
  return [...document.querySelectorAll('iframe')].find(
    (iframe) => iframe.contentWindow === source,
  );
}

function handleMessage(event: MessageEvent): void {
  const iframe = findIframeBySource(event.source);
  if (!iframe) {
    return;
  }
  const parsed = iframeHeightMessage.safeParse(event.data);
  if (!parsed.success) {
    return;
  }
  iframe.style.height = `${Math.ceil(parsed.data.height)}px`;
}

/**
 * Listen for iframe height reports. Safe to call more than once: the same
 * handler reference is added, so the browser keeps a single listener.
 */
export function registerIframeHeightListener(): void {
  window.addEventListener("message", handleMessage);
}
