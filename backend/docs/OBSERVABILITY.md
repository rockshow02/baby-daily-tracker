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

Publik, **TANPA autentikasi**, murah — cuma baca 1 baris dari
`sqlite_master` (bukan `PRAGMA integrity_check` penuh), dibatasi genuine
2 detik (default, `DEFAULT_HEALTH_CHECK_TIMEOUT_SECONDS`).

### Bound waktu yang GENUINE (bukan thread-per-request)

Implementasi SEBELUMNYA pakai
`ThreadPoolExecutor(max_workers=1).submit(...).result(timeout=...)`. Itu
BUG: kalau `.result()` timeout, baris `with ThreadPoolExecutor(...):`
berikutnya tetep manggil `executor.shutdown(wait=True)` saat keluar blok
— yang NUNGGU worker yang macet itu SAMPAI SELESAI. Jadi `/api/health`
tetep bisa nge-hang selama operasi DB-nya macet — persis kebalikan dari
tujuan timeout itu sendiri — DAN tiap request timeout ninggalin 1 thread
pool yang nunggu (resource exhaustion kalau kejadian bertubi-tubi).

Perbaikannya (`check_database_ok()` di
[`utils/observability.py`](../utils/observability.py)) DIRANCANG KHUSUS
buat deployment SQLite backend ini (lihat [`config.py`](../config.py) —
`SQLALCHEMY_DATABASE_URI` SELALU SQLite file lokal di production/staging
PythonAnywhere, nggak pernah driver lain):

- Buka 1 koneksi `sqlite3` MENTAH, read-only, PENDEK UMURNYA (connect ->
  baca `sqlite_master` -> close) — **bukan** lewat connection pool
  Flask-SQLAlchemy, dan **bukan** di thread terpisah.
- Query-nya BENERAN baca isi database (`SELECT 1 FROM sqlite_master
  LIMIT 1` — tabel sistem yang SELALU ada, termasuk di database kosong
  tanpa tabel user sama sekali), **bukan** ekspresi konstan (`SELECT 1`
  doang, TANPA `FROM`). Ini koreksi dari draft awal, ketahuan lewat
  eksperimen langsung (bukan asumsi): SQLite di beberapa platform bisa
  ngevaluasi `SELECT 1` tanpa PERNAH nyoba ambil lock kooperatif sama
  sekali (nggak nyentuh halaman database), jadi walau koneksi LAIN nahan
  `EXCLUSIVE` lock, query itu bisa aja tetep "berhasil" instan — nggak
  BENERAN membuktikan database-nya kebaca. `SELECT ... FROM
  sqlite_master` ngharuskan SQLite acquire SHARED lock buat baca halaman
  skema, jadi lock koneksi lain BENERAN ketauan. **Verifikasi empiris**
  (dijalankan langsung, bukan cuma dibaca dokumentasinya) ada di
  `test_health_check_query_reads_the_actual_database_not_a_constant` di
  `test_observability.py`.
- `timeout=` yang di-pass ke `sqlite3.connect()`, DITAMBAH `PRAGMA
  busy_timeout` eksplisit yang dijalankan begitu konek (2 lapis, nilainya
  selaras) — keduanya sama-sama nerjemahin jadi **busy_timeout SQLite
  beneran** (mekanisme retry level driver/C). Kalau file lagi dikunci
  koneksi lain, SQLite sendiri yang retry sampai batas waktu itu, lalu
  raise `OperationalError`. Bound-nya datang dari driver, BUKAN dari
  Python yang nge-cancel/kill thread.
- Karena nggak ada thread yang dibikin buat pengecekan biasa, **nggak ada
  apa pun yang bisa "nyangkut" di background** walau timeout kejadian —
  dan karena nggak ada thread yang dibikin PER REQUEST, jumlah thread
  hidup nggak pernah nambah gara-gara request `/api/health` yang
  bertubi-tubi timeout (lihat
  `test_repeated_timeouts_do_not_increase_live_thread_count` di
  `test_observability.py`).
