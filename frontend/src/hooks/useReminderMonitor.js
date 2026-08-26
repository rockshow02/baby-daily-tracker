import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError } from "../api/client";
import { cacheReminderSnapshot, getCachedReminderSnapshot } from "../utils/reminderCache";
import { notifyDueOccurrence } from "../utils/reminderNotifications";

// "Efisien & terbatas" — PythonAnywhere Free nggak punya scheduler
// background, jadi frontend inilah yang berkala nanya ulang status
// reminder SELAGI tab aplikasi terbuka (lihat backend/docs/REMINDERS.md).
// 60 detik cukup responsif buat pengingat (ambang due/overdue-nya sendiri
// dalam hitungan menit, lihat utils/reminder_engine.py), TANPA membebani
// backend gratis dengan polling yang kelewat sering.
const POLL_INTERVAL_MS = 60000;

/**
 * Dipasang SEKALI di AuthenticatedAppShell (persis pola useOfflineSync)
 * — MENGHITUNG ULANG status reminder anak aktif secara berkala SELAGI
 * tab ini terbuka, dipakai bareng buat 2 hal: (1) ringkasan due/overdue/
 * berikutnya di Dashboard, DAN (2) memicu notifikasi browser best-effort
 * (lihat utils/reminderNotifications.js — TIDAK PERNAH notifikasi kalau
 * user belum eksplisit menyalakannya). TIDAK ADA proses latar belakang
 * di sini — ini MURNI polling REST biasa selagi tab terbuka, konsisten
 * sama arsitektur "tanpa scheduler" di seluruh fitur ini.
 */
export function useReminderMonitor({ child, currentUserId, isOnline, onNavigateToReminders }) {
  // loading | ready | offline_cached | offline_no_cache | error
  const [status, setStatus] = useState("loading");
  const [summary, setSummary] = useState(null);
  const [reminders, setReminders] = useState([]);
  const [cachedAt, setCachedAt] = useState(null);
  const childId = child?.id;
  const navigateRef = useRef(onNavigateToReminders);
  navigateRef.current = onNavigateToReminders;

  const loadFromCache = useCallback(() => {
    if (childId == null) return;
    const cached = getCachedReminderSnapshot(currentUserId, childId);
    if (cached) {
      setSummary(cached.data.summary);
      setReminders(cached.data.reminders || []);
      setCachedAt(cached.cachedAt);
      setStatus("offline_cached");
    } else {
      setSummary(null);
      setReminders([]);
      setCachedAt(null);
      setStatus("offline_no_cache");
    }
  }, [currentUserId, childId]);

  const load = useCallback(async () => {
    if (childId == null) return;
    if (!isOnline) {
      loadFromCache();
      return;
    }
    try {
      const res = await api.listReminders(childId);
      setSummary(res.summary);
      setReminders(res.reminders || []);
      setCachedAt(null);
      setStatus("ready");
      cacheReminderSnapshot(currentUserId, childId, res);

      // Notifikasi best-effort — SELAGI tab terbuka doang, cuma buat
      // occurrence yang lagi due/overdue, deduplikasi diurus
      // notifyDueOccurrence() sendiri (lihat utils/reminderNotifications.js).
      for (const reminder of res.reminders || []) {
        for (const occurrence of reminder.occurrences || []) {
          if (occurrence.state === "due" || occurrence.state === "overdue") {
            notifyDueOccurrence({
              userId: currentUserId,
              childId,
              childName: child?.nickname || child?.name,
              reminder,
              occurrence,
              onClickNavigate: () => navigateRef.current && navigateRef.current(),
            });
          }
        }
      }
    } catch (err) {
      if (err instanceof ApiError && err.kind === "network") {
        loadFromCache();
        return;
      }
      setStatus("error");
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [childId, currentUserId, isOnline, loadFromCache, child?.nickname, child?.name]);

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [childId, isOnline]);

  useEffect(() => {
    const interval = setInterval(load, POLL_INTERVAL_MS);
    const onVisibility = () => {
      if (document.visibilityState === "visible") load();
    };
    document.addEventListener("visibilitychange", onVisibility);
    window.addEventListener("online", load);
    return () => {
      clearInterval(interval);
      document.removeEventListener("visibilitychange", onVisibility);
      window.removeEventListener("online", load);
    };
  }, [load]);

  return { status, summary, reminders, cachedAt, reload: load };
}
