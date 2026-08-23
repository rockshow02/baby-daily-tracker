"""
Test Smart Insights & Weekly Summary — Phase 1 (`GET
/children/<id>/insights`). Lihat backend/docs/INSIGHTS.md buat kontrak
lengkapnya.

SEMUA test pakai fixture `client` (SQLite in-memory), TIDAK PERNAH
menyentuh instance/tracker.db asli. "Hari ini" WAJIB dibekukan lewat
`_freeze_today()` (monkeypatch `routes.insights_routes.today_wib`) di
SETIAP test yang bergantung ke batas tanggal — endpoint ini SENGAJA
manggil `today_wib()` cuma sekali di layer route (bukan di
utils/insights_engine.py) justru biar bisa dites deterministik kayak
gini, lihat routes/insights_routes.py.
"""
import json
from contextlib import contextmanager
from datetime import date, datetime, timedelta

import pytest
from sqlalchemy import event
from sqlalchemy.engine import Engine

import routes.insights_routes as insights_routes_module
from extensions import db
from models import (
    ActivityLog, CaregiverAuditEvent, Child, DiaperLog, DoctorVisitLog,
    FeedingLog, GrowthMeasurement, IllnessLog, MedicationLog, MilestoneLog,
    MoodLog, PumpingLog, SleepLog, TemperatureLog,
)
from utils.insights_engine import INSIGHT_ALLOWLIST, MAX_INSIGHT_CARDS
from tests.conftest import auth_headers, create_child, register
from tests.test_roles_permissions import invite_and_join

# Minggu, dipilih sembarang -- cuma perlu tetap/deterministik.
FAKE_TODAY = date(2026, 8, 23)


def _freeze_today(monkeypatch, today=FAKE_TODAY):
    monkeypatch.setattr(insights_routes_module, "today_wib", lambda: today)


def _get_insights(client, token, child_id, period="7d"):
    return client.get(
        f"/api/children/{child_id}/insights?period={period}", headers=auth_headers(token)
    )


@contextmanager
def count_queries():
    """Hitung SEMUA statement SQL yang beneran dieksekusi di blok `with` ini."""
    counter = [0]

    def _before_cursor_execute(*args, **kwargs):
        counter[0] += 1

    event.listen(Engine, "before_cursor_execute", _before_cursor_execute)
    try:
        yield counter
    finally:
        event.remove(Engine, "before_cursor_execute", _before_cursor_execute)


# --------------------------------------------------------------------------
# 1-4. Otorisasi: owner/editor/viewer boleh baca, outsider 404 (bukan 403,
# bukan bisa mbedain "ada tapi ditolak" dari "beneran nggak ada").
# --------------------------------------------------------------------------


def test_owner_can_access_insights(client, monkeypatch):
    _freeze_today(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])
    resp = _get_insights(client, user["token"], child["id"])
    assert resp.status_code == 200, resp.get_json()


def test_editor_can_access_insights(client, monkeypatch):
    _freeze_today(monkeypatch)
    owner = register(client, name="Pemilik", email="owner-insights-editor@example.com")
    child = create_child(client, owner["token"])
    editor = register(client, name="Editor", email="editor-insights@example.com")
    invite_and_join(client, owner["token"], child["id"], editor["token"], "editor")
    resp = _get_insights(client, editor["token"], child["id"])
    assert resp.status_code == 200, resp.get_json()


def test_viewer_can_access_insights(client, monkeypatch):
    _freeze_today(monkeypatch)
    owner = register(client, name="Pemilik", email="owner-insights-viewer@example.com")
    child = create_child(client, owner["token"])
    viewer = register(client, name="Viewer", email="viewer-insights@example.com")
    invite_and_join(client, owner["token"], child["id"], viewer["token"], "viewer")
    resp = _get_insights(client, viewer["token"], child["id"])
    assert resp.status_code == 200, resp.get_json()


def test_outsider_gets_404_indistinguishable_from_nonexistent_child(client, monkeypatch):
    _freeze_today(monkeypatch)
    owner = register(client, name="Pemilik", email="owner-insights-outsider@example.com")
    child = create_child(client, owner["token"])
    outsider = register(client, name="Orang Lain", email="outsider-insights@example.com")

    resp = _get_insights(client, outsider["token"], child["id"])
    assert resp.status_code == 404

    nonexistent_resp = _get_insights(client, outsider["token"], 999999)
    assert nonexistent_resp.status_code == 404
    # Pesan error-nya SAMA PERSIS -- outsider nggak bisa mbedain "anak ini
    # ADA tapi kamu ditolak" dari "anak ini beneran nggak ada".
    assert resp.get_json() == nonexistent_resp.get_json()


# --------------------------------------------------------------------------
# 5. Isolasi data antar anak.
# --------------------------------------------------------------------------


def test_insights_never_leak_another_childs_data(client, monkeypatch):
    _freeze_today(monkeypatch)
    user = register(client)
    child_a = create_child(client, user["token"], name="Anak A")
    child_b = create_child(client, user["token"], name="Anak B")

    db.session.add(FeedingLog(child_id=child_a["id"], timestamp=datetime(2026, 8, 20, 8, 0, 0), feed_type="asi_langsung"))
    db.session.add(FeedingLog(child_id=child_b["id"], timestamp=datetime(2026, 8, 20, 8, 0, 0), feed_type="sufor"))
    db.session.add(FeedingLog(child_id=child_b["id"], timestamp=datetime(2026, 8, 20, 9, 0, 0), feed_type="sufor"))
    db.session.commit()

    body = _get_insights(client, user["token"], child_a["id"]).get_json()
    assert body["metrics"]["feeding"]["total_events"] == 1


# --------------------------------------------------------------------------
# 6-7. Batas periode WIB + tepat di ujung batas.
# --------------------------------------------------------------------------


def test_period_boundaries_are_correct_in_wib(client, monkeypatch):
    _freeze_today(monkeypatch)  # FAKE_TODAY = 2026-08-23
    user = register(client)
    child = create_child(client, user["token"])

    body = _get_insights(client, user["token"], child["id"]).get_json()
    assert body["period"] == {
        "key": "7d", "start_date": "2026-08-17", "end_date": "2026-08-23",
        "timezone": "Asia/Jakarta", "days": 7,
    }
    assert body["previous_period"] == {"start_date": "2026-08-10", "end_date": "2026-08-16"}


