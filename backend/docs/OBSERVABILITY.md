# Observability — health check, request ID, logging, error response

Fondasi monitoring produksi buat backend Baby Daily Tracker: endpoint
health publik yang murah, request ID buat korelasi log, logging terstruktur
yang privacy-safe, respons error yang konsisten, plus 2 script diagnostik
manual (nggak ada scheduled task otomatis — PythonAnywhere free tier nggak
support itu).

Semua kode intinya ada di [`utils/observability.py`](../utils/observability.py)
(diwiring dari [`app.py`](../app.py)), test-nya di
[`tests/test_observability.py`](../tests/test_observability.py).

## 1. Endpoint `/api/health`

```
GET /api/health
```

Publik, **TANPA autentikasi**, murah — cuma `SELECT 1` (bukan
`PRAGMA integrity_check` penuh), dibungkus timeout 2 detik lewat
`ThreadPoolExecutor` biar 1 request health check nggak bisa nge-hang
selamanya kalau DB lagi bermasalah.

**Sehat (200):**
```json
{
  "status": "ok",
  "database": "ok",
  "version": "abc1234",
  "request_id": "b3f1..."
}
```

**Degraded — DB nggak bisa diakses (503):**
```json
{
  "status": "degraded",
  "database": "unavailable",
  "request_id": "b3f1..."
}
```

`version` diambil dari env var `APP_VERSION` atau `DEPLOY_COMMIT` (urutan
prioritas ini), disaring lewat whitelist regex `^[A-Za-z0-9._-]{1,40}$` —
kalau nggak ada/nggak valid, balik ke string `"unknown"`. **Nggak pernah**
menjalankan shell command buat resolve versi (mis. `git rev-parse`) —
biar endpoint publik ini nggak punya jalur eksekusi command sama sekali.

**Yang SENGAJA TIDAK PERNAH ada di respons ini** (baik sukses maupun
gagal): tipe/path database, nama tabel, jumlah record, hostname,
environment variable lain, git remote/branch, atau teks exception mentah.
Kalau DB check gagal karena exception, pesan exception-nya TIDAK PERNAH
ikut ke body respons — cuma `"database": "unavailable"`.

## 2. Request ID korelasi (`X-Request-ID`)

Setiap request dapet 1 request ID, disimpan di `flask.g.request_id`
sepanjang siklus hidup request itu, dan selalu dikembalikan lewat header
respons `X-Request-ID` — termasuk di respons 500/error.

- Kalau klien ngirim header `X-Request-ID` sendiri dan formatnya valid
  (`^[A-Za-z0-9_-]{1,64}$`), nilai itu dipakai apa adanya (berguna buat
  nyambungin log frontend<->backend).
- Kalau nggak ada, atau formatnya nggak valid (ada spasi, simbol aneh,
  kepanjangan, atau newline/control character yang bisa dipakai buat log
  injection), backend generate UUID v4 baru — klien nggak pernah bisa
  maksa nilai sembarangan masuk ke log.
- Request ID **BUKAN mekanisme autentikasi** — cuma buat korelasi/debug.

**Cara pakai buat troubleshooting:** ambil `request_id` dari respons error
yang dilaporkan user (ada di body JSON error DAN di header `X-Request-ID`),
lalu grep log server:

```bash
grep '"request_id": "b3f1..."' /path/ke/log
```

Karena log-nya 1 JSON per baris, semua baris (`request_completed`,
`unhandled_exception`, dst) yang punya `request_id` yang sama itu langsung
kebaca — biasanya cukup 1-2 baris per request.

## 3. Logging terstruktur (JSON per baris)

Lewat `logging` standar Python (logger bernama `"babytracker"`), 1 objek
JSON per baris ke stdout (PythonAnywhere nangkep ini ke error/server log
biasa — nggak butuh setup tambahan).

**Field yang DIIZINKAN muncul** (subset, tergantung event):
`timestamp`, `level`, `event`, `request_id`, `method`, `route` (route
TEMPLATE kayak `/api/children/<int:child_id>/feeding-logs`, bukan URL
literal), `status`, `duration_ms`, `user_id`, `exception_type`,
`stack_trace` (KHUSUS baris `unhandled_exception`, server-side aja).

**Field yang TIDAK PERNAH dicatat** (di baris log manapun): header
Authorization, cookie, isi body request/response, nilai query string,
password, token, username/email, nama bayi, catatan bebas, nama obat,
nama file upload, chat ID Telegram, pesan/traceback error database
mentah dari SQLAlchemy.

Setiap request yang selesai bikin 1 baris `event: "request_completed"`.
Exception yang nggak ketangkep route manapun bikin 1 baris tambahan
`event: "unhandled_exception"` (stack trace-nya CUMA di baris ini, CUMA
di log server — **tidak pernah** dikembalikan ke klien).

