/**
 * Metadata sinkronisasi NON-SENSITIF, per-user — SATU-SATUNYA hal yang
 * disimpan di sini sekarang adalah kapan terakhir kali SEMUA catatan
 * milik user ini berhasil tersinkron penuh ke server. Sengaja file
 * terpisah dari utils/offlineQueue.js (bukan field tambahan di record
 * antrian) karena ini metadata TINGKAT AKUN, bukan tingkat 1 record —
 * mencampurnya ke record queue individual bakal bikin makna "kapan
 * terakhir SEMUA beres" kabur begitu ada campuran record lama/baru.
 *
 * localStorage (BUKAN IndexedDB) sengaja dipilih: nilainya cuma 1
 * timestamp per user, sama sekali nggak sensitif, dan nggak ada alasan
 * kuat buat nambah versi skema IndexedDB (utils/offlineQueue.js) cuma
 * buat nyimpen 1 field kecil kayak gini.
 *
 * Semua key di-namespace pakai userId, POLA YANG SAMA kayak
 * utils/sessionCache.js — isolasi antar akun otomatis lewat key yang
 * beda, bukan lewat logic pembersihan manual yang bisa lupa dipanggil.
 *
 * TIDAK PERNAH nyimpen: token, body request, catatan bebas, nama anak,
 * detail obat, atau respons server apa pun — cuma 1 string ISO timestamp.
 */

const LAST_SYNCED_PREFIX = "babytracker_last_synced_v1:";

// Rentang wajar buat validasi timestamp yang dibaca balik dari
// localStorage — storage browser BISA diubah manual/corrupt (ekstensi
// lain, devtools, dst.), jadi nilai yang keluar dari sini nggak pernah
// dipercaya mentah-mentah tanpa validasi.
const MIN_VALID_YEAR = 2020;
const MAX_FUTURE_SKEW_MS = 5 * 60 * 1000; // toleransi jam klien meleset dikit

function isValidIsoTimestamp(value) {
  if (typeof value !== "string" || value.trim() === "") return false;
  const ms = Date.parse(value);
  if (Number.isNaN(ms)) return false;
  const date = new Date(ms);
  if (date.getUTCFullYear() < MIN_VALID_YEAR) return false;
  if (ms > Date.now() + MAX_FUTURE_SKEW_MS) return false;
  return true;
}

/**
 * Kapan terakhir kali SEMUA catatan milik `userId` berhasil tersinkron
 * penuh (ISO string), atau `null` kalau belum pernah/nggak valid/storage
 * nggak kebuka. Nggak pernah throw — kegagalan baca metadata sinkronisasi
 * TIDAK BOLEH bikin sinkronisasi ITU SENDIRI gagal.
 */
export function getLastSyncedAt(userId) {
  if (userId == null) return null;
  try {
    const raw = localStorage.getItem(`${LAST_SYNCED_PREFIX}${userId}`);
    if (!isValidIsoTimestamp(raw)) return null;
    return raw;
  } catch (_) {
    // localStorage nggak kebuka (mode private ketat di beberapa browser,
    // kuota penuh, dll) — anggap aja "belum pernah tersinkron", jangan
    // sampai gagal keras.
    return null;
  }
}

/** Catat waktu SEKARANG sebagai terakhir kali user ini berhasil full-sync. Gagal diam-diam kalau storage nggak kebuka. */
export function setLastSyncedAt(userId, isoTimestamp = new Date().toISOString()) {
  if (userId == null) return;
  try {
    localStorage.setItem(`${LAST_SYNCED_PREFIX}${userId}`, isoTimestamp);
  } catch (_) {
    // penyimpanan gagal (kuota/private mode) — sinkronisasi tetap sukses,
    // cuma timestamp "terakhir disinkron"-nya nggak ke-update. Nggak fatal.
  }
}

/**
 * Dipanggil pas logout (lihat context/AuthContext.jsx:clearSession) —
 * KONSISTEN sama kebijakan cache per-user lain di utils/sessionCache.js
 * (profil, daftar anak, anak aktif: semua dibersihkan pas logout).
 * Timestamp ini sendiri nggak sensitif, tapi dibersihkan biar
 * perilakunya SATU POLA yang predictable buat semua state per-user yang
 * di-cache browser — bukan karena ada risiko privasi lintas akun (key-nya
 * sudah di-namespace per userId sejak awal, jadi isolasi akun tetap utuh
 * walau baris ini dihapus).
 */
export function clearLastSyncedAt(userId) {
  if (userId == null) return;
  try {
    localStorage.removeItem(`${LAST_SYNCED_PREFIX}${userId}`);
  } catch (_) {
    // storage nggak kebuka — nggak ada yang perlu dibersihkan
  }
}
