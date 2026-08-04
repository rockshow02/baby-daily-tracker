import io
import os

from flask import Blueprint, jsonify, session, send_file, request
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable, Image, KeepTogether,
)
from reportlab.graphics.shapes import Drawing, Line, String, Rect

from models import (
    Child, GrowthMeasurement, VaccineSchedule, ChildVaccination,
    DoctorVisitLog, IllnessLog, MilestoneLog, GrowthReference,
)
from utils.access import get_accessible_child
from utils.auth import get_current_user_id
from utils.timezone_utils import today_wib
from utils.growth_calc import evaluate_measurement
from utils.milestone_reference import MILESTONE_REFERENCE
from routes.children_routes import _age_in_months, _add_months, _build_vaccination_list

report_bp = Blueprint("report", __name__)

# ---------- warna status, dipakai konsisten di seluruh laporan ----------
COLOR_GOOD = colors.HexColor("#2E8B57")   # hijau
COLOR_WARN = colors.HexColor("#D4A017")   # kuning/oranye tua
COLOR_BAD = colors.HexColor("#C0392B")    # merah
COLOR_ACCENT = colors.HexColor("#FFA733")  # oranye khas app
COLOR_MUTED = colors.HexColor("#C7BAA9")
COLOR_INK = colors.HexColor("#4A3F35")


def _owned_child(child_id):
    user_id = get_current_user_id()
    if not user_id:
        return None
    return get_accessible_child(child_id, user_id)


def _age_str(birth_date, on_date):
    days = (on_date - birth_date).days
    months = days // 30
    if months < 1:
        return f"{days} hari"
    years, rem_months = divmod(months, 12)
    if years > 0:
        return f"{years} thn {rem_months} bln"
    return f"{months} bulan"


def _is_zscore_normal(z_score):
    """
    Cek 'normal' pakai z-score langsung (-2 s/d 2, sesuai definisi WHO yang
    dipakai growth_calc.py), BUKAN cocokin string status — soalnya label
    status beda-beda per jenis pengukuran ("Gizi baik (normal)" buat berat,
    "Normal" buat tinggi/lingkar kepala), jadi string matching gampang meleset.
    """
    return z_score is not None and -2 <= z_score <= 2


def _status_dot(z_score):
    """Bulatan warna kecil sesuai z-score, dipakai di tabel/ringkasan."""
    if z_score is None:
        return "\u25CF", COLOR_MUTED
    if _is_zscore_normal(z_score):
        return "\u25CF", COLOR_GOOD
    return "\u25CF", COLOR_WARN


# ============================================================
#  RINGKASAN & INSIGHT — rule-based, TANPA AI
# ============================================================

def _build_summary_checklist(child, latest_measurement, age_months, vax_given, vax_total,
                              illness_count, visit_count):
    """
    Poin ✔/✗ ringkasan halaman pertama. Setiap poin murni hasil pengecekan
    kondisi data — nggak ada interpretasi "kira-kira", semua berdasar aturan
    tetap (acuan WHO/Kemenkes yang udah dipakai di seluruh app ini).

    PENTING: status berat/tinggi/lingkar kepala dihitung pakai usia PAS
    TANGGAL PENGUKURAN diambil (bukan usia hari ini) — biar konsisten sama
    baris yang sama di tabel "Riwayat Pengukuran". Kalau measurement_age
    dan usia hari ini beda (pengukuran terakhir bukan hari ini), pakai
    age_months (hari ini) di sini bisa geser hasil status karena z-score
    WHO sensitif terhadap usia dalam hitungan hari.
    """
    measurement_age = None
    if latest_measurement:
        measurement_age = (latest_measurement.measured_date - child.birth_date).days / 30.4375

    items = []

    if latest_measurement and latest_measurement.weight_kg:
        ev = evaluate_measurement("weight", latest_measurement.weight_kg, child.gender, measurement_age)
        ok = ev and _is_zscore_normal(ev["z_score"])
        items.append((ok, "Berat sesuai kurva WHO" if ok else "Berat di luar rentang normal kurva WHO"))
    else:
        items.append((None, "Belum ada data berat badan"))

    if latest_measurement and latest_measurement.height_cm:
        ev = evaluate_measurement("height", latest_measurement.height_cm, child.gender, measurement_age)
        ok = ev and _is_zscore_normal(ev["z_score"])
        items.append((ok, "Tinggi sesuai kurva WHO" if ok else "Tinggi di luar rentang normal kurva WHO"))
    else:
        items.append((None, "Belum ada data tinggi badan"))

    if latest_measurement and latest_measurement.head_circumference_cm:
        ev = evaluate_measurement("head_circumference", latest_measurement.head_circumference_cm,
                                   child.gender, measurement_age)
        ok = ev and _is_zscore_normal(ev["z_score"])
        items.append((ok, "Lingkar kepala normal" if ok else "Lingkar kepala di luar rentang normal"))
    else:
        items.append((None, "Belum ada data lingkar kepala"))

    items.append((vax_given == vax_total, f"{vax_given} dari {vax_total} vaksin wajib telah diberikan"))
    items.append((illness_count == 0, "Tidak ada riwayat sakit" if illness_count == 0
                  else f"Tercatat {illness_count} riwayat sakit"))
    items.append((visit_count == 0, "Belum ada kunjungan dokter" if visit_count == 0
                  else f"Tercatat {visit_count} kunjungan dokter"))

    return items


