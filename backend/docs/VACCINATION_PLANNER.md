# Vaccination Planner & Immunization Record — Phase 1

Fitur ini memperluas tabel lama `vaccine_schedules` dan
`child_vaccinations`; tidak membuat sistem vaksin kedua dan tidak membutuhkan
scheduler/background worker. Semua status dihitung saat endpoint dibaca.

## Status

Tanggal rekomendasi dihitung dari tanggal lahir + usia rekomendasi:

- `upcoming`: lebih dari 14 hari sebelum tanggal rekomendasi.
- `due`: mulai 14 hari sebelum sampai 30 hari setelah tanggal rekomendasi.
- `overdue`: lebih dari 30 hari setelah tanggal rekomendasi dan belum tercatat.
- `given`: sudah dicatat diberikan, selalu mengalahkan status waktu.

Status adalah bantuan pengelompokan, bukan keputusan medis. Waktu dan kebutuhan
vaksin harus dikonfirmasi dengan dokter atau tenaga kesehatan.

## API

`GET /api/children/<id>/vaccinations` mengembalikan daftar lama beserta
`state`, `recommended_date`, ringkasan, disclaimer, dan `can_update` dari
backend. Field boolean `due` tetap tersedia untuk kompatibilitas klien lama.

`POST /api/children/<id>/vaccinations` tetap memakai format bulk lama. Seluruh
payload divalidasi sebelum satu baris pun diubah: maksimal 50 item, ID harus
ada dan unik, `given` wajib boolean, tanggal tidak boleh sebelum kelahiran atau
di masa depan, dan catatan maksimal 500 karakter. Mutasi tetap atomik.

Owner dan Editor dapat memperbarui. Viewer hanya dapat melihat; kontrol UI
disembunyikan/dinonaktifkan, tetapi backend tetap menjadi otoritas.

## Consultation report

Bagian vaksinasi pada preview dan PDF memakai snapshot yang sama dan sekarang
menampilkan status planner, tanggal rekomendasi, serta tanggal pemberian.

## Deployment

Tidak ada perubahan skema dan tidak ada migrasi khusus. Deployment cukup pull,
menjalankan test, reload web app, lalu health check. PythonAnywhere Free tetap
didukung karena tidak ada cron, Celery, Redis, WebSocket, atau worker.

## Phase 1 limitations

- Pencatatan vaksin masih online-only; mutasi medis tidak diantrikan offline.
- Tidak menyimpan foto kartu vaksin/fasilitas kesehatan sebagai field terpisah.
- Jadwal referensi mengikuti data seed yang sudah tersedia dan bukan pengganti
  rekomendasi individual/catch-up dari dokter.
