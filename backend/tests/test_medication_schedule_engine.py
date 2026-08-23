"""
Test murni buat utils/medication_schedule_engine.py -- TIDAK ADA Flask app,
TIDAK ADA database, TIDAK ADA client -- cuma manggil fungsi engine langsung
dengan `now`/`today` yang dikontrol manual. Lihat juga test_medication_schedule.py
buat test level route/integrasi (otorisasi, idempotensi, audit trail, dst).
"""
from datetime import date, datetime, timedelta
from types import SimpleNamespace

import pytest

from utils.medication_schedule_engine import (
    LOOKBACK_DAYS,
    MAX_TIMES_PER_DAY,
    ScheduleValidationError,
    adherence_percentage,
    compute_adherence,
    compute_schedule_occurrences,
    next_actionable_occurrence_at,
    occurrence_key_for,
    parse_occurrence_key,
    valid_occurrence_range,
    validate_dose,
    validate_times_of_day,
)

TODAY = date(2026, 8, 23)


def _schedule(start_date, end_date=None, times_of_day=("08:00",), is_active=True):
    return SimpleNamespace(start_date=start_date, end_date=end_date, times_of_day=list(times_of_day), is_active=is_active)


# --------------------------------------------------------------------------
# validate_dose()
# --------------------------------------------------------------------------


def test_validate_dose_allows_both_none():
    assert validate_dose(None, None) == (None, None)


def test_validate_dose_rejects_value_without_unit():
    with pytest.raises(ScheduleValidationError):
        validate_dose(5, None)


def test_validate_dose_rejects_unit_without_value():
    with pytest.raises(ScheduleValidationError):
        validate_dose(None, "ml")


def test_validate_dose_rejects_boolean_value():
    """`isinstance(True, int)` True di Python -- WAJIB ditolak eksplisit, bukan diam-diam lolos sebagai 1."""
    with pytest.raises(ScheduleValidationError):
        validate_dose(True, "ml")


def test_validate_dose_rejects_zero_or_negative():
    with pytest.raises(ScheduleValidationError):
        validate_dose(0, "ml")
    with pytest.raises(ScheduleValidationError):
        validate_dose(-1, "ml")


def test_validate_dose_normalizes_to_float():
    value, unit = validate_dose(5, "ml")
    assert value == 5.0 and unit == "ml"


# --------------------------------------------------------------------------
# validate_times_of_day()
# --------------------------------------------------------------------------


def test_validate_times_of_day_rejects_empty_list():
    with pytest.raises(ScheduleValidationError):
        validate_times_of_day([])


def test_validate_times_of_day_rejects_non_list():
    with pytest.raises(ScheduleValidationError):
        validate_times_of_day("08:00")


def test_validate_times_of_day_rejects_invalid_hour():
    with pytest.raises(ScheduleValidationError):
        validate_times_of_day(["24:00"])


def test_validate_times_of_day_rejects_invalid_minute():
    with pytest.raises(ScheduleValidationError):
        validate_times_of_day(["08:60"])


def test_validate_times_of_day_allows_exactly_max_times():
    times = [f"{h:02d}:00" for h in range(MAX_TIMES_PER_DAY)]
    assert validate_times_of_day(times) == times


def test_validate_times_of_day_rejects_over_max_times():
    times = [f"{h:02d}:00" for h in range(MAX_TIMES_PER_DAY + 1)]
    with pytest.raises(ScheduleValidationError):
        validate_times_of_day(times)


def test_validate_times_of_day_dedupes_and_sorts():
    assert validate_times_of_day(["20:00", "08:00", "08:00", "14:00"]) == ["08:00", "14:00", "20:00"]


# --------------------------------------------------------------------------
# parse_occurrence_key() / occurrence_key_for()
# --------------------------------------------------------------------------


def test_occurrence_key_roundtrip():
    dt = datetime(2026, 8, 23, 8, 5, 0)
    key = occurrence_key_for(dt)
    assert key == "2026-08-23T08:05"
    assert parse_occurrence_key(key) == dt


@pytest.mark.parametrize("bad_key", ["not-a-key", "2026-08-23", "2026-08-23T25:00", "2026-08-23T08:60", "", None, 123])
def test_parse_occurrence_key_rejects_malformed_input(bad_key):
    assert parse_occurrence_key(bad_key) is None


# --------------------------------------------------------------------------
# valid_occurrence_range()
# --------------------------------------------------------------------------


def test_future_start_date_has_no_valid_range():
    future_start = TODAY + timedelta(days=5)
    assert valid_occurrence_range(_schedule(future_start), TODAY) is None


def test_started_today_range_is_just_today():
    assert valid_occurrence_range(_schedule(TODAY), TODAY) == (
        datetime.combine(TODAY, datetime.min.time()),
        datetime.combine(TODAY, datetime.max.time()),
    )


def test_started_long_ago_range_bounded_by_lookback():
    started_long_ago = TODAY - timedelta(days=100)
    earliest, latest = valid_occurrence_range(_schedule(started_long_ago), TODAY)
    assert earliest.date() == TODAY - timedelta(days=LOOKBACK_DAYS)
    assert latest.date() == TODAY


def test_end_date_in_past_bounds_the_range():
    started = TODAY - timedelta(days=10)
    ended = TODAY - timedelta(days=3)
    earliest, latest = valid_occurrence_range(_schedule(started, end_date=ended), TODAY)
    assert latest.date() == ended


