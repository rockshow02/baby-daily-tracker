/**
 * 16 kode section Laporan Konsultasi + label Indonesia + status
 * sensitif + default terpilih -- SATU sumber dipakai bareng
 * DoctorConsultationScreen.jsx (checkbox pilihan section) DAN
 * components/consultation/ConsultationPreview.jsx (judul section di
 * pratinjau) DAN sectionRenderers.jsx (badge sensitif), biar nggak
 * pernah ada 2 tempat yang bisa beda label buat kode yang sama.
 *
 * HARUS disinkronkan manual sama
 * backend/utils/consultation_report.py:SECTION_CODES/SENSITIVE_SECTIONS
 * (persis pola frontend/src/utils/insightCodes.js vs backend
 * INSIGHT_ALLOWLIST) — backend TETAP validasi otoritatif, daftar ini
 * CUMA buat tampilan/urutan checkbox di frontend.
 */
export const SECTION_DEFS = [
  { code: "child_summary", label: "Ringkasan Anak", sensitive: false, defaultOn: true },
  { code: "feeding", label: "Menyusui / Makan", sensitive: false, defaultOn: true },
  { code: "sleep", label: "Tidur", sensitive: false, defaultOn: true },
  { code: "diaper", label: "Popok", sensitive: false, defaultOn: true },
  { code: "pumping", label: "Memerah ASI", sensitive: false, defaultOn: false },
  { code: "activity_mood", label: "Aktivitas & Suasana Hati", sensitive: false, defaultOn: false },
  { code: "growth", label: "Pertumbuhan", sensitive: false, defaultOn: true },
  { code: "temperature", label: "Ringkasan Suhu", sensitive: false, defaultOn: true },
  { code: "vaccination", label: "Status Vaksinasi", sensitive: false, defaultOn: true },
  { code: "milestones", label: "Tumbuh Kembang", sensitive: false, defaultOn: true },
  { code: "insights", label: "Ringkasan Smart Insights", sensitive: false, defaultOn: false },
  { code: "illness", label: "Riwayat Sakit", sensitive: true, defaultOn: false },
  { code: "medication", label: "Riwayat Obat", sensitive: true, defaultOn: false },
  { code: "doctor_visits", label: "Kunjungan Dokter Sebelumnya", sensitive: true, defaultOn: false },
  // Child Medical Profile & Emergency Card Phase 1 — PALING sensitif
  // (golongan darah, alergi, kondisi medis, kontak darurat), default
  // OFF, DAN (beda dari section sensitif lain di atas) Owner/Editor
  // SAJA yang boleh menyertakannya — Viewer ditolak 403 kalau nyoba
  // (lihat backend/docs/MEDICAL_PROFILE.md).
  { code: "medical_profile", label: "Profil Medis & Kartu Darurat", sensitive: true, defaultOn: false },
  { code: "questions", label: "Pertanyaan untuk Dokter", sensitive: true, defaultOn: false },
  { code: "note", label: "Catatan Tambahan Caregiver", sensitive: true, defaultOn: false },
];

const _BY_CODE = Object.fromEntries(SECTION_DEFS.map((s) => [s.code, s]));

export function sectionLabel(code) {
  return _BY_CODE[code]?.label || code;
}

export function isSensitiveSection(code) {
  return _BY_CODE[code]?.sensitive || false;
}