- Path database di-resolve lewat helper ringan
  (`_resolve_sqlite_health_check_path`) yang CUMA baca metadata URL
  engine (`db.engine.url`) — **nggak** manggil `db.engine.dispose()`
  (beda dari `scripts/db_backup_common.py:resolve_active_sqlite_path`,
  yang sengaja dispose buat kebutuhan backup/restore manual — dispose di
  hot path publik ini bakal nutup koneksi idle punya request LAIN).
- Kategori kegagalan (`"timeout"` vs `"error"`) ditentukan lewat
  **seberapa lama** pengecekan berlangsung relatif ke `timeout_seconds`
  (elapsed >= timeout -> `"timeout"`; lebih cepat -> `"error"`, mis. file
  nggak ada/rusak) — BUKAN lewat parsing pesan exception-nya, biar
  kategorinya sendiri nggak pernah butuh nyimpen teks exception mentah.

**Perbedaan perilaku antar-platform yang ketahuan lewat eksperimen:**
locking SQLite ("nyoba ambil lock kalau beneran perlu baca file") itu
LOGIKA level SQLite core, sama persis di semua platform — tapi
ENFORCEMENT-nya di level OS beda. Di eksperimen dev lokal (Windows),
bahkan `SELECT 1` doang KADANG udah keblokir (kemungkinan Windows'
sendiri nerapin locking wajib di level `LockFileEx`/OS buat byte range
tertentu, independen dari protokol locking kooperatif SQLite) — jadi bug
awal ini sempet KETUTUPAN di Windows (tampak "jalan"), padahal query-nya
sendiri nggak pernah beneran nyoba lock. Di Linux (POSIX advisory
locking via `fcntl`, yang dipakai PythonAnywhere), locking itu KOOPERATIF
— kalau SQLite nggak pernah manggil mekanisme lock-nya sendiri (karena
query-nya nggak butuh baca file), OS nggak akan pernah nolak/nge-block
apa pun, walau ada koneksi lain yang nahan `EXCLUSIVE`. Itu PERSIS akar
masalah kenapa 2 test locking ini lolos di Windows tapi gagal di
PythonAnywhere Linux. Query yang beneran baca `sqlite_master` (bagian di
atas) menutup celah ini di KEDUA platform, karena sekarang SQLite-nya
sendiri yang genuinely manggil protokol locking-nya — bukan cuma
kebetulan ketutup sama enforcement OS yang platform-spesifik.

**Batasan yang diketahui:** `timeout=` sqlite3 cuma membatasi retry
SQLITE_BUSY (lock antar-koneksi) — BUKAN syscall `open()` file itu
sendiri. Kalau disk-nya sendiri yang macet total (I/O hang OS-level),
bound ini nggak berlaku. Ini dianggap di luar scope health check level
aplikasi buat deployment ini (disk lokal per-akun PythonAnywhere, bukan
network drive) — kalau suatu saat pindah ke database non-SQLite, bound
genuine kayak gini butuh dirancang ulang lewat mekanisme driver yang
sesuai (mis. `statement_timeout` Postgres), BUKAN pasang balik
`ThreadPoolExecutor` generik.

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
ikut ke body respons — cuma `"database": "unavailable"`. Kategori
kegagalan internal (`"timeout"`/`"error"`) juga TIDAK PERNAH ikut ke
body — cuma nempel di log server-side (field `db_check_category` di
baris `request_completed`, lihat bagian logging di bawah).

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

**Buat tim support:** minta user screenshot/copy pesan error yang muncul
di UI (fallback Error Boundary di bagian 5 nampilin "Kode error" client-
side, TAPI itu ID yang beda — random di browser, BUKAN `request_id`
backend). Buat korelasi ke log BACKEND, request ID yang relevan ada di
header respons `X-Request-ID` — devtools browser (tab Network -> pilih
request yang gagal -> Response Headers) selalu bisa liat ini, karena
CORS udah expose header ini secara eksplisit (lihat bagian CORS di
bawah) — nggak perlu akses ke source frontend buat baca headernya.

