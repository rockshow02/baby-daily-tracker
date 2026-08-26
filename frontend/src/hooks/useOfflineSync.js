import { useCallback, useEffect, useRef, useState } from "react";
import {
  getQueue,
  getQueueForUser,
  getLegacyItems,
  removeFromQueue,
  updateQueueItem,
  sanitizeLegacyQueue,
  describeQueueItem,
  QUEUE_STATUS,
  REVIEW_REASON,
  QUEUE_CHANGE_EVENT,
} from "../utils/offlineQueue";
import { getToken, getCurrentUserId, generateRequestId, api } from "../api/client";
import { getLastSyncedAt, setLastSyncedAt } from "../utils/syncMetadata";
import { sanitizeRequestId } from "../utils/requestId";

const BASE_URL = import.meta.env.VITE_API_URL || "http://localhost:5000/api";

const BACKOFF_BASE_MS = 5000; // 5s
const BACKOFF_FACTOR = 2;
const BACKOFF_MAX_MS = 5 * 60 * 1000; // 5 menit — di-cap, tapi TETAP dicoba lagi terus, nggak pernah nyerah

function computeBackoffMs(attempts) {
  return Math.min(BACKOFF_BASE_MS * BACKOFF_FACTOR ** attempts, BACKOFF_MAX_MS);
}

function parseRetryAfter(headerValue) {
  if (!headerValue) return null;
  const seconds = Number(headerValue);
  if (!Number.isNaN(seconds)) return seconds * 1000;
  const dateMs = Date.parse(headerValue);
  if (!Number.isNaN(dateMs)) return Math.max(0, dateMs - Date.now());
  return null;
}

async function readErrorMessage(res) {
  try {
    const data = await res.json();
    if (data?.error) return data.error;
  } catch (_) {
    // body bukan JSON / kosong
  }
  return `Server menolak request ini (${res.status})`;
}

/**
 * Ambil X-Request-ID dari respons server buat troubleshooting — CUMA
 * kalau formatnya cocok whitelist di utils/requestId.js (dipakai bareng
 * sama lapis validasi TAMPILAN di components/RequestIdDetail.jsx —
 * header respons diperlakukan sebagai DATA TIDAK TERPERCAYA sepenuhnya,
 * kalau formatnya nggak persis cocok, dianggap TIDAK ADA, bukan disaring
 * sebagian). Nggak pernah men-generate ID palsu kalau headernya nggak ada
 * (mis. kegagalan jaringan murni, yang memang nggak pernah nyampe ke
 * server sama sekali).
 */
function extractSafeRequestId(res) {
  try {
    return sanitizeRequestId(res?.headers?.get?.("X-Request-ID"));
  } catch (_) {
    return null;
  }
}

/**
 * Hook buat pantau status koneksi + auto-sync antrian offline begitu
 * online lagi. Dipasang sekali di level App (cuma pas user login — lihat
 * App.jsx), dipakai buat nampilin indikator status di OfflineStatusBanner.
 *
 * Antrian diproses BERURUTAN (bukan paralel), dan tiap item di-cek ULANG
 * kepemilikannya (userId) pas mau disync — kalau user yang login sekarang
 * beda dari pemilik item itu (ganti akun / logout), item itu DILEWATIN,
 * BUKAN dihapus atau disync pakai token user yang salah.
 */
