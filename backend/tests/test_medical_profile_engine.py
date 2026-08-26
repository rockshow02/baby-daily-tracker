"""
Test murni buat utils/medical_profile_engine.py -- TIDAK ADA Flask app,
TIDAK ADA database, TIDAK ADA client. Lihat juga test_medical_profile.py
buat test level route/integrasi (otorisasi, audit trail, dst).
"""
import pytest

from utils.medical_profile_engine import (
    ALLERGY_TYPES,
    BLOOD_TYPES,
    CONDITION_STATUSES,
    MAX_ALLERGIES,
    MAX_CONDITIONS,
    MedicalProfileValidationError,
    SEVERITY_LEVELS,
    validate_allergies,
    validate_blood_type,
    validate_conditions,
    validate_emergency_instructions,
    validate_medical_profile_payload,
    validate_phone,
)


# --------------------------------------------------------------------------
# validate_blood_type()
# --------------------------------------------------------------------------


@pytest.mark.parametrize("blood_type", BLOOD_TYPES)
def test_validate_blood_type_accepts_every_allowlisted_value(blood_type):
    assert validate_blood_type(blood_type) == blood_type


def test_validate_blood_type_accepts_none_and_empty_string():
    assert validate_blood_type(None) is None
    assert validate_blood_type("") is None


def test_validate_blood_type_rejects_unknown_value():
    with pytest.raises(MedicalProfileValidationError):
        validate_blood_type("Z+")


def test_validate_blood_type_never_infers_from_other_data():
    """Requirement: 'never infer blood type' -- fungsi ini CUMA validasi allowlist, tidak pernah menyimpulkan apa pun."""
    with pytest.raises(MedicalProfileValidationError):
        validate_blood_type("O")  # bukan 'O+'/'O-', TIDAK PERNAH ditebak jadi salah satunya


# --------------------------------------------------------------------------
# validate_allergies()
# --------------------------------------------------------------------------


def test_validate_allergies_accepts_empty_or_none():
    assert validate_allergies(None) == []
    assert validate_allergies([]) == []


@pytest.mark.parametrize("allergy_type", ALLERGY_TYPES)
def test_validate_allergies_accepts_every_allowlisted_type(allergy_type):
    result = validate_allergies([{"type": allergy_type, "allergen": "Kacang"}])
    assert result[0]["type"] == allergy_type


def test_validate_allergies_rejects_unknown_type():
    with pytest.raises(MedicalProfileValidationError):
        validate_allergies([{"type": "bukan_tipe_valid", "allergen": "Kacang"}])


def test_validate_allergies_requires_allergen_name():
    with pytest.raises(MedicalProfileValidationError):
        validate_allergies([{"type": "food", "allergen": ""}])
    with pytest.raises(MedicalProfileValidationError):
        validate_allergies([{"type": "food"}])


@pytest.mark.parametrize("severity", SEVERITY_LEVELS)
def test_validate_allergies_accepts_every_allowlisted_severity(severity):
    result = validate_allergies([{"type": "drug", "allergen": "Amoxicillin", "severity": severity}])
    assert result[0]["severity"] == severity


def test_validate_allergies_rejects_unknown_severity():
    with pytest.raises(MedicalProfileValidationError):
        validate_allergies([{"type": "drug", "allergen": "Amoxicillin", "severity": "sangat_parah"}])


def test_validate_allergies_never_infers_severity_from_reaction():
    """Requirement: 'preserve literal user meaning; do not classify severity automatically'."""
    result = validate_allergies([{
        "type": "food", "allergen": "Kacang", "reaction": "syok anafilaksis parah",  # kedengarannya berat...
    }])
    assert result[0]["severity"] is None  # ...TAPI severity TETAP None, TIDAK PERNAH ditebak dari teks reaksi


def test_validate_allergies_rejects_non_boolean_confirmed_flag():
    with pytest.raises(MedicalProfileValidationError):
        validate_allergies([{"type": "drug", "allergen": "Amoxicillin", "confirmed_by_professional": "yes"}])


def test_validate_allergies_rejects_unexpected_nested_fields():
    with pytest.raises(MedicalProfileValidationError):
        validate_allergies([{"type": "drug", "allergen": "Amoxicillin", "diagnosis": "should not be here"}])


