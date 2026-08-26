/**
 * Cache offline MINIMAL buat 1 snapshot daftar reminder TERAKHIR yang
 * berhasil dimuat, per (user, anak) — SAMA PERSIS pola
 * utils/insightCache.js (lihat file itu buat penjelasan desain lengkap:
 * kenapa localStorage, kenapa namespace per user+anak, kenapa
 * schemaVersion). BUKAN sumber kebenaran otorisasi/status reminder —
 * begitu online lagi, server SELALU yang otoritatif (fetch fresh, cache
 * ditimpa).
 *
 * TIDAK PERNAH menyimpan apa pun selain PERSIS payload yang backend
 * kembalikan dari GET /children/:id/reminders — endpoint itu sendiri
 * SUDAH privacy-minimal (title reminder TETAP ada di sana karena itu
 * memang bagian dari data yang caregiver perlu lihat, tapi TIDAK PERNAH
 * bocor keluar cache ini ke notifikasi/log, lihat
 * utils/reminderNotifications.js).
 */

const REMINDER_CACHE_PREFIX = "babytracker_reminder_cache_v1:";
const CACHE_SCHEMA_VERSION = 1;

function cacheKey(userId, childId) {
  return `${REMINDER_CACHE_PREFIX}${userId}:${childId}`;
}

function safeParse(raw) {
  if (!raw) return null;
  try {
    return JSON.parse(raw);
  } catch (_) {
    return null;
  }
}

export function cacheReminderSnapshot(userId, childId, reminderResponse) {
  if (userId == null || childId == null || !reminderResponse) return;
  try {
    const record = {
      schemaVersion: CACHE_SCHEMA_VERSION,
      userId,
      childId,
      cachedAt: new Date().toISOString(),
      data: reminderResponse,
    };
    localStorage.setItem(cacheKey(userId, childId), JSON.stringify(record));
  } catch (_) {
    // storage nggak kebuka (kuota/private mode) — nggak fatal
  }
}

export function getCachedReminderSnapshot(userId, childId) {
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

export function clearCachedReminderSnapshot(userId, childId) {
  if (userId == null || childId == null) return;
  try {
    localStorage.removeItem(cacheKey(userId, childId));
  } catch (_) {
    // nggak ada yang perlu dibersihkan kalau storage nggak kebuka
  }
}

/** Hapus SEMUA snapshot reminder punya 1 user (semua anaknya) — dipanggil pas logout. */
export function clearAllReminderSnapshotsForUser(userId) {
  if (userId == null) return;
  try {
    const prefix = `${REMINDER_CACHE_PREFIX}${userId}:`;
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
 * direvalidasi ONLINE — hapus snapshot reminder anak MANA PUN yang tidak
 * lagi ada di `accessibleChildIds` sekarang (akses dicabut caregiver
 * lain, atau anak dihapus).
 */
export function pruneReminderCacheToAccessibleChildren(userId, accessibleChildIds) {
  if (userId == null) return;
  try {
    const prefix = `${REMINDER_CACHE_PREFIX}${userId}:`;
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
