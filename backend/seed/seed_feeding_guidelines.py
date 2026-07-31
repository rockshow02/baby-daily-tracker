"""
Seed tabel feeding_guidelines.
Angka bersumber dari IDAI (menyusui, BAK/BAB) dan konsensus AAP/National
Sleep Foundation (durasi tidur) — dicek Juli 2026.

Jalankan: python seed/seed_feeding_guidelines.py
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app import create_app
from extensions import db
from models import FeedingGuideline

GUIDELINES = [
    {
        "label": "0-1 bulan (minggu pertama)",
        "age_min_days": 0,
        "age_max_days": 30,
        "min_feeds_per_day": 8,
        "max_feeds_per_day": 12,
        "min_sleep_hours": 14,
        "max_sleep_hours": 17,
        "min_wet_diapers": 6,
        "min_bab_per_day": 4,
        "notes": (
            "Minggu pertama BAK bertahap: hari 1 minimal 1x, naik ~1x per hari "
            "hingga minimal 6x/hari di hari ke-6. Menyusui sebaiknya on-demand, "
            "bukan dipaksa sesuai jadwal."
        ),
        "source": "IDAI",
    },
    {
        "label": "1-2 bulan",
        "age_min_days": 31,
        "age_max_days": 60,
        "min_feeds_per_day": 7,
        "max_feeds_per_day": 9,
        "min_sleep_hours": 14,
        "max_sleep_hours": 17,
        "min_wet_diapers": 6,
        "min_bab_per_day": None,
        "notes": "Frekuensi BAB mulai sangat bervariasi antar bayi, ini normal.",
        "source": "IDAI",
    },
    {
        "label": "3-5 bulan",
        "age_min_days": 61,
        "age_max_days": 150,
        "min_feeds_per_day": 7,
        "max_feeds_per_day": 8,
        "min_sleep_hours": 12,
        "max_sleep_hours": 16,
        "min_wet_diapers": 6,
        "min_bab_per_day": None,
        "notes": "Rentang waktu antar sesi menyusu sekitar 2,5-3,5 jam.",
        "source": "IDAI/AAP",
    },
    {
        "label": "6-12 bulan (mulai MPASI)",
        "age_min_days": 151,
        "age_max_days": 365,
        "min_feeds_per_day": 4,
        "max_feeds_per_day": 6,
        "min_sleep_hours": 12,
        "max_sleep_hours": 16,
        "min_wet_diapers": 6,
        "min_bab_per_day": None,
        "notes": (
            "ASI/sufor tetap diberikan meski frekuensi menurun karena MPASI. "
            "MPASI dimulai tepat usia 6 bulan, bertahap 2-3x makan + 1-2x snack."
        ),
        "source": "IDAI/Kemenkes",
    },
    {
        "label": "1-2 tahun",
        "age_min_days": 366,
        "age_max_days": 730,
        "min_feeds_per_day": None,
        "max_feeds_per_day": None,
        "min_sleep_hours": 11,
        "max_sleep_hours": 14,
        "min_wet_diapers": None,
        "min_bab_per_day": None,
        "notes": "Fokus pantauan bergeser ke pola makan keluarga (3x makan + 2x snack) dan tidur.",
        "source": "AAP/NSF",
    },
]


def run():
    added = 0
    for g in GUIDELINES:
        exists = FeedingGuideline.query.filter_by(label=g["label"]).first()
        if exists:
            continue
        db.session.add(FeedingGuideline(**g))
        added += 1
    db.session.commit()
    print(f"Seeded {added} feeding guidelines baru (total definisi: {len(GUIDELINES)}).")


if __name__ == "__main__":
    app = create_app()
    with app.app_context():
        run()
