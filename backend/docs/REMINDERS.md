# Care Reminders & Schedules — Phase 1

`GET/POST /children/<child_id>/reminders`, `PATCH/DELETE
/children/<child_id>/reminders/<reminder_id>`,
`POST /children/<child_id>/reminders/<reminder_id>/occurrences/<occurrence_key>/complete|skip`
(`routes/reminder_routes.py` + `utils/reminder_engine.py`) — pengingat
perawatan terjadwal (sekali-jalan atau harian) yang statusnya
(upcoming/due/overdue) SELALU dihitung ulang saat diminta, dirancang
KHUSUS buat hosting gratis PythonAnywhere yang **tidak punya** proses
scheduler background.

## Arsitektur tanpa scheduler background

PythonAnywhere Free **tidak** menyediakan cron/scheduled-task yang
reliable buat akun ini, dan Phase 1 ini SENGAJA **tidak** memakai
Celery, Redis, task queue, worker persisten, WebSocket, Server-Sent
Events, ataupun proses lain yang harus "hidup" terus-menerus di
background.

Sebagai gantinya:

- Backend **tidak pernah** menyimpan status "upcoming"/"due"/"overdue" —
  cuma menyimpan JADWAL (`Reminder.scheduled_at` + `recurrence`) dan
  AKSI yang beneran terjadi (`ReminderAction`, cuma buat
  completed/skipped).
- Status okurensi dihitung ULANG, murni dari data yang tersimpan +
  waktu SEKARANG, setiap kali:
  - Daftar reminder diminta (`GET /children/<id>/reminders`).
  - Dashboard dimuat (endpoint yang sama, dipanggil dari `Dashboard.jsx`).
  - Aplikasi frontend kembali terlihat (`visibilitychange` browser).
  - Interval polling frontend yang berjalan selama tab masih terbuka
    (lihat bagian "Perilaku frontend" di bawah).
- Backend **selalu otoritatif** buat status ini — klien TIDAK PERNAH
  bisa mengirim status okurensi sendiri; endpoint aksi (complete/skip)
  menghitung ulang jangkauan okurensi yang sah dari data server sendiri
  sebelum menerima aksi apa pun (lihat "Rentang okurensi yang sah" di
  bawah).
- Okurensi yang terlewat (mis. user tidak membuka app selama beberapa
  hari) otomatis muncul sebagai `overdue` begitu user kembali membuka
  app — TANPA proses apa pun yang perlu "mengejar" jadwal yang
  terlewat, karena status memang dihitung dari nol setiap saat, bukan
  di-update secara bertahap oleh sesuatu yang berjalan di latar
  belakang.
- **Tidak ada** push notification server-side di Phase 1. Notifikasi
  browser (lihat di bawah) SEPENUHNYA best-effort, cuma jalan selagi
  tab aplikasi terbuka di device itu.

Konsekuensi langsung dari arsitektur ini: `utils/reminder_engine.py`
**murni fungsi Python** yang menerima `now`/`today` sebagai parameter
dari pemanggil (`routes/reminder_routes.py` memanggil `now_wib()` satu
kali per request) — modul itu sendiri **tidak pernah** memanggil jam
sistem. Ini membuat seluruh logika status/rekurensi bisa dites
deterministik dengan waktu palsu (lihat `backend/tests/test_reminders.py`),
dan membuktikan bahwa tidak ada bagian dari kode ini yang diam-diam
mengasumsikan sebuah proses akan berjalan tepat pada waktu jadwal.

## Model data

### `Reminder` (definisi jadwal)

| Field | Tipe | Keterangan |
|---|---|---|
| `id` | int | PK |
| `child_id` | int (FK) | Anak yang dituju, ter-index |
| `created_by_user_id` | int (FK) | Siapa yang membuat definisi ini |
| `reminder_type` | string | `medication` \| `doctor_visit` \| `vaccination` \| `pumping` \| `general` (CHECK constraint) |
| `title` | string(150) | **Berpotensi sensitif** (caregiver bisa mengetik nama obat) — lihat bagian Privasi |
| `scheduled_at` | datetime (WIB naive) | Untuk `none`: waktu pastinya. Untuk `daily`: JANGKAR (tanggal awal + jam:menit yang diulang tiap hari) |
| `recurrence` | string | `none` \| `daily` (CHECK constraint) |
| `is_active` | bool | Reminder nonaktif tidak pernah menghasilkan okurensi apa pun |
| `created_at` / `updated_at` | datetime (UTC) | Metadata baris, konsisten dengan konvensi model lain di app ini |

