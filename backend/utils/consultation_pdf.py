"""
Doctor Consultation Workflow — Phase 1: render laporan konsultasi
(dict dari utils/consultation_report.py:build_consultation_report) jadi
PDF SINKRON, DI MEMORI (BytesIO) -- TIDAK PERNAH ditulis ke disk server,
TIDAK PERNAH ada penyimpanan permanen (lihat routes/doctor_consultation_routes.py
buat siklus hidup buffer-nya, dibuang begitu response terkirim).

Pakai `reportlab` -- dependency PDF yang SAMA PERSIS dipakai
routes/report_routes.py (laporan umum yang sudah ada), TIDAK menambah
dependency baru. Warna & unit halaman (A4, margin) mengikuti konvensi
visual report_routes.py (COLOR_* di bawah) biar konsisten identitas
visual app.

KEAMANAN TEKS BEBAS: `reportlab.platypus.Paragraph` menafsirkan
sebagian markup mirip-XML (`<b>`, `<br/>`, dst) di teksnya -- SEMUA teks
yang sumbernya dari caregiver (nama obat, nama penyakit, gejala, nama
dokter/klinik, alasan, diagnosis, ATAUPUN teks transien
questions/additional_note) WAJIB lewat `_safe()` (html.escape) SEBELUM
dibungkus Paragraph di mana pun di file ini -- mencegah PDF-markup
injection lewat data yang caregiver ketik sendiri.
"""
import html
import io

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import (
    KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
)

from utils.consultation_report import (
    SECTION_ACTIVITY_MOOD, SECTION_CHILD_SUMMARY, SECTION_DIAPER, SECTION_DOCTOR_VISITS,
    SECTION_FEEDING, SECTION_GROWTH, SECTION_ILLNESS, SECTION_INSIGHTS, SECTION_MEDICATION,
    SECTION_MILESTONES, SECTION_NOTE, SECTION_PUMPING, SECTION_QUESTIONS, SECTION_SLEEP,
    SECTION_TEMPERATURE, SECTION_VACCINATION,
)

COLOR_ACCENT = colors.HexColor("#FFA733")
COLOR_MUTED = colors.HexColor("#C7BAA9")
COLOR_INK = colors.HexColor("#4A3F35")
COLOR_HEADER_BG = colors.HexColor("#FFF1DE")

SECTION_LABELS = {
    SECTION_CHILD_SUMMARY: "Ringkasan Anak",
    SECTION_FEEDING: "Menyusui / Makan",
    SECTION_SLEEP: "Tidur",
    SECTION_DIAPER: "Popok",
    SECTION_PUMPING: "Memerah ASI",
    SECTION_ACTIVITY_MOOD: "Aktivitas & Suasana Hati",
    SECTION_GROWTH: "Pertumbuhan",
    SECTION_TEMPERATURE: "Ringkasan Suhu",
    SECTION_ILLNESS: "Riwayat Sakit",
    SECTION_MEDICATION: "Riwayat Obat",
    SECTION_VACCINATION: "Status Vaksinasi",
    SECTION_MILESTONES: "Tumbuh Kembang",
    SECTION_DOCTOR_VISITS: "Kunjungan Dokter Sebelumnya",
    SECTION_INSIGHTS: "Ringkasan Smart Insights",
    SECTION_QUESTIONS: "Pertanyaan untuk Dokter",
    SECTION_NOTE: "Catatan Tambahan Caregiver",
}

MOOD_LABELS = {"ceria": "Ceria", "baik": "Baik", "sedih": "Sedih", "menangis": "Menangis"}


def _safe(value):
    """Escape teks sumber-caregiver SEBELUM masuk Paragraph -- lihat docstring modul. `None`/kosong -> '-'."""
    if value is None or value == "":
        return "-"
    return html.escape(str(value), quote=False)


