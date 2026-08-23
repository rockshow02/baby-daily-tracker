from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash

from extensions import db
from utils.timezone_utils import now_wib


class User(db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    telegram_chat_id = db.Column(db.String(50), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    children = db.relationship("Child", backref="owner", lazy="dynamic", cascade="all, delete-orphan")

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def to_dict(self):
        return {"id": self.id, "name": self.name, "email": self.email, "telegram_chat_id": self.telegram_chat_id}


class Child(db.Model):
    __tablename__ = "children"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)

    name = db.Column(db.String(100), nullable=False)
    nickname = db.Column(db.String(30), nullable=True)  # nama panggilan, buat tampilan ringkas di Dashboard
    birth_date = db.Column(db.Date, nullable=False)
    gender = db.Column(db.String(10), nullable=True)  # 'L' | 'P'

    birth_weight_kg = db.Column(db.Float, nullable=True)
    birth_height_cm = db.Column(db.Float, nullable=True)
    photo_filename = db.Column(db.String(255), nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    feeding_logs = db.relationship("FeedingLog", backref="child", lazy="dynamic", cascade="all, delete-orphan")
    sleep_logs = db.relationship("SleepLog", backref="child", lazy="dynamic", cascade="all, delete-orphan")
    diaper_logs = db.relationship("DiaperLog", backref="child", lazy="dynamic", cascade="all, delete-orphan")
    vaccinations = db.relationship(
        "ChildVaccination", backref="child", lazy="dynamic", cascade="all, delete-orphan"
    )
    # `idempotency_keys` SEBELUMNYA nggak punya relationship cascade sama
    # sekali (beda dari SEMUA tabel child-scoped lain — termasuk
    # `child_caregivers`, yang cascade-nya UDAH ada dari sisi lain, lihat
    # `ChildCaregiver.child` -> backref `Child.caregivers` di bawah) —
    # nggak ketauan selama ini soalnya SQLite nggak nge-enforce FK per
    # default (lihat extensions.py, yang sekarang MENYALAKAN PRAGMA
    # foreign_keys=ON permanen buat kebutuhan Issue 2 audit trail). Begitu
    # FK beneran ditegakkan, hapus 1 Child yang masih py idempotency key
    # (mis. abis dipakai idempotent_create() buat 1 log-nya) TANPA cascade
    # ini bakal gagal IntegrityError — ditambahin di sini biar KONSISTEN
    # sama pola cascade semua tabel child-scoped lain, BUKAN pengecualian.
    idempotency_keys = db.relationship(
        "IdempotencyKey", backref="child", lazy="dynamic", cascade="all, delete-orphan"
    )

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "nickname": self.nickname,
            "birth_date": self.birth_date.isoformat(),
            "gender": self.gender,
            "birth_weight_kg": self.birth_weight_kg,
            "birth_height_cm": self.birth_height_cm,
            "photo_filename": self.photo_filename,
        }


class FeedingLog(db.Model):
    __tablename__ = "feeding_logs"

    id = db.Column(db.Integer, primary_key=True)
    child_id = db.Column(db.Integer, db.ForeignKey("children.id"), nullable=False, index=True)

    timestamp = db.Column(db.DateTime, nullable=False, default=now_wib, index=True)

    # 'asi_langsung' | 'asi_perah' | 'sufor' | 'mpasi'
    feed_type = db.Column(db.String(20), nullable=False)

    duration_minutes = db.Column(db.Integer, nullable=True)   # asi_langsung
    volume_ml = db.Column(db.Integer, nullable=True)          # asi_perah/sufor/mpasi
    breast_side = db.Column(db.String(10), nullable=True)     # 'kiri' | 'kanan' | 'kedua'

    notes = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    created_by_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    creator = db.relationship("User", foreign_keys=[created_by_user_id])

    def to_dict(self):
        return {
            "id": self.id,
            "child_id": self.child_id,
            "timestamp": self.timestamp.isoformat() + "+07:00",
            "feed_type": self.feed_type,
            "duration_minutes": self.duration_minutes,
            "volume_ml": self.volume_ml,
            "breast_side": self.breast_side,
            "notes": self.notes,
            "created_by_user_id": self.created_by_user_id,
            "created_by_name": self.creator.name if self.creator else None,
        }


class SleepLog(db.Model):
    __tablename__ = "sleep_logs"

    id = db.Column(db.Integer, primary_key=True)
    child_id = db.Column(db.Integer, db.ForeignKey("children.id"), nullable=False, index=True)

    start_time = db.Column(db.DateTime, nullable=False, default=now_wib, index=True)
    end_time = db.Column(db.DateTime, nullable=True)  # null = sesi masih berjalan

    sleep_type = db.Column(db.String(10), nullable=False, default="siang")  # 'siang' | 'malam'

    notes = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    created_by_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    creator = db.relationship("User", foreign_keys=[created_by_user_id])

    @property
    def duration_minutes(self):
        if not self.end_time:
            return None
        return round((self.end_time - self.start_time).total_seconds() / 60)

    def to_dict(self):
        return {
            "id": self.id,
            "child_id": self.child_id,
            "start_time": self.start_time.isoformat() + "+07:00",
            "end_time": (self.end_time.isoformat() + "+07:00") if self.end_time else None,
            "sleep_type": self.sleep_type,
            "duration_minutes": self.duration_minutes,
            "notes": self.notes,
            "created_by_user_id": self.created_by_user_id,
            "created_by_name": self.creator.name if self.creator else None,
        }


class DiaperLog(db.Model):
    __tablename__ = "diaper_logs"

    id = db.Column(db.Integer, primary_key=True)
    child_id = db.Column(db.Integer, db.ForeignKey("children.id"), nullable=False, index=True)

    timestamp = db.Column(db.DateTime, nullable=False, default=now_wib, index=True)

    diaper_type = db.Column(db.String(10), nullable=False)  # 'pipis' | 'pup' | 'keduanya'

    # khusus pup/keduanya — indikator kesehatan pencernaan
    consistency = db.Column(db.String(15), nullable=True)  # normal/keras/cair/berlendir/berdarah
    color = db.Column(db.String(30), nullable=True)

    notes = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    created_by_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    creator = db.relationship("User", foreign_keys=[created_by_user_id])

    def to_dict(self):
        return {
            "id": self.id,
            "child_id": self.child_id,
            "timestamp": self.timestamp.isoformat() + "+07:00",
            "diaper_type": self.diaper_type,
            "consistency": self.consistency,
            "color": self.color,
            "notes": self.notes,
            "created_by_user_id": self.created_by_user_id,
            "created_by_name": self.creator.name if self.creator else None,
        }


class FeedingGuideline(db.Model):
    """
    Tabel acuan statis (di-seed sekali, bukan data user).
    Sumber: IDAI (frekuensi menyusui, BAK/BAB) + konsensus AAP/National
    Sleep Foundation (durasi tidur).
    """
    __tablename__ = "feeding_guidelines"

    id = db.Column(db.Integer, primary_key=True)
    age_min_days = db.Column(db.Integer, nullable=False)
    age_max_days = db.Column(db.Integer, nullable=False)
    label = db.Column(db.String(50), nullable=False)

    min_feeds_per_day = db.Column(db.Integer, nullable=True)
    max_feeds_per_day = db.Column(db.Integer, nullable=True)

    min_sleep_hours = db.Column(db.Float, nullable=True)
    max_sleep_hours = db.Column(db.Float, nullable=True)

    min_wet_diapers = db.Column(db.Integer, nullable=True)
    min_bab_per_day = db.Column(db.Integer, nullable=True)

    notes = db.Column(db.Text, nullable=True)
    source = db.Column(db.String(50), default="IDAI/AAP")

    def to_dict(self):
        return {
            "id": self.id,
            "label": self.label,
            "age_min_days": self.age_min_days,
            "age_max_days": self.age_max_days,
            "min_feeds_per_day": self.min_feeds_per_day,
            "max_feeds_per_day": self.max_feeds_per_day,
            "min_sleep_hours": self.min_sleep_hours,
            "max_sleep_hours": self.max_sleep_hours,
            "min_wet_diapers": self.min_wet_diapers,
            "min_bab_per_day": self.min_bab_per_day,
            "notes": self.notes,
            "source": self.source,
        }


class VaccineSchedule(db.Model):
    """
    Tabel acuan jadwal imunisasi (statis, di-seed sekali, bukan data user).
    Sumber: Kementerian Kesehatan RI (ayosehat.kemkes.go.id) — Tabel Jadwal
    Pemberian Imunisasi Bayi dan Baduta.
    """
    __tablename__ = "vaccine_schedules"

    id = db.Column(db.Integer, primary_key=True)
    vaccine_name = db.Column(db.String(50), nullable=False)   # "BCG", "Polio Tetes 1", dst
    dose_label = db.Column(db.String(50), nullable=True)      # "Dosis 1", null kalau cuma sekali
    recommended_age_months = db.Column(db.Integer, nullable=False)
    is_optional = db.Column(db.Boolean, default=False)        # mis. JE khusus wilayah endemis
    category = db.Column(db.String(10), nullable=False, default="wajib")  # 'wajib' | 'tambahan'
    notes = db.Column(db.Text, nullable=True)
    order_index = db.Column(db.Integer, default=0)            # urutan tampil
    source = db.Column(db.String(50), default="Kemenkes RI")

    def to_dict(self):
        return {
            "id": self.id,
            "vaccine_name": self.vaccine_name,
            "dose_label": self.dose_label,
            "recommended_age_months": self.recommended_age_months,
            "is_optional": self.is_optional,
            "category": self.category,
            "notes": self.notes,
            "source": self.source,
        }


class ChildVaccination(db.Model):
    """Status vaksinasi aktual per anak, relasi ke VaccineSchedule."""
    __tablename__ = "child_vaccinations"
    __table_args__ = (db.UniqueConstraint("child_id", "vaccine_schedule_id", name="uq_child_vaccine"),)

    id = db.Column(db.Integer, primary_key=True)
    child_id = db.Column(db.Integer, db.ForeignKey("children.id"), nullable=False, index=True)
    vaccine_schedule_id = db.Column(db.Integer, db.ForeignKey("vaccine_schedules.id"), nullable=False)

    given = db.Column(db.Boolean, default=False, nullable=False)
    given_date = db.Column(db.Date, nullable=True)
    notes = db.Column(db.Text, nullable=True)

    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    vaccine = db.relationship("VaccineSchedule")

    def to_dict(self):
        return {
            "id": self.id,
            "child_id": self.child_id,
            "vaccine_schedule_id": self.vaccine_schedule_id,
            "vaccine_name": self.vaccine.vaccine_name,
            "dose_label": self.vaccine.dose_label,
            "recommended_age_months": self.vaccine.recommended_age_months,
            "given": self.given,
            "given_date": self.given_date.isoformat() if self.given_date else None,
        }


class PumpingLog(db.Model):
    """
    Sesi memerah ASI (bukan bayi minum langsung, jadi terpisah dari FeedingLog
    supaya tidak ikut kehitung di angka "menyusui X kali/hari").
    """
    __tablename__ = "pumping_logs"

    id = db.Column(db.Integer, primary_key=True)
    child_id = db.Column(db.Integer, db.ForeignKey("children.id"), nullable=False, index=True)

    timestamp = db.Column(db.DateTime, nullable=False, default=now_wib, index=True)
    duration_minutes = db.Column(db.Integer, nullable=True)
    volume_ml = db.Column(db.Integer, nullable=True)
    breast_side = db.Column(db.String(10), nullable=True)  # 'kiri' | 'kanan' | 'kedua'

    notes = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    created_by_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    creator = db.relationship("User", foreign_keys=[created_by_user_id])

    child = db.relationship("Child", backref=db.backref("pumping_logs", lazy="dynamic", cascade="all, delete-orphan"))

    def to_dict(self):
        return {
            "id": self.id,
            "child_id": self.child_id,
            "timestamp": self.timestamp.isoformat() + "+07:00",
            "duration_minutes": self.duration_minutes,
            "volume_ml": self.volume_ml,
            "breast_side": self.breast_side,
            "notes": self.notes,
            "created_by_user_id": self.created_by_user_id,
            "created_by_name": self.creator.name if self.creator else None,
        }


class ActivityLog(db.Model):
    """
    Aktivitas ringan generik (jalan-jalan, mandi, dst). Sengaja dibuat generik
    (bukan tabel terpisah per jenis) karena strukturnya sama-sama sederhana:
    cukup waktu + durasi + catatan. Menambah jenis aktivitas baru nanti tinggal
    tambah value baru di activity_type, tidak perlu tabel baru.
    """
    __tablename__ = "activity_logs"

    id = db.Column(db.Integer, primary_key=True)
    child_id = db.Column(db.Integer, db.ForeignKey("children.id"), nullable=False, index=True)

    activity_type = db.Column(db.String(20), nullable=False)  # 'stroll' | 'bathing'
    timestamp = db.Column(db.DateTime, nullable=False, default=now_wib, index=True)
    duration_minutes = db.Column(db.Integer, nullable=True)

    notes = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    created_by_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    creator = db.relationship("User", foreign_keys=[created_by_user_id])

    child = db.relationship("Child", backref=db.backref("activity_logs", lazy="dynamic", cascade="all, delete-orphan"))

    def to_dict(self):
        return {
            "id": self.id,
            "child_id": self.child_id,
            "activity_type": self.activity_type,
            "timestamp": self.timestamp.isoformat() + "+07:00",
            "duration_minutes": self.duration_minutes,
            "notes": self.notes,
            "created_by_user_id": self.created_by_user_id,
            "created_by_name": self.creator.name if self.creator else None,
        }


class GrowthReference(db.Model):
    """
    Tabel acuan LMS WHO Child Growth Standards (statis, di-seed sekali).
    Dipakai untuk menghitung z-score/persentil berat, tinggi, dan lingkar
    kepala anak dibanding standar pertumbuhan WHO.
    """
    __tablename__ = "growth_references"
    __table_args__ = (
        db.UniqueConstraint("measurement_type", "gender", "age_months", name="uq_growth_ref"),
    )

    id = db.Column(db.Integer, primary_key=True)
    measurement_type = db.Column(db.String(20), nullable=False)  # 'weight' | 'height' | 'head_circumference'
    gender = db.Column(db.String(10), nullable=False)            # 'L' | 'P'
    age_months = db.Column(db.Integer, nullable=False)
    L = db.Column(db.Float, nullable=False)
    M = db.Column(db.Float, nullable=False)
    S = db.Column(db.Float, nullable=False)


class GrowthMeasurement(db.Model):
    """Catatan ukur berat/tinggi/lingkar kepala anak (biasanya 1 baris per kunjungan)."""
    __tablename__ = "growth_measurements"

    id = db.Column(db.Integer, primary_key=True)
    child_id = db.Column(db.Integer, db.ForeignKey("children.id"), nullable=False, index=True)

    measured_date = db.Column(db.Date, nullable=False, index=True)
    weight_kg = db.Column(db.Float, nullable=True)
    height_cm = db.Column(db.Float, nullable=True)
    head_circumference_cm = db.Column(db.Float, nullable=True)

    notes = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    created_by_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    creator = db.relationship("User", foreign_keys=[created_by_user_id])

    child = db.relationship(
        "Child", backref=db.backref("growth_measurements", lazy="dynamic", cascade="all, delete-orphan")
    )

    def to_dict(self):
        return {
            "id": self.id,
            "child_id": self.child_id,
            "measured_date": self.measured_date.isoformat(),
            "weight_kg": self.weight_kg,
            "height_cm": self.height_cm,
            "head_circumference_cm": self.head_circumference_cm,
            "notes": self.notes,
            "created_by_user_id": self.created_by_user_id,
            "created_by_name": self.creator.name if self.creator else None,
        }


class DoctorVisitLog(db.Model):
    """Catatan kunjungan ke dokter/klinik."""
    __tablename__ = "doctor_visit_logs"

    id = db.Column(db.Integer, primary_key=True)
    child_id = db.Column(db.Integer, db.ForeignKey("children.id"), nullable=False, index=True)

    visit_date = db.Column(db.Date, nullable=False, index=True)
    doctor_name = db.Column(db.String(100), nullable=True)
    clinic_name = db.Column(db.String(150), nullable=True)
    reason = db.Column(db.String(255), nullable=True)      # keluhan/alasan kunjungan
    diagnosis = db.Column(db.String(255), nullable=True)
    next_visit_date = db.Column(db.Date, nullable=True)     # jadwal kontrol berikutnya

    notes = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    created_by_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    creator = db.relationship("User", foreign_keys=[created_by_user_id])

    child = db.relationship(
        "Child", backref=db.backref("doctor_visit_logs", lazy="dynamic", cascade="all, delete-orphan")
    )

    def to_dict(self):
        return {
            "id": self.id,
            "child_id": self.child_id,
            "visit_date": self.visit_date.isoformat(),
            "doctor_name": self.doctor_name,
            "clinic_name": self.clinic_name,
            "reason": self.reason,
            "diagnosis": self.diagnosis,
            "next_visit_date": self.next_visit_date.isoformat() if self.next_visit_date else None,
            "notes": self.notes,
            "created_by_user_id": self.created_by_user_id,
            "created_by_name": self.creator.name if self.creator else None,
        }


class TemperatureLog(db.Model):
    """Catatan suhu tubuh (buat pantau demam)."""
    __tablename__ = "temperature_logs"

    id = db.Column(db.Integer, primary_key=True)
    child_id = db.Column(db.Integer, db.ForeignKey("children.id"), nullable=False, index=True)

    timestamp = db.Column(db.DateTime, nullable=False, default=now_wib, index=True)
    temperature_celsius = db.Column(db.Float, nullable=False)
    method = db.Column(db.String(10), nullable=False, default="ketiak")  # ketiak|dahi|telinga|mulut|dubur

    notes = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    created_by_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    creator = db.relationship("User", foreign_keys=[created_by_user_id])

    child = db.relationship(
        "Child", backref=db.backref("temperature_logs", lazy="dynamic", cascade="all, delete-orphan")
    )

    def to_dict(self):
        return {
            "id": self.id,
            "child_id": self.child_id,
            "timestamp": self.timestamp.isoformat() + "+07:00",
            "temperature_celsius": self.temperature_celsius,
            "method": self.method,
            "notes": self.notes,
            "created_by_user_id": self.created_by_user_id,
            "created_by_name": self.creator.name if self.creator else None,
        }


class IllnessLog(db.Model):
    """Catatan sakit/penyakit (bisa berlangsung beberapa hari)."""
    __tablename__ = "illness_logs"

    id = db.Column(db.Integer, primary_key=True)
    child_id = db.Column(db.Integer, db.ForeignKey("children.id"), nullable=False, index=True)

    illness_name = db.Column(db.String(150), nullable=False)
    start_date = db.Column(db.Date, nullable=False)
    end_date = db.Column(db.Date, nullable=True)  # null = masih berlangsung
    symptoms = db.Column(db.Text, nullable=True)

    notes = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    created_by_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    creator = db.relationship("User", foreign_keys=[created_by_user_id])

    child = db.relationship(
        "Child", backref=db.backref("illness_logs", lazy="dynamic", cascade="all, delete-orphan")
    )
    medications = db.relationship(
        "MedicationLog", backref="illness", lazy="dynamic", cascade="all, delete-orphan"
    )

    def to_dict(self):
        return {
            "id": self.id,
            "child_id": self.child_id,
            "illness_name": self.illness_name,
            "start_date": self.start_date.isoformat(),
            "end_date": self.end_date.isoformat() if self.end_date else None,
            "symptoms": self.symptoms,
            "notes": self.notes,
            "is_ongoing": self.end_date is None,
            "created_by_user_id": self.created_by_user_id,
            "created_by_name": self.creator.name if self.creator else None,
        }


class MedicationLog(db.Model):
    """Catatan pemberian obat, bisa dikaitkan ke catatan sakit tertentu (opsional)."""
    __tablename__ = "medication_logs"

    id = db.Column(db.Integer, primary_key=True)
    child_id = db.Column(db.Integer, db.ForeignKey("children.id"), nullable=False, index=True)
    illness_id = db.Column(db.Integer, db.ForeignKey("illness_logs.id"), nullable=True)

    medication_name = db.Column(db.String(150), nullable=False)
    dosage = db.Column(db.String(100), nullable=True)  # cth. "0.8 ml", "1 sendok takar"
    timestamp = db.Column(db.DateTime, nullable=False, default=now_wib, index=True)

    notes = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    created_by_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    creator = db.relationship("User", foreign_keys=[created_by_user_id])

    child = db.relationship(
        "Child", backref=db.backref("medication_logs", lazy="dynamic", cascade="all, delete-orphan")
    )

    def to_dict(self):
        return {
            "id": self.id,
            "child_id": self.child_id,
            "illness_id": self.illness_id,
            "medication_name": self.medication_name,
            "dosage": self.dosage,
            "timestamp": self.timestamp.isoformat() + "+07:00",
            "notes": self.notes,
            "created_by_user_id": self.created_by_user_id,
            "created_by_name": self.creator.name if self.creator else None,
        }


class MoodLog(db.Model):
    """Catatan suasana hati bayi."""
    __tablename__ = "mood_logs"

    id = db.Column(db.Integer, primary_key=True)
    child_id = db.Column(db.Integer, db.ForeignKey("children.id"), nullable=False, index=True)

    timestamp = db.Column(db.DateTime, nullable=False, default=now_wib, index=True)
    mood = db.Column(db.String(15), nullable=False)  # 'ceria' | 'baik' | 'sedih' | 'menangis'

    notes = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    created_by_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    creator = db.relationship("User", foreign_keys=[created_by_user_id])

    child = db.relationship("Child", backref=db.backref("mood_logs", lazy="dynamic", cascade="all, delete-orphan"))

    def to_dict(self):
        return {
            "id": self.id,
            "child_id": self.child_id,
            "timestamp": self.timestamp.isoformat() + "+07:00",
            "mood": self.mood,
            "notes": self.notes,
            "created_by_user_id": self.created_by_user_id,
            "created_by_name": self.creator.name if self.creator else None,
        }


class MilestoneLog(db.Model):
    """Momen penting tumbuh kembang (langkah pertama, gigi pertama, dst)."""
    __tablename__ = "milestone_logs"

    id = db.Column(db.Integer, primary_key=True)
    child_id = db.Column(db.Integer, db.ForeignKey("children.id"), nullable=False, index=True)

    # 'bisa_duduk' | 'langkah_pertama' | 'kata_pertama' | 'gigi_pertama' | 'custom'
    milestone_type = db.Column(db.String(30), nullable=False)
    custom_label = db.Column(db.String(100), nullable=True)  # dipakai kalau milestone_type == 'custom'
    achieved_date = db.Column(db.Date, nullable=False)

    notes = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    created_by_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    creator = db.relationship("User", foreign_keys=[created_by_user_id])

    child = db.relationship(
        "Child", backref=db.backref("milestone_logs", lazy="dynamic", cascade="all, delete-orphan")
    )

    def to_dict(self):
        return {
            "id": self.id,
            "child_id": self.child_id,
            "milestone_type": self.milestone_type,
            "custom_label": self.custom_label,
            "achieved_date": self.achieved_date.isoformat(),
            "notes": self.notes,
            "created_by_user_id": self.created_by_user_id,
            "created_by_name": self.creator.name if self.creator else None,
        }



class ChildCaregiver(db.Model):
    """
    Relasi banyak-ke-banyak antara User dan Child — satu anak bisa punya
    beberapa pengasuh (orang tua, ART, dll), satu akun bisa akses beberapa anak.

    Baris di tabel ini CUMA PERNAH merepresentasikan caregiver NON-PEMILIK
    (`role` CUMA boleh `'editor'` atau `'viewer'`, ditegakkan CHECK
    constraint di bawah — lihat Caregiver Roles & Permissions Phase 1,
    backend/docs/ROLES_PERMISSIONS.md). PEMILIK anak SENGAJA TIDAK PERNAH
    punya baris di sini — status pemilik SATU-SATUNYA sumber kebenarannya
    tetap `Child.user_id` (lihat utils/access.py:resolve_role()), BUKAN
    baris `role='owner'` di tabel ini kayak versi sebelumnya (yang bikin
    2 sumber kebenaran ganda/kontradiktif buat 1 hal yang sama). Migrasi
    Phase 1 (scripts/migrate_production.py) MENGHAPUS baris `role='owner'`
    lama yang tersisa dari versi sebelumnya, dan mengonversi baris
    `role='caregiver'` lama jadi `'editor'` (persis perilaku lama —
    caregiver yang diundang SEBELUM fitur role ini selalu bisa
    create/update/delete, sama kayak editor sekarang).
    """
    __tablename__ = "child_caregivers"
    __table_args__ = (
        db.UniqueConstraint("child_id", "user_id", name="uq_child_caregiver"),
        db.CheckConstraint("role IN ('editor', 'viewer')", name="ck_child_caregivers_role"),
    )

    id = db.Column(db.Integer, primary_key=True)
    child_id = db.Column(db.Integer, db.ForeignKey("children.id"), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)

    role = db.Column(db.String(15), nullable=False, default="editor")  # 'editor' | 'viewer' — LIHAT docstring kelas
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship("User")
    child = db.relationship(
        "Child", backref=db.backref("caregivers", lazy="dynamic", cascade="all, delete-orphan")
    )

    def to_dict(self):
        """
        SENGAJA nyertain email apa adanya, TANPA cek siapa yang minta —
        model nggak boleh (dan nggak bisa) tau konteks otorisasi
        pemanggilnya. CUMA aman dipanggil dari endpoint yang SUDAH
        ditegakkan owner-only di layer route (update_caregiver_role,
        remove_caregiver — lihat routes/children_routes.py). Endpoint
        BACA yang bisa diakses editor/viewer juga (list_caregivers)
        SENGAJA TIDAK PERNAH manggil method ini — dia punya serializer
        eksplisit sendiri (`_caregiver_entry()`) yang cuma nyertain email
        kalau peminta-nya kebukti owner (Issue 2, lihat
        backend/docs/ROLES_PERMISSIONS.md).
        """
        return {
            "id": self.id,
            "user_id": self.user_id,
            "name": self.user.name,
            "email": self.user.email,
            "role": self.role,
        }


class ChildInvite(db.Model):
    """Kode undangan sekali pakai buat nambah caregiver baru ke seorang anak."""
    __tablename__ = "child_invites"

    id = db.Column(db.Integer, primary_key=True)
    child_id = db.Column(db.Integer, db.ForeignKey("children.id"), nullable=False, index=True)
    code = db.Column(db.String(12), unique=True, nullable=False, index=True)

    created_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    expires_at = db.Column(db.DateTime, nullable=False)

    used_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    used_at = db.Column(db.DateTime, nullable=True)

    # Peran yang DIPILIH PEMILIK pas bikin undangan ini ('editor' | 'viewer'
    # — SAMA whitelist-nya kayak ChildCaregiver.role, ditegakkan CHECK
    # constraint yang sama pola-nya di bawah). Diterapkan APA ADANYA ke
    # ChildCaregiver.role begitu undangan ini dipakai (join_child) — user
    # yang nerima undangan TIDAK PERNAH bisa milih/nimpa peran ini sendiri.
    # Default 'editor' buat undangan yang dibikin SEBELUM kolom ini ada
    # (lihat scripts/migrate_production.py) — PERSIS perilaku lama
    # (caregiver yang gabung lewat undangan lama selalu bisa create/
    # update/delete).
    role = db.Column(db.String(15), nullable=False, default="editor")

    child = db.relationship("Child", backref=db.backref("invites", lazy="dynamic", cascade="all, delete-orphan"))

    __table_args__ = (
        db.CheckConstraint("role IN ('editor', 'viewer')", name="ck_child_invites_role"),
    )

    def to_dict(self):
        return {
            "id": self.id,
            "code": self.code,
            "role": self.role,
            "created_at": self.created_at.isoformat() + "Z",
            "expires_at": self.expires_at.isoformat() + "Z",
            "used": self.used_by is not None,
        }


class Article(db.Model):
    """Artikel edukasi singkat, ditampilkan kontekstual sesuai fitur yang lagi dibuka."""
    __tablename__ = "articles"

    id = db.Column(db.Integer, primary_key=True)
    category = db.Column(db.String(30), nullable=False, index=True)
    # 'feeding' | 'sleep' | 'diaper' | 'growth' | 'vaccination' | 'health' | 'mood' | 'milestone'
    title = db.Column(db.String(150), nullable=False)
    summary = db.Column(db.String(250), nullable=False)
    body = db.Column(db.Text, nullable=False)
    min_age_months = db.Column(db.Integer, nullable=True)  # null = berlaku semua usia
    max_age_months = db.Column(db.Integer, nullable=True)
    source = db.Column(db.String(100), nullable=True)  # cth. "IDAI", "WHO", "Kemenkes RI"
    source_url = db.Column(db.String(500), nullable=True)  # kalau diisi, card jadi redirect ke sumber asli
    order_index = db.Column(db.Integer, default=0)
    last_tip_shown_at = db.Column(db.DateTime, nullable=True)  # buat rotasi tips di reminder Telegram

    def to_dict(self):
        return {
            "id": self.id,
            "category": self.category,
            "title": self.title,
            "summary": self.summary,
            "body": self.body,
            "min_age_months": self.min_age_months,
            "max_age_months": self.max_age_months,
            "source": self.source,
            "source_url": self.source_url,
        }


class WakeWindowGuideline(db.Model):
    """
    Tabel acuan statis (di-seed sekali, bukan data user) — rentang waktu
    bayi biasanya bisa terjaga sebelum ngantuk lagi, per kelompok usia.
    Acuan umum konsensus pediatric sleep (mirip yang dipakai fitur
    "wake window"/"SweetSpot" di app-app tracker bayi populer).
    """
    __tablename__ = "wake_window_guidelines"

    id = db.Column(db.Integer, primary_key=True)
    age_min_days = db.Column(db.Integer, nullable=False)
    age_max_days = db.Column(db.Integer, nullable=False)
    label = db.Column(db.String(50), nullable=False)

    min_wake_minutes = db.Column(db.Integer, nullable=False)
    max_wake_minutes = db.Column(db.Integer, nullable=False)

    def to_dict(self):
        return {
            "id": self.id,
            "label": self.label,
            "min_wake_minutes": self.min_wake_minutes,
            "max_wake_minutes": self.max_wake_minutes,
        }


class IdempotencyKey(db.Model):
    """
    Rekaman request offline-queue yang sudah pernah diproses, dikunci per
    (user, anak, endpoint, client_request_id). Dipakai buat nolak nyipta
    record dobel kalau klien retry request yang sebenernya udah sukses
    diproses server tapi responsnya nggak sempat nyampe balik ke klien
    (koneksi putus pas offline-sync).
    """
    __tablename__ = "idempotency_keys"
    __table_args__ = (
        db.UniqueConstraint(
            "user_id", "child_id", "endpoint", "client_request_id", name="uq_idempotency_key"
        ),
    )

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    child_id = db.Column(db.Integer, db.ForeignKey("children.id"), nullable=False, index=True)
    endpoint = db.Column(db.String(50), nullable=False)
    client_request_id = db.Column(db.String(100), nullable=False)

    # sha256 hex dari payload request yang dinormalisasi — BUKAN payload
    # mentahnya (biar nggak nyimpen data kesehatan bayi dobel di tabel ini).
    # Dipakai buat mastiin key yang sama dipakai ulang utk request yang
    # ISINYA SAMA — kalau isinya beda, itu tandanya bug klien atau reuse
    # key yang nggak sengaja, jadi ditolak (409) bukan diam-diam dianggap
    # sama. Nullable buat kompatibilitas mundur ke baris lama sebelum kolom
    # ini ada (lihat scripts/migrate_production.py).
    fingerprint = db.Column(db.String(64), nullable=True)

    response_status = db.Column(db.Integer, nullable=False)
    response_body = db.Column(db.JSON, nullable=False)

    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)