### `ReminderAction` (SATU aksi atas SATU okurensi)

| Field | Tipe | Keterangan |
|---|---|---|
| `id` | int | PK |
| `reminder_id` | int (FK) | |
| `occurrence_at` | datetime (WIB naive) | Tanggal + jam:menit okurensi spesifik yang diaksi |
| `status` | string | `completed` \| `skipped` (CHECK constraint — **`pending` TIDAK PERNAH disimpan**, lihat di bawah) |
| `acted_at` | datetime (WIB naive) | Kapan aksi ini dilakukan |
| `acted_by_user_id` | int (FK) | Siapa yang melakukan |
| `linked_log_type` | string, nullable | `medication_log` \| `pumping_log` \| `doctor_visit`, kalau aksi ini lahir dari alur "Catat sekarang" |
| `linked_log_id` | int, nullable | ID catatan yang ditautkan |

**Kenapa tidak ada baris untuk okurensi "pending"**: menyimpan 1 baris
per hari untuk setiap reminder harian yang aktif akan menghasilkan
jumlah baris yang tumbuh tanpa batas seiring waktu, padahal
"pending" (belum ada aksi) sudah bisa disimpulkan 100% dari
**ketiadaan** baris `ReminderAction` untuk tanggal itu. Baris di tabel
ini HANYA dibuat pada saat caregiver benar-benar menyelesaikan atau
melewati sebuah okurensi — riwayat completed/skipped yang sudah
tersimpan **tidak pernah** dihapus/ditimpa oleh perhitungan status
berikutnya.

**Uniqueness**: `UNIQUE(reminder_id, occurrence_at)` — inilah jaminan
utama "1 okurensi cuma boleh punya 1 aksi", ditegakkan di level
database (bukan cuma di level aplikasi), lihat bagian Idempotensi.

## Kunci okurensi (`occurrence_key`)

Format `YYYY-MM-DD` (tanggal WIB lokal), dipakai SERAGAM untuk reminder
`none` maupun `daily`:

- `none`: satu-satunya kunci yang sah = `scheduled_at.date()`.
- `daily`: kunci = tanggal WIB kalender okurensi itu; jam:menitnya
  selalu diambil dari `Reminder.scheduled_at` aslinya (bukan disimpan
  ulang per hari).

## Timezone (Asia/Jakarta)

Semua kolom timestamp domain (`scheduled_at`, `occurrence_at`,
`acted_at`) memakai konvensi yang SUDAH ada di seluruh app ini
(`utils/timezone_utils.py`): **wall-clock WIB naive**, bukan UTC. Batas
hari kalender untuk rekurensi harian dihitung dari nilai WIB ini
LANGSUNG (`datetime.combine(tanggal_wib, jam_asli)`), **tidak pernah**
lewat konversi UTC — jadi tidak ada risiko sebuah okurensi "meleset satu
hari" akibat pergeseran zona waktu. `now`/`today` yang dipakai
`utils/reminder_engine.py` SELALU `now_wib()`/`.date()`-nya, dipanggil
sekali di layer route.

Respons API secara eksplisit menyertakan `"timezone": "Asia/Jakarta"`
dan `server_time` (waktu WIB server saat respons dibuat) di setiap
`GET /reminders` — frontend **tidak pernah** memakai locale/timezone
browser sebagai sumber kebenaran untuk menghitung rekurensi/status;
semua state datang jadi dari server.

## Status okurensi & grace window

Status dihitung `utils/reminder_engine.py:compute_occurrence_state()`:

| Status | Kondisi |
|---|---|
| `upcoming` | `occurrence_at` lebih dari 15 menit ke depan |
| `due` | dari 15 menit sebelum sampai 30 menit sesudah `occurrence_at` (inklusif di kedua ujung) |
| `overdue` | lebih dari 30 menit sesudah `occurrence_at`, dan belum ada `ReminderAction` |
| `completed` | ada `ReminderAction` dengan `status='completed'` |
| `skipped` | ada `ReminderAction` dengan `status='skipped'` |

