/**
 * Daftar entri bounded (illness/medication/doctor_visits/milestones/
 * pengukuran pertumbuhan/vaksinasi) sebagai KARTU BERTUMPUK, BUKAN
 * tabel lebar -- di layar sempit, tabel lebar butuh scroll horizontal
 * (dilarang requirement mobile); kartu bertumpuk otomatis pas
 * lebarnya, teks panjang (nama obat/gejala/alasan kunjungan) bebas
 * bungkus multi-baris.
 */
export default function DetailList({ children }) {
  return <ul className="space-y-2">{children}</ul>;
}

export function DetailListItem({ children }) {
  return (
    <li className="bg-void-card border border-void-hairline rounded-xl2 px-3 py-2.5 text-sm text-ink break-words">
      {children}
    </li>
  );
}
