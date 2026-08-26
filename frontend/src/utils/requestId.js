/**
 * Validasi X-Request-ID yang DIPAKAI BARENG di 2 titik terpisah:
 *   1. Saat NYIMPEN (hooks/useOfflineSync.js) — sebelum nilai dari header
 *      respons server ditulis ke IndexedDB.
 *   2. Saat NAMPILIN (components/RequestIdDetail.jsx) — SEBAGAI LAPIS
 *      KEDUA yang independen, bukan asumsi "udah divalidasi pas nyimpen
 *      jadi pasti aman dibaca balik". IndexedDB bisa aja kebaca nilai
 *      yang nggak lewat jalur simpan normal (mis. hasil dari versi kode
 *      lama sebelum validasi ini ada, atau data yang diutak-atik manual
 *      lewat devtools) — jadi TIDAK PERNAH dipercaya mentah-mentah cuma
 *      karena datang dari penyimpanan lokal sendiri.
 *
 * Sama persis format yang divalidasi backend (lihat
 * backend/utils/observability.py:REQUEST_ID_RE) — whitelist ketat, bukan
 * blacklist, biar nggak mungkin ada karakter aneh/kontrol/newline yang
 * kesimpen atau ketampil lewat header ini.
 */
export const SAFE_REQUEST_ID_RE = /^[A-Za-z0-9_-]{1,64}$/;

/** Balikin ID yang udah di-trim kalau formatnya valid, atau null kalau nggak. */
export function sanitizeRequestId(value) {
  if (typeof value !== "string") return null;
  const trimmed = value.trim();
  return SAFE_REQUEST_ID_RE.test(trimmed) ? trimmed : null;
}
