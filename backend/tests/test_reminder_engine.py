"""
Test murni buat utils/reminder_engine.py -- TIDAK ADA Flask app, TIDAK ADA
database, TIDAK ADA client -- cuma manggil fungsi-fungsi engine langsung
dengan `now`/`today` yang dikontrol manual. Lihat juga test_reminders.py
buat test level route/integrasi (otorisasi, idempotensi, audit trail, dst).

Fokus file ini: dua defect scheduling masa depan yang direview Agustus 2026
-- `valid_occurrence_date_range()` & `next_pending_occurrence_at()` --
plus `compute_reminder_occurrences()` biar kontraknya kebaca lengkap dalam
satu file yang sama.
"""
from datetime import date, datetime, timedelta
from types import SimpleNamespace

from utils.reminder_engine import (
    DAILY_LOOKBACK_DAYS,
    compute_reminder_occurrences,
    next_pending_occurrence_at,
    valid_occurrence_date_range,
)

TODAY = date(2026, 8, 23)


def _reminder(scheduled_at, recurrence="none", is_active=True):
    return SimpleNamespace(scheduled_at=scheduled_at, recurrence=recurrence, is_active=is_active)


# --------------------------------------------------------------------------
# valid_occurrence_date_range()
# --------------------------------------------------------------------------


def test_none_recurrence_future_schedule_has_no_valid_range():
    future = datetime(2026, 8, 28, 8, 0, 0)
    assert valid_occurrence_date_range(future, "none", TODAY) is None


def test_none_recurrence_today_schedule_range_is_just_today():
    scheduled = datetime(2026, 8, 23, 20, 0, 0)  # jam berapa pun di hari ini
    assert valid_occurrence_date_range(scheduled, "none", TODAY) == (TODAY, TODAY)


def test_none_recurrence_past_schedule_range_is_just_that_date():
    scheduled = datetime(2026, 8, 10, 8, 0, 0)
    assert valid_occurrence_date_range(scheduled, "none", TODAY) == (date(2026, 8, 10), date(2026, 8, 10))


def test_daily_recurrence_future_start_date_has_no_valid_range():
    future_start = datetime(2026, 8, 28, 8, 0, 0)
    assert valid_occurrence_date_range(future_start, "daily", TODAY) is None


def test_daily_recurrence_started_today_range_is_just_today():
    started_today = datetime(2026, 8, 23, 6, 0, 0)
    assert valid_occurrence_date_range(started_today, "daily", TODAY) == (TODAY, TODAY)


def test_daily_recurrence_started_in_past_range_is_bounded_by_lookback():
    started_long_ago = TODAY - timedelta(days=100)
    earliest, latest = valid_occurrence_date_range(datetime.combine(started_long_ago, datetime.min.time()), "daily", TODAY)
    assert earliest == TODAY - timedelta(days=DAILY_LOOKBACK_DAYS)
    assert latest == TODAY


def test_daily_recurrence_started_recently_range_starts_at_its_own_start_date():
    started_5_days_ago = TODAY - timedelta(days=5)
    earliest, latest = valid_occurrence_date_range(datetime.combine(started_5_days_ago, datetime.min.time()), "daily", TODAY)
    assert earliest == started_5_days_ago  # LEBIH ketat dari lookback window generik
    assert latest == TODAY


# --------------------------------------------------------------------------
# next_pending_occurrence_at()
# --------------------------------------------------------------------------


def test_daily_reminder_starting_in_future_next_pending_is_original_scheduled_at():
    scheduled_at = datetime(2026, 8, 28, 8, 0, 0)
    reminder = _reminder(scheduled_at, recurrence="daily")
    assert next_pending_occurrence_at(reminder, {}, TODAY) == scheduled_at


def test_one_time_reminder_scheduled_in_future_next_pending_is_original_scheduled_at():
    scheduled_at = datetime(2026, 8, 28, 8, 0, 0)
    reminder = _reminder(scheduled_at, recurrence="none")
    assert next_pending_occurrence_at(reminder, {}, TODAY) == scheduled_at


def test_daily_reminder_started_today_next_pending_is_today():
    scheduled_at = datetime(2026, 8, 23, 8, 0, 0)
    reminder = _reminder(scheduled_at, recurrence="daily")
    assert next_pending_occurrence_at(reminder, {}, TODAY) == scheduled_at


def test_daily_reminder_today_resolved_next_pending_is_tomorrow():
    scheduled_at = datetime(2026, 8, 20, 8, 0, 0)
    reminder = _reminder(scheduled_at, recurrence="daily")
    actions_by_date = {TODAY: SimpleNamespace()}
    result = next_pending_occurrence_at(reminder, actions_by_date, TODAY)
    assert result == datetime(2026, 8, 24, 8, 0, 0)


def test_one_time_reminder_resolved_has_no_next_pending():
    scheduled_at = datetime(2026, 8, 20, 8, 0, 0)
    reminder = _reminder(scheduled_at, recurrence="none")
    actions_by_date = {date(2026, 8, 20): SimpleNamespace()}
    assert next_pending_occurrence_at(reminder, actions_by_date, TODAY) is None


def test_inactive_reminder_has_no_next_pending_even_if_scheduled_in_future():
    scheduled_at = datetime(2026, 8, 28, 8, 0, 0)
    reminder = _reminder(scheduled_at, recurrence="daily", is_active=False)
    assert next_pending_occurrence_at(reminder, {}, TODAY) is None


# --------------------------------------------------------------------------
# compute_reminder_occurrences() -- kelayakan TAMPILAN, terpisah dari
# kelayakan AKSI di atas.
# --------------------------------------------------------------------------


def test_daily_reminder_starting_in_future_produces_no_occurrences():
    scheduled_at = datetime(2026, 8, 28, 8, 0, 0)
    reminder = _reminder(scheduled_at, recurrence="daily")
    assert compute_reminder_occurrences(reminder, {}, TODAY, datetime(2026, 8, 23, 10, 0, 0)) == []


def test_one_time_reminder_scheduled_in_future_still_shown_as_a_single_upcoming_occurrence():
    scheduled_at = datetime(2026, 8, 28, 8, 0, 0)
    reminder = _reminder(scheduled_at, recurrence="none")
    occs = compute_reminder_occurrences(reminder, {}, TODAY, datetime(2026, 8, 23, 10, 0, 0))
    assert len(occs) == 1
    assert occs[0]["occurrence_key"] == "2026-08-28"
    assert occs[0]["state"] == "upcoming"
