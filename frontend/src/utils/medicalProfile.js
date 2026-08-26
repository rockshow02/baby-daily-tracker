/**
 * Label Bahasa Indonesia buat Child Medical Profile & Emergency Card
 * Phase 1 — SATU sumber dipakai bareng MedicalProfileScreen.jsx, biar
 * nggak ada tempat yang nampilin kode enum/allowlist mentah dari
 * respons API. HARUS disinkronkan manual sama
 * backend/utils/medical_profile_engine.py (persis pola
 * utils/medicationSchedule.js vs backend).
 */

export const BLOOD_TYPES = ["A+", "A-", "B+", "B-", "AB+", "AB-", "O+", "O-", "unknown"];

const BLOOD_TYPE_LABELS = {
  "A+": "A+", "A-": "A-", "B+": "B+", "B-": "B-",
  "AB+": "AB+", "AB-": "AB-", "O+": "O+", "O-": "O-",
  unknown: "Tidak diketahui",
};

export function describeBloodType(bloodType) {
  return BLOOD_TYPE_LABELS[bloodType] || "Belum dicatat";
}

export const ALLERGY_TYPES = ["drug", "food", "other"];

const ALLERGY_TYPE_LABELS = { drug: "Obat", food: "Makanan", other: "Lainnya" };

export function describeAllergyType(type) {
  return ALLERGY_TYPE_LABELS[type] || "Tidak diketahui";
}

export const SEVERITY_LEVELS = ["mild", "moderate", "severe", "unknown"];

const SEVERITY_LABELS = { mild: "Ringan", moderate: "Sedang", severe: "Berat", unknown: "Tidak diketahui" };

export function describeSeverity(severity) {
  return severity ? (SEVERITY_LABELS[severity] || "Tidak diketahui") : "Belum diisi";
}

export const CONDITION_STATUSES = ["active", "resolved", "unknown"];

const CONDITION_STATUS_LABELS = { active: "Aktif", resolved: "Sudah sembuh", unknown: "Tidak diketahui" };

export function describeConditionStatus(status) {
  return status ? (CONDITION_STATUS_LABELS[status] || "Tidak diketahui") : "Belum diisi";
}

export function formatDateTimeWIB(iso) {
  if (!iso) return "";
  try {
    return new Date(iso).toLocaleString("id-ID", { dateStyle: "medium", timeStyle: "short" });
  } catch (_) {
    return iso;
  }
}

export const MEDICAL_PROFILE_LIMITS = {
  MAX_ALLERGIES: 30,
  MAX_CONDITIONS: 30,
  ALLERGEN_NAME_MAX_LEN: 100,
  REACTION_MAX_LEN: 300,
  CONDITION_NAME_MAX_LEN: 100,
  CONDITION_NOTE_MAX_LEN: 300,
  DOCTOR_NAME_MAX_LEN: 100,
  CLINIC_NAME_MAX_LEN: 150,
  CONTACT_NAME_MAX_LEN: 100,
  RELATIONSHIP_MAX_LEN: 50,
  PHONE_MAX_LEN: 30,
  EMERGENCY_INSTRUCTIONS_MAX_LEN: 1000,
};