**Ambang 15/30 menit ini adalah heuristik produk** (dipilih supaya UI
tidak buru-buru bilang "terlambat" hanya karena telat semenit, dan
tidak diam-diam menyembunyikan sesuatu yang sebentar lagi jatuh tempo),
**bukan** standar medis apa pun. Diuji eksplisit di
`backend/tests/test_reminders.py::test_one_time_reminder_state_thresholds`
pada nilai batas persis (15, 30 menit).

## Rekurensi harian & jendela tampilan

Reminder `daily` **tidak** membuat 1 baris per hari. Okurensi hari
apa pun dihitung on-the-fly: `tanggal + jam:menit dari scheduled_at`.

Daftar okurensi yang **ditampilkan** di 1 respons `GET /reminders`
dibatasi jendela `DAILY_LOOKBACK_DAYS = 14` hari ke belakang + hari ini
(maksimal 15 baris per reminder harian, TIDAK PERNAH lebih walau
reminder-nya sudah aktif berbulan-bulan) — jendela ini mencakup okurensi
`due`/`overdue` yang perlu ditindaklanjuti **dan** riwayat
completed/skipped terkini (dua-duanya perlu ditampilkan di layar
Reminder — lihat bagian Frontend). Okurensi di luar jendela ini tidak
ikut muncul di 1 respons list, tapi baris `ReminderAction`-nya sendiri
(kalau ada) tetap permanen di database.

**Rentang okurensi yang sah untuk endpoint aksi** (`complete`/`skip`)
sedikit berbeda dari jendela TAMPILAN di atas —
`valid_occurrence_date_range()`:
- `none`: hanya `scheduled_at.date()` yang sah.
- `daily`: `[max(scheduled_at.date(), today - 14 hari), today]` —
  boleh menindaklanjuti okurensi historis yang lebih tua dari yang
  kebetulan tampil di halaman list saat itu (selama masih dalam jendela
  14 hari), tapi **tidak pernah** okurensi masa depan (belum terjadi)
  ataupun lebih tua dari jendela ini (mencegah aksi historis tak
  terbatas).

## Ringkasan dashboard

`GET /reminders` juga mengembalikan `summary` (`due_count`,
`overdue_count`, `next_upcoming_at`) yang diagregasi dari SEMUA
reminder aktif anak itu — endpoint yang SAMA dipakai baik oleh layar
Reminder penuh maupun ringkasan ringkas di Dashboard, supaya tidak ada
2 jalur perhitungan status yang bisa berbeda hasilnya.

## Roles & permissions

Memakai helper otorisasi terpusat yang SUDAH ADA
(`utils/access.py` — `resolve_role`, `WRITE_ROLES`,
`can_delete_record`), **tidak** memperkenalkan sistem izin kedua:

| Aksi | Owner | Editor | Viewer |
|---|---|---|---|
| Lihat reminder | ✅ | ✅ | ✅ |
| Buat reminder | ✅ | ✅ | ❌ |
| Ubah reminder | ✅ (semua) | ✅ (buatan sendiri saja — `can_delete_record`) | ❌ |
| Hapus reminder | ✅ (semua) | ✅ (buatan sendiri saja) | ❌ |
| Selesaikan/lewati okurensi | ✅ | ✅ (**siapa pun** reminder-nya, tidak dibatasi kepemilikan) | ❌ |

"Selesaikan/lewati" SENGAJA tidak dibatasi kepemilikan reminder (beda
dari ubah/hapus definisinya) — mencatat bahwa sebuah perawatan sudah
dilakukan adalah tindakan baru, bukan mengedit riwayat orang lain,
persis seperti caregiver mana pun boleh mencatat pemberian makan/tidur
baru terlepas siapa yang mencatat sebelumnya.

Setiap objek reminder di respons list menyertakan `can_edit`/
`can_delete`/`can_act` yang SUDAH dihitung server — frontend tidak
pernah menyimpulkan izin sendiri dari role mentah.

## Idempotensi & konkurensi

Dua sumbu keunikan yang INDEPENDEN, keduanya harus dijaga:

1. **`client_request_id` yang sama diulang** (klik ganda yang
   sebenarnya SATU permintaan yang di-retry, replay antrian offline,
   koneksi putus di tengah request) → server mengembalikan respons
   ASLI yang sudah tersimpan, **tidak** membuat baris baru. Memakai
   pola `IdempotencyKey` yang sama dengan endpoint log lain
   (`utils/idempotency.py`), dicocokkan lewat fingerprint hash payload
   (`reminder_id` + `occurrence_key` + info tautan log) — kalau key
   yang sama dipakai ulang dengan payload yang BEDA (bug klien), server
   menolak dengan `409`, bukan diam-diam mengembalikan hasil lama yang
   salah.
