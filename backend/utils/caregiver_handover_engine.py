"""
Caregiver Handover Summary — Phase 1: validasi murni (TIDAK ADA
Flask/database di sini) — pola SAMA PERSIS
utils/medical_profile_engine.py. SATU-SATUNYA field mutable lewat
POST/PUT adalah `note` (catatan serah-terima bebas-teks, OPSIONAL).
"""
NOTE_MAX_LEN = 1000


class HandoverValidationError(ValueError):
    """Input handover nggak valid -- route menangkap ini, balas 400."""

    def __init__(self, message):
        super().__init__(message)
        self.message = message


def validate_note(raw):
    """
    Teks bebas OPSIONAL -- CRLF dinormalisasi ke LF, di-trim, dibatasi
    panjang ketat. `None`/string kosong (sebelum ATAUPUN sesudah trim)
    -> `None` (belum diisi, BUKAN error). TIDAK PERNAH ditafsirkan
    sebagai HTML/markup di sini -- escaping HTML/PDF-markup jadi
    tanggung jawab pemanggil SAAT dirender (Fase 1 belum ada PDF buat
    fitur ini, TAPI prinsipnya TETAP berlaku, requirement eksplisit),
    pola sama persis questions/additional_note Doctor Consultation.
    """
    if raw is None:
        return None
    if not isinstance(raw, str):
        raise HandoverValidationError("Catatan harus berupa teks")
    normalized = raw.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not normalized:
        return None
    if len(normalized) > NOTE_MAX_LEN:
        raise HandoverValidationError(f"Catatan maksimal {NOTE_MAX_LEN} karakter")
    return normalized
