import io

from flask import Blueprint, jsonify, session, send_file
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable,
)

from models import (
    Child, GrowthMeasurement, VaccineSchedule, ChildVaccination,
    DoctorVisitLog, IllnessLog,
)
from utils.access import get_accessible_child
from utils.timezone_utils import today_wib
from utils.growth_calc import evaluate_measurement

report_bp = Blueprint("report", __name__)


def _owned_child(child_id):
    user_id = session.get("user_id")
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
                               textColor=colors.HexColor("#4A3F35"))
    normal_style = styles["Normal"]
    small_style = ParagraphStyle("SmallCustom", parent=styles["Normal"], fontSize=8, textColor=colors.grey)

    story = []

    # ---------- HEADER ----------
    today = today_wib()
    story.append(Paragraph("Laporan Kesehatan Anak", title_style))
    story.append(Paragraph(f"Dicetak {today.strftime('%d %B %Y')} — Baby Daily Tracker", subtitle_style))
    story.append(Spacer(1, 12))
    story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#F0E2CC")))
    story.append(Spacer(1, 12))

    # ---------- DATA ANAK ----------
    story.append(Paragraph("Data Anak", h2_style))
    gender_label = "Laki-laki" if child.gender == "L" else "Perempuan" if child.gender == "P" else "-"
    info_data = [
        ["Nama", child.name],
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

    # ---------- PERTUMBUHAN ----------
    story.append(Paragraph("Riwayat Pertumbuhan (Acuan WHO)", h2_style))
    measurements = (
        GrowthMeasurement.query.filter_by(child_id=child_id)
        .order_by(GrowthMeasurement.measured_date.asc())
        .all()
    )
    if not measurements:
        story.append(Paragraph("Belum ada data pengukuran tercatat.", normal_style))
    else:
        rows = [["Tanggal", "Berat", "Tinggi", "Lingkar Kepala", "Status Berat"]]
        for m in measurements:
            age_months = (m.measured_date - child.birth_date).days / 30.4375
            weight_status = ""
            if m.weight_kg:
                ev = evaluate_measurement("weight", m.weight_kg, child.gender, age_months)
                weight_status = ev["status"] if ev else ""
            rows.append([
                m.measured_date.strftime("%d/%m/%Y"),
                f"{m.weight_kg} kg" if m.weight_kg else "-",
                f"{m.height_cm} cm" if m.height_cm else "-",
                f"{m.head_circumference_cm} cm" if m.head_circumference_cm else "-",
                weight_status,
            ])
        growth_table = Table(rows, colWidths=[2.5 * cm, 2.3 * cm, 2.3 * cm, 3 * cm, 4 * cm], repeatRows=1)
        growth_table.setStyle(TableStyle([
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#FFF1DE")),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#F0E2CC")),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
        ]))
        story.append(growth_table)

    # ---------- VAKSINASI WAJIB ----------
    story.append(Paragraph("Status Vaksinasi Wajib (Kemenkes)", h2_style))
    schedule = (
        VaccineSchedule.query.filter_by(category="wajib")
        .order_by(VaccineSchedule.order_index.asc())
        .all()
    )
    given_map = {
        cv.vaccine_schedule_id: cv
        for cv in ChildVaccination.query.filter_by(child_id=child_id).all()
    }
    rows = [["Vaksin", "Usia Rekomendasi", "Status", "Tanggal Diberikan"]]
    for v in schedule:
        cv = given_map.get(v.id)
        given = cv.given if cv else False
        status = "Sudah" if given else "Belum"
        date_str = cv.given_date.strftime("%d/%m/%Y") if (cv and cv.given_date) else "-"
        rows.append([v.vaccine_name, f"{v.recommended_age_months} bulan", status, date_str])
    vax_table = Table(rows, colWidths=[6 * cm, 3.3 * cm, 2.2 * cm, 3 * cm], repeatRows=1)
    vax_table.setStyle(TableStyle([
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#FFF1DE")),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#F0E2CC")),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(vax_table)

    given_count = sum(1 for cv in given_map.values() if cv.given)
    story.append(Spacer(1, 4))
    story.append(Paragraph(
        f"<i>{given_count} dari {len(schedule)} vaksin wajib sudah diberikan.</i>", small_style
    ))

    # ---------- RIWAYAT KESEHATAN ----------
    story.append(Paragraph("Riwayat Kunjungan Dokter", h2_style))
    visits = (
        DoctorVisitLog.query.filter_by(child_id=child_id)
        .order_by(DoctorVisitLog.visit_date.desc())
        .limit(10)
        .all()
    )
    if not visits:
        story.append(Paragraph("Belum ada catatan kunjungan dokter.", normal_style))
    else:
        rows = [["Tanggal", "Dokter/Klinik", "Keluhan", "Diagnosis"]]
        for v in visits:
            rows.append([
                v.visit_date.strftime("%d/%m/%Y"),
                v.doctor_name or v.clinic_name or "-",
                v.reason or "-",
                v.diagnosis or "-",
            ])
        visit_table = Table(rows, colWidths=[2.3 * cm, 3.5 * cm, 3.8 * cm, 4.9 * cm], repeatRows=1)
        visit_table.setStyle(TableStyle([
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#FFF1DE")),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#F0E2CC")),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
        ]))
        story.append(visit_table)

    story.append(Paragraph("Riwayat Sakit", h2_style))
    illnesses = (
        IllnessLog.query.filter_by(child_id=child_id)
        .order_by(IllnessLog.start_date.desc())
        .limit(10)
        .all()
    )
    if not illnesses:
        story.append(Paragraph("Belum ada catatan sakit.", normal_style))
    else:
        rows = [["Mulai", "Selesai", "Sakit", "Gejala"]]
        for ill in illnesses:
            rows.append([
                ill.start_date.strftime("%d/%m/%Y"),
                ill.end_date.strftime("%d/%m/%Y") if ill.end_date else "Berlangsung",
                ill.illness_name,
                ill.symptoms or "-",
            ])
        illness_table = Table(rows, colWidths=[2.3 * cm, 2.6 * cm, 3.5 * cm, 6 * cm], repeatRows=1)
        illness_table.setStyle(TableStyle([
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#FFF1DE")),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#F0E2CC")),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
        ]))
        story.append(illness_table)

    # ---------- FOOTER ----------
    story.append(Spacer(1, 20))
    story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#F0E2CC")))
    story.append(Spacer(1, 6))
    story.append(Paragraph(
        "Laporan ini dibuat otomatis dari catatan orang tua/wali di aplikasi Baby Daily Tracker. "
        "Data bukan pengganti rekam medis resmi — mohon konfirmasi ke tenaga kesehatan untuk keputusan medis.",
        small_style,
    ))

    doc.build(story)
    buffer.seek(0)

    filename = f"laporan-{child.name.replace(' ', '-').lower()}-{today.isoformat()}.pdf"
    return send_file(
        buffer,
        mimetype="application/pdf",
        as_attachment=True,
        download_name=filename,
    )