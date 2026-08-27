"""Builder murni untuk Monthly Story; tidak menyimpan snapshot atau PDF."""
import calendar
import hashlib
from datetime import date, datetime, time

from sqlalchemy import func

from extensions import db
from models import (ChildVaccination, GrowthMeasurement, MemoryJournalEntry,
                    MilestoneLog)
from utils.memory_journal_images import validated_journal_path

MAX_NOTE_LENGTH = 1000
MAX_SELECTED_PHOTOS = 4


class MonthlyStoryValidationError(ValueError):
    pass


def parse_month(value, today):
    try:
        year, month = map(int, (value or "").split("-"))
        start = date(year, month, 1)
    except (TypeError, ValueError):
        raise MonthlyStoryValidationError("Bulan harus menggunakan format YYYY-MM")
    if start > today.replace(day=1):
        raise MonthlyStoryValidationError("Cerita untuk bulan mendatang belum dapat dibuat")
    end = date(year, month, calendar.monthrange(year, month)[1])
    previous_end = start.fromordinal(start.toordinal() - 1)
    previous_start = previous_end.replace(day=1)
    return start, end, previous_start, previous_end


def validate_payload(data, today, can_add_note):
    if not isinstance(data, dict):
        raise MonthlyStoryValidationError("Format data tidak valid")
    start, end, previous_start, previous_end = parse_month(data.get("month"), today)
    note = (data.get("parent_note") or "").replace("\r\n", "\n").strip()
    if note and not can_add_note:
        raise PermissionError("Peran Anda tidak bisa menambahkan catatan orang tua")
    if len(note) > MAX_NOTE_LENGTH:
        raise MonthlyStoryValidationError("Catatan maksimal 1000 karakter")
    ids = data.get("selected_photo_ids") or []
    if not isinstance(ids, list) or len(ids) > MAX_SELECTED_PHOTOS or any(type(x) is not int for x in ids):
        raise MonthlyStoryValidationError("Pilih maksimal 4 foto yang valid")
    if len(ids) != len(set(ids)):
        raise MonthlyStoryValidationError("Foto pilihan tidak boleh duplikat")
    return start, end, previous_start, previous_end, note, ids


def _counts(child_id, start, end):
    result = {}
    result["milestones"] = MilestoneLog.query.filter(MilestoneLog.child_id == child_id,
        MilestoneLog.achieved_date.between(start, end)).count()
    result["vaccinations"] = ChildVaccination.query.filter(ChildVaccination.child_id == child_id,
        ChildVaccination.given.is_(True), ChildVaccination.given_date.between(start, end)).count()
    result["photos"] = MemoryJournalEntry.query.filter(MemoryJournalEntry.child_id == child_id,
        MemoryJournalEntry.occurred_date.between(start, end)).count()
    return result


def build_monthly_story(child, start, end, previous_start, previous_end, note, selected_ids, generated_at):
    selected = []
    if selected_ids:
        rows = MemoryJournalEntry.query.filter(MemoryJournalEntry.child_id == child.id,
            MemoryJournalEntry.id.in_(selected_ids), MemoryJournalEntry.occurred_date.between(start, end)).all()
        by_id = {row.id: row for row in rows}
        if set(by_id) != set(selected_ids):
            raise MonthlyStoryValidationError("Salah satu foto pilihan tidak tersedia pada bulan tersebut")
        for entry_id in selected_ids:
            row = by_id[entry_id]
            path = validated_journal_path(row.photo_filename)
            if not path or not path.is_file():
                raise MonthlyStoryValidationError("Salah satu foto pilihan tidak dapat dibaca")
            selected.append({"id": row.id, "caption": row.caption,
                "occurred_date": row.occurred_date.isoformat(),
                "_content_sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
    milestones = MilestoneLog.query.filter(MilestoneLog.child_id == child.id,
        MilestoneLog.achieved_date.between(start, end)).order_by(MilestoneLog.achieved_date).limit(20).all()
    growth = GrowthMeasurement.query.filter(GrowthMeasurement.child_id == child.id,
        GrowthMeasurement.measured_date.between(start, end)).order_by(GrowthMeasurement.measured_date).limit(20).all()
    return {
        "child": {"display_name": child.nickname or child.name, "birth_date": child.birth_date.isoformat()},
        "month": start.strftime("%Y-%m"), "period": {"start": start.isoformat(), "end": end.isoformat()},
        "generated_at": generated_at.isoformat(), "counts": _counts(child.id, start, end),
        "previous_counts": _counts(child.id, previous_start, previous_end),
        "milestones": [{"date": x.achieved_date.isoformat(), "label": x.custom_label if x.milestone_type == "custom" else x.milestone_type} for x in milestones],
        "growth": [{"date": x.measured_date.isoformat(), "weight_kg": x.weight_kg,
                    "height_cm": x.height_cm, "head_circumference_cm": x.head_circumference_cm} for x in growth],
        "selected_photos": selected, "parent_note": note or None,
        "disclaimer": "Ringkasan ini membantu keluarga mengingat perkembangan anak dan bukan penilaian medis.",
    }
