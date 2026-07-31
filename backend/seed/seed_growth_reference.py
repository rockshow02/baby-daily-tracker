"""
Seed tabel growth_references dengan data LMS WHO Child Growth Standards.
Sumber data ada di who_growth_data.py (366 baris: 3 jenis ukuran x 2 gender x 61 bulan).

Jalankan: python seed/seed_growth_reference.py
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app import create_app
from extensions import db
from models import GrowthReference
from who_growth_data import WHO_GROWTH_DATA


def run():
    added = 0
    for row in WHO_GROWTH_DATA:
        exists = GrowthReference.query.filter_by(
            measurement_type=row["measurement_type"],
            gender=row["gender"],
            age_months=row["age_months"],
        ).first()
        if exists:
            continue
        db.session.add(GrowthReference(**row))
        added += 1
    db.session.commit()
    print(f"Seeded {added} baris referensi WHO growth standard baru (total definisi: {len(WHO_GROWTH_DATA)}).")


if __name__ == "__main__":
    app = create_app()
    with app.app_context():
        run()