def _safe_multiline(value):
    """Sama seperti `_safe`, TAPI newline (dari questions/additional_note yang sudah dinormalisasi) diubah jadi `<br/>` SETELAH escape -- tag ini yang kita sisipkan sendiri, bukan dari input user, jadi aman."""
    if value is None or value == "":
        return "-"
    return html.escape(str(value), quote=False).replace("\n", "<br/>")


def _fmt_num(value, suffix=""):
    if value is None:
        return "-"
    return f"{value}{suffix}"


class _Styles:
    def __init__(self):
        base = getSampleStyleSheet()
        self.title = ParagraphStyle("ConsultTitle", parent=base["Title"], fontSize=18, spaceAfter=2)
        self.subtitle = ParagraphStyle("ConsultSubtitle", parent=base["Normal"], fontSize=10, textColor=colors.grey)
        self.h2 = ParagraphStyle(
            "ConsultH2", parent=base["Heading2"], fontSize=13, spaceBefore=14, spaceAfter=6, textColor=COLOR_INK
        )
        self.normal = ParagraphStyle("ConsultNormal", parent=base["Normal"], fontSize=9, leading=12)
        self.cell = ParagraphStyle("ConsultCell", parent=base["Normal"], fontSize=8, leading=10)
        self.small = ParagraphStyle("ConsultSmall", parent=base["Normal"], fontSize=8, textColor=colors.grey, leading=11)
        self.disclaimer = ParagraphStyle(
            "ConsultDisclaimer", parent=base["Normal"], fontSize=9, leading=12, textColor=COLOR_INK
        )


