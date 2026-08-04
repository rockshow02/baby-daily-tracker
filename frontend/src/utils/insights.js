/**
 * Generate insight interpretatif (bukan angka mentah) dari data harian +
 * tren 7 hari — semuanya rule-based, TANPA AI. Prioritas aturan:
 *   1. Kalau di bawah acuan usia -> ⚠️ (paling penting, selalu ditampilin)
 *   2. Kalau di atas acuan usia -> ℹ️ (biasanya nggak masalah)
 *   3. Kalau dalam acuan TAPI beda jauh dari tren 7 hari terakhir (±20%)
 *      -> tetep di-flag, karena perubahan mendadak worth diperhatiin
 *      walau masih "normal" secara acuan usia
 *   4. Kalau semua aman & konsisten -> ✅
 */

const TREND_THRESHOLD_PCT = 20;

export function buildInsight({
  label,
  actual,
  min,
  max,
  status,
  weeklyAvg,
  unit,
  ageLabel,
}) {
  if (actual == null || status == null) return null;

  if (status === "kurang") {
    return {
      icon: "⚠️",
      tone: "warn",
      text: `${label} hari ini di bawah acuan usia ${ageLabel} (${formatNum(actual)}${unit} dari minimal ${formatNum(min)}${unit}).`,
    };
  }

  if (status === "lebih") {
    return {
      icon: "ℹ️",
      tone: "info",
      text: `${label} hari ini lebih banyak dari acuan usia ${ageLabel} (${formatNum(actual)}${unit}) — umumnya nggak masalah.`,
    };
  }

  // status "normal"/cukup -> cek dulu ada penyimpangan mencolok dari tren
  if (weeklyAvg != null && weeklyAvg > 0) {
    const diffPct = ((actual - weeklyAvg) / weeklyAvg) * 100;
    if (diffPct <= -TREND_THRESHOLD_PCT) {
      return {
        icon: "⚠️",
        tone: "warn",
        text: `${label} hari ini (${formatNum(actual)}${unit}) lebih rendah ${Math.abs(Math.round(diffPct))}% dibanding rata-rata 7 hari terakhir (${formatNum(weeklyAvg)}${unit}), meski masih dalam acuan usia.`,
      };
    }
    if (diffPct >= TREND_THRESHOLD_PCT) {
      return {
        icon: "ℹ️",
        tone: "info",
        text: `${label} hari ini (${formatNum(actual)}${unit}) lebih tinggi ${Math.round(diffPct)}% dibanding rata-rata 7 hari terakhir (${formatNum(weeklyAvg)}${unit}).`,
      };
    }
  }

  return {
    icon: "✅",
    tone: "good",
    text: `${label} hari ini sudah sesuai rekomendasi usia ${ageLabel}.`,
  };
}

function formatNum(n) {
  if (n == null) return "-";
  return Number.isInteger(n) ? String(n) : n.toFixed(1);
}

/** Rata-rata 1 field dari array bucket stats, KECUALI hari ini (biar nggak bias sama data hari ini yang masih berjalan/belum lengkap). */
export function weeklyAverageExcludingToday(statsDays, field, todayDateStr) {
  const pastDays = statsDays.filter((d) => d.date !== todayDateStr);
  if (pastDays.length === 0) return null;
  const sum = pastDays.reduce((acc, d) => acc + (d[field] || 0), 0);
  return sum / pastDays.length;
}
