import { useEffect, useState, useCallback, useRef } from "react";
import { api, getCurrentUserId } from "../api/client";
import { getQueueForUser, QUEUE_STATUS, QUEUE_CHANGE_EVENT } from "../utils/offlineQueue";
import {
  mapQueueItemToHistoryRecord,
  matchesSelectedDate,
  reconcilePendingArray,
  dedupeByQueueIdentity,
} from "../utils/offlineHistoryMapping";
import DailyRadialClock from "../components/DailyRadialClock";
import FeedingPredictionCard from "../components/FeedingPredictionCard";
import WakeWindowCard from "../components/WakeWindowCard";
import NextVaccineCard from "../components/NextVaccineCard";
import RelatedArticles from "../components/RelatedArticles";
import StatusPill from "../components/StatusPill";
import QuickLogSheet from "../components/QuickLogSheet";
import SwipeableHistoryItem from "../components/SwipeableHistoryItem";
import SmartInsightsBell from "../components/SmartInsightsBell";
import MotorActivityCard from "../components/MotorActivityCard";
import DashboardReminderSummary from "../components/DashboardReminderSummary";
import CaregiverHandoverScreen from "./CaregiverHandoverScreen";
import { weeklyAverageExcludingToday } from "../utils/insights";
import { todayWIB, toWIBDateStr, timePeriodLabel } from "../utils/date";
import { canWrite as canWriteRole, canDeleteRecord } from "../utils/roles";

const todayStr = () => todayWIB();

function formatAge(days) {
  if (days < 60) return `${days} hari`;
  const months = Math.floor(days / 30.44);
  return `${months} bulan`;
}

function timeOf(iso) {
  return new Date(iso).toLocaleTimeString("id-ID", { hour: "2-digit", minute: "2-digit" });
}

/**
 * Label rentang waktu tidur, dipotong (clip) sesuai tanggal yang lagi dilihat.
 * Sesi yang mulai kemarin dan lanjut sampai hari ini bakal kelihatan
 * "00:00 - 05:00 (lanjutan)" pas dilihat di hari ini, dan "20:00 - 24:00
 * (lanjut besok)" pas dilihat di hari kemarin — bukan nampilin rentang
 * penuh yang sama persis di kedua hari (membingungkan).
 */
function sleepTimeRangeLabel(item, viewedDate) {
  const startDateStr = toWIBDateStr(new Date(item.start_time));
  const startsBeforeViewedDay = startDateStr < viewedDate;
  const startLabel = startsBeforeViewedDay ? "00:00" : timeOf(item.start_time);

  if (!item.end_time) {
    return `${startLabel} - berlangsung`;
  }

  const endDateStr = toWIBDateStr(new Date(item.end_time));
  const endsAfterViewedDay = endDateStr > viewedDate;
  const endLabel = endsAfterViewedDay ? "24:00" : timeOf(item.end_time);

  const suffix = startsBeforeViewedDay ? " (lanjutan)" : endsAfterViewedDay ? " (lanjut besok)" : "";
  return `${startLabel} - ${endLabel}${suffix}`;
}

const FEED_TYPE_LABEL = {
  asi_langsung: "ASI Langsung",
  asi_perah: "ASI Perah",
  sufor: "Sufor",
  mpasi: "MPASI",
};

const OTHER_ACTIVITIES = [
  { type: "pumping", icon: "🤱", label: "Perah ASI" },
  { type: "stroll", icon: "🚶", label: "Jalan-jalan" },
  { type: "bathing", icon: "🛁", label: "Mandi" },
  { type: "vitamin", icon: "💊", label: "Vitamin D" },
];

/**
 * True kalau item ini masih optimistic/antrian offline (belum beneran
 * kesimpen di server) — sinyal UTAMA-nya `_offlineQueued`. Cek awalan id
 * "local-" cuma jaring pengaman KEDUA (defensive), buat jaga-jaga kalau
 * suatu saat `_offlineQueued` somehow ilang dari record; JANGAN dijadiin
 * sinyal utama soalnya format id "local-*" itu detail implementasi.
 */
// Diekspor (bukan cuma internal) biar bisa dites langsung sebagai lapis
// proteksi independen dari wiring UI-nya — lihat Dashboard.test.jsx.
export function isPendingOfflineItem(item) {
  if (!item) return false;
  if (item._offlineQueued === true) return true;
  return isLocalOnlyId(item.id);
}

/** Proteksi lapis kedua langsung di titik panggil API — id kayak gini nggak ada di server, jangan pernah dikirim ke endpoint update/delete. */
export function isLocalOnlyId(id) {
  return typeof id === "string" && id.startsWith("local-");
}

