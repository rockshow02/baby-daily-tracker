import { useCallback, useEffect, useMemo, useState } from "react";
import { api, ApiError } from "../api/client";
import { cacheReminderSnapshot, getCachedReminderSnapshot } from "../utils/reminderCache";
import {
  describeOccurrenceState, describeReminderType, describeRecurrence,
  formatOccurrenceDateTime, reminderTypeIcon, REMINDER_TYPES, RECORD_NOW_LOG_TYPES,
} from "../utils/reminders";
import {
  getNotificationPermission, isNotificationOptedIn, requestNotificationPermission,
  setNotificationOptedIn,
} from "../utils/reminderNotifications";
import { QUEUE_CHANGE_EVENT } from "../utils/offlineQueue";
import { canWrite } from "../utils/roles";

const MAX_TITLE_LENGTH = 150;

function useOnlineStatus() {
  const [isOnline, setIsOnline] = useState(navigator.onLine);
  useEffect(() => {
    const goOnline = () => setIsOnline(true);
    const goOffline = () => setIsOnline(false);
    window.addEventListener("online", goOnline);
    window.addEventListener("offline", goOffline);
    return () => {
      window.removeEventListener("online", goOnline);
      window.removeEventListener("offline", goOffline);
    };
  }, []);
  return isOnline;
}

function occurrenceIdentity(reminderId, occurrenceKey) {
  return `${reminderId}:${occurrenceKey}`;
}

function toDatetimeLocalValue(iso) {
  if (!iso) return "";
  try {
    const d = new Date(iso);
    const pad = (n) => String(n).padStart(2, "0");
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
  } catch (_) {
    return "";
  }
}

/** Form buat bikin/ubah 1 reminder — dipakai bareng create & edit (mirip pola modal lain di app ini). */
function ReminderFormModal({ initial, onClose, onSubmit, submitting, errorMessage }) {
  const [reminderType, setReminderType] = useState(initial?.reminder_type || "medication");
  const [title, setTitle] = useState(initial?.title || "");
  const [scheduledAt, setScheduledAt] = useState(
    initial?.scheduled_at ? toDatetimeLocalValue(initial.scheduled_at) : "",
  );
  const [recurrence, setRecurrence] = useState(initial?.recurrence || "none");

  const isEdit = Boolean(initial?.id);

  const handleSubmit = (e) => {
    e.preventDefault();
    onSubmit({
      reminder_type: reminderType,
      title: title.trim(),
      scheduled_at: scheduledAt ? new Date(scheduledAt).toISOString() : "",
      recurrence,
    });
  };

  return (
    <div className="fixed inset-0 z-50 flex items-end sm:items-center sm:justify-center">
      <div className="absolute inset-0 bg-black/50" onClick={onClose} />
      <form
        onSubmit={handleSubmit}
        role="dialog"
        aria-modal="true"
        aria-labelledby="reminder-form-title"
        className="relative w-full sm:max-w-md bg-void-card border-t sm:border border-void-hairline rounded-t-xl2 sm:rounded-xl2 p-6 pb-8 max-h-[85vh] overflow-y-auto"
      >
        <h2 id="reminder-form-title" className="font-display text-2xl text-ink mb-4">
          {isEdit ? "Ubah Pengingat" : "Pengingat Baru"}
        </h2>

        <label className="block text-xs text-ink-faint uppercase tracking-wider mb-1.5" htmlFor="reminder-type">
          Jenis
        </label>
        <select
          id="reminder-type"
          value={reminderType}
          onChange={(e) => setReminderType(e.target.value)}
          className="w-full bg-void border border-void-hairline rounded-lg px-3 py-2.5 text-sm text-ink mb-4"
        >
          {REMINDER_TYPES.map((t) => (
            <option key={t} value={t}>{describeReminderType(t)}</option>
          ))}
        </select>

        <label className="block text-xs text-ink-faint uppercase tracking-wider mb-1.5" htmlFor="reminder-title">
          Judul
        </label>
        <input
          id="reminder-title"
          type="text"
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          maxLength={MAX_TITLE_LENGTH}
          placeholder="cth. Obat pagi"
          className="w-full bg-void border border-void-hairline rounded-lg px-3 py-2.5 text-sm text-ink mb-4"
          required
        />

        <label className="block text-xs text-ink-faint uppercase tracking-wider mb-1.5" htmlFor="reminder-scheduled-at">
          Waktu
        </label>
        <input
          id="reminder-scheduled-at"
          type="datetime-local"
          value={scheduledAt}
          onChange={(e) => setScheduledAt(e.target.value)}
          className="w-full bg-void border border-void-hairline rounded-lg px-3 py-2.5 text-sm text-ink mb-4"
          required
        />

        <label className="block text-xs text-ink-faint uppercase tracking-wider mb-1.5" htmlFor="reminder-recurrence">
          Pengulangan
        </label>
        <select
          id="reminder-recurrence"
          value={recurrence}
          onChange={(e) => setRecurrence(e.target.value)}
          className="w-full bg-void border border-void-hairline rounded-lg px-3 py-2.5 text-sm text-ink mb-4"
        >
          <option value="none">Sekali</option>
          <option value="daily">Setiap hari</option>
        </select>

        {errorMessage && <p className="text-warn text-xs mb-4">{errorMessage}</p>}

        <div className="flex gap-2">
          <button
            type="button"
            onClick={onClose}
            className="flex-1 py-3 rounded-lg border border-void-hairline text-ink-muted text-sm font-medium"
          >
            Batal
          </button>
          <button
            type="submit"
            disabled={submitting}
            className="flex-1 py-3 rounded-lg bg-feed text-white text-sm font-semibold disabled:opacity-50"
          >
            {submitting ? "Menyimpan..." : "Simpan"}
          </button>
        </div>
      </form>
    </div>
  );
}

