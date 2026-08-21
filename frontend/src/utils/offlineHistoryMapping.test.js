import { describe, expect, it } from "vitest";
import {
  determineLogType,
  extractChildIdFromUrl,
  mapQueueItemToHistoryRecord,
  matchesSelectedDate,
  reconcilePendingArray,
  dedupeByQueueIdentity,
} from "./offlineHistoryMapping";

function item(overrides = {}) {
  return {
    id: 1,
    url: "/children/7/feeding-logs",
    body: JSON.stringify({ feed_type: "sufor", volume_ml: 60, timestamp: "2026-01-01T10:00:00.000Z" }),
    ...overrides,
  };
}

describe("determineLogType", () => {
  it("maps each supported endpoint to its internal type", () => {
    expect(determineLogType("/children/1/feeding-logs")).toBe("feeding");
    expect(determineLogType("/children/1/sleep-logs")).toBe("sleep");
    expect(determineLogType("/children/1/diaper-logs")).toBe("diaper");
    expect(determineLogType("/children/1/pumping-logs")).toBe("pumping");
    expect(determineLogType("/children/1/activity-logs")).toBe("activity");
    expect(determineLogType("/children/1/medication-logs")).toBe("vitamin");
  });

  it("returns null for an unrecognized endpoint", () => {
    expect(determineLogType("/children/1/growth-measurements")).toBeNull();
    expect(determineLogType(undefined)).toBeNull();
  });
});

describe("extractChildIdFromUrl", () => {
  it("extracts the numeric child id", () => {
    expect(extractChildIdFromUrl("/children/42/feeding-logs")).toBe(42);
  });

  it("returns null when there is no child id in the url", () => {
    expect(extractChildIdFromUrl("/auth/me")).toBeNull();
    expect(extractChildIdFromUrl(undefined)).toBeNull();
  });
});

describe("mapQueueItemToHistoryRecord", () => {
  it("9. maps a feeding queue item correctly", () => {
    const record = mapQueueItemToHistoryRecord(
      item({ id: 5, body: JSON.stringify({ feed_type: "sufor", volume_ml: 60, timestamp: "2026-01-01T10:00:00" }) }),
    );
    expect(record).toMatchObject({
      id: "local-5",
      _offlineQueued: true,
      kind: "feeding",
      childId: 7,
      feed_type: "sufor",
      volume_ml: 60,
      at: "2026-01-01T10:00:00",
    });
  });

  it("10. maps a sleep queue item correctly, keyed by start_time", () => {
    const record = mapQueueItemToHistoryRecord(
      item({
        id: 6,
        url: "/children/7/sleep-logs",
        body: JSON.stringify({ start_time: "2026-01-01T20:00:00", end_time: null, sleep_type: "malam" }),
      }),
    );
    expect(record).toMatchObject({ kind: "sleep", at: "2026-01-01T20:00:00", sleep_type: "malam", end_time: null });
  });

  it("11. maps a diaper queue item correctly", () => {
    const record = mapQueueItemToHistoryRecord(
      item({
        id: 7,
        url: "/children/7/diaper-logs",
        body: JSON.stringify({ diaper_type: "pup", consistency: "normal", timestamp: "2026-01-01T08:00:00" }),
      }),
    );
    expect(record).toMatchObject({ kind: "diaper", diaper_type: "pup", consistency: "normal" });
  });

  it("12. maps a pumping queue item correctly", () => {
    const record = mapQueueItemToHistoryRecord(
      item({
        id: 8,
        url: "/children/7/pumping-logs",
        body: JSON.stringify({ duration_minutes: 15, volume_ml: 80, breast_side: "kedua", timestamp: "2026-01-01T09:00:00" }),
      }),
    );
    expect(record).toMatchObject({ kind: "pumping", duration_minutes: 15, volume_ml: 80, breast_side: "kedua" });
  });

  it("13. maps stroll and bathing activity queue items correctly, disambiguated by body.activity_type", () => {
    const stroll = mapQueueItemToHistoryRecord(
      item({
        id: 9,
        url: "/children/7/activity-logs",
        body: JSON.stringify({ activity_type: "stroll", duration_minutes: 20, notes: null, timestamp: "2026-01-01T16:00:00" }),
      }),
    );
    expect(stroll).toMatchObject({ kind: "stroll", activity_type: "stroll" });

    const bathing = mapQueueItemToHistoryRecord(
      item({
        id: 10,
        url: "/children/7/activity-logs",
        body: JSON.stringify({ activity_type: "bathing", duration_minutes: 10, notes: null, timestamp: "2026-01-01T17:00:00" }),
      }),
    );
    expect(bathing).toMatchObject({ kind: "bathing", activity_type: "bathing" });
  });

  it("14. maps a medication/vitamin queue item correctly", () => {
    const record = mapQueueItemToHistoryRecord(
      item({
        id: 11,
        url: "/children/7/medication-logs",
        body: JSON.stringify({ medication_name: "Vitamin D", timestamp: "2026-01-01T07:00:00" }),
      }),
    );
    expect(record).toMatchObject({ kind: "vitamin", medication_name: "Vitamin D" });
  });

  it("15. does not crash on a malformed (non-JSON) body — returns null", () => {
    expect(() => mapQueueItemToHistoryRecord(item({ body: "{not valid json" }))).not.toThrow();
    expect(mapQueueItemToHistoryRecord(item({ body: "{not valid json" }))).toBeNull();
  });

  it("returns null for an unrecognized endpoint instead of crashing", () => {
    expect(mapQueueItemToHistoryRecord(item({ url: "/children/7/growth-measurements" }))).toBeNull();
  });

  it("returns null when the url has no child id", () => {
    expect(mapQueueItemToHistoryRecord(item({ url: "/feeding-logs" }))).toBeNull();
  });

  it("returns null when the timestamp field is missing entirely", () => {
    expect(mapQueueItemToHistoryRecord(item({ body: JSON.stringify({ feed_type: "sufor" }) }))).toBeNull();
  });

  it("returns null for an activity item with an unrecognized activity_type", () => {
    const record = mapQueueItemToHistoryRecord(
      item({
        url: "/children/7/activity-logs",
        body: JSON.stringify({ activity_type: "unknown_thing", timestamp: "2026-01-01T10:00:00" }),
      }),
    );
    expect(record).toBeNull();
  });

  it("returns null for a completely malformed item without throwing", () => {
    expect(mapQueueItemToHistoryRecord(null)).toBeNull();
    expect(mapQueueItemToHistoryRecord({})).toBeNull();
    expect(mapQueueItemToHistoryRecord({ id: 1, url: "/children/7/feeding-logs", body: "[]" })).toBeNull();
  });
});