def test_records_exactly_on_period_boundaries_are_handled_correctly(client, monkeypatch):
    _freeze_today(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])
    cid = child["id"]

    db.session.add(FeedingLog(child_id=cid, timestamp=datetime(2026, 8, 17, 0, 0, 0), feed_type="asi_langsung"))  # awal periode ini, inklusif
    db.session.add(FeedingLog(child_id=cid, timestamp=datetime(2026, 8, 23, 23, 59, 59), feed_type="asi_langsung"))  # akhir periode ini, inklusif
    db.session.add(FeedingLog(child_id=cid, timestamp=datetime(2026, 8, 16, 23, 59, 59), feed_type="asi_langsung"))  # 1 detik sebelum awal -> periode SEBELUMNYA
    db.session.add(FeedingLog(child_id=cid, timestamp=datetime(2026, 8, 24, 0, 0, 0), feed_type="asi_langsung"))  # 1 hari setelah akhir -> di luar dua-duanya
    db.session.commit()

    body = _get_insights(client, user["token"], cid).get_json()
    assert body["metrics"]["feeding"]["total_events"] == 2
    assert body["comparisons"]["feeding_count"]["previous"] == 1


# --------------------------------------------------------------------------
# 8-9. Feeding: total/rata-rata, volume yang hilang dikecualikan dari rata-rata.
# --------------------------------------------------------------------------


def test_feeding_totals_and_averages_correct(client, monkeypatch):
    _freeze_today(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])
    cid = child["id"]

    db.session.add(FeedingLog(child_id=cid, timestamp=datetime(2026, 8, 18, 8, 0, 0), feed_type="asi_langsung", volume_ml=None))
    db.session.add(FeedingLog(child_id=cid, timestamp=datetime(2026, 8, 18, 11, 0, 0), feed_type="sufor", volume_ml=100))
    db.session.add(FeedingLog(child_id=cid, timestamp=datetime(2026, 8, 18, 14, 0, 0), feed_type="sufor", volume_ml=120))
    db.session.commit()

    feeding = _get_insights(client, user["token"], cid).get_json()["metrics"]["feeding"]
    assert feeding["total_events"] == 3
    assert feeding["avg_events_per_day"] == round(3 / 7, 1)
    assert feeding["by_type"]["asi_langsung"] == 1
    assert feeding["by_type"]["sufor"] == 2
    assert feeding["total_volume_ml"] == 220
    assert feeding["events_with_volume"] == 2
    assert feeding["avg_volume_ml_per_event"] == 110.0


def test_missing_feeding_volume_excluded_from_average(client, monkeypatch):
    _freeze_today(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])
    cid = child["id"]

    db.session.add(FeedingLog(child_id=cid, timestamp=datetime(2026, 8, 18, 8, 0, 0), feed_type="asi_langsung", volume_ml=None))
    db.session.add(FeedingLog(child_id=cid, timestamp=datetime(2026, 8, 18, 9, 0, 0), feed_type="sufor", volume_ml=200))
    db.session.commit()

    feeding = _get_insights(client, user["token"], cid).get_json()["metrics"]["feeding"]
    # BUKAN (200+0)/2=100 -- event tanpa volume_ml TIDAK PERNAH dianggap 0
    assert feeding["avg_volume_ml_per_event"] == 200.0
    assert feeding["events_with_volume"] == 1
    assert feeding["total_events"] == 2


# --------------------------------------------------------------------------
# 10-11. Sleep: sesi belum selesai dipisah, durasi negatif ditangani defensif.
# --------------------------------------------------------------------------


def test_sleep_excludes_unfinished_sessions_and_reports_separately(client, monkeypatch):
    _freeze_today(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])
    cid = child["id"]

    db.session.add(SleepLog(child_id=cid, start_time=datetime(2026, 8, 18, 20, 0, 0), end_time=datetime(2026, 8, 18, 22, 0, 0), sleep_type="malam"))
    db.session.add(SleepLog(child_id=cid, start_time=datetime(2026, 8, 19, 20, 0, 0), end_time=None, sleep_type="malam"))
    db.session.commit()

    sleep = _get_insights(client, user["token"], cid).get_json()["metrics"]["sleep"]
    assert sleep["completed_session_count"] == 1
    assert sleep["unfinished_session_count"] == 1
    assert sleep["total_completed_minutes"] == 120.0
    assert sleep["avg_duration_minutes_per_session"] == 120.0


def test_negative_sleep_duration_handled_defensively(client, monkeypatch):
    _freeze_today(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])
    cid = child["id"]

    # end_time SEBELUM start_time -- data korup/nggak valid (nggak bisa
    # kejadian lewat API biasa, tapi endpoint ini WAJIB nggak crash dan
    # nggak ngasilin total negatif kalau somehow ada di database).
    db.session.add(SleepLog(child_id=cid, start_time=datetime(2026, 8, 18, 22, 0, 0), end_time=datetime(2026, 8, 18, 20, 0, 0), sleep_type="malam"))
    db.session.add(SleepLog(child_id=cid, start_time=datetime(2026, 8, 19, 20, 0, 0), end_time=datetime(2026, 8, 19, 21, 0, 0), sleep_type="malam"))
    db.session.commit()

    resp = _get_insights(client, user["token"], cid)
    assert resp.status_code == 200
    sleep = resp.get_json()["metrics"]["sleep"]
    assert sleep["total_completed_minutes"] == 60.0
    assert sleep["completed_session_count"] == 1


# --------------------------------------------------------------------------
# 12. Diaper: kategori & total.
# --------------------------------------------------------------------------


