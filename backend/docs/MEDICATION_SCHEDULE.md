# Medication Schedule & Adherence — Phase 1

`GET/POST /children/<child_id>/medication-schedules`,
`PATCH/DELETE /children/<child_id>/medication-schedules/<schedule_id>`,
`POST /children/<child_id>/medication-schedules/<schedule_id>/occurrences/<occurrence_key>/administer|skip`,
`GET /children/<child_id>/medication-schedules/adherence`
(`routes/medication_schedule_routes.py` + `utils/medication_schedule_engine.py`)
— regimen obat berulang (1-6 kali/hari) yang statusnya
(upcoming/due/overdue) SELALU dihitung ulang saat diminta, dan yang
menandai dosis "sudah diberikan" otomatis mengisi `MedicationLog` yang
SUDAH ADA tanpa entri data ganda. Dirancang KHUSUS buat hosting gratis
PythonAnywhere yang **tidak punya** proses scheduler background — pola
arsitektur, model data, dan mekanisme idempotensi di sini SENGAJA
REUSE penuh dari Care Reminders & Schedules Phase 1
(`backend/docs/REMINDERS.md`), bukan mesin/skema kedua yang bersaing.

## Arsitektur tanpa scheduler background

Sama persis prinsip `backend/docs/REMINDERS.md` bagian "Arsitektur
tanpa scheduler background" — **tidak** memakai Celery, Redis, cron,
scheduled task, worker persisten, WebSocket, atau proses lain yang
harus "hidup" terus-menerus:

- `MedicationSchedule` **tidak pernah** menyimpan status
  "due"/"overdue" — cuma jadwal (nama obat, dosis, jam pemberian per
  hari, tanggal mulai/selesai). `MedicationDoseAction` cuma menyimpan
  AKSI yang beneran terjadi (administered/skipped).
- Status okurensi dihitung ULANG murni dari data tersimpan + waktu
  SEKARANG, setiap kali `GET /medication-schedules` diminta (dashboard,
  layar Jadwal Obat, reconnect, dst).
- Backend **selalu otoritatif** — endpoint administer/skip menghitung
  ulang jangkauan okurensi yang sah dari data server sendiri sebelum
  menerima aksi apa pun (lihat "Rentang okurensi yang sah" di bawah).
- Dosis yang terlewat (app tidak dibuka beberapa hari) otomatis muncul
  sebagai `overdue` begitu dibuka lagi — tanpa proses apa pun yang
  "mengejar" jadwal.

`utils/medication_schedule_engine.py` **murni fungsi Python**, `now`/
`today` SELALU parameter dari pemanggil (`routes/medication_schedule_routes.py`
memanggil `now_wib()` sekali per request) — modul ini sendiri tidak
pernah memanggil jam sistem, dan **reuse langsung**
`utils/reminder_engine.py:compute_occurrence_state`/`DUE_AFTER_MINUTES`
buat ambang grace-window (bukan menyalin ulang angka/logikanya). Yang
benar-benar baru di modul ini cuma dukungan **beberapa jam pemberian
per hari** (`times_of_day`), sesuatu yang belum ada di reminder harian
biasa (1 jam per hari).

## Model data

### `MedicationSchedule` (definisi regimen)

| Field | Tipe | Keterangan |
|---|---|---|
| `id` | int | PK |
| `child_id` | int (FK) | Anak yang dituju, ter-index |
| `created_by_user_id` | int (FK) | Siapa yang membuat definisi ini |
| `medication_name` | string(150) | **Sensitif** (identitas obat spesifik anak) — lihat Privasi/Audit |
| `dose_value` | float, nullable | Opsional, **berpasangan** dengan `dose_unit` (dua-duanya diisi atau dua-duanya kosong) |
| `dose_unit` | string(20), nullable | Allowlist: `ml, mg, mcg, tetes, sendok_takar, tablet, kapsul, sachet, puff, unit` — kompatibel dengan `MedicationLog.dosage` bebas-teks yang sudah ada |
| `instructions` | text, nullable | **Sensitif**, teks bebas caregiver, maks 500 karakter |
| `start_date` | date, ter-index | Regimen belum menghasilkan okurensi apa pun sebelum tanggal ini |
| `end_date` | date, nullable | Opsional; tidak boleh sebelum `start_date`; durasi maks 366 hari |
| `times_of_day` | JSON (list string `"HH:MM"`) | Minimal 1, maksimal 6 jam/hari; disimpan TERNORMALISASI (unik, terurut) |
| `timezone` | string(30) | Selalu `"Asia/Jakarta"` di Phase 1 (kolom disiapkan buat multi-zona nanti, TIDAK dipakai sekarang — app ini WIB-only) |
| `is_active` | bool | Regimen nonaktif tidak pernah menghasilkan okurensi baru |
| `created_at` / `updated_at` | datetime (UTC) | Metadata baris |

