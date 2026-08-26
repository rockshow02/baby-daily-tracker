from datetime import timedelta


def goal_state(goal, today):
    if goal.completed_at is not None:
        return "completed"
    if goal.target_date < today:
        return "overdue"
    if goal.target_date <= today + timedelta(days=7):
        return "due"
    return "upcoming"
