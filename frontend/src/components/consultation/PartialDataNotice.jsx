/**
 * Notis cakupan data parsial -- dipakai kalau CUMA SEBAGIAN event di
 * suatu section punya nilai terukur (volume/durasi), lihat
 * backend/utils/insights_engine.py kebijakan "jangan anggap subtotal
 * parsial sebagai total lengkap". `covered`/`total` = jumlah event
 * DENGAN nilai vs jumlah event SELURUHNYA.
 */
export default function PartialDataNotice({ covered, total, label = "data" }) {
  if (covered === total) return null;
  return (
    <p className="text-xs text-ink-faint italic mt-1">
      {covered} dari {total} sesi memiliki {label}.
    </p>
  );
}