function OccurrenceCard({ reminder, occurrence, onComplete, onSkip, onRecordNow, pendingSync }) {
  const isPending = pendingSync;
  const canAct = reminder.can_act && !isPending && (occurrence.status == null);
  const linkableLogType = RECORD_NOW_LOG_TYPES[reminder.reminder_type];

  return (
    <div className="bg-void border border-void-hairline rounded-xl2 px-4 py-3 mb-2">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="text-sm text-ink font-medium truncate">
            {reminderTypeIcon(reminder.reminder_type)} {reminder.title}
          </p>
          <p className="text-[11px] text-ink-faint">
            {formatOccurrenceDateTime(occurrence.occurrence_at)} · {describeReminderType(reminder.reminder_type)}
          </p>
        </div>
        <span
          className={`flex-shrink-0 text-[11px] font-semibold px-2 py-1 rounded-full ${
            occurrence.state === "overdue" ? "bg-warn/15 text-warn"
            : occurrence.state === "due" ? "bg-feed/15 text-feed"
            : occurrence.state === "completed" ? "bg-feed/10 text-feed"
            : occurrence.state === "skipped" ? "bg-void-hairline text-ink-faint"
            : "bg-void-hairline text-ink-muted"
          }`}
        >
          {isPending ? "Menunggu sinkron" : describeOccurrenceState(occurrence.state)}
        </span>
      </div>

      {occurrence.status && occurrence.acted_by_name && (
        <p className="text-[11px] text-ink-faint mt-1">oleh {occurrence.acted_by_name}</p>
      )}

      {canAct && (
        <div className="flex gap-2 mt-2.5">
          {linkableLogType && (
            <button
              type="button"
              onClick={() => onRecordNow(reminder)}
              className="text-xs font-medium text-feed underline underline-offset-2"
            >
              Catat sekarang
            </button>
          )}
          <div className="flex-1" />
          <button
            type="button"
            onClick={() => onSkip(reminder, occurrence)}
            className="px-3 py-1.5 rounded-lg border border-void-hairline text-ink-muted text-xs font-medium"
          >
            Lewati
          </button>
          <button
            type="button"
            onClick={() => onComplete(reminder, occurrence)}
            className="px-3 py-1.5 rounded-lg bg-feed text-white text-xs font-semibold"
          >
            Selesai
          </button>
        </div>
      )}
    </div>
  );
}

