/**
 * 1 baris label/nilai -- pakai `<dt>`/`<dd>` (struktur definisi
 * semantik, dibaca screen reader sebagai pasangan label-nilai) di
 * dalam `<dl>` (lihat SummaryGrid.jsx, yang membungkus baris-baris
 * ini). Baris berdiri sendiri (bukan tabel lebar) -- otomatis nggak
 * pernah butuh scroll horizontal di layar sempit.
 */
export default function KeyValueRow({ label, value }) {
  return (
    <div className="flex justify-between gap-3 py-1.5 border-b border-void-hairline last:border-b-0">
      <dt className="text-xs text-ink-faint">{label}</dt>
      <dd className="text-sm text-ink font-medium text-right break-words">{value}</dd>
    </div>
  );
}