**Sengaja TIDAK menyimpan status due/overdue** apa pun — persis
kebijakan `Reminder`, lihat bagian Arsitektur di atas.

### `MedicationDoseAction` (SATU aksi atas SATU okurensi dosis)

| Field | Tipe | Keterangan |
|---|---|---|
| `id` | int | PK |
| `schedule_id` | int (FK), ter-index | |
| `occurrence_at` | datetime (WIB naive), ter-index | Tanggal + jam:menit okurensi TERJADWAL yang diaksi |
| `status` | string(12) | `administered` \| `skipped` (CHECK constraint — **`pending` TIDAK PERNAH disimpan**) |
| `acted_at` | datetime (WIB naive) | Waktu AKSI beneran dicatat — bisa berbeda dari `occurrence_at` (caregiver baru sempat menandai belakangan) |
| `acted_by_user_id` | int (FK) | Siapa yang menandai |
| `medication_log_id` | int (FK), nullable | Diisi CUMA buat `status='administered'` — link ke `MedicationLog` yang otomatis dibuat (lihat bagian Integrasi di bawah). **Selalu `NULL` buat `skipped`** |
| `created_at` | datetime (UTC) | |

**Uniqueness**: `UNIQUE(schedule_id, occurrence_at)` — jaminan utama "1
okurensi dosis cuma boleh punya 1 aksi", ditegakkan di level database.

**`MedicationLog` (model YANG SUDAH ADA) dipakai apa adanya** — tidak
ada perubahan skema padanya, tidak ada sistem riwayat obat kedua.
Kolom `dosage`-nya yang bebas-teks diisi hasil gabungan
`f"{dose_value:g} {dose_unit}"` dari schedule (mis. `"5 ml"`) saat
dosis ditandai administered.

## Kunci okurensi (`occurrence_key`)

Format `YYYY-MM-DDTHH:MM` (tanggal + jam:menit WIB lokal, **bukan**
cuma tanggal seperti reminder) — perlu menyebut JAM eksplisit karena 1
schedule bisa punya beberapa okurensi per hari. Endpoint
administer/skip memvalidasi jam pada key ini benar-benar ada di
`schedule.times_of_day` (bukan cuma tanggalnya yang dicek), sebelum
memvalidasi tanggal.

## Timezone (Asia/Jakarta)

Sama persis konvensi `Reminder` (lihat `backend/docs/REMINDERS.md`
bagian Timezone) — semua timestamp domain WIB naive, batas hari
kalender dihitung langsung dari nilai WIB (tidak pernah lewat konversi
UTC). Respons `GET /medication-schedules` menyertakan `"timezone":
"Asia/Jakarta"` dan `server_time` eksplisit.

## Status okurensi & grace window (REUSE penuh dari Reminders)

Ambang & label SAMA PERSIS `utils/reminder_engine.py:compute_occurrence_state`
(dipanggil langsung, bukan disalin ulang):

| Status | Kondisi |
|---|---|
| `upcoming` | `occurrence_at` lebih dari 15 menit ke depan |
| `due` | dari 15 menit sebelum sampai 30 menit sesudah `occurrence_at` (inklusif) |
| `overdue` | lebih dari 30 menit sesudah `occurrence_at`, dan belum ada `MedicationDoseAction` |
| `administered` | ada `MedicationDoseAction` dengan `status='administered'` |
| `skipped` | ada `MedicationDoseAction` dengan `status='skipped'` |

Ini heuristik produk yang sama dengan Care Reminders (bukan standar
medis apa pun) — satu kebijakan, dua mesin yang membaginya.

