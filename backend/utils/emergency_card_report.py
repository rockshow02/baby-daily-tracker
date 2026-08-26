"""
Child Medical Profile & Emergency Card — Phase 1 (lihat
backend/docs/MEDICAL_PROFILE.md buat kontrak lengkapnya).

Mesin MURNI-DATA -- TIDAK PERNAH mendiagnosis/menyarankan tindakan
medis apa pun, cuma merangkum apa yang caregiver SENDIRI sudah catat
jadi bentuk yang gampang dibaca petugas medis dalam keadaan darurat.
`now` SELALU parameter dari pemanggil (route), modul ini TIDAK PERNAH
memanggil jam sistem sendiri -- pola sama persis utils/consultation_report.py.

SATU fungsi builder (`build_emergency_card_summary`) dipakai DUA
tempat -- Emergency Card berdiri sendiri (routes/medical_profile_routes.py)
DAN section `medical_profile` opsional milik Doctor Consultation
(utils/consultation_report.py) -- SATU sumber kebenaran bentuk data,
BUKAN 2 ringkasan yang bisa beda isi.
"""
from datetime import date, datetime, time

from models import MedicationSchedule
from routes.report_routes import _age_str

DISCLAIMER = (
    "Kartu ini merangkum informasi yang dimasukkan sendiri oleh caregiver dan BUKAN "
    "diagnosis, resep, atau saran pengobatan. Selalu konfirmasi ke tenaga medis yang menangani."
)
PRIVACY_NOTE = (
    "Kartu ini berisi data medis dan kontak yang sangat pribadi -- tunjukkan hanya kepada "
    "tenaga medis atau pihak yang benar-benar membutuhkannya dalam keadaan darurat."
)

BLOOD_TYPE_UNRECORDED_LABEL = "Belum dicatat"
BLOOD_TYPE_LABELS = {
    "A+": "A+", "A-": "A-", "B+": "B+", "B-": "B-",
    "AB+": "AB+", "AB-": "AB-", "O+": "O+", "O-": "O-",
    "unknown": "Tidak diketahui",
}

# Urutan tampil "PENTING dulu" -- SEVERITY_RANK/STATUS_RANK CUMA
# menentukan URUTAN baris (requirement: "severe/important allergies
# first", "important active conditions"), TIDAK PERNAH mengubah/
# menyimpulkan nilai severity/status-nya sendiri (itu tetap literal
# apa adanya dari input caregiver, lihat utils/medical_profile_engine.py).
_SEVERITY_RANK = {"severe": 0, "moderate": 1, "mild": 2, "unknown": 3, None: 4}
_STATUS_RANK = {"active": 0, "unknown": 1, None: 2, "resolved": 3}


def _sorted_allergies(allergies):
    return sorted(allergies, key=lambda a: _SEVERITY_RANK.get(a.get("severity"), 4))


def _sorted_conditions(conditions):
    return sorted(conditions, key=lambda c: _STATUS_RANK.get(c.get("status"), 2))


def _regular_medications(child_id, today):
    """
    Ringkasan obat rutin DIDERIVASI langsung dari `MedicationSchedule`
    yang AKTIF milik anak ini SEKARANG (`is_active=True`, dan tanggal
    `today` masih di dalam rentang `start_date`..`end_date`) -- TIDAK
    PERNAH disalin ke tabel/kolom lain, TIDAK PERNAH menyertakan jadwal
    yang sudah nonaktif/berakhir (requirement eksplisit: "do not
    duplicate current medication logs or medication schedules",
    "deleted/inactive medication schedules" dikecualikan).
    """
    schedules = MedicationSchedule.query.filter(
        MedicationSchedule.child_id == child_id,
        MedicationSchedule.is_active.is_(True),
        MedicationSchedule.start_date <= today,
    ).filter(
        (MedicationSchedule.end_date.is_(None)) | (MedicationSchedule.end_date >= today)
    ).order_by(
        # `id` sebagai tie-breaker SEKUNDER -- 2 jadwal dengan
        # `medication_name` PERSIS sama urutannya TIDAK BOLEH bergantung
        # ke urutan penyimpanan internal SQLite yang tidak dijamin
        # (requirement: "avoid unstable ORM ordering", krusial buat
        # digest snapshot preview->PDF di utils/emergency_card_snapshot.py
        # tetap deterministik antara 2 request yang membaca data SAMA).
        MedicationSchedule.medication_name.asc(), MedicationSchedule.id.asc(),
    ).all()

    result = []
    for s in schedules:
        dose = f"{s.dose_value:g} {s.dose_unit}" if s.dose_value is not None and s.dose_unit else None
        result.append({
            "medication_name": s.medication_name,
            "dose": dose,
            "times_of_day": list(s.times_of_day or []),
        })
    return result


def build_emergency_card_summary(child, profile, now):
    """
    `profile`: `ChildMedicalProfile` instance ATAU `None` (anak ini
    belum pernah mengisi profil medis sama sekali -- SEMUA field medis
    balik kosong/None, `has_profile=False`, BUKAN error). `now`: datetime
    WIB naive, dipakai buat usia SAAT INI dan sebagai `today` batas
    obat rutin yang masih aktif.

    Balikin dict SIAP-render (preview JSON MAUPUN PDF, dua-duanya
    dari fungsi yang SAMA -- kesetaraan logis preview<->PDF, pola sama
    persis utils/consultation_report.py:build_consultation_report).
    """
    today = now.date() if isinstance(now, datetime) else now

    blood_type = profile.blood_type if profile else None
    allergies = _sorted_allergies(list(profile.allergies or [])) if profile else []
    conditions = _sorted_conditions(list(profile.conditions or [])) if profile else []

    return {
        "child_display_name": child.nickname or child.name,
        "birth_date": child.birth_date.isoformat(),
        "age_now": _age_str(child.birth_date, today),
        "blood_type": blood_type,
        "blood_type_label": BLOOD_TYPE_LABELS.get(blood_type, BLOOD_TYPE_UNRECORDED_LABEL),
        "allergies": allergies,
        "conditions": conditions,
        "regular_medications": _regular_medications(child.id, today),
        "primary_doctor_name": profile.primary_doctor_name if profile else None,
        "primary_clinic_name": profile.primary_clinic_name if profile else None,
        "primary_clinic_phone": profile.primary_clinic_phone if profile else None,
        "emergency_contact_name": profile.emergency_contact_name if profile else None,
        "emergency_contact_relationship": profile.emergency_contact_relationship if profile else None,
        "emergency_contact_phone": profile.emergency_contact_phone if profile else None,
        "emergency_instructions": profile.emergency_instructions if profile else None,
        "last_reviewed_at": (
            (profile.last_reviewed_at.isoformat() + "+07:00") if profile and profile.last_reviewed_at else None
        ),
        "last_reviewed_by_name": (
            profile.last_reviewed_by.name if profile and profile.last_reviewed_by else None
        ),
        "has_profile": profile is not None,
        "generated_at": now.isoformat() + "+07:00" if isinstance(now, datetime) else None,
        "disclaimer": DISCLAIMER,
        "privacy_note": PRIVACY_NOTE,
    }