class CaregiverAuditEvent(db.Model):
    """
    Jejak audit IMUTABLE: siapa yang create/update/delete 1 record anak
    (Caregiver Audit Trail — Phase 1, lihat backend/docs/AUDIT_TRAIL.md).

    SENGAJA PRIVACY-MINIMAL — baris di tabel ini TIDAK PERNAH berisi:
    isi request mentah, nilai field APA PUN (aman maupun privat — lihat
    di bawah), catatan/teks bebas, nama anak, email user, token,
    idempotency key, request ID, teks exception, atau URL endpoint.
    Cukup metadata minimal biar caregiver yang berwenang paham APA yang
    kejadian dan SIAPA yang ngelakuin — bukan salinan kedua data medisnya.

    `changed_fields_json` (khusus event `update`) CUMA berisi NAMA field
    yang berubah, dari 2 kemungkinan bentuk (kebijakan lengkapnya di
    utils/audit.py):
      - nama field ASLI (mis. `["timestamp", "volume_ml"]`) — CUMA kalau
        field itu ada di whitelist utils/audit.py:SAFE_CHANGED_FIELDS
        (field struktural/kategori/angka/waktu yang aman disebut
        namanya);
      - marker generik `"private_details"` (utils/audit.py:PRIVATE_MARKER)
        — kalau field yang berubah ada di
        utils/audit.py:PRIVATE_CHANGED_FIELDS (teks bebas kayak `notes`,
        atau field yang NAMANYA AJA udah identitas medis spesifik kayak
        nama obat/penyakit/diagnosis) — marker ini CUMA muncul SEKALI
        biar pun beberapa field privat berubah bareng.
    Nama field mentah dari request yang nggak ada di KEDUA whitelist itu
    (typo, field baru yang belum dikenal, dst) otomatis dibuang, TIDAK
    PERNAH lolos apa adanya — dan TIDAK PERNAH ada nilai lama/baru
    tersimpan di kolom ini, bentuk apa pun field-nya.

    `actor_user_id` SENGAJA nullable + FK-nya `ondelete="SET NULL"` —
    kalau suatu saat akun user yang jadi actor di sini beneran dihapus
    (belum ada fitur hapus akun lewat endpoint publik sekarang), baris
    event ini TETAP ada (bukti audit harus tetap ada, TIDAK PERNAH ikut
    kehapus), CUMA `actor_user_id`-nya di-null-kan OTOMATIS sama SQLite
    sendiri (bukan kode Python yang nyusul nge-update manual), lalu
    `to_dict()["actor_name"]` balik `None` (lewat relationship yang
    gagal nemu User-nya) — bukan exception. Field lain di baris event-nya
    (action/entity_type/entity_id/changed_fields_json/recorded_at/
    created_at) SAMA SEKALI nggak kesentuh.

    `ondelete="SET NULL"` ini CUMA beneran ditegakkan SQLite kalau
    `PRAGMA foreign_keys=ON` aktif di koneksinya — makanya
    extensions.py masang listener `Engine.connect` yang nyalain PRAGMA
    itu buat SETIAP koneksi SQLite baru, PERMANEN (bukan cuma pas
    migrasi) — lihat extensions.py buat detailnya. Buat database SQLite
    yang tabel `caregiver_audit_events`-nya udah kebikin SEBELUM
    perbaikan ini (FK constraint lama TANPA `ON DELETE SET NULL`),
    scripts/migrate_production.py punya langkah migrasi tersendiri yang
    ngebangun ulang tabelnya (rename+copy, BUKAN hapus+bikin ulang) biar
    FK-nya kekoreksi TANPA kehilangan baris yang udah ada — lihat
    `_ensure_audit_actor_fk_set_null()` di sana.

    `child` pakai backref dengan `cascade="all, delete-orphan"` PERSIS
    pola semua log lain di file ini — begitu 1 Child dihapus permanen,
    SEMUA audit event anak itu ikut kehapus otomatis (konsisten sama
    kebijakan hapus-permanen yang udah ada buat semua log anak lainnya,
    bukan pengecualian).
    """
    __tablename__ = "caregiver_audit_events"

    id = db.Column(db.Integer, primary_key=True)
    child_id = db.Column(db.Integer, db.ForeignKey("children.id"), nullable=False, index=True)
    actor_user_id = db.Column(
        db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )

    action = db.Column(db.String(10), nullable=False)       # 'create' | 'update' | 'delete'
    entity_type = db.Column(db.String(30), nullable=False)  # lihat utils/audit.py:ENTITY_TYPES
    entity_id = db.Column(db.Integer, nullable=False)        # id record asli (bukan FK — record-nya bisa aja udah kehapus)

    # List nama field yang berubah (CUMA buat action='update'; null buat create/delete)
    changed_fields_json = db.Column(db.JSON, nullable=True)

    # Waktu KEJADIAN ASLI record-nya (mis. FeedingLog.timestamp,
    # GrowthMeasurement.measured_date) — null kalau entity_type-nya nggak
    # punya field waktu kejadian yang jelas. BEDA dari created_at di bawah
    # (kapan EVENT AUDIT ini sendiri dicatat).
    recorded_at = db.Column(db.DateTime, nullable=True)

    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)

    actor = db.relationship("User", foreign_keys=[actor_user_id])
    child = db.relationship(
        "Child", backref=db.backref("audit_events", lazy="dynamic", cascade="all, delete-orphan")
    )

    def to_dict(self):
        return {
            "id": self.id,
            "action": self.action,
            "entity_type": self.entity_type,
            "entity_id": self.entity_id,
            "changed_fields": self.changed_fields_json or [],
            "recorded_at": (self.recorded_at.isoformat() + "+07:00") if self.recorded_at else None,
            "created_at": self.created_at.isoformat() + "Z",
            "actor_user_id": self.actor_user_id,
            "actor_name": self.actor.name if self.actor else None,
        }


