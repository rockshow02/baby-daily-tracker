from models import FeedingGuideline


def get_age_in_days(birth_date, on_date) -> int:
    return (on_date - birth_date).days


def get_guideline_for_age(age_days: int):
    return (
        FeedingGuideline.query.filter(
            FeedingGuideline.age_min_days <= age_days,
            FeedingGuideline.age_max_days >= age_days,
        )
        .first()
    )


def _status(actual, min_val, max_val):
    if actual is None or (min_val is None and max_val is None):
        return None
    if min_val is not None and actual < min_val:
        return "kurang"
    if max_val is not None and actual > max_val:
        return "lebih"
    return "normal"


def build_daily_summary(child, on_date, feeding_count, sleep_hours, wet_diaper_count, bab_count):
    age_days = get_age_in_days(child.birth_date, on_date)
    guideline = get_guideline_for_age(age_days)

    if not guideline:
        return {
            "age_days": age_days,
            "guideline": None,
            "message": "Belum ada acuan untuk usia ini (di luar 0-2 tahun).",
        }

    return {
        "age_days": age_days,
        "guideline_label": guideline.label,
        "source": guideline.source,
        "feeding": {
            "actual": feeding_count,
            "min": guideline.min_feeds_per_day,
            "max": guideline.max_feeds_per_day,
            "status": _status(feeding_count, guideline.min_feeds_per_day, guideline.max_feeds_per_day),
        },
        "sleep": {
            "actual_hours": sleep_hours,
            "min": guideline.min_sleep_hours,
            "max": guideline.max_sleep_hours,
            "status": _status(sleep_hours, guideline.min_sleep_hours, guideline.max_sleep_hours),
        },
        "wet_diaper": {
            "actual": wet_diaper_count,
            "min": guideline.min_wet_diapers,
            "status": _status(wet_diaper_count, guideline.min_wet_diapers, None),
            "note": "Indikator kecukupan ASI (IDAI): minimal 6x/hari sejak usia 6 hari.",
        },
        "bab": {
            "actual": bab_count,
            "min": guideline.min_bab_per_day,
            "status": _status(bab_count, guideline.min_bab_per_day, None) if guideline.min_bab_per_day else None,
            "note": "Frekuensi BAB sangat bervariasi antar bayi, ini hanya panduan umum.",
        },
        "guideline_notes": guideline.notes,
    }