def _build_auto_insights(child, measurements, age_months, vax_overdue_count, illness_count):
    """
    Insight naratif di akhir laporan — semua rule-based dari data yang ada,
    BUKAN dikarang/AI-generated. Kalimat dipilih dari kondisi data yang
    beneran terdeteksi.
    """
    insights = []

    # tren berat badan: bandingin 2 pengukuran terakhir
    weighted = [m for m in measurements if m.weight_kg]
    if len(weighted) >= 2:
        prev, latest = weighted[-2], weighted[-1]
        if latest.weight_kg < prev.weight_kg:
            insights.append(
                f"! Berat badan turun dari {prev.weight_kg} kg ({prev.measured_date.strftime('%d %b')}) "
                f"ke {latest.weight_kg} kg ({latest.measured_date.strftime('%d %b')}) — sebaiknya konsultasi "
                f"ke tenaga kesehatan."
            )
        else:
            insights.append("\u2713 Tidak ditemukan penurunan berat badan antar pengukuran terakhir.")
    if weighted:
        latest_w = weighted[-1]
        latest_w_age = (latest_w.measured_date - child.birth_date).days / 30.4375
        ev = evaluate_measurement("weight", latest_w.weight_kg, child.gender, latest_w_age)
        if ev and _is_zscore_normal(ev["z_score"]):
            insights.append("\u2713 Berat badan mengikuti kurva pertumbuhan WHO.")
        elif ev:
            insights.append(f"! Berat badan saat ini berstatus '{ev['status']}' menurut kurva WHO.")

    if vax_overdue_count == 0:
        insights.append("\u2713 Jadwal imunisasi berjalan sesuai rekomendasi, tidak ada yang tertunda.")
    else:
        insights.append(f"! Ada {vax_overdue_count} vaksin wajib yang sudah jatuh tempo tapi belum tercatat diberikan.")

    if illness_count == 0:
        insights.append("\u2713 Tidak ada riwayat penyakit yang tercatat pada periode pemantauan.")
    else:
        insights.append(f"i Tercatat {illness_count} riwayat sakit — lihat detail di bagian riwayat kesehatan.")

    return insights


# ============================================================
#  GRAFIK PERTUMBUHAN — digambar manual pakai reportlab.graphics,
#  garis oranye = data anak, garis putus-putus abu = median WHO
# ============================================================

