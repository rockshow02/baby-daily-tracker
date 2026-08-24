"""
Child Medical Profile & Emergency Card — Phase 1: render ringkasan
kartu darurat (dict dari utils/emergency_card_report.py:
build_emergency_card_summary) jadi PDF SINKRON, DI MEMORI (BytesIO) --
TIDAK PERNAH ditulis ke disk server, TIDAK PERNAH ada penyimpanan
permanen -- pola SAMA PERSIS utils/consultation_pdf.py.

REUSE penuh utils/pdf_common.py (styling, escaping, tabel dasar) --
BUKAN framework PDF kedua. `render_medical_profile_flowables()` di
bawah JUGA dipakai LANGSUNG oleh utils/consultation_pdf.py buat section
opsional `medical_profile` milik Doctor Consultation -- SATU fungsi
render, dua pemanggil, kesetaraan visual terjamin antara Emergency Card
berdiri sendiri dan section di dalam laporan konsultasi.
"""
import io
import re

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.platypus import KeepTogether, Paragraph, SimpleDocTemplate, Spacer

from utils.pdf_common import (
    BaseStyles, COLOR_MUTED, entries_table, fmt_num, kv_table, safe, safe_multiline,
)

_FILENAME_SAFE_RE = re.compile(r"[^a-z0-9-]+")


def safe_filename_component(text):
    """Sama persis routes/doctor_consultation_routes.py:_safe_filename_component -- 1 kebijakan nama file aman, dipakai ulang di sini."""
    lowered = (text or "").strip().lower().replace(" ", "-")
    cleaned = _FILENAME_SAFE_RE.sub("", lowered)
    return cleaned or "anak"


_ALLERGY_TYPE_LABELS = {"drug": "Obat", "food": "Makanan", "other": "Lainnya"}
_SEVERITY_LABELS = {"mild": "Ringan", "moderate": "Sedang", "severe": "Berat", "unknown": "Tidak diketahui"}
_CONDITION_STATUS_LABELS = {"active": "Aktif", "resolved": "Sudah sembuh", "unknown": "Tidak diketahui"}


def render_medical_profile_flowables(section, styles, *, heading=None):
    """
    List flowable reportlab buat 1 ringkasan profil medis/kartu darurat
    -- dipakai LANGSUNG oleh render_emergency_card_pdf() di bawah
    MAUPUN utils/consultation_pdf.py (section `medical_profile`).
    `heading`: Paragraph opsional buat judul section (dilewatin dari
    consultation_pdf.py yang sudah punya konvensi judul section sendiri;
    dokumen Emergency Card berdiri sendiri makein judul dokumen di
    render_emergency_card_pdf(), bukan lewat parameter ini).

    SEMUA teks sumber-caregiver (nama alergen/reaksi/kondisi/catatan/
    nama dokter/klinik/kontak/instruksi darurat) lewat `safe()`/
    `safe_multiline()` SEBELUM masuk Paragraph -- lihat docstring
    utils/pdf_common.py.
    """
    flows = []
    if heading:
        flows.append(heading)

    if not section["has_profile"]:
        flows.append(Paragraph(
            "Profil medis anak ini belum pernah diisi caregiver.", styles.normal,
        ))
        return flows

    flows.append(kv_table([
        ("Golongan darah", section["blood_type_label"]),
    ], styles))

    # Alergi -- yang PENTING/berat duluan (sudah diurutkan di
    # utils/emergency_card_report.py), TIDAK PERNAH diklasifikasi ulang
    # di sini.
    flows.append(Spacer(1, 6))
    flows.append(Paragraph("<b>Alergi</b>", styles.normal))
    if not section["allergies"]:
        flows.append(Paragraph("Tidak ada alergi tercatat.", styles.small))
    else:
        rows = [
            [
                _ALLERGY_TYPE_LABELS.get(a["type"], a["type"]),
                a["allergen"],
                a.get("reaction") or "-",
                _SEVERITY_LABELS.get(a.get("severity"), "-"),
            ]
            for a in section["allergies"]
        ]
        flows.append(entries_table(
            ["Jenis", "Alergen", "Reaksi", "Tingkat Keparahan"], rows,
            [2.4 * cm, 3.6 * cm, 5.5 * cm, 4.5 * cm], styles,
        ))

    flows.append(Spacer(1, 6))
    flows.append(Paragraph("<b>Kondisi Medis Penting</b>", styles.normal))
    if not section["conditions"]:
        flows.append(Paragraph("Tidak ada kondisi medis penting tercatat.", styles.small))
    else:
        rows = [
            [
                c["condition_name"],
                _CONDITION_STATUS_LABELS.get(c.get("status"), "-"),
                fmt_num(c.get("diagnosed_year")),
                c.get("note") or "-",
            ]
            for c in section["conditions"]
        ]
        flows.append(entries_table(
            ["Kondisi", "Status", "Tahun Diagnosis", "Catatan"], rows,
            [4 * cm, 2.6 * cm, 2.9 * cm, 6.5 * cm], styles,
        ))

    flows.append(Spacer(1, 6))
    flows.append(Paragraph("<b>Obat Rutin Saat Ini</b>", styles.normal))
    if not section["regular_medications"]:
        flows.append(Paragraph("Tidak ada obat rutin aktif tercatat.", styles.small))
    else:
        rows = [
            [m["medication_name"], m.get("dose") or "-", ", ".join(m.get("times_of_day") or []) or "-"]
            for m in section["regular_medications"]
        ]
        flows.append(entries_table(["Nama Obat", "Dosis", "Jam Pemberian"], rows, [6 * cm, 4 * cm, 6 * cm], styles))

    flows.append(Spacer(1, 6))
    flows.append(Paragraph("<b>Kontak Medis & Darurat</b>", styles.normal))
    flows.append(kv_table([
        ("Dokter utama", section.get("primary_doctor_name") or "-"),
        ("Klinik/RS utama", section.get("primary_clinic_name") or "-"),
        ("Telepon klinik", section.get("primary_clinic_phone") or "-"),
        ("Kontak darurat", section.get("emergency_contact_name") or "-"),
        ("Hubungan", section.get("emergency_contact_relationship") or "-"),
        ("Telepon kontak darurat", section.get("emergency_contact_phone") or "-"),
    ], styles))

    if section.get("emergency_instructions"):
        flows.append(Spacer(1, 6))
        flows.append(Paragraph("<b>Instruksi Darurat dari Caregiver</b>", styles.normal))
        flows.append(Paragraph(safe_multiline(section["emergency_instructions"]), styles.normal))

    flows.append(Spacer(1, 6))
    last_reviewed = section.get("last_reviewed_at")
    reviewed_by = section.get("last_reviewed_by_name")
    if last_reviewed:
        reviewed_text = f"Terakhir diperiksa ulang: {last_reviewed[:16].replace('T', ' ')}"
        if reviewed_by:
            reviewed_text += f" oleh {reviewed_by}"
    else:
        reviewed_text = "Belum pernah ditandai diperiksa ulang."
    flows.append(Paragraph(safe(reviewed_text), styles.small))

    return flows


