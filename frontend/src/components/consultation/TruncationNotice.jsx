/**
 * Notis pemotongan daftar -- dipakai section berbatas baris (illness/
 * medication/growth/milestones/doctor_visits, lihat
 * backend/utils/consultation_report.py:_capped_query_result). TIDAK
 * PERNAH menampilkan boolean `truncated` mentah -- selalu kalimat
 * jumlah tampil vs jumlah total.
 */
export default function TruncationNotice({ visibleCount, totalCount }) {
  if (!totalCount || visibleCount >= totalCount) return null;
  return (
    <p className="text-xs text-ink-faint italic mt-2">
      Menampilkan {visibleCount} dari {totalCount} catatan terbaru pada periode ini.
    </p>
  );
}