### CORS buat `X-Request-ID` lintas origin

Frontend (Vercel) dan backend (PythonAnywhere) beda origin — browser
CUMA ngizinin JavaScript baca header respons CUSTOM (bukan header
"simple" bawaan kayak `Content-Type`) kalau server eksplisit nyantumin
di `Access-Control-Expose-Headers`. `X-Request-ID` ada di 2 daftar
konfigurasi CORS (`app.py:create_app`):

- `allow_headers` — biar browser boleh NGIRIM `X-Request-ID` di request
  (preflight OPTIONS bakal nge-approve-nya), kalau frontend suatu saat
  eksplisit nge-set header ini sendiri.
- `expose_headers` — biar `fetch`/`XMLHttpRequest` di browser boleh
  MEMBACA `X-Request-ID` dari respons. Tanpa ini, header-nya TETAP ada
  di respons HTTP mentah (devtools tetep nunjukin), tapi kode JavaScript
  frontend nggak bisa akses nilainya.

Berlaku konsisten di SEMUA jenis respons: sukses (200), degraded (503),
error framework (404/405/dst), DAN error nggak ketangkep (500) — juga di
respons preflight OPTIONS itu sendiri. `Content-Type`, `Authorization`,
`X-Idempotency-Key` tetep ada di `allow_headers` seperti sebelumnya
(nggak dicabut), `supports_credentials=True` tetep nyala, dan origin
TETAP dibatasi lewat whitelist `FRONTEND_ORIGIN` (nggak pernah wildcard
`*` — flask-cors sendiri nolak kombinasi wildcard + credentials).

**Frontend belum diubah buat NGIRIM `X-Request-ID` di tiap request** —
task ini sengaja nggak nambahin itu (nggak ada kebutuhan konkret yang
butuh korelasi request ID sisi-klien->server yang di-generate FRONTEND;
korelasi yang ada sekarang cukup lewat request ID yang di-GENERATE
BACKEND dan dibaca dari respons). CORS-nya udah siap kalau suatu saat
dibutuhkan (mis. buat nyambungin log frontend custom ke request ID
backend), tapi nambahin behavior kirim itu di frontend BELUM dikerjakan.

### Isolasi test dari `FRONTEND_ORIGIN` environment host

`create_app()` baca `FRONTEND_ORIGIN` dari `os.environ` tiap dipanggil —
itu KEPUTUSAN YANG BENAR buat production (operator bisa ganti origin
frontend tanpa redeploy kode), tapi artinya test yang ngirim header
`Origin: http://localhost:5173` bisa gagal di mesin mana pun yang
kebetulan udah punya `FRONTEND_ORIGIN` LAIN ke-set — persis yang
kejadian di PythonAnywhere (environment host-nya nunjuk ke origin Vercel
staging beneran, bukan localhost), sementara di mesin dev Windows lokal
kebetulan `.env`-nya udah nyantumin `http://localhost:5173` jadi
"kelihatan jalan". Ini murni cacat ISOLASI TEST, bukan cacat production —
`create_app()`/CORS-nya sendiri nggak diubah buat fix ini.

Fixture `frontend_origin_env` di
[`tests/conftest.py`](../tests/conftest.py) maksa `FRONTEND_ORIGIN` ke
`TEST_FRONTEND_ORIGIN` (`"http://localhost:5173"`) SEBELUM `create_app()`
dipanggil, lewat `monkeypatch.setenv()` — otomatis balik ke nilai semula
begitu tiap test kelar (nggak ada state yang bocor antar test). Fixture
`app` (dipakai fixture `client`, dipakai HAMPIR SEMUA test di seluruh
suite) sekarang depend ke fixture ini, jadi SATU titik konfigurasi yang
berlaku ke semua test — bukan tiap test CORS ngulang-ngulang
`monkeypatch.setenv` sendiri-sendiri. Test yang butuh origin LAIN (mis.
`test_non_default_configured_origin_is_honored`) bikin app-nya sendiri
langsung (bukan lewat fixture `client` yang udah dikunci ke
`TEST_FRONTEND_ORIGIN`), buat ngebuktiin mekanismenya beneran baca
`FRONTEND_ORIGIN` apa pun, bukan hardcode ke localhost.

