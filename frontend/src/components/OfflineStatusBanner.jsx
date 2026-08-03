import { useOfflineSync } from "../hooks/useOfflineSync";

export default function OfflineStatusBanner() {
  const { isOnline, pendingCount, syncing } = useOfflineSync();

  if (isOnline && pendingCount === 0) return null;

  return (
    <div
      className={`px-4 py-2 text-center text-xs font-medium ${
        !isOnline ? "bg-warn/15 text-warn" : "bg-feed/15 text-feed"
      }`}
    >
      {!isOnline
        ? `📡 Nggak ada koneksi — catatan tetap tersimpan${pendingCount > 0 ? `, ${pendingCount} nunggu sinkron` : ""}`
        : syncing
        ? `🔄 Menyinkronkan ${pendingCount} catatan...`
        : `⏳ ${pendingCount} catatan nunggu disinkron`}
    </div>
  );
}