import SectionErrorBoundary from "./SectionErrorBoundary";

/**
 * Bungkus 1 section laporan: judul (heading semantik, urutan logis
 * ngikutin urutan section di respons), badge "Sensitif" kalau relevan
 * (TEKS, bukan cuma warna -- lihat requirement aksesibilitas), lalu
 * konten section itu sendiri di dalam SectionErrorBoundary (1 section
 * gagal render TIDAK PERNAH menjatuhkan section lain).
 */
export default function ConsultationSectionCard({ sectionCode, title, sensitive, children }) {
  return (
    <section className="mb-4" aria-labelledby={`consult-heading-${sectionCode}`}>
      <div className="flex items-center gap-2 mb-2">
        <h3 id={`consult-heading-${sectionCode}`} className="text-sm font-semibold text-ink">
          {title}
        </h3>
        {sensitive && (
          <span className="text-[10px] font-medium text-warn bg-warn/10 border border-warn/30 rounded-full px-2 py-0.5">
            Sensitif
          </span>
        )}
      </div>
      <SectionErrorBoundary sectionCode={sectionCode}>{children}</SectionErrorBoundary>
    </section>
  );
}
