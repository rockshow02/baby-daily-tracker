"""
Child Medical Profile & Emergency Card — Phase 1 (lihat
backend/docs/MEDICAL_PROFILE.md buat kontrak lengkapnya).

Modul MURNI validasi/normalisasi -- TIDAK ADA Flask/database di sini,
gampang dites tanpa app context (pola sama persis
utils/medication_schedule_engine.py). SATU sumber kebenaran validasi,
dipakai routes/medical_profile_routes.py buat PUT profil DAN
routes/backup_routes.py buat import backup -- DUA jalur yang SAMA-SAMA
menyimpan data ini ke `ChildMedicalProfile` HARUS lewat validasi yang
SAMA, bukan aturan yang beda-beda per jalur masuk.

TIDAK PERNAH mendiagnosis/menilai kebenaran medis apa pun -- fungsi di
sini CUMA menegakkan BENTUK data (allowlist, panjang, jumlah item),
TIDAK PERNAH menafsirkan/mengklasifikasikan ARTI medisnya (requirement
eksplisit: "preserve literal user meaning; do not classify severity
automatically", "do not interpret or diagnose the condition").
"""
import re

BLOOD_TYPES = ("A+", "A-", "B+", "B-", "AB+", "AB-", "O+", "O-", "unknown")

ALLERGY_TYPES = ("drug", "food", "other")
SEVERITY_LEVELS = ("mild", "moderate", "severe", "unknown")
CONDITION_STATUSES = ("active", "resolved", "unknown")

# Batas jumlah entri -- mencegah array JSON nggak masuk akal (requirement:
# "reject excessive item counts", "keep strict size and item-count limits").
MAX_ALLERGIES = 30
MAX_CONDITIONS = 30

ALLERGEN_NAME_MAX_LEN = 100
REACTION_MAX_LEN = 300
CONDITION_NAME_MAX_LEN = 100
CONDITION_NOTE_MAX_LEN = 300
DOCTOR_NAME_MAX_LEN = 100
CLINIC_NAME_MAX_LEN = 150
CONTACT_NAME_MAX_LEN = 100
RELATIONSHIP_MAX_LEN = 50
PHONE_MAX_LEN = 30
EMERGENCY_INSTRUCTIONS_MAX_LEN = 1000

# Karakter telepon KONSERVATIF -- angka, spasi, `+` (kode negara), `-`,
# `()` -- TIDAK PERNAH mencoba memverifikasi kepemilikan nomor
# (requirement eksplisit), cuma bentuk yang masuk akal buat nomor
# telepon yang diketik manual.
_PHONE_RE = re.compile(r"^[0-9+\-() ]+$")

# Tahun diagnosis -- rentang masuk akal (bukan validasi medis, cuma
# sanity-check nilai integer yang mustahil, mis. tahun 0 atau 9999).
_MIN_DIAGNOSED_YEAR = 1900
_MAX_DIAGNOSED_YEAR = 2100

CURRENT_MEDICAL_PROFILE_VERSION = 1


class MedicalProfileValidationError(ValueError):
    """Input profil medis nggak valid -- route menangkap ini, balas 400."""

    def __init__(self, message):
        super().__init__(message)
        self.message = message


def _normalize_text(raw, field_name, max_len, required=False):
    if raw is None or raw == "":
        if required:
            raise MedicalProfileValidationError(f"{field_name} wajib diisi")
        return None
    if not isinstance(raw, str):
        raise MedicalProfileValidationError(f"{field_name} harus berupa teks")
    normalized = " ".join(raw.strip().split())  # rapikan spasi berlebih di awal/akhir/tengah
    if not normalized:
        if required:
            raise MedicalProfileValidationError(f"{field_name} wajib diisi")
        return None
    if len(normalized) > max_len:
        raise MedicalProfileValidationError(f"{field_name} maksimal {max_len} karakter")
    return normalized


def validate_blood_type(raw):
    if raw is None or raw == "":
        return None
    if not isinstance(raw, str) or raw not in BLOOD_TYPES:
        raise MedicalProfileValidationError(f"Golongan darah harus salah satu dari: {', '.join(BLOOD_TYPES)}")
    return raw


def validate_phone(raw, field_name):
    normalized = _normalize_text(raw, field_name, PHONE_MAX_LEN)
    if normalized is None:
        return None
    if not _PHONE_RE.match(normalized):
        raise MedicalProfileValidationError(f"{field_name} hanya boleh berisi angka, spasi, +, -, ( dan )")
    return normalized