2. **Okurensi yang sama diaksi dari `client_request_id` yang BEDA**
   (klik dobel asli dari pengguna — tiap klik menghasilkan idempotency
   key baru — ATAU dua caregiver berbeda menekan tombol hampir
   bersamaan) → ditegakkan lewat `UNIQUE(reminder_id, occurrence_at)`
   di level database. Endpoint aksi CEK dulu (mencegah kasus umum),
   LALU tangkap `IntegrityError` dari commit sebagai jaring pengaman
   terakhir untuk race genuine — dua-duanya berujung `409` dengan
   `current_status` yang jelas, **tidak pernah** exception 500 yang
   tidak tersanitasi.

Akibat langsung dari desain ini: **okurensi yang sudah `completed`
tidak pernah bisa "tertimpa" jadi `skipped`** oleh retry/caregiver
lain (dan sebaliknya) — begitu 1 baris `ReminderAction` ada untuk
sebuah okurensi, semua percobaan aksi lain (kecuali replay
`client_request_id` yang identik) berhenti di `409`. Fase 1 sengaja
**tidak** menyediakan alur pembatalan/reversal eksplisit.

SQLite: seperti endpoint lain di app ini, penulisan bersamaan
diserialkan oleh SQLite sendiri (single-writer) — kegagalan commit
akibat race ditangkap sebagai `IntegrityError` dan diproses ulang
sebagai konflik terdeteksi, bukan crash.

## "Catat sekarang"

`complete` boleh menyertakan `{"linked_log_type": ..., "linked_log_id": ...}`
opsional. `linked_log_type` dibatasi allowlist
(`medication_log`/`pumping_log`/`doctor_visit`) dan divalidasi bahwa
catatan itu **benar-benar milik anak yang sama** sebelum ditautkan
(mencegah IDOR lintas anak). Server **tidak pernah** membuat catatan
perawatan otomatis hanya karena reminder jatuh tempo — alur yang
didukung Phase 1: pengguna membuka form catatan yang sudah ada (dengan
field aman terisi otomatis dari reminder), menyimpannya sendiri lewat
endpoint yang sudah ada, BARU KEMUDIAN memanggil `complete` dengan
`linked_log_id` hasil penyimpanan itu. Untuk reminder `vaccination`,
Phase 1 cukup mengarahkan ke layar vaksinasi yang sudah ada (tidak ada
tautan otomatis). Untuk `general`, `complete` tidak pernah membuat
catatan apa pun.

## Audit trail

Terintegrasi ke `utils/audit.py`/`CaregiverAuditEvent` yang sudah ada:

- `create`/`update`/`delete` pada `entity_type="reminder"` untuk
  mutasi definisi reminder. `title` ada di `PRIVATE_CHANGED_FIELDS`
  (bisa berisi nama obat) — perubahan `title` cuma tercatat sebagai
  marker generik `private_details`, **tidak pernah** nilainya.
  `reminder_type`/`scheduled_at`/`recurrence`/`is_active` aman disebut
  namanya.