`configure_logging()` idempotent — dipanggil ulang tiap `create_app()`
(kejadian normal di test suite) nggak bikin handler ganda/log duplikat,
lewat marker `logger._babytracker_configured`.

## 4. Bentuk respons error yang konsisten

```json
{
  "error": {
    "code": "internal_error",
    "message": "Terjadi kesalahan pada server.",
    "request_id": "b3f1..."
  }
}
```

### Batasan yang SENGAJA dipilih (baca ini sebelum nambah endpoint baru)

Standardisasi ini **HANYA** diterapkan ke 2 hal:
1. **Exception Python yang nggak ketangkep** di mana pun (bug asli) ->
   selalu jadi 500 dengan bentuk di atas, `code: "internal_error"`, pesan
   generik Indonesia, TANPA teks exception asli.
2. **Error level-framework/Werkzeug** — 404 (route nggak ketemu), 405
   (method salah), 400 (body JSON nggak bisa diparse Werkzeug sendiri),
   dst — lewat `@app.errorhandler(HTTPException)`.

**SEMUA ~100+ endpoint yang sudah ada** (yang manggil
`return jsonify({"error": "..."}), status` secara eksplisit di kode route)
**TIDAK DIUBAH SAMA SEKALI** — bentuk respons error mereka (termasuk pesan
Indonesia yang udah ada, kayak `{"error": "Email atau password salah"}`)
tetap 100% sama seperti sebelumnya. Ini keputusan sadar (bukan belum
sempat dikerjakan): mengonversi ratusan endpoint yang sudah dites frontend
punya risiko regresi yang nggak sepadan buat task observability ini — jadi
"eskalasi standardisasi" cuma nutup celah di titik yang **belum pernah**
ketutup validasi eksplisit (exception asli & 404/405/dst), bukan
menimpa validasi yang udah sengaja ditulis manual.

Terverifikasi lewat: `grep` codebase (nggak ada satu pun route yang manggil
`abort()`/raise `HTTPException` langsung — semua eksplisit `jsonify(...)`),
plus test khusus (`test_24_existing_validation_status_unchanged`,
`test_25_existing_authentication_behavior_unchanged` di
`test_observability.py`) yang mastiin bentuk lama itu byte-for-byte sama.

CORS (`Access-Control-Allow-Origin`) dan idempotency (`X-Idempotency-Key`)
tetap jalan normal di semua kondisi ini, termasuk di respons 500 —
lihat `test_observability.py` test 22-23.

## 5. Frontend: Error Boundary

[`frontend/src/components/ErrorBoundary.jsx`](../../frontend/src/components/ErrorBoundary.jsx),
dipasang di [`frontend/src/main.jsx`](../../frontend/src/main.jsx)
membungkus `<App />`.

Nangkep error render/lifecycle React (BUKAN error di event handler, promise
gagal di background, kegagalan API call, atau service worker — itu semua
tetap lewat jalur penanganan masing-masing yang udah ada). Fallback-nya:
pesan Indonesia ramah + kode error client-side yang aman (random, bukan
diturunkan dari isi error) + tombol "Coba lagi" (remount subtree) dan
"Muat ulang aplikasi" (`window.location.reload()`). **Tidak pernah**
menghapus token auth, cache sesi, atau antrian offline saat crash — data
yang udah tersimpan tetap aman.

## 6. `scripts/production_health_check.py` — diagnostik manual

Dijalankan operator dari Bash console PythonAnywhere (nggak ada scheduled
task di free tier):

```bash
cd ~/baby-daily-tracker/backend
source ~/.virtualenvs/babytracker-venv/bin/activate
python scripts/production_health_check.py --environment staging

# opsional:
python scripts/production_health_check.py --environment production \
    --backup-stale-days 7 --min-disk-free-mb 500 --json
```

Read-only terhadap database dan nggak pernah bikin backup baru sendiri
(cuma MEMERIKSA backup yang udah ada, pakai fungsi yang sama dari
`scripts/db_backup_common.py` — nggak duplikat logic path). Satu-satunya
tulis-ke-disk yang mungkin: 1 file probe kecil yang dibikin DAN dihapus
lagi di folder `uploads/` (cek writable), kalau folder itu dipakai.

18 pengecekan: pembuatan Flask app, konfigurasi SQLite, file DB
ada/kebaca, `SELECT 1`, `PRAGMA quick_check`, ukuran file DB, folder
backup ter-resolve aman, minimal 1 backup valid, integrity+checksum
backup terbaru, umur backup (WARNING kalau lebih tua dari
`--backup-stale-days`, default 7), semua package inti ke-import, `requests`
ke-import tanpa `RequestsDependencyWarning`, config kritis
(`SECRET_KEY`, `SQLALCHEMY_DATABASE_URI`) ada TANPA nampilin nilainya,
folder upload ada+writable (kalau dipakai), disk free space di atas
`--min-disk-free-mb` (default 500).

