import ConsultationSectionCard from "./ConsultationSectionCard";
import { renderSectionContent } from "./sectionRenderers";
import { sectionLabel, isSensitiveSection } from "../../utils/consultationSections";

/**
 * Render laporan konsultasi TERSTRUKTUR (dari `activeSnapshot.report`
 * di DoctorConsultationScreen.jsx, sumber kebenaran preview/PDF yang
 * SAMA — lihat docstring di sana) jadi tampilan yang bisa dibaca
 * caregiver, BUKAN dump JSON mentah. TIDAK PERNAH menghitung ulang
 * data apa pun — murni presentasional, cuma memformat & melabeli field
 * yang SUDAH dikirim backend, satu section satu renderer eksplisit
 * (lihat sectionRenderers.jsx). Section kode yang nggak dikenal
 * (`renderSectionContent` fallback) ditampilkan sebagai pesan generik,
 * TIDAK PERNAH raw object.
 */
export default function ConsultationPreview({ report }) {
  if (!report || !report.sections) return null;
  const order = report.included_sections || Object.keys(report.sections);

  return (
    <div>
      {order.map((code) => {
        const section = report.sections[code];
        if (section === undefined) return null;
        return (
          <ConsultationSectionCard
            key={code}
            sectionCode={code}
            title={sectionLabel(code)}
            sensitive={isSensitiveSection(code)}
          >
            {renderSectionContent(code, section, report.period)}
          </ConsultationSectionCard>
        );
      })}
    </div>
  );
}