def test_end_date_before_lookback_start_has_no_valid_range():
    started = TODAY - timedelta(days=100)
    ended = TODAY - timedelta(days=90)  # SEBELUM jendela lookback dari `today`
    assert valid_occurrence_range(_schedule(started, end_date=ended), TODAY) is None


# --------------------------------------------------------------------------
# compute_schedule_occurrences()
# --------------------------------------------------------------------------


def test_inactive_schedule_produces_no_occurrences():
    schedule = _schedule(TODAY - timedelta(days=1), is_active=False)
    assert compute_schedule_occurrences(schedule, {}, TODAY, datetime(2026, 8, 23, 10, 0, 0)) == []


def test_future_start_date_produces_no_occurrences():
    schedule = _schedule(TODAY + timedelta(days=5))
    assert compute_schedule_occurrences(schedule, {}, TODAY, datetime(2026, 8, 23, 10, 0, 0)) == []


def test_occurrences_bounded_by_lookback_window():
    schedule = _schedule(TODAY - timedelta(days=100), times_of_day=["08:00"])
    occs = compute_schedule_occurrences(schedule, {}, TODAY, datetime(2026, 8, 23, 10, 0, 0))
    assert len(occs) == LOOKBACK_DAYS + 1


def test_occurrences_multiplied_by_times_per_day():
    schedule = _schedule(TODAY, times_of_day=["06:00", "12:00", "18:00"])
    occs = compute_schedule_occurrences(schedule, {}, TODAY, datetime(2026, 8, 23, 10, 0, 0))
    assert len(occs) == 3
    assert [o["occurrence_key"] for o in occs] == ["2026-08-23T06:00", "2026-08-23T12:00", "2026-08-23T18:00"]


# --------------------------------------------------------------------------
# next_actionable_occurrence_at()
# --------------------------------------------------------------------------


def test_future_start_date_next_actionable_is_first_time_on_start_date():
    future_start = TODAY + timedelta(days=5)
    schedule = _schedule(future_start, times_of_day=["09:00", "21:00"])
    result = next_actionable_occurrence_at(schedule, {}, TODAY, datetime(2026, 8, 23, 10, 0, 0))
    assert result == datetime.combine(future_start, datetime.min.time().replace(hour=9))


def test_inactive_schedule_has_no_next_actionable():
    schedule = _schedule(TODAY - timedelta(days=1), is_active=False)
    assert next_actionable_occurrence_at(schedule, {}, TODAY, datetime(2026, 8, 23, 10, 0, 0)) is None


def test_started_today_resolved_next_actionable_is_none_when_no_more_times_left():
    schedule = _schedule(TODAY, times_of_day=["08:00"])
    action = SimpleNamespace(status="administered", acted_at=datetime(2026, 8, 23, 8, 5), acted_by_user_id=1, actor=None, medication_log_id=1)
    actions = {datetime(2026, 8, 23, 8, 0): action}
    assert next_actionable_occurrence_at(schedule, actions, TODAY, datetime(2026, 8, 23, 10, 0, 0)) is None


# --------------------------------------------------------------------------
# compute_adherence()
# --------------------------------------------------------------------------


def test_adherence_zero_when_no_expected_doses_yet():
    schedule = _schedule(TODAY + timedelta(days=5))
    result = compute_adherence(schedule, {}, TODAY, TODAY, datetime(2026, 8, 23, 10, 0, 0))
    assert result["expected_count"] == 0
    assert adherence_percentage(result["expected_count"], result["administered_count"]) is None


def test_adherence_inactive_schedule_without_end_date_is_conservatively_zero():
    """Schedule nonaktif TANPA end_date eksplisit -- Phase 1 nggak menghitung ekspektasi apa pun (lihat docstring compute_adherence)."""
    schedule = _schedule(TODAY - timedelta(days=5), is_active=False)
    result = compute_adherence(schedule, {}, TODAY - timedelta(days=5), TODAY, datetime(2026, 8, 23, 10, 0, 0))
    assert result["expected_count"] == 0


def test_adherence_inactive_schedule_with_end_date_still_counts_up_to_end_date():
    """Nonaktif TAPI punya end_date eksplisit -- ekspektasi TETAP dihitung sampai end_date itu (beda dari kasus tanpa end_date di atas)."""
    started = TODAY - timedelta(days=5)
    ended = TODAY - timedelta(days=2)
    schedule = _schedule(started, end_date=ended, is_active=False, times_of_day=["08:00"])
    result = compute_adherence(schedule, {}, started, TODAY, datetime(2026, 8, 23, 10, 0, 0))
    assert result["expected_count"] == 4  # started..ended inklusif = 4 hari


def test_adherence_future_occurrences_never_counted_as_expected():
    schedule = _schedule(TODAY, times_of_day=["23:00"])  # jam ini MASA DEPAN relatif now=10:00
    result = compute_adherence(schedule, {}, TODAY, TODAY, datetime(2026, 8, 23, 10, 0, 0))
    assert result["expected_count"] == 0


def test_adherence_percentage_rounds_to_one_decimal():
    assert adherence_percentage(3, 1) == 33.3


def test_adherence_percentage_handles_full_and_zero_administered():
    assert adherence_percentage(4, 4) == 100.0
    assert adherence_percentage(4, 0) == 0.0