export default function Dashboard({ child, onOpenProfile, reminderMonitor, onOpenReminders, onOpenMenu }) {
  const [date, setDate] = useState(todayStr());
  const [summary, setSummary] = useState(null);
  const [feedingLogs, setFeedingLogs] = useState([]);
  const [sleepLogs, setSleepLogs] = useState([]);
  const [diaperLogs, setDiaperLogs] = useState([]);
  const [pumpingLogs, setPumpingLogs] = useState([]);
  const [activityLogs, setActivityLogs] = useState([]);
  const [medicationLogs, setMedicationLogs] = useState([]);
  const [sheetType, setSheetType] = useState(null); // 'feeding' | 'sleep' | 'diaper' | 'pumping' | 'stroll' | 'bathing' | 'vitamin' | null
  const [editingItem, setEditingItem] = useState(null); // item riwayat yang lagi diedit, atau null buat catat baru
  const [showMoreMenu, setShowMoreMenu] = useState(false);
  const [showCaregiverHandover, setShowCaregiverHandover] = useState(false);
  const [loading, setLoading] = useState(true);
  const [weeklyStats, setWeeklyStats] = useState(null);

  const isToday = date === todayStr();

  // Caregiver Roles & Permissions Phase 1 (lihat
  // backend/docs/ROLES_PERMISSIONS.md) — backend TETAP otoritatif buat
  // SEMUA keputusan izin (401/403 tetap ditangani aman di mana pun
  // panggilan API bisa nembus, lihat handleCreate/handleUpdate/
  // handleDelete di bawah); flag di sini CUMA nyembunyiin kontrol yang
  // bakal ditolak backend, biar viewer nggak nawarin tombol yang
  // percuma. `child.role` yang undefined/null (cache lama sebelum field
  // ini ada) otomatis kehitung read-only lewat canWriteRole().
  const canWrite = canWriteRole(child.role);
  const currentUserId = getCurrentUserId();

  // insight cuma masuk akal buat "hari ini" (bandingin ke tren beberapa
  // hari terakhir) — pas lihat riwayat tanggal lama, nggak perlu fetch ini
  useEffect(() => {
    if (!isToday) {
      setWeeklyStats(null);
      return;
    }
    api
      .getStats(child.id, 7)
      .then((res) => setWeeklyStats(res.days || []))
      .catch(() => {
        // gagal (mis. offline) — insight mingguan sekadar nggak tampil,
        // BUKAN error yang perlu diributin ke user; jangan sampai jadi
        // unhandled promise rejection
      });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [child.id, isToday, feedingLogs.length, sleepLogs.length, diaperLogs.length]);

  const weeklyAverages = weeklyStats
    ? {
        feeding: weeklyAverageExcludingToday(weeklyStats, "feeding_count", date),
        sleep: weeklyAverageExcludingToday(weeklyStats, "sleep_hours", date),
        wetDiaper: weeklyAverageExcludingToday(weeklyStats, "wet_diaper_count", date),
      }
    : null;

  // null | "offline" — nyimpen kenapa loadAll() TERAKHIR gagal, biar
  // ke-bedain dari "belum ada catatan" beneran (lihat bagian render Riwayat)
  const [loadError, setLoadError] = useState(null);
  const loadAllRef = useRef(null);

  /**
   * Baca ulang antrian offline milik user yang lagi login, buat anak &
   * tanggal yang lagi ditampilin, terus SELARASKAN 6 state array riwayat:
   * - entri optimistic (`_offlineQueued`) yang id-nya UDAH NGGAK ADA lagi
   *   di antrian (abis kesync ATAU dibuang manual) dibuang dari state,
   * - entri pending yang BELUM ada di state (mis. abis Dashboard di-mount
   *   ulang, atau anak/tanggal baru dipilih) ditambahin.
   * Fungsi murni buat kalkulasi "state array berikutnya"-nya sendiri ada
   * di utils/offlineHistoryMapping.js (reconcilePendingArray) — di sini
   * cuma nyambungin ke IndexedDB + state React-nya.
   *
   * Item yang statusnya needs_review atau ownerUnknown SENGAJA disaring di
   * sini (nggak ikut direstorasi jadi record riwayat biasa) — itu tetap
   * ditangani lewat QueueReviewPanel yang sudah ada.
   */
  const prevPendingIdsRef = useRef(new Set());
  const reconcilePendingFromQueue = useCallback(async () => {
    // SELURUH badan fungsi ini dibungkus try/catch — dipanggil dari
    // beberapa tempat TANPA di-await/di-catch (mis. listener event), jadi
    // fungsi ini WAJIB nggak pernah reject sama sekali, biar nggak ada
    // unhandled promise rejection nongol di manapun dia dipanggil.
    try {
      const userId = getCurrentUserId();
      if (userId == null) return; // nggak ada user aktif (mis. lagi proses logout) — jangan restorasi apa-apa

      const queueItems = await getQueueForUser(userId);

      const mapped = dedupeByQueueIdentity(
        queueItems
          .filter((item) => item.status === QUEUE_STATUS.PENDING && !item.ownerUnknown)
          .map(mapQueueItemToHistoryRecord)
          .filter(Boolean)
          .filter((record) => record.childId === child.id)
          .filter((record) => matchesSelectedDate(record, date)),
      );

      const currentIds = new Set(mapped.map((r) => r.id));
      const somethingDisappeared = [...prevPendingIdsRef.current].some((id) => !currentIds.has(id));
      prevPendingIdsRef.current = currentIds;

      setFeedingLogs((prev) => reconcilePendingArray(prev, mapped.filter((r) => r.kind === "feeding")));
      setSleepLogs((prev) => reconcilePendingArray(prev, mapped.filter((r) => r.kind === "sleep")));
      setDiaperLogs((prev) => reconcilePendingArray(prev, mapped.filter((r) => r.kind === "diaper")));
      setPumpingLogs((prev) => reconcilePendingArray(prev, mapped.filter((r) => r.kind === "pumping")));
      setActivityLogs((prev) =>
        reconcilePendingArray(prev, mapped.filter((r) => r.kind === "stroll" || r.kind === "bathing")),
      );
      setMedicationLogs((prev) => reconcilePendingArray(prev, mapped.filter((r) => r.kind === "vitamin")));

      if (somethingDisappeared) {
        // sesuatu yang tadinya masih pending sekarang udah nggak ada lagi
        // di antrian — kemungkinan besar abis KESYNC (bisa juga dibuang
        // manual lewat panel review; dua-duanya aman di-refresh, cuma 1
        // GET ekstra yang nggak masalah) -> tarik data server terbaru
        // biar record asli (id numerik dari server) muncul gantiin yang
        // optimistic. loadAll() sendiri udah nggak pernah reject (self
        // contained try/catch), jadi aman dipanggil tanpa await di sini.
        loadAllRef.current?.();
      }
    } catch (_) {
      // IndexedDB nggak kebuka, atau kegagalan nggak terduga lain — fitur
      // restorasi sekadar nggak aktif buat siklus ini, sisa Dashboard
      // (data server yang udah kemuat) tetap jalan normal
    }
  }, [child.id, date]);

  const loadAll = useCallback(async () => {
    setLoading(true);
    try {
      const [s, f, sl, d, p, a, m] = await Promise.all([
        api.dailySummary(child.id, date),
        api.listFeeding(child.id, date),
        api.listSleep(child.id, date),
        api.listDiaper(child.id, date),
        api.listPumping(child.id, date),
        api.listActivity(child.id, date),
        api.listMedication(child.id, date),
      ]);
      setSummary(s);
      setFeedingLogs(f);
      setSleepLogs(sl);
      setDiaperLogs(d);
      setPumpingLogs(p);
      setActivityLogs(a);
      setMedicationLogs(m);
      setLoadError(null);
    } catch (_err) {
      // GET gagal (biasanya offline) — ini masalah MEMUAT data server,
      // BUKAN kehilangan data yang udah diqueue: data offline yang udah
      // ke-queue tetap aman di IndexedDB, direstorasi terpisah di bawah
      setLoadError("offline");
    } finally {
      setLoading(false);
    }
    // reconcile SETELAH loadAll — soalnya setFeedingLogs(f) dkk di atas
    // NGE-TIMPA seluruh array (cuma data server), jadi record yang masih
    // pending (belum kesync) perlu ditambahin balik biar nggak ilang
    await reconcilePendingFromQueue();
  }, [child.id, date, reconcilePendingFromQueue]);

  useEffect(() => {
    loadAllRef.current = loadAll;
  }, [loadAll]);

  useEffect(() => {
    loadAll();
  }, [loadAll]);

  // reagen ke perubahan antrian offline dari MANA AJA (sync sukses, item
  // baru diantrikan, status berubah jadi needs_review, dibuang manual,
  // dll) — lihat utils/offlineQueue.js:QUEUE_CHANGE_EVENT. Listener-nya
  // idempotent (baca ulang IndexedDB tiap kali), jadi aman kalau event-nya
  // nyala berkali-kali beruntun.
  useEffect(() => {
    const handleQueueChange = () => {
      reconcilePendingFromQueue();
    };
    window.addEventListener(QUEUE_CHANGE_EVENT, handleQueueChange);
    return () => window.removeEventListener(QUEUE_CHANGE_EVENT, handleQueueChange);
  }, [reconcilePendingFromQueue]);

  // begitu koneksi balik, coba muat ulang data server otomatis — jalur
  // retry buat kasus "Dashboard sempat gagal loadAll() pas offline"
  useEffect(() => {
    const handleOnline = () => {
      loadAllRef.current?.();
    };
    window.addEventListener("online", handleOnline);
    return () => window.removeEventListener("online", handleOnline);
  }, []);

  // pill notifikasi "tersimpan offline" — SENGAJA dibikin mirip pola
  // pendingDelete di bawah (bar mengambang, ilang sendiri), bukan sistem
  // toast baru, biar konsisten sama UI yang udah ada
  const [offlineSavedNotice, setOfflineSavedNotice] = useState(false);
  const offlineNoticeTimeoutRef = useRef(null);
  const OFFLINE_NOTICE_DURATION_MS = 4000;

  useEffect(() => {
    return () => clearTimeout(offlineNoticeTimeoutRef.current);
  }, []);

  const showOfflineSavedNotice = () => {
    setOfflineSavedNotice(true);
    clearTimeout(offlineNoticeTimeoutRef.current);
    offlineNoticeTimeoutRef.current = setTimeout(() => setOfflineSavedNotice(false), OFFLINE_NOTICE_DURATION_MS);
  };

  // nambahin record baru (asli dari server ATAU optimistic dari antrian
  // offline) ke state lokal yang sesuai jenisnya, biar langsung kelihatan
  // di riwayat tanpa perlu loadAll() dulu
  // Nambahin record baru CUMA kalau id-nya belum ada (dedup by id, BUKAN
  // reconcilePendingArray — itu mangkas SEMUA entri _offlineQueued lain
  // yang nggak ada di daftar "fresh" barunya, cocok buat rekonsiliasi
  // penuh tapi SALAH di sini karena kita cuma mau nambah 1 item, bukan
  // ngasih daftar lengkap ulang). Dedup ini perlu soalnya item yang sama
  // (id `local-<queueId>` yang sama) bisa aja UDAH keduluan ditambahin
  // sama reconcilePendingFromQueue (dipicu QUEUE_CHANGE_EVENT dari
  // enqueueRequest, yang kepanggil SEBELUM handleCreate nyampe sini).
  const appendIfNew = (record) => (prev) =>
    prev.some((item) => item.id === record.id) ? prev : [record, ...prev];

  const addOptimisticLog = (type, record) => {
    if (type === "feeding") setFeedingLogs(appendIfNew(record));
    else if (type === "sleep") setSleepLogs(appendIfNew(record));
    else if (type === "diaper") setDiaperLogs(appendIfNew(record));
    else if (type === "pumping") setPumpingLogs(appendIfNew(record));
    else if (type === "stroll" || type === "bathing") setActivityLogs(appendIfNew(record));
    else if (type === "vitamin") setMedicationLogs(appendIfNew(record));
  };

  const createByType = async (type, payload) => {
    if (type === "feeding") return await api.createFeeding(child.id, payload);
    if (type === "sleep") return await api.createSleep(child.id, payload);
    if (type === "diaper") return await api.createDiaper(child.id, payload);
    if (type === "pumping") return await api.createPumping(child.id, payload);
    if (type === "stroll" || type === "bathing") return await api.createActivity(child.id, payload);
    if (type === "vitamin") return await api.createMedication(child.id, payload);
    return undefined;
  };

  const handleCreate = async (type, payload) => {
    // kalau createByType() sendiri gagal (request-nya beneran ditolak,
    // ATAU IndexedDB gagal dipakai buat antri pas offline), exception-nya
    // BIARIN nembus ke atas apa adanya — itu yang bikin QuickLogSheet tau
    // penyimpanannya beneran gagal (modal tetap kebuka, pesan error muncul)
    const result = await createByType(type, payload);

    if (result?._offlineQueued) {
      // offline: request-nya UDAH SUKSES diantrikan (bukan gagal!) — JANGAN
      // panggil loadAll(), soalnya GET bakal gagal offline dan bikin
      // penyimpanan yang sebenarnya sukses ini keanggep gagal. Cukup
      // tambahin optimistic record ke state lokal.
      addOptimisticLog(type, result);
      showOfflineSavedNotice();
      return result;
    }

    // online, beneran kesimpen di server — refresh biar dapet data lengkap
    // (id asli, created_by_name, dll). Kalau refresh-nya sendiri yang gagal
    // (mis. koneksi putus PAS SETELAH create sukses), itu kegagalan REFRESH,
    // BUKAN kegagalan SIMPAN — jangan sampai bikin QuickLogSheet ngelaporin
    // "gagal disimpan" padahal datanya udah aman di server.
    try {
      await loadAll();
    } catch (_) {
      // data lokal mungkin agak basi sampai refresh berikutnya berhasil,
      // tapi record-nya sendiri udah tersimpan — bukan kegagalan buat user
    }
    return result;
  };

  const handleUpdate = async (kind, id, payload) => {
    if (isLocalOnlyId(id)) return; // defensif — record ini belum ada di server, jangan pernah dikirim ke endpoint update
    if (kind === "feeding") await api.updateFeeding(id, payload);
    if (kind === "sleep") await api.updateSleep(id, payload);
    if (kind === "diaper") await api.updateDiaper(id, payload);
    if (kind === "pumping") await api.updatePumping(id, payload);
    if (kind === "stroll" || kind === "bathing") await api.updateActivity(id, payload);
    if (kind === "vitamin") await api.updateMedication(id, payload);
    await loadAll();
  };

  const handleSheetSubmit = async (payload) => {
    if (editingItem) {
      await handleUpdate(editingItem.kind, editingItem.id, payload);
    } else {
      await handleCreate(sheetType, payload);
    }
  };

  const openEdit = (item) => {
    // catatan yang masih nunggu sinkron belum punya id asli di server —
    // belum bisa diedit sampai selesai disinkronkan
    if (isPendingOfflineItem(item)) return;
    // viewer (atau role yang nggak dikenal) nggak boleh ubah apa pun —
    // backend bakal nolak juga, ini cuma nyegah modal edit percuma kebuka
    if (!canWrite) return;
    setSheetType(item.kind);
    setEditingItem(item);
  };

  const closeSheet = () => {
    setSheetType(null);
    setEditingItem(null);
  };

  const handleDelete = async (kind, id) => {
    if (isLocalOnlyId(id)) return; // defensif — record ini belum ada di server, jangan pernah dikirim ke endpoint delete
    if (kind === "feeding") await api.deleteFeeding(id);
    if (kind === "sleep") await api.deleteSleep(id);
    if (kind === "diaper") await api.deleteDiaper(id);
    if (kind === "pumping") await api.deletePumping(id);
    if (kind === "stroll" || kind === "bathing") await api.deleteActivity(id);
    if (kind === "vitamin") await api.deleteMedication(id);
    await loadAll();
  };

  // duplikasi 1 entri jadi entri baru dengan waktu SEKARANG, data lainnya
  // sama persis — biar nggak perlu ngisi ulang form dari nol
  const handleDuplicate = async (item) => {
    // belum sinkron -> jangan bikin antrian POST baru lagi buat duplikatnya
    // (UI udah nyembunyiin aksi ini buat item pending, ini jaring pengaman kedua)
    if (isPendingOfflineItem(item)) return;
    const nowIso = new Date().toISOString();
    let type = item.kind;
    let payload = {};

    if (item.kind === "feeding") {
      payload = {
        timestamp: nowIso,
        feed_type: item.feed_type,
        duration_minutes: item.duration_minutes,
        volume_ml: item.volume_ml,
        breast_side: item.breast_side,
      };
    } else if (item.kind === "sleep") {
      payload = { start_time: nowIso, end_time: null, sleep_type: item.sleep_type };
    } else if (item.kind === "diaper") {
      payload = { timestamp: nowIso, diaper_type: item.diaper_type, consistency: item.consistency };
    } else if (item.kind === "pumping") {
      payload = {
        timestamp: nowIso,
        duration_minutes: item.duration_minutes,
        volume_ml: item.volume_ml,
        breast_side: item.breast_side,
      };
    } else if (item.kind === "stroll" || item.kind === "bathing") {
      payload = {
        timestamp: nowIso,
        activity_type: item.kind,
        duration_minutes: item.duration_minutes,
        notes: item.notes,
      };
    } else if (item.kind === "vitamin") {
      payload = { timestamp: nowIso, medication_name: item.medication_name };
    }

    await handleCreate(type, payload);
  };

  // hapus dengan jeda "Batalkan" — item langsung disembunyikan dari
  // tampilan (optimistic), tapi baru BENERAN dihapus dari server setelah
  // beberapa detik kalau nggak dibatalkan. Biar nggak was-was kepencet
  // nggak sengaja pas lagi buru-buru.
  const [hiddenKeys, setHiddenKeys] = useState(new Set());
  const [pendingDelete, setPendingDelete] = useState(null); // {key, kind, id, timeoutId}
  const UNDO_DELAY_MS = 5000;

  const handleSoftDelete = (item) => {
    // belum sinkron -> nggak ada apa-apa di server buat dihapus, dan
    // nyembunyiin item ini secara optimistic bisa bikin dia "ilang" terus
    // (id lokalnya nggak akan pernah match record asli abis kesync)
    if (isPendingOfflineItem(item)) return;
    const key = `${item.kind}-${item.id}`;

    // kalau ada penghapusan lain yang masih nunggu, langsung eksekusi
    // dulu (jangan numpuk beberapa "pending" bersamaan, bikin bingung)
    if (pendingDelete) {
      clearTimeout(pendingDelete.timeoutId);
      handleDelete(pendingDelete.kind, pendingDelete.id);
    }

    setHiddenKeys((prev) => new Set(prev).add(key));
    const timeoutId = setTimeout(async () => {
      await handleDelete(item.kind, item.id);
      setPendingDelete(null);
      setHiddenKeys((prev) => {
        const next = new Set(prev);
        next.delete(key);
        return next;
      });
    }, UNDO_DELAY_MS);

    setPendingDelete({ key, kind: item.kind, id: item.id, label: item.kind, timeoutId });
  };

  const handleUndoDelete = () => {
    if (!pendingDelete) return;
    clearTimeout(pendingDelete.timeoutId);
    setHiddenKeys((prev) => {
      const next = new Set(prev);
      next.delete(pendingDelete.key);
      return next;
    });
    setPendingDelete(null);
  };

  const handleWakeUp = async (item) => {
    // belum sinkron -> belum ada sleep log asli di server buat di-update
    if (isPendingOfflineItem(item)) return;
    await api.updateSleep(item.id, { end_time: new Date().toISOString() });
    await loadAll();
  };

  const shiftDate = (deltaDays) => {
    const d = new Date(date);
    d.setDate(d.getDate() + deltaDays);
    const next = toWIBDateStr(d);
    if (next > todayStr()) return;
    setDate(next);
  };

  // gabungkan semua log jadi satu riwayat urut waktu
  const historyItems = [
    ...feedingLogs.map((l) => ({ ...l, kind: "feeding", at: l.timestamp })),
    ...diaperLogs.map((l) => ({ ...l, kind: "diaper", at: l.timestamp })),
    ...sleepLogs.map((l) => ({ ...l, kind: "sleep", at: l.start_time })),
    ...pumpingLogs.map((l) => ({ ...l, kind: "pumping", at: l.timestamp })),
    ...activityLogs.map((l) => ({ ...l, kind: l.activity_type, at: l.timestamp })),
    ...medicationLogs.map((l) => ({ ...l, kind: "vitamin", at: l.timestamp })),
  ].sort((a, b) => new Date(b.at) - new Date(a.at))
    .filter((item) => !hiddenKeys.has(`${item.kind}-${item.id}`));

  // kelompokin riwayat per periode waktu (Pagi/Siang/Sore/Malam) — dibikin
  // dari list yang UDAH keurut (terbaru dulu), jadi grup baru dibuat tiap
  // periode-nya beda dari item sebelumnya, biar urutannya tetap natural
  const groupedHistory = historyItems.reduce((groups, item) => {
    const period = timePeriodLabel(item.at);
    const lastGroup = groups[groups.length - 1];
    if (lastGroup && lastGroup.period === period) {
      lastGroup.items.push(item);
    } else {
      groups.push({ period, items: [item] });
    }
    return groups;
  }, []);

  const dotColor = (kind) => {
    if (kind === "feeding" || kind === "pumping" || kind === "vitamin") return "bg-feed";
    if (kind === "sleep" || kind === "stroll") return "bg-sleep";
    return "bg-diaper"; // diaper, bathing
  };

  // ringkasan ala PiyoLog: ASI langsung vs botol dipisah, biar lebih detail
  const nursingCount = feedingLogs.filter((l) => l.feed_type === "asi_langsung").length;
  const bottleLogs = feedingLogs.filter((l) => l.feed_type === "asi_perah" || l.feed_type === "sufor");
  const bottleCount = bottleLogs.length;
  const bottleMl = bottleLogs.reduce((sum, l) => sum + (l.volume_ml || 0), 0);
  // pakai angka dari summary.sleep.actual_hours (backend), BUKAN jumlah
  // mentah duration_minutes dari sleepLogs — soalnya sleepLogs sekarang
  // termasuk sesi yang lintas tengah malam (overlap sama hari ini), dan
  // duration_minutes-nya itu durasi PENUH sesi itu, belum dipotong sesuai
  // porsi hari yang lagi dilihat. summary.sleep.actual_hours udah bener
  // dipotong per hari (fix yang sama kayak Bug #2 sebelumnya).
  const sleepActualHours = summary ? summary.sleep.actual_hours : 0;
  const sleepH = Math.floor(sleepActualHours);
  const sleepM = Math.round((sleepActualHours % 1) * 60);
  const wetCount = diaperLogs.filter((l) => l.diaper_type === "pipis" || l.diaper_type === "keduanya").length;
  const dirtyCount = diaperLogs.filter((l) => l.diaper_type === "pup" || l.diaper_type === "keduanya").length;
  const ongoingSleep = sleepLogs.find((log) => !log.end_time);
  const greetingHour = new Date().getHours();
  const greeting = greetingHour < 11 ? "Selamat pagi" : greetingHour < 15 ? "Selamat siang" : greetingHour < 19 ? "Selamat sore" : "Selamat malam";

  return (
    <div className="min-h-screen pb-8">
      <header className="px-5 pb-5 pt-5">
        <div className="flex items-center justify-between gap-4">
          <div>
            <p className="text-sm font-semibold text-ink-muted">{greeting}</p>
            <h1 className="mt-0.5 font-display text-3xl leading-tight text-ink">Hari ini</h1>
          </div>
          <div className="flex items-center gap-2">
            {isToday && <SmartInsightsBell summary={summary} weeklyAverages={weeklyAverages} />}
            {onOpenMenu && (
              <button
                type="button"
                onClick={onOpenMenu}
                aria-label="Buka menu lainnya"
                className="flex h-10 w-10 items-center justify-center rounded-full border border-void-hairline bg-white text-base text-ink-muted shadow-soft"
              >
                ☰
              </button>
            )}
          </div>
        </div>

        <div className="mt-5 flex flex-col gap-3 min-[380px]:flex-row min-[380px]:items-center min-[380px]:justify-between">
          <button type="button" onClick={onOpenProfile} className="flex min-w-0 items-center gap-3 text-left">
            {child.photo_filename ? (
              <img
                src={api.photoUrl(child.photo_filename)}
                alt={child.name}
                className="h-14 w-14 rounded-full border-2 border-white object-cover shadow-soft"
              />
            ) : (
              <span className="flex h-14 w-14 items-center justify-center rounded-full bg-feed-soft text-2xl shadow-soft" aria-hidden="true">
                👶
              </span>
            )}
            <span className="min-w-0">
              <span className="block break-words text-lg font-extrabold leading-tight text-ink">{child.nickname || child.name}</span>
              <span className="block text-xs text-ink-muted">{summary ? formatAge(summary.age_days) : "Memuat usia..."} · Lihat profil ›</span>
            </span>
          </button>
          <div className="flex w-full flex-shrink-0 items-center justify-between rounded-full border border-void-hairline bg-white p-1 shadow-soft min-[380px]:w-auto min-[380px]:justify-start">
            <button type="button" aria-label="Hari sebelumnya" onClick={() => shiftDate(-1)} className="flex h-8 w-8 items-center justify-center rounded-full text-lg text-ink-muted hover:bg-void-raised">
              ‹
            </button>
            <span className="min-w-[64px] px-1 text-center text-xs font-bold text-ink-muted">
              {isToday ? "Hari ini" : new Date(date).toLocaleDateString("id-ID", { day: "2-digit", month: "short" })}
            </span>
            <button type="button" aria-label="Hari berikutnya" onClick={() => shiftDate(1)} disabled={isToday} className="flex h-8 w-8 items-center justify-center rounded-full text-lg text-ink-muted hover:bg-void-raised disabled:opacity-25">
              ›
            </button>
          </div>
        </div>

        <div className="mt-4 grid grid-cols-3 gap-2" aria-label="Aksi data dan pengasuh">
          <button
            type="button"
            aria-label="Export laporan PDF"
            onClick={() =>
              api.downloadAuthenticated(
                api.exportPdfUrl(child.id),
                `laporan-${child.name.toLowerCase()}.pdf`
              )
            }
            className="flex min-h-12 flex-col items-center justify-center gap-0.5 rounded-2xl bg-white px-1.5 py-2 text-center text-[10px] font-semibold leading-tight text-ink-muted shadow-sm"
          >
            <span className="text-base" aria-hidden="true">📄</span>
            <span>Export PDF</span>
          </button>
          <button
            type="button"
            aria-label="Backup data (JSON)"
            onClick={() =>
              api.downloadAuthenticated(
                api.exportJsonUrl(child.id),
                `backup-${child.name.toLowerCase()}.json`
              )
            }
            className="flex min-h-12 flex-col items-center justify-center gap-0.5 rounded-2xl bg-white px-1.5 py-2 text-center text-[10px] font-semibold leading-tight text-ink-muted shadow-sm"
          >
            <span className="text-base" aria-hidden="true">💾</span>
            <span>Backup JSON</span>
          </button>
          <button
            type="button"
            aria-label="Serah Terima Pengasuh"
            onClick={() => setShowCaregiverHandover(true)}
            className="flex min-h-12 flex-col items-center justify-center gap-0.5 rounded-2xl bg-white px-1.5 py-2 text-center text-[10px] font-semibold leading-tight text-ink-muted shadow-sm"
          >
            <span className="text-base" aria-hidden="true">🤝</span>
            <span>Serah terima</span>
          </button>
        </div>
      </header>

      {isToday && ongoingSleep && (
        <section className="mx-5 mb-5 overflow-hidden rounded-[1.75rem] bg-gradient-to-br from-sleep to-[#B7A7F6] p-5 text-white shadow-soft" aria-label="Status tidur saat ini">
          <div className="flex items-center justify-between gap-4">
            <div>
              <p className="text-sm font-semibold text-white/80">{child.nickname || child.name} sedang tidur</p>
              <p className="mt-1 font-display text-3xl">Sejak {timeOf(ongoingSleep.start_time)}</p>
              <p className="mt-1 text-xs text-white/75">Ketuk catatan tidur untuk mengakhiri sesi.</p>
            </div>
            <span className="baby-float text-6xl" aria-hidden="true">🌙</span>
          </div>
        </section>
      )}

      <section className="px-5" aria-labelledby="daily-summary-title">
        <div className="mb-3 flex items-end justify-between">
          <div>
            <p className="text-xs font-bold uppercase tracking-[0.16em] text-feed">Ringkasan hari ini</p>
            <h2 id="daily-summary-title" className="mt-1 text-xl font-extrabold text-ink">Aktivitas utama</h2>
          </div>
          <span className="text-xs text-ink-faint">{nursingCount + bottleCount + sleepLogs.length + diaperLogs.length} catatan</span>
        </div>
        <div className="grid grid-cols-3 gap-2.5">
          <div className="min-w-0 rounded-xl2 bg-feed-soft px-2 py-3.5 text-center">
            <span className="text-2xl" aria-hidden="true">🍼</span>
            <p className="mt-2 text-xl font-extrabold text-ink">{nursingCount + bottleCount}x</p>
            <p className="text-xs font-semibold text-ink-muted">Total susu</p>
            {bottleMl > 0 && <p className="mt-1 text-[10px] text-ink-faint">{bottleMl}ml dari botol</p>}
          </div>
          <div className="min-w-0 rounded-xl2 bg-sleep-soft px-2 py-3.5 text-center">
            <span className="text-2xl" aria-hidden="true">🌙</span>
            <p className="mt-2 text-xl font-extrabold text-ink">{sleepH}j {sleepM}m</p>
            <p className="text-xs font-semibold text-ink-muted">Tidur</p>
          </div>
          <div className="min-w-0 rounded-xl2 bg-diaper-soft px-2 py-3.5 text-center">
            <span className="text-2xl" aria-hidden="true">🧷</span>
            <p className="mt-2 text-xl font-extrabold text-ink">{wetCount + dirtyCount}x</p>
            <p className="text-xs font-semibold text-ink-muted">Popok</p>
          </div>
        </div>
      </section>

      {canWrite && (
        <section className="px-5 pb-6 pt-6" aria-labelledby="quick-log-title">
          <h2 id="quick-log-title" className="mb-3 text-base font-extrabold text-ink">Catat cepat</h2>
          <div className="grid grid-cols-2 gap-3">
            <button onClick={() => { setEditingItem(null); setSheetType("feeding"); }} className="flex min-h-[76px] min-w-0 items-center gap-2 overflow-hidden rounded-xl2 bg-feed-soft p-3 text-left text-sm font-bold text-ink transition-transform active:scale-[0.98]">
              <span className="flex h-10 w-10 flex-shrink-0 items-center justify-center rounded-full bg-white text-xl shadow-sm">🍼</span>
              <span className="min-w-0">Susu<span className="mt-0.5 hidden whitespace-nowrap text-[9px] font-medium text-ink-muted min-[360px]:block">Catat sekarang ›</span></span>
            </button>
            <button onClick={() => { setEditingItem(null); setSheetType("sleep"); }} className="flex min-h-[76px] min-w-0 items-center gap-2 overflow-hidden rounded-xl2 bg-sleep-soft p-3 text-left text-sm font-bold text-ink transition-transform active:scale-[0.98]">
              <span className="flex h-10 w-10 flex-shrink-0 items-center justify-center rounded-full bg-white text-xl shadow-sm">🌙</span>
              <span className="min-w-0">Tidur<span className="mt-0.5 hidden whitespace-nowrap text-[9px] font-medium text-ink-muted min-[360px]:block">Catat sekarang ›</span></span>
            </button>
            <button onClick={() => { setEditingItem(null); setSheetType("diaper"); }} className="flex min-h-[76px] min-w-0 items-center gap-2 overflow-hidden rounded-xl2 bg-diaper-soft p-3 text-left text-sm font-bold text-ink transition-transform active:scale-[0.98]">
              <span className="flex h-10 w-10 flex-shrink-0 items-center justify-center rounded-full bg-white text-xl shadow-sm">🧷</span>
              <span className="min-w-0">Popok<span className="mt-0.5 hidden whitespace-nowrap text-[9px] font-medium text-ink-muted min-[360px]:block">Catat sekarang ›</span></span>
            </button>
            <button onClick={() => setShowMoreMenu(true)} className="flex min-h-[76px] min-w-0 items-center gap-2 overflow-hidden rounded-xl2 bg-sky-soft p-3 text-left text-sm font-bold text-ink transition-transform active:scale-[0.98]">
              <span className="flex h-10 w-10 flex-shrink-0 items-center justify-center rounded-full bg-white text-xl text-sky shadow-sm">•••</span>
              <span className="min-w-0">Lainnya<span className="mt-0.5 hidden whitespace-nowrap text-[9px] font-medium text-ink-muted min-[360px]:block">Catat aktivitas ›</span></span>
            </button>
          </div>
        </section>
      )}

      <div className="px-5">
        <NextVaccineCard childId={child.id} />
      </div>

      {isToday && (
        <div className="px-6">
          <FeedingPredictionCard childId={child.id} refreshKey={feedingLogs.length} />
          <WakeWindowCard childId={child.id} refreshKey={sleepLogs.length} />
        </div>
      )}

      {/* info singkat anak */}
      <div className="px-6 mb-4">
        <div className="bg-void-card border border-void-hairline rounded-xl2 px-4 py-3.5 flex items-center justify-between">
          <div>
            <p className="text-sm text-ink">
              {child.nickname || child.name} · {summary ? formatAge(summary.age_days) : "..."}
            </p>
            <p className="text-xs text-ink-faint mt-0.5">
              {child.gender === "L" ? "Laki-laki" : child.gender === "P" ? "Perempuan" : ""}
              {child.birth_weight_kg && ` · Lahir ${child.birth_weight_kg} kg`}
              {child.birth_height_cm && ` / ${child.birth_height_cm} cm`}
            </p>
          </div>
          <button
            onClick={onOpenProfile}
            className="text-xs text-feed font-medium whitespace-nowrap flex-shrink-0 ml-3"
          >
            Lihat Selengkapnya →
          </button>
        </div>
      </div>

      {reminderMonitor && (
        <div className="px-6">
          <DashboardReminderSummary
            status={reminderMonitor.status}
            summary={reminderMonitor.summary}
            onOpen={onOpenReminders}
          />
        </div>
      )}

      {isToday && (
        <div className="px-6">
          <MotorActivityCard ageMonths={summary ? summary.age_days / 30.4375 : null} />
        </div>
      )}

      {/* radial clock */}
      <div className="px-6 py-4 flex justify-center">
        <DailyRadialClock feedingLogs={feedingLogs} sleepLogs={sleepLogs} diaperLogs={diaperLogs} />
      </div>

      {/* legend */}
      <div className="flex justify-center gap-4 -mt-2 mb-6">
        <span className="flex items-center gap-1.5 text-xs text-ink-muted">
          <span className="w-2 h-2 rounded-full bg-feed" /> Menyusui
        </span>
        <span className="flex items-center gap-1.5 text-xs text-ink-muted">
          <span className="w-2 h-2 rounded-full bg-sleep" /> Tidur
        </span>
        <span className="flex items-center gap-1.5 text-xs text-ink-muted">
          <span className="w-2 h-2 rounded-full bg-diaper" /> Popok
        </span>
      </div>

      {/* status pills */}
      {summary?.guideline_label ? (
        <div className="px-6 flex gap-3 overflow-x-auto pb-1">
          <StatusPill
            icon="🍼"
            title="Menyusui"
            actual={summary.feeding.actual}
            unit="x"
            range={
              summary.feeding.min != null ? `${summary.feeding.min}-${summary.feeding.max}x/hari (IDAI)` : null
            }
            status={summary.feeding.status}
          />
          <StatusPill
            icon="🌙"
            title="Tidur"
            actual={summary.sleep.actual_hours}
            unit="jam"
            range={summary.sleep.min != null ? `${summary.sleep.min}-${summary.sleep.max} jam/hari` : null}
            status={summary.sleep.status}
          />
          <StatusPill
            icon="💧"
            title="BAK (pipis)"
            actual={summary.wet_diaper.actual}
            unit="x"
            range={summary.wet_diaper.min != null ? `min ${summary.wet_diaper.min}x/hari` : null}
            status={summary.wet_diaper.status}
          />
        </div>
      ) : (
        summary?.message && <p className="px-6 text-sm text-ink-faint text-center">{summary.message}</p>
      )}

      {/* riwayat */}
      <div className="px-6 mt-8">
        <h2 className="font-mono text-xs text-ink-faint tracking-[0.2em] uppercase mb-3">Riwayat</h2>
        {loading ? (
          <p className="text-ink-faint text-sm">Memuat...</p>
        ) : (
          <>
            {loadError && (
              <div className="mb-3 flex items-center justify-between gap-3 bg-warn/10 text-warn text-xs rounded-xl2 px-3 py-2.5">
                <span>📡 Nggak bisa memuat data terbaru dari server — kamu sedang offline.</span>
                <button
                  type="button"
                  onClick={() => loadAll()}
                  disabled={loading}
                  className="font-semibold underline underline-offset-2 flex-shrink-0 disabled:opacity-50"
                >
                  Coba lagi
                </button>
              </div>
            )}
            {historyItems.length === 0 ? (
              <p className="text-ink-faint text-sm">Belum ada catatan {isToday ? "hari ini" : "di tanggal ini"}.</p>
            ) : (
          <div className="space-y-4">
            {groupedHistory.map((group, groupIdx) => (
              <div key={groupIdx}>
                <p className="text-[11px] text-ink-faint font-medium mb-2 pl-1">{group.period}</p>
                <div className="space-y-2">
                  {group.items.map((item) => {
                    const pending = isPendingOfflineItem(item);
                    const itemClickable = !pending && canWrite;
                    // Editor CUMA boleh hapus catatan buatan sendiri;
                    // owner boleh hapus catatan siapa pun; viewer nggak
                    // pernah boleh hapus — backend juga menegakkan ulang
                    // ini (utils/access.py:can_delete_record), ini CUMA
                    // buat nyembunyiin tombolnya di UI.
                    const itemCanDelete = canWrite && canDeleteRecord(child.role, item.created_by_user_id, currentUserId);
                    const card = (
                      <div
                        onClick={itemClickable ? () => openEdit(item) : undefined}
                        aria-disabled={!itemClickable || undefined}
                        className={`flex items-center justify-between bg-void-card border border-void-hairline rounded-xl2 px-4 py-3 ${
                          itemClickable ? "cursor-pointer active:bg-void-raised" : ""
                        }`}
                      >
                        <div className="flex items-center gap-3">
                          <span className={`w-2 h-2 rounded-full ${dotColor(item.kind)}`} />
                          <div>
                            <p className="text-sm text-ink">
                              {item.kind === "feeding" && FEED_TYPE_LABEL[item.feed_type]}
                              {item.kind === "sleep" && `Tidur ${item.sleep_type}`}
                              {item.kind === "diaper" &&
                                (item.diaper_type === "pipis" ? "Pipis" : item.diaper_type === "pup" ? "Pup" : "Pipis + Pup")}
                              {item.kind === "pumping" && "Perah ASI"}
                              {item.kind === "stroll" && "Jalan-jalan"}
                              {item.kind === "bathing" && "Mandi"}
                              {item.kind === "vitamin" && (item.medication_name || "Vitamin D")}
                            </p>
                            <p className="text-xs text-ink-faint font-mono">
                              {item.kind === "sleep" ? sleepTimeRangeLabel(item, date) : timeOf(item.at)}
                              {item.kind === "feeding" && item.duration_minutes && ` · ${item.duration_minutes} mnt`}
                              {item.kind === "feeding" && item.volume_ml && ` · ${item.volume_ml} ml`}
                              {item.kind === "pumping" && ` · ${item.duration_minutes} mnt · ${item.volume_ml} ml`}
                              {(item.kind === "stroll" || item.kind === "bathing") &&
                                item.duration_minutes &&
                                ` · ${item.duration_minutes} mnt`}
                              {(item.kind === "stroll" || item.kind === "bathing") && item.notes && ` · ${item.notes}`}
                            </p>
                            {item._offlineQueued && (
                              <>
                                <p className="text-[11px] text-warn mt-0.5">⏳ nunggu sinkron</p>
                                <p className="text-[11px] text-ink-faint mt-0.5">
                                  Catatan ini dapat diubah setelah selesai disinkronkan.
                                </p>
                              </>
                            )}
                            {item.created_by_name && (
                              <p className="text-[11px] text-ink-faint mt-0.5">oleh {item.created_by_name}</p>
                            )}
                          </div>
                        </div>
                        {!pending && canWrite && (
                          <div className="flex items-center gap-2">
                            {item.kind === "sleep" && !item.end_time && (
                              <button
                                onClick={(e) => {
                                  e.stopPropagation();
                                  handleWakeUp(item);
                                }}
                                className="text-xs px-3 py-1.5 rounded-full bg-sleep text-white font-medium"
                              >
                                🌤️ Bangun
                              </button>
                            )}
                            {itemCanDelete && (
                              <button
                                onClick={(e) => {
                                  e.stopPropagation();
                                  handleSoftDelete(item);
                                }}
                                className="text-ink-faint text-xs px-2 py-1"
                                aria-label="Hapus catatan"
                              >
                                Hapus
                              </button>
                            )}
                          </div>
                        )}
                      </div>
                    );

                    // catatan yang masih nunggu sinkron TIDAK dibungkus
                    // SwipeableHistoryItem — nggak ada aksi swipe (duplikat/
                    // hapus) yang valid buat ditawarin sebelum record-nya
                    // beneran ada di server. Viewer (atau role yang nggak
                    // dikenal) juga nggak dibungkus sama sekali — nggak
                    // ada aksi geser yang boleh ditawarin (duplikat =
                    // bikin record baru, tetap butuh izin tulis).
                    if (pending || !canWrite) {
                      return <div key={`${item.kind}-${item.id}`}>{card}</div>;
                    }
                    return (
                      <SwipeableHistoryItem
                        key={`${item.kind}-${item.id}`}
                        onDuplicate={() => handleDuplicate(item)}
                        onDelete={() => handleSoftDelete(item)}
                        canDelete={itemCanDelete}
                      >
                        {card}
                      </SwipeableHistoryItem>
                    );
                  })}
                </div>
              </div>
            ))}
          </div>
            )}
          </>
        )}
      </div>

      {pendingDelete && (
        <div className="fixed bottom-24 left-1/2 -translate-x-1/2 z-40 bg-ink text-void px-4 py-2.5 rounded-full shadow-soft flex items-center gap-3 text-sm">
          <span>Catatan dihapus</span>
          <button onClick={handleUndoDelete} className="font-semibold text-feed">
            Batalkan
          </button>
        </div>
      )}

      {offlineSavedNotice && (
        <div className="fixed bottom-36 left-1/2 -translate-x-1/2 z-40 bg-ink text-void px-4 py-2.5 rounded-full shadow-soft text-sm text-center max-w-[90vw]">
          Catatan disimpan di perangkat dan akan disinkronkan saat online.
        </div>
      )}

      <div className="px-6">
        <RelatedArticles category="feeding" ageMonths={summary ? summary.age_days / 30.4375 : null} />
      </div>

      {/* menu "lainnya" */}
      {canWrite && showMoreMenu && (
        <div className="fixed inset-0 z-50 flex items-end sm:items-center sm:justify-center">
          <div className="absolute inset-0 bg-black/60" onClick={() => setShowMoreMenu(false)} />
          <div className="relative w-full sm:max-w-sm bg-void-card border-t sm:border border-void-hairline rounded-t-xl2 sm:rounded-xl2 p-6 pb-8">
            <div className="w-10 h-1 bg-void-hairline rounded-full mx-auto mb-5 sm:hidden" />
            <h2 className="font-display text-2xl text-ink mb-5">Aktivitas Lainnya</h2>
            <div className="grid grid-cols-3 gap-3">
              {OTHER_ACTIVITIES.map((a) => (
                <button
                  key={a.type}
                  onClick={() => {
                    setShowMoreMenu(false);
                    setEditingItem(null);
                    setSheetType(a.type);
                  }}
                  className="flex flex-col items-center gap-2 bg-void border border-void-hairline rounded-xl2 py-4 text-xs text-ink-muted"
                >
                  <span className="text-2xl">{a.icon}</span>
                  {a.label}
                </button>
              ))}
            </div>
            <button
              onClick={() => setShowMoreMenu(false)}
              className="w-full py-3 mt-6 rounded-lg border border-void-hairline text-ink-muted text-sm"
            >
              Batal
            </button>
          </div>
        </div>
      )}

      {sheetType && (
        <QuickLogSheet
          type={sheetType}
          editingLog={editingItem}
          lastFeedingLog={
            feedingLogs.length > 0
              ? [...feedingLogs].sort((a, b) => new Date(b.timestamp) - new Date(a.timestamp))[0]
              : null
          }
          onClose={closeSheet}
          onSubmit={handleSheetSubmit}
          onDelete={
            editingItem && canDeleteRecord(child.role, editingItem.created_by_user_id, currentUserId)
              ? () => handleDelete(editingItem.kind, editingItem.id)
              : undefined
          }
        />
      )}

      {showCaregiverHandover && (
        <CaregiverHandoverScreen
          child={child}
          currentUserId={currentUserId}
          onClose={() => setShowCaregiverHandover(false)}
        />
      )}
    </div>
  );
}
