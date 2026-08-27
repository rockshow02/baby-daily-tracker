from io import BytesIO

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer

from utils.pdf_common import BaseStyles, kv_table, safe, safe_multiline


def render_monthly_story_pdf(report, photo_paths):
    output = BytesIO(); styles = BaseStyles()
    doc = SimpleDocTemplate(output, pagesize=A4, leftMargin=1.7*cm, rightMargin=1.7*cm,
                            topMargin=1.5*cm, bottomMargin=1.5*cm)
    story = [Paragraph(f"Cerita Bulanan {safe(report['child']['display_name'])}", styles.title),
             Paragraph(safe(report["month"]), styles.subtitle), Spacer(1, 12)]
    counts = report["counts"]; previous = report["previous_counts"]
    story += [Paragraph("Sorotan bulan ini", styles.h2), kv_table([
        ("Foto kenangan", counts["photos"]), ("Momen penting", counts["milestones"]),
        ("Vaksinasi", counts["vaccinations"]),
        ("Momen bulan sebelumnya", previous["milestones"]),
    ], styles)]
    if report["milestones"]:
        story.append(Paragraph("Pencapaian", styles.h2))
        for item in report["milestones"]:
            story.append(Paragraph(f"{safe(item['date'])} — {safe(item['label'])}", styles.normal))
    if report["growth"]:
        story.append(Paragraph("Pertumbuhan", styles.h2))
        for item in report["growth"]:
            values = [f"{item['weight_kg']} kg" if item["weight_kg"] is not None else None,
                      f"{item['height_cm']} cm" if item["height_cm"] is not None else None]
            story.append(Paragraph(f"{safe(item['date'])} — {safe(' · '.join(x for x in values if x) or '-')}", styles.normal))
    if report["selected_photos"]:
        story.append(Paragraph("Kenangan pilihan", styles.h2))
        for item in report["selected_photos"]:
            path = photo_paths.get(item["id"])
            if path:
                image = Image(str(path), width=8*cm, height=6*cm, kind="proportional")
                story += [image, Paragraph(safe(item.get("caption") or "Momen berharga"), styles.small), Spacer(1, 8)]
    if report.get("parent_note"):
        story += [Paragraph("Catatan orang tua", styles.h2), Paragraph(safe_multiline(report["parent_note"]), styles.normal)]
    story += [Spacer(1, 16), Paragraph(safe(report["disclaimer"]), styles.disclaimer)]
    doc.build(story); output.seek(0); return output
