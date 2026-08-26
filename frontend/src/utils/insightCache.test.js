import { beforeEach, describe, expect, it } from "vitest";
import {
  cacheInsightSnapshot,
  getCachedInsightSnapshot,
  clearCachedInsightSnapshot,
  clearAllInsightSnapshotsForUser,
  pruneInsightCacheToAccessibleChildren,
} from "./insightCache";

const sampleInsight = { period: { key: "7d" }, metrics: { feeding: { total_events: 3 } } };

beforeEach(() => {
  localStorage.clear();
});

describe("insightCache — isolasi per (user, anak)", () => {
  it("menyimpan lalu membaca balik snapshot yang sama persis", () => {
    cacheInsightSnapshot(1, 10, sampleInsight);
    const cached = getCachedInsightSnapshot(1, 10);
    expect(cached.data).toEqual(sampleInsight);
    expect(cached.userId).toBe(1);
    expect(cached.childId).toBe(10);
    expect(typeof cached.cachedAt).toBe("string");
  });

  it("nggak pernah nyampur snapshot antar anak yang beda, walau user sama", () => {
    cacheInsightSnapshot(1, 10, { ...sampleInsight, marker: "anak-10" });
    cacheInsightSnapshot(1, 20, { ...sampleInsight, marker: "anak-20" });

    expect(getCachedInsightSnapshot(1, 10).data.marker).toBe("anak-10");
    expect(getCachedInsightSnapshot(1, 20).data.marker).toBe("anak-20");
  });

  it("nggak pernah nyampur snapshot antar user yang beda, walau anak sama", () => {
    cacheInsightSnapshot(1, 10, { ...sampleInsight, marker: "user-1" });
    cacheInsightSnapshot(2, 10, { ...sampleInsight, marker: "user-2" });

    expect(getCachedInsightSnapshot(1, 10).data.marker).toBe("user-1");
    expect(getCachedInsightSnapshot(2, 10).data.marker).toBe("user-2");
  });

  it("balikin null kalau belum pernah ada cache buat kombinasi (user, anak) itu", () => {
    expect(getCachedInsightSnapshot(99, 99)).toBeNull();
  });
});

describe("insightCache — versi skema", () => {
  it("menolak record dengan schemaVersion yang tidak dikenal/hilang, TIDAK PERNAH menebak bentuknya", () => {
    localStorage.setItem(
      "babytracker_insight_cache_v1:1:10",
      JSON.stringify({ userId: 1, childId: 10, data: sampleInsight, cachedAt: new Date().toISOString() }),
      // schemaVersion SENGAJA dihilangkan
    );
    expect(getCachedInsightSnapshot(1, 10)).toBeNull();
  });

  it("menolak record dengan schemaVersion yang lebih baru/beda dari yang dikenal", () => {
    localStorage.setItem(
      "babytracker_insight_cache_v1:1:10",
      JSON.stringify({
        schemaVersion: 999, userId: 1, childId: 10, data: sampleInsight, cachedAt: new Date().toISOString(),
      }),
    );
    expect(getCachedInsightSnapshot(1, 10)).toBeNull();
  });

  it("nggak pernah throw kalau isi localStorage-nya JSON rusak", () => {
    localStorage.setItem("babytracker_insight_cache_v1:1:10", "{bukan json valid");
    expect(() => getCachedInsightSnapshot(1, 10)).not.toThrow();
    expect(getCachedInsightSnapshot(1, 10)).toBeNull();
  });
});

describe("insightCache — pembersihan", () => {
  it("clearCachedInsightSnapshot cuma hapus 1 kombinasi (user, anak), bukan yang lain", () => {
    cacheInsightSnapshot(1, 10, sampleInsight);
    cacheInsightSnapshot(1, 20, sampleInsight);
    clearCachedInsightSnapshot(1, 10);
    expect(getCachedInsightSnapshot(1, 10)).toBeNull();
    expect(getCachedInsightSnapshot(1, 20)).not.toBeNull();
  });

  it("clearAllInsightSnapshotsForUser hapus semua anak punya 1 user doang, nggak nyentuh user lain", () => {
    cacheInsightSnapshot(1, 10, sampleInsight);
    cacheInsightSnapshot(1, 20, sampleInsight);
    cacheInsightSnapshot(2, 10, sampleInsight);

    clearAllInsightSnapshotsForUser(1);

    expect(getCachedInsightSnapshot(1, 10)).toBeNull();
    expect(getCachedInsightSnapshot(1, 20)).toBeNull();
    expect(getCachedInsightSnapshot(2, 10)).not.toBeNull();
  });

  it("pruneInsightCacheToAccessibleChildren membuang snapshot anak yang aksesnya sudah dicabut", () => {
    cacheInsightSnapshot(1, 10, sampleInsight);
    cacheInsightSnapshot(1, 20, sampleInsight);
    cacheInsightSnapshot(1, 30, sampleInsight);

    // Revalidasi online cuma nemu anak 10 dan 30 yang masih bisa diakses
    // sekarang — anak 20 (aksesnya dicabut caregiver lain) harus hilang.
    pruneInsightCacheToAccessibleChildren(1, [10, 30]);

    expect(getCachedInsightSnapshot(1, 10)).not.toBeNull();
    expect(getCachedInsightSnapshot(1, 30)).not.toBeNull();
    expect(getCachedInsightSnapshot(1, 20)).toBeNull();
  });

  it("pruneInsightCacheToAccessibleChildren nggak pernah nyentuh snapshot user lain", () => {
    cacheInsightSnapshot(1, 10, sampleInsight);
    cacheInsightSnapshot(2, 10, sampleInsight);

    pruneInsightCacheToAccessibleChildren(1, []); // user 1 kehilangan akses ke SEMUA anak

    expect(getCachedInsightSnapshot(1, 10)).toBeNull();
    expect(getCachedInsightSnapshot(2, 10)).not.toBeNull(); // user 2 tetap utuh
  });
});
