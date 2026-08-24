"""
Helper ReportLab BERSAMA -- gaya visual (warna/tipografi), escaping teks,
dan tabel dasar dipakai `utils/consultation_pdf.py` DAN
`utils/emergency_card_pdf.py` (Child Medical Profile & Emergency Card
Phase 1). SATU sumber kebenaran styling/keamanan teks PDF di app ini --
BUKAN 2 framework PDF yang bersaing, cuma 1 (reportlab, dependency yang
SUDAH ADA sejak routes/report_routes.py) dipakai berulang.

KEAMANAN TEKS BEBAS: `reportlab.platypus.Paragraph` menafsirkan
sebagian markup mirip-XML (`<b>`, `<br/>`, dst) di teksnya -- SEMUA
teks yang sumbernya dari caregiver WAJIB lewat `safe()`/`safe_multiline()`
(html.escape) SEBELUM dibungkus Paragraph di mana pun yang memakai
modul ini -- mencegah PDF-markup injection lewat data yang caregiver
ketik sendiri.
"""
import html

from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import Paragraph, Table, TableStyle

COLOR_ACCENT = colors.HexColor("#FFA733")
COLOR_MUTED = colors.HexColor("#C7BAA9")
COLOR_INK = colors.HexColor("#4A3F35")
COLOR_HEADER_BG = colors.HexColor("#FFF1DE")
COLOR_WARN_BG = colors.HexColor("#FDEBEB")
COLOR_WARN = colors.HexColor("#B3402A")


def safe(value):
    """Escape teks sumber-caregiver SEBELUM masuk Paragraph. `None`/kosong -> '-'."""
    if value is None or value == "":
        return "-"
    return html.escape(str(value), quote=False)


def safe_multiline(value):
    """Sama seperti `safe`, TAPI newline diubah jadi `<br/>` SETELAH escape -- tag ini yang kita sisipkan sendiri, bukan dari input user, jadi aman."""
    if value is None or value == "":
        return "-"
    return html.escape(str(value), quote=False).replace("\n", "<br/>")


def fmt_num(value, suffix=""):
    if value is None:
        return "-"
    return f"{value}{suffix}"


class BaseStyles:
    def __init__(self):
        base = getSampleStyleSheet()
        self.title = ParagraphStyle("PdfTitle", parent=base["Title"], fontSize=18, spaceAfter=2)
        self.subtitle = ParagraphStyle("PdfSubtitle", parent=base["Normal"], fontSize=10, textColor=colors.grey)
        self.h2 = ParagraphStyle(
            "PdfH2", parent=base["Heading2"], fontSize=13, spaceBefore=14, spaceAfter=6, textColor=COLOR_INK
        )
        self.normal = ParagraphStyle("PdfNormal", parent=base["Normal"], fontSize=9, leading=12)
        self.cell = ParagraphStyle("PdfCell", parent=base["Normal"], fontSize=8, leading=10)
        self.small = ParagraphStyle("PdfSmall", parent=base["Normal"], fontSize=8, textColor=colors.grey, leading=11)
        self.disclaimer = ParagraphStyle(
            "PdfDisclaimer", parent=base["Normal"], fontSize=9, leading=12, textColor=COLOR_INK
        )
        self.warn = ParagraphStyle(
            "PdfWarn", parent=base["Normal"], fontSize=9, leading=12, textColor=COLOR_WARN
        )


def kv_table(rows, styles, col_widths=(5.5 * cm, 10.5 * cm)):
    """Tabel 2 kolom label/nilai -- dipakai buat semua section ringkasan (bukan daftar baris)."""
    data = [[Paragraph(f"<b>{safe(k)}</b>", styles.cell), Paragraph(safe(v), styles.cell)] for k, v in rows]
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


def entries_table(header, rows, col_widths, styles):
    """Tabel banyak baris -- SEMUA sel teks bebas lewat Paragraph (auto-wrap, nggak pernah clipped), header berulang tiap halaman baru (`repeatRows=1`)."""
    data = [[Paragraph(f"<b>{safe(h)}</b>", styles.cell) for h in header]]
    for row in rows:
        data.append([Paragraph(safe(cell), styles.cell) for cell in row])
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
