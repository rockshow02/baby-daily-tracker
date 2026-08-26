import { useCallback, useEffect, useState } from "react";
import { api, ApiError } from "../api/client";
import {
  describeAuditEvent,
  ACTION_FILTER_OPTIONS,
  ENTITY_TYPE_FILTER_OPTIONS,
} from "../utils/auditTrail";

const PAGE_LIMIT = 25;

function formatTimestamp(iso) {
  if (!iso) return "";
  try {
    return new Date(iso).toLocaleString("id-ID");
  } catch (_) {
    return "";
  }
}

// State koneksi LOKAL buat layar ini doang (bukan sinkronisasi antrian
// offline) — SENGAJA nggak manggil useOfflineSync() sendiri di sini
// (itu instance tunggal yang cuma boleh dipasang di AuthenticatedAppShell,
// lihat App.jsx). Aktivitas Pengasuh murni baca-server, online-only di
// Phase 1, jadi cukup dengar event online/offline browser secara lokal.
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

function AuditEventRow({ event }) {
  const sentence = describeAuditEvent(event);
  const recordedAt = formatTimestamp(event.recorded_at);
  const auditedAt = formatTimestamp(event.created_at);
  return (
    <div className="bg-void border border-void-hairline rounded-xl2 px-4 py-3 space-y-1">
      <p className="text-sm text-ink">{sentence}</p>
      <div className="flex flex-wrap items-center gap-x-3 gap-y-0.5 text-[11px] text-ink-faint">
        <span>Dicatat sistem: {auditedAt}</span>
        {recordedAt && <span>Waktu catatan: {recordedAt}</span>}
      </div>
    </div>
  );
}

/**
 * "🕘 Aktivitas Pengasuh" — riwayat BACA-SAJA siapa menambah/mengubah/
 * menghapus catatan anak (Caregiver Audit Trail Phase 1). Online-only,
 * TIDAK di-cache di localStorage/IndexedDB, TIDAK masuk antrian sinkron
 * offline — kalau server nggak kesentuh, layar ini cuma nunjukin pesan
 * error yang bisa dicoba ulang, TIDAK PERNAH memicu logout otomatis
 * (lihat penanganan ApiError kind "network" vs lainnya di bawah).
 */