def validate_doctor_name(raw):
    return _normalize_text(raw, "Nama dokter", DOCTOR_NAME_MAX_LEN)


def validate_clinic_name(raw):
    return _normalize_text(raw, "Nama klinik/rumah sakit", CLINIC_NAME_MAX_LEN)


def validate_contact_name(raw, field_name="Nama kontak darurat"):
    return _normalize_text(raw, field_name, CONTACT_NAME_MAX_LEN)


def validate_relationship(raw):
    return _normalize_text(raw, "Hubungan dengan anak", RELATIONSHIP_MAX_LEN)


def validate_emergency_instructions(raw):
    """
    Teks bebas PLAIN TEXT -- CRLF dinormalisasi ke LF, dibatasi panjang
    ketat, TIDAK PERNAH ditafsirkan sebagai HTML/markup di sini
    (escaping HTML/PDF-markup jadi tanggung jawab pemanggil SAAT
    dirender, sama persis pola questions/additional_note milik Doctor
    Consultation -- lihat utils/consultation_report.py:_normalize_free_text).
    """
    if raw is None or raw == "":
        return None
    if not isinstance(raw, str):
        raise MedicalProfileValidationError("Instruksi darurat harus berupa teks")
    normalized = raw.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not normalized:
        return None
    if len(normalized) > EMERGENCY_INSTRUCTIONS_MAX_LEN:
        raise MedicalProfileValidationError(f"Instruksi darurat maksimal {EMERGENCY_INSTRUCTIONS_MAX_LEN} karakter")
    return normalized


def _allergy_dedup_key(entry):
    return (entry["type"], entry["allergen"].strip().lower())


def validate_allergies(raw):
    """
    List dict TERVALIDASI PENUH, dinormalisasi & di-deduplikasi -- atau
    raise. `None`/`[]` -> `[]` (belum ada alergi tercatat, BUKAN error).

    Setiap entri: `type` (allowlist ketat), `allergen` (wajib, dibatasi
    panjang), `reaction` opsional, `severity` opsional (allowlist,
    TIDAK PERNAH disimpulkan otomatis dari `reaction` -- requirement
    "preserve literal user meaning"), `confirmed_by_professional`
    opsional bool. Field/key di luar 5 ini SELALU ditolak (requirement:
    "reject unexpected nested values") -- JSON arbitrer TIDAK PERNAH
    dipercaya begitu saja.
    """
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise MedicalProfileValidationError("Daftar alergi harus berupa list")
    if len(raw) > MAX_ALLERGIES:
        raise MedicalProfileValidationError(f"Jumlah alergi maksimal {MAX_ALLERGIES} entri")

    _ALLOWED_KEYS = {"type", "allergen", "reaction", "severity", "confirmed_by_professional"}
    result = []
    seen_keys = set()
    for idx, raw_entry in enumerate(raw):
        if not isinstance(raw_entry, dict):
            raise MedicalProfileValidationError(f"Entri alergi ke-{idx + 1} tidak valid")
        unexpected = set(raw_entry.keys()) - _ALLOWED_KEYS
        if unexpected:
            raise MedicalProfileValidationError(f"Entri alergi ke-{idx + 1} berisi field yang tidak dikenal")

        allergy_type = raw_entry.get("type")
        if allergy_type not in ALLERGY_TYPES:
            raise MedicalProfileValidationError(f"Jenis alergi harus salah satu dari: {', '.join(ALLERGY_TYPES)}")

        allergen = _normalize_text(raw_entry.get("allergen"), "Nama alergen", ALLERGEN_NAME_MAX_LEN, required=True)
        reaction = _normalize_text(raw_entry.get("reaction"), "Reaksi alergi", REACTION_MAX_LEN)

        severity = raw_entry.get("severity")
        if severity is not None and severity not in SEVERITY_LEVELS:
            raise MedicalProfileValidationError(f"Tingkat keparahan alergi harus salah satu dari: {', '.join(SEVERITY_LEVELS)}")

        confirmed = raw_entry.get("confirmed_by_professional")
        if confirmed is not None and not isinstance(confirmed, bool):
            raise MedicalProfileValidationError("confirmed_by_professional harus bernilai boolean")

        entry = {
            "type": allergy_type, "allergen": allergen, "reaction": reaction,
            "severity": severity, "confirmed_by_professional": confirmed,
        }
        key = _allergy_dedup_key(entry)
        if key in seen_keys:
            continue  # duplikat (jenis + nama alergen sama, tanpa memandang huruf besar/kecil/spasi) -- entri pertama yang menang
        seen_keys.add(key)
        result.append(entry)

    return result


