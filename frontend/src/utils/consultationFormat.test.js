import { describe, expect, it } from "vitest";
import {
  MISSING_VALUE, formatDateWIB, formatDateTimeWIB, formatInt, formatDecimal,
  formatVolumeMl, formatWeightKg, formatLengthCm, formatTemperatureC,
  formatTimes, formatRatePerDay, formatRecordCount, formatDurationMinutes, orDash,
} from "./consultationFormat";

describe("formatDateWIB", () => {
  it("formats a pure date string into readable Indonesian", () => {
    expect(formatDateWIB("2026-08-23")).toBe("23 Agu 2026");
  });

  it("does not shift the day due to browser-local timezone reinterpretation", () => {
    // "2026-01-01" (tahun baru) -- kalau ada bug `new Date("2026-01-01")`
    // ditafsirkan UTC lalu diformat di timezone yang mundur dari UTC,
    // ini bisa salah jadi "31 Des 2025". Parsing string manual di sini
    // TIDAK PERNAH lewat `Date`, jadi kebal dari itu.
    expect(formatDateWIB("2026-01-01")).toBe("1 Jan 2026");
  });

  it("returns the missing-value dash for null/undefined/empty", () => {
    expect(formatDateWIB(null)).toBe(MISSING_VALUE);
    expect(formatDateWIB(undefined)).toBe(MISSING_VALUE);
    expect(formatDateWIB("")).toBe(MISSING_VALUE);
  });

  it("returns the missing-value dash for a malformed date string", () => {
    expect(formatDateWIB("not-a-date")).toBe(MISSING_VALUE);
  });
});

describe("formatDateTimeWIB", () => {
  it("formats an ISO datetime with +07:00 offset into WIB wall-clock text", () => {
    expect(formatDateTimeWIB("2026-08-23T08:30:00+07:00")).toBe("23 Agu 2026, 08.30 WIB");
  });

  it("converts a UTC timestamp to the correct WIB wall-clock time (UTC+7)", () => {
    // 01:00 UTC == 08:00 WIB -- kalau salah ditampilkan pakai timezone
    // device pembaca (bukan WIB eksplisit), ini bisa nunjukin jam yang beda.
    expect(formatDateTimeWIB("2026-08-23T01:00:00Z")).toBe("23 Agu 2026, 08.00 WIB");
  });

  it("returns the missing-value dash for null/undefined/empty/invalid", () => {
    expect(formatDateTimeWIB(null)).toBe(MISSING_VALUE);
    expect(formatDateTimeWIB("")).toBe(MISSING_VALUE);
    expect(formatDateTimeWIB("not-a-datetime")).toBe(MISSING_VALUE);
  });
});

describe("numeric/unit formatters", () => {
  it("formatInt renders a thousands-separated integer", () => {
    expect(formatInt(1234)).toBe("1.234");
    expect(formatInt(0)).toBe("0");
  });

  it("formatDecimal uses a comma decimal separator", () => {
    expect(formatDecimal(5.2, 1)).toBe("5,2");
    expect(formatDecimal(5, 1)).toBe("5,0");
  });

  it("formatVolumeMl appends the unit", () => {
    expect(formatVolumeMl(450)).toBe("450 ml");
    expect(formatVolumeMl(null)).toBe(MISSING_VALUE);
  });

  it("formatWeightKg uses a comma decimal", () => {
    expect(formatWeightKg(5.2)).toBe("5,2 kg");
  });

  it("formatLengthCm uses a comma decimal", () => {
    expect(formatLengthCm(61)).toBe("61,0 cm");
  });

  it("formatTemperatureC uses a comma decimal and the degree symbol", () => {
    expect(formatTemperatureC(37.2)).toBe("37,2°C");
  });

  it("formatTimes/formatRatePerDay/formatRecordCount render invariant Indonesian counts", () => {
    expect(formatTimes(8)).toBe("8 kali");
    expect(formatTimes(0)).toBe("0 kali");
    expect(formatRatePerDay(1.4)).toBe("1,4 kali/hari");
    expect(formatRecordCount(0)).toBe("0 catatan");
    expect(formatRecordCount(3)).toBe("3 catatan");
  });

  it("all numeric formatters fall back to the missing-value dash", () => {
    expect(formatInt(null)).toBe(MISSING_VALUE);
    expect(formatDecimal(undefined)).toBe(MISSING_VALUE);
    expect(formatWeightKg(undefined)).toBe(MISSING_VALUE);
    expect(formatLengthCm(null)).toBe(MISSING_VALUE);
    expect(formatTemperatureC(null)).toBe(MISSING_VALUE);
    expect(formatTimes(null)).toBe(MISSING_VALUE);
    expect(formatRatePerDay(null)).toBe(MISSING_VALUE);
    expect(formatRecordCount(null)).toBe(MISSING_VALUE);
  });
});

describe("formatDurationMinutes", () => {
  it("renders 0 minutes explicitly (a real zero, not missing)", () => {
    expect(formatDurationMinutes(0)).toBe("0 menit");
  });

  it("renders minutes under an hour", () => {
    expect(formatDurationMinutes(45)).toBe("45 menit");
  });

  it("renders an exact hour without a minutes remainder", () => {
    expect(formatDurationMinutes(60)).toBe("1 jam");
    expect(formatDurationMinutes(480)).toBe("8 jam");
  });

  it("renders hours plus minutes", () => {
    expect(formatDurationMinutes(90)).toBe("1 jam 30 menit");
  });

  it("returns the missing-value dash when the value is absent", () => {
    expect(formatDurationMinutes(null)).toBe(MISSING_VALUE);
    expect(formatDurationMinutes(undefined)).toBe(MISSING_VALUE);
  });

  it("rounds fractional minute totals to the nearest whole minute", () => {
    expect(formatDurationMinutes(89.6)).toBe("1 jam 30 menit");
  });
});

describe("orDash", () => {
  it("passes through a real value unchanged", () => {
    expect(orDash("Dr. A")).toBe("Dr. A");
    expect(orDash(0)).toBe(0);
  });

  it("falls back to the missing-value dash for null/undefined/empty string", () => {
    expect(orDash(null)).toBe(MISSING_VALUE);
    expect(orDash(undefined)).toBe(MISSING_VALUE);
    expect(orDash("")).toBe(MISSING_VALUE);
  });
});
