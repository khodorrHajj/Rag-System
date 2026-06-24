const CACHE_PREFIX = "rag-document-assistant:v2:cache:";

type CacheRecord<T> = {
  storedAt: number;
  value: T;
};

function getStorage() {
  if (typeof window === "undefined") {
    return null;
  }

  return window.sessionStorage;
}

export function readCachedValue<T>(
  key: string,
  maxAgeMs: number,
): T | null {
  const storage = getStorage();
  if (!storage) {
    return null;
  }

  try {
    const raw = storage.getItem(`${CACHE_PREFIX}${key}`);
    if (!raw) {
      return null;
    }

    const parsed = JSON.parse(raw) as CacheRecord<T>;
    if (
      !parsed
      || typeof parsed !== "object"
      || typeof parsed.storedAt !== "number"
      || !("value" in parsed)
    ) {
      storage.removeItem(`${CACHE_PREFIX}${key}`);
      return null;
    }

    if (Date.now() - parsed.storedAt > maxAgeMs) {
      storage.removeItem(`${CACHE_PREFIX}${key}`);
      return null;
    }

    return parsed.value;
  } catch {
    storage.removeItem(`${CACHE_PREFIX}${key}`);
    return null;
  }
}

export function writeCachedValue<T>(key: string, value: T) {
  const storage = getStorage();
  if (!storage) {
    return;
  }

  try {
    const payload: CacheRecord<T> = {
      storedAt: Date.now(),
      value,
    };
    storage.setItem(`${CACHE_PREFIX}${key}`, JSON.stringify(payload));
  } catch {
    
  }
}

export function clearClientCache() {
  const storage = getStorage();
  if (!storage) {
    return;
  }

  const keysToDelete: string[] = [];
  for (let index = 0; index < storage.length; index += 1) {
    const key = storage.key(index);
    if (key?.startsWith(CACHE_PREFIX)) {
      keysToDelete.push(key);
    }
  }

  keysToDelete.forEach((key) => storage.removeItem(key));
}
