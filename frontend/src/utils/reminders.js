/**
 * Label & ikon Bahasa Indonesia buat Care Reminders & Schedules Phase 1
 * — SATU sumber dipakai bareng ReminderScreen.jsx dan ringkasan
 * dashboard, biar dua tempat itu nggak pernah beda kata buat hal yang
 * sama. Kode/tipe di luar allowlist di sini SELALU fallback generik
 * (bukan nampilin key mentah dari respons API), konsisten sama pola
 * frontend/src/utils/insightCodes.js.
 */

export const REMINDER_TYPES = ["medication", "doctor_visit", "vaccination", "pumping", "general"];

export const REMINDER_TYPE_LABELS = {
  medication: "Obat",
  doctor_visit: "Kunjungan Dokter",
  vaccination: "Vaksinasi",
  pumping: "Perah ASI",
  general: "Umum",
};

export const REMINDER_TYPE_ICONS = {
  medication: "💊",
  doctor_visit: "🩺",
  vaccination: "💉",
  pumping: "🤱",
  general: "🔔",
};

const UNKNOWN_TYPE_LABEL = "Perawatan";
const UNKNOWN_TYPE_ICON = "🔔";

export function describeReminderType(type) {
  return REMINDER_TYPE_LABELS[type] || UNKNOWN_TYPE_LABEL;
}

export function reminderTypeIcon(type) {
  return REMINDER_TYPE_ICONS[type] || UNKNOWN_TYPE_ICON;
}

export const RECURRENCE_LABELS = {
  none: "Sekali",
  daily: "Setiap hari",
};

export function describeRecurrence(recurrence) {
  return RECURRENCE_LABELS[recurrence] || "Tidak diketahui";
}

export const OCCURRENCE_STATE_LABELS = {
  upcoming: "Akan datang",
  due: "Jatuh tempo",
  overdue: "Terlambat",
  completed: "Selesai",
  skipped: "Dilewati",
};

const UNKNOWN_STATE_LABEL = "Tidak diketahui";

export function describeOccurrenceState(state) {
  return OCCURRENCE_STATE_LABELS[state] || UNKNOWN_STATE_LABEL;
}

// Reminder yang bisa ditautkan ke alur "Catat sekarang" (buka form yang
// sudah ada) — vaksinasi & umum SENGAJA nggak di sini (lihat
// backend/docs/REMINDERS.md bagian "Catat sekarang").
export const RECORD_NOW_LOG_TYPES = {
  medication: "medication_log",
  pumping: "pumping_log",
  doctor_visit: "doctor_visit",
};

export function formatOccurrenceDateTime(iso) {
  if (!iso) return "";
  try {
    return new Date(iso).toLocaleString("id-ID", { dateStyle: "medium", timeStyle: "short" });
  } catch (_) {
    return iso;
  }
}

export function formatOccurrenceTimeOnly(iso) {
  if (!iso) return "";
  try {
    return new Date(iso).toLocaleTimeString("id-ID", { hour: "2-digit", minute: "2-digit" });
  } catch (_) {
    return iso;
  }
}
