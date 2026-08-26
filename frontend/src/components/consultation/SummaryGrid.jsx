import KeyValueRow from "./KeyValueRow";

/**
 * Daftar ringkasan label/nilai -- `rows`: array `{label, value}`. Satu
 * kolom di layar sempit (mobile-first, TIDAK PERNAH butuh scroll
 * horizontal) — nama "grid" cuma mengacu ke tampilan ringkas
 * label+nilai berdampingan per baris, BUKAN tabel lebar bergrid literal.
 */
export default function SummaryGrid({ rows }) {
  const visible = (rows || []).filter(Boolean);
  if (visible.length === 0) return null;
  return (
    <dl className="bg-void-card border border-void-hairline rounded-xl2 px-3 py-1">
      {visible.map((row) => (
        <KeyValueRow key={row.label} label={row.label} value={row.value} />
      ))}
    </dl>
  );
}