class Reminder(db.Model):
    """
    Definisi 1 pengingat perawatan (Care Reminders & Schedules — Phase 1,
    lihat backend/docs/REMINDERS.md). SENGAJA CUMA nyimpen JADWAL +
    METADATA, TIDAK PERNAH status "sudah lewat"/"jatuh tempo" — status
    itu SELALU dihitung ULANG saat diminta (lihat
    utils/reminder_engine.py) karena PythonAnywhere Free nggak punya
    scheduler background yang bisa nge-update status di latar belakang
    pada waktu yang tepat.

    `title` SENGAJA diperlakukan sebagai teks POTENSIAL SENSITIF (bisa
    aja diisi caregiver dengan nama obat/rincian medis, mis. "Kasih
    Paracetamol 5ml") — TIDAK PERNAH dikirim ke notifikasi
    browser/log/audit trail apa adanya, cuma teks generik per
    `reminder_type` yang dipakai di sana (lihat routes/reminder_routes.py).
    """
    __tablename__ = "reminders"
    __table_args__ = (
        db.CheckConstraint(
            "reminder_type IN ('medication','doctor_visit','vaccination','pumping','general')",
            name="ck_reminders_type",
        ),
        # 'weekly'/'custom' SENGAJA belum masuk allowlist Phase 1 (lihat
        # backend/docs/REMINDERS.md#scope) — kolom `recurrence` string
        # bebas (bukan enum SQLite native) biar allowlist ini gampang
        # diperluas nanti TANPA migrasi skema kolom, cuma ganti CHECK
        # constraint-nya.
        db.CheckConstraint("recurrence IN ('none','daily')", name="ck_reminders_recurrence"),
        db.Index("ix_reminders_child_active", "child_id", "is_active"),
    )

    id = db.Column(db.Integer, primary_key=True)
    child_id = db.Column(db.Integer, db.ForeignKey("children.id"), nullable=False, index=True)
    created_by_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)

    reminder_type = db.Column(db.String(20), nullable=False)
    title = db.Column(db.String(150), nullable=False)

    # Wall-clock WIB naive (KONSISTEN sama semua kolom timestamp domain
    # lain di app ini, lihat utils/timezone_utils.py) — buat pengingat
    # 'daily', kolom ini jadi JANGKAR (tanggal awal + jam-menit tiap
    # hari); okurensi hari-hari berikutnya dihitung dari jam:menit-nya,
    # BUKAN disimpan baris terpisah per hari (lihat
    # utils/reminder_engine.py).
    scheduled_at = db.Column(db.DateTime, nullable=False, index=True)
    recurrence = db.Column(db.String(10), nullable=False, default="none")
    is_active = db.Column(db.Boolean, nullable=False, default=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    creator = db.relationship("User", foreign_keys=[created_by_user_id])
    child = db.relationship(
        "Child", backref=db.backref("reminders", lazy="dynamic", cascade="all, delete-orphan")
    )

    def to_dict(self):
        return {
            "id": self.id,
            "child_id": self.child_id,
            "created_by_user_id": self.created_by_user_id,
            "reminder_type": self.reminder_type,
            "title": self.title,
            "scheduled_at": self.scheduled_at.isoformat() + "+07:00",
            "recurrence": self.recurrence,
            "is_active": self.is_active,
            "created_at": self.created_at.isoformat() + "Z",
            "updated_at": self.updated_at.isoformat() + "Z",
        }


class ReminderAction(db.Model):
    """
    SATU aksi caregiver (selesai/lewati) atas SATU okurensi 1 Reminder.
    Baris di sini SENGAJA CUMA dibikin buat okurensi yang BENERAN
    di-selesaikan/dilewati caregiver — okurensi yang masih "pending"
    TIDAK PERNAH punya baris (statusnya dihitung IMPLISIT: nggak ada
    baris = pending), biar reminder harian yang udah aktif lama nggak
    numpuk baris kosong nggak terbatas (lihat requirement "avoid
    materializing unlimited future occurrences").

    `occurrence_at` = jam kejadian okurensi spesifik itu (tanggal +
    jam:menit dari `Reminder.scheduled_at`, WIB naive) — SATU-SATUNYA
    kunci yang nentuin "okurensi yang MANA" (lihat UniqueConstraint di
    bawah: 1 Reminder cuma boleh punya SATU baris aksi per
    `occurrence_at`, apa pun statusnya — occurrence yang UDAH punya aksi
    TIDAK PERNAH bisa dapet aksi ke-2 lewat jalur normal, lihat
    routes/reminder_routes.py buat penanganan konflik 409-nya).

    TIDAK ADA status 'pending' literal di sini (beda dari daftar status
    okurensi yang "kelihatan" di API) — CHECK constraint di bawah SENGAJA
    cuma izinin 'completed'/'skipped'.
    """
    __tablename__ = "reminder_actions"
    __table_args__ = (
        db.UniqueConstraint("reminder_id", "occurrence_at", name="uq_reminder_action_occurrence"),
        db.CheckConstraint("status IN ('completed','skipped')", name="ck_reminder_actions_status"),
        db.CheckConstraint(
            "linked_log_type IS NULL OR linked_log_type IN ('medication_log','pumping_log','doctor_visit')",
            name="ck_reminder_actions_linked_log_type",
        ),
    )

    id = db.Column(db.Integer, primary_key=True)
    reminder_id = db.Column(db.Integer, db.ForeignKey("reminders.id"), nullable=False, index=True)

    occurrence_at = db.Column(db.DateTime, nullable=False, index=True)
    status = db.Column(db.String(10), nullable=False)

    acted_at = db.Column(db.DateTime, nullable=False)
    acted_by_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)

    # Diisi CUMA kalau aksi ini lahir dari alur "Catat sekarang" yang
    # berhasil nyimpen 1 catatan perawatan (lihat routes/reminder_routes.py)
    # — TIDAK PERNAH diisi otomatis tanpa konfirmasi eksplisit caregiver
    # (requirement: jangan otomatis catat pemberian obat/vaksinasi cuma
    # gara-gara pengingatnya jatuh tempo).
    linked_log_type = db.Column(db.String(20), nullable=True)
    linked_log_id = db.Column(db.Integer, nullable=True)

    reminder = db.relationship(
        "Reminder", backref=db.backref("actions", lazy="dynamic", cascade="all, delete-orphan")
    )
    actor = db.relationship("User", foreign_keys=[acted_by_user_id])

    def to_dict(self):
        return {
            "id": self.id,
            "reminder_id": self.reminder_id,
            "occurrence_at": self.occurrence_at.isoformat() + "+07:00",
            "status": self.status,
            "acted_at": self.acted_at.isoformat() + "+07:00",
            "acted_by_user_id": self.acted_by_user_id,
            "acted_by_name": self.actor.name if self.actor else None,
            "linked_log_type": self.linked_log_type,
            "linked_log_id": self.linked_log_id,
        }


