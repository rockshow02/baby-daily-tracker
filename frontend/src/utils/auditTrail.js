/**
 * Allowlist frontend buat Caregiver Audit Trail (Phase 1) — SATU-SATUNYA
 * sumber teks Indonesia yang ditampilkan buat entity_type/action/nama
 * field yang dikirim backend. SENGAJA whitelist (bukan nampilin key
 * mentah dari respons API langsung) — kalau backend suatu saat ngirim
 * entity_type/field yang belum dikenal frontend (versi lama/baru beda),
 * fallback ke label generik AMAN, bukan bocorin key teknis mentah ke UI.
 */

export const ENTITY_TYPE_LABELS = {
  feeding_log: "menyusui",
  sleep_log: "tidur",
  diaper_log: "popok",
  pumping_log: "perah ASI",
  activity_log: "aktivitas",
  growth_measurement: "pertumbuhan",
  doctor_visit: "kunjungan dokter",
  temperature_log: "suhu tubuh",
  illness_log: "sakit",
  medication_log: "obat",
  mood_log: "mood",
  milestone_log: "milestone",
};

const UNKNOWN_ENTITY_LABEL = "catatan";

export function describeEntityType(entityType) {
  return ENTITY_TYPE_LABELS[entityType] || UNKNOWN_ENTITY_LABEL;
}

// Dropdown filter jenis catatan — urutannya SENGAJA ngikutin urutan
// ENTITY_TYPE_LABELS di atas biar konsisten di seluruh layar ini.
export const ENTITY_TYPE_FILTER_OPTIONS = [
  { value: "", label: "Semua jenis" },
  ...Object.entries(ENTITY_TYPE_LABELS).map(([value, label]) => ({
    value,
    label: label.charAt(0).toUpperCase() + label.slice(1),
  })),
];

// Nama field -> label manusiawi, PER entity_type — HARUS cocok whitelist
// backend (backend/utils/audit.py:SAFE_CHANGED_FIELDS). Field yang nggak
// ada di sini (harusnya nggak pernah kejadian kalau backend/frontend
// sinkron, tapi dijaga jaga-jaga) fallback ke UNKNOWN_FIELD_LABEL —
// TIDAK PERNAH nampilin nama field mentah dari respons API.
const FIELD_LABELS = {
  feeding_log: {
    timestamp: "waktu",
    feed_type: "jenis menyusui",
    duration_minutes: "durasi",
    volume_ml: "volume",
    breast_side: "sisi",
  },
  sleep_log: {
    start_time: "waktu mulai",
    end_time: "waktu selesai",
    sleep_type: "jenis tidur",
  },
  diaper_log: {
    timestamp: "waktu",
    diaper_type: "jenis popok",
    consistency: "konsistensi",
    color: "warna",
  },
  pumping_log: {
    timestamp: "waktu",
    duration_minutes: "durasi",
    volume_ml: "volume",
    breast_side: "sisi",
  },
  activity_log: {
    timestamp: "waktu",
    activity_type: "jenis aktivitas",
    duration_minutes: "durasi",
  },
  growth_measurement: {
    measured_date: "tanggal ukur",
    weight_kg: "berat",
    height_cm: "tinggi",
    head_circumference_cm: "lingkar kepala",
  },
  doctor_visit: {
    visit_date: "tanggal kunjungan",
    doctor_name: "nama dokter",
    clinic_name: "nama klinik",
    reason: "alasan kunjungan",
    diagnosis: "diagnosis",
    next_visit_date: "jadwal kontrol",
  },
  temperature_log: {
    timestamp: "waktu",
    temperature_celsius: "suhu",
    method: "cara ukur",
  },
  illness_log: {
    illness_name: "nama sakit",
    start_date: "tanggal mulai",
    end_date: "tanggal sembuh",
    symptoms: "gejala",
  },
  medication_log: {
    timestamp: "waktu",
    medication_name: "nama obat",
    dosage: "dosis",
  },
  mood_log: {
    timestamp: "waktu",
    mood: "suasana hati",
  },
  milestone_log: {
    milestone_type: "jenis milestone",
    custom_label: "label",
    achieved_date: "tanggal tercapai",
  },
};

const UNKNOWN_FIELD_LABEL = "detail";

/** List label manusiawi (bukan nama field mentah) buat 1 event `changed_fields`. */
export function describeChangedFields(entityType, changedFields) {
  const labels = FIELD_LABELS[entityType] || {};
  const list = Array.isArray(changedFields) ? changedFields : [];
  return list.map((field) => labels[field] || UNKNOWN_FIELD_LABEL);
}

function joinIndonesian(words) {
  if (words.length === 0) return "";
  if (words.length === 1) return words[0];
  return `${words.slice(0, -1).join(", ")} dan ${words[words.length - 1]}`;
}

const ACTION_VERBS = {
  create: "menambahkan",
  delete: "menghapus",
};

export const ACTION_FILTER_OPTIONS = [
  { value: "", label: "Semua aksi" },
  { value: "create", label: "Ditambahkan" },
  { value: "update", label: "Diubah" },
  { value: "delete", label: "Dihapus" },
];

const UNKNOWN_ACTOR_LABEL = "Pengguna";

/**
 * 1 kalimat Indonesia manusiawi buat 1 audit event, cth:
 *   "Weswew menambahkan catatan menyusui"
 *   "Weswew mengubah waktu dan volume catatan menyusui"
 *   "Weswew menghapus catatan popok"
 * SEMUA teksnya lewat allowlist di atas — TIDAK PERNAH nampilin
 * entity_type/nama field/nilai mentah dari respons API langsung.
 */
export function describeAuditEvent(event) {
  const actor = event.actor_name || UNKNOWN_ACTOR_LABEL;
  const entityLabel = describeEntityType(event.entity_type);

  if (event.action === "update") {
    const fieldLabels = describeChangedFields(event.entity_type, event.changed_fields);
    const fieldsText = fieldLabels.length > 0 ? joinIndonesian(fieldLabels) : "sebagian detail";
    return `${actor} mengubah ${fieldsText} catatan ${entityLabel}`;
  }

  const verb = ACTION_VERBS[event.action] || "memperbarui";
  return `${actor} ${verb} catatan ${entityLabel}`;
}
