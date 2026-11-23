/** Browser storage under the current `happyclaw.` prefix, reading the pre-rename `octop.` key once. */
const PREFIX = "happyclaw.";
const LEGACY_PREFIX = "octop.";

/**
 * Read a stored value, migrating a value left under the pre-rename prefix.
 *
 * The migration is on read so nobody loses a half-typed chat message or their
 * session-sort choice because of the rename; the legacy key is dropped once its
 * value has been copied across.
 */
export function readStorage(name: string): string | null {
  const current = window.localStorage.getItem(PREFIX + name);
  if (current !== null) return current;
  const legacy = window.localStorage.getItem(LEGACY_PREFIX + name);
  if (legacy !== null) {
    window.localStorage.setItem(PREFIX + name, legacy);
    window.localStorage.removeItem(LEGACY_PREFIX + name);
  }
  return legacy;
}

export function writeStorage(name: string, value: string): void {
  window.localStorage.setItem(PREFIX + name, value);
}

export function removeStorage(name: string): void {
  window.localStorage.removeItem(PREFIX + name);
  window.localStorage.removeItem(LEGACY_PREFIX + name);
}