## 3. Logging terstruktur (JSON per baris)

Lewat `logging` standar Python (logger bernama `"babytracker"`), 1 objek
JSON per baris ke stdout (PythonAnywhere nangkep ini ke error/server log
biasa — nggak butuh setup tambahan).

**Field yang DIIZINKAN muncul** (subset, tergantung event):
`timestamp`, `level`, `event`, `request_id`, `method`, `route` (route
TEMPLATE kayak `/api/children/<int:child_id>/feeding-logs`, bukan URL
literal — lihat "Route yang nggak match" di bawah), `status`,
`duration_ms`, `user_id`, `exception_type`, `db_check_category`
(`"timeout"`/`"error"`, cuma di baris `request_completed` buat
`/api/health` yang degraded), `frames` (lokasi traceback yang udah
disaring, CUMA di baris `unhandled_exception` — lihat di bawah).

**Field yang TIDAK PERNAH dicatat SECARA DEFAULT** (di baris log
manapun): header Authorization, cookie, isi body request/response, nilai
query string, password, token, username/email, nama bayi, catatan bebas,
nama obat, nama file upload, chat ID Telegram, **pesan exception mentah
(`str(exc)`), teks traceback mentah, statement SQL, parameter SQL, path
filesystem absolut**.

### Exception yang nggak ketangkep — TANPA pesan/traceback mentah secara default

Setiap request yang selesai bikin 1 baris `event: "request_completed"`.
Exception yang nggak ketangkep route manapun (bug asli) bikin 1 baris
tambahan `event: "unhandled_exception"`, tapi **secara default field ini
CUMA berisi**:

- `exception_type` — nama class-nya doang (mis. `"RuntimeError"`), BUKAN
  pesannya.
- `frames` — daftar (maks 6, paling deket ke titik error) lokasi frame
  yang udah disaring: `{"file": "routes/auth_routes.py", "function":
  "get_current_user_id", "line": 42}`. `file` selalu relatif ke folder
  `backend/` (nggak pernah path absolut). **Nggak ada** teks baris kode,
  nilai variabel, atau pesan exception di sini — cuma lokasinya.

Ini KOREKSI dari implementasi awal, yang sempet nyalain
`logger.error(..., exc_info=True)` buat SEMUA exception nggak ketangkep
— traceback Python yang diformat SELALU diakhiri baris
`ExceptionType: pesan`, dan pesan exception SQLAlchemy/database bisa aja
ngandung statement SQL, parameter SQL (termasuk data user), atau path
database. Itu pelanggaran langsung ke aturan privasi di atas walau
"cuma" di log server, bukan di respons klien.

Traceback MENTAH (exc_info beneran) cuma bisa nyala lewat config
eksplisit `OBSERVABILITY_LOG_RAW_TRACEBACKS=true` (env var, dibaca sekali
di `create_app()`) — **BUKAN** ngikutin `DEBUG`/`FLASK_ENV` (yang bisa
aja kepasang True nggak sengaja di staging). Default-nya **False di mana
pun**, termasuk `TestConfig`/`DevConfig` yang `DEBUG=True` — flag ini
sengaja dipisah total dari `DEBUG` (lihat
`test_raw_traceback_config_defaults_to_false_and_is_not_tied_to_debug`).
Bahkan kalau operator sengaja nyalain buat debugging lokal, traceback itu
**TETAP CUMA masuk log server** — nggak pernah, dalam kondisi apa pun,
ikut ke body respons klien (lihat
`test_raw_traceback_opt_in_still_never_leaks_to_client_response`).

### Route yang nggak match route manapun

