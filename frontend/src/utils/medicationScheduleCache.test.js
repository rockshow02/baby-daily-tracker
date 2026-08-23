import { beforeEach, describe, expect, it } from "vitest";
import {
  cacheMedicationScheduleSnapshot,
  getCachedMedicationScheduleSnapshot,
  clearCachedMedicationScheduleSnapshot,
  clearAllMedicationScheduleSnapshotsForUser,
  pruneMedicationScheduleCacheToAccessibleChildren,
} from "./medicationScheduleCache";

const sampleSchedules = { schedules: [{ id: 1, medication_name: "Obat" }], summary: { due_count: 1, overdue_count: 0, next_upcoming_at: null } };

beforeEach(() => {
  localStorage.clear();
});

describe("medicationScheduleCache — isolasi per (user, anak)", () => {
  it("menyimpan lalu membaca balik snapshot yang sama persis", () => {
    cacheMedicationScheduleSnapshot(1, 10, sampleSchedules);
    const cached = getCachedMedicationScheduleSnapshot(1, 10);
    expect(cached.data).toEqual(sampleSchedules);
    expect(cached.userId).toBe(1);
    expect(cached.childId).toBe(10);
    expect(typeof cached.cachedAt).toBe("string");
  });

  it("nggak pernah nyampur snapshot antar anak yang beda, walau user sama", () => {
    cacheMedicationScheduleSnapshot(1, 10, { ...sampleSchedules, marker: "anak-10" });
    cacheMedicationScheduleSnapshot(1, 20, { ...sampleSchedules, marker: "anak-20" });

    expect(getCachedMedicationScheduleSnapshot(1, 10).data.marker).toBe("anak-10");
    expect(getCachedMedicationScheduleSnapshot(1, 20).data.marker).toBe("anak-20");
  });

  it("nggak pernah nyampur snapshot antar user yang beda, walau anak sama", () => {
    cacheMedicationScheduleSnapshot(1, 10, { ...sampleSchedules, marker: "user-1" });
    cacheMedicationScheduleSnapshot(2, 10, { ...sampleSchedules, marker: "user-2" });

    expect(getCachedMedicationScheduleSnapshot(1, 10).data.marker).toBe("user-1");
    expect(getCachedMedicationScheduleSnapshot(2, 10).data.marker).toBe("user-2");
  });

  it("balikin null kalau belum pernah ada cache buat kombinasi (user, anak) itu", () => {
    expect(getCachedMedicationScheduleSnapshot(99, 99)).toBeNull();
  });
});

describe("medicationScheduleCache — versi skema", () => {
  it("menolak record dengan schemaVersion yang tidak dikenal/hilang", () => {
    localStorage.setItem(
      "babytracker_medschedule_cache_v1:1:10",
      JSON.stringify({ userId: 1, childId: 10, data: sampleSchedules, cachedAt: new Date().toISOString() }),
    );
    expect(getCachedMedicationScheduleSnapshot(1, 10)).toBeNull();
  });

  it("nggak pernah throw kalau isi localStorage-nya JSON rusak", () => {
    localStorage.setItem("babytracker_medschedule_cache_v1:1:10", "{bukan json valid");
    expect(() => getCachedMedicationScheduleSnapshot(1, 10)).not.toThrow();
    expect(getCachedMedicationScheduleSnapshot(1, 10)).toBeNull();
  });
});

describe("medicationScheduleCache — pembersihan", () => {
  it("clearCachedMedicationScheduleSnapshot cuma hapus 1 kombinasi (user, anak)", () => {
    cacheMedicationScheduleSnapshot(1, 10, sampleSchedules);
    cacheMedicationScheduleSnapshot(1, 20, sampleSchedules);
    clearCachedMedicationScheduleSnapshot(1, 10);
    expect(getCachedMedicationScheduleSnapshot(1, 10)).toBeNull();
    expect(getCachedMedicationScheduleSnapshot(1, 20)).not.toBeNull();
  });

  it("clearAllMedicationScheduleSnapshotsForUser hapus semua anak punya 1 user doang", () => {
    cacheMedicationScheduleSnapshot(1, 10, sampleSchedules);
    cacheMedicationScheduleSnapshot(1, 20, sampleSchedules);
    cacheMedicationScheduleSnapshot(2, 10, sampleSchedules);

    clearAllMedicationScheduleSnapshotsForUser(1);

    expect(getCachedMedicationScheduleSnapshot(1, 10)).toBeNull();
    expect(getCachedMedicationScheduleSnapshot(1, 20)).toBeNull();
    expect(getCachedMedicationScheduleSnapshot(2, 10)).not.toBeNull();
  });

  it("pruneMedicationScheduleCacheToAccessibleChildren membuang snapshot anak yang aksesnya sudah dicabut", () => {
    cacheMedicationScheduleSnapshot(1, 10, sampleSchedules);
    cacheMedicationScheduleSnapshot(1, 20, sampleSchedules);
    cacheMedicationScheduleSnapshot(1, 30, sampleSchedules);

    pruneMedicationScheduleCacheToAccessibleChildren(1, [10, 30]);

    expect(getCachedMedicationScheduleSnapshot(1, 10)).not.toBeNull();
    expect(getCachedMedicationScheduleSnapshot(1, 30)).not.toBeNull();
    expect(getCachedMedicationScheduleSnapshot(1, 20)).toBeNull();
  });

  it("pruneMedicationScheduleCacheToAccessibleChildren nggak pernah nyentuh snapshot user lain", () => {
    cacheMedicationScheduleSnapshot(1, 10, sampleSchedules);
    cacheMedicationScheduleSnapshot(2, 10, sampleSchedules);

    pruneMedicationScheduleCacheToAccessibleChildren(1, []);

    expect(getCachedMedicationScheduleSnapshot(1, 10)).toBeNull();
    expect(getCachedMedicationScheduleSnapshot(2, 10)).not.toBeNull();
  });
});
