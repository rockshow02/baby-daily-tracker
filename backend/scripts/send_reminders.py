"""
Kirim reminder + ringkasan harian via Telegram — pengganti n8n (yang sekarang
cuma trial 14 hari buat versi Cloud-nya). Langsung manggil Telegram Bot API,
gratis selamanya.

SENGAJA TANPA AI: ringkasan disusun dari template teks biasa, bukan di-generate
model bahasa. Datanya data kesehatan bayi — akurasi harus 100% terjamin dan
persis sama kayak yang ditampilin di app, bukan "diparafrase ulang" yang
berisiko meleset walau kecil. Tips di bagian bawah juga diambil dari artikel
yang udah ada di database (ditulis manusia/dikurasi dari IDAI-Kemenkes),
bukan dikarang AI.

Isi pesan per anak:
  1. Alert urgent (kalau ada): vaksin wajib jatuh tempo, kontrol dokter besok
  2. Ringkasan aktivitas hari ini: menyusui, tidur, popok — dibandingin ke
     acuan IDAI/WHO yang sama persis kayak dipakai di app (status kurang/
     cukup/lebih)
  3. Satu tips random yang relevan sesuai usia anak saat ini, dari artikel
     yang udah ada (internal maupun eksternal)

CARA SETUP: lihat docstring lama / panduan yang udah dikasih ke user.
CARA JADWALIN (PythonAnywhere, tab Tasks, gratis 1 task/hari):
  python3.10 /home/USERNAME/baby-daily-tracker/backend/scripts/send_reminders.py
"""
import os
import random
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from extensions import db
from models import (
    Child, ChildCaregiver, User, VaccineSchedule, ChildVaccination,
    DoctorVisitLog, FeedingLog, SleepLog, DiaperLog, Article,
)
from utils.telegram import send_telegram_message
from utils.timezone_utils import today_wib, now_wib
from utils.summary_engine import build_daily_summary

FEEDING_OVERDUE_HOURS = 6


def _age_in_months(birth_date, on_date):
    return (
        (on_date.year - birth_date.year) * 12
        + (on_date.month - birth_date.month)
        - (1 if on_date.day < birth_date.day else 0)
    )


def _caregivers_with_telegram(child_id):
    return (
        db.session.query(User)
        .join(ChildCaregiver, ChildCaregiver.user_id == User.id)
        .filter(ChildCaregiver.child_id == child_id, User.telegram_chat_id.isnot(None))
        .all()
    )


# ---------- ALERT URGENT ----------

def check_vaccine_overdue(child):
    age_months = _age_in_months(child.birth_date, today_wib())
    schedule = VaccineSchedule.query.filter_by(category="wajib").order_by(VaccineSchedule.order_index.asc()).all()
    given_ids = {
        cv.vaccine_schedule_id
        for cv in ChildVaccination.query.filter_by(child_id=child.id, given=True).all()
    }
    overdue = [v for v in schedule if v.id not in given_ids and v.recommended_age_months <= age_months]
    if not overdue:
        return None
    earliest = min(overdue, key=lambda v: v.recommended_age_months)
    extra = f" (+{len(overdue) - 1} vaksin lain juga tertunda)" if len(overdue) > 1 else ""
    return f"💉 Vaksin <b>{earliest.vaccine_name}</b> sudah jatuh tempo{extra}."


def check_doctor_visit_tomorrow(child):
    tomorrow = today_wib() + timedelta(days=1)
    visit = DoctorVisitLog.query.filter_by(child_id=child.id, next_visit_date=tomorrow).first()
    if not visit:
        return None
    return f"🩺 Jadwal kontrol dokter besok ({tomorrow.strftime('%d %b %Y')})."


URGENT_CHECKS = [check_vaccine_overdue, check_doctor_visit_tomorrow]


# ---------- RINGKASAN HARIAN ----------

def _status_emoji(status):
    return {"kurang": "⬇️", "cukup": "✅", "lebih": "⬆️"}.get(status, "")