def test_diaper_categories_and_totals_correct(client, monkeypatch):
    _freeze_today(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])
    cid = child["id"]

    db.session.add(DiaperLog(child_id=cid, timestamp=datetime(2026, 8, 18, 8, 0, 0), diaper_type="pipis"))
    db.session.add(DiaperLog(child_id=cid, timestamp=datetime(2026, 8, 18, 9, 0, 0), diaper_type="pup"))
    db.session.add(DiaperLog(child_id=cid, timestamp=datetime(2026, 8, 18, 10, 0, 0), diaper_type="keduanya"))
    db.session.commit()

    diaper = _get_insights(client, user["token"], cid).get_json()["metrics"]["diaper"]
    assert diaper["total_events"] == 3
    assert diaper["pipis_count"] == 2
    assert diaper["bab_count"] == 2
    assert diaper["combined_count"] == 1


# --------------------------------------------------------------------------
# 13. Pumping: total & nilai yang hilang.
# --------------------------------------------------------------------------


def test_pumping_totals_and_missing_value_behavior(client, monkeypatch):
    _freeze_today(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])
    cid = child["id"]

    db.session.add(PumpingLog(child_id=cid, timestamp=datetime(2026, 8, 18, 8, 0, 0), volume_ml=80, duration_minutes=15))
    db.session.add(PumpingLog(child_id=cid, timestamp=datetime(2026, 8, 18, 12, 0, 0), volume_ml=None, duration_minutes=None))
    db.session.commit()

    pumping = _get_insights(client, user["token"], cid).get_json()["metrics"]["pumping"]
    assert pumping["session_count"] == 2
    assert pumping["total_volume_ml"] == 80
    assert pumping["events_with_volume"] == 1
    assert pumping["avg_volume_ml_per_event"] == 80.0
    assert pumping["total_duration_minutes"] == 15
    assert pumping["events_with_duration"] == 1


# --------------------------------------------------------------------------
# 14-15. Growth: 2 pengukuran terakhir, nilai parsial -> null.
# --------------------------------------------------------------------------


def test_growth_compares_latest_two_measurements(client, monkeypatch):
    _freeze_today(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])
    cid = child["id"]

    db.session.add(GrowthMeasurement(child_id=cid, measured_date=date(2026, 6, 1), weight_kg=3.0, height_cm=55.0, head_circumference_cm=36.0))
    db.session.add(GrowthMeasurement(child_id=cid, measured_date=date(2026, 7, 1), weight_kg=4.0, height_cm=58.0, head_circumference_cm=37.0))
    db.session.add(GrowthMeasurement(child_id=cid, measured_date=date(2026, 8, 1), weight_kg=5.0, height_cm=60.0, head_circumference_cm=38.0))
    db.session.commit()

    growth = _get_insights(client, user["token"], cid).get_json()["metrics"]["growth"]
    assert growth["latest"]["measured_date"] == "2026-08-01"
    assert growth["previous"]["measured_date"] == "2026-07-01"
    assert growth["weight_change_kg"] == 1.0
    assert growth["height_change_cm"] == 2.0
    assert growth["head_circumference_change_cm"] == 1.0
    assert growth["days_since_latest_measurement"] == (FAKE_TODAY - date(2026, 8, 1)).days


def test_growth_partial_values_produce_null_comparisons(client, monkeypatch):
    _freeze_today(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])
    cid = child["id"]

    db.session.add(GrowthMeasurement(child_id=cid, measured_date=date(2026, 7, 1), weight_kg=4.0, height_cm=None, head_circumference_cm=37.0))
    db.session.add(GrowthMeasurement(child_id=cid, measured_date=date(2026, 8, 1), weight_kg=5.0, height_cm=60.0, head_circumference_cm=None))
    db.session.commit()

    growth = _get_insights(client, user["token"], cid).get_json()["metrics"]["growth"]
    assert growth["weight_change_kg"] == 1.0  # dua-duanya ada
    assert growth["height_change_cm"] is None  # nggak ada di pengukuran sebelumnya
    assert growth["head_circumference_change_cm"] is None  # nggak ada di pengukuran terbaru


# --------------------------------------------------------------------------
# 16. Health: nggak nyertain teks sensitif.
# --------------------------------------------------------------------------


def test_health_overview_excludes_sensitive_text_fields(client, monkeypatch):
    _freeze_today(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])
    cid = child["id"]

    db.session.add(TemperatureLog(child_id=cid, timestamp=datetime(2026, 8, 18, 8, 0, 0), temperature_celsius=37.8, method="ketiak", notes="RAHASIA_SUHU"))
    db.session.add(MedicationLog(child_id=cid, timestamp=datetime(2026, 8, 18, 9, 0, 0), medication_name="RAHASIA_OBAT", dosage="RAHASIA_DOSIS"))
    db.session.add(DoctorVisitLog(child_id=cid, visit_date=date(2026, 8, 18), doctor_name="RAHASIA_DOKTER", clinic_name="RAHASIA_KLINIK", reason="RAHASIA_ALASAN", diagnosis="RAHASIA_DIAGNOSIS"))
    db.session.add(IllnessLog(child_id=cid, illness_name="RAHASIA_PENYAKIT", start_date=date(2026, 8, 18), symptoms="RAHASIA_GEJALA"))
    db.session.commit()

    health = _get_insights(client, user["token"], cid).get_json()["metrics"]["health"]
    assert health["temperature_record_count"] == 1
    assert health["latest_temperature_celsius"] == 37.8
    assert health["medication_event_count"] == 1
    assert health["doctor_visit_count"] == 1
    assert health["illness_record_count"] == 1
    assert set(health.keys()) == {
        "temperature_record_count", "latest_temperature_celsius", "latest_temperature_at",
        "medication_event_count", "doctor_visit_count", "illness_record_count",
    }
    assert "RAHASIA" not in json.dumps(health)


# --------------------------------------------------------------------------
# 17. Activity, mood (kategori terkontrol), milestone.
# --------------------------------------------------------------------------


