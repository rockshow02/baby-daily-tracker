/**
 * Cache offline MINIMAL buat 1 snapshot insight TERAKHIR yang berhasil
 * dimuat, per (user, anak) — dipakai SEMATA buat nampilin "Menampilkan
 * ringkasan terakhir saat offline" pas Insight Screen dibuka tanpa
 * koneksi. BUKAN sumber kebenaran otorisasi/data medis — begitu online
 * lagi, server SELALU yang otoritatif (fetch fresh, cache ditimpa).
 *
 * TIDAK PERNAH menyimpan apa pun selain PERSIS payload yang backend
 * kembalikan dari GET /children/:id/insights — endpoint itu sendiri
 * SUDAH privacy-minimal by design (lihat backend/docs/INSIGHTS.md dan
 * test privasinya di backend/tests/test_insights.py), jadi TIDAK ADA
 * filtering tambahan yang perlu dilakukan lagi di sini.
 *
 * Key di-namespace pakai userId DAN childId (bukan cuma userId kayak
 * utils/sessionCache.js) — 1 user bisa punya beberapa anak, snapshot
 * insight anak A TIDAK PERNAH boleh nyampur/ketimpa sama anak B.
 */

const INSIGHT_CACHE_PREFIX = "babytracker_insight_cache_v1:";

// Versi skema record yang disimpan — dicek balik pas dibaca. Kalau
// suatu saat bentuk record ini berubah, naikkan angka ini: record versi
// lama otomatis ditolak dengan aman (dianggap "tidak ada cache"),
// TIDAK PERNAH ditebak-tebak bentuknya.
const CACHE_SCHEMA_VERSION = 1;

function cacheKey(userId, childId) {
  return `${INSIGHT_CACHE_PREFIX}${userId}:${childId}`;
}

function safeParse(raw) {
  if (!raw) return null;
  try {
    return JSON.parse(raw);
  } catch (_) {
    return null;
  }
}

/** Simpan snapshot insight yang BARU SAJA berhasil dimuat online. */
export function cacheInsightSnapshot(userId, childId, insightResponse) {
  if (userId == null || childId == null || !insightResponse) return;
  try {
    const record = {
      schemaVersion: CACHE_SCHEMA_VERSION,
      userId,
      childId,
      cachedAt: new Date().toISOString(),
      data: insightResponse,
    };
    localStorage.setItem(cacheKey(userId, childId), JSON.stringify(record));
  } catch (_) {
    // storage nggak kebuka (kuota/private mode) — nggak fatal, cuma
    // berarti nanti nggak ada snapshot buat ditampilin pas offline
  }
}

/**
 * Balikin `{ schemaVersion, userId, childId, cachedAt, data }` kalau ADA
 * dan cocok user+anak yang diminta, atau `null` kalau nggak ada/rusak/
 * versi skema nggak dikenal — TIDAK PERNAH throw.
 */
export function getCachedInsightSnapshot(userId, childId) {
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

export function clearCachedInsightSnapshot(userId, childId) {
  if (userId == null || childId == null) return;
  try {
    localStorage.removeItem(cacheKey(userId, childId));
  } catch (_) {
    // nggak ada yang perlu dibersihkan kalau storage nggak kebuka
  }
}

/** Hapus SEMUA snapshot insight punya 1 user (semua anaknya) — dipanggil pas logout. */
export function clearAllInsightSnapshotsForUser(userId) {
  if (userId == null) return;
  try {
    const prefix = `${INSIGHT_CACHE_PREFIX}${userId}:`;
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
 * direvalidasi ONLINE — hapus snapshot insight anak MANA PUN yang tidak
 * lagi ada di `accessibleChildIds` sekarang (akses dicabut caregiver
 * lain, atau anak dihapus), biar snapshot lama nggak nyangkut jadi
 * "hantu" yang masih bisa dilihat offline padahal aksesnya udah dicabut.
 */
export function pruneInsightCacheToAccessibleChildren(userId, accessibleChildIds) {
  if (userId == null) return;
  try {
    const prefix = `${INSIGHT_CACHE_PREFIX}${userId}:`;
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