## Rentang okurensi yang sah & jendela tampilan

`valid_occurrence_range(schedule, today)` (pola SAMA PERSIS
`valid_occurrence_date_range()` milik Reminder) balikin `(earliest_dt,
latest_dt)` inklusif, atau **`None`** eksplisit kalau tidak ada
okurensi yang sah sama sekali sekarang:

- `None` kalau `start_date > today` (regimen belum mulai — okurensi
  masa depan **tidak pernah** bisa ditandai lebih awal).
- Dibatasi `end_date` (kalau ada) atau `today`, mana yang lebih awal.
- Dibatasi ke belakang oleh `LOOKBACK_DAYS = 14` hari + hari ini (SAMA
  PERSIS `DAILY_LOOKBACK_DAYS` milik Reminder) — okurensi lebih tua
  dari ini ditolak, mencegah query/generasi okurensi tak terbatas untuk
  regimen yang sudah aktif berbulan-bulan.

`compute_schedule_occurrences()` menghasilkan MAKSIMAL
`(LOOKBACK_DAYS + 1) × MAX_TIMES_PER_DAY` = `15 × 6` = 90 baris per
schedule per respons list — tidak pernah lebih, walau regimen sudah
aktif setahun. Endpoint administer/skip memvalidasi tanggal via
`valid_occurrence_range()` **dan** jam via keanggotaan
`schedule.times_of_day` sebelum menerima aksi apa pun.

Setiap objek okurensi di respons list menyertakan `can_act` yang
**digabung server** dari role, status okurensi (`status is None`), DAN
`valid_occurrence_range()` — field yang SAMA PERSIS dipakai endpoint
aksi. Frontend memakai field ini langsung, tidak pernah menghitung
ulang kelayakan tanggal/jam sendiri dari timezone browser.

## Integrasi dengan `MedicationLog` yang sudah ada

Menandai dosis **`administered`** SELALU otomatis membuat 1 baris
`MedicationLog` BARU (beda dari alur "Catat sekarang" opsional 2-langkah
milik Reminder) — **dalam transaksi database yang SAMA** dengan baris
`MedicationDoseAction`-nya:

1. `MedicationLog` di-`add()` + `flush()` (dapat `id`-nya).
2. `MedicationDoseAction` (dengan `medication_log_id` terisi) di-`add()`
   + `flush()`.
3. 2 baris audit (`medication_log` create + `medication_dose_administered`
   create) di-`add()`.
4. **Satu** `db.session.commit()` di ujung — kalau gagal di mana pun
   sebelum baris ini (termasuk saat konstruksi `MedicationLog` ATAU
   flush pertama), **tidak ada** yang ter-commit sama sekali (session
   dibuang begitu request berakhir, lihat `PROPAGATE_EXCEPTIONS=False`
   di `app.py`/`utils/observability.py` — exception jadi respons `500`
   yang aman, TIDAK PERNAH baris setengah jadi). Diuji eksplisit di
   `backend/tests/test_medication_schedule.py::test_administer_transaction_rolls_back_entirely_if_log_creation_fails`.

Menandai dosis **`skipped`** **tidak pernah** membuat `MedicationLog`
apa pun — tidak ada obat yang beneran diberikan.

`MedicationLog.timestamp` diisi `acted_at` (waktu AKSI beneran
dicatat), **bukan** `occurrence_at` (waktu TERJADWAL) — dua field ini
sengaja dipisah di `MedicationDoseAction` juga, supaya "obat dikasih
jam berapa persisnya" tetap akurat walau caregiver baru sempat menandai
belakangan.

Field `illness_id`/`notes` milik `MedicationLog` **tidak pernah** diisi
lewat jalur ini (tetap `NULL`) — caregiver yang ingin menautkan ke
catatan sakit atau menambah catatan bebas tetap memakai form obat manual
yang sudah ada, konsisten dengan kebijakan "tidak membuat sistem
riwayat obat kedua".

## Idempotensi & konkurensi

Pola SAMA PERSIS Care Reminders (lihat `backend/docs/REMINDERS.md`
bagian Idempotensi & konkurensi) — dua sumbu keunikan independen:

