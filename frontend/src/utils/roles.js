/**
 * Caregiver Roles & Permissions Phase 1 — allowlist label peran +
 * helper izin frontend. Backend TETAP otoritatif buat SEMUA keputusan
 * izin (lihat backend/docs/ROLES_PERMISSIONS.md) — helper di sini CUMA
 * buat nyembunyiin/nonaktifin kontrol yang backend bakal tolak, TIDAK
 * PERNAH satu-satunya lapisan penegakan. Backend 403 tetap harus
 * ditangani dengan aman di mana pun request bisa nembus (lihat
 * api/client.js:ApiError).
 */

export const ROLE_OWNER = "owner";
export const ROLE_EDITOR = "editor";
export const ROLE_VIEWER = "viewer";

const ROLE_LABELS = {
  [ROLE_OWNER]: "Pemilik",
  [ROLE_EDITOR]: "Editor",
  [ROLE_VIEWER]: "Hanya melihat",
};

/**
 * Label Indonesia yang aman ditampilkan — TIDAK PERNAH nampilin string
 * role mentah dari backend langsung. Role yang nggak dikenal (data lama
 * yang kebetulan beda format, atau field belum ke-load) fallback ke
 * label generik, BUKAN meng-crash atau nampilin key teknis.
 */
export function describeRole(role) {
  return ROLE_LABELS[role] || "Tidak diketahui";
}

// Role yang boleh create/update/delete (Hapus tetap butuh cek kepemilikan
// tambahan per-record — lihat canDeleteRecord di bawah). Object.freeze
// biar nggak ada yang nge-mutate set ini secara nggak sengaja.
const WRITE_ROLES = new Set([ROLE_OWNER, ROLE_EDITOR]);

/**
 * True kalau role ini (secara umum) boleh create/update record. Role
 * yang nggak dikenal/null/undefined (cache lama sebelum field `role`
 * ada, atau belum sempat dikonfirmasi ulang dari server) SENGAJA
 * dianggap TIDAK boleh nulis — default aman read-only, BUKAN
 * mengasumsikan izin penuh cuma karena field-nya kosong.
 */
export function canWrite(role) {
  return WRITE_ROLES.has(role);
}

export function isOwner(role) {
  return role === ROLE_OWNER;
}

/**
 * True kalau `role` (dengan `currentUserId`) boleh hapus 1 record yang
 * `createdByUserId`-nya sekian — CUMA buat keperluan UI (tampil/sembunyi
 * tombol Hapus), SAMA PERSIS logikanya kayak
 * backend/utils/access.py:can_delete_record(), tapi backend yang
 * BENERAN menegakkan ini, bukan fungsi ini.
 */
export function canDeleteRecord(role, createdByUserId, currentUserId) {
  if (role === ROLE_OWNER) return true;
  if (role === ROLE_EDITOR) {
    return createdByUserId != null && currentUserId != null && createdByUserId === currentUserId;
  }
  return false;
}
