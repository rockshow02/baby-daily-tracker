import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from extensions import db
from models import WakeWindowGuideline

# acuan umum konsensus pediatric sleep — makin besar usia, makin lama bisa
# terjaga sebelum butuh tidur lagi. Rentang (bukan angka pasti) karena tiap
# bayi beda-beda, tujuannya kasih GAMBARAN, bukan aturan kaku.
GUIDELINES = [
    {"age_min_days": 0, "age_max_days": 30, "label": "0-1 bulan", "min_wake_minutes": 45, "max_wake_minutes": 60},
    {"age_min_days": 31, "age_max_days": 60, "label": "1-2 bulan", "min_wake_minutes": 60, "max_wake_minutes": 90},
    {"age_min_days": 61, "age_max_days": 90, "label": "2-3 bulan", "min_wake_minutes": 75, "max_wake_minutes": 105},
    {"age_min_days": 91, "age_max_days": 120, "label": "3-4 bulan", "min_wake_minutes": 90, "max_wake_minutes": 120},
    {"age_min_days": 121, "age_max_days": 180, "label": "4-6 bulan", "min_wake_minutes": 120, "max_wake_minutes": 150},
    {"age_min_days": 181, "age_max_days": 270, "label": "6-9 bulan", "min_wake_minutes": 150, "max_wake_minutes": 180},
    {"age_min_days": 271, "age_max_days": 365, "label": "9-12 bulan", "min_wake_minutes": 180, "max_wake_minutes": 240},
    {"age_min_days": 366, "age_max_days": 545, "label": "12-18 bulan", "min_wake_minutes": 240, "max_wake_minutes": 300},
    {"age_min_days": 546, "age_max_days": 730, "label": "18-24 bulan", "min_wake_minutes": 300, "max_wake_minutes": 360},
]


def seed():
    app = create_app()
    with app.app_context():
        existing = WakeWindowGuideline.query.count()
        if existing > 0:
            print(f"Sudah ada {existing} acuan wake window, dihapus dulu biar nggak dobel...")
            WakeWindowGuideline.query.delete()
            db.session.commit()

        for item in GUIDELINES:
            db.session.add(WakeWindowGuideline(**item))
        db.session.commit()
        print(f"Berhasil seed {len(GUIDELINES)} acuan wake window.")


if __name__ == "__main__":
    seed()