def test_activity_mood_milestone_summaries_correct(client, monkeypatch):
    _freeze_today(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])
    cid = child["id"]

    db.session.add(ActivityLog(child_id=cid, timestamp=datetime(2026, 8, 18, 8, 0, 0), activity_type="stroll", duration_minutes=30))
    db.session.add(ActivityLog(child_id=cid, timestamp=datetime(2026, 8, 19, 8, 0, 0), activity_type="bathing", duration_minutes=None))
    db.session.add(MoodLog(child_id=cid, timestamp=datetime(2026, 8, 18, 8, 0, 0), mood="ceria"))
    db.session.add(MoodLog(child_id=cid, timestamp=datetime(2026, 8, 19, 8, 0, 0), mood="ceria"))
    db.session.add(MoodLog(child_id=cid, timestamp=datetime(2026, 8, 20, 8, 0, 0), mood="sedih"))
    db.session.add(MilestoneLog(child_id=cid, milestone_type="bisa_duduk", achieved_date=date(2026, 8, 18)))
    db.session.add(MilestoneLog(child_id=cid, milestone_type="custom", custom_label="RAHASIA_LABEL_MILESTONE", achieved_date=date(2026, 8, 20)))
    db.session.commit()

    metrics = _get_insights(client, user["token"], cid).get_json()["metrics"]
    assert metrics["activity"]["session_count"] == 2
    assert metrics["activity"]["total_duration_minutes"] == 30
    assert metrics["activity"]["events_with_duration"] == 1
    assert metrics["mood"]["counts"] == {"ceria": 2, "baik": 0, "sedih": 1, "menangis": 0}
    assert metrics["mood"]["total_events"] == 3
    assert metrics["milestones"]["count_in_period"] == 2
    assert metrics["milestones"]["latest_milestone_type"] == "custom"
    assert metrics["milestones"]["latest_milestone_date"] == "2026-08-20"
    assert "custom_label" not in json.dumps(metrics["milestones"])
    assert "RAHASIA_LABEL_MILESTONE" not in json.dumps(metrics["milestones"])


# --------------------------------------------------------------------------
# 18-20. Perbandingan periode: benar, persentase null kalau previous=0,
# nggak ada "penurunan palsu" dari data yang nggak tercatat.
# --------------------------------------------------------------------------


def test_comparisons_current_vs_previous_computed_correctly(client, monkeypatch):
    _freeze_today(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])
    cid = child["id"]

    for i in range(4):
        db.session.add(FeedingLog(child_id=cid, timestamp=datetime(2026, 8, 12, 8 + i, 0, 0), feed_type="asi_langsung"))
    for i in range(6):
        db.session.add(FeedingLog(child_id=cid, timestamp=datetime(2026, 8, 19, 8 + i, 0, 0), feed_type="asi_langsung"))
    db.session.commit()

    comparisons = _get_insights(client, user["token"], cid).get_json()["comparisons"]
    assert comparisons["feeding_count"] == {"current": 6, "previous": 4, "change": 2, "percent_change": 50.0}


def test_percent_change_is_null_when_previous_value_is_zero(client, monkeypatch):
    _freeze_today(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])
    cid = child["id"]

    for i in range(5):
        db.session.add(FeedingLog(child_id=cid, timestamp=datetime(2026, 8, 19, 8 + i, 0, 0), feed_type="asi_langsung"))
    db.session.commit()

    comparisons = _get_insights(client, user["token"], cid).get_json()["comparisons"]
    assert comparisons["feeding_count"] == {"current": 5, "previous": 0, "change": 5, "percent_change": None}


def test_no_false_decrease_insight_when_current_period_has_no_data(client, monkeypatch):
    _freeze_today(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])
    cid = child["id"]

    # Periode SEBELUMNYA ada banyak catatan menyusui; periode SEKARANG
    # nihil menyusui (tapi ADA catatan lain, biar has_any_data tetap True
    # dan build_insights() nggak cuma balikin insufficient_data doang) --
    # ini TIDAK PERNAH boleh ngasilin kartu "feeding_count_decreased",
    # soalnya 0 di periode sekarang kemungkinan besar cuma belum sempat
    # dicatat, bukan bukti anaknya beneran berhenti minum.
    for i in range(5):
        db.session.add(FeedingLog(child_id=cid, timestamp=datetime(2026, 8, 12, 8 + i, 0, 0), feed_type="asi_langsung"))
    db.session.add(DiaperLog(child_id=cid, timestamp=datetime(2026, 8, 18, 9, 0, 0), diaper_type="pipis"))
    db.session.commit()

    body = _get_insights(client, user["token"], cid).get_json()
    assert body["comparisons"]["feeding_count"]["current"] == 0
    assert body["comparisons"]["feeding_count"]["previous"] == 5
    codes = [c["code"] for c in body["insights"]]
    assert "feeding_count_decreased" not in codes


# --------------------------------------------------------------------------
# 21-23. Insufficient-data state, allowlist ketat, batas maksimal kartu.
# --------------------------------------------------------------------------


def test_insufficient_data_returns_stable_dedicated_state(client, monkeypatch):
    _freeze_today(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])

    body = _get_insights(client, user["token"], child["id"]).get_json()
    assert body["data_quality"]["has_any_data"] is False
    assert body["insights"] == [
        {"code": "insufficient_data", "severity": "info", "metric": None, "direction": None, "value": None}
    ]


def test_insight_codes_always_come_from_the_allowlist(client, monkeypatch):
    _freeze_today(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])
    cid = child["id"]

    db.session.add(FeedingLog(child_id=cid, timestamp=datetime(2026, 8, 18, 8, 0, 0), feed_type="asi_langsung"))
    db.session.commit()

    body = _get_insights(client, user["token"], cid).get_json()
    for card in body["insights"]:
        assert card["code"] in INSIGHT_ALLOWLIST