def build_digest(child):
    target_date = today_wib()

    feeding_count = FeedingLog.query.filter(
        FeedingLog.child_id == child.id,
        db.func.date(FeedingLog.timestamp) == target_date,
    ).count()

    day_start = now_wib().replace(hour=0, minute=0, second=0, microsecond=0)
    day_end = day_start + timedelta(days=1)
    sleep_logs = SleepLog.query.filter(
        SleepLog.child_id == child.id,
        SleepLog.start_time < day_end,
        db.or_(SleepLog.end_time.is_(None), SleepLog.end_time > day_start),
    ).all()
    sleep_minutes = 0
    for log in sleep_logs:
        seg_start = max(log.start_time, day_start)
        seg_end = min(log.end_time, day_end) if log.end_time else min(now_wib(), day_end)
        if seg_end > seg_start:
            sleep_minutes += (seg_end - seg_start).total_seconds() / 60
    sleep_hours = round(sleep_minutes / 60, 1)

    wet_count = DiaperLog.query.filter(
        DiaperLog.child_id == child.id,
        db.func.date(DiaperLog.timestamp) == target_date,
        DiaperLog.diaper_type.in_(["pipis", "keduanya"]),
    ).count()
    bab_count = DiaperLog.query.filter(
        DiaperLog.child_id == child.id,
        db.func.date(DiaperLog.timestamp) == target_date,
        DiaperLog.diaper_type.in_(["pup", "keduanya"]),
    ).count()

    summary = build_daily_summary(
        child=child, on_date=target_date,
        feeding_count=feeding_count, sleep_hours=sleep_hours,
        wet_diaper_count=wet_count, bab_count=bab_count,
    )

    if "feeding" not in summary:
        return None  # anak di luar rentang 0-2 tahun, nggak ada acuan buat dibandingin

    lines = ["📋 <b>Ringkasan Hari Ini</b>"]
    f = summary["feeding"]
    lines.append(f"🍼 Menyusui: {f['actual']}x {_status_emoji(f['status'])}")
    s = summary["sleep"]
    lines.append(f"😴 Tidur: {s['actual_hours']} jam {_status_emoji(s['status'])}")
    lines.append(f"👶 Popok: {wet_count}x pipis, {bab_count}x pup")

    return "\n".join(lines)


# ---------- TIPS SESUAI USIA ----------

def pick_random_tip(child):
    age_months = _age_in_months(child.birth_date, today_wib())
    # cuma dari artikel INTERNAL (source_url kosong) — isinya (body) lengkap
    # & informatif karena ditulis sendiri, beda dari artikel eksternal yang
    # body-nya sengaja cuma cuplikan pendek (nggak boleh reproduksi konten
    # berhak cipta orang lain, jadi kurang cocok buat ditampilin utuh di sini)
    candidates = Article.query.filter(Article.source_url.is_(None)).all()
    matching = [
        a for a in candidates
        if (a.min_age_months is None or age_months >= a.min_age_months)
        and (a.max_age_months is None or age_months <= a.max_age_months)
    ]
    if not matching:
        return None

    # ROTASI: pilih yang paling lama nggak pernah ditampilin (belum pernah
    # ditampilin = paling diprioritaskan), bukan asal random — biar nggak
    # ada yang keulang sebelum semua tips lain di kategori usia itu abis
    # ditampilin dulu. random.shuffle buat mecah "seri" kalau ada beberapa
    # yang sama-sama belum pernah ditampilin, biar urutannya nggak monoton.
    random.shuffle(matching)
    picked = min(matching, key=lambda a: a.last_tip_shown_at or datetime(2000, 1, 1))

    picked.last_tip_shown_at = now_wib()
    db.session.commit()

    return f"💡 <b>Tips hari ini: {picked.title}</b>\n{picked.body}"


# ---------- RUN ----------

def run():
    app = create_app()
    with app.app_context():
        children = Child.query.all()
        sent_count = 0
        skipped_no_telegram = 0

        for child in children:
            caregivers = _caregivers_with_telegram(child.id)
            if not caregivers:
                skipped_no_telegram += 1
                continue

            sections = [f"👶 <b>{child.nickname or child.name}</b>"]

            urgent = [msg for check in URGENT_CHECKS if (msg := check(child))]
            if urgent:
                sections.append("\n".join(urgent))

            digest = build_digest(child)
            if digest:
                sections.append(digest)

            tip = pick_random_tip(child)
            if tip:
                sections.append(tip)

            text = "\n\n".join(sections)

            for user in caregivers:
                if send_telegram_message(user.telegram_chat_id, text):
                    sent_count += 1
                    print(f"  Terkirim ke {user.name} ({user.email}) soal {child.name}")
                else:
                    print(f"  GAGAL kirim ke {user.name} ({user.email})")

        print(f"\nSelesai. Notifikasi terkirim: {sent_count}. "
              f"Anak tanpa pengasuh ber-Telegram: {skipped_no_telegram}.")


if __name__ == "__main__":
    run()