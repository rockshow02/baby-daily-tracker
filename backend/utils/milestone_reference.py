"""
Acuan rentang usia normal pencapaian momen tumbuh kembang.
Sumber: IDAI, ADA (American Dental Association), dan literatur tumbuh kembang
anak umum (KPSP Kemenkes memakai prinsip skrining serupa: bandingkan usia
pencapaian anak dengan rentang tipikal, bukan angka tunggal).
"""

MILESTONE_REFERENCE = {
    "bisa_duduk": {
        "label": "Bisa Duduk Sendiri",
        "typical_min_months": 6,
        "typical_max_months": 8,
        "concern_after_months": 10,
    },
    "langkah_pertama": {
        "label": "Langkah Pertama",
        "typical_min_months": 9,
        "typical_max_months": 12,
        "concern_after_months": 18,
    },
    "kata_pertama": {
        "label": "Kata Pertama",
        "typical_min_months": 9,
        "typical_max_months": 14,
        "concern_after_months": 18,
    },
    "gigi_pertama": {
        "label": "Gigi Pertama",
        "typical_min_months": 3,
        "typical_max_months": 12,
        "concern_after_months": 12,
    },
}


def evaluate_milestone(milestone_type, age_months):
    ref = MILESTONE_REFERENCE.get(milestone_type)
    if not ref:
        return None  # milestone custom, tidak ada acuan

    if age_months < ref["typical_min_months"]:
        status = "Lebih awal dari umumnya"
    elif age_months <= ref["typical_max_months"]:
        status = "Sesuai rentang umumnya"
    elif age_months <= ref["concern_after_months"]:
        status = "Sedikit lebih lambat dari umumnya (masih wajar)"
    else:
        status = "Terlambat dari umumnya — baiknya diskusikan ke dokter anak"

    return {
        "status": status,
        "typical_range": f"{ref['typical_min_months']}-{ref['typical_max_months']} bulan",
    }