def test_max_insight_card_count_is_enforced(client, monkeypatch):
    _freeze_today(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])
    cid = child["id"]

    # Periode sekarang (08-17..08-23) rame di SEMUA 6 domain yang punya
    # rule, periode sebelumnya (08-10..08-16) nihil sama sekali -- ini
    # dengan sengaja memicu SEMUA 6 kandidat insight sekaligus (5 rule
    # "meningkat" + 1 rule "belum ada pengukuran pertumbuhan"), biar bisa
    # mbuktiin batas MAX_INSIGHT_CARDS beneran ditegakkan (bukan cuma
    # kebetulan nggak pernah lebih dari 5 di skenario lain).
    db.session.add(SleepLog(child_id=cid, start_time=datetime(2026, 8, 18, 20, 0, 0), end_time=datetime(2026, 8, 18, 21, 0, 0), sleep_type="malam"))
    for i in range(4):
        db.session.add(FeedingLog(child_id=cid, timestamp=datetime(2026, 8, 19, 8 + i, 0, 0), feed_type="asi_langsung"))
    for i in range(4):
        db.session.add(DiaperLog(child_id=cid, timestamp=datetime(2026, 8, 19, 8 + i, 0, 0), diaper_type="pipis"))
    db.session.add(PumpingLog(child_id=cid, timestamp=datetime(2026, 8, 18, 10, 0, 0), volume_ml=150))
    db.session.add(ActivityLog(child_id=cid, timestamp=datetime(2026, 8, 18, 11, 0, 0), activity_type="stroll", duration_minutes=45))
    # SENGAJA nggak ada GrowthMeasurement sama sekali -> memicu
    # growth_no_recent_measurement, kandidat ke-6.
    db.session.commit()

    body = _get_insights(client, user["token"], cid).get_json()
    assert len(body["insights"]) == MAX_INSIGHT_CARDS
    assert MAX_INSIGHT_CARDS == 5
    codes = [c["code"] for c in body["insights"]]
    # urutan rule TETAP (tidur -> menyusui -> popok -> pumping ->
    # aktivitas -> tumbuh kembang) -- yang ke-6 (growth) kepotong duluan.
    assert codes == [
        "sleep_duration_increased",
        "feeding_count_increased",
        "diaper_count_increased",
        "pumping_volume_increased",
        "activity_duration_increased",
    ]
    assert "growth_no_recent_measurement" not in codes


# --------------------------------------------------------------------------
# 24. Periode yang nggak didukung -> 400.
# --------------------------------------------------------------------------


def test_unsupported_period_returns_400(client, monkeypatch):
    _freeze_today(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])

    resp = _get_insights(client, user["token"], child["id"], period="14d")
    assert resp.status_code == 400


def test_30d_period_is_supported(client, monkeypatch):
    _freeze_today(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])

    resp = _get_insights(client, user["token"], child["id"], period="30d")
    assert resp.status_code == 200
    assert resp.get_json()["period"]["key"] == "30d"
    assert resp.get_json()["period"]["days"] == 30


# --------------------------------------------------------------------------
# 25. Riwayat anak kosong -> respons nol/kosong yang valid, bukan exception.
# --------------------------------------------------------------------------


def test_empty_child_history_returns_valid_zero_response(client, monkeypatch):
    _freeze_today(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])

    resp = _get_insights(client, user["token"], child["id"])
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["metrics"]["feeding"]["total_events"] == 0
    assert body["metrics"]["sleep"]["completed_session_count"] == 0
    assert body["metrics"]["diaper"]["total_events"] == 0
    assert body["metrics"]["pumping"]["session_count"] == 0
    assert body["metrics"]["growth"]["latest"] is None
    assert body["metrics"]["health"]["temperature_record_count"] == 0
    assert body["metrics"]["activity"]["session_count"] == 0
    assert body["metrics"]["mood"]["total_events"] == 0
    assert body["metrics"]["milestones"]["count_in_period"] == 0
    assert body["data_quality"] == {
        "has_any_data": False, "days_with_records": 0,
        "missing_volume_count": 0, "unfinished_sleep_count": 0,
    }


# --------------------------------------------------------------------------
# 26. Seluruh respons yang di-serialize nggak boleh ngandung nilai
# sensitif yang di-seed.
# --------------------------------------------------------------------------


def test_full_serialized_response_contains_no_seeded_sensitive_values(client, monkeypatch):
    _freeze_today(monkeypatch)
    marker = "RAHASIA_MARKER_XYZ"
    user = register(client, name="Privacy Test", email="privacy-marker-insights@example.com")
    child = create_child(client, user["token"])
    cid = child["id"]
    d = datetime(2026, 8, 20, 10, 0, 0)

    db.session.add(FeedingLog(child_id=cid, timestamp=d, feed_type="asi_langsung", notes=marker + "_feeding"))
    db.session.add(SleepLog(child_id=cid, start_time=d, end_time=d + timedelta(hours=1), notes=marker + "_sleep"))
    db.session.add(DiaperLog(child_id=cid, timestamp=d, diaper_type="pipis", notes=marker + "_diaper", color=marker + "_color"))
    db.session.add(PumpingLog(child_id=cid, timestamp=d, volume_ml=50, notes=marker + "_pumping"))
    db.session.add(ActivityLog(child_id=cid, timestamp=d, activity_type="stroll", notes=marker + "_activity"))
    db.session.add(MoodLog(child_id=cid, timestamp=d, mood="ceria", notes=marker + "_mood"))
    db.session.add(MilestoneLog(child_id=cid, milestone_type="custom", custom_label=marker + "_milestone", achieved_date=d.date()))
    db.session.add(TemperatureLog(child_id=cid, timestamp=d, temperature_celsius=37.5, notes=marker + "_temp"))
    db.session.add(MedicationLog(child_id=cid, timestamp=d, medication_name=marker + "_med", dosage=marker + "_dosage", notes=marker + "_mednotes"))
    db.session.add(DoctorVisitLog(child_id=cid, visit_date=d.date(), doctor_name=marker + "_doctor", clinic_name=marker + "_clinic", reason=marker + "_reason", diagnosis=marker + "_diagnosis", notes=marker + "_visitnotes"))
    db.session.add(IllnessLog(child_id=cid, illness_name=marker + "_illness", start_date=d.date(), symptoms=marker + "_symptoms", notes=marker + "_illnessnotes"))
    db.session.commit()

    resp = _get_insights(client, user["token"], cid)
    assert resp.status_code == 200
    body_text = json.dumps(resp.get_json())

    assert marker not in body_text
    assert "privacy-marker-insights@example.com" not in body_text
    assert user["token"] not in body_text


# --------------------------------------------------------------------------
# 27. Baca-saja: nggak pernah bikin audit event.
# --------------------------------------------------------------------------


def test_insights_endpoint_creates_no_audit_event(client, monkeypatch):
    _freeze_today(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])

    before = CaregiverAuditEvent.query.count()
    _get_insights(client, user["token"], child["id"])
    after = CaregiverAuditEvent.query.count()
    assert after == before == 0


