import { beforeEach, describe, expect, it, vi } from "vitest";
import { getLastSyncedAt, setLastSyncedAt, clearLastSyncedAt } from "./syncMetadata";

beforeEach(() => {
  localStorage.clear();
});

describe("syncMetadata", () => {
  it("returns null when nothing has ever been recorded for this user", () => {
    expect(getLastSyncedAt(1)).toBeNull();
  });

  it("persists and returns a timestamp for a specific user", () => {
    setLastSyncedAt(1, "2026-01-15T10:00:00.000Z");
    expect(getLastSyncedAt(1)).toBe("2026-01-15T10:00:00.000Z");
  });

  it("defaults to now() when no explicit timestamp is passed", () => {
    const before = Date.now();
    setLastSyncedAt(1);
    const stored = getLastSyncedAt(1);
    expect(stored).toBeTruthy();
    expect(Date.parse(stored)).toBeGreaterThanOrEqual(before);
  });

  it("namespaces storage per user — one account never sees another account's timestamp", () => {
    setLastSyncedAt(1, "2026-01-15T10:00:00.000Z");
    expect(getLastSyncedAt(2)).toBeNull();
    expect(getLastSyncedAt(1)).toBe("2026-01-15T10:00:00.000Z");
  });

  it("returns null for a null/undefined userId instead of a shared/global value", () => {
    setLastSyncedAt(1, "2026-01-15T10:00:00.000Z");
    expect(getLastSyncedAt(null)).toBeNull();
    expect(getLastSyncedAt(undefined)).toBeNull();
  });

  it("clearLastSyncedAt removes only the given user's timestamp", () => {
    setLastSyncedAt(1, "2026-01-15T10:00:00.000Z");
    setLastSyncedAt(2, "2026-01-16T10:00:00.000Z");
    clearLastSyncedAt(1);
    expect(getLastSyncedAt(1)).toBeNull();
    expect(getLastSyncedAt(2)).toBe("2026-01-16T10:00:00.000Z");
  });

  it("fails safely (returns null) for corrupt/unparseable stored values", () => {
    localStorage.setItem("babytracker_last_synced_v1:1", "not a real timestamp at all");
    expect(getLastSyncedAt(1)).toBeNull();
  });

  it("fails safely (returns null) for a timestamp implausibly far in the past", () => {
    localStorage.setItem("babytracker_last_synced_v1:1", "1990-01-01T00:00:00.000Z");
    expect(getLastSyncedAt(1)).toBeNull();
  });

  it("fails safely (returns null) for a timestamp implausibly far in the future", () => {
    const farFuture = new Date(Date.now() + 365 * 24 * 60 * 60 * 1000).toISOString();
    localStorage.setItem("babytracker_last_synced_v1:1", farFuture);
    expect(getLastSyncedAt(1)).toBeNull();
  });

  it("does not throw when localStorage.getItem throws (storage unavailable)", () => {
    const spy = vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("storage unavailable");
    });
    expect(() => getLastSyncedAt(1)).not.toThrow();
    expect(getLastSyncedAt(1)).toBeNull();
    spy.mockRestore();
  });

  it("does not throw when localStorage.setItem throws (quota exceeded / private mode)", () => {
    const spy = vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("quota exceeded");
    });
    expect(() => setLastSyncedAt(1, "2026-01-15T10:00:00.000Z")).not.toThrow();
    spy.mockRestore();
  });

  it("does not throw when userId is missing for setLastSyncedAt/clearLastSyncedAt", () => {
    expect(() => setLastSyncedAt(null, "2026-01-15T10:00:00.000Z")).not.toThrow();
    expect(() => clearLastSyncedAt(null)).not.toThrow();
  });
});
