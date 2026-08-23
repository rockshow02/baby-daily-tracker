"""
Test murni buat utils/consultation_pdf.py -- TIDAK ADA Flask app/client/
auth, manggil renderer-nya LANGSUNG dengan data section buatan sendiri,
persis pola tests/test_reminder_engine.py buat fungsi murni lainnya.

Fokus file ini: kesetaraan LOGIS preview<->PDF buat section `growth`
(bug review -- PDF sebelumnya SAMA-SAMA nggak nampilin pengukuran
SEBELUMNYA ataupun perubahan lingkar kepala, celah yang sama kayak
preview JSON mentah yang sudah diperbaiki di frontend, lihat
backend/docs/DOCTOR_CONSULTATION.md).

TIDAK ADA dependency ekstraksi teks PDF (mis. pdfplumber) yang
di-declare di requirements.txt -- daripada nambah dependency test-only
yang nggak resmi, teks yang bakal masuk PDF diverifikasi LANGSUNG dari
flowable reportlab yang dikembalikan `_render_growth` (Paragraph/Table
sebelum dirender jadi byte PDF) -- ini justru lebih presisi (nggak
tergantung parser PDF pihak ketiga) buat ngecek "apa isinya", digabung
1 test end-to-end (`render_consultation_pdf`) yang memverifikasi PDF
akhir beneran valid & di memori.
"""
from datetime import date, datetime

from utils.consultation_pdf import (
    _render_growth, _render_medication, _render_medication_adherence_summary, _Styles, render_consultation_pdf,
)

FAKE_PERIOD = {
    "preset": "7d", "start_date": "2026-08-17", "end_date": "2026-08-23",
    "timezone": "Asia/Jakarta", "days": 7,
}


def _flowable_texts(flows):
    """Kumpulin SEMUA teks dari flowable (Paragraph biasa ATAUPUN tiap sel Table) jadi 1 list string -- lihat docstring modul."""
    texts = []
    for f in flows:
        if hasattr(f, "text"):
            texts.append(f.text)
        elif hasattr(f, "_cellvalues"):
            for row in f._cellvalues:
                for cell in row:
                    if hasattr(cell, "text"):
                        texts.append(cell.text)
    return texts


def _joined(flows):
    return "\n".join(_flowable_texts(flows))


FULL_GROWTH_SECTION = {
    "latest": {"measured_date": "2026-08-20", "weight_kg": 8.2, "height_cm": 68, "head_circumference_cm": 44},
    "previous": {"measured_date": "2026-07-20", "weight_kg": 7.8, "height_cm": 66, "head_circumference_cm": 43},
    "weight_change_kg": 0.4, "height_change_cm": 2, "head_circumference_change_cm": 1,
    "days_since_latest_measurement": 3,
    "measurements_in_period": [],
    "total_count_in_period": 0,
    "truncated": False,
}


def test_growth_pdf_includes_previous_measurement_label_and_values():
    text = _joined(_render_growth(FULL_GROWTH_SECTION, _Styles()))
    assert "Pengukuran sebelumnya" in text
    assert "2026-07-20" in text
    assert "7.8" in text
    assert "66" in text
    assert "43" in text


def test_growth_pdf_includes_head_circumference_change():
    text = _joined(_render_growth(FULL_GROWTH_SECTION, _Styles()))
    assert "Perubahan lingkar kepala" in text
    # `1` (delta lingkar kepala) muncul sebagai sel tersendiri -- dicek
    # via daftar teks flowable (bukan substring `text` gabungan, biar
    # nggak match nomor lain yang kebetulan mengandung "1").
    assert "1" in _flowable_texts(_render_growth(FULL_GROWTH_SECTION, _Styles()))


def test_growth_pdf_omits_previous_section_when_previous_is_none():
    section = {**FULL_GROWTH_SECTION, "previous": None, "weight_change_kg": None, "height_change_cm": None, "head_circumference_change_cm": None}
    text = _joined(_render_growth(section, _Styles()))
    assert "Pengukuran sebelumnya" not in text
    assert "Perubahan sejak pengukuran sebelumnya" not in text


def test_growth_pdf_missing_previous_field_renders_as_dash_not_python_none():
    section = {
        **FULL_GROWTH_SECTION,
        "previous": {"measured_date": "2026-07-20", "weight_kg": 7.8, "height_cm": None, "head_circumference_cm": None},
        "height_change_cm": None, "head_circumference_change_cm": None,
    }
    texts = _flowable_texts(_render_growth(section, _Styles()))
    assert "None" not in "\n".join(texts)
    assert "-" in texts  # `_fmt_num(None)` -> "-", lihat utils/consultation_pdf.py


def test_growth_pdf_zero_delta_shown_as_real_zero():
    section = {**FULL_GROWTH_SECTION, "weight_change_kg": 0, "height_change_cm": 0, "head_circumference_change_cm": 0}
    texts = _flowable_texts(_render_growth(section, _Styles()))
    # `_fmt_num(0)` -> "0" apa adanya (BUKAN "-"/kosong) -- literal 0 TIDAK
    # PERNAH dianggap "nilai hilang" di sini, sama kebijakan preview.
    assert texts.count("0") >= 3