def _footer(canvas, doc, child_display_name):
    canvas.saveState()
    canvas.setStrokeColor(COLOR_MUTED)
    canvas.setLineWidth(0.5)
    canvas.line(1.8 * cm, 1.3 * cm, A4[0] - 1.8 * cm, 1.3 * cm)
    canvas.setFont("Helvetica", 7)
    canvas.setFillColor(colors.grey)
    canvas.drawString(1.8 * cm, 1.0 * cm, f"Kartu Darurat Medis — {child_display_name}")
    canvas.drawRightString(A4[0] - 1.8 * cm, 1.0 * cm, f"Halaman {canvas.getPageNumber()}")
    canvas.restoreState()


def render_emergency_card_pdf(section):
    """
    `section`: dict dari utils/emergency_card_report.py:build_emergency_card_summary.
    Balikin `io.BytesIO` siap-kirim (posisi sudah di-seek(0)) -- SELALU
    dibuang begitu response terkirim, TIDAK PERNAH ditulis ke file.
    """
    styles = BaseStyles()
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4,
        topMargin=1.5 * cm, bottomMargin=2.0 * cm,
        leftMargin=1.8 * cm, rightMargin=1.8 * cm,
        title="Kartu Darurat Medis",
    )

    child_name = section["child_display_name"]
    story = [
        Paragraph("Kartu Darurat Medis", styles.title),
        Paragraph(f"{child_name} · Lahir {section['birth_date']} · Usia saat ini {section['age_now']}", styles.subtitle),
        Paragraph(f"Dibuat: {section['generated_at']}", styles.subtitle),
        Spacer(1, 8),
        KeepTogether([
            Paragraph(f"<b>Perhatian:</b> {safe(section['disclaimer'])}", styles.disclaimer),
            Spacer(1, 4),
            Paragraph(safe(section["privacy_note"]), styles.warn),
        ]),
        Spacer(1, 10),
    ]
    story.extend(render_medical_profile_flowables(section, styles))

    def _on_page(canvas, doc_):
        _footer(canvas, doc_, child_name)

    doc.build(story, onFirstPage=_on_page, onLaterPages=_on_page)
    buffer.seek(0)
    return buffer
