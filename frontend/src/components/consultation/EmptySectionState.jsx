/** Pesan kosong yang bisa dibaca -- SELALU teks konkret spesifik section (lihat sectionRenderers.jsx), bukan generik "tidak ada data". */
export default function EmptySectionState({ message }) {
  return <p className="text-sm text-ink-faint py-2">{message}</p>;
}