function OccurrenceSection({ title, items, ...handlers }) {
  if (items.length === 0) return null;
  return (
    <div className="mb-4">
      <p className="text-xs text-ink-faint font-mono uppercase tracking-wider mb-2">{title}</p>
      {items.map(({ reminder, occurrence }) => (
        <OccurrenceCard
          key={occurrenceIdentity(reminder.id, occurrence.occurrence_key)}
          reminder={reminder}
          occurrence={occurrence}
          pendingSync={handlers.pendingSyncKeys.has(occurrenceIdentity(reminder.id, occurrence.occurrence_key))}
          onComplete={handlers.onComplete}
          onSkip={handlers.onSkip}
          onRecordNow={handlers.onRecordNow}
        />
      ))}
    </div>
  );
}

/**
 * "🔔 Pengingat" — Care Reminders & Schedules Phase 1. Lihat
 * backend/docs/REMINDERS.md buat kontrak API & kebijakan lengkapnya.
 * Status due/overdue SELALU dari server (dihitung ulang tiap fetch) —
 * layar ini TIDAK PERNAH menghitung status sendiri dari waktu lokal
 * browser.
 */
export default function ReminderScreen({ child, currentUserId, onRecordNow }) {
  const isOnline = useOnlineStatus();
  const [status, setStatus] = useState("loading");
  const [data, setData] = useState(null);
  const [cachedAt, setCachedAt] = useState(null);
  const [errorMessage, setErrorMessage] = useState("");
  const [showForm, setShowForm] = useState(false);
  const [editingReminder, setEditingReminder] = useState(null);
  const [formError, setFormError] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [manageFilter, setManageFilter] = useState("active");
  const [pendingSyncKeys, setPendingSyncKeys] = useState(new Set());
  const [notifPermission, setNotifPermission] = useState(getNotificationPermission());
  const [notifOptedIn, setNotifOptedIn] = useState(isNotificationOptedIn(currentUserId));

  const loadFromCache = useCallback(() => {
    const cached = getCachedReminderSnapshot(currentUserId, child.id);
    if (cached) {
      setData(cached.data);
      setCachedAt(cached.cachedAt);
      setStatus("offline_cached");
    } else {
      setData(null);
      setCachedAt(null);
      setStatus("offline_no_cache");
    }
  }, [currentUserId, child.id]);

  const load = useCallback(async () => {
    if (!isOnline) {
      loadFromCache();
      return;
    }
    setStatus((prev) => (prev === "ready" || prev === "offline_cached" ? prev : "loading"));
    setErrorMessage("");
    try {
      const res = await api.listReminders(child.id);
      setData(res);
      setCachedAt(null);
      setStatus("ready");
      cacheReminderSnapshot(currentUserId, child.id, res);
    } catch (err) {
      if (err instanceof ApiError && err.kind === "network") {
        loadFromCache();
        return;
      }
      setStatus("error");
      setErrorMessage(err?.message || "Gagal memuat pengingat.");
    }
  }, [child.id, isOnline, currentUserId, loadFromCache]);

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [child.id, isOnline]);

  // Antrian offline berubah (item baru masuk ATAU berhasil disinkron) —
  // muat ulang biar status occurrence yang barusan disinkron ke-refresh,
  // dan bersihin penanda "menunggu sinkron" buat yang udah kelar.
  useEffect(() => {
    const onQueueChange = () => {
      setPendingSyncKeys((prev) => (prev.size > 0 ? new Set() : prev));
      load();
    };
    window.addEventListener(QUEUE_CHANGE_EVENT, onQueueChange);
    return () => window.removeEventListener(QUEUE_CHANGE_EVENT, onQueueChange);
  }, [load]);

  const handleAct = async (reminder, occurrence, action) => {
    const key = occurrenceIdentity(reminder.id, occurrence.occurrence_key);
    try {
      const call = action === "complete" ? api.completeReminderOccurrence : api.skipReminderOccurrence;
      const result = await call(child.id, reminder.id, occurrence.occurrence_key);
      if (result && result._offlineQueued) {
        setPendingSyncKeys((prev) => new Set(prev).add(key));
      } else {
        load();
      }
    } catch (err) {
      setErrorMessage(err?.message || "Aksi gagal, coba lagi.");
    }
  };

  const handleCreateOrUpdate = async (payload) => {
    setSubmitting(true);
    setFormError("");
    try {
      if (editingReminder) {
        await api.updateReminder(child.id, editingReminder.id, payload);
      } else {
        await api.createReminder(child.id, payload);
      }
      setShowForm(false);
      setEditingReminder(null);
      load();
    } catch (err) {
      setFormError(err?.message || "Gagal menyimpan pengingat.");
    } finally {
      setSubmitting(false);
    }
  };

  const handleDelete = async (reminder) => {
    if (!window.confirm(`Hapus pengingat "${reminder.title}"?`)) return;
    try {
      await api.deleteReminder(child.id, reminder.id);
      load();
    } catch (err) {
      setErrorMessage(err?.message || "Gagal menghapus pengingat.");
    }
  };

  const handleToggleActive = async (reminder) => {
    try {
      await api.updateReminder(child.id, reminder.id, { is_active: !reminder.is_active });
      load();
    } catch (err) {
      setErrorMessage(err?.message || "Gagal mengubah pengingat.");
    }
  };

  const handleEnableNotifications = async () => {
    const result = await requestNotificationPermission();
    setNotifPermission(result);
    if (result === "granted") {
      setNotificationOptedIn(currentUserId, true);
      setNotifOptedIn(true);
    }
  };

  const grouped = useMemo(() => {
    const buckets = { overdue: [], due: [], upcoming: [], resolved: [] };
    for (const reminder of data?.reminders || []) {
      for (const occurrence of reminder.occurrences || []) {
        const entry = { reminder, occurrence };
        if (occurrence.state === "overdue") buckets.overdue.push(entry);
        else if (occurrence.state === "due") buckets.due.push(entry);
        else if (occurrence.state === "upcoming") buckets.upcoming.push(entry);
        else buckets.resolved.push(entry);
      }
    }
    buckets.overdue.sort((a, b) => a.occurrence.occurrence_at.localeCompare(b.occurrence.occurrence_at));
    buckets.due.sort((a, b) => a.occurrence.occurrence_at.localeCompare(b.occurrence.occurrence_at));
    buckets.upcoming.sort((a, b) => a.occurrence.occurrence_at.localeCompare(b.occurrence.occurrence_at));
    buckets.resolved.sort((a, b) => (b.occurrence.acted_at || "").localeCompare(a.occurrence.acted_at || ""));
    return buckets;
  }, [data]);

  const manageableReminders = (data?.reminders || []).filter((r) => manageFilter === "all" || r.is_active);
  // Tombol BUAT nggak bisa disimpulkan dari `can_edit`/`can_act` PER
  // reminder (bisa aja nol reminder sama sekali buat anak ini, ATAU
  // semuanya kebetulan bukan buatan editor ini) — `child.role` (dikirim
  // GET /children yang sama, dipakai juga di App.jsx buat kontrol lain)
  // adalah sinyal peran yang BENERAN dapat diandalkan di sini. Backend
  // TETAP yang menegakkan izin beneran pas request POST-nya dikirim.
  const canCreate = canWrite(child.role);

  return (
    <div className="min-h-screen pb-16 px-6 pt-8">
      <div className="flex items-center justify-between mb-1">
        <h1 className="font-display text-3xl text-ink">🔔 Pengingat</h1>
      </div>
      <p className="text-sm text-ink-muted mb-4">Jadwal perawatan {child.nickname || child.name}</p>

      <div className="bg-void border border-void-hairline rounded-xl2 px-4 py-3 mb-4">
        <p className="text-xs text-ink-muted mb-2">
          Notifikasi cuma muncul selagi aplikasi ini terbuka di perangkat ini — tidak ada jaminan
          pengingat kalau aplikasi ditutup (keterbatasan hosting gratis & browser).
        </p>
        {notifPermission === "unsupported" && (
          <p className="text-[11px] text-ink-faint">Browser ini tidak mendukung notifikasi.</p>
        )}
        {notifPermission === "denied" && (
          <p className="text-[11px] text-warn">
            Izin notifikasi ditolak. Aktifkan lewat pengaturan browser kalau ingin menyalakannya.
          </p>
        )}
        {notifPermission === "default" && (
          <button
            type="button"
            onClick={handleEnableNotifications}
            className="text-xs font-semibold text-feed underline underline-offset-2"
          >
            Aktifkan notifikasi saat aplikasi terbuka
          </button>
        )}
        {notifPermission === "granted" && notifOptedIn && (
          <p className="text-[11px] text-feed">Notifikasi aktif selagi aplikasi terbuka.</p>
        )}
      </div>

      {status === "offline_cached" && (
        <p className="text-[11px] text-warn bg-warn/10 border border-warn/30 rounded-lg px-3 py-2 mb-4">
          Menampilkan pengingat terakhir saat offline — dibuat {formatOccurrenceDateTime(cachedAt)}.
        </p>
      )}

      {status === "loading" && (
        <div className="space-y-3" aria-live="polite" aria-busy="true">
          <p className="text-ink-faint text-sm text-center py-2">Memuat pengingat...</p>
          {[0, 1].map((i) => (
            <div key={i} className="h-16 bg-void-card border border-void-hairline rounded-xl2 animate-pulse" />
          ))}
        </div>
      )}

      {status === "error" && (
        <div className="text-center py-6 space-y-3">
          <p className="text-warn text-sm">{errorMessage}</p>
          <button onClick={load} className="px-4 py-2 rounded-lg border border-void-hairline text-ink-muted text-sm font-medium">
            Coba lagi
          </button>
        </div>
      )}

      {status === "offline_no_cache" && (
        <div className="text-center py-10 px-4">
          <p className="text-3xl mb-3">📡</p>
          <p className="text-ink text-sm font-medium mb-1">Belum ada pengingat tersimpan</p>
          <p className="text-ink-faint text-xs">Sambungkan ke internet dulu untuk memuat pengingat.</p>
        </div>
      )}

      {(status === "ready" || status === "offline_cached") && data && (
        <>
          {errorMessage && <p className="text-warn text-xs mb-3">{errorMessage}</p>}

          {isOnline && canCreate && (
            <button
              type="button"
              onClick={() => { setEditingReminder(null); setFormError(""); setShowForm(true); }}
              className="w-full py-3 mb-4 rounded-xl2 bg-feed text-white text-sm font-semibold"
            >
              + Pengingat Baru
            </button>
          )}
          {!isOnline && (
            <p className="text-[11px] text-ink-faint mb-4">
              Membuat/mengubah/menghapus pengingat butuh koneksi internet. Menyelesaikan atau
              melewati pengingat yang ada tetap bisa dilakukan offline.
            </p>
          )}

          {grouped.overdue.length === 0 && grouped.due.length === 0 && grouped.upcoming.length === 0
            && grouped.resolved.length === 0 && (data.reminders || []).length === 0 && (
            <p className="text-ink-faint text-sm text-center py-10">
              Belum ada pengingat. Buat pengingat pertama untuk mulai memantau jadwal perawatan.
            </p>
          )}

          <OccurrenceSection
            title="Terlambat"
            items={grouped.overdue}
            onComplete={(r, o) => handleAct(r, o, "complete")}
            onSkip={(r, o) => handleAct(r, o, "skip")}
            onRecordNow={onRecordNow}
            pendingSyncKeys={pendingSyncKeys}
          />
          <OccurrenceSection
            title="Jatuh Tempo"
            items={grouped.due}
            onComplete={(r, o) => handleAct(r, o, "complete")}
            onSkip={(r, o) => handleAct(r, o, "skip")}
            onRecordNow={onRecordNow}
            pendingSyncKeys={pendingSyncKeys}
          />
          <OccurrenceSection
            title="Akan Datang"
            items={grouped.upcoming}
            onComplete={(r, o) => handleAct(r, o, "complete")}
            onSkip={(r, o) => handleAct(r, o, "skip")}
            onRecordNow={onRecordNow}
            pendingSyncKeys={pendingSyncKeys}
          />
          <OccurrenceSection
            title="Riwayat Terkini"
            items={grouped.resolved.slice(0, 10)}
            onComplete={(r, o) => handleAct(r, o, "complete")}
            onSkip={(r, o) => handleAct(r, o, "skip")}
            onRecordNow={onRecordNow}
            pendingSyncKeys={pendingSyncKeys}
          />

          {(data.reminders || []).length > 0 && (
            <div className="mt-6">
              <div className="flex items-center justify-between mb-2">
                <p className="text-xs text-ink-faint font-mono uppercase tracking-wider">Kelola Pengingat</p>
                <div className="flex gap-1">
                  {["active", "all"].map((f) => (
                    <button
                      key={f}
                      type="button"
                      onClick={() => setManageFilter(f)}
                      className={`px-2.5 py-1 rounded-full text-[11px] font-medium border ${
                        manageFilter === f ? "bg-feed/15 border-feed text-feed" : "border-void-hairline text-ink-muted"
                      }`}
                    >
                      {f === "active" ? "Aktif" : "Semua"}
                    </button>
                  ))}
                </div>
              </div>
              {manageableReminders.map((r) => (
                <div key={r.id} className="bg-void-card border border-void-hairline rounded-xl2 px-4 py-3 mb-2 flex items-center justify-between gap-2">
                  <div className="min-w-0">
                    <p className="text-sm text-ink truncate">{reminderTypeIcon(r.reminder_type)} {r.title}</p>
                    <p className="text-[11px] text-ink-faint">
                      {describeReminderType(r.reminder_type)} · {describeRecurrence(r.recurrence)}
                      {!r.is_active && " · Nonaktif"}
                    </p>
                  </div>
                  {(r.can_edit || r.can_delete) && isOnline && (
                    <div className="flex gap-1.5 flex-shrink-0">
                      {r.can_edit && (
                        <button
                          type="button"
                          onClick={() => handleToggleActive(r)}
                          className="px-2.5 py-1.5 rounded-lg border border-void-hairline text-ink-muted text-[11px] font-medium"
                        >
                          {r.is_active ? "Nonaktifkan" : "Aktifkan"}
                        </button>
                      )}
                      {r.can_edit && (
                        <button
                          type="button"
                          onClick={() => { setEditingReminder(r); setFormError(""); setShowForm(true); }}
                          className="px-2.5 py-1.5 rounded-lg border border-void-hairline text-ink-muted text-[11px] font-medium"
                        >
                          Ubah
                        </button>
                      )}
                      {r.can_delete && (
                        <button
                          type="button"
                          onClick={() => handleDelete(r)}
                          className="px-2.5 py-1.5 rounded-lg border border-void-hairline text-warn text-[11px] font-medium"
                        >
                          Hapus
                        </button>
                      )}
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
        </>
      )}

      {showForm && (
        <ReminderFormModal
          initial={editingReminder}
          onClose={() => { setShowForm(false); setEditingReminder(null); }}
          onSubmit={handleCreateOrUpdate}
          submitting={submitting}
          errorMessage={formError}
        />
      )}
    </div>
  );
}
