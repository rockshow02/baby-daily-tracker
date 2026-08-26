import { beforeEach, describe, expect, it } from "vitest";
import {
  cacheReminderSnapshot,
  getCachedReminderSnapshot,
  clearCachedReminderSnapshot,
  clearAllReminderSnapshotsForUser,
  pruneReminderCacheToAccessibleChildren,
} from "./reminderCache";

const sampleReminders = { reminders: [{ id: 1, title: "Obat" }], summary: { due_count: 1, overdue_count: 0, next_upcoming_at: null } };

beforeEach(() => {
  localStorage.clear();
});

describe("reminderCache — isolasi per (user, anak)", () => {
  it("menyimpan lalu membaca balik snapshot yang sama persis", () => {
    cacheReminderSnapshot(1, 10, sampleReminders);
    const cached = getCachedReminderSnapshot(1, 10);
    expect(cached.data).toEqual(sampleReminders);
    expect(cached.userId).toBe(1);
    expect(cached.childId).toBe(10);
    expect(typeof cached.cachedAt).toBe("string");
  });

  it("nggak pernah nyampur snapshot antar anak yang beda, walau user sama", () => {
    cacheReminderSnapshot(1, 10, { ...sampleReminders, marker: "anak-10" });
    cacheReminderSnapshot(1, 20, { ...sampleReminders, marker: "anak-20" });

    expect(getCachedReminderSnapshot(1, 10).data.marker).toBe("anak-10");
    expect(getCachedReminderSnapshot(1, 20).data.marker).toBe("anak-20");
  });

  it("nggak pernah nyampur snapshot antar user yang beda, walau anak sama", () => {
    cacheReminderSnapshot(1, 10, { ...sampleReminders, marker: "user-1" });
    cacheReminderSnapshot(2, 10, { ...sampleReminders, marker: "user-2" });

    expect(getCachedReminderSnapshot(1, 10).data.marker).toBe("user-1");
    expect(getCachedReminderSnapshot(2, 10).data.marker).toBe("user-2");
  });

  it("balikin null kalau belum pernah ada cache buat kombinasi (user, anak) itu", () => {
    expect(getCachedReminderSnapshot(99, 99)).toBeNull();
  });
});

describe("reminderCache — versi skema", () => {
  it("menolak record dengan schemaVersion yang tidak dikenal/hilang", () => {
    localStorage.setItem(
      "babytracker_reminder_cache_v1:1:10",
      JSON.stringify({ userId: 1, childId: 10, data: sampleReminders, cachedAt: new Date().toISOString() }),
    );
    expect(getCachedReminderSnapshot(1, 10)).toBeNull();
  });

  it("nggak pernah throw kalau isi localStorage-nya JSON rusak", () => {
    localStorage.setItem("babytracker_reminder_cache_v1:1:10", "{bukan json valid");
    expect(() => getCachedReminderSnapshot(1, 10)).not.toThrow();
    expect(getCachedReminderSnapshot(1, 10)).toBeNull();
  });
});

describe("reminderCache — pembersihan", () => {
  it("clearCachedReminderSnapshot cuma hapus 1 kombinasi (user, anak)", () => {
    cacheReminderSnapshot(1, 10, sampleReminders);
    cacheReminderSnapshot(1, 20, sampleReminders);
    clearCachedReminderSnapshot(1, 10);
    expect(getCachedReminderSnapshot(1, 10)).toBeNull();
    expect(getCachedReminderSnapshot(1, 20)).not.toBeNull();
  });

  it("clearAllReminderSnapshotsForUser hapus semua anak punya 1 user doang", () => {
    cacheReminderSnapshot(1, 10, sampleReminders);
    cacheReminderSnapshot(1, 20, sampleReminders);
    cacheReminderSnapshot(2, 10, sampleReminders);

    clearAllReminderSnapshotsForUser(1);

    expect(getCachedReminderSnapshot(1, 10)).toBeNull();
    expect(getCachedReminderSnapshot(1, 20)).toBeNull();
    expect(getCachedReminderSnapshot(2, 10)).not.toBeNull();
  });

  it("pruneReminderCacheToAccessibleChildren membuang snapshot anak yang aksesnya sudah dicabut", () => {
    cacheReminderSnapshot(1, 10, sampleReminders);
    cacheReminderSnapshot(1, 20, sampleReminders);
    cacheReminderSnapshot(1, 30, sampleReminders);

    pruneReminderCacheToAccessibleChildren(1, [10, 30]);

    expect(getCachedReminderSnapshot(1, 10)).not.toBeNull();
    expect(getCachedReminderSnapshot(1, 30)).not.toBeNull();
    expect(getCachedReminderSnapshot(1, 20)).toBeNull();
  });

  it("pruneReminderCacheToAccessibleChildren nggak pernah nyentuh snapshot user lain", () => {
    cacheReminderSnapshot(1, 10, sampleReminders);
    cacheReminderSnapshot(2, 10, sampleReminders);

    pruneReminderCacheToAccessibleChildren(1, []);

    expect(getCachedReminderSnapshot(1, 10)).toBeNull();
    expect(getCachedReminderSnapshot(2, 10)).not.toBeNull();
  });
});