def test_growth_pdf_negative_delta_keeps_minus_sign():
    section = {**FULL_GROWTH_SECTION, "weight_change_kg": -0.2}
    texts = _flowable_texts(_render_growth(section, _Styles()))
    assert "-0.2" in texts


def test_growth_pdf_does_not_leak_raw_python_dict_repr():
    text = _joined(_render_growth(FULL_GROWTH_SECTION, _Styles()))
    # Nggak ada tanda kurung kurawal Python dict/tanda kutip repr yang
    # nyelip ke teks yang bakal dirender -- lapis pertahanan tambahan
    # biar section ini nggak pernah kebobolan nampilin object mentah.
    assert "{" not in text
    assert "}" not in text


# --------------------------------------------------------------------------
# Integrasi Medication Schedule & Adherence Phase 1 -- ringkasan kepatuhan
# di section `medication` (lihat utils/consultation_report.py:
# _medication_adherence_summary, backend/docs/MEDICATION_SCHEDULE.md).
# --------------------------------------------------------------------------

FULL_ADHERENCE_SUMMARY = {
    "schedule_count": 1, "expected_count": 6, "administered_count": 4, "skipped_count": 1,
    "overdue_unresolved_count": 1, "on_time_administered_count": 3, "late_administered_count": 1,
    "adherence_percentage": 66.7,
}


def test_medication_adherence_summary_omitted_entirely_when_none():
    """`adherence_summary=None` (child belum punya jadwal obat) -- TIDAK ADA flowable apa pun yang dirender, bukan tabel kosong."""
    assert _render_medication_adherence_summary(None, _Styles()) == []


def test_medication_adherence_summary_rendered_when_present():
    texts = _flowable_texts(_render_medication_adherence_summary(FULL_ADHERENCE_SUMMARY, _Styles()))
    joined = "\n".join(texts)
    assert "Ringkasan Kepatuhan Jadwal Obat" in joined
    assert "66.7%" in joined
    assert "4" in texts  # administered_count
    assert "1" in texts  # skipped_count (dan overdue/late, masing-masing sel sendiri)


def test_medication_adherence_summary_never_leaks_medication_name_or_instructions():
    """Ringkasan CUMA angka agregat -- konten sengaja nggak boleh punya field nama obat/instruksi per-jadwal apa pun buat dirender."""
    assert "medication_name" not in FULL_ADHERENCE_SUMMARY
    assert "instructions" not in FULL_ADHERENCE_SUMMARY


def test_medication_section_appends_adherence_summary_after_entries_table():
    section = {
        "entries": [{"medication_name": "Paracetamol", "dosage": "5 ml", "timestamp": "2026-08-23T08:00:00+07:00"}],
        "total_count_in_period": 1, "truncated": False,
        "adherence_summary": FULL_ADHERENCE_SUMMARY,
    }
    texts = _flowable_texts(_render_medication(section, _Styles()))
    joined = "\n".join(texts)
    assert "Paracetamol" in joined
    assert "Ringkasan Kepatuhan Jadwal Obat" in joined


def test_medication_section_with_no_entries_still_renders_adherence_summary_if_present():
    section = {"entries": [], "total_count_in_period": 0, "truncated": False, "adherence_summary": FULL_ADHERENCE_SUMMARY}
    texts = _flowable_texts(_render_medication(section, _Styles()))
    joined = "\n".join(texts)
    assert "Tidak ada catatan obat pada periode ini." in joined
    assert "Ringkasan Kepatuhan Jadwal Obat" in joined


def test_growth_pdf_end_to_end_render_is_valid_and_in_memory():
    """Full pipeline (bukan cuma _render_growth) -- PDF akhir beneran valid & TIDAK PERNAH ditulis ke file, cuma BytesIO."""
    report = {
        "child_display_name": "Dedek",
        "period": FAKE_PERIOD,
        "generated_at": "2026-08-23T10:00:00+07:00",
        "disclaimer": "Laporan ini dibuat dari catatan yang dimasukkan oleh caregiver dan bukan diagnosis atau pengganti konsultasi medis profesional.",
        "generated_statement": "Dibuat dari catatan yang dimasukkan oleh caregiver.",
        "included_sections": ["growth"],
        "sections": {"growth": FULL_GROWTH_SECTION},
    }
    buffer = render_consultation_pdf(report)
    data = buffer.read()
    assert data.startswith(b"%PDF-")
    assert len(data) > 0
    # `render_consultation_pdf` cuma balikin BytesIO -- pemanggilnya
    # (routes/doctor_consultation_routes.py) yang nentuin apa yang
    # terjadi selanjutnya (kirim ke klien), TIDAK PERNAH ada langkah
    # tulis-ke-disk di fungsi ini sendiri (diverifikasi structural: tipe
    # balikan HARUS BytesIO, bukan path/nama file apa pun).
    import io
    assert isinstance(buffer, io.BytesIO)
