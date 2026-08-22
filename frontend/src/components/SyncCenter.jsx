import { useEffect, useRef, useState } from "react";
import { describeQueueItem } from "../utils/offlineQueue";
import QueueReviewPanel from "./QueueReviewPanel";

const CURRENT_STATE_LABELS = {
  idle: "Semua catatan tersinkron",
  synced: "Semua catatan tersinkron",
  waiting: "Menunggu disinkronkan",
  syncing: "Sedang menyinkronkan",
  retry_scheduled: "Percobaan ulang dijadwalkan",
  auth_required: "Perlu masuk ulang",
  needs_review: "Ada catatan perlu ditinjau",
  offline: "Offline — catatan tersimpan lokal",
};

// Ikon TEKS/EMOJI selalu didampingi LABEL kata di sebelahnya di seluruh
// komponen ini (bukan cuma warna) — requirement aksesibilitas "jangan
// cuma komunikasi lewat warna", jadi status apa pun tetap kebaca kalau
// warnanya nggak kelihatan (color blindness, mode kontras tinggi, dst).
const CURRENT_STATE_ICON = {
  idle: "✅",
  synced: "✅",
  waiting: "⏳",
  syncing: "🔄",
  retry_scheduled: "🔁",
  auth_required: "🔒",
  needs_review: "⚠️",
  offline: "📡",
};

function formatTimestamp(iso) {
  if (!iso) return "";
  try {
    return new Date(iso).toLocaleString("id-ID");
  } catch (_) {
    return "";
  }
}

/**
 * Tombol "info teknis" yang expandable — SATU-SATUNYA tempat request ID
 * server (X-Request-ID) ditampilkan, dan CUMA kalau beneran ada (nggak
 * pernah nampilin placeholder kosong buat item yang nggak punya, mis.
 * kegagalan jaringan murni yang nggak pernah nyampe ke server). Nggak
 * pernah nampilin body/respons/exception server mentah — cuma ID
 * korelasi ini doang, yang formatnya udah disaring whitelist ketat di
 * hooks/useOfflineSync.js SEBELUM disimpan.
 */
