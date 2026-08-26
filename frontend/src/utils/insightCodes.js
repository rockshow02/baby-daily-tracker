/**
 * Peta kode insight (rule-based, dari backend) -> teks Bahasa Indonesia.
 *
 * PENTING: `INSIGHT_CODE_ALLOWLIST` di sini HARUS selalu sinkron manual
 * sama `INSIGHT_ALLOWLIST` di backend/utils/insights_engine.py — dua
 * sisi didokumentasikan berdampingan (lihat backend/docs/INSIGHTS.md)
 * karena tidak ada cara otomatis buat backend Python dan frontend JS
 * saling impor konstanta.
 *
 * Kode di LUAR allowlist ini (backend versi lama/baru yang belum
 * disinkronkan, bug, dsb.) SELALU jatuh ke `UNKNOWN_INSIGHT_FALLBACK`
 * yang generik — TIDAK PERNAH menampilkan kode mentah (`sleep_duration_x`
 * dst.) ke pengguna.
 */

export const INSIGHT_CODE_ALLOWLIST = [
  "insufficient_data",
  "sleep_duration_increased",
  "sleep_duration_decreased",
  "feeding_count_increased",
  "feeding_count_decreased",
  "diaper_count_increased",
  "diaper_count_decreased",
  "pumping_volume_increased",
  "pumping_volume_decreased",
  "activity_duration_increased",
  "activity_duration_decreased",
  "growth_no_recent_measurement",
];

export const UNKNOWN_INSIGHT_FALLBACK = "Ada observasi baru dari catatanmu.";

/** "minggu sebelumnya" buat 7 hari (persis contoh produk), "N hari sebelumnya" buat lainnya. */
function previousPeriodLabel(days) {
  return days === 7 ? "minggu sebelumnya" : `${days} hari sebelumnya`;
}

const TEMPLATES = {
  insufficient_data: (_value, days) =>
    `Data ${days === 7 ? "minggu" : `${days} hari`} ini masih terbatas, jadi perbandingan belum tersedia.`,
  sleep_duration_increased: (value, days) =>
    `Durasi tidur tercatat meningkat ${value} menit dibanding ${previousPeriodLabel(days)}.`,
  sleep_duration_decreased: (value, days) =>
    `Durasi tidur tercatat menurun ${value} menit dibanding ${previousPeriodLabel(days)}.`,
  feeding_count_increased: (value, days) =>
    `Jumlah catatan menyusui meningkat ${value}x dibanding ${previousPeriodLabel(days)}.`,
  feeding_count_decreased: (_value, days) =>
    `Jumlah catatan menyusui menurun dibanding ${previousPeriodLabel(days)}.`,
  diaper_count_increased: (value, days) =>
    `Jumlah ganti popok meningkat ${value}x dibanding ${previousPeriodLabel(days)}.`,
  diaper_count_decreased: (_value, days) =>
    `Jumlah ganti popok menurun dibanding ${previousPeriodLabel(days)}.`,
  pumping_volume_increased: (value, days) =>
    `Volume ASI perah tercatat meningkat ${value} ml dibanding ${previousPeriodLabel(days)}.`,
  pumping_volume_decreased: (value, days) =>
    `Volume ASI perah tercatat menurun ${value} ml dibanding ${previousPeriodLabel(days)}.`,
  activity_duration_increased: (value, days) =>
    `Durasi aktivitas tercatat meningkat ${value} menit dibanding ${previousPeriodLabel(days)}.`,
  activity_duration_decreased: (value, days) =>
    `Durasi aktivitas tercatat menurun ${value} menit dibanding ${previousPeriodLabel(days)}.`,
  growth_no_recent_measurement: () => "Belum ada pengukuran pertumbuhan dalam 30 hari terakhir.",
};

/**
 * Balikin teks Bahasa Indonesia buat 1 kartu insight `{code, value}`.
 * `periodDays` dipakai buat frasa "N hari sebelumnya"/"minggu ini".
 * Kode yang nggak dikenal (di luar allowlist ATAU nggak ada di
 * TEMPLATES) SELALU fallback ke teks generik — TIDAK PERNAH nampilin
 * kode mentah.
 */
export function describeInsightCard(card, periodDays = 7) {
  if (!card || typeof card.code !== "string") return UNKNOWN_INSIGHT_FALLBACK;
  if (!INSIGHT_CODE_ALLOWLIST.includes(card.code)) return UNKNOWN_INSIGHT_FALLBACK;
  const template = TEMPLATES[card.code];
  if (!template) return UNKNOWN_INSIGHT_FALLBACK;
  try {
    return template(card.value, periodDays);
  } catch (_) {
    return UNKNOWN_INSIGHT_FALLBACK;
  }
}
