# Baby Daily Tracker V3 — Release Checklist

V3 mencakup Memory Journal, Development Timeline/Calendar/Goals/Hub, Monthly
Story, Family Development Check-in, Appointment Preparation, Data Quality
Center, dan Family Monthly Review.

## Urutan deploy staging/production

1. Pastikan branch dan environment target benar.
2. Aktifkan virtualenv PythonAnywhere.
3. Buat backup SQLite beserta metadata checksum dan verifikasi hasilnya.
4. Pull commit V3 dari branch target.
5. Instal dependency dari `requirements.txt` bila berubah.
6. Jalankan `python scripts/migrate_production.py` satu kali. Script idempotent;
   data/tabel lama tidak dihapus atau dikosongkan.
7. Jalankan test migrasi dan test fitur V3 yang relevan.
8. Jalankan `python scripts/production_health_check.py --environment <target>`.
   Check `v3_schema` wajib `OK`; bila gagal, jangan reload web app.
9. Reload web app melalui PythonAnywhere lalu cek `/api/health`.
10. Lakukan smoke test Owner, Editor, dan Viewer serta uji mobile viewport.

## Rollback

Jangan menjalankan DROP TABLE. Kembalikan kode ke commit sebelumnya dan gunakan
backup database terverifikasi hanya bila migrasi/data benar-benar bermasalah.
Tabel V3 tambahan aman dibiarkan kosong ketika kode lama sedang dijalankan.

## Batasan deployment

- Fitur V3 tidak membutuhkan Celery, Redis, cron, atau scheduled task.
- Photo Memory Journal membutuhkan folder `uploads/` dapat ditulis.
- Perubahan data offline tetap hanya berlaku pada fitur yang secara eksplisit
  memakai offline queue; CRUD V3 lain sengaja online-only.