# --------------------------------------------------------------------------
# 28. Perilaku request-ID dipertahankan.
# --------------------------------------------------------------------------


def test_request_id_present_in_header_and_response_body(client, monkeypatch):
    _freeze_today(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])

    resp = _get_insights(client, user["token"], child["id"])
    header_id = resp.headers.get("X-Request-ID")
    assert header_id
    assert resp.get_json()["request_id"] == header_id


# --------------------------------------------------------------------------
# 29. Nggak ada regresi N+1 -- jumlah query TETAP kecil walau jumlah
# catatannya banyak.
# --------------------------------------------------------------------------


def test_no_n_plus_one_query_regression(client, monkeypatch):
    _freeze_today(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])
    cid = child["id"]

    for i in range(60):
        db.session.add(FeedingLog(
            child_id=cid, timestamp=datetime(2026, 8, 18, 0, 0, 0) + timedelta(minutes=i),
            feed_type="asi_langsung", volume_ml=100,
        ))
    db.session.commit()

    with count_queries() as counter:
        resp = _get_insights(client, user["token"], cid)
    assert resp.status_code == 200
    # Jumlah query WAJIB tetap kecil & TETAP (nggak proporsional ke 60
    # baris) -- kalau ada pola N+1 yang nyelip, ini bakal meledak jauh di
    # atas ambang longgar ini.
    assert counter[0] < 40, f"query count {counter[0]} -- kemungkinan ada pola N+1"


# --------------------------------------------------------------------------
# 30. Fitur statistik/laporan yang sudah ada tetap jalan normal.
# --------------------------------------------------------------------------


def test_existing_stats_endpoint_still_works(client, monkeypatch):
    _freeze_today(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])

    resp = client.get(f"/api/children/{child['id']}/stats?days=7", headers=auth_headers(user["token"]))
    assert resp.status_code == 200
    assert "averages" in resp.get_json()


# ============================================================================
# Review pasca-Phase-1 — Issue 1: health/growth/milestone-only data
# SEBELUMNYA salah dianggap "belum ada data sama sekali" karena
# `all_dates` cuma nyatuin 6 kategori "harian" (feeding/sleep/diaper/
# pumping/activity/mood), nggak pernah nyertain growth/temperature/
# medication/doctor-visit/illness/milestone. Lihat
# utils/insights_engine.py:build_insight_response().
# ============================================================================


def test_growth_only_data_in_period_counts_as_has_any_data(client, monkeypatch):
    _freeze_today(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])
    cid = child["id"]

    db.session.add(GrowthMeasurement(child_id=cid, measured_date=date(2026, 8, 19), weight_kg=5.0))
    db.session.commit()

    body = _get_insights(client, user["token"], cid).get_json()
    assert body["data_quality"]["has_any_data"] is True
    assert body["data_quality"]["days_with_records"] == 1
    assert body["metrics"]["growth"]["latest"]["measured_date"] == "2026-08-19"
    assert body["insights"] != [
        {"code": "insufficient_data", "severity": "info", "metric": None, "direction": None, "value": None}
    ]


def test_temperature_only_data_in_period_counts_as_has_any_data(client, monkeypatch):
    _freeze_today(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])
    cid = child["id"]

    db.session.add(TemperatureLog(child_id=cid, timestamp=datetime(2026, 8, 19, 8, 0, 0), temperature_celsius=37.2, method="ketiak"))
    db.session.commit()

    body = _get_insights(client, user["token"], cid).get_json()
    assert body["data_quality"]["has_any_data"] is True
    assert body["data_quality"]["days_with_records"] == 1
    assert body["metrics"]["health"]["temperature_record_count"] == 1
    assert body["insights"] != [
        {"code": "insufficient_data", "severity": "info", "metric": None, "direction": None, "value": None}
    ]


def test_medication_only_data_in_period_counts_as_has_any_data(client, monkeypatch):
    _freeze_today(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])
    cid = child["id"]

    db.session.add(MedicationLog(child_id=cid, timestamp=datetime(2026, 8, 19, 8, 0, 0), medication_name="Obat", dosage="5ml"))
    db.session.commit()

    body = _get_insights(client, user["token"], cid).get_json()
    assert body["data_quality"]["has_any_data"] is True
    assert body["data_quality"]["days_with_records"] == 1
    assert body["metrics"]["health"]["medication_event_count"] == 1
    assert body["insights"] != [
        {"code": "insufficient_data", "severity": "info", "metric": None, "direction": None, "value": None}
    ]


def test_doctor_visit_only_data_in_period_counts_as_has_any_data(client, monkeypatch):
    _freeze_today(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])
    cid = child["id"]

    db.session.add(DoctorVisitLog(child_id=cid, visit_date=date(2026, 8, 19), doctor_name="Dr. Test"))
    db.session.commit()

    body = _get_insights(client, user["token"], cid).get_json()
    assert body["data_quality"]["has_any_data"] is True
    assert body["data_quality"]["days_with_records"] == 1
    assert body["metrics"]["health"]["doctor_visit_count"] == 1
    assert body["insights"] != [
        {"code": "insufficient_data", "severity": "info", "metric": None, "direction": None, "value": None}
    ]


def test_illness_only_data_in_period_counts_as_has_any_data(client, monkeypatch):
    _freeze_today(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])
    cid = child["id"]

    db.session.add(IllnessLog(child_id=cid, illness_name="Flu", start_date=date(2026, 8, 19)))
    db.session.commit()

    body = _get_insights(client, user["token"], cid).get_json()
    assert body["data_quality"]["has_any_data"] is True
    assert body["data_quality"]["days_with_records"] == 1
    assert body["metrics"]["health"]["illness_record_count"] == 1
    assert body["insights"] != [
        {"code": "insufficient_data", "severity": "info", "metric": None, "direction": None, "value": None}
    ]


