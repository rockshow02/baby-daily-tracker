"""
Seed tabel vaccine_schedules.

Bagian "wajib": Kementerian Kesehatan RI, ayosehat.kemkes.go.id/1000-hari-pertama-kehidupan/seputar-imunisasi
"Tabel 1. Jadwal Pemberian Imunisasi Bayi dan Baduta" — program pemerintah, gratis di posyandu/puskesmas.

Bagian "tambahan": rekomendasi IDAI (Ikatan Dokter Anak Indonesia) di luar
program pemerintah — umumnya berbayar di klinik/RS, sifatnya dianjurkan
bukan wajib. Dicek Juli 2026.

Jalankan: python seed/seed_vaccine_schedule.py
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app import create_app
from extensions import db
from models import VaccineSchedule

# ---------- WAJIB (program pemerintah, gratis) ----------
WAJIB = [
    {"vaccine_name": "Hepatitis B (HB 0)", "recommended_age_months": 0, "order_index": 1,
     "notes": "Wajib diberikan maksimal 24 jam setelah lahir."},

    {"vaccine_name": "BCG", "recommended_age_months": 1, "order_index": 2,
     "notes": "Sebaiknya sebelum usia 2 bulan; maksimal sampai usia 1 tahun."},
    {"vaccine_name": "Polio Tetes 1 (bOPV 1)", "recommended_age_months": 1, "order_index": 3},

    {"vaccine_name": "DPT-HB-Hib 1", "recommended_age_months": 2, "order_index": 4},
    {"vaccine_name": "Polio Tetes 2 (bOPV 2)", "recommended_age_months": 2, "order_index": 5},
    {"vaccine_name": "PCV 1", "recommended_age_months": 2, "order_index": 6},
    {"vaccine_name": "Rotavirus 1", "recommended_age_months": 2, "order_index": 7},

    {"vaccine_name": "DPT-HB-Hib 2", "recommended_age_months": 3, "order_index": 8},
    {"vaccine_name": "Polio Tetes 3 (bOPV 3)", "recommended_age_months": 3, "order_index": 9},
    {"vaccine_name": "PCV 2", "recommended_age_months": 3, "order_index": 10},
    {"vaccine_name": "Rotavirus 2", "recommended_age_months": 3, "order_index": 11},

    {"vaccine_name": "DPT-HB-Hib 3", "recommended_age_months": 4, "order_index": 12},
    {"vaccine_name": "Polio Tetes 4 (bOPV 4)", "recommended_age_months": 4, "order_index": 13},
    {"vaccine_name": "Polio Suntik (IPV) 1", "recommended_age_months": 4, "order_index": 14},
    {"vaccine_name": "Rotavirus 3", "recommended_age_months": 4, "order_index": 15},

    {"vaccine_name": "Campak Rubela 1 (MR 1)", "recommended_age_months": 9, "order_index": 16},
    {"vaccine_name": "Polio Suntik (IPV) 2", "recommended_age_months": 9, "order_index": 17},

    {"vaccine_name": "Japanese Encephalitis (JE)", "recommended_age_months": 10, "order_index": 18,
     "is_optional": True, "notes": "Hanya untuk wilayah endemis JE."},

    {"vaccine_name": "PCV 3", "recommended_age_months": 12, "order_index": 19},

    {"vaccine_name": "DPT-HB-Hib 4", "recommended_age_months": 18, "order_index": 20},
    {"vaccine_name": "Campak Rubela 2 (MR 2)", "recommended_age_months": 18, "order_index": 21},
]
for v in WAJIB:
    v["category"] = "wajib"
    v["source"] = "Kemenkes RI"


# ---------- TAMBAHAN (rekomendasi IDAI, di luar program pemerintah) ----------
TAMBAHAN = [
    {"vaccine_name": "Influenza 1", "recommended_age_months": 6, "order_index": 100,
     "notes": "Diulang setiap tahun setelah dosis pertama."},

    {"vaccine_name": "Hepatitis A 1", "recommended_age_months": 12, "order_index": 101},
    {"vaccine_name": "Varisela (Cacar Air) 1", "recommended_age_months": 12, "order_index": 102,
     "notes": "Bisa diberikan mulai usia 7 bulan sampai sebelum usia 7 tahun."},

    {"vaccine_name": "Hepatitis A 2", "recommended_age_months": 18, "order_index": 103,
     "notes": "6-12 bulan setelah dosis pertama."},
    {"vaccine_name": "Varisela (Cacar Air) 2", "recommended_age_months": 18, "order_index": 104,
     "notes": "6 minggu - 3 bulan setelah dosis pertama."},

    {"vaccine_name": "Tifoid", "recommended_age_months": 24, "order_index": 105,
     "notes": "Diulang setiap 3 tahun."},

    {"vaccine_name": "Dengue (DBD) 1", "recommended_age_months": 72, "order_index": 106,
     "notes": "Untuk usia 6-16 tahun di wilayah endemis dengue."},
    {"vaccine_name": "Dengue (DBD) 2", "recommended_age_months": 75, "order_index": 107,
     "notes": "3 bulan setelah dosis pertama."},

    {"vaccine_name": "HPV 1", "recommended_age_months": 108, "order_index": 108,
     "notes": "Usia 9-14 tahun, dianjurkan terutama untuk anak perempuan (juga bermanfaat untuk anak laki-laki)."},
    {"vaccine_name": "HPV 2", "recommended_age_months": 114, "order_index": 109,
     "notes": "6-15 bulan setelah dosis pertama."},
]
for v in TAMBAHAN:
    v["category"] = "tambahan"
    v["source"] = "IDAI"

VACCINES = WAJIB + TAMBAHAN


def run():
    added = 0
    for v in VACCINES:
        exists = VaccineSchedule.query.filter_by(
            vaccine_name=v["vaccine_name"], recommended_age_months=v["recommended_age_months"]
        ).first()
        if exists:
            continue
        db.session.add(VaccineSchedule(**v))
        added += 1
    db.session.commit()
    print(f"Seeded {added} vaccine schedule entries baru (total definisi: {len(VACCINES)}).")


if __name__ == "__main__":
    app = create_app()
    with app.app_context():
        run()