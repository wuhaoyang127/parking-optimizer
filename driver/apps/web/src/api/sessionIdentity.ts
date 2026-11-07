const STORAGE_KEY = "parksim.driver-session-id.v1";
const ID_PATTERN = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/;

function createSessionId(): string {
  return `driver-${crypto.randomUUID()}`;
}

export function getDriverSessionId(): string {
  try {
    const existing = globalThis.localStorage.getItem(STORAGE_KEY);
    if (existing !== null && ID_PATTERN.test(existing)) return existing;
    const created = createSessionId();
    globalThis.localStorage.setItem(STORAGE_KEY, created);
    return created;
  } catch {
    // A private/locked-down browser may reject storage; keep one tab stable in memory.
    return fallbackSessionId;
  }
}

const fallbackSessionId = createSessionId();
