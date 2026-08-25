# Caregiver Handover Summary — Phase 1

## Tujuan produk

Ringkasan **operasional** buat caregiver yang baru mengambil alih
penjagaan bayi: apa yang terjadi 24 jam terakhir, catatan terbaru yang
penting, item obat/pengingat yang butuh perhatian, catatan serah-terima
opsional dari yang membuat, dan siapa saja caregiver yang sudah membaca
(acknowledge) ringkasan ini.

**BUKAN**:
- laporan tren statistik (itu Smart Insights, `utils/insights_engine.py`),
- laporan konsultasi dokter (itu Doctor Consultation, periode fleksibel
  7-90 hari, dibawa KELUAR aplikasi),
- diagnosis, saran pengobatan, atau rekomendasi penanganan darurat.

## Beda dari fitur lain

| | Smart Insights | Doctor Consultation | Caregiver Handover (fitur ini) |
|---|---|---|---|
| Periode | Kalender WIB (mingguan) | Fleksibel 7-90 hari, dipilih manual | TEPAT 24 jam bergulir, dibekukan saat dibuat |
| Tujuan | Tren/perbandingan periode | Bahan dibawa ke dokter | Konteks operasional buat caregiver PENGGANTI |
| Disimpan? | Tidak, dihitung ulang tiap request | Tidak, dihitung ulang tiap request | **Ya** — 1 baris `caregiver_handovers` per handover (metadata + jendela beku), ringkasannya sendiri TETAP dihitung ulang tiap dibaca |
| Snapshot/token | — | Ya (token bertanda tangan preview→PDF) | **Tidak** — sudah persisten di DB, bukan dokumen transient sekali-render |

## Environment: PythonAnywhere Free

Tidak ada Celery/Redis/scheduled task/background worker/WebSocket/queue
eksternal. Ringkasan **selalu** dihitung sinkron per-request dari tabel
sumber yang sudah ada (`utils/caregiver_handover_summary.py`), sama
prinsipnya seperti Reminders/Medication Schedule/Insights.

## Skema data

Skema paling kecil yang mungkin — **tidak menyalin ulang** feeding/sleep/
health log ke tabel handover, ringkasan dihitung ulang dari tabel sumber
tiap kali dibaca.

### `caregiver_handovers`

| Kolom | Tipe | Keterangan |
|---|---|---|
| `id` | PK | |
| `child_id` | FK → `children.id` | |
| `created_by_user_id` | FK → `users.id` | |
| `window_start` | DateTime | `as_of_at - 24 jam`, dibekukan saat dibuat |
| `as_of_at` | DateTime | sampel `now_wib()` TUNGGAL saat dibuat, dibekukan |
| `note` | Text, nullable | catatan serah-terima opsional, max 1000 karakter |
| `status` | String, CHECK `IN ('open','closed')` | |
| `created_at`/`updated_at`/`closed_at` | DateTime | |
| `closed_by_user_id` | FK → `users.id`, nullable | |

**Constraint kunci**: partial unique index
`(child_id) WHERE status='open'` — menegakkan "1 handover terbuka per
anak" **di database**, bukan cuma query cek-dulu di aplikasi (yang rentan
race 2 request bersamaan). Diverifikasi lewat
`tests/test_migrate_production.py` dan `tests/test_caregiver_handover.py`
(termasuk test konkurensi thread asli).

### `caregiver_handover_acknowledgements`

| Kolom | Tipe | Keterangan |
|---|---|---|
| `id` | PK | |
| `handover_id` | FK → `caregiver_handovers.id`, index | |
| `user_id` | FK → `users.id`, index | |
| `acknowledged_at` | DateTime | sampel `now_wib()` TUNGGAL per request acknowledge |

**Constraint kunci**: `UniqueConstraint(handover_id, user_id)` —
menegakkan idempotensi acknowledge di database.

### Cascade

`Child` → `CaregiverHandover` (`cascade="all, delete-orphan"`) →
`CaregiverHandoverAcknowledgement` (`cascade="all, delete-orphan"`):
menghapus anak otomatis membersihkan handover dan semua acknowledgement-
nya, tidak ada baris yatim yang tersisa. Tidak ada fitur hapus akun user
di app ini (`ChildCaregiver` — bukan `User` — yang dihapus saat caregiver
dicabut aksesnya), jadi `created_by_user_id`/`closed_by_user_id`/`user_id`
pakai FK biasa (tanpa `ondelete` khusus), konsisten `Reminder`/
`MedicationSchedule`.

## Jendela 24 jam beku

`now_wib()` disampel **tepat sekali** saat `POST .../caregiver-handover`
dipanggil. `as_of_at` = nilai itu, `window_start` = `as_of_at - 24 jam`.
Ringkasan (`utils/caregiver_handover_summary.py`) **selalu** memakai
rentang ini — waktu wall-clock belakangan **tidak pernah** menggeser
jendela handover yang sudah ada. Ringkasan boleh dihitung ULANG dari
tabel sumber tiap kali GET dipanggil (bukan snapshot statis), tapi
batas `window_start`/`as_of_at`-nya tetap beku.

**Keterbatasan Phase 1 yang didokumentasikan secara eksplisit**: kalau
sebuah catatan sumber (mis. feeding log) diedit/dihapus SETELAH handover
dibuat, ringkasan yang dibaca ULANG akan mencerminkan versi TERBARU
record itu, bukan versi saat handover dibuat — ini **bukan** snapshot
immutable. Tidak ada mekanisme `source_data_updated_at`/peringatan di
Phase 1 (menambahkannya butuh melacak versi tiap tipe record sumber,
kompleksitas yang tidak sepadan untuk fitur yang jendelanya cuma 24 jam
dan dimaksudkan dibaca-lalu-ditutup dalam waktu singkat).

## Ringkasan (`utils/caregiver_handover_summary.py`)

Modul murni: `build_caregiver_handover_summary(child, handover,
generated_at)` — **tidak pernah** memanggil jam sistem sendiri,
`window_start`/`as_of_at` dibaca dari baris `handover`, `generated_at`
selalu parameter dari pemanggil.

| Section | Isi | Sumber |
|---|---|---|
| `feeding`/`pumping` | jumlah event, event terbaru, total volume terukur (kebijakan konservatif) | Query langsung `[window_start, as_of_at]` |
| `sleep` | jumlah event, sesi terbaru (termasuk status masih-berlangsung), total menit SELESAI | idem |
| `diaper` | jumlah event, jenis terbaru, hitung basah/kotor/keduanya | idem |
| `activity_mood` | jumlah + terbaru aktivitas & mood | idem |
| `health` | suhu terbaru **DI DALAM JENDELA** (bukan "terbaru sepanjang waktu"), penyakit yang overlap jendela (CUMA tanggal mulai/selesai/status berlangsung), kunjungan dokter terbaru (CUMA tanggal + alasan) | idem |
| `medication` | dosis administered/skipped di jendela, overdue per `as_of_at`, next occurrence setelah `as_of_at` | **REUSE PENUH** `utils/medication_schedule_engine.py` |
| `reminders` | okurensi resolved di jendela, overdue per `as_of_at`, next occurrence | **REUSE PENUH** `utils/reminder_engine.py` |

### Kebijakan kelengkapan nilai terukur

Total volume (feeding/pumping) memakai
`utils.insights_engine._measured_total_or_none` yang **sama persis**
dipakai Smart Insights — 1 sumber kebenaran "kapan total boleh
dipercaya": `0` event → total `0` (valid), SEMUA event terukur → total
apa adanya, SEBAGIAN terukur → `None` (bukan total parsial yang
menyesatkan). Data yang hilang **selalu** eksplisit `null`/list kosong/
teks manusiawi — **tidak pernah** dikarang jadi nol.

### Medikasi & pengingat — horizon tanpa scheduler baru

`_medication_section`/`_reminder_section` **tidak pernah** menghitung
ulang logika status/okurensi sendiri — keduanya memanggil mesin yang
sudah ada dengan `today`/`now` = `as_of_at` (BEKU). Konsekuensi yang
didokumentasikan (BUKAN bug): `compute_schedule_occurrences` dibatasi
sampai `as_of_at.date()` saja (lihat `_schedule_range_end_date` di
`medication_schedule_engine.py`), jadi "next occurrence" di ringkasan
handover CUMA bisa ketemu kalau masih ada jam pemberian tersisa **hari
yang sama** yang belum di-resolve — tidak pernah okurensi besok/lusa.
Ini keterbatasan Phase 1 yang sengaja diterima demi tidak menulis logic
horizon baru/scheduler tambahan.

### Data yang TIDAK PERNAH muncul di ringkasan

Catatan bebas-teks apa pun (`notes` di 12+ tipe log), instruksi obat,
catatan dokter privat, `illness_name` (nama penyakit spesifik, hanya
tanggal mulai/selesai yang muncul), nama dokter/klinik/diagnosis, label
kustom milestone, detail audit, request ID, token otentikasi, ID
database mentah di UI, dump historis lengkap.

## Roles & Capabilities

| Aksi | Owner | Editor | Viewer |
|---|---|---|---|
| Lihat handover terbuka + ringkasan | ✅ | ✅ | ✅ |
| Buat handover baru | ✅ | ✅ | ❌ |
| Edit catatan handover MANA PUN | ✅ | ❌ (cuma miliknya sendiri) | ❌ |
| Tutup handover MANA PUN | ✅ | ❌ (cuma miliknya sendiri) | ❌ |
| Acknowledge (tandai sudah baca) | ✅ | ✅ | ✅ |

Owner **selalu** `Child.user_id` (tidak pernah baris `ChildCaregiver`
terpisah, konsisten seluruh app). Kapabilitas (`can_view`/`can_create`/
`can_edit`/`can_close`/`can_acknowledge`) **selalu dihitung backend**,
dikirim di tiap respons `GET`/`POST`/`PUT` — frontend **tidak pernah**
dipercaya soal peran sendiri, dan role/status di-cek ULANG di SETIAP
request (bukan cuma saat handover dibuat). Caregiver yang aksesnya
dicabut (`ChildCaregiver` dihapus) langsung dapat `404` yang SAMA PERSIS
kayak handover yang beneran tidak ada — keberadaan handover anak lain
tidak pernah bisa disimpulkan dari luar.

## API Contract

Semua endpoint butuh login (`Authorization: Bearer <token>`), body
JSON via POST/PUT saja (**tidak pernah** query string).

### `GET /api/children/<child_id>/caregiver-handover`

Tidak ada handover terbuka:
```json
{"handover": null, "summary": null, "acknowledgements": [], "capabilities": {"can_view": true, "can_create": true, "can_edit": false, "can_close": false, "can_acknowledge": false}}
```

Ada handover terbuka: `handover` (metadata), `summary` (dihitung ulang
tiap request), `acknowledgements` (list `{id, user_id, display_name,
acknowledged_at}`), `capabilities`.

### `POST /api/children/<child_id>/caregiver-handover`

Body: `{"note": "..."}` (opsional). `201` + payload sama seperti GET.
`409` kalau sudah ada handover terbuka untuk anak ini (race unique
index ditangkap eksplisit, **tidak pernah** 500/error mentah).

### `PUT /api/caregiver-handovers/<handover_id>`

Body: `{"note": "..."}`. `403` kalau bukan Owner/pembuat-Editor. `400`
kalau handover sudah `closed` (update atomik bersyarat
`WHERE status='open'`, race-safe). No-op (nilai sama) **tidak**
menghasilkan baris audit.

### `POST /api/caregiver-handovers/<handover_id>/acknowledge`

Body kosong atau objek kecil. Idempoten per user — percobaan ulang
balikin `{"acknowledgement": {...}, "created": false}` (200), sukses
pertama `{"acknowledgement": {...}, "created": true}` (201). **Sengaja
tidak** mensyaratkan status `open` — caregiver tetap boleh mengakui
handover yang baru saja ditutup.

### `POST /api/caregiver-handovers/<handover_id>/close`

Idempoten — panggilan kedua & seterusnya tetap `200` (bukan error),
cuma request PERTAMA yang benar-benar menutup yang menghasilkan baris
audit. Handover baru boleh dibuat setelah ini.

**Tidak ada endpoint delete** di Phase 1 — semantik close/archive sudah
cukup, tidak ada kebutuhan konkret buat penghapusan permanen.

## Makna acknowledgement

Acknowledge **HANYA** berarti "caregiver ini sudah membuka/membaca
handover ini" — **BUKAN** persetujuan atas keakuratan medis, **BUKAN**
penerimaan tanggung jawab, **BUKAN** konfirmasi semua tugas selesai.
Ditampilkan hanya nama tampilan + waktu — **tidak pernah** email/nomor
telepon/token/ID user internal.

## Konkurensi

Ditegakkan lewat constraint database + update atomik bersyarat, bukan
cek-lalu-tulis di memori:

- **2 create bersamaan, anak sama** → partial unique index menolak yang
  kalah dengan `IntegrityError` → `409` (dibuktikan test thread asli,
  `tests/test_caregiver_handover.py::test_concurrent_creates_yield_exactly_one_open_handover`).
- **2 acknowledge bersamaan, user sama** → `UniqueConstraint` +
  `IntegrityError` ditangkap, dikembalikan `created: false` (bukan
  error).
- **Close vs acknowledge bersamaan** → deterministik by design: keduanya
  independen (acknowledge tidak mensyaratkan status), tidak bisa saling
  menggagalkan.
- **Edit/close handover yang sudah closed** → `updated_rows == 0` dari
  `UPDATE ... WHERE status='open'` → `400`/idempoten `200`, tidak pernah
  mutasi parsial.
- **Close kedua/ketiga kalinya** → selalu `200`, tidak pernah `500`,
  tepat 1 baris audit tercatat terlepas berapa kali dipanggil.

## Privasi & Offline

Catatan (`note`) dinormalisasi CRLF→LF, di-trim, maks 1000 karakter,
selalu di-escape sesuai prinsip HTML/PDF-safe saat dirender (belum ada
PDF di Phase 1, tapi prinsipnya tetap berlaku), **tidak pernah** masuk
log/audit/exception/URL/notifikasi. Body-size limit ketat per endpoint
(`MAX_HANDOVER_BODY_BYTES=4000` create/update, `MAX_SMALL_BODY_BYTES=200`
acknowledge/close), dicek dari `request.stream` langsung (bukan cuma
`Content-Length`, yang bisa dipalsukan/hilang).

**Phase 1 online-only** — frontend **tidak pernah** menyimpan data
handover di localStorage/IndexedDB/sessionStorage/service-worker cache,
**tidak pernah** menambahkan create/update/acknowledge/close ke antrean
offline. Pesan offline:
`"Butuh koneksi internet untuk membuka atau memperbarui Serah Terima Pengasuh."`

## Audit trail

Entity type `caregiver_handover` (create/update, `changed_fields` selalu
`private_details` marker untuk `note` — tidak pernah nama field
`note` disebut apa adanya, karena isinya bebas-teks). 2 entity type
event-only terpisah (`caregiver_handover_closed`,
`caregiver_handover_acknowledged`) — `action` selalu `create`,
`changed_fields` selalu `None`. **Tidak pernah** menyimpan isi ringkasan
atau isi `note` di baris audit mana pun. No-op update dan acknowledge
retry (sudah pernah) **tidak** menghasilkan baris audit baru.

## Backup & Import

**Dikecualikan total** dari `export_json`/`import_json`, konsisten
kebijakan yang sudah ada untuk Reminders/MedicationSchedule (juga tidak
pernah diekspor). Alasan: (1) kebijakan peran backup per-CHILD (semua
peran bisa backup), berbeda dari kebijakan per-record handover (Editor
cuma boleh miliknya sendiri) — menyalin `note` mentah ke backup akan
melewati kontrol kepemilikan itu; (2) handover adalah state operasional
sementara (1 baris terbuka, jendela 24 jam, dimaksudkan dibaca-lalu-
ditutup), bukan riwayat medis permanen yang jadi tujuan fitur
backup/restore. Backup lama (sebelum fitur ini ada) tetap
importable apa adanya — tidak ada field baru yang jadi wajib.

## Migrasi

2 tabel baru — **tidak ada** entri `COLUMNS_TO_ENSURE` (bukan kolom baru
di tabel lama), `db.create_all()` di akhir `migrate()` sudah cukup,
termasuk partial unique index-nya (SQLite mendukung
`CREATE UNIQUE INDEX ... WHERE status = 'open'` apa adanya lewat
`db.create_all()`, tidak perlu DDL manual). Aman dijalankan berulang
(idempotent), tidak pernah menyentuh baris yang sudah ada di tabel lain.

## PythonAnywhere Free compatibility

Tidak ada proses baru, thread background, WebSocket, atau dependency
eksternal apa pun — 100% request/response sinkron di atas Flask + SQLite
yang sudah ada.

## Keterbatasan Phase 1

- Bukan snapshot immutable — record sumber yang diedit/dihapus setelah
  handover dibuat langsung tercermin di ringkasan berikutnya (lihat
  "Jendela 24 jam beku" di atas).
- "Next occurrence" medikasi/pengingat cuma menjangkau sisa hari yang
  sama dengan `as_of_at` (keterbatasan mesin yang di-reuse).
- Tidak ada PDF, link publik, QR, push notification, atau layar riwayat
  handover — semuanya di luar cakupan Phase 1.
- Tidak ada endpoint delete permanen.