class MedicationSchedule(db.Model):
    """
    Definisi 1 regimen pemberian obat berulang (Medication Schedule &
    Adherence — Phase 1, lihat backend/docs/MEDICATION_SCHEDULE.md).
    SENGAJA CUMA nyimpen JADWAL + METADATA, TIDAK PERNAH status
    "jatuh tempo"/"terlambat" -- status okurensi SELALU dihitung ULANG
    saat diminta (lihat utils/medication_schedule_engine.py), PERSIS
    prinsip arsitektur `Reminder` di atas (PythonAnywhere Free nggak
    punya scheduler background).

    `medication_name`/`instructions` SENGAJA diperlakukan sebagai teks
    POTENSIAL SENSITIF (nama obat spesifik/instruksi bebas caregiver)
    -- TIDAK PERNAH masuk audit trail apa adanya, lihat utils/audit.py.
    """
    __tablename__ = "medication_schedules"
    __table_args__ = (
        db.Index("ix_medication_schedules_child_active", "child_id", "is_active"),
    )

    id = db.Column(db.Integer, primary_key=True)
    child_id = db.Column(db.Integer, db.ForeignKey("children.id"), nullable=False, index=True)
    created_by_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)

    medication_name = db.Column(db.String(150), nullable=False)
    # Opsional BERPASANGAN (dua-duanya diisi, atau dua-duanya kosong) --
    # ditegakkan di utils/medication_schedule_engine.py:validate_dose,
    # BUKAN di kolom DB (SQLite CHECK constraint lintas-kolom nullable
    # sering rewel, validasi Python di layer route SUDAH cukup buat
    # Phase 1 -- lihat juga pola serupa reminder `recurrence`).
    dose_value = db.Column(db.Float, nullable=True)
    dose_unit = db.Column(db.String(20), nullable=True)
    instructions = db.Column(db.Text, nullable=True)

    start_date = db.Column(db.Date, nullable=False, index=True)
    end_date = db.Column(db.Date, nullable=True)
    # List string "HH:MM" (24 jam), TERURUT + UNIK -- ditegakkan di
    # layer validasi (utils/medication_schedule_engine.py:validate_times_of_day)
    # sebelum disimpan, BUKAN diasumsikan begitu saja tiap dibaca balik.
    times_of_day = db.Column(db.JSON, nullable=False)
    # Kolom timezone DISEDIAKAN (skema siap multi-zona nanti), TAPI
    # Phase 1 CUMA nerima "Asia/Jakarta" -- SELURUH app ini WIB-only
    # (lihat utils/timezone_utils.py), belum ada kebutuhan nyata buat
    # zona lain, jadi belum ditambah kompleksitas konversi timezone
    # asli. Ditegakkan di layer validasi, bukan CHECK constraint DB,
    # biar gampang diperluas nanti tanpa migrasi skema.
    timezone = db.Column(db.String(30), nullable=False, default="Asia/Jakarta")
    is_active = db.Column(db.Boolean, nullable=False, default=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    creator = db.relationship("User", foreign_keys=[created_by_user_id])
    child = db.relationship(
        "Child", backref=db.backref("medication_schedules", lazy="dynamic", cascade="all, delete-orphan")
    )

    def to_dict(self):
        return {
            "id": self.id,
            "child_id": self.child_id,
            "created_by_user_id": self.created_by_user_id,
            "created_by_name": self.creator.name if self.creator else None,
            "medication_name": self.medication_name,
            "dose_value": self.dose_value,
            "dose_unit": self.dose_unit,
            "instructions": self.instructions,
            "start_date": self.start_date.isoformat(),
            "end_date": self.end_date.isoformat() if self.end_date else None,
            "times_of_day": list(self.times_of_day or []),
            "timezone": self.timezone,
            "is_active": self.is_active,
            "created_at": self.created_at.isoformat() + "Z",
            "updated_at": self.updated_at.isoformat() + "Z",
        }


class MedicationDoseAction(db.Model):
    """
    SATU aksi caregiver (diberikan/dilewati) atas SATU okurensi dosis 1
    MedicationSchedule -- pola SAMA PERSIS `ReminderAction` di atas
    (baris CUMA dibikin buat okurensi yang BENERAN diaksi, okurensi
    "pending" TIDAK PERNAH punya baris, `occurrence_at` = kunci unik
    "okurensi yang MANA").

    BEDA dari ReminderAction: dosis yang ditandai "administered" SELALU
    otomatis membuat 1 MedicationLog (requirement produk: "without
    requiring duplicate data entry") -- `medication_log_id` nyimpen
    tautan itu, DIBUAT DALAM TRANSAKSI DATABASE YANG SAMA (lihat
    routes/medication_schedule_routes.py), bukan lewat alur "Catat
    sekarang" 2-langkah opsional kayak Reminder. `acted_at` = waktu
    AKSI beneran dicatat (bisa mundur dari `occurrence_at` kalau
    caregiver baru sempat nge-tap belakangan) -- SENGAJA field
    terpisah dari `occurrence_at` (jadwal), lihat requirement "preserve
    the distinction between scheduled time and actual administration
    time".
    """
    __tablename__ = "medication_dose_actions"
    __table_args__ = (
        db.UniqueConstraint("schedule_id", "occurrence_at", name="uq_medication_dose_action_occurrence"),
        db.CheckConstraint("status IN ('administered','skipped')", name="ck_medication_dose_actions_status"),
    )

    id = db.Column(db.Integer, primary_key=True)
    schedule_id = db.Column(db.Integer, db.ForeignKey("medication_schedules.id"), nullable=False, index=True)

    occurrence_at = db.Column(db.DateTime, nullable=False, index=True)
    status = db.Column(db.String(12), nullable=False)

    acted_at = db.Column(db.DateTime, nullable=False)
    acted_by_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)

    # Diisi CUMA buat status='administered' (lihat docstring kelas) --
    # TIDAK PERNAH diisi buat 'skipped' (nggak ada obat yang beneran
    # diberikan, jadi TIDAK ADA MedicationLog yang dibuat sama sekali).
    medication_log_id = db.Column(db.Integer, db.ForeignKey("medication_logs.id"), nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    schedule = db.relationship(
        "MedicationSchedule", backref=db.backref("actions", lazy="dynamic", cascade="all, delete-orphan")
    )
    actor = db.relationship("User", foreign_keys=[acted_by_user_id])
    medication_log = db.relationship("MedicationLog", foreign_keys=[medication_log_id])

    def to_dict(self):
        return {
            "id": self.id,
            "schedule_id": self.schedule_id,
            "occurrence_at": self.occurrence_at.isoformat() + "+07:00",
            "status": self.status,
            "acted_at": self.acted_at.isoformat() + "+07:00",
            "acted_by_user_id": self.acted_by_user_id,
            "acted_by_name": self.actor.name if self.actor else None,
            "medication_log_id": self.medication_log_id,
        }