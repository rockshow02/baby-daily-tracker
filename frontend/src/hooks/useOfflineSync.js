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
} from "../utils/offlineQueue";
import { getToken, getCurrentUserId, generateRequestId, api } from "../api/client";

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
  const [needsReviewItems, setNeedsReviewItems] = useState([]);
  const [legacyItems, setLegacyItems] = useState([]);

  const syncingRef = useRef(false);
  const retryTimerRef = useRef(null);
  const syncedResetTimerRef = useRef(null);

  const refreshCounts = useCallback(async () => {
    try {
      const userId = getCurrentUserId();
      const mine = userId != null ? await getQueueForUser(userId) : [];
      setPendingCount(mine.filter((i) => i.status !== QUEUE_STATUS.NEEDS_REVIEW).length);
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
          // masih offline / gagal jaringan — retain, backoff, stop run
          const attempts = (item.attempts || 0) + 1;
          const delay = computeBackoffMs(attempts - 1);
          await updateQueueItem(item.id, {
            attempts,
            nextRetryAt: new Date(Date.now() + delay).toISOString(),
            lastError: "Gagal terhubung ke server, akan dicoba lagi.",
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
          // yang di belakangnya, tunggu login ulang
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
        });
      }

      setRunState(removedAny ? "synced" : "idle");
    } finally {
      syncingRef.current = false;
      setSyncing(false);
      await refreshCounts();
      if (removedAny) {
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

    window.addEventListener("online", handleOnline);
    window.addEventListener("offline", handleOffline);

    return () => {
      window.removeEventListener("online", handleOnline);
      window.removeEventListener("offline", handleOffline);
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
    needsReviewCount,
    needsReviewItems,
    legacyItems,
    syncNow: syncQueue,
    discardItem,
    claimLegacyItem,
    retryWithEdits,
  };
}