describe("matchesSelectedDate", () => {
  it("matches a non-sleep record by its WIB calendar date", () => {
    const record = { kind: "feeding", at: "2026-01-01T10:00:00" };
    expect(matchesSelectedDate(record, "2026-01-01")).toBe(true);
    expect(matchesSelectedDate(record, "2026-01-02")).toBe(false);
  });

  it("matches a sleep record that overlaps the selected day even if it started the day before", () => {
    // mulai jam 23:00 tanggal 1, belum selesai (masih berlangsung) —
    // harus tetap muncul di tanggal 2 (SAMA kayak query backend)
    const overnightSleep = { kind: "sleep", at: "2026-01-01T23:00:00+07:00", end_time: null };
    expect(matchesSelectedDate(overnightSleep, "2026-01-02")).toBe(true);
  });

  it("does not match a sleep record that ended before the selected day started", () => {
    const finishedEarlier = {
      kind: "sleep",
      at: "2025-12-30T20:00:00+07:00",
      end_time: "2025-12-30T22:00:00+07:00",
    };
    expect(matchesSelectedDate(finishedEarlier, "2026-01-01")).toBe(false);
  });
});

describe("reconcilePendingArray", () => {
  it("appends a fresh pending record not already present", () => {
    const fresh = [{ id: "local-1", _offlineQueued: true, kind: "feeding" }];
    expect(reconcilePendingArray([], fresh)).toEqual(fresh);
  });

  it("does not duplicate a record whose id is already present (optimistic-add + restore case)", () => {
    const alreadyThere = { id: "local-1", _offlineQueued: true, kind: "feeding" };
    const fresh = [{ id: "local-1", _offlineQueued: true, kind: "feeding" }];
    const result = reconcilePendingArray([alreadyThere], fresh);
    expect(result).toHaveLength(1);
  });

  it("removes a stale optimistic entry whose id is no longer in the fresh pending set (synced or discarded)", () => {
    const stale = { id: "local-1", _offlineQueued: true, kind: "feeding" };
    const result = reconcilePendingArray([stale], []);
    expect(result).toHaveLength(0);
  });

  it("never removes a real server record (no _offlineQueued flag), only stale optimistic ones", () => {
    const serverRecord = { id: 99, kind: "feeding" };
    const result = reconcilePendingArray([serverRecord], []);
    expect(result).toEqual([serverRecord]);
  });

  it("is idempotent — calling it twice with the same fresh set doesn't change the result further", () => {
    const fresh = [{ id: "local-1", _offlineQueued: true, kind: "feeding" }];
    const once = reconcilePendingArray([], fresh);
    const twice = reconcilePendingArray(once, fresh);
    expect(twice).toHaveLength(1);
  });
});

describe("dedupeByQueueIdentity", () => {
  it("keeps only the first occurrence of each id", () => {
    const records = [
      { id: "local-1", kind: "feeding" },
      { id: "local-1", kind: "feeding" },
      { id: "local-2", kind: "sleep" },
    ];
    expect(dedupeByQueueIdentity(records)).toEqual([
      { id: "local-1", kind: "feeding" },
      { id: "local-2", kind: "sleep" },
    ]);
  });

  it("does not merge two legitimately different records that happen to share identical payload values", () => {
    const records = [
      { id: "local-1", kind: "feeding", volume_ml: 60 },
      { id: "local-2", kind: "feeding", volume_ml: 60 },
    ];
    expect(dedupeByQueueIdentity(records)).toHaveLength(2);
  });

  it("skips null/undefined entries safely", () => {
    expect(dedupeByQueueIdentity([null, { id: "local-1" }, undefined])).toEqual([{ id: "local-1" }]);
  });
});
