/**
 * Cache offline MINIMAL buat merender shell UI (profil user + daftar anak)
 * pas hard refresh/reopen sambil offline — BUKAN sumber kebenaran
 * otorisasi. Server tetap otoritatif begitu online lagi (lihat
 * AuthContext.jsx: refreshSessionFromServer). Nggak pernah nyimpen
 * token/password/cookie/data medis di sini, cuma field non-sensitif yang
 * beneran dipakai buat nge-render Dashboard/App.
 *
 * Semua key di-namespace pakai userId (bukan 1 slot global) — ini yang
 * bikin isolasi antar akun jalan otomatis: ganti akun berarti ganti key,
 * jadi nggak mungkin ke-baca cache akun lain, bahkan tanpa perlu hapus
 * punya akun sebelumnya secara eksplisit.
 */

const USER_CACHE_PREFIX = "babytracker_cached_user_v1:";
const CHILDREN_CACHE_PREFIX = "babytracker_cached_children_v1:";
const ACTIVE_CHILD_PREFIX = "babytracker_active_child_v1:";

function safeParse(raw) {
  if (!raw) return null;
  try {
    return JSON.parse(raw);
  } catch (_) {
    return null;
  }
}

/** Simpan cuma field yang dipakai buat nampilin shell profil user (bukan token, bukan telegram_chat_id, dst). */
export function cacheUserProfile(user) {
  if (!user || user.id == null) return;
  const minimal = { id: user.id, name: user.name, email: user.email };
  localStorage.setItem(`${USER_CACHE_PREFIX}${user.id}`, JSON.stringify(minimal));
}

/**
 * Balikin profil user yang di-cache, TAPI cuma kalau id di dalamnya cocok
 * sama userId yang diminta (jaga-jaga kedua selain namespace key — kalau
 * suatu saat ada bug penulisan silang, ini nolak makenya, bukan diam-diam
 * pakai punya akun lain).
 */
export function getCachedUserProfile(userId) {
  if (userId == null) return null;
  const cached = safeParse(localStorage.getItem(`${USER_CACHE_PREFIX}${userId}`));
  if (!cached || cached.id !== userId) return null;
  return cached;
}

export function clearCachedUserProfile(userId) {
  if (userId == null) return;
  localStorage.removeItem(`${USER_CACHE_PREFIX}${userId}`);
}

// Field anak yang dicache — persis yang dipakai Dashboard/App buat
// merender (header, kartu info anak, foto). SENGAJA nggak nyertain apapun
// dari riwayat kesehatan (vaksin, growth, dll) — itu tetap butuh online.
const CHILD_FIELDS = [
  "id",
  "name",
  "nickname",
  "birth_date",
  "gender",
  "birth_weight_kg",
  "birth_height_cm",
  "photo_filename",
  // Caregiver Roles & Permissions Phase 1 — peran EFEKTIF user yang
  // login buat anak ini ("owner" | "editor" | "viewer"), dikirim
  // backend di respons child-scoped yang sama. Cache LAMA (dari
  // sebelum field ini ada) nggak bakal punya key ini sama sekali —
  // utils/roles.js:canWrite()/isOwner() SENGAJA nganggep role yang
  // undefined/null sebagai read-only, jadi UI otomatis fallback aman
  // sampai server dikonfirmasi ulang, TIDAK PERNAH diam-diam
  // mengasumsikan izin penuh.
  "role",
];

function pickChildFields(child) {
  const picked = {};
  for (const key of CHILD_FIELDS) {
    if (child[key] !== undefined) picked[key] = child[key];
  }
  return picked;
}

export function cacheChildren(userId, children) {
  if (userId == null || !Array.isArray(children)) return;
  localStorage.setItem(`${CHILDREN_CACHE_PREFIX}${userId}`, JSON.stringify(children.map(pickChildFields)));
}

export function getCachedChildren(userId) {
  if (userId == null) return [];
  const cached = safeParse(localStorage.getItem(`${CHILDREN_CACHE_PREFIX}${userId}`));
  return Array.isArray(cached) ? cached : [];
}

export function clearCachedChildren(userId) {
  if (userId == null) return;
  localStorage.removeItem(`${CHILDREN_CACHE_PREFIX}${userId}`);
}

export function setCachedActiveChildId(userId, childId) {
  if (userId == null || childId == null) return;
  localStorage.setItem(`${ACTIVE_CHILD_PREFIX}${userId}`, String(childId));
}

export function getCachedActiveChildId(userId) {
  if (userId == null) return null;
  const raw = localStorage.getItem(`${ACTIVE_CHILD_PREFIX}${userId}`);
  return raw ? Number(raw) : null;
}

export function clearCachedActiveChildId(userId) {
  if (userId == null) return;
  localStorage.removeItem(`${ACTIVE_CHILD_PREFIX}${userId}`);
}

/** Bersihin semua cache offline (profil, daftar anak, anak aktif) punya 1 user — dipanggil pas 401 kekonfirmasi atau logout eksplisit. */
export function clearUserCache(userId) {
  clearCachedUserProfile(userId);
  clearCachedChildren(userId);
  clearCachedActiveChildId(userId);
}
