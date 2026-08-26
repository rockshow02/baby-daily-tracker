/**
 * Definisi field yang AMAN diedit user buat tiap tipe catatan offline-queue
 * yang gagal (needs_review). Sengaja per-tipe (bukan "field apapun yang ada
 * di body") biar:
 *  - kontrolnya sesuai jenis datanya (select buat enum, datetime-local buat
 *    waktu, number buat angka) bukan input teks generik semua,
 *  - field internal/berbahaya (id relasi ke entitas lain, mis. illness_id)
 *    TIDAK ketawarin buat diedit — user nggak punya cara aman milih ID yang
 *    valid dari form generik kayak gini,
 *  - `notes` (teks bebas) tetap nggak ditampilin, konsisten sama ringkasan
 *    non-sensitif yang dipakai di panel review.
 */

export const FIELD_TYPE = {
  TEXT: "text",
  NUMBER: "number",
  DATETIME: "datetime",
  SELECT: "select",
};

const BREAST_SIDE_OPTIONS = ["kiri", "kanan", "kedua"];

export const EDITABLE_SCHEMAS = {
  "Menyusui": [
    {
      key: "feed_type",
      label: "Jenis",
      type: FIELD_TYPE.SELECT,
      options: ["asi_langsung", "asi_perah", "sufor", "mpasi"],
      required: true,
    },
    { key: "duration_minutes", label: "Durasi (menit)", type: FIELD_TYPE.NUMBER },
    { key: "volume_ml", label: "Volume (ml)", type: FIELD_TYPE.NUMBER },
    { key: "breast_side", label: "Sisi", type: FIELD_TYPE.SELECT, options: BREAST_SIDE_OPTIONS },
    { key: "timestamp", label: "Waktu", type: FIELD_TYPE.DATETIME },
  ],
  "Tidur": [
    { key: "start_time", label: "Mulai", type: FIELD_TYPE.DATETIME, required: true },
    { key: "end_time", label: "Selesai", type: FIELD_TYPE.DATETIME },
    { key: "sleep_type", label: "Jenis", type: FIELD_TYPE.SELECT, options: ["siang", "malam"] },
  ],
  "Popok": [
    { key: "diaper_type", label: "Jenis", type: FIELD_TYPE.SELECT, options: ["pipis", "pup", "keduanya"], required: true },
    {
      key: "consistency",
      label: "Konsistensi",
      type: FIELD_TYPE.SELECT,
      options: ["normal", "keras", "cair", "berlendir", "berdarah"],
    },
    { key: "color", label: "Warna", type: FIELD_TYPE.TEXT },
    { key: "timestamp", label: "Waktu", type: FIELD_TYPE.DATETIME },
  ],
  "Perah ASI": [
    { key: "duration_minutes", label: "Durasi (menit)", type: FIELD_TYPE.NUMBER },
    { key: "volume_ml", label: "Volume (ml)", type: FIELD_TYPE.NUMBER },
    { key: "breast_side", label: "Sisi", type: FIELD_TYPE.SELECT, options: BREAST_SIDE_OPTIONS },
    { key: "timestamp", label: "Waktu", type: FIELD_TYPE.DATETIME },
  ],
  "Aktivitas": [
    { key: "activity_type", label: "Jenis", type: FIELD_TYPE.SELECT, options: ["stroll", "bathing"], required: true },
    { key: "duration_minutes", label: "Durasi (menit)", type: FIELD_TYPE.NUMBER },
    { key: "timestamp", label: "Waktu", type: FIELD_TYPE.DATETIME },
  ],
  "Obat": [
    { key: "medication_name", label: "Nama obat", type: FIELD_TYPE.TEXT, required: true },
    { key: "dosage", label: "Dosis", type: FIELD_TYPE.TEXT },
    { key: "timestamp", label: "Waktu", type: FIELD_TYPE.DATETIME },
  ],
};

export function getEditableSchema(typeLabel) {
  return EDITABLE_SCHEMAS[typeLabel] || [];
}

/**
 * True kalau body-nya punya field terisi yang BUKAN bagian dari schema
 * (mis. `illness_id` di catatan Obat) — berarti editor generik ini nggak
 * bisa nawarin cara aman buat benerin errornya, UI harus nyaranin catat
 * ulang manual, bukan nampilin tombol Edit yang percuma.
 */
export function hasUnsupportedField(typeLabel, parsedBody) {
  const schema = getEditableSchema(typeLabel);
  const editableKeys = new Set(schema.map((f) => f.key));
  return Object.entries(parsedBody || {}).some(
    ([key, value]) => value != null && value !== "" && key !== "notes" && !editableKeys.has(key),
  );
}

/** Cek lokal sebelum retry — field yang backend wajibkan nggak boleh kosong. */
export function validateEditedBody(typeLabel, body) {
  const schema = getEditableSchema(typeLabel);
  for (const field of schema) {
    if (field.required && (body[field.key] === undefined || body[field.key] === null || body[field.key] === "")) {
      return `${field.label} wajib diisi.`;
    }
  }
  return null;
}

/** "2024-01-01T10:00:00+07:00" -> "2024-01-01T10:00" (format yg dipahami <input type="datetime-local">). */
export function toDatetimeLocalValue(value) {
  return typeof value === "string" ? value.slice(0, 16) : "";
}

/** Kebalikan toDatetimeLocalValue — nambahin ":00" detik biar konsisten diterima Python fromisoformat di semua versi. */
export function fromDatetimeLocalValue(value) {
  if (typeof value === "string" && value.length === 16) return `${value}:00`;
  return value;
}
