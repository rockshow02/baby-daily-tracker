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

    def to_dict(self):
        return {
            "id": self.id,
            "child_id": self.child_id,
            "timestamp": self.timestamp.isoformat() + "+07:00",
            "diaper_type": self.diaper_type,
            "consistency": self.consistency,
            "color": self.color,
            "notes": self.notes,
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

    child = db.relationship("Child", backref=db.backref("activity_logs", lazy="dynamic", cascade="all, delete-orphan"))

    def to_dict(self):
        return {
            "id": self.id,
            "child_id": self.child_id,
            "activity_type": self.activity_type,
            "timestamp": self.timestamp.isoformat() + "+07:00",
            "duration_minutes": self.duration_minutes,
            "notes": self.notes,
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

    child = db.relationship("Child", backref=db.backref("mood_logs", lazy="dynamic", cascade="all, delete-orphan"))

    def to_dict(self):
        return {
            "id": self.id,
            "child_id": self.child_id,
            "timestamp": self.timestamp.isoformat() + "+07:00",
            "mood": self.mood,
            "notes": self.notes,
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
        }



class ChildCaregiver(db.Model):
    """
    Relasi banyak-ke-banyak antara User dan Child — satu anak bisa punya
    beberapa pengasuh (orang tua, ART, dll), satu akun bisa akses beberapa anak.
    """
    __tablename__ = "child_caregivers"
    __table_args__ = (db.UniqueConstraint("child_id", "user_id", name="uq_child_caregiver"),)

    id = db.Column(db.Integer, primary_key=True)
    child_id = db.Column(db.Integer, db.ForeignKey("children.id"), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)

    role = db.Column(db.String(15), nullable=False, default="caregiver")  # 'owner' | 'caregiver'
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship("User")
    child = db.relationship(
        "Child", backref=db.backref("caregivers", lazy="dynamic", cascade="all, delete-orphan")
    )

    def to_dict(self):
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

    child = db.relationship("Child", backref=db.backref("invites", lazy="dynamic", cascade="all, delete-orphan"))

    def to_dict(self):
        return {
            "id": self.id,
            "code": self.code,
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