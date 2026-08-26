"""Pure helpers for the on-demand vaccination planner (no scheduler)."""
import calendar
from datetime import timedelta


DUE_SOON_DAYS = 14
OVERDUE_AFTER_DAYS = 30


def add_months(value, months):
    month_index = value.month - 1 + months
    year = value.year + month_index // 12
    month = month_index % 12 + 1
    day = min(value.day, calendar.monthrange(year, month)[1])
    return value.replace(year=year, month=month, day=day)


def vaccination_state(*, birth_date, recommended_age_months, reference_date, given):
    """Return (state, recommended_date) using stable, documented boundaries."""
    recommended_date = add_months(birth_date, recommended_age_months)
    if given:
        return "given", recommended_date
    if reference_date < recommended_date - timedelta(days=DUE_SOON_DAYS):
        return "upcoming", recommended_date
    if reference_date <= recommended_date + timedelta(days=OVERDUE_AFTER_DAYS):
        return "due", recommended_date
    return "overdue", recommended_date


def vaccination_summary(items):
    summary = {"total": len(items), "given": 0, "upcoming": 0, "due": 0, "overdue": 0}
    for item in items:
        state = item["state"]
        if state in summary:
            summary[state] += 1
    return summary