export function useOfflineSync() {
  const [isOnline, setIsOnline] = useState(navigator.onLine);
  const [syncing, setSyncing] = useState(false);
  // 'idle' | 'auth_required' | 'retry_scheduled' | 'synced'
  const [runState, setRunState] = useState("idle");
  const [pendingCount, setPendingCount] = useState(0);
  // Item pending (BUKAN needs_review) milik user yang lagi login — dipakai
  // buat "ringkasan catatan nunggu" di Sync Center. `pendingCount` di atas
  // TETAP dipertahankan terpisah (bukan diturunkan dari .length di tempat
  // pakai) biar kode lama yang cuma butuh angkanya nggak perlu berubah.
  const [pendingItems, setPendingItems] = useState([]);
  const [needsReviewItems, setNeedsReviewItems] = useState([]);
  const [legacyItems, setLegacyItems] = useState([]);
  // ISO string atau null — kapan terakhir SEMUA catatan milik user yang
  // lagi login berhasil tersinkron penuh (lihat utils/syncMetadata.js).
  // Dibaca lazy pas mount hook ini — hook ini SENGAJA cuma dipasang 1
  // instance per SESI LOGIN (lihat App.jsx: dipasang di dalam shell yang
  // mount/unmount ngikutin ada-tidaknya user login), jadi "user aktif
  // berubah" (login/logout/ganti akun) SELALU berarti hook ini di-mount
  // ULANG dari nol — nilai awal yang dibaca di sini otomatis selalu milik
  // user yang lagi login, nggak pernah kebawa dari sesi sebelumnya.
  const [lastSyncedAt, setLastSyncedAtState] = useState(() => getLastSyncedAt(getCurrentUserId()));

  const syncingRef = useRef(false);
  const retryTimerRef = useRef(null);
  const syncedResetTimerRef = useRef(null);

  const refreshCounts = useCallback(async () => {
    try {
      const userId = getCurrentUserId();
      const mine = userId != null ? await getQueueForUser(userId) : [];
      const pending = mine.filter((i) => i.status !== QUEUE_STATUS.NEEDS_REVIEW);
      setPendingCount(pending.length);
      setPendingItems(pending);
      setNeedsReviewItems(mine.filter((i) => i.status === QUEUE_STATUS.NEEDS_REVIEW));
      // item legacy TIDAK difilter per-userId (kepemilikannya belum
      // dipastikan) — tapi tetap harus keliatan biar bisa di-klaim/dibuang,
      // makanya query terpisah, bukan bagian dari `mine`.
      setLegacyItems(await getLegacyItems());
    } catch (_) {
      // IndexedDB nggak kebuka (mode private/incognito di beberapa
      // browser bisa nolak) — abaikan aja, fitur offline queue-nya
      // sekadar nggak aktif, sisa app tetap jalan normal
    }
  }, []);

  const clearRetryTimer = () => {
    if (retryTimerRef.current) {
      clearTimeout(retryTimerRef.current);
      retryTimerRef.current = null;
    }
  };

  const syncQueue = useCallback(async () => {
    if (syncingRef.current) return; // biar nggak dobel jalan bersamaan
    syncingRef.current = true;
    setSyncing(true);
    clearRetryTimer();

    let removedAny = false;

    try {
      const queue = await getQueue();

      for (const item of queue) {
        const currentUserId = getCurrentUserId();

        if (currentUserId == null) {
          // nggak ada user aktif (logout di tengah-tengah) — stop total,
          // jangan sentuh item siapapun
          setRunState("idle");
          return;
        }

        if (item.userId !== currentUserId) {
          // punya user lain (atau belum pernah ditandai pemiliknya) —
          // lewatin, JANGAN disync ataupun dihapus
          continue;
        }

        if (item.status === QUEUE_STATUS.NEEDS_REVIEW) {
          // record tidak valid, udah diparkir — jangan diretry otomatis,
          // tapi jangan sampai mem-block record sehat di belakangnya
          continue;
        }

        if (item.nextRetryAt && Date.now() < new Date(item.nextRetryAt).getTime()) {
          // belum waktunya retry — stop di sini biar urutan tetap kejaga
          // (item setelah ini nggak boleh nyalip yang masih nunggu)
          const delay = new Date(item.nextRetryAt).getTime() - Date.now();
          retryTimerRef.current = setTimeout(syncQueue, Math.max(delay, 0));
          setRunState("retry_scheduled");
          return;
        }

        const token = getToken();
        let res;
        try {
          res = await fetch(`${BASE_URL}${item.url}`, {
            method: item.method,
            credentials: "include",
            headers: {
              "Content-Type": "application/json",
              "X-Idempotency-Key": item.clientRequestId,
              ...(token ? { Authorization: `Bearer ${token}` } : {}),
            },
            body: item.body,
          });
        } catch (_networkError) {
          // masih offline / gagal jaringan — retain, backoff, stop run.
          // Gagal jaringan MURNI nggak pernah nyampe ke server sama
          // sekali, jadi nggak mungkin ada X-Request-ID beneran —
          // lastRequestId eksplisit di-null-kan (bukan dibiarin field
          // lama nyangkut) biar diagnostik yang ditampilin selalu cocok
          // sama percobaan TERAKHIR, bukan sisa kegagalan tipe lain.
          const attempts = (item.attempts || 0) + 1;
          const delay = computeBackoffMs(attempts - 1);
          await updateQueueItem(item.id, {
            attempts,
            nextRetryAt: new Date(Date.now() + delay).toISOString(),
            lastError: "Gagal terhubung ke server, akan dicoba lagi.",
            lastRequestId: null,
          });
          retryTimerRef.current = setTimeout(syncQueue, delay);
          setRunState("retry_scheduled");
          return;
        }

        if (res.ok) {
          await removeFromQueue(item.id);
          removedAny = true;
          continue;
        }

        if (res.status === 401) {
          // sesi login abis — STOP total, jangan sentuh item ini ataupun
          // yang di belakangnya, tunggu login ulang. TETAP simpen
          // X-Request-ID buat troubleshooting (kalau ada & valid) — ini
          // CUMA metadata diagnostik aman, BUKAN data fungsional: nggak
          // nambah attempts, nggak ubah body/url/userId/status/
          // clientRequestId, dan urutan retry-nya nggak berubah sama
          // sekali (item ini tetep "pending" persis di posisi yang sama).
          // Eksplisit null-kan kalau nggak ada/nggak valid, biar nggak
          // nyisain lastRequestId BASI dari percobaan SEBELUMNYA yang beda
          // sama sekali dari kegagalan 401 ini.
          await updateQueueItem(item.id, { lastRequestId: extractSafeRequestId(res) });
          setRunState("auth_required");
          return;
        }

        if (res.status === 403) {
          // masih login, tapi kemungkinan udah nggak punya akses ke anak
          // ini (mis. dikeluarin dari daftar pengasuh) — beda dari 401,
          // retry buta nggak bakal nolong, jadi diparkir buat ditinjau
          // manual dan LANJUT ke item berikutnya (bukan stop total)
          await updateQueueItem(item.id, {
            status: QUEUE_STATUS.NEEDS_REVIEW,
            reviewReason: REVIEW_REASON.ACCESS_REVOKED,
            lastError: "Kamu mungkin sudah tidak punya akses ke anak ini.",
            lastRequestId: extractSafeRequestId(res),
          });
          continue;
        }

        if (res.status === 429) {
          const attempts = (item.attempts || 0) + 1;
          const retryAfterMs = parseRetryAfter(res.headers.get("Retry-After"));
          const delay = retryAfterMs != null ? retryAfterMs : computeBackoffMs(attempts - 1);
          await updateQueueItem(item.id, {
            attempts,
            nextRetryAt: new Date(Date.now() + delay).toISOString(),
            lastError: "Server sedang sibuk, akan dicoba lagi.",
            lastRequestId: extractSafeRequestId(res),
          });
          retryTimerRef.current = setTimeout(syncQueue, delay);
          setRunState("retry_scheduled");
          return;
        }

        if (res.status >= 500) {
          const attempts = (item.attempts || 0) + 1;
          const delay = computeBackoffMs(attempts - 1);
          await updateQueueItem(item.id, {
            attempts,
            nextRetryAt: new Date(Date.now() + delay).toISOString(),
            lastError: "Server sedang bermasalah, akan dicoba lagi.",
            lastRequestId: extractSafeRequestId(res),
          });
          retryTimerRef.current = setTimeout(syncQueue, delay);
          setRunState("retry_scheduled");
          return;
        }

        if (res.status === 409) {
          // Idempotency key ini UDAH kepake buat request lain yang isinya
          // beda (backend nge-hash payload-nya, bukan cuma cocokin key —
          // lihat utils/idempotency.py:compute_fingerprint). Ini BEDA dari
          // 400/422: di 400/422 nggak ada baris idempotency yang kesimpen
          // sama sekali (validasinya gagal SEBELUM idempotent_create()
          // dipanggil), jadi retry pakai key yang sama abis dibenerin itu
          // aman. Di 409, sesuatu SUDAH kesimpen di server pakai key ini —
          // retry buta (bahkan abis diedit) cuma bakal kena 409 lagi kalau
          // datanya masih beda dari yang kesimpen. Parkir, JANGAN diretry
          // otomatis, kasih pesan yang jelas biar user nggak nyangka
          // datanya diam-diam ketimpa.
          await updateQueueItem(item.id, {
            status: QUEUE_STATUS.NEEDS_REVIEW,
            reviewReason: REVIEW_REASON.CONFLICT,
            lastError:
              "Request ini sudah pernah diproses server dengan data yang berbeda — tidak disimpan otomatis lagi.",
            lastRequestId: extractSafeRequestId(res),
          });
          continue;
        }

        // 400/422/dst — request-nya sendiri nggak valid, DAN belum pernah
        // ada baris idempotency yang kesimpen buat key ini (validasi gagal
        // sebelum idempotent_create dipanggil di backend) — jadi ngedit
        // lalu retry pakai clientRequestId yang SAMA itu aman, bukan
        // beresiko nabrak record lain. Retry buta (tanpa edit) nggak
        // bakal nolong, jadi diparkir dulu, lanjut ke item berikutnya
        // (jangan sampai 1 record rusak nge-block semuanya).
        const message = await readErrorMessage(res);
        await updateQueueItem(item.id, {
          status: QUEUE_STATUS.NEEDS_REVIEW,
          reviewReason: REVIEW_REASON.VALIDATION,
          lastError: message,
          lastRequestId: extractSafeRequestId(res),
        });
      }

      setRunState(removedAny ? "synced" : "idle");
    } finally {
      syncingRef.current = false;
      setSyncing(false);
      await refreshCounts();
      if (removedAny) {
        // "Berhasil drain semua" CUMA dicatat kalau larinya ini BENERAN
        // ngosongin semua catatan normal (pending) DAN nggak nyisain
        // satupun yang perlu ditinjau punya user yang lagi login — bukan
        // sekadar "1 item sukses tapi masih ada 3 lagi", dan BUKAN
        // "kebetulan udah kosong dari awal tanpa larinya ini beneran
        // ngapa-ngapain" (makanya di dalam `if (removedAny)`, bukan
        // dicek tanpa syarat).
        const currentUserId = getCurrentUserId();
        if (currentUserId != null) {
          const mine = await getQueueForUser(currentUserId);
          const stillPending = mine.filter((i) => i.status !== QUEUE_STATUS.NEEDS_REVIEW).length;
          const stillNeedsReview = mine.length - stillPending;
          if (stillPending === 0 && stillNeedsReview === 0) {
            const now = new Date().toISOString();
            setLastSyncedAt(currentUserId, now);
            setLastSyncedAtState(now);
          }
        }
        clearTimeout(syncedResetTimerRef.current);
        syncedResetTimerRef.current = setTimeout(() => setRunState("idle"), 3000);
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [refreshCounts]);

  useEffect(() => {
    sanitizeLegacyQueue().finally(() => {
      refreshCounts();
      if (navigator.onLine) syncQueue();
    });

    const handleOnline = () => {
      setIsOnline(true);
      syncQueue();
    };
    const handleOffline = () => setIsOnline(false);

    // Reaksi ke PERUBAHAN antrian dari MANA AJA (item baru diantrikan
    // client.js:queueOfflineRequest, item diupdate/dihapus dari luar
    // syncQueue ini sendiri, dst) — SENGAJA cuma refreshCounts() (baca
    // ulang state buat ditampilin), BUKAN syncQueue() — event ini
    // bukan sinyal "koneksi baru balik", jadi nggak boleh nambah jalur
    // auto-sync baru di luar yang udah ada (mount + online). syncQueue
    // sendiri SUDAH motor event ini tiap updateQueueItem/removeFromQueue,
    // jadi listener ini idempotent terhadap panggilan berulang beruntun —
    // sama persis pola yang dipakai pages/Dashboard.jsx.
    const handleQueueChange = () => {
      refreshCounts();
    };

    window.addEventListener("online", handleOnline);
    window.addEventListener("offline", handleOffline);
    window.addEventListener(QUEUE_CHANGE_EVENT, handleQueueChange);

    return () => {
      window.removeEventListener("online", handleOnline);
      window.removeEventListener("offline", handleOffline);
      window.removeEventListener(QUEUE_CHANGE_EVENT, handleQueueChange);
      clearRetryTimer();
      clearTimeout(syncedResetTimerRef.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const discardItem = useCallback(
    async (id) => {
      await removeFromQueue(id);
      await refreshCounts();
    },
    [refreshCounts],
  );

  /**
   * Klaim 1 item legacy (kepemilikan nggak jelas) buat user yang lagi
   * login sekarang — TAPI cuma kalau backend beneran ngonfirmasi user ini
   * punya akses ke anak yang direferensiin item itu (bukan tebak-tebakan
   * lokal). Pakai endpoint /children yang udah ada (GET, balikin anak
   * yang bisa diakses user ini), bukan bikin endpoint baru.
   *
   * Return { claimed: true } kalau berhasil, atau { claimed: false, reason }
   * kalau ditolak (item TETAP di karantina, nggak disentuh).
   */
  const claimLegacyItem = useCallback(
    async (id) => {
      const currentUserId = getCurrentUserId();
      if (currentUserId == null) {
        return { claimed: false, reason: "Kamu harus login dulu buat klaim catatan ini." };
      }

      const [item] = (await getQueue()).filter((i) => i.id === id);
      if (!item) {
        return { claimed: false, reason: "Catatan ini sudah tidak ada." };
      }

      const { childId } = describeQueueItem(item);
      let accessibleChildren;
      try {
        accessibleChildren = await api.listChildren();
      } catch (_) {
        return { claimed: false, reason: "Gagal memeriksa akses ke anak ini, coba lagi." };
      }

      const hasAccess = childId != null && accessibleChildren.some((c) => c.id === childId);
      if (!hasAccess) {
        return { claimed: false, reason: "Kamu nggak punya akses ke anak yang dicatat di sini." };
      }

      await updateQueueItem(id, {
        userId: currentUserId,
        ownerUnknown: false,
        status: QUEUE_STATUS.PENDING,
        reviewReason: null,
        clientRequestId: item.clientRequestId || generateRequestId(),
        attempts: 0,
        nextRetryAt: null,
        lastError: null,
        lastRequestId: null,
      });
      await refreshCounts();
      syncQueue();
      return { claimed: true };
    },
    [refreshCounts, syncQueue],
  );

  /**
   * Simpan body yang udah diedit user buat 1 item needs-review, lalu coba
   * sync lagi — `clientRequestId`-nya SENGAJA dibiarin sama (nggak diganti
   * baru). Ini aman KHUSUS buat item yang gagal karena validasi (400/422):
   * di kasus itu backend belum pernah nyimpen baris idempotency sama
   * sekali buat key ini (validasinya gagal SEBELUM idempotent_create()
   * kepanggil), jadi nggak ada risiko nabrak record lain. Backend tetap
   * ngecek fingerprint payload-nya (bukan cuma key-nya) buat jaga-jaga —
   * kalau ternyata ADA baris lama yang somehow udah kesimpen duluan
   * dengan data yang beda, balikannya 409, bukan diam-diam nimpa/nganggep
   * sama (lihat cabang 409 di atas). UI (QueueReviewPanel) SENGAJA nggak
   * nawarin edit-lalu-retry buat item yang reviewReason-nya "conflict"
   * atau "access_revoked", soalnya retry-nya nggak bakal pernah nolong.
   */
  const retryWithEdits = useCallback(
    async (id, newBody) => {
      await updateQueueItem(id, {
        body: newBody,
        status: QUEUE_STATUS.PENDING,
        reviewReason: null,
        lastError: null,
        nextRetryAt: null,
        attempts: 0,
        lastRequestId: null,
      });
      await refreshCounts();
      syncQueue();
    },
    [refreshCounts, syncQueue],
  );

  const needsReviewCount = needsReviewItems.length;

  let status = "idle";
  if (!isOnline) status = "offline";
  else if (syncing) status = "syncing";
  else if (runState === "auth_required") status = "auth_required";
  else if (runState === "retry_scheduled") status = "retry_scheduled";
  else if (runState === "synced") status = "synced";
  else if (needsReviewCount > 0 || legacyItems.length > 0) status = "needs_review";
  else if (pendingCount > 0) status = "waiting";

  return {
    status,
    isOnline,
    syncing,
    pendingCount,
    pendingItems,
    needsReviewCount,
    needsReviewItems,
    legacyItems,
    lastSyncedAt,
    syncNow: syncQueue,
    discardItem,
    claimLegacyItem,
    retryWithEdits,
  };
}
