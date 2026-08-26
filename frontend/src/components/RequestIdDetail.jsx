import { useEffect, useRef, useState } from "react";
import { sanitizeRequestId } from "../utils/requestId";

/**
 * Tombol "info teknis" yang expandable — SATU-SATUNYA tempat request ID
 * server (X-Request-ID) ditampilkan, dan CUMA kalau beneran ada & VALID
 * (nggak pernah nampilin placeholder kosong buat item yang nggak punya,
 * mis. kegagalan jaringan murni yang nggak pernah nyampe ke server).
 * Nggak pernah nampilin body/respons/exception server mentah — cuma ID
 * korelasi ini doang.
 *
 * `requestId` divalidasi ULANG di sini (utils/requestId.js) sebagai LAPIS
 * KEDUA yang independen dari validasi pas nyimpen di
 * hooks/useOfflineSync.js — nilai dari IndexedDB TIDAK PERNAH dipercaya
 * mentah-mentah cuma karena datangnya dari penyimpanan lokal sendiri
 * (defense in depth: kalau somehow ada nilai nggak valid/kepanjangan yang
 * kesimpen — mis. dari versi kode lama — nggak bakal ketampil ATAU
 * ke-copy).
 *
 * Dipakai bareng oleh components/SyncCenter.jsx (item pending) dan
 * components/QueueReviewPanel.jsx (item needs-review yang KEPEMILIKANNYA
 * udah jelas — item legacy/unclaimed SENGAJA nggak pernah dikasih
 * komponen ini sama sekali, lihat QueueReviewPanel.jsx:LegacyCard).
 */
export default function RequestIdDetail({ requestId }) {
  const safeId = sanitizeRequestId(requestId);
  const [open, setOpen] = useState(false);
  const [copied, setCopied] = useState(false);
  const copiedTimerRef = useRef(null);

  useEffect(() => {
    // Bersihin timer "Tersalin" kalau komponennya di-unmount (mis. item
    // ini keburu tersinkron/dibuang) SEBELUM 2 detiknya lewat — nggak
    // boleh ada setState abis unmount, dan nggak boleh timer nyangkut.
    return () => clearTimeout(copiedTimerRef.current);
  }, []);

  if (!safeId) return null;

  const handleCopy = async () => {
    try {
      await navigator.clipboard?.writeText?.(safeId);
      setCopied(true);
      // Klik "Salin" berkali-kali beruntun HARUS nge-reset timer yang
      // lama (bukan numpuk beberapa setTimeout yang masing-masing nyoba
      // setCopied(false) sendiri-sendiri) — clear dulu sebelum bikin baru.
      clearTimeout(copiedTimerRef.current);
      copiedTimerRef.current = setTimeout(() => setCopied(false), 2000);
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
          <code className="text-[10px] text-ink-faint break-all flex-1">{safeId}</code>
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