`safe_route_template()` (`utils/observability.py`) dipakai KONSISTEN di
log `request_completed` DAN `unhandled_exception`: kalau
`request.url_rule` ada, log TEMPLATE-nya (mis.
`/api/children/<int:child_id>`, bukan `/api/children/42`). Kalau NGGAK
ADA route yang match (mis. request ke path acak yang bukan endpoint
beneran), yang dicatat SELALU konstanta aman `"<unmatched>"` — TIDAK
PERNAH `request.path` mentah, yang 100% dikontrol pengirim request dan
bisa aja berisi apa pun (`/api/reset/token-secret-value`,
`/api/user/email@example.com`, dst). Query string juga TIDAK PERNAH
ikut, match atau nggak.

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
9. `curl -i http://localhost:5000/api/health -H "Origin: http://localhost:5173"`
   — cek header respons ada `Access-Control-Allow-Origin`,
   `Access-Control-Allow-Credentials: true`, DAN
   `Access-Control-Expose-Headers` yang nyebut `X-Request-ID` (biar
   browser beneran bisa baca header itu, bukan cuma ada di respons
   mentah).

## Batasan yang diketahui

- Bound waktu `/api/health` genuine buat SQLITE_BUSY (lock antar-koneksi
  SQLite), tapi TIDAK melindungi dari I/O hang level OS/filesystem
  (mis. disk/network drive yang beneran macet total) — dianggap di luar
  scope buat deployment SQLite-lokal-per-akun PythonAnywhere ini. Lihat
  bagian 1 buat detail.
- Frontend belum ngirim `X-Request-ID` di request biasa (CORS-nya udah
  siap kalau suatu saat dibutuhkan) — lihat bagian 2.
- Traceback mentah (`OBSERVABILITY_LOG_RAW_TRACEBACKS=true`) kalau
  operator sengaja nyalain buat debug lokal TETAP bisa ngandung SQL/
  parameter/path — jangan nyalain ini di staging/production, dan jangan
  nempel isi log itu ke tempat lain (tiket support, chat) tanpa disensor
  dulu.

## Ringkasan file yang berubah/ditambah

| File | Perubahan |
|---|---|
| `backend/utils/observability.py` | Inti request ID, logging, error handler, DB health check — DIREVISI (ronde 2): query health check sekarang beneran baca `sqlite_master` (bukan ekspresi konstan `SELECT 1`), ditambah `PRAGMA busy_timeout` eksplisit |
| `backend/app.py` | Wiring observability + endpoint `/api/health` — DIREVISI (ronde 2): docstring endpoint disesuaikan sama query baru; CORS/error-handling logic-nya SENDIRI nggak diubah (bug CORS ternyata di isolasi test, bukan di sini) |
| `backend/tests/conftest.py` | DIREVISI (ronde 2): fixture terpusat `frontend_origin_env` + konstanta `TEST_FRONTEND_ORIGIN`, dipakai fixture `app`/`client` — maksa `FRONTEND_ORIGIN` deterministik di seluruh suite, terlepas dari environment host |
| `backend/tests/test_notifications.py` | 1 test disesuaikan (`PROPAGATE_EXCEPTIONS=False`), invariant intinya sama |
| `backend/tests/test_observability.py` | 49 test — DIREVISI (ronde 2): 4 test baru + 1 diperkuat buat health-check query/lock/leak, 2 test baru buat isolasi CORS dari environment host |
| `backend/scripts/production_health_check.py` | Diagnostik manual (nggak diubah di ronde korektif ini) |
| `backend/tests/test_production_health_check.py` | 16 test |
| `backend/scripts/post_deploy_smoke_test.py` | Smoke test manual (nggak diubah di ronde korektif ini) |
| `backend/tests/test_post_deploy_smoke_test.py` | 13 test |
| `frontend/src/components/ErrorBoundary.jsx` | Error Boundary React (nggak diubah di ronde korektif ini) |
| `frontend/src/components/ErrorBoundary.test.jsx` | 9 test |
| `frontend/src/main.jsx` | Membungkus `<App />` dengan `<ErrorBoundary>` |
| `backend/docs/OBSERVABILITY.md` | Dokumen ini — direvisi buat perbaikan korektif ronde 1 & 2 |
