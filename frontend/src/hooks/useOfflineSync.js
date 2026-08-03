import { useCallback, useEffect, useState } from "react";
import {
  getQueue,
  getQueueCount,
  removeFromQueue,
} from "../utils/offlineQueue";

const BASE_URL = import.meta.env.VITE_API_URL || "http://localhost:5000/api";

/**
 * Hook buat pantau status koneksi + auto-sync antrian offline begitu
 * online lagi. Dipasang sekali di level App, dipakai buat nampilin
 * indikator "X data belum tersinkron" di mana aja di UI.
 */
export function useOfflineSync() {
  const [isOnline, setIsOnline] = useState(navigator.onLine);
  const [pendingCount, setPendingCount] = useState(0);
  const [syncing, setSyncing] = useState(false);

  const refreshCount = useCallback(async () => {
    try {
      const count = await getQueueCount();
      setPendingCount(count);
    } catch (_) {
      // IndexedDB nggak kebuka (mode private/incognito di beberapa
      // browser bisa nolak) — abaikan aja, fitur offline queue-nya
      // sekadar nggak aktif, sisa app tetap jalan normal
    }
  }, []);

  const syncQueue = useCallback(async () => {
    if (syncing) return; // biar nggak dobel jalan bersamaan
    setSyncing(true);
    try {
      const queue = await getQueue();
      // proses BERURUTAN (bukan paralel) — penting biar urutan waktu
      // pencatatan tetap benar kalau ada beberapa entri yang nunggu
      for (const item of queue) {
        try {
          const res = await fetch(`${BASE_URL}${item.url}`, {
            method: item.method,
            credentials: "include",
            headers: {
              "Content-Type": "application/json",
              ...(item.headers?.Authorization
                ? { Authorization: item.headers.Authorization }
                : {}),
            },
            body: item.body,
          });
          if (res.ok) {
            await removeFromQueue(item.id);
          } else {
            // server nolak (bukan soal koneksi) — request ini emang
            // invalid, hapus dari antrian biar nggak nyangkut selamanya
            await removeFromQueue(item.id);
          }
        } catch (_) {
          // masih offline / gagal jaringan lagi — STOP di sini, sisa
          // antrian dicoba lagi nanti pas online event nyala lagi
          break;
        }
      }
    } finally {
      setSyncing(false);
      await refreshCount();
    }
  }, [syncing, refreshCount]);

  useEffect(() => {
    refreshCount();

    const handleOnline = () => {
      setIsOnline(true);
      syncQueue();
    };
    const handleOffline = () => setIsOnline(false);

    window.addEventListener("online", handleOnline);
    window.addEventListener("offline", handleOffline);

    if (navigator.onLine) {
      syncQueue();
    }

    return () => {
      window.removeEventListener("online", handleOnline);
      window.removeEventListener("offline", handleOffline);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return { isOnline, pendingCount, syncing, syncNow: syncQueue };
}