def test_validate_allergies_rejects_non_list():
    with pytest.raises(MedicalProfileValidationError):
        validate_allergies("bukan list")


def test_validate_allergies_rejects_non_dict_entry():
    with pytest.raises(MedicalProfileValidationError):
        validate_allergies(["bukan dict"])


def test_validate_allergies_rejects_excessive_item_count():
    entries = [{"type": "drug", "allergen": f"Obat {i}"} for i in range(MAX_ALLERGIES + 1)]
    with pytest.raises(MedicalProfileValidationError):
        validate_allergies(entries)


def test_validate_allergies_allows_exactly_max_item_count():
    entries = [{"type": "drug", "allergen": f"Obat {i}"} for i in range(MAX_ALLERGIES)]
    assert len(validate_allergies(entries)) == MAX_ALLERGIES


def test_validate_allergies_deduplicates_by_type_and_normalized_allergen():
    result = validate_allergies([
        {"type": "drug", "allergen": "Amoxicillin", "severity": "severe"},
        {"type": "drug", "allergen": "  amoxicillin  ", "severity": "mild"},  # duplikat (beda spasi/huruf besar-kecil) -- entri PERTAMA menang
        {"type": "food", "allergen": "Amoxicillin"},  # tipe beda -- BUKAN duplikat
    ])
    assert len(result) == 2
    drug_entry = next(e for e in result if e["type"] == "drug")
    assert drug_entry["severity"] == "severe"  # entri pertama yang disimpan


def test_validate_allergies_bounds_free_text_fields():
    with pytest.raises(MedicalProfileValidationError):
        validate_allergies([{"type": "drug", "allergen": "x" * 200}])
    with pytest.raises(MedicalProfileValidationError):
        validate_allergies([{"type": "drug", "allergen": "Amoxicillin", "reaction": "x" * 500}])


# --------------------------------------------------------------------------
# validate_conditions()
# --------------------------------------------------------------------------


def test_validate_conditions_accepts_empty_or_none():
    assert validate_conditions(None) == []
    assert validate_conditions([]) == []


def test_validate_conditions_requires_condition_name():
    with pytest.raises(MedicalProfileValidationError):
        validate_conditions([{"condition_name": ""}])


@pytest.mark.parametrize("status", CONDITION_STATUSES)
def test_validate_conditions_accepts_every_allowlisted_status(status):
    result = validate_conditions([{"condition_name": "Asma", "status": status}])
    assert result[0]["status"] == status


def test_validate_conditions_rejects_unknown_status():
    with pytest.raises(MedicalProfileValidationError):
        validate_conditions([{"condition_name": "Asma", "status": "bukan_status_valid"}])


def test_validate_conditions_rejects_non_integer_diagnosed_year():
    with pytest.raises(MedicalProfileValidationError):
        validate_conditions([{"condition_name": "Asma", "diagnosed_year": "2020"}])
    with pytest.raises(MedicalProfileValidationError):
        validate_conditions([{"condition_name": "Asma", "diagnosed_year": True}])  # bool TIDAK PERNAH dianggap int valid di sini


def test_validate_conditions_rejects_out_of_range_diagnosed_year():
    with pytest.raises(MedicalProfileValidationError):
        validate_conditions([{"condition_name": "Asma", "diagnosed_year": 1500}])
    with pytest.raises(MedicalProfileValidationError):
        validate_conditions([{"condition_name": "Asma", "diagnosed_year": 9999}])


def test_validate_conditions_rejects_unexpected_nested_fields():
    with pytest.raises(MedicalProfileValidationError):
        validate_conditions([{"condition_name": "Asma", "severity": "severe"}])


def test_validate_conditions_rejects_excessive_item_count():
    entries = [{"condition_name": f"Kondisi {i}"} for i in range(MAX_CONDITIONS + 1)]
    with pytest.raises(MedicalProfileValidationError):
        validate_conditions(entries)


def test_validate_conditions_deduplicates_by_normalized_name():
    result = validate_conditions([
        {"condition_name": "Asma", "status": "active"},
        {"condition_name": "  asma  ", "status": "resolved"},  # duplikat -- entri PERTAMA menang
    ])
    assert len(result) == 1
    assert result[0]["status"] == "active"