def test_milestone_only_data_in_period_counts_as_has_any_data(client, monkeypatch):
    _freeze_today(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])
    cid = child["id"]

    db.session.add(MilestoneLog(child_id=cid, milestone_type="bisa_duduk", achieved_date=date(2026, 8, 19)))
    db.session.commit()

    body = _get_insights(client, user["token"], cid).get_json()
    assert body["data_quality"]["has_any_data"] is True
    assert body["data_quality"]["days_with_records"] == 1
    assert body["metrics"]["milestones"]["count_in_period"] == 1
    assert body["insights"] != [
        {"code": "insufficient_data", "severity": "info", "metric": None, "direction": None, "value": None}
    ]


def test_lifetime_only_growth_measurement_does_not_count_as_current_period_activity(client, monkeypatch):
    _freeze_today(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])
    cid = child["id"]

    # measured_date JAUH sebelum periode sekarang (08-17..08-23) --
    # "terbaru" secara lifetime, TAPI BUKAN kejadian periode ini.
    db.session.add(GrowthMeasurement(child_id=cid, measured_date=date(2026, 6, 1), weight_kg=4.0))
    db.session.commit()

    body = _get_insights(client, user["token"], cid).get_json()
    # `latest` TETAP nunjuk measurement lama ini (kontrak lifetime yang
    # sudah didokumentasikan, requirement #4) ...
    assert body["metrics"]["growth"]["latest"]["measured_date"] == "2026-06-01"
    # ...TAPI has_any_data TETAP false -- measurement ini cuma "kebetulan
    # jadi yang terbaru", BUKAN aktivitas periode sekarang (requirement #3).
    assert body["data_quality"]["has_any_data"] is False
    assert body["data_quality"]["days_with_records"] == 0
    assert body["insights"] == [
        {"code": "insufficient_data", "severity": "info", "metric": None, "direction": None, "value": None}
    ]


def test_lifetime_only_temperature_and_milestone_do_not_count_as_current_period_activity(client, monkeypatch):
    _freeze_today(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])
    cid = child["id"]

    db.session.add(TemperatureLog(child_id=cid, timestamp=datetime(2026, 6, 1, 8, 0, 0), temperature_celsius=37.0, method="ketiak"))
    db.session.add(MilestoneLog(child_id=cid, milestone_type="bisa_duduk", achieved_date=date(2026, 6, 1)))
    db.session.commit()

    body = _get_insights(client, user["token"], cid).get_json()
    assert body["metrics"]["health"]["latest_temperature_celsius"] == 37.0  # lifetime tetap ditampilkan
    assert body["metrics"]["milestones"]["latest_milestone_type"] == "bisa_duduk"
    assert body["data_quality"]["has_any_data"] is False
    assert body["insights"] == [
        {"code": "insufficient_data", "severity": "info", "metric": None, "direction": None, "value": None}
    ]


def test_days_with_records_unions_all_supported_categories_on_the_same_day(client, monkeypatch):
    _freeze_today(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])
    cid = child["id"]

    same_day = date(2026, 8, 19)
    db.session.add(GrowthMeasurement(child_id=cid, measured_date=same_day, weight_kg=5.0))
    db.session.add(TemperatureLog(child_id=cid, timestamp=datetime(2026, 8, 19, 9, 0, 0), temperature_celsius=37.0, method="ketiak"))
    db.session.add(MilestoneLog(child_id=cid, milestone_type="bisa_duduk", achieved_date=same_day))
    db.session.add(IllnessLog(child_id=cid, illness_name="Flu", start_date=date(2026, 8, 20)))  # hari lain
    db.session.commit()

    body = _get_insights(client, user["token"], cid).get_json()
    assert body["data_quality"]["days_with_records"] == 2
    assert body["data_quality"]["has_any_data"] is True


# ============================================================================
# Review pasca-Phase-1 — Issue 2: feeding_volume_ml/pumping_volume_ml/
# activity_duration_minutes SEBELUMNYA memakai total mentah (sum of
# non-null, yang jadi 0 kalau semua event nggak punya nilai) langsung di
# perbandingan periode -- bikin -100%/+100% palsu pas 1 periode punya
# event tapi TIDAK SATU PUN keukur. Lihat
# utils/insights_engine.py:_measured_total_or_none()/build_comparison().
# ============================================================================


def test_feeding_volume_comparison_current_missing_previous_measured_produces_null_not_false_decrease(client, monkeypatch):
    _freeze_today(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])
    cid = child["id"]

    db.session.add(FeedingLog(child_id=cid, timestamp=datetime(2026, 8, 12, 8, 0, 0), feed_type="sufor", volume_ml=100))
    db.session.add(FeedingLog(child_id=cid, timestamp=datetime(2026, 8, 19, 8, 0, 0), feed_type="asi_langsung", volume_ml=None))
    db.session.commit()

    cmp_ = _get_insights(client, user["token"], cid).get_json()["comparisons"]["feeding_volume_ml"]
    assert cmp_["current"] is None
    assert cmp_["previous"] == 100
    assert cmp_["change"] is None
    assert cmp_["percent_change"] is None


def test_pumping_volume_comparison_current_missing_previous_measured_no_false_decrease_card(client, monkeypatch):
    _freeze_today(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])
    cid = child["id"]

    db.session.add(PumpingLog(child_id=cid, timestamp=datetime(2026, 8, 12, 8, 0, 0), volume_ml=200))
    db.session.add(PumpingLog(child_id=cid, timestamp=datetime(2026, 8, 19, 8, 0, 0), volume_ml=None))
    db.session.commit()

    body = _get_insights(client, user["token"], cid).get_json()
    cmp_ = body["comparisons"]["pumping_volume_ml"]
    assert cmp_["current"] is None
    assert cmp_["previous"] == 200
    assert cmp_["change"] is None
    assert cmp_["percent_change"] is None
    codes = [c["code"] for c in body["insights"]]
    assert "pumping_volume_decreased" not in codes
    assert "pumping_volume_increased" not in codes


