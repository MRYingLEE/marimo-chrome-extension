/* Copyright 2026 Marimo. All rights reserved. */

import { getIframeCapabilities } from "../capabilities";

/**
 * Storage for embedders that persist values outside the page, such as the
 * Chrome extension panel. `snapshot` seeds the store synchronously, and `write`
 * receives every change (`null` means removed).
 */
export interface ParentStorageBridge {
  snapshot: Record<string, string>;
  write: (key: string, value: string | null) => void;
}

declare global {
  interface Window {
    marimoParentStorage?: ParentStorageBridge;
  }
}

/**
 * In-memory storage implementation of the Storage interface, optionally
 * mirroring writes to an external sink.
 */
export class InMemoryStorage implements Storage {
  private store: Map<string, string>;
  private onWrite?: (key: string, value: string | null) => void;

  constructor(
    initial: Record<string, string> = {},
    onWrite?: (key: string, value: string | null) => void,
  ) {
    this.store = new Map(Object.entries(initial));
    this.onWrite = onWrite;
  }

  public get length(): number {
    return this.store.size;
  }

  public clear(): void {
    for (const key of this.store.keys()) {
      this.onWrite?.(key, null);
    }
    this.store.clear();
  }

  public getItem(key: string): string | null {
    return this.store.get(key) || null;
  }

  public key(index: number): string | null {
    const keys = [...this.store.keys()];
    return keys[index] || null;
  }

  public removeItem(key: string): void {
    this.store.delete(key);
    this.onWrite?.(key, null);
  }

  public setItem(key: string, value: string): void {
    this.store.set(key, value);
    this.onWrite?.(key, value);
  }
}

/**
 * Gets the best available storage. Should only be called once.
 */
function getAvailableStorage(): Storage {
  const { hasLocalStorage, hasSessionStorage } = getIframeCapabilities();

  if (hasLocalStorage) {
    return window.localStorage;
  }

  if (hasSessionStorage) {
    return window.sessionStorage;
  }

  const bridge = window.marimoParentStorage;
  if (bridge) {
    return new InMemoryStorage(bridge.snapshot, bridge.write);
  }

  return new InMemoryStorage();
}

/**
 * The best available storage. Either localStorage, sessionStorage, the parent's
 * storage bridge, or in-memory storage.
 */
export const availableStorage: Storage = getAvailableStorage();