def test_validate_conditions_never_interprets_or_diagnoses():
    """Requirement: 'do not interpret or diagnose the condition' -- nilai apa adanya, tidak pernah diklasifikasi ulang."""
    result = validate_conditions([{"condition_name": "Batuk berkepanjangan", "note": "sudah 3 minggu"}])
    assert result[0]["condition_name"] == "Batuk berkepanjangan"
    assert result[0]["note"] == "sudah 3 minggu"
    assert result[0]["status"] is None


# --------------------------------------------------------------------------
# validate_phone()
# --------------------------------------------------------------------------


def test_validate_phone_accepts_conservative_character_set():
    assert validate_phone("+62 812-3456-7890", "Nomor telepon") == "+62 812-3456-7890"
    assert validate_phone("(021) 555-1234", "Nomor telepon") == "(021) 555-1234"


def test_validate_phone_rejects_letters_and_symbols():
    with pytest.raises(MedicalProfileValidationError):
        validate_phone("call-me-maybe", "Nomor telepon")
    with pytest.raises(MedicalProfileValidationError):
        validate_phone("0812<script>", "Nomor telepon")


def test_validate_phone_normalizes_surrounding_whitespace():
    assert validate_phone("   0812 3456 7890   ", "Nomor telepon") == "0812 3456 7890"


def test_validate_phone_accepts_none():
    assert validate_phone(None, "Nomor telepon") is None


# --------------------------------------------------------------------------
# validate_emergency_instructions()
# --------------------------------------------------------------------------


def test_validate_emergency_instructions_normalizes_crlf():
    result = validate_emergency_instructions("Baris 1\r\nBaris 2\rBaris 3")
    assert result == "Baris 1\nBaris 2\nBaris 3"


def test_validate_emergency_instructions_enforces_length_limit():
    with pytest.raises(MedicalProfileValidationError):
        validate_emergency_instructions("x" * 1001)


def test_validate_emergency_instructions_allows_none():
    assert validate_emergency_instructions(None) is None
    assert validate_emergency_instructions("") is None


def test_validate_emergency_instructions_does_not_strip_meaningful_content():
    result = validate_emergency_instructions("  Hubungi ayah dulu sebelum ke UGD  ")
    assert result == "Hubungi ayah dulu sebelum ke UGD"


# --------------------------------------------------------------------------
# validate_medical_profile_payload() -- validasi gabungan (SATU sumber
# kebenaran dipakai PUT /medical-profile MAUPUN import backup).
# --------------------------------------------------------------------------


def test_validate_medical_profile_payload_rejects_non_dict():
    with pytest.raises(MedicalProfileValidationError):
        validate_medical_profile_payload("bukan dict")


def test_validate_medical_profile_payload_accepts_fully_empty_object():
    result = validate_medical_profile_payload({})
    assert result["blood_type"] is None
    assert result["allergies"] == []
    assert result["conditions"] == []
    assert result["primary_doctor_name"] is None


def test_validate_medical_profile_payload_ignores_unknown_top_level_fields():
    result = validate_medical_profile_payload({"blood_type": "A+", "unexpected_field": "should be ignored"})
    assert result["blood_type"] == "A+"
    assert "unexpected_field" not in result


def test_validate_medical_profile_payload_validates_every_field_together():
    result = validate_medical_profile_payload({
        "blood_type": "O+",
        "allergies": [{"type": "drug", "allergen": "Amoxicillin", "severity": "severe"}],
        "conditions": [{"condition_name": "Asma", "status": "active"}],
        "primary_doctor_name": "dr. Sarah",
        "primary_clinic_name": "Klinik Sehat",
        "primary_clinic_phone": "021-5551234",
        "emergency_contact_name": "Budi",
        "emergency_contact_relationship": "Ayah",
        "emergency_contact_phone": "0812-3456-7890",
        "emergency_instructions": "Hubungi ayah dulu",
    })
    assert result["blood_type"] == "O+"
    assert len(result["allergies"]) == 1
    assert len(result["conditions"]) == 1
    assert result["primary_doctor_name"] == "dr. Sarah"
    assert result["emergency_contact_phone"] == "0812-3456-7890"