def test_activity_duration_comparison_current_missing_previous_measured_no_false_decrease_card(client, monkeypatch):
    _freeze_today(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])
    cid = child["id"]

    db.session.add(ActivityLog(child_id=cid, timestamp=datetime(2026, 8, 12, 8, 0, 0), activity_type="stroll", duration_minutes=60))
    db.session.add(ActivityLog(child_id=cid, timestamp=datetime(2026, 8, 19, 8, 0, 0), activity_type="bathing", duration_minutes=None))
    db.session.commit()

    body = _get_insights(client, user["token"], cid).get_json()
    cmp_ = body["comparisons"]["activity_duration_minutes"]
    assert cmp_["current"] is None
    assert cmp_["previous"] == 60
    assert cmp_["change"] is None
    codes = [c["code"] for c in body["insights"]]
    assert "activity_duration_decreased" not in codes
    assert "activity_duration_increased" not in codes


def test_pumping_volume_comparison_current_measured_previous_unmeasured_produces_null_not_fabricated(client, monkeypatch):
    _freeze_today(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])
    cid = child["id"]

    db.session.add(PumpingLog(child_id=cid, timestamp=datetime(2026, 8, 12, 8, 0, 0), volume_ml=None))
    db.session.add(PumpingLog(child_id=cid, timestamp=datetime(2026, 8, 19, 8, 0, 0), volume_ml=250))
    db.session.commit()

    body = _get_insights(client, user["token"], cid).get_json()
    cmp_ = body["comparisons"]["pumping_volume_ml"]
    assert cmp_["current"] == 250
    assert cmp_["previous"] is None
    assert cmp_["change"] is None
    assert cmp_["percent_change"] is None
    codes = [c["code"] for c in body["insights"]]
    assert "pumping_volume_increased" not in codes
    assert "pumping_volume_decreased" not in codes


def test_pumping_volume_comparison_both_periods_unmeasured(client, monkeypatch):
    _freeze_today(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])
    cid = child["id"]

    db.session.add(PumpingLog(child_id=cid, timestamp=datetime(2026, 8, 12, 8, 0, 0), volume_ml=None))
    db.session.add(PumpingLog(child_id=cid, timestamp=datetime(2026, 8, 19, 8, 0, 0), volume_ml=None))
    db.session.commit()

    cmp_ = _get_insights(client, user["token"], cid).get_json()["comparisons"]["pumping_volume_ml"]
    assert cmp_ == {"current": None, "previous": None, "change": None, "percent_change": None}


def test_pumping_volume_comparison_both_periods_measured_computes_a_real_change(client, monkeypatch):
    _freeze_today(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])
    cid = child["id"]

    db.session.add(PumpingLog(child_id=cid, timestamp=datetime(2026, 8, 12, 8, 0, 0), volume_ml=100))
    db.session.add(PumpingLog(child_id=cid, timestamp=datetime(2026, 8, 19, 8, 0, 0), volume_ml=250))
    db.session.commit()

    body = _get_insights(client, user["token"], cid).get_json()
    assert body["comparisons"]["pumping_volume_ml"] == {
        "current": 250, "previous": 100, "change": 150, "percent_change": 150.0,
    }
    codes = [c["code"] for c in body["insights"]]
    assert "pumping_volume_increased" in codes


def test_pumping_volume_comparison_mixed_measured_and_unmeasured_uses_conservative_partial_sum(client, monkeypatch):
    """Kebijakan konservatif (didokumentasikan di INSIGHTS.md): data PARSIAL (sebagian event keukur) tetap dipakai apa adanya, TIDAK di-null-kan semua."""
    _freeze_today(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])
    cid = child["id"]

    db.session.add(PumpingLog(child_id=cid, timestamp=datetime(2026, 8, 19, 8, 0, 0), volume_ml=120))
    db.session.add(PumpingLog(child_id=cid, timestamp=datetime(2026, 8, 19, 12, 0, 0), volume_ml=None))
    db.session.add(PumpingLog(child_id=cid, timestamp=datetime(2026, 8, 12, 8, 0, 0), volume_ml=80))
    db.session.commit()

    body = _get_insights(client, user["token"], cid).get_json()
    cmp_ = body["comparisons"]["pumping_volume_ml"]
    assert cmp_["current"] == 120
    assert cmp_["previous"] == 80
    assert cmp_["change"] == 40
    assert body["metrics"]["pumping"]["session_count"] == 2
    assert body["metrics"]["pumping"]["events_with_volume"] == 1


def test_pumping_volume_zero_is_a_real_measured_value_not_missing_data(client, monkeypatch):
    _freeze_today(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])
    cid = child["id"]

    # DICATAT sebagai 0 literal (bukan None) -- model nggak melarang 0,
    # dan 0 di sini WAJIB diperlakukan beda dari "nggak ada nilai".
    db.session.add(PumpingLog(child_id=cid, timestamp=datetime(2026, 8, 19, 8, 0, 0), volume_ml=0))
    db.session.add(PumpingLog(child_id=cid, timestamp=datetime(2026, 8, 12, 8, 0, 0), volume_ml=50))
    db.session.commit()

    body = _get_insights(client, user["token"], cid).get_json()
    cmp_ = body["comparisons"]["pumping_volume_ml"]
    assert cmp_["current"] == 0
    assert cmp_["previous"] == 50
    assert cmp_["change"] == -50
    assert body["metrics"]["pumping"]["events_with_volume"] == 1


def test_pumping_volume_no_events_at_all_is_a_confirmed_zero_not_unmeasured(client, monkeypatch):
    """'Nggak ada event sama sekali' TETAP angka 0 yang sah (beda dari 'ada event tapi nggak keukur', yang jadi None)."""
    _freeze_today(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])
    cid = child["id"]

    db.session.add(PumpingLog(child_id=cid, timestamp=datetime(2026, 8, 19, 8, 0, 0), volume_ml=150))
    # TIDAK ADA PumpingLog SAMA SEKALI di periode sebelumnya.
    db.session.commit()

    body = _get_insights(client, user["token"], cid).get_json()
    cmp_ = body["comparisons"]["pumping_volume_ml"]
    assert cmp_["current"] == 150
    assert cmp_["previous"] == 0
    assert cmp_["change"] == 150
    assert cmp_["percent_change"] is None  # previous==0 -> null (aturan lama, bukan bug baru)
    codes = [c["code"] for c in body["insights"]]
    assert "pumping_volume_increased" in codes  # naik dari 0 TETAP observasi valid