function RequestIdDetail({ requestId }) {
  const [open, setOpen] = useState(false);
  const [copied, setCopied] = useState(false);

  if (!requestId) return null;

  const handleCopy = async () => {
    try {
      await navigator.clipboard?.writeText?.(requestId);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch (_) {
      // clipboard API nggak tersedia/ditolak browser — nggak fatal,
      // ID-nya tetap kebaca manual dari teks yang udah ditampilkan
    }
  };

  return (
    <div className="mt-1">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="text-[10px] underline underline-offset-2 text-ink-faint"
      >
        {open ? "Sembunyikan info teknis" : "Info teknis"}
      </button>
      {open && (
        <div className="mt-1 flex items-center gap-2 bg-void-bg rounded px-2 py-1">
          <code className="text-[10px] text-ink-faint break-all flex-1">{requestId}</code>
          <button
            type="button"
            onClick={handleCopy}
            className="text-[10px] text-feed underline underline-offset-2 flex-shrink-0"
          >
            {copied ? "Tersalin" : "Salin"}
          </button>
        </div>
      )}
    </div>
  );
}

function PendingItemRow({ item }) {
  const { typeLabel } = describeQueueItem(item);
  return (
    <div className="bg-void-card/60 rounded-lg px-3 py-2 space-y-0.5">
      <div className="flex items-center justify-between gap-2">
        <p className="font-medium text-ink text-xs">{typeLabel}</p>
        <p className="text-ink-faint text-[11px]">{formatTimestamp(item.queuedAt)}</p>
      </div>
      <div className="flex items-center gap-3 text-[11px] text-ink-faint">
        {item.attempts > 0 && <span>{item.attempts}x dicoba</span>}
        {item.nextRetryAt && <span>Coba lagi: {formatTimestamp(item.nextRetryAt)}</span>}
      </div>
      <RequestIdDetail requestId={item.lastRequestId} />
    </div>
  );
}

/**
 * Sync Center — panel/modal pusat status sinkronisasi offline, dibuka
 * dari menu "🔄 Status Sinkronisasi" ATAU tombol "Detail" di
 * OfflineStatusBanner. `sync` HARUS berasal dari SATU instance
 * useOfflineSync() yang sama yang dipasang di App.jsx (AuthenticatedAppShell)
 * — komponen ini SENGAJA nggak manggil hook-nya sendiri.
 */
export default function SyncCenter({ sync, onClose }) {
  const panelRef = useRef(null);
  const confirmActiveRef = useRef(false);

  useEffect(() => {
    panelRef.current?.focus();
  }, []);

  useEffect(() => {
    const handleKeyDown = (e) => {
      if (e.key !== "Escape") return;
      // Jangan nutup diam-diam sambil user lagi di tengah konfirmasi
      // "Yakin? Batal/Buang" 2-langkah di QueueReviewPanel — lihat
      // components/QueueReviewPanel.jsx:onAnyConfirmingChange.
      if (confirmActiveRef.current) return;
      onClose();
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [onClose]);

  const {
    status,
    isOnline,
    syncing,
    pendingCount,
    pendingItems,
    needsReviewCount,
    needsReviewItems,
    legacyItems,
    lastSyncedAt,
    syncNow,
    discardItem,
    claimLegacyItem,
    retryWithEdits,
  } = sync;

  const stateLabel = CURRENT_STATE_LABELS[status] || "Status tidak diketahui";
  const stateIcon = CURRENT_STATE_ICON[status] || "•";
  const nothingToSync = pendingCount === 0 && needsReviewCount === 0;

  return (
    <div className="fixed inset-0 z-50 flex items-end sm:items-center sm:justify-center">
      <div className="absolute inset-0 bg-black/50" />
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="sync-center-title"
        tabIndex={-1}
        className="relative w-full sm:max-w-sm bg-void-card border-t sm:border border-void-hairline rounded-t-xl2 sm:rounded-xl2 p-6 pb-8 max-h-[85vh] overflow-y-auto outline-none"
      >
        <div className="w-10 h-1 bg-void-hairline rounded-full mx-auto mb-5 sm:hidden" />

        <div className="flex items-start justify-between gap-3 mb-5">
          <h2 id="sync-center-title" className="font-display text-2xl text-ink">
            Status Sinkronisasi
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

        <div className="space-y-4 text-sm">
          <div className="flex items-center justify-between bg-void border border-void-hairline rounded-xl2 px-4 py-3">
            <span className="text-ink-muted">Koneksi</span>
            <span className="font-medium text-ink">{isOnline ? "🟢 Online" : "🔴 Offline"}</span>
          </div>

          <div className="flex items-center justify-between bg-void border border-void-hairline rounded-xl2 px-4 py-3">
            <span className="text-ink-muted">Status saat ini</span>
            <span className="font-medium text-ink">
              {stateIcon} {stateLabel}
            </span>
          </div>

          <div className="grid grid-cols-2 gap-2">
            <div className="bg-void border border-void-hairline rounded-xl2 px-3 py-2.5 text-center">
              <p className="text-2xl font-display text-ink">{pendingCount}</p>
              <p className="text-[11px] text-ink-faint">Nunggu disinkron</p>
            </div>
            <div className="bg-void border border-void-hairline rounded-xl2 px-3 py-2.5 text-center">
              <p className="text-2xl font-display text-ink">{needsReviewCount}</p>
              <p className="text-[11px] text-ink-faint">Perlu ditinjau</p>
            </div>
          </div>

          {legacyItems.length > 0 && (
            <div className="bg-warn/10 border border-warn/30 rounded-xl2 px-4 py-2.5 flex items-center justify-between">
              <span className="text-ink-muted text-xs">Catatan lama (kepemilikan belum jelas)</span>
              <span className="font-medium text-warn">{legacyItems.length}</span>
            </div>
          )}

          <div className="flex items-center justify-between bg-void border border-void-hairline rounded-xl2 px-4 py-3">
            <span className="text-ink-muted">Terakhir tersinkron</span>
            <span className="font-medium text-ink text-right text-xs">
              {lastSyncedAt ? formatTimestamp(lastSyncedAt) : "Belum pernah tersinkron"}
            </span>
          </div>

          <div>
            <button
              type="button"
              onClick={syncNow}
              disabled={!isOnline || syncing}
              className="w-full py-3 rounded-lg bg-feed text-white text-sm font-semibold disabled:opacity-50"
            >
              {syncing ? "Menyinkronkan..." : "Sinkronkan sekarang"}
            </button>
            {nothingToSync && (
              <p className="text-[11px] text-ink-faint text-center mt-2">
                Tidak ada catatan yang perlu disinkronkan saat ini.
              </p>
            )}
          </div>

          {pendingItems.length > 0 && (
            <div>
              <p className="text-[11px] text-ink-faint uppercase tracking-wider font-mono mb-2">
                Catatan nunggu disinkron
              </p>
              <div className="space-y-2">
                {pendingItems.map((item) => (
                  <PendingItemRow key={item.id} item={item} />
                ))}
              </div>
            </div>
          )}

          {(needsReviewItems.length > 0 || legacyItems.length > 0) && (
            <div>
              <p className="text-[11px] text-ink-faint uppercase tracking-wider font-mono mb-2">
                Perlu ditinjau
              </p>
              <div className="-mx-4">
                <QueueReviewPanel
                  needsReviewItems={needsReviewItems}
                  legacyItems={legacyItems}
                  discardItem={discardItem}
                  claimLegacyItem={claimLegacyItem}
                  retryWithEdits={retryWithEdits}
                  onAnyConfirmingChange={(active) => {
                    confirmActiveRef.current = active;
                  }}
                />
              </div>
            </div>
          )}
        </div>

        <button
          onClick={onClose}
          className="w-full py-3 mt-6 rounded-lg border border-void-hairline text-ink-muted text-sm font-medium"
        >
          Tutup
        </button>
      </div>
    </div>
  );
}
