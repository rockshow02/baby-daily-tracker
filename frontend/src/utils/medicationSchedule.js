/**
 * Label & format Bahasa Indonesia buat Medication Schedule & Adherence
 * Phase 1 — SATU sumber dipakai bareng MedicationScheduleScreen.jsx,
 * biar nggak ada tempat yang nampilin key/enum mentah dari respons API.
 * Pola SAMA PERSIS utils/reminders.js.
 */

export const OCCURRENCE_STATE_LABELS = {
  upcoming: "Akan datang",
  due: "Jatuh tempo",
  overdue: "Terlambat",
  administered: "Sudah diberikan",
  skipped: "Dilewati",
};

const UNKNOWN_STATE_LABEL = "Tidak diketahui";

export function describeOccurrenceState(state) {
  return OCCURRENCE_STATE_LABELS[state] || UNKNOWN_STATE_LABEL;
}

// Allowlist satuan dosis — SAMA PERSIS utils/medication_schedule_engine.py:DOSE_UNITS.
export const DOSE_UNIT_LABELS = {
  ml: "ml",
  mg: "mg",
  mcg: "mcg",
  tetes: "tetes",
  sendok_takar: "sendok takar",
  tablet: "tablet",
  kapsul: "kapsul",
  sachet: "sachet",
  puff: "puff/semprot",
  unit: "unit",
};

export const DOSE_UNITS = Object.keys(DOSE_UNIT_LABELS);

export function describeDoseUnit(unit) {
  return DOSE_UNIT_LABELS[unit] || unit || "";
}

export function formatDose(doseValue, doseUnit) {
  if (doseValue == null || !doseUnit) return null;
  return `${doseValue} ${describeDoseUnit(doseUnit)}`;
}

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

/** "08:00" x1, "08:00, 20:00" x2, dst — daftar jam pemberian per hari, urut apa adanya (backend sudah nyortir). */
export function formatTimesOfDay(timesOfDay) {
  return (timesOfDay || []).join(", ");
}

export function formatAdherencePercentage(pct) {
  return pct == null ? "—" : `${pct}%`;
}
