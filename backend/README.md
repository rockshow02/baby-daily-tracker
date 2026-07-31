# Baby Daily Tracker — Backend

Backend Flask + SQLAlchemy + SQLite untuk mencatat aktivitas harian bayi
(menyusui, tidur, popok) dan membandingkannya dengan acuan IDAI/AAP sesuai usia.
Sudah tervalidasi end-to-end (register → login → catat log → daily summary).

## 1. Setup

```bash
cd backend
python3 -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
```

Edit `.env`, minimal ganti `SECRET_KEY` dengan string acak.

## 2. Jalankan

```bash
python app.py
```

Server jalan di `http://localhost:5000`. Tabel database otomatis dibuat saat
pertama kali run (`db.create_all()` di `app.py`).

## 3. Seed data acuan (WAJIB, sekali saja)

```bash
python seed/seed_feeding_guidelines.py
```

Ini mengisi tabel `feeding_guidelines` dengan 5 rentang usia (0-1 bln, 1-2 bln,
3-5 bln, 6-12 bln, 1-2 thn) berdasarkan IDAI (frekuensi menyusui, BAK/BAB) dan
konsensus AAP/National Sleep Foundation (durasi tidur). Idempotent — aman
dijalankan berkali-kali, hanya nambah yang belum ada.

## 4. Struktur project

```
backend/
├── app.py                      # entrypoint (app factory)
├── config.py                   # config dev & production
├── extensions.py               # instance db, cors
├── models.py                   # User, Child, FeedingLog, SleepLog, DiaperLog, FeedingGuideline
├── routes/
│   ├── auth_routes.py          # register, login, logout, me
│   ├── children_routes.py      # CRUD data anak
│   └── daily_log_routes.py     # CRUD log + daily-summary
├── utils/
│   └── summary_engine.py       # logic hitung usia & bandingkan ke acuan
├── seed/
│   └── seed_feeding_guidelines.py
└── instance/                   # tempat file SQLite dibuat otomatis
```

## 5. API Endpoints

### Auth (`/api/auth`)
| Method | Endpoint | Body |
|---|---|---|
| POST | `/register` | `{name, email, password}` |
| POST | `/login` | `{email, password}` |
| POST | `/logout` | - |
| GET | `/me` | - (cek siapa yang login) |

### Anak (`/api`)
| Method | Endpoint | Body |
|---|---|---|
| GET | `/children` | - |
| POST | `/children` | `{name, birth_date: "YYYY-MM-DD", gender}` |
| PUT/DELETE | `/children/<id>` | - |

### Daily Log (`/api`)
| Method | Endpoint | Body |
|---|---|---|
| GET/POST | `/children/<id>/feeding-logs?date=YYYY-MM-DD` | `{feed_type, duration_minutes, volume_ml, breast_side, notes}` |
| PUT/DELETE | `/feeding-logs/<id>` | - |
| GET/POST | `/children/<id>/sleep-logs?date=YYYY-MM-DD` | `{start_time, end_time, sleep_type, notes}` |
| PUT/DELETE | `/sleep-logs/<id>` | - |
| GET/POST | `/children/<id>/diaper-logs?date=YYYY-MM-DD` | `{diaper_type, consistency, color, notes}` |
| DELETE | `/diaper-logs/<id>` | - |
| GET | `/children/<id>/daily-summary?date=YYYY-MM-DD` | **Dashboard**: tally hari ini vs acuan |

`feed_type`: `asi_langsung` \| `asi_perah` \| `sufor` \| `mpasi`
`diaper_type`: `pipis` \| `pup` \| `keduanya`
`consistency` (khusus pup): `normal` \| `keras` \| `cair` \| `berlendir` \| `berdarah`

### Contoh respons `daily-summary`
```json
{
  "age_days": 45,
  "guideline_label": "1-2 bulan",
  "source": "IDAI",
  "feeding": { "actual": 6, "min": 7, "max": 9, "status": "kurang" },
  "sleep": { "actual_hours": 6.5, "min": 14.0, "max": 17.0, "status": "kurang" },
  "wet_diaper": { "actual": 7, "min": 6, "status": "normal", "note": "..." },
  "bab": { "actual": 2, "min": null, "status": null, "note": "..." },
  "guideline_notes": "..."
}
```
Frontend tinggal render badge hijau (normal) / kuning (kurang) / merah (lebih)
dari field `status`.

## 6. Deploy ke PythonAnywhere

Sama seperti pola Lenya Gas / Tumbuh:
1. Upload folder `backend/` (atau git clone dari repo)
2. Buat virtualenv di PythonAnywhere, `pip install -r requirements.txt`
3. Set environment variable `SECRET_KEY`, `FRONTEND_ORIGIN` (domain Vercel kamu) di WSGI config
4. Point WSGI file ke `create_app()` dari `app.py`
5. Jalankan sekali: `python seed/seed_feeding_guidelines.py` via konsol PythonAnywhere

## Catatan penting
Angka acuan ini panduan umum (IDAI/AAP), **bukan pengganti saran dokter anak**.
Kalau bayi terus-menerus "kurang" di beberapa kategori, sarankan konsultasi
ke dokter — jangan jadikan app ini sebagai satu-satunya acuan medis.

## Selanjutnya
Backend ini sudah tervalidasi jalan (test end-to-end: register → tambah anak →
catat feeding/sleep/diaper → daily-summary menghitung status dengan benar).
Langkah berikut: frontend React — quick-log buttons + kartu dashboard "Hari ini".