def _build_growth_chart(measurements, who_median_points, field, width_pt, height_pt, unit):
    points_actual = [
        (round((m.measured_date - m._birth_date_ref).days / 30.4375, 1), getattr(m, field))
        for m in measurements if getattr(m, field) is not None
    ]
    if len(points_actual) < 1:
        return None

    d = Drawing(width_pt, height_pt)
    margin_left, margin_bottom, margin_top, margin_right = 32, 22, 12, 8
    plot_w = width_pt - margin_left - margin_right
    plot_h = height_pt - margin_top - margin_bottom

    all_points = points_actual + who_median_points
    ages = [p[0] for p in all_points]
    values = [p[1] for p in all_points]
    x_min, x_max = min(ages), max(ages)
    y_min, y_max = min(values) * 0.9, max(values) * 1.1
    if x_max == x_min:
        x_max = x_min + 1
    if y_max == y_min:
        y_max = y_min + 1

    def sx(age):
        return margin_left + (age - x_min) / (x_max - x_min) * plot_w

    def sy(val):
        return margin_bottom + (val - y_min) / (y_max - y_min) * plot_h

    d.add(Line(margin_left, margin_bottom, margin_left, height_pt - margin_top, strokeColor=COLOR_MUTED))
    d.add(Line(margin_left, margin_bottom, width_pt - margin_right, margin_bottom, strokeColor=COLOR_MUTED))
    d.add(String(2, margin_bottom - 3, f"{y_min:.1f}", fontSize=6, fillColor=colors.grey))
    d.add(String(2, height_pt - margin_top - 3, f"{y_max:.1f}{unit}", fontSize=6, fillColor=colors.grey))

    who_sorted = sorted(who_median_points, key=lambda p: p[0])
    for i in range(len(who_sorted) - 1):
        x1, y1 = sx(who_sorted[i][0]), sy(who_sorted[i][1])
        x2, y2 = sx(who_sorted[i + 1][0]), sy(who_sorted[i + 1][1])
        line = Line(x1, y1, x2, y2, strokeColor=COLOR_MUTED, strokeWidth=1)
        line.strokeDashArray = [3, 2]
        d.add(line)

    actual_sorted = sorted(points_actual, key=lambda p: p[0])
    for i in range(len(actual_sorted) - 1):
        x1, y1 = sx(actual_sorted[i][0]), sy(actual_sorted[i][1])
        x2, y2 = sx(actual_sorted[i + 1][0]), sy(actual_sorted[i + 1][1])
        d.add(Line(x1, y1, x2, y2, strokeColor=COLOR_ACCENT, strokeWidth=2))
    for age, val in actual_sorted:
        x, y = sx(age), sy(val)
        d.add(Rect(x - 2, y - 2, 4, 4, fillColor=COLOR_ACCENT, strokeColor=None))

    step = max(1, len(actual_sorted) // 6)
    for i, (age, val) in enumerate(actual_sorted):
        if i % step == 0 or i == len(actual_sorted) - 1:
            d.add(String(sx(age) - 6, margin_bottom - 12, f"{age:.0f}bl", fontSize=6, fillColor=colors.grey))

    return d


def _who_median_points(measurement_type, gender, max_age_months):
    refs = (
        GrowthReference.query.filter(
            GrowthReference.measurement_type == measurement_type,
            GrowthReference.gender == gender,
            GrowthReference.age_months <= max_age_months + 1,
        )
        .order_by(GrowthReference.age_months.asc())
        .all()
    )
    return [(r.age_months, r.M) for r in refs]


# ============================================================
#  PROGRESS BAR VAKSIN — digambar manual
# ============================================================

def _build_progress_bar(given, total, width_pt=200, height_pt=14):
    d = Drawing(width_pt, height_pt)
    pct = (given / total) if total else 0
    d.add(Rect(0, 0, width_pt, height_pt, fillColor=colors.HexColor("#F0E2CC"), strokeColor=None))
    fill_color = COLOR_GOOD if pct >= 0.8 else (COLOR_WARN if pct >= 0.4 else COLOR_BAD)
    d.add(Rect(0, 0, width_pt * pct, height_pt, fillColor=fill_color, strokeColor=None))
    return d


# ============================================================
#  ROUTE UTAMA
# ============================================================

@report_bp.route("/children/<int:child_id>/export-pdf", methods=["GET"])
def export_pdf(child_id):
    child = _owned_child(child_id)
    if not child:
        return jsonify({"error": "Anak tidak ditemukan"}), 404

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4,
        topMargin=1.5 * cm, bottomMargin=1.5 * cm,
        leftMargin=1.8 * cm, rightMargin=1.8 * cm,
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle("TitleCustom", parent=styles["Title"], fontSize=18, spaceAfter=2)
    subtitle_style = ParagraphStyle("SubtitleCustom", parent=styles["Normal"], fontSize=10, textColor=colors.grey)
    h2_style = ParagraphStyle("H2Custom", parent=styles["Heading2"], fontSize=13, spaceBefore=16, spaceAfter=6,
                               textColor=COLOR_INK)
    normal_style = styles["Normal"]
    small_style = ParagraphStyle("SmallCustom", parent=styles["Normal"], fontSize=8, textColor=colors.grey)
    checklist_style = ParagraphStyle("Checklist", parent=styles["Normal"], fontSize=10, spaceAfter=3)

    story = []
    today = today_wib()
    age_months = _age_in_months(child.birth_date)

    # ---------- data pendukung, diambil di awal biar bisa dipakai di beberapa section ----------
    measurements = (
        GrowthMeasurement.query.filter_by(child_id=child_id)
        .order_by(GrowthMeasurement.measured_date.asc())
        .all()
    )
    for m in measurements:
        m._birth_date_ref = child.birth_date  # dipakai _build_growth_chart hitung usia per titik

    latest_measurement = measurements[-1] if measurements else None

    schedule = VaccineSchedule.query.filter_by(category="wajib").order_by(VaccineSchedule.order_index.asc()).all()
    given_map = {cv.vaccine_schedule_id: cv for cv in ChildVaccination.query.filter_by(child_id=child_id).all()}
    vax_given = sum(1 for cv in given_map.values() if cv.given)
    vax_total = len(schedule)

    all_vax_list = _build_vaccination_list(child, age_months)
    vax_overdue = [v for v in all_vax_list if v["category"] == "wajib" and not v["given"] and v["due"]]

    illnesses = IllnessLog.query.filter_by(child_id=child_id).order_by(IllnessLog.start_date.desc()).all()
    visits = DoctorVisitLog.query.filter_by(child_id=child_id).order_by(DoctorVisitLog.visit_date.desc()).all()
    milestones = MilestoneLog.query.filter_by(child_id=child_id).order_by(MilestoneLog.achieved_date.asc()).all()

    # ---------- HEADER ----------
    story.append(Paragraph("Laporan Kesehatan Anak", title_style))
    story.append(Paragraph(f"Dicetak {today.strftime('%d %B %Y')} \u2014 Baby Daily Tracker", subtitle_style))
    story.append(Spacer(1, 12))
    story.append(HRFlowable(width="100%", thickness=1, color=COLOR_MUTED))
    story.append(Spacer(1, 12))

    # ---------- DATA ANAK ----------
    story.append(Paragraph("Data Anak", h2_style))
    gender_label = "Laki-laki" if child.gender == "L" else "Perempuan" if child.gender == "P" else "-"
    info_data = [
        ["Nama", child.nickname or child.name],
        ["Tanggal Lahir", child.birth_date.strftime("%d %B %Y")],
        ["Usia Saat Ini", _age_str(child.birth_date, today)],
        ["Jenis Kelamin", gender_label],
        ["Berat Lahir", f"{child.birth_weight_kg} kg" if child.birth_weight_kg else "-"],
        ["Tinggi Lahir", f"{child.birth_height_cm} cm" if child.birth_height_cm else "-"],
    ]
    info_table = Table(info_data, colWidths=[4 * cm, 10 * cm])
    info_table.setStyle(TableStyle([
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("TEXTCOLOR", (0, 0), (0, -1), colors.grey),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(info_table)

    # ---------- 1. RINGKASAN ----------
    story.append(Paragraph("Ringkasan", h2_style))
    checklist = _build_summary_checklist(
        child, latest_measurement, age_months, vax_given, vax_total, len(illnesses), len(visits)
    )
    for ok, text in checklist:
        if ok is True:
            mark, color = "\u2713", COLOR_GOOD
        elif ok is False:
            mark, color = "\u2717", COLOR_WARN
        else:
            mark, color = "\u2013", colors.grey
        story.append(Paragraph(
            f'<font color="{color.hexval()}"><b>{mark}</b></font> {text}', checklist_style
        ))
    story.append(Spacer(1, 4))

    # ---------- 4. STATISTIK PERTUMBUHAN SEJAK LAHIR ----------
    if len(measurements) >= 1:
        story.append(Paragraph("Statistik Sejak Lahir", h2_style))
        stat_cells = []
        if child.birth_weight_kg and latest_measurement and latest_measurement.weight_kg:
            delta_w = round(latest_measurement.weight_kg - child.birth_weight_kg, 2)
            stat_cells.append(["Berat", f"+{delta_w} kg" if delta_w >= 0 else f"{delta_w} kg"])
        if child.birth_height_cm and latest_measurement and latest_measurement.height_cm:
            delta_h = round(latest_measurement.height_cm - child.birth_height_cm, 1)
            stat_cells.append(["Tinggi", f"+{delta_h} cm" if delta_h >= 0 else f"{delta_h} cm"])
        if latest_measurement and latest_measurement.head_circumference_cm:
            stat_cells.append(["Lingkar Kepala Terkini", f"{latest_measurement.head_circumference_cm} cm"])
        if stat_cells:
            stat_table = Table(stat_cells, colWidths=[6 * cm, 6 * cm])
            stat_table.setStyle(TableStyle([
                ("FONTSIZE", (0, 0), (-1, -1), 10),
                ("FONTNAME", (1, 0), (1, -1), "Helvetica-Bold"),
                ("TEXTCOLOR", (1, 0), (1, -1), COLOR_ACCENT),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]))
            story.append(stat_table)

    # ---------- 2. GRAFIK PERTUMBUHAN ----------
    if len(measurements) >= 2:
        story.append(Paragraph("Grafik Pertumbuhan (dibanding median WHO)", h2_style))
        max_age = age_months
        chart_specs = [("weight_kg", "Berat (kg)", "kg"), ("height_cm", "Tinggi (cm)", "cm")]
        for field, label, unit in chart_specs:
            who_type = "weight" if field == "weight_kg" else "height"
            who_points = _who_median_points(who_type, child.gender, max_age)
            chart = _build_growth_chart(measurements, who_points, field, 480, 130, unit)
            if chart:
                story.append(Paragraph(label, ParagraphStyle("ChartLabel", parent=normal_style, fontSize=9,
                                                               textColor=colors.grey, spaceBefore=6)))
                story.append(chart)
        story.append(Paragraph(
            "<font color='#FFA733'>\u2014</font> Data anak &nbsp;&nbsp; "
            "<font color='#C7BAA9'>- - -</font> Median WHO (P50)",
            small_style,
        ))

    # ---------- Riwayat Pertumbuhan (tabel, dengan warna status) ----------
    story.append(Paragraph("Riwayat Pengukuran", h2_style))
    if not measurements:
        story.append(Paragraph("Belum ada data pengukuran tercatat.", normal_style))
    else:
        rows = [["Tanggal", "Berat", "Tinggi", "Lingkar Kepala", "Status Berat"]]
        row_colors = []
        for m in measurements:
            m_age = (m.measured_date - child.birth_date).days / 30.4375
            weight_status = ""
            dot_color = None
            if m.weight_kg:
                ev = evaluate_measurement("weight", m.weight_kg, child.gender, m_age)
                if ev:
                    weight_status = ev["status"]
                    _, dot_color = _status_dot(ev["z_score"])
            rows.append([
                m.measured_date.strftime("%d/%m/%Y"),
                f"{m.weight_kg} kg" if m.weight_kg else "-",
                f"{m.height_cm} cm" if m.height_cm else "-",
                f"{m.head_circumference_cm} cm" if m.head_circumference_cm else "-",
                weight_status,
            ])
            row_colors.append(dot_color)
        growth_table = Table(rows, colWidths=[2.5 * cm, 2.3 * cm, 2.3 * cm, 3 * cm, 4 * cm], repeatRows=1)
        style_cmds = [
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#FFF1DE")),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("GRID", (0, 0), (-1, -1), 0.5, COLOR_MUTED),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
        ]
        for i, c in enumerate(row_colors, start=1):
            if c:
                style_cmds.append(("TEXTCOLOR", (4, i), (4, i), c))
        growth_table.setStyle(TableStyle(style_cmds))
        story.append(growth_table)

    # ---------- 5. VAKSIN BERIKUTNYA ----------
    story.append(Paragraph("Vaksin Berikutnya", h2_style))
    wajib_not_given = [v for v in all_vax_list if v["category"] == "wajib" and not v["given"]]
    if not wajib_not_given:
        box_text = "Semua vaksin wajib sudah tercatat lengkap."
        box_color = COLOR_GOOD
    else:
        overdue_list = [v for v in wajib_not_given if v["due"]]
        target = min(overdue_list, key=lambda v: v["recommended_age_months"]) if overdue_list else \
            min(wajib_not_given, key=lambda v: v["recommended_age_months"])
        est_date = _add_months(child.birth_date, target["recommended_age_months"])
        is_overdue = bool(overdue_list)
        box_color = COLOR_BAD if is_overdue else COLOR_WARN
        status_word = "Sudah jatuh tempo" if is_overdue else "Akan datang"
        box_text = (
            f"<b>{target['vaccine_name']}</b><br/>Usia rekomendasi: {target['recommended_age_months']} bulan"
            f"<br/>Perkiraan: {est_date.strftime('%d %B %Y')} &mdash; <font color='{box_color.hexval()}'>{status_word}</font>"
        )
    box_table = Table([[Paragraph(box_text, ParagraphStyle("Box", parent=normal_style, fontSize=10))]],
                       colWidths=[16.2 * cm])
    box_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#FFF8F0")),
        ("BOX", (0, 0), (-1, -1), 1, box_color),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
    ]))
    story.append(box_table)
    story.append(Spacer(1, 8))

    # ---------- 3. STATUS VAKSINASI + PROGRESS BAR ----------
    story.append(Paragraph("Status Vaksinasi Wajib (Kemenkes)", h2_style))
    pct = round((vax_given / vax_total) * 100) if vax_total else 0
    progress_row = Table(
        [[_build_progress_bar(vax_given, vax_total, width_pt=300, height_pt=12),
          Paragraph(f"<b>{vax_given} / {vax_total}</b> &nbsp;&nbsp; ({pct}%)",
                    ParagraphStyle("ProgLabel", parent=normal_style, fontSize=10))]],
        colWidths=[8 * cm, 6 * cm],
    )
    progress_row.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE")]))
    story.append(progress_row)
    story.append(Spacer(1, 6))

    rows = [["", "Vaksin", "Usia Rekomendasi", "Status", "Tanggal Diberikan"]]
    row_colors = []
    for v in schedule:
        cv = given_map.get(v.id)
        given = cv.given if cv else False
        status = "Sudah" if given else "Belum"
        dot_color = COLOR_GOOD if given else COLOR_BAD
        date_str = cv.given_date.strftime("%d/%m/%Y") if (cv and cv.given_date) else "-"
        rows.append(["\u25CF", v.vaccine_name, f"{v.recommended_age_months} bulan", status, date_str])
        row_colors.append(dot_color)
    vax_table = Table(rows, colWidths=[0.6 * cm, 5.4 * cm, 3.3 * cm, 2.2 * cm, 3 * cm], repeatRows=1)
    style_cmds = [
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#FFF1DE")),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("GRID", (0, 0), (-1, -1), 0.5, COLOR_MUTED),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
    ]
    for i, c in enumerate(row_colors, start=1):
        style_cmds.append(("TEXTCOLOR", (0, i), (0, i), c))
    vax_table.setStyle(TableStyle(style_cmds))
    story.append(vax_table)

    # ---------- Riwayat Kunjungan Dokter ----------
    story.append(Paragraph("Riwayat Kunjungan Dokter", h2_style))
    if not visits:
        story.append(Paragraph("Belum ada catatan kunjungan dokter.", normal_style))
    else:
        rows = [["Tanggal", "Dokter/Klinik", "Keluhan", "Diagnosis"]]
        for v in visits[:10]:
            rows.append([
                v.visit_date.strftime("%d/%m/%Y"), v.doctor_name or v.clinic_name or "-",
                v.reason or "-", v.diagnosis or "-",
            ])
        visit_table = Table(rows, colWidths=[2.3 * cm, 3.5 * cm, 3.8 * cm, 4.9 * cm], repeatRows=1)
        visit_table.setStyle(TableStyle([
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#FFF1DE")),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("GRID", (0, 0), (-1, -1), 0.5, COLOR_MUTED),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
        ]))
        story.append(visit_table)

    # ---------- 6. RIWAYAT SAKIT SEBAGAI TIMELINE ----------
    story.append(Paragraph("Riwayat Sakit", h2_style))
    if not illnesses:
        story.append(Paragraph("Belum ada catatan sakit.", normal_style))
    else:
        for ill in illnesses[:10]:
            duration = ""
            if ill.end_date:
                days = (ill.end_date - ill.start_date).days + 1
                duration = f"{days} hari"
            else:
                duration = "Masih berlangsung"
            detail_parts = [ill.illness_name]
            if ill.symptoms:
                detail_parts.append(ill.symptoms)
            detail_parts.append(duration)
            detail_line = " \u2022 ".join(detail_parts)

            timeline_row = Table(
                [[
                    Paragraph(f"<b>{ill.start_date.strftime('%d %b')}</b>",
                              ParagraphStyle("TDate", parent=normal_style, fontSize=9, textColor=COLOR_ACCENT)),
                    Paragraph(detail_line, ParagraphStyle("TDetail", parent=normal_style, fontSize=9)),
                ]],
                colWidths=[2 * cm, 14.2 * cm],
            )
            timeline_row.setStyle(TableStyle([
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LINEBELOW", (0, 0), (-1, -1), 0.5, colors.HexColor("#F0E2CC")),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
            ]))
            story.append(timeline_row)

    # ---------- 7. MILESTONE ----------
    story.append(Paragraph("Milestone Tumbuh Kembang", h2_style))
    if not milestones:
        story.append(Paragraph("Belum ada momen penting tercatat.", normal_style))
    else:
        for ms in milestones:
            label = ms.custom_label or MILESTONE_REFERENCE.get(ms.milestone_type, {}).get("label", ms.milestone_type)
            ms_age = round((ms.achieved_date - child.birth_date).days / 30.4375, 1)
            story.append(Paragraph(
                f'<font color="{COLOR_GOOD.hexval()}"><b>\u2713</b></font> {label} '
                f'<font color="grey" size="8">&mdash; {ms.achieved_date.strftime("%d %b %Y")} (usia {ms_age} bulan)</font>',
                checklist_style,
            ))

    # ---------- 10. INSIGHT OTOMATIS ----------
    story.append(Paragraph("Insight", h2_style))
    insights = _build_auto_insights(child, measurements, age_months, len(vax_overdue), len(illnesses))
    for line in insights:
        story.append(Paragraph(f"\u2022 {line}", ParagraphStyle("Insight", parent=normal_style, fontSize=9.5, spaceAfter=4)))

    # ---------- 8. FOOTER + QR CODE ----------
    story.append(Spacer(1, 20))
    story.append(HRFlowable(width="100%", thickness=0.5, color=COLOR_MUTED))
    story.append(Spacer(1, 8))

    app_url = os.environ.get("FRONTEND_ORIGIN", "").split(",")[0] or "https://baby-daily-tracker.vercel.app"
    qr_image = _build_qr_image(app_url)
    footer_text = (
        "<b>Generated by Baby Daily Tracker</b><br/>"
        f"{today.strftime('%d %B %Y')}<br/>"
        "Version 1.3.0<br/>"
        f"{app_url}<br/><br/>"
        "Laporan ini dibuat otomatis dari catatan orang tua/wali. Data bukan pengganti rekam medis "
        "resmi \u2014 mohon konfirmasi ke tenaga kesehatan untuk keputusan medis."
    )
    footer_row_data = [[Paragraph(footer_text, small_style)]]
    if qr_image:
        footer_row_data = [[Paragraph(footer_text, small_style), qr_image]]
    footer_table = Table(footer_row_data, colWidths=[13.2 * cm, 3 * cm] if qr_image else [16.2 * cm])
    footer_table.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))
    story.append(footer_table)

    doc.build(story)
    buffer.seek(0)

    filename = f"laporan-{(child.nickname or child.name).replace(' ', '-').lower()}-{today.isoformat()}.pdf"
    return send_file(
        buffer,
        mimetype="application/pdf",
        as_attachment=True,
        download_name=filename,
    )


def _build_qr_image(url):
    """QR code nunjuk ke halaman utama app (BUKAN data anak spesifik — itu
    butuh fitur sharing terpisah yang sengaja belum dibangun karena isu
    privasi, biar nggak sembarang orang yang scan bisa lihat data anak)."""
    try:
        import qrcode
        qr_buffer = io.BytesIO()
        qr = qrcode.QRCode(box_size=4, border=1)
        qr.add_data(url)
        qr.make(fit=True)
        img = qr.make_image(fill_color="#4A3F35", back_color="white")
        img.save(qr_buffer, format="PNG")
        qr_buffer.seek(0)
        return Image(qr_buffer, width=2.2 * cm, height=2.2 * cm)
    except Exception:
        return None