1. **`client_request_id` (`X-Idempotency-Key`) yang sama diulang** →
   respons ASLI dikembalikan, tidak ada baris baru (baik
   `MedicationDoseAction` maupun `MedicationLog`-nya). Fingerprint hash
   payload mencegah key yang sama dipakai ulang dengan data berbeda
   (`409` kalau tidak cocok).
2. **Okurensi yang sama diaksi dari `client_request_id` yang BEDA**
   (klik dobel, atau 2 caregiver hampir bersamaan) → ditegakkan
   `UNIQUE(schedule_id, occurrence_at)` di database. Endpoint cek dulu
   secara proaktif, lalu menangkap `IntegrityError` dari commit sebagai
   jaring pengaman terakhir untuk race genuine — SELURUH transaksi
   (termasuk `MedicationLog` yang sudah di-flush) ikut roll back
   bersama pada race yang kalah, jadi **tidak pernah** ada log obat
   "yatim" tanpa aksi yang menang.

Akibatnya: dosis yang sudah `administered` **tidak pernah** bisa
"tertimpa" jadi `skipped` (dan sebaliknya) oleh retry/caregiver lain —
begitu 1 baris `MedicationDoseAction` ada, percobaan lain berhenti di
`409` dengan `current_status` yang jelas. Fase 1 sengaja **tidak**
menyediakan alur undo/koreksi eksplisit (lihat Keterbatasan di bawah).

## Roles & permissions

Memakai helper otorisasi terpusat yang sudah ada (`utils/access.py`),
**tidak** memperkenalkan sistem izin kedua:

| Aksi | Owner | Editor | Viewer |
|---|---|---|---|
| Lihat jadwal & ringkasan kepatuhan | ✅ | ✅ | ✅ |
| Buat jadwal | ✅ | ✅ | ❌ |
| Ubah/nonaktifkan/hapus jadwal | ✅ (semua) | ✅ (buatan sendiri saja — `can_delete_record`) | ❌ |
| Tandai dosis diberikan/dilewati | ✅ | ✅ (**jadwal siapa pun**, tidak dibatasi kepemilikan) | ❌ |

"Tandai diberikan/dilewati" sengaja tidak dibatasi kepemilikan jadwal
(sama seperti "selesaikan/lewati" milik Reminder) — mencatat bahwa obat
sudah diberikan adalah tindakan baru, bukan mengedit definisi jadwal
orang lain.

Setiap objek schedule di respons list menyertakan `can_edit`/
`can_delete`/`can_act` yang sudah dihitung server. Endpoint adherence
bisa diakses semua role (viewer termasuk) karena murni baca.

## Perilaku offline

Pola SAMA PERSIS Care Reminders:

- **Administer/skip dosis** boleh diantrikan offline
  (`frontend/src/utils/offlineQueue.js`, 2 pattern baru di
  `OFFLINE_QUEUEABLE_PATHS` milik `client.js`) — `X-Idempotency-Key`
  yang stabil, UI optimis menandai "Menunggu sinkron" sampai request
  aslinya berhasil, direplay lewat `useOfflineSync.js` yang sudah ada.
  Kalau okurensi ternyata sudah ditandai caregiver lain di server
  duluan, replay itu balik `409` dan UI memuat ulang daftar dengan
  pesan yang jelas — **tidak pernah** duplikat `MedicationLog`.
- **Membuat/mengubah/menghapus DEFINISI jadwal** SENGAJA tetap
  online-only (tombol dinonaktifkan/disembunyikan saat offline) — form
  penuh + validasi server offline berada di luar cakupan Fase 1, sama
  seperti kebijakan definisi Reminder.
- Snapshot daftar jadwal terakhir yang berhasil dimuat di-cache per
  `(userId, childId)` di localStorage
  (`frontend/src/utils/medicationScheduleCache.js`, pola identik
  `reminderCache.js`) — dibersihkan otomatis saat logout dan saat akses
  ke seorang anak dicabut.

## Adherence (formula kepatuhan)

Dihitung `utils/medication_schedule_engine.py:compute_adherence()`
untuk 1 schedule dalam rentang tanggal `[period_start, period_end]`
(inklusif), diagregasi lintas semua schedule anak oleh
`routes/medication_schedule_routes.py:medication_adherence` (endpoint
`GET .../adherence?period=7d|30d`) **dan** oleh
`utils/consultation_report.py:_medication_adherence_summary` (dipakai
laporan Doctor Consultation, lihat bagian di bawah) — **satu fungsi
sumber kebenaran**, dua pemanggil.

| Metrik | Definisi |
|---|---|
| `expected_count` | Okurensi yang JADWALNYA sudah TIBA (`occurrence_at <= now`), jatuh di dalam periode, dan di dalam rentang aktif schedule (`start_date`..`end_date`/hari ini) |
| `administered_count` | Subset expected yang punya `MedicationDoseAction(status='administered')` |
| `skipped_count` | Subset expected yang punya `MedicationDoseAction(status='skipped')` |
| `overdue_unresolved_count` | Subset expected yang BELUM ada aksi sama sekali DAN statusnya `overdue` (`compute_occurrence_state()` yang sama) |
| `on_time_administered_count` | Subset administered dengan `(acted_at - occurrence_at) <= 30 menit` (`DUE_AFTER_MINUTES`, sama ambang due/overdue) |
| `late_administered_count` | Subset administered dengan delta di atas itu |
| `adherence_percentage` | `round(administered_count / expected_count * 100, 1)`, atau **`None`** kalau `expected_count == 0` — **tidak pernah** mengarang persentase dari penyebut kosong |

Penanganan kasus khusus (didokumentasikan eksplisit, sesuai
requirement):

- **Okurensi masa depan** (`occurrence_at > now`) **tidak pernah**
  dihitung `expected` — tidak adil menghukum kepatuhan untuk dosis yang
  belum waktunya.
- **Okurensi yang belum overdue** (masih `due`) dan belum ada aksi:
  tetap masuk `expected_count`, tapi **tidak** masuk
  `overdue_unresolved_count` (belum tentu "terlambat", masih dalam
  jendela wajar).
- **Overdue tanpa aksi**: masuk `expected_count` DAN
  `overdue_unresolved_count`.
- **Skipped**: masuk `expected_count` dan `skipped_count`, **tidak**
  dianggap "gagal kepatuhan" secara terpisah dari administered — cuma
  dikurangi dari pembilang `adherence_percentage` (yang cuma menghitung
  `administered_count`).
- **Regimen mulai di tengah periode**: otomatis tertangani —
  `range_start = max(schedule.start_date, period_start)`, generasi
  okurensi tidak pernah menghasilkan tanggal sebelum `start_date`
  schedule-nya sendiri.
- **Tidak ada dosis yang diharapkan sama sekali** (`expected_count ==
  0`, mis. schedule baru dibuat hari ini jam yang belum tiba, atau
  periode dipilih sebelum `start_date`): SELURUH metrik `0`,
  `adherence_percentage = None` — **tidak pernah** ditampilkan sebagai
  "0%" (0% menyiratkan "gagal total", padahal sebenarnya "belum ada
  yang diharapkan sama sekali").
- **Schedule nonaktif TANPA `end_date` eksplisit**: konservatif
  dianggap `0` ekspektasi sama sekali sejak kapan pun dinonaktifkan
  (kapan persisnya dinonaktifkan tidak direkam, sesuai kebijakan "jangan
  simpan status turunan") — daripada menghukum caregiver untuk dosis
  yang secara teknis "seharusnya" tapi schedule-nya sendiri sudah
  dimatikan. Schedule nonaktif **dengan** `end_date` eksplisit tetap
  dihitung normal sampai `end_date` itu.

## Integrasi Doctor Consultation

Section `medication` yang sudah ada (`utils/consultation_report.py`)
diperluas dengan field baru `adherence_summary` — **hanya** dihitung
dan ditampilkan kalau caregiver secara eksplisit memilih section
`medication` (section sensitif, sama seperti sebelumnya), memakai
`period` konsultasi yang sudah dipilih (7d/14d/30d/custom):

```json
"medication": {
  "entries": [ ... /* MedicationLog, TIDAK BERUBAH dari Phase 1 sebelumnya */ ],
  "total_count_in_period": 3,
  "truncated": false,
  "adherence_summary": {
    "schedule_count": 1,
    "expected_count": 14, "administered_count": 12, "skipped_count": 1,
    "overdue_unresolved_count": 1,
    "on_time_administered_count": 10, "late_administered_count": 2,
    "adherence_percentage": 85.7
  }
}
```

- `adherence_summary` = **`null`** kalau anak ini tidak punya
  `MedicationSchedule` yang overlap periode laporan sama sekali (fitur
  ini belum/tidak dipakai) — bukan dict nol yang bisa disalahartikan
  "kepatuhan 0%".
- **Cuma angka agregat** — tidak pernah nama obat/instruksi
  per-jadwal apa pun (beda dari `entries`, yang memang sudah
  menampilkan `medication_name`/`dosage` sejak Doctor Consultation
  Phase 1 sebelumnya, kebijakan lama yang TIDAK diperluas lebih jauh
  lewat ringkasan baru ini — `instructions` bebas-teks TIDAK PERNAH
  masuk laporan ini sama sekali, prefer excluding).
- Dihitung lewat `build_consultation_report()` yang SAMA PERSIS dipakai
  preview JSON **dan** PDF (`utils/consultation_pdf.py:_render_medication`
  merender blok "Ringkasan Kepatuhan Jadwal Obat" tepat dari data yang
  sama) — mekanisme snapshot immutable preview↔PDF milik Doctor
  Consultation (`activeSnapshot` di `DoctorConsultationScreen.jsx`)
  **tidak diubah sama sekali**, ringkasan ini cuma menumpang di
  section yang sudah ada.

## Audit trail

Terintegrasi ke `utils/audit.py`/`CaregiverAuditEvent` yang sudah ada:

- `create`/`update`/`delete` pada `entity_type="medication_schedule"`.
  `medication_name`/`dose_value`/`dose_unit`/`instructions` ada di
  `PRIVATE_CHANGED_FIELDS` (identitas medis spesifik anak, sama
  kebijakan `medication_log` yang sudah ada) — perubahan field ini cuma
  tercatat sebagai marker generik `private_details`. `start_date`/
  `end_date`/`times_of_day`/`is_active` aman disebut namanya (murni
  jadwal/struktural).
- Menandai dosis memakai 2 entity_type baru yang terpisah —
  `medication_dose_administered` dan `medication_dose_skipped` — pola
  SAMA PERSIS `reminder_occurrence_completed`/`reminder_occurrence_skipped`
  (`action="create"`, `changed_fields` selalu `None`, `entity_id` =
  `MedicationDoseAction.id`, `recorded_at` = `occurrence_at`).
- Menandai `administered` **juga** menghasilkan audit event terpisah
  `entity_type="medication_log"` (`action="create"`) untuk baris
  `MedicationLog` otomatis yang dibuat — memakai kebijakan
  privasi `medication_log` yang **sudah ada**, bukan duplikasi.

## Kontrak API

```
GET    /api/children/<child_id>/medication-schedules
POST   /api/children/<child_id>/medication-schedules
PATCH  /api/children/<child_id>/medication-schedules/<schedule_id>
DELETE /api/children/<child_id>/medication-schedules/<schedule_id>
POST   /api/children/<child_id>/medication-schedules/<schedule_id>/occurrences/<occurrence_key>/administer
POST   /api/children/<child_id>/medication-schedules/<schedule_id>/occurrences/<occurrence_key>/skip
GET    /api/children/<child_id>/medication-schedules/adherence?period=7d|30d
```

`GET .../medication-schedules` balikin:

```json
{
  "child_id": 1, "timezone": "Asia/Jakarta", "server_time": "2026-08-23T10:00:00+07:00",
  "schedules": [
    {
      "id": 5, "child_id": 1, "created_by_user_id": 2, "created_by_name": "Bunda",
      "medication_name": "Amoxicillin", "dose_value": 5.0, "dose_unit": "ml",
      "instructions": "Berikan setelah makan", "start_date": "2026-08-20", "end_date": null,
      "times_of_day": ["08:00", "20:00"], "timezone": "Asia/Jakarta", "is_active": true,
      "created_at": "...", "updated_at": "...",
      "can_edit": true, "can_delete": true, "can_act": true,
      "next_occurrence_at": "2026-08-23T20:00:00+07:00",
      "occurrences": [
        {
          "occurrence_key": "2026-08-23T08:00", "occurrence_at": "2026-08-23T08:00:00+07:00",
          "state": "administered", "status": "administered",
          "acted_at": "...", "acted_by_user_id": 2, "acted_by_name": "Bunda",
          "medication_log_id": 41, "can_act": false
        }
      ]
    }
  ],
  "summary": { "due_count": 0, "overdue_count": 0, "next_upcoming_at": "2026-08-23T20:00:00+07:00" },
  "dose_units": ["ml", "mg", "..."],
  "can_create": true
}
```

`POST create` menerima `{medication_name, dose_value?, dose_unit?,
instructions?, start_date, end_date?, times_of_day}`. `PATCH` menerima
subset field mana pun (partial update, termasuk `is_active` untuk
nonaktifkan/aktifkan). `administer`/`skip` tidak menerima body (dosis
SELALU ditautkan otomatis, tidak ada alur "tautkan log manual" seperti
Reminder).

`GET .../adherence` balikin:

```json
{
  "child_id": 1,
  "period": { "key": "7d", "days": 7, "start_date": "2026-08-17", "end_date": "2026-08-23", "timezone": "Asia/Jakarta" },
  "expected_count": 14, "administered_count": 12, "skipped_count": 1,
  "overdue_unresolved_count": 1, "on_time_administered_count": 10, "late_administered_count": 2,
  "adherence_percentage": 85.7
}
```

Error: `401` belum login, `404` anak/jadwal tidak ada atau tidak bisa
diakses, `403` role tidak punya izin, `400` validasi gagal /
occurrence_key atau periode di luar jangkauan, `409` konflik aksi.

## Privasi

`medication_name`/`instructions` **tidak pernah** dikirim ke audit
trail apa adanya (lihat Audit trail di atas). Ringkasan kepatuhan
(baik di endpoint `/adherence` maupun di section Doctor Consultation)
**cuma angka agregat** — tidak pernah field bebas-teks/identitas
per-jadwal.

Disclaimer keamanan wajib ditampilkan di UI (`MedicationScheduleScreen.jsx`):

> "Jadwal ini hanya mencerminkan instruksi yang dimasukkan sendiri oleh
> caregiver — bukan resep atau saran medis. Selalu ikuti petunjuk
> dokter/apoteker untuk dosis dan jadwal pemberian obat."

## Migrasi database

Dua tabel BARU (`medication_schedules`, `medication_dose_actions`) —
**tidak ada** kolom baru di tabel yang sudah ada, jadi **tidak ada**
entri baru yang perlu ditambahkan ke `COLUMNS_TO_ENSURE`.
`db.create_all()` di `scripts/migrate_production.py` (langkah yang
sudah ada, dipanggil di akhir `migrate()`) otomatis membuat kedua tabel
ini kalau belum ada — persis pola yang sama seperti
`reminders`/`reminder_actions` sebelumnya. Aman dijalankan berkali-kali
(idempoten).

### Deployment PythonAnywhere (Bash console akun production)

```bash
cd ~/baby-daily-tracker
git pull origin main
cd backend
source venv/bin/activate   # kalau pakai virtualenv terpisah
pip install -r requirements.txt
python scripts/migrate_production.py
```

Lalu reload web app dari tab **Web** dashboard PythonAnywhere. **Tidak
ada** langkah scheduled-task/cron yang perlu dikonfigurasi.

### Rollback

Karena migrasi ini cuma menambah 2 tabel baru:

1. `git checkout <commit-sebelumnya>` di server.
2. Reload web app.
3. Tabel `medication_schedules`/`medication_dose_actions` yang sudah
   terlanjur dibuat **boleh dibiarkan** (kode lama tidak pernah
   menyentuhnya) — atau, kalau ingin benar-benar bersih, hapus manual
   lewat SQLite console SETELAH memverifikasi tidak ada data yang masih
   ingin disimpan. **Tidak pernah** menjalankan `DROP TABLE` sebagai
   bagian dari script migrasi otomatis.

## Manual QA checklist

1. Buat jadwal obat 2x/hari (mis. 08:00 & 20:00) sebagai owner — status
   awal `upcoming` untuk kedua jam.
2. Tunggu/ubah waktu sistem sampai masuk jendela `due` — indikator
   berubah tanpa reload manual.
3. Tandai "Sudah diberikan" — status jadi `administered`, verifikasi 1
   `MedicationLog` baru muncul di tab Obat dengan nama/dosis yang benar
   dan waktu = waktu tap (bukan waktu terjadwal).
4. Coba tandai occurrence yang sama lagi — ditolak (konflik), tidak ada
   log dobel.
5. Tandai jam 20:00 sebagai "Lewati" — verifikasi TIDAK ada
   `MedicationLog` baru yang dibuat untuk aksi ini.
6. Biarkan 2-3 hari tanpa dibuka, buka lagi — okurensi yang terlewat
   muncul sebagai `overdue` terpisah per hari per jam.
7. Sebagai editor: buat jadwal sendiri (bisa edit/nonaktifkan), coba
   edit jadwal milik owner (ditolak), tetap bisa tandai dosis jadwal
   milik owner.
8. Sebagai viewer: pastikan semua tombol mutasi disembunyikan, tapi
   ringkasan kepatuhan tetap terlihat; request langsung ke API ditolak
   `403`.
9. Buka Ringkasan Kepatuhan, ganti 7 Hari ⇄ 30 Hari — angka berubah
   sesuai; pastikan tidak pernah tampil "0%" ketika belum ada dosis
   yang diharapkan (harus tampil pesan "belum ada dosis dijadwalkan").
10. Offline: tandai 1 dosis (masuk status "Menunggu sinkron"),
    sambungkan kembali internet, verifikasi tersinkron otomatis tanpa
    `MedicationLog` dobel. Verifikasi tombol buat/ubah jadwal
    disembunyikan saat offline.
11. Siapkan Konsultasi Dokter, pilih section "Obat" dengan periode yang
    mencakup dosis di atas — verifikasi "Ringkasan Kepatuhan Jadwal
    Obat" muncul di preview DAN di PDF yang diunduh, dengan angka yang
    identik. Pilih section lain (bukan "Obat") — pastikan tidak ada
    jejak data jadwal obat sama sekali di laporan.
12. Ganti akun (logout/login akun lain) — verifikasi tidak ada data
    jadwal obat akun sebelumnya yang bocor di cache.

## Keterbatasan Phase 1 yang diketahui

- **Tidak ada alur undo/koreksi** untuk dosis yang sudah ditandai
  administered/skipped — kesalahan tap harus ditangani manual (mis.
  menghapus `MedicationLog` yang salah lewat form obat biasa; baris
  `MedicationDoseAction`-nya sendiri tetap permanen sebagai jejak audit
  "dosis ini pernah ditandai", link `medication_log_id`-nya jadi
  mengarah ke log yang sudah dihapus — bukan dianggap error, sama
  seperti pola record terhapus lainnya di app ini).
- **Membuat/mengubah/menghapus definisi jadwal tetap online-only** —
  belum ada dukungan offline buat operasi CRUD jadwal (cuma
  administer/skip dosis yang bisa offline).
- **Timezone terbatas Asia/Jakarta** — kolom `timezone` di skema sudah
  siap multi-zona, tapi validasi Phase 1 cuma menerima nilai itu.
- **Tidak ada pengingat/notifikasi otomatis** khusus fitur ini di Phase
  1 (beda dari Care Reminders yang punya notifikasi browser
  best-effort) — caregiver perlu membuka layar Jadwal Obat sendiri
  untuk melihat dosis yang jatuh tempo/terlambat. Menambahkan reminder
  terpisah yang menunjuk ke jadwal obat ini adalah kandidat Phase 2.
  Reminder Phase 1 yang sudah ada TETAP bisa dipakai manual sebagai
  workaround (buat reminder `medication` biasa di samping jadwal obat
  ini) — dua fitur ini SENGAJA tidak digabung otomatis di Phase 1.
- **Tidak ada dukungan dosis variabel/titrasi** (mis. "5 ml hari
  pertama, 10 ml mulai hari ketiga") — 1 schedule cuma punya 1 nilai
  dosis tetap sepanjang durasinya; regimen yang dosisnya berubah perlu
  dibuat sebagai 2 schedule terpisah dengan `end_date`/`start_date`
  yang bersambungan.