def validate_conditions(raw):
    """
    List dict TERVALIDASI, DIDEDUPLIKASI berdasar nama kondisi -- atau
    raise. `None`/`[]` -> `[]`. TIDAK PERNAH menafsirkan/mendiagnosis
    kondisinya -- cuma menyimpan APA yang caregiver ketik.
    """
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise MedicalProfileValidationError("Daftar kondisi medis harus berupa list")
    if len(raw) > MAX_CONDITIONS:
        raise MedicalProfileValidationError(f"Jumlah kondisi medis maksimal {MAX_CONDITIONS} entri")

    _ALLOWED_KEYS = {"condition_name", "diagnosed_year", "status", "note"}
    result = []
    seen_names = set()
    for idx, raw_entry in enumerate(raw):
        if not isinstance(raw_entry, dict):
            raise MedicalProfileValidationError(f"Entri kondisi medis ke-{idx + 1} tidak valid")
        unexpected = set(raw_entry.keys()) - _ALLOWED_KEYS
        if unexpected:
            raise MedicalProfileValidationError(f"Entri kondisi medis ke-{idx + 1} berisi field yang tidak dikenal")

        condition_name = _normalize_text(
            raw_entry.get("condition_name"), "Nama kondisi medis", CONDITION_NAME_MAX_LEN, required=True,
        )

        diagnosed_year = raw_entry.get("diagnosed_year")
        if diagnosed_year is not None:
            if isinstance(diagnosed_year, bool) or not isinstance(diagnosed_year, int):
                raise MedicalProfileValidationError("Tahun diagnosis harus berupa angka")
            if not (_MIN_DIAGNOSED_YEAR <= diagnosed_year <= _MAX_DIAGNOSED_YEAR):
                raise MedicalProfileValidationError(f"Tahun diagnosis harus antara {_MIN_DIAGNOSED_YEAR} dan {_MAX_DIAGNOSED_YEAR}")

        status = raw_entry.get("status")
        if status is not None and status not in CONDITION_STATUSES:
            raise MedicalProfileValidationError(f"Status kondisi medis harus salah satu dari: {', '.join(CONDITION_STATUSES)}")

        note = _normalize_text(raw_entry.get("note"), "Catatan kondisi medis", CONDITION_NOTE_MAX_LEN)

        dedup_key = condition_name.strip().lower()
        if dedup_key in seen_names:
            continue  # duplikat nama kondisi (tanpa memandang huruf besar/kecil/spasi) -- entri pertama yang menang
        seen_names.add(dedup_key)
        result.append({
            "condition_name": condition_name, "diagnosed_year": diagnosed_year,
            "status": status, "note": note,
        })

    return result


def validate_medical_profile_payload(data):
    """
    Validasi SELURUH body PUT /medical-profile SEKALIGUS -- dipakai
    SAMA PERSIS oleh routes/medical_profile_routes.py DAN
    routes/backup_routes.py:import_json (requirement: "validate imported
    data with the same rules as the API"). Balikin dict field
    tervalidasi siap disimpan, ATAU raise MedicalProfileValidationError.

    Field top-level di luar yang dikenal SENGAJA diabaikan diam-diam
    (pola KONSISTEN sama seluruh endpoint lain di app ini, lihat
    utils/consultation_report.py:_parse_request_payload).
    """
    if not isinstance(data, dict):
        raise MedicalProfileValidationError("Format data tidak valid")

    return {
        "blood_type": validate_blood_type(data.get("blood_type")),
        "allergies": validate_allergies(data.get("allergies")),
        "conditions": validate_conditions(data.get("conditions")),
        "primary_doctor_name": validate_doctor_name(data.get("primary_doctor_name")),
        "primary_clinic_name": validate_clinic_name(data.get("primary_clinic_name")),
        "primary_clinic_phone": validate_phone(data.get("primary_clinic_phone"), "Nomor telepon klinik"),
        "emergency_contact_name": validate_contact_name(data.get("emergency_contact_name")),
        "emergency_contact_relationship": validate_relationship(data.get("emergency_contact_relationship")),
        "emergency_contact_phone": validate_phone(data.get("emergency_contact_phone"), "Nomor telepon kontak darurat"),
        "emergency_instructions": validate_emergency_instructions(data.get("emergency_instructions")),
    }
