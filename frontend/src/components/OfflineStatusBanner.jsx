import { useState } from "react";
import { useAuth } from "../context/AuthContext";
import QueueReviewPanel from "./QueueReviewPanel";

const STATUS_STYLE = {
  offline: "bg-warn/15 text-warn",
  waiting: "bg-feed/15 text-feed",
  syncing: "bg-feed/15 text-feed",
  auth_required: "bg-warn/15 text-warn",
  retry_scheduled: "bg-warn/15 text-warn",
  needs_review: "bg-warn/15 text-warn",
  synced: "bg-feed/15 text-feed",
};

/**
 * `sync`: hasil SATU-SATUNYA panggilan useOfflineSync() yang dipasang di
 * App.jsx (AuthenticatedAppShell) — komponen ini SENGAJA nggak manggil
 * hook-nya sendiri lagi, biar nggak ada 2 loop auto-sync yang balapan.
 * `onOpenDetail`: buka Sync Center yang sama yang bisa dibuka lewat menu
 * "🔄 Status Sinkronisasi" — state showSyncCenter juga dipegang di level
 * yang sama (App.jsx), bukan duplikat di sini.
 */
export default function OfflineStatusBanner({ sync, onOpenDetail }) {
  const {
    status,
    pendingCount,
    needsReviewCount,
    needsReviewItems,
    legacyItems,
    syncNow,
    discardItem,
    claimLegacyItem,
    retryWithEdits,
  } = sync;
  const { logout } = useAuth();
  const [showReview, setShowReview] = useState(false);

  // "Masuk lagi" nge-clear sesi yang udah nggak valid LEWAT AuthContext
  // (bukan ngoprek token/currentUser langsung dari sini) — logout() udah
  // nge-clear token + currentUser + set user jadi null, yang otomatis
  // bikin App.jsx nampilin AuthScreen lagi. Antrian offline TETAP utuh —
  // logout cuma ngapus sesi login, bukan data yang lagi nunggu disync.
  // Nggak pakai konfirmasi "masih ada N catatan" di sini kayak menu logout
  // manual — sesinya emang udah nggak valid, nggak ada gunanya nunggu.
  const handleReauthenticate = () => {
    logout();
  };

  const reviewCount = needsReviewCount + legacyItems.length;

  if (status === "idle") return null;

  const message = {
    offline: `📡 Nggak ada koneksi — catatan tetap tersimpan${pendingCount > 0 ? `, ${pendingCount} nunggu sinkron` : ""}`,
    waiting: `⏳ ${pendingCount} catatan nunggu disinkron`,
    syncing: `🔄 Menyinkronkan ${pendingCount} catatan...`,
    auth_required: "🔒 Sesi login berakhir — masuk lagi buat sinkronkan catatan yang belum terkirim",
    retry_scheduled: `🔁 Gagal sinkron sementara, dicoba lagi otomatis${pendingCount > 0 ? ` (${pendingCount} catatan)` : ""}`,
    needs_review: `⚠️ ${reviewCount} catatan perlu ditinjau`,
    synced: "✅ Semua catatan tersinkron",
  }[status];

  return (
    <div className={`text-xs font-medium ${STATUS_STYLE[status] || "bg-feed/15 text-feed"}`}>
      <div className="px-4 py-2 flex items-center justify-center gap-2 text-center">
        <span>{message}</span>
        {status === "auth_required" && (
          <button onClick={handleReauthenticate} className="underline underline-offset-2">
            Masuk lagi
          </button>
        )}
        {status === "retry_scheduled" && (
          <button onClick={syncNow} className="underline underline-offset-2">
            Coba sekarang
          </button>
        )}
        {reviewCount > 0 && status !== "needs_review" && (
          <button onClick={() => setShowReview((v) => !v)} className="underline underline-offset-2">
            {reviewCount} perlu ditinjau
          </button>
        )}
        {status === "needs_review" && (
          <button onClick={() => setShowReview((v) => !v)} className="underline underline-offset-2">
            {showReview ? "Tutup" : "Lihat"}
          </button>
        )}
        {onOpenDetail && (
          <button onClick={onOpenDetail} className="underline underline-offset-2">
            Detail
          </button>
        )}
      </div>

      {showReview && (
        <QueueReviewPanel
          needsReviewItems={needsReviewItems}
          legacyItems={legacyItems}
          discardItem={discardItem}
          claimLegacyItem={claimLegacyItem}
          retryWithEdits={retryWithEdits}
        />
      )}
    </div>
  );
}