export default function AuditTrailScreen({ child, currentUserId, onClose }) {
  const isOnline = useOnlineStatus();

  const [events, setEvents] = useState([]);
  const [nextCursor, setNextCursor] = useState(null);
  const [status, setStatus] = useState("loading"); // loading | ready | error
  const [errorMessage, setErrorMessage] = useState("");
  const [loadingMore, setLoadingMore] = useState(false);

  const [actionFilter, setActionFilter] = useState("");
  const [entityTypeFilter, setEntityTypeFilter] = useState("");
  const [actorFilter, setActorFilter] = useState("");
  const [caregivers, setCaregivers] = useState([]);

  useEffect(() => {
    // Filter aktor pakai daftar pengasuh SAAT INI (endpoint yang udah
    // ada, /children/:id/caregivers) biar pengasuh yang jarang aktif
    // tetap muncul sebagai pilihan — bukan cuma nama yang kebetulan
    // udah kemuat di halaman event pertama.
    api
      .listCaregivers(child.id)
      .then(setCaregivers)
      .catch(() => {});
  }, [child.id]);

  const loadPage = useCallback(
    async (cursor, { replace }) => {
      if (replace) {
        setStatus("loading");
      } else {
        setLoadingMore(true);
      }
      setErrorMessage("");
      try {
        const params = { limit: PAGE_LIMIT };
        if (cursor) params.cursor = cursor;
        if (actionFilter) params.action = actionFilter;
        if (entityTypeFilter) params.entity_type = entityTypeFilter;
        if (actorFilter) params.actor_user_id = actorFilter;
        const data = await api.listAuditEvents(child.id, params);
        setEvents((prev) => (replace ? data.events : [...prev, ...data.events]));
        setNextCursor(data.next_cursor || null);
        setStatus("ready");
      } catch (err) {
        setStatus("error");
        // Error jaringan (server nggak kesentuh) dibedain SECARA JELAS
        // dari error server BENERAN (401/403/dst) — dua-duanya CUMA
        // nampilin pesan + tombol "Coba lagi" di sini, TIDAK PERNAH
        // memicu logout otomatis dari layar baca-saja ini.
        if (err instanceof ApiError && err.kind === "network") {
          setErrorMessage("Nggak bisa terhubung ke server. Periksa koneksi internet kamu.");
        } else {
          setErrorMessage(err.message || "Gagal memuat aktivitas pengasuh.");
        }
      } finally {
        setLoadingMore(false);
      }
    },
    [child.id, actionFilter, entityTypeFilter, actorFilter],
  );

  useEffect(() => {
    if (!isOnline) {
      setStatus("offline");
      return;
    }
    loadPage(null, { replace: true });
  }, [loadPage, isOnline]);

  const handleRetry = () => loadPage(null, { replace: true });
  const handleLoadMore = () => loadPage(nextCursor, { replace: false });

  return (
    <div className="fixed inset-0 z-50 flex items-end sm:items-center sm:justify-center">
      <div className="absolute inset-0 bg-black/50" onClick={onClose} />
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="audit-trail-title"
        className="relative w-full sm:max-w-md bg-void-card border-t sm:border border-void-hairline rounded-t-xl2 sm:rounded-xl2 p-6 pb-8 max-h-[85vh] overflow-y-auto"
      >
        <div className="w-10 h-1 bg-void-hairline rounded-full mx-auto mb-5 sm:hidden" />
        <div className="flex items-start justify-between gap-3 mb-1">
          <h2 id="audit-trail-title" className="font-display text-2xl text-ink">
            Aktivitas Pengasuh
          </h2>
          <button
            type="button"
            onClick={onClose}
            aria-label="Tutup"
            className="flex-shrink-0 w-8 h-8 flex items-center justify-center rounded-full border border-void-hairline text-ink-muted"
          >
            ✕
          </button>
        </div>
        <p className="text-sm text-ink-muted mb-4">
          Riwayat siapa menambah, mengubah, atau menghapus catatan {child.nickname || child.name}.
        </p>

        {!isOnline && (
          <p className="text-[11px] text-warn bg-warn/10 border border-warn/30 rounded-lg px-3 py-2 mb-4">
            Riwayat aktivitas pengasuh cuma bisa dilihat pas online. Sambungkan ke internet dulu,
            ya.
          </p>
        )}

        {isOnline && (
          <div className="grid grid-cols-3 gap-1.5 mb-4">
            <select
              value={actionFilter}
              onChange={(e) => setActionFilter(e.target.value)}
              aria-label="Filter aksi"
              className="bg-void border border-void-hairline rounded-lg px-1.5 py-2 text-[11px] text-ink"
            >
              {ACTION_FILTER_OPTIONS.map((opt) => (
                <option key={opt.value} value={opt.value}>
                  {opt.label}
                </option>
              ))}
            </select>
            <select
              value={entityTypeFilter}
              onChange={(e) => setEntityTypeFilter(e.target.value)}
              aria-label="Filter jenis catatan"
              className="bg-void border border-void-hairline rounded-lg px-1.5 py-2 text-[11px] text-ink"
            >
              {ENTITY_TYPE_FILTER_OPTIONS.map((opt) => (
                <option key={opt.value} value={opt.value}>
                  {opt.label}
                </option>
              ))}
            </select>
            <select
              value={actorFilter}
              onChange={(e) => setActorFilter(e.target.value)}
              aria-label="Filter pengasuh"
              className="bg-void border border-void-hairline rounded-lg px-1.5 py-2 text-[11px] text-ink"
            >
              <option value="">Semua pengasuh</option>
              {caregivers.map((c) => (
                <option key={c.user_id} value={c.user_id}>
                  {c.user_id === currentUserId ? `${c.name} (kamu)` : c.name}
                </option>
              ))}
            </select>
          </div>
        )}

        {isOnline && status === "loading" && (
          <p className="text-ink-faint text-sm text-center py-6">Memuat aktivitas...</p>
        )}

        {isOnline && status === "error" && (
          <div className="text-center py-6 space-y-3">
            <p className="text-warn text-sm">{errorMessage}</p>
            <button
              onClick={handleRetry}
              className="px-4 py-2 rounded-lg border border-void-hairline text-ink-muted text-sm font-medium"
            >
              Coba lagi
            </button>
          </div>
        )}

        {isOnline && status === "ready" && events.length === 0 && (
          <p className="text-ink-faint text-sm text-center py-6">
            Belum ada aktivitas yang tercatat untuk filter ini.
          </p>
        )}

        {isOnline && status === "ready" && events.length > 0 && (
          <div className="space-y-2">
            {events.map((event) => (
              <AuditEventRow key={event.id} event={event} />
            ))}
          </div>
        )}

        {isOnline && status === "ready" && nextCursor && (
          <button
            onClick={handleLoadMore}
            disabled={loadingMore}
            className="w-full py-2.5 mt-3 rounded-lg border border-void-hairline text-ink-muted text-sm font-medium disabled:opacity-50"
          >
            {loadingMore ? "Memuat..." : "Muat lagi"}
          </button>
        )}

        <button
          onClick={onClose}
          className="w-full py-3 mt-5 rounded-lg border border-void-hairline text-ink-muted text-sm font-medium"
        >
          Tutup
        </button>
      </div>
    </div>
  );
}
