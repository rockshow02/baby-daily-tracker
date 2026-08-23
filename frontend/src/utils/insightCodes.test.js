import { describe, expect, it } from "vitest";
import { describeInsightCard, INSIGHT_CODE_ALLOWLIST, UNKNOWN_INSIGHT_FALLBACK } from "./insightCodes";

describe("insightCodes — kode dari allowlist", () => {
  it("menerjemahkan setiap kode di allowlist jadi teks Bahasa Indonesia yang nggak kosong", () => {
    for (const code of INSIGHT_CODE_ALLOWLIST) {
      const text = describeInsightCard({ code, value: 30 }, 7);
      expect(typeof text).toBe("string");
      expect(text.length).toBeGreaterThan(0);
      expect(text).not.toBe(UNKNOWN_INSIGHT_FALLBACK);
    }
  });

  it("menyisipkan value numerik ke teks kartu yang butuh angka", () => {
    const text = describeInsightCard({ code: "sleep_duration_increased", value: 45 }, 7);
    expect(text).toContain("45");
    expect(text).toMatch(/menit/);
  });

  it("memakai frasa 'minggu sebelumnya' buat periode 7 hari (persis contoh produk)", () => {
    const text = describeInsightCard({ code: "feeding_count_decreased", value: null }, 7);
    expect(text).toBe("Jumlah catatan menyusui menurun dibanding minggu sebelumnya.");
  });

  it("memakai frasa 'N hari sebelumnya' buat periode selain 7 hari", () => {
    const text = describeInsightCard({ code: "feeding_count_decreased", value: null }, 30);
    expect(text).toContain("30 hari sebelumnya");
  });
});

describe("insightCodes — kode tidak dikenal", () => {
  it("kode di luar allowlist jatuh ke fallback generik, TIDAK PERNAH tampilkan kode mentah", () => {
    const text = describeInsightCard({ code: "some_future_code_v2", value: 99 }, 7);
    expect(text).toBe(UNKNOWN_INSIGHT_FALLBACK);
    expect(text).not.toContain("some_future_code_v2");
  });

  it("input null/undefined/tanpa code juga aman jatuh ke fallback, TIDAK throw", () => {
    expect(describeInsightCard(null)).toBe(UNKNOWN_INSIGHT_FALLBACK);
    expect(describeInsightCard(undefined)).toBe(UNKNOWN_INSIGHT_FALLBACK);
    expect(describeInsightCard({})).toBe(UNKNOWN_INSIGHT_FALLBACK);
    expect(describeInsightCard({ code: 123 })).toBe(UNKNOWN_INSIGHT_FALLBACK);
  });

  it("fallback generik itu sendiri nggak pernah menyerupai kode mentah (snake_case)", () => {
    expect(UNKNOWN_INSIGHT_FALLBACK).not.toMatch(/^[a-z_]+$/);
  });
});