def _kv_table(rows, styles, col_widths=(5.5 * cm, 10.5 * cm)):
    """Tabel 2 kolom label/nilai -- dipakai buat semua section ringkasan (bukan daftar baris)."""
    data = [[Paragraph(f"<b>{_safe(k)}</b>", styles.cell), Paragraph(_safe(v), styles.cell)] for k, v in rows]
    t = Table(data, colWidths=list(col_widths))
    t.setStyle(TableStyle([
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("GRID", (0, 0), (-1, -1), 0.4, COLOR_MUTED),
        ("BACKGROUND", (0, 0), (0, -1), COLOR_HEADER_BG),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    return t


def _entries_table(header, rows, col_widths, styles):
    """Tabel banyak baris (illness/medication/doctor_visits/growth/milestones/vaksinasi) -- SEMUA sel teks bebas lewat Paragraph (auto-wrap, nggak pernah clipped), header berulang tiap halaman baru (`repeatRows=1`)."""
    data = [[Paragraph(f"<b>{_safe(h)}</b>", styles.cell) for h in header]]
    for row in rows:
        data.append([Paragraph(_safe(cell), styles.cell) for cell in row])
    t = Table(data, colWidths=col_widths, repeatRows=1)
    t.setStyle(TableStyle([
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("BACKGROUND", (0, 0), (-1, 0), COLOR_HEADER_BG),
        ("GRID", (0, 0), (-1, -1), 0.4, COLOR_MUTED),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    return t


def _truncation_note(section, styles):
    if not section.get("truncated"):
        return None
    total = section.get("total_count_in_period")
    return Paragraph(
        f"Menampilkan sebagian data terbaru saja (dari total {total} baris pada periode ini).", styles.small
    )


def _render_child_summary(section, styles):
    rows = [
        ("Nama", section["display_name"]),
        ("Tanggal lahir", section["birth_date"]),
        ("Jenis kelamin", section.get("gender") or "-"),
        ("Usia (per akhir periode)", section["age_as_of_report_end"]),
        ("Jumlah catatan obat (periode ini)", section["medication_event_count_in_period"]),
        ("Jumlah kunjungan dokter (periode ini)", section["doctor_visit_count_in_period"]),
        ("Jumlah catatan sakit (periode ini)", section["illness_record_count_in_period"]),
        ("Jumlah catatan suhu (periode ini)", section["temperature_record_count_in_period"]),
    ]
    return [_kv_table(rows, styles)]


def _render_feeding(section, styles):
    rows = [
        ("Total sesi", section["total_events"]),
        ("Rata-rata sesi/hari", section["avg_events_per_day"]),
        ("ASI langsung", section["by_type"].get("asi_langsung", 0)),
        ("ASI perah", section["by_type"].get("asi_perah", 0)),
        ("Susu formula", section["by_type"].get("sufor", 0)),
        ("MPASI", section["by_type"].get("mpasi", 0)),
        ("Total volume tercatat (ml)", _fmt_num(section["total_volume_ml"])),
        ("Rata-rata volume/sesi (ml)", _fmt_num(section["avg_volume_ml_per_event"])),
    ]
    return [_kv_table(rows, styles)]


def _render_sleep(section, styles):
    rows = [
        ("Sesi selesai", section["completed_session_count"]),
        ("Sesi belum selesai (masih berjalan)", section["unfinished_session_count"]),
        ("Total durasi tercatat (menit)", section["total_completed_minutes"]),
        ("Rata-rata durasi/sesi (menit)", _fmt_num(section["avg_duration_minutes_per_session"])),
    ]
    return [_kv_table(rows, styles)]


def _render_diaper(section, styles):
    rows = [
        ("Total ganti popok", section["total_events"]),
        ("Pipis", section["pipis_count"]),
        ("BAB", section["bab_count"]),
        ("Rata-rata/hari", section["avg_events_per_day"]),
    ]
    return [_kv_table(rows, styles)]


def _render_pumping(section, styles):
    rows = [
        ("Total sesi", section["session_count"]),
        ("Total volume tercatat (ml)", section["total_volume_ml"]),
        ("Rata-rata volume/sesi (ml)", _fmt_num(section["avg_volume_ml_per_event"])),
        ("Total durasi tercatat (menit)", section["total_duration_minutes"]),
    ]
    return [_kv_table(rows, styles)]


def _render_activity_mood(section, styles):
    activity, mood = section["activity"], section["mood"]
    rows = [
        ("Jumlah sesi aktivitas", activity["session_count"]),
        ("Total durasi aktivitas (menit)", activity["total_duration_minutes"]),
        ("Suasana hati - ceria", mood["counts"].get("ceria", 0)),
        ("Suasana hati - baik", mood["counts"].get("baik", 0)),
        ("Suasana hati - sedih", mood["counts"].get("sedih", 0)),
        ("Suasana hati - menangis", mood["counts"].get("menangis", 0)),
    ]
    return [_kv_table(rows, styles)]


def _render_growth(section, styles):
    """
    3 kelompok (bug review: preview sempat nggak nampilin pengukuran
    SEBELUMNYA & perubahan lingkar kepala sama sekali -- PDF ini
    ternyata punya celah yang SAMA, diperbaiki bareng biar kesetaraan
    LOGIS preview<->PDF tetap terjaga, lihat
    frontend/src/components/consultation/sectionRenderers.jsx:GrowthSection):
    pengukuran terakhir, pengukuran SEBELUMNYA (CUMA kalau ada), lalu
    perubahan (CUMA kalau ada pengukuran sebelumnya buat dibandingkan).
    `_fmt_num` cuma balikin "-" buat `None` SUNGGUHAN (BUKAN 0, BUKAN
    falsy) -- nilai 0 literal & delta negatif tetap tampil apa adanya.
    """
    flows = []
    latest, previous = section["latest"], section["previous"]
    rows = [
        ("Pengukuran terakhir (tanggal)", latest["measured_date"] if latest else "-"),
        ("Berat terakhir (kg)", _fmt_num(latest["weight_kg"]) if latest else "-"),
        ("Tinggi terakhir (cm)", _fmt_num(latest["height_cm"]) if latest else "-"),
        ("Lingkar kepala terakhir (cm)", _fmt_num(latest["head_circumference_cm"]) if latest else "-"),
        ("Hari sejak pengukuran terakhir", _fmt_num(section["days_since_latest_measurement"])),
    ]
    flows.append(_kv_table(rows, styles))
    if previous:
        flows.append(Spacer(1, 6))
        flows.append(Paragraph("Pengukuran sebelumnya:", styles.normal))
        previous_rows = [
            ("Tanggal", previous["measured_date"]),
            ("Berat (kg)", _fmt_num(previous["weight_kg"])),
            ("Tinggi (cm)", _fmt_num(previous["height_cm"])),
            ("Lingkar kepala (cm)", _fmt_num(previous["head_circumference_cm"])),
        ]
        flows.append(_kv_table(previous_rows, styles))
        flows.append(Spacer(1, 6))
        flows.append(Paragraph("Perubahan sejak pengukuran sebelumnya:", styles.normal))
        change_rows = [
            ("Perubahan berat (kg)", _fmt_num(section["weight_change_kg"])),
            ("Perubahan tinggi (cm)", _fmt_num(section["height_change_cm"])),
            ("Perubahan lingkar kepala (cm)", _fmt_num(section["head_circumference_change_cm"])),
        ]
        flows.append(_kv_table(change_rows, styles))
    measurements = section["measurements_in_period"]
    if measurements:
        flows.append(Spacer(1, 6))
        flows.append(Paragraph("Pengukuran dalam periode ini:", styles.normal))
        table_rows = [
            [m["measured_date"], _fmt_num(m["weight_kg"]), _fmt_num(m["height_cm"]), _fmt_num(m["head_circumference_cm"])]
            for m in measurements
        ]
        flows.append(_entries_table(
            ["Tanggal", "Berat (kg)", "Tinggi (cm)", "Lingkar Kepala (cm)"],
            table_rows, [3.2 * cm, 3.2 * cm, 3.2 * cm, 4.4 * cm], styles,
        ))
        note = _truncation_note(section, styles)
        if note:
            flows.append(note)
    return flows


def _render_temperature(section, styles):
    rows = [
        ("Jumlah catatan (periode ini)", section["record_count_in_period"]),
        ("Rata-rata suhu (°C, periode ini)", _fmt_num(section["avg_celsius_in_period"])),
        ("Suhu terendah (°C, periode ini)", _fmt_num(section["min_celsius_in_period"])),
        ("Suhu tertinggi (°C, periode ini)", _fmt_num(section["max_celsius_in_period"])),
        ("Suhu terakhir tercatat (°C)", _fmt_num(section["latest_temperature_celsius"])),
    ]
    return [_kv_table(rows, styles)]


def _render_illness(section, styles):
    flows = []
    if not section["entries"]:
        flows.append(Paragraph("Tidak ada catatan sakit pada periode ini.", styles.normal))
        return flows
    rows = [[e["illness_name"], e["start_date"], e["end_date"] or "Berlangsung", e["symptoms"] or "-"] for e in section["entries"]]
    flows.append(_entries_table(
        ["Nama Sakit", "Mulai", "Selesai", "Gejala"], rows,
        [3.2 * cm, 2.4 * cm, 2.4 * cm, 8 * cm], styles,
    ))
    note = _truncation_note(section, styles)
    if note:
        flows.append(note)
    return flows


def _render_medication_adherence_summary(summary, styles):
    """
    Ringkasan kepatuhan AGREGAT (Medication Schedule & Adherence Phase 1)
    -- `None` kalau child ini nggak punya jadwal obat yang overlap
    periode ini SAMA SEKALI (lihat utils/consultation_report.py:
    _medication_adherence_summary), BUKAN dirender sebagai tabel kosong.
    CUMA angka agregat, TIDAK PERNAH nama obat per-jadwal -- konsisten
    sama preview JSON (1 sumber data yang sama, lihat docstring modul).
    """
    if summary is None:
        return []
    rows = [
        ("Jumlah jadwal obat aktif pada periode ini", summary["schedule_count"]),
        ("Dosis yang dijadwalkan (periode ini)", summary["expected_count"]),
        ("Dosis diberikan", summary["administered_count"]),
        ("Dosis dilewati", summary["skipped_count"]),
        ("Dosis terlambat diberikan", summary["late_administered_count"]),
        ("Dosis belum diselesaikan (lewat jadwal)", summary["overdue_unresolved_count"]),
        ("Persentase kepatuhan", _fmt_num(summary["adherence_percentage"], "%")),
    ]
    return [
        Paragraph("<b>Ringkasan Kepatuhan Jadwal Obat</b>", styles.normal),
        _kv_table(rows, styles),
    ]


def _render_medication(section, styles):
    flows = []
    if not section["entries"]:
        flows.append(Paragraph("Tidak ada catatan obat pada periode ini.", styles.normal))
    else:
        rows = [[e["medication_name"], e["dosage"] or "-", e["timestamp"][:16].replace("T", " ")] for e in section["entries"]]
        flows.append(_entries_table(["Nama Obat", "Dosis", "Waktu"], rows, [6 * cm, 4 * cm, 6 * cm], styles))
        note = _truncation_note(section, styles)
        if note:
            flows.append(note)
    flows.extend(_render_medication_adherence_summary(section.get("adherence_summary"), styles))
    return flows


def _render_vaccination(section, styles):
    status_labels = {"given": "Sudah diberikan", "upcoming": "Akan datang", "due": "Waktunya", "overdue": "Terlambat"}
    rows = [
        [v["vaccine_name"] + (f" ({v['dose_label']})" if v.get("dose_label") else ""),
         status_labels.get(v.get("state"), "Sudah diberikan" if v["given"] else "Belum diberikan"),
         v.get("recommended_date") or "-", v.get("given_date") or "-"]
        for v in section["vaccinations"]
    ]
    if not rows:
        return [Paragraph("Belum ada jadwal vaksinasi yang tersedia.", styles.normal)]
    return [_entries_table(["Vaksin", "Status", "Rekomendasi", "Diberikan"], rows, [7 * cm, 3 * cm, 3 * cm, 3 * cm], styles)]


def _render_milestones(section, styles):
    flows = []
    if not section["entries"]:
        flows.append(Paragraph("Tidak ada milestone tercatat pada periode ini.", styles.normal))
        return flows
    rows = [[e["milestone_type"], e["achieved_date"]] for e in section["entries"]]
    flows.append(_entries_table(["Milestone", "Tanggal"], rows, [10 * cm, 6 * cm], styles))
    note = _truncation_note(section, styles)
    if note:
        flows.append(note)
    return flows


def _render_doctor_visits(section, styles):
    flows = []
    if not section["entries"]:
        flows.append(Paragraph("Tidak ada kunjungan dokter pada periode ini.", styles.normal))
        return flows
    rows = [
        [e["visit_date"], e["doctor_name"] or e["clinic_name"] or "-", e["reason"] or "-", e["diagnosis"] or "-"]
        for e in section["entries"]
    ]
    flows.append(_entries_table(
        ["Tanggal", "Dokter/Klinik", "Keluhan", "Diagnosis"], rows,
        [2.4 * cm, 3.6 * cm, 4.2 * cm, 5.8 * cm], styles,
    ))
    note = _truncation_note(section, styles)
    if note:
        flows.append(note)
    return flows


def _render_insights(section, styles):
    flows = []
    if not section["data_quality"]["has_any_data"]:
        flows.append(Paragraph(
            "Data pada periode ini masih terbatas, sehingga ringkasan tren belum dapat ditampilkan.", styles.normal
        ))
        return flows
    for card in section["insights"]:
        flows.append(Paragraph(f"• {_safe(card['description'])}", styles.normal))
    return flows


def _render_questions(section, styles):
    return [Paragraph(_safe_multiline(section["text"]) or "-", styles.normal)]


def _render_note(section, styles):
    return [Paragraph(_safe_multiline(section["text"]) or "-", styles.normal)]


_SECTION_RENDERERS = {
    SECTION_CHILD_SUMMARY: _render_child_summary,
    SECTION_FEEDING: _render_feeding,
    SECTION_SLEEP: _render_sleep,
    SECTION_DIAPER: _render_diaper,
    SECTION_PUMPING: _render_pumping,
    SECTION_ACTIVITY_MOOD: _render_activity_mood,
    SECTION_GROWTH: _render_growth,
    SECTION_TEMPERATURE: _render_temperature,
    SECTION_ILLNESS: _render_illness,
    SECTION_MEDICATION: _render_medication,
    SECTION_VACCINATION: _render_vaccination,
    SECTION_MILESTONES: _render_milestones,
    SECTION_DOCTOR_VISITS: _render_doctor_visits,
    SECTION_INSIGHTS: _render_insights,
    SECTION_QUESTIONS: _render_questions,
    SECTION_NOTE: _render_note,
}


def _footer(canvas, doc, child_display_name):
    """Footer BERULANG di tiap halaman -- nomor halaman + catatan privasi ringkas (lihat requirement 'page numbers' & 'repeated header/footer')."""
    canvas.saveState()
    canvas.setStrokeColor(COLOR_MUTED)
    canvas.setLineWidth(0.5)
    canvas.line(1.8 * cm, 1.3 * cm, A4[0] - 1.8 * cm, 1.3 * cm)
    canvas.setFont("Helvetica", 7)
    canvas.setFillColor(colors.grey)
    canvas.drawString(1.8 * cm, 1.0 * cm, f"Laporan Konsultasi Dokter — {child_display_name}")
    canvas.drawRightString(A4[0] - 1.8 * cm, 1.0 * cm, f"Halaman {canvas.getPageNumber()}")
    canvas.restoreState()


def render_consultation_pdf(report):
    """
    `report`: dict dari utils/consultation_report.py:build_consultation_report.
    Balikin `io.BytesIO` siap-kirim (posisi sudah di-seek(0)) -- SELALU
    dibuang begitu response terkirim (lihat routes/doctor_consultation_routes.py),
    TIDAK PERNAH ditulis ke file.
    """
    styles = _Styles()
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4,
        topMargin=1.5 * cm, bottomMargin=2.0 * cm,
        leftMargin=1.8 * cm, rightMargin=1.8 * cm,
        title="Laporan Konsultasi Dokter",
    )

    child_name = report["child_display_name"]
    period = report["period"]

    story = [
        Paragraph("Laporan Konsultasi Dokter", styles.title),
        Paragraph(f"{child_name} · Periode {period['start_date']} s/d {period['end_date']} (WIB)", styles.subtitle),
        Paragraph(f"Dibuat: {report['generated_at']}", styles.subtitle),
        Spacer(1, 8),
        KeepTogether([
            Paragraph(f"<b>Perhatian:</b> {_safe(report['disclaimer'])}", styles.disclaimer),
            Spacer(1, 4),
            Paragraph(_safe(report["generated_statement"]), styles.small),
        ]),
        Spacer(1, 10),
    ]

    for code in report["included_sections"]:
        section = report["sections"].get(code)
        if section is None:
            continue
        renderer = _SECTION_RENDERERS.get(code)
        if renderer is None:
            continue
        block = [Paragraph(SECTION_LABELS.get(code, code), styles.h2)]
        block.extend(renderer(section, styles))
        # Judul section dikunci BARENG flowable konten pertamanya (nggak
        # pernah judul kepisah sendirian di bawah halaman) -- sisa
        # konten (kalau ada) tetap boleh berpindah halaman biasa, biar
        # section panjang (tabel banyak baris) tetap paginasi dengan benar.
        story.append(KeepTogether(block[:2]))
        story.extend(block[2:])

    def _on_page(canvas, doc_):
        _footer(canvas, doc_, child_name)

    doc.build(story, onFirstPage=_on_page, onLaterPages=_on_page)
    buffer.seek(0)
    return buffer