- Menyelesaikan/melewati sebuah okurensi memakai **2 entity_type baru**
  yang terpisah — `reminder_occurrence_completed` dan
  `reminder_occurrence_skipped` — dengan `action="create"` (1 baris
  `ReminderAction` baru benar-benar dibuat). Nama entity_type ITU
  SENDIRI adalah metadata "kejadian apa ini" (persis seperti
  `mood_log` vs `feeding_log` berbeda entity_type, bukan kebocoran
  nilai) — dipilih supaya kebijakan `changed_fields` yang ketat ("cuma
  nama field, tidak pernah nilai") tidak perlu dilanggar untuk
  menyimpan `status`. `entity_id` = `ReminderAction.id`, sehingga
  detail lengkap (reminder_id, occurrence_at, siapa yang beraksi) tetap
  bisa ditelusuri balik dari baris permanen `reminder_actions` bila
  diperlukan, tanpa perlu menyimpannya dobel di baris audit.

## Kontrak API

Semua endpoint memakai konvensi otentikasi/error/observability yang
sudah ada (header `Authorization: Bearer`, `X-Request-ID`, error
`{"error": "..."}`).

```
GET    /api/children/<child_id>/reminders
POST   /api/children/<child_id>/reminders
PATCH  /api/children/<child_id>/reminders/<reminder_id>
DELETE /api/children/<child_id>/reminders/<reminder_id>
POST   /api/children/<child_id>/reminders/<reminder_id>/occurrences/<occurrence_key>/complete
POST   /api/children/<child_id>/reminders/<reminder_id>/occurrences/<occurrence_key>/skip
```

`GET` balikin:

```json
{
  "child_id": 1,
  "timezone": "Asia/Jakarta",
  "server_time": "2026-08-23T10:00:00+07:00",
  "reminders": [
    {
      "id": 5, "child_id": 1, "created_by_user_id": 2,
      "reminder_type": "medication", "title": "Obat pagi",
      "scheduled_at": "2026-08-23T08:00:00+07:00", "recurrence": "daily",
      "is_active": true, "created_at": "...", "updated_at": "...",
      "can_edit": true, "can_delete": true, "can_act": true,
      "next_occurrence_at": "2026-08-24T08:00:00+07:00",
      "occurrences": [
        {
          "occurrence_key": "2026-08-23", "occurrence_at": "2026-08-23T08:00:00+07:00",
          "state": "completed", "status": "completed",
          "acted_at": "...", "acted_by_user_id": 2, "acted_by_name": "Bunda",
          "linked_log_type": "medication_log", "linked_log_id": 41
        }
      ]
    }
  ],
  "summary": { "due_count": 0, "overdue_count": 1, "next_upcoming_at": "2026-08-24T08:00:00+07:00" }
}
```

`POST create` menerima `{reminder_type, title, scheduled_at, recurrence?}`.
`PATCH` menerima subset field mana pun (partial update). `complete`/`skip`
menerima body opsional `{linked_log_type?, linked_log_id?}`.

Error: `401` belum login, `404` anak/reminder tidak ada atau tidak bisa
diakses (outsider tidak bisa membedakan dua kasus ini), `403` role tidak
punya izin, `400` validasi gagal / occurrence_key di luar jangkauan,
`409` konflik aksi (occurrence sudah beraksi, atau idempotency key
dipakai ulang dengan payload berbeda).

## Privasi

`title` **tidak pernah** dikirim ke notifikasi browser, log server,
ataupun audit trail apa adanya — hanya teks generik per `reminder_type`
yang dipakai di sana (lihat `frontend/src/utils/reminderNotifications.js`).
Tidak ada nama obat, diagnosis, nama dokter, dosis, atau teks bebas lain
yang pernah masuk ke `Notification` browser.

## Migrasi database

Dua tabel BARU (`reminders`, `reminder_actions`) — **tidak ada** kolom
baru di tabel yang sudah ada, jadi **tidak ada** entri baru yang perlu
ditambahkan ke `COLUMNS_TO_ENSURE`. `db.create_all()` di
`scripts/migrate_production.py` (langkah yang sudah ada, dipanggil di
akhir `migrate()`) otomatis membuat kedua tabel ini kalau belum ada —
persis pola yang sama seperti `caregiver_audit_events` sebelumnya.
Aman dijalankan berkali-kali (idempoten): tabel yang sudah ada tidak
pernah di-drop/dibuat ulang oleh `db.create_all()`.

### Deployment PythonAnywhere (Bash console akun production)

```bash
cd ~/baby-daily-tracker
git pull origin main
cd backend
source venv/bin/activate   # kalau pakai virtualenv terpisah
pip install -r requirements.txt
python scripts/migrate_production.py
```

Lalu reload web app dari tab **Web** dashboard PythonAnywhere (tombol
hijau "Reload"). **Tidak ada** langkah scheduled-task/cron yang perlu
dikonfigurasi — fitur ini sepenuhnya jalan lewat request biasa.

### Rollback

Karena migrasi ini CUMA menambah 2 tabel baru (tidak mengubah/menghapus
apa pun di tabel yang sudah ada), rollback aman dilakukan dengan:

1. `git checkout <commit-sebelumnya>` di server (kembali ke kode lama
   yang tidak mengenal `reminders`/`reminder_actions`).
2. Reload web app.
3. Tabel `reminders`/`reminder_actions` yang sudah terlanjur dibuat
   **boleh dibiarkan** (kode lama tidak pernah menyentuhnya, jadi tidak
   ada risiko) — atau, kalau ingin benar-benar bersih, hapus manual
   lewat SQLite console (`DROP TABLE reminders; DROP TABLE
   reminder_actions;`) SETELAH memverifikasi tidak ada data yang masih
   ingin disimpan. **Tidak pernah** menjalankan `DROP TABLE` sebagai
   bagian dari script migrasi otomatis.

## Perilaku offline

Lihat `frontend/src/utils/reminderCache.js` untuk detail cache, dan
bagian Offline di dokumen ini untuk kebijakan lengkap — ringkasannya:
snapshot list reminder terakhir yang berhasil dimuat di-cache per
`(userId, childId)` di localStorage (skema bervarsi, isolasi otomatis
lewat namespace key — pola yang identik dengan
`frontend/src/utils/insightCache.js`). Aksi complete/skip offline
masuk antrian offline yang sudah ada
(`frontend/src/utils/offlineQueue.js`) dengan `X-Idempotency-Key` yang
stabil, direplay lewat `useOfflineSync.js` yang sudah ada — **tidak**
ada mekanisme offline baru yang diciptakan khusus untuk fitur ini.

## Notifikasi browser (best-effort)

- **Tidak** diminta otomatis saat halaman dimuat — cuma via tombol
  eksplisit "Aktifkan notifikasi saat aplikasi terbuka" di layar
  Reminder.
- Cuma jalan selagi tab aplikasi ini terbuka di device itu — **tidak
  ada** jaminan notifikasi kalau app ditutup/device dimatikan (batasan
  PythonAnywhere Free + batasan browser, dijelaskan eksplisit di UI).
- Teks notifikasi SELALU generik per `reminder_type` (lihat contoh di
  bagian Frontend implementation) — **tidak pernah** memuat `title`
  reminder atau detail medis apa pun.
- Deduplikasi per okurensi disimpan di localStorage (cuma
  `occurrence_key`, bukan data sensitif) — okurensi yang sama tidak
  pernah memicu notifikasi dobel di browser yang sama.

## Manual QA checklist

1. Buat reminder sekali-jalan 20 menit ke depan sebagai owner — status
   awal `upcoming`.
2. Tunggu/ubah waktu sistem sampai masuk jendela `due` — indikator
   dashboard & layar Reminder berubah tanpa perlu reload manual (lewat
   polling interval).
3. Biarkan lewat 30 menit tanpa aksi — status `overdue`.
4. Selesaikan (`Complete`) — status jadi `completed`, tidak bisa
   diselesaikan/dilewati dua kali (tombol nonaktif/pesan konflik).
5. Buat reminder harian jam tertentu, biarkan 2-3 hari tanpa dibuka,
   buka lagi — okurensi hari-hari yang terlewat muncul sebagai
   `overdue` terpisah per hari, okurensi hari ini tetap independen.
6. Sebagai editor: buat reminder sendiri (bisa edit/hapus), coba edit
   reminder milik owner (ditolak), tetap bisa complete/skip reminder
   milik owner.
7. Sebagai viewer: pastikan semua tombol mutasi disembunyikan/nonaktif,
   dan request langsung ke API tetap ditolak `403`.
8. Klik "Catat sekarang" pada reminder medication — form obat terbuka
   dengan field waktu terisi, simpan, verifikasi occurrence otomatis
   `completed` dan tertaut ke catatan yang baru dibuat.
9. Offline: buka layar Reminder (harus tampil dari cache dengan
   penanda "terakhir tersinkron"), selesaikan 1 occurrence offline
   (masuk status "menunggu sinkron"), sambungkan kembali ke internet,
   verifikasi tersinkron otomatis tanpa duplikasi.
10. Aktifkan notifikasi browser, biarkan 1 reminder jatuh tempo selagi
    tab terbuka — notifikasi generik muncul sekali saja (tidak dobel
    walau interval polling jalan berkali-kali).
11. Tolak izin notifikasi — verifikasi UI tidak meminta ulang berkali-
    kali dan tetap menjelaskan batasannya dengan jelas.
12. Ganti akun (logout/login akun lain) — verifikasi tidak ada data
    reminder akun sebelumnya yang bocor di cache/notifikasi.
13. Cabut akses caregiver dari anak tertentu, revalidasi online —
    verifikasi cache reminder anak itu terhapus dari device caregiver
    yang dicabut aksesnya.