**Kode keluar:** `0` = semua pengecekan WAJIB lolos (WARNING boleh ada) ·
`1` = minimal 1 pengecekan WAJIB gagal · `2` = penggunaan command salah.

Belum ada backup sama sekali = **WARNING** (deployment baru wajar belum
punya backup). Backup ADA tapi korup/checksum nggak cocok = **FAILED**
(masalah nyata). Nggak pernah mencetak isi baris database, nilai config,
atau `DATABASE_URL` lengkap.

## 7. `scripts/post_deploy_smoke_test.py` — smoke test pasca-deploy

Dijalankan operator SETELAH deploy (staging atau production):

```bash
python scripts/post_deploy_smoke_test.py --base-url https://xaleena.pythonanywhere.com/api
```

Cuma manggil `GET <base-url>/health` — nggak pernah bikin user/catatan,
nggak pernah kirim token autentikasi, nggak pernah ngikutin redirect ke
host lain kecuali eksplisit `--allow-cross-host-redirect`. Validasi HTTPS
wajib buat host non-lokal, menolak URL dengan kredensial ter-embed
(`user:pass@host`), pakai timeout (`--timeout`, default 10 detik).

**Kode keluar:** `0` = semua pengecekan WAJIB lolos · `1` = minimal 1
pengecekan WAJIB gagal (termasuk `status: "degraded"` di body) · `2` =
URL/argumen nggak valid.

**Batasan penting PythonAnywhere free tier:** akun free MEMBATASI akses
internet keluar (whitelist domain terbatas) — script ini paling gampang
dijalankan dari **komputer lokal kamu** ke staging/production, BUKAN dari
dalam Bash console PythonAnywhere itu sendiri, kecuali domain targetnya
kebetulan ada di whitelist mereka.

## 8. Frekuensi eksekusi manual yang disarankan

Nggak ada satu pun dari 2 script di atas yang jalan otomatis (task ini
sengaja TIDAK menambahkan monitoring service berbayar atau scheduled
task) — jalanin manual:

- `production_health_check.py`: sesudah deploy, dan sesekali rutin (mis.
  tiap minggu) buat ngecek backup masih sehat & disk space cukup.
- `post_deploy_smoke_test.py`: SETIAP SELESAI deploy ke staging maupun
  production, sebelum ngumumin deploy selesai.

## Checklist verifikasi manual

1. `cd backend && python -m pytest` — semua test lolos, termasuk
   `test_observability.py`, `test_production_health_check.py`,
   `test_post_deploy_smoke_test.py`.
2. `cd frontend && npm test -- --run` — semua test lolos, termasuk
   `ErrorBoundary.test.jsx`.
3. `cd frontend && npm run build` — build production sukses.
4. Jalankan backend lokal (`python app.py` atau `flask run`), lalu
   `curl -i http://localhost:5000/api/health` — cek `status: "ok"`,
   header `X-Request-ID` ada, nggak ada path/secret yang bocor di body.
5. `curl -i http://localhost:5000/api/health -H "X-Request-ID: my-test-id-123"`
   — cek header respons `X-Request-ID` balik persis `my-test-id-123`.
6. `python scripts/production_health_check.py --environment local` dari
   `backend/` — cek keluaran, exit code sesuai ekspektasi (0 kalau semua
   sehat).
7. Dengan server lokal jalan:
   `python scripts/post_deploy_smoke_test.py --base-url http://localhost:5000/api`
   — cek semua pengecekan `OK`, exit code 0.
8. Sengaja matiin DB (mis. rename sementara file `instance/tracker.db`
   pas server nggak jalan, restart server, `curl /api/health`) — cek
   balik 503 `{"status":"degraded",...}` TANPA bocorin pesan exception,
   lalu kembalikan nama file aslinya.

## Ringkasan file yang berubah/ditambah

| File | Perubahan |
|---|---|
| `backend/utils/observability.py` | BARU — inti request ID, logging, error handler, DB health check |
| `backend/app.py` | Wiring observability + endpoint `/api/health` baru |
| `backend/tests/test_notifications.py` | 1 test disesuaikan (`PROPAGATE_EXCEPTIONS=False`), invariant intinya sama |
| `backend/tests/test_observability.py` | BARU — 24 test |
| `backend/scripts/production_health_check.py` | BARU |
| `backend/tests/test_production_health_check.py` | BARU — 16 test |
| `backend/scripts/post_deploy_smoke_test.py` | BARU |
| `backend/tests/test_post_deploy_smoke_test.py` | BARU — 13 test |
| `frontend/src/components/ErrorBoundary.jsx` | BARU |
| `frontend/src/components/ErrorBoundary.test.jsx` | BARU — 9 test |
| `frontend/src/main.jsx` | Membungkus `<App />` dengan `<ErrorBoundary>` |
| `backend/docs/OBSERVABILITY.md` | BARU — dokumen ini |
