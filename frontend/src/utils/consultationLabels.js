/**
 * Label Bahasa Indonesia buat nilai berkategori di pratinjau Laporan
 * Konsultasi -- SEMUA fungsi di sini fallback ke label generik yang
 * AMAN kalau kodenya nggak dikenal (BUKAN nampilin kode mentah dari
 * API), pola yang sama persis dipakai
 * frontend/src/utils/reminders.js/insightCodes.js.
 */

export const FEED_TYPE_LABELS = {
  asi_langsung: "ASI langsung",
  asi_perah: "ASI perah",
  sufor: "Susu formula",
  mpasi: "MPASI",
};

export function describeFeedType(type) {
  return FEED_TYPE_LABELS[type] || "Lainnya";
}

export const MOOD_LABELS = {
  ceria: "Ceria",
  baik: "Baik",
  sedih: "Sedih",
  menangis: "Menangis",
};

export function describeMood(mood) {
  return MOOD_LABELS[mood] || "Lainnya";
}

const UNKNOWN_MILESTONE_LABEL = "Milestone lainnya";

export const MILESTONE_TYPE_LABELS = {
  bisa_duduk: "Bisa duduk",
  langkah_pertama: "Langkah pertama",
  kata_pertama: "Kata pertama",
  gigi_pertama: "Gigi pertama",
  custom: UNKNOWN_MILESTONE_LABEL,
};

export function describeMilestoneType(type) {
  return MILESTONE_TYPE_LABELS[type] || UNKNOWN_MILESTONE_LABEL;
}

export function describeVaccinationStatus(given, state = null) {
  if (given || state === "given") return "Sudah diberikan";
  return { upcoming: "Akan datang", due: "Waktunya", overdue: "Terlambat" }[state] || "Belum diberikan";
}

export function describeGender(gender) {
  if (gender === "L") return "Laki-laki";
  if (gender === "P") return "Perempuan";
  return null;
}
