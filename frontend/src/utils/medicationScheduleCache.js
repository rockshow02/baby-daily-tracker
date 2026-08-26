/**
 * Cache offline MINIMAL buat 1 snapshot daftar jadwal obat TERAKHIR yang
 * berhasil dimuat, per (user, anak) — SAMA PERSIS pola
 * utils/reminderCache.js (lihat file itu buat penjelasan desain lengkap:
 * kenapa localStorage, kenapa namespace per user+anak, kenapa
 * schemaVersion). BUKAN sumber kebenaran otorisasi/status dosis — begitu
 * online lagi, server SELALU yang otoritatif (fetch fresh, cache ditimpa).
 */

const CACHE_PREFIX = "babytracker_medschedule_cache_v1:";
const CACHE_SCHEMA_VERSION = 1;

function cacheKey(userId, childId) {
  return `${CACHE_PREFIX}${userId}:${childId}`;
}

function safeParse(raw) {
  if (!raw) return null;
  try {
    return JSON.parse(raw);
  } catch (_) {
    return null;
  }
}

export function cacheMedicationScheduleSnapshot(userId, childId, response) {
  if (userId == null || childId == null || !response) return;
  try {
    const record = {
      schemaVersion: CACHE_SCHEMA_VERSION,
      userId,
      childId,
      cachedAt: new Date().toISOString(),
      data: response,
    };
    localStorage.setItem(cacheKey(userId, childId), JSON.stringify(record));
  } catch (_) {
    // storage nggak kebuka (kuota/private mode) — nggak fatal
  }
}

export function getCachedMedicationScheduleSnapshot(userId, childId) {
  if (userId == null || childId == null) return null;
  try {
    const record = safeParse(localStorage.getItem(cacheKey(userId, childId)));
    if (!record) return null;
    if (record.schemaVersion !== CACHE_SCHEMA_VERSION) return null;
    if (record.userId !== userId || record.childId !== childId) return null;
    if (!record.data || !record.cachedAt) return null;
    return record;
  } catch (_) {
    return null;
  }
}

export function clearCachedMedicationScheduleSnapshot(userId, childId) {
  if (userId == null || childId == null) return;
  try {
    localStorage.removeItem(cacheKey(userId, childId));
  } catch (_) {
    // nggak ada yang perlu dibersihkan kalau storage nggak kebuka
  }
}

/** Hapus SEMUA snapshot jadwal obat punya 1 user (semua anaknya) — dipanggil pas logout. */
export function clearAllMedicationScheduleSnapshotsForUser(userId) {
  if (userId == null) return;
  try {
    const prefix = `${CACHE_PREFIX}${userId}:`;
    const keysToRemove = [];
    for (let i = 0; i < localStorage.length; i++) {
      const key = localStorage.key(i);
      if (key && key.startsWith(prefix)) keysToRemove.push(key);
    }
    keysToRemove.forEach((k) => localStorage.removeItem(k));
  } catch (_) {
    // storage nggak kebuka — nggak ada yang perlu dibersihkan
  }
}

/**
 * Dipanggil App.jsx:loadChildren() SETIAP KALI daftar anak berhasil
 * direvalidasi ONLINE — hapus snapshot jadwal obat anak MANA PUN yang
 * tidak lagi ada di `accessibleChildIds` sekarang (akses dicabut
 * caregiver lain, atau anak dihapus).
 */
export function pruneMedicationScheduleCacheToAccessibleChildren(userId, accessibleChildIds) {
  if (userId == null) return;
  try {
    const prefix = `${CACHE_PREFIX}${userId}:`;
    const allowed = new Set((accessibleChildIds || []).map(String));
    const keysToRemove = [];
    for (let i = 0; i < localStorage.length; i++) {
      const key = localStorage.key(i);
      if (!key || !key.startsWith(prefix)) continue;
      const childIdPart = key.slice(prefix.length);
      if (!allowed.has(childIdPart)) keysToRemove.push(key);
    }
    keysToRemove.forEach((k) => localStorage.removeItem(k));
  } catch (_) {
    // storage nggak kebuka — nggak ada yang bisa dibersihkan sekarang
  }
}
