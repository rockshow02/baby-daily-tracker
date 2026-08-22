# Caregiver Audit Trail — Phase 1

Jejak audit privacy-minimal: siapa yang **membuat**, **mengubah**, atau
**menghapus** 1 catatan anak, dan (buat update) field APA yang berubah —
TANPA menyimpan salinan kedua dari data medis/personalnya. Bukan
pengganti/duplikat fitur atribusi "dicatat oleh" (`created_by_user_id`/
`created_by_name`) yang sudah ada di tiap log — atribusi itu tetap
menunjuk ke PEMBUAT ASLI record, tidak pernah berubah walau caregiver
lain mengedit record itu belakangan. Audit trail ini justru pelengkapnya:
menjawab "apa yang terjadi belakangan", bukan cuma "siapa yang bikin".

Kode inti: [`backend/models.py`](../models.py) (`CaregiverAuditEvent`),
[`backend/utils/audit.py`](../utils/audit.py) (helper transaksional +
whitelist), [`backend/routes/audit_routes.py`](../routes/audit_routes.py)
(endpoint baca). Test: `backend/tests/test_audit_trail.py`,
`backend/tests/test_audit_trail_api.py`, `backend/tests/test_migrate_production.py`.

## Yang diaudit (Phase 1) vs yang TIDAK

**Diaudit** — 12 tipe log anak yang sudah ada:

1. Catatan menyusui (`feeding_log`)
2. Catatan tidur (`sleep_log`)
3. Catatan popok (`diaper_log`)
4. Catatan perah ASI (`pumping_log`)
5. Catatan aktivitas (`activity_log`)
6. Data pertumbuhan (`growth_measurement`)
7. Kunjungan dokter (`doctor_visit`)
8. Catatan suhu tubuh (`temperature_log`)
9. Catatan sakit (`illness_log`)
10. Catatan pemberian obat (`medication_log`)
11. Catatan mood (`mood_log`)
12. Catatan milestone (`milestone_log`)

**SENGAJA DIKECUALIKAN di Phase 1** (kandidat Phase 2, belum dikerjakan):

- Edit profil anak (nama, tanggal lahir, foto, dst di `Child`)
- Membership/undangan caregiver (`ChildCaregiver`, `ChildInvite`)
- Status vaksinasi (`ChildVaccination`)
- Perubahan profil user (nama, password, dst)
- Konfigurasi Telegram
- Operasi backup/restore
- Aktivitas login/autentikasi

Alasan pengecualian ini: Phase 1 fokus ke jenis catatan yang PALING
sering diedit multi-caregiver (riwayat harian anak) — kategori di atas
punya karakteristik beda (frekuensi rendah, sensitivitas berbeda, atau
sudah punya jejak sendiri lewat mekanisme lain) yang lebih pas dirancang
terpisah, bukan asal ditambahin ke model yang sama.

## Model privasi — apa yang TIDAK PERNAH disimpan

Tabel `caregiver_audit_events` **bukan salinan kedua** dari data
medis/personal. Baris di tabel ini TIDAK PERNAH berisi:

- isi request mentah / body JSON
- nilai sebelum/sesudah (before/after values)
- catatan/teks bebas (`notes`) apa pun
- nama obat atau dosis
- deskripsi/gejala sakit
- suhu, berat, tinggi, volume menyusui, atau ukuran medis lain
- nama anak
- email user
- access token
- idempotency key
- request ID
- teks exception
- URL endpoint

Yang BENERAN disimpan (lihat `CaregiverAuditEvent` di `models.py`):

| Kolom | Isi |
|---|---|
| `id` | ID event ini sendiri |
| `child_id` | anak yang bersangkutan (index) |
| `actor_user_id` | user yang MELAKUKAN aksi ini (index) |
| `action` | `"create"` \| `"update"` \| `"delete"` |
| `entity_type` | salah satu dari 12 tipe di atas (allowlist ketat) |
| `entity_id` | ID record aslinya (bukan FK — record-nya bisa aja udah kehapus) |
| `changed_fields_json` | list NAMA field yang berubah (CUMA action=`update`) |
| `recorded_at` | waktu KEJADIAN ASLI record-nya (mis. `FeedingLog.timestamp`) |
| `created_at` | kapan EVENT AUDIT ini sendiri dicatat (index) |

`changed_fields_json` cuma nama field (mis. `["timestamp", "volume_ml"]`),
**tidak pernah nilainya** — dan cuma boleh berisi nama dari whitelist
ketat per `entity_type` (`utils/audit.py:SAFE_CHANGED_FIELDS`), yang
SENGAJA nggak menyertakan `notes`, nama obat, gejala, atau field ID relasi
lain. Field di luar whitelist yang kebetulan berubah TIDAK PERNAH muncul
di sini — namanya pun tidak disebut.

## Model otorisasi

Akses selalu berdasarkan status caregiver **SAAT INI** (bukan histori):
`GET /api/children/<child_id>/audit-events` memakai
`utils/access.py:get_accessible_child()` — helper akses yang SAMA persis
dipakai semua endpoint anak lain di app ini. Kalau user bukan caregiver
aktif anak itu (nggak pernah jadi caregiver, ATAU pernah tapi udah
dicabut), endpoint balikin `404 {"error": "Anak tidak ditemukan"}` —
pesan generik yang SAMA dipakai endpoint lain, biar user yang nggak
berwenang nggak bisa mbedain "anak ini nggak ada" dari "anak ini ada tapi
kamu nggak punya akses" atau "audit event-nya ada tapi disembunyikan".

**Histori event TETAP kebaca** oleh caregiver yang MASIH aktif, WALAUPUN
event itu dulunya dibuat oleh caregiver yang SEKARANG sudah dicabut
aksesnya — karena `actor_user_id` di baris event nggak pernah dihapus
cuma gara-gara akses caregiver itu dicabut (beda hal: "siapa yang PERNAH
ngelakuin sesuatu" vs "siapa yang SEKARANG punya akses ke anak ini").

**Kalau `actor_user_id` mengarah ke User yang sudah tidak ada** (belum
ada fitur hapus akun di app ini sekarang, tapi didesain buat masa
depan): baris event TETAP ada (bukti historis tetap harus ada), cuma
`actor_name` di respons API balik `null` — bukan error/exception.

## Endpoint baca

```
GET /api/children/<child_id>/audit-events
```

- Wajib login (`401` kalau nggak).
- Wajib caregiver aktif anak itu (`404` kalau nggak, lihat di atas).
- Urut TERBARU dulu (`id DESC` — id monoton naik sesuai urutan dibikin,
  jadi juga otomatis "created_at DESC" secara efektif, TANPA rawan
  ambigu kalau ada 2 event created_at-nya kebetulan identik).
- Paginasi **cursor-based** (bukan OFFSET) — parameter `cursor` = `id`
  event terakhir di halaman sebelumnya, filter `id < cursor`. Ini stabil
  walau ada event baru masuk di antara 2 permintaan halaman (beda dari
  OFFSET yang bisa dobel/kelewat kalau datanya berubah di tengah
  paginasi).
- `limit`: default **25**, maksimal **100**. Nilai di luar rentang atau
  bukan angka → `400`.
- Filter opsional (SEMUA lewat SQLAlchemy query builder — TIDAK PERNAH
  nyusun SQL mentah dari input):
  - `action` — harus salah satu dari `create`/`update`/`delete`, else `400`.
  - `entity_type` — harus salah satu dari 12 tipe allowlist, else `400`.
  - `actor_user_id` — harus integer positif, else `400`.

Contoh respons:

```json
{
  "events": [
    {
      "id": 42,
      "action": "update",
      "entity_type": "feeding_log",
      "entity_id": 17,
      "changed_fields": ["timestamp", "volume_ml"],
      "recorded_at": "2026-01-15T08:00:00+07:00",
      "created_at": "2026-01-15T08:05:12.345Z",
      "actor_user_id": 3,
      "actor_name": "Budi"
    }
  ],
  "next_cursor": 41
}
```

`next_cursor` adalah `null` kalau ini halaman terakhir. **Nggak pernah**
ada `child_id` di tiap event (redundan — udah di URL), email, JSON
mentah, atau detail exception di respons ini.

**Tidak ada endpoint POST/PUT/DELETE buat audit event sama sekali** —
baris `caregiver_audit_events` CUMA pernah dibikin lewat
`utils/audit.py:record_audit_event()`, dipanggil DARI DALAM route
create/update/delete entity-nya sendiri. Mencoba POST/PUT/DELETE/PATCH
ke `/api/children/<id>/audit-events` balik `405 Method Not Allowed`.

## Jaminan transaksional

`record_audit_event()` CUMA `db.session.add(...)` — **tidak pernah**
`db.session.commit()` sendiri. Route yang manggilnya yang commit, di
commit YANG SAMA PERSIS dengan mutasi entity-nya. Ini bikin mutasi
entity dan audit event-nya **atomik**:

- Kalau commit sukses → dua-duanya kesimpen.
- Kalau commit gagal/exception → dua-duanya di-rollback bareng (nggak
  pernah ada mutasi entity kesimpen TANPA audit event-nya, atau
  sebaliknya).

**Sengaja TIDAK** pakai `after_commit`/background thread — event audit
harus PASTI konsisten sama data yang beneran kesimpen, bukan "mungkin
kesimpen belakangan kalau proses background-nya sempat jalan".

### Create via `idempotent_create()`

Endpoint create yang sudah dukung antrian offline (feeding/sleep/diaper/
pumping/activity/medication log) memakai `utils/idempotency.py:idempotent_create()`.
`record_audit_event(action="create", ...)` dipanggil **di dalam**
`build()`, **setelah** `db.session.flush()` (jadi ID entity-nya udah ada).
Konsekuensinya otomatis, tanpa kode tambahan apa pun:

- **Replay** (idempotency key yang sama, request kedua): `build()` sama
  sekali nggak dipanggil (kontrak `idempotent_create()` yang sudah ada) —
  jadi nggak ada audit event kedua.
- **Race/concurrent request** dengan key yang sama: kalau salah satu
  kalah race (kena `IntegrityError` pas commit `IdempotencyKey`),
  **SELURUH transaksi kalah** itu di-rollback — termasuk entity DAN
  audit event yang barusan di-`flush()` di dalam `build()`-nya. Cuma
  pemenang race yang beneran kesimpen, dengan TEPAT 1 entity dan 1
  audit event.

Endpoint create lain (growth/doctor-visit/temperature/illness/mood/
milestone) nggak lewat `idempotent_create()` (nggak didukung antrian
offline) — `record_audit_event()` dipanggil langsung setelah
`db.session.add()` + `db.session.flush()`, sebelum `db.session.commit()`.

### Update

Setiap route update:

1. Ambil snapshot nilai field-field whitelist SEBELUM mutasi
   (`utils/audit.py:snapshot_fields()`) — dibaca langsung dari attribute
   model (bukan dari request).
2. Terapkan mutasi persis seperti sebelumnya (nggak ada logic baru).
3. Ambil snapshot lagi SESUDAH mutasi, bandingkan
   (`diff_snapshots()`) — cuma field yang NILAINYA BENERAN beda yang
   masuk `changed_fields`.
4. Kalau nggak ada yang berubah (`changed_fields` kosong) → **nggak ada
   audit event yang dibikin sama sekali** (no-op update nggak nyampah
   jejak audit).

Dibandingkan ATTRIBUTE MODEL vs ATTRIBUTE MODEL (bukan request JSON
mentah vs nilai DB) — dua-duanya sudah dalam TIPE KOLOM YANG SAMA (mis.
sama-sama `datetime`, bukan `datetime` vs string ISO), jadi nggak ada
risiko keliru mendeteksi "berubah" cuma karena beda representasi
(termasuk `None` vs `None` yang tetap dianggap sama).

`actor_user_id` pada event `update` SELALU user yang login saat
melakukan update itu — **BUKAN** `created_by_user_id` si record (yang
tetap menunjuk pembuat ASLI, tidak pernah berubah).

### Delete

Audit event `delete` dicatat **SEBELUM** `db.session.delete(entity)`
dipanggil (ID dan waktu kejadian entity-nya diambil dulu selagi masih
ada), tapi TETAP dalam commit yang SAMA — jadi tetap atomik dengan
penghapusannya. Cuma `entity_id` dan (kalau ada) `recorded_at` yang
disimpan — nilai medis/personal record yang dihapus TIDAK PERNAH ikut
kesimpen.

## Penghapusan anak (cascade)

`CaregiverAuditEvent.child` memakai `backref` dengan
`cascade="all, delete-orphan"` — **persis pola** yang sudah dipakai
semua log anak lain di `models.py`. Begitu 1 `Child` dihapus permanen
(`DELETE /api/children/<id>`), SEMUA audit event anak itu ikut terhapus
otomatis — konsisten dengan kebijakan hapus-permanen yang sudah ada
untuk semua data anak lainnya, bukan pengecualian baru.

## Tidak ada backfill historis

Migrasi (lihat bagian di bawah) **TIDAK PERNAH** membuat audit event
palsu untuk record yang sudah ada sebelum fitur ini di-deploy. Tabel
`caregiver_audit_events` dibuat **kosong** — histori sebelum fitur ini
ada memang nggak tercatat (itu memang batasan yang disengaja, bukan bug),
dan record lama TIDAK "seolah-olah baru dibuat sekarang" cuma gara-gara
migrasi jalan. Lihat `backend/tests/test_migrate_production.py` buat
bukti eksplisitnya.

## Migrasi

`caregiver_audit_events` adalah **tabel baru** (bukan kolom baru di
tabel lama) — jadi `backend/scripts/migrate_production.py` cukup
mengandalkan `db.create_all()` yang sudah ada di skrip itu (yang
otomatis membuat tabel apa pun yang belum ada, TANPA PERNAH menyentuh
tabel/baris yang sudah ada). Nggak perlu `ALTER TABLE` apa pun untuk
fitur ini.

### Prosedur di PythonAnywhere (staging DULU, baru production)

```bash
cd ~/baby-daily-tracker/backend
source ~/.virtualenvs/babytracker-venv/bin/activate

# 1. WAJIB: backup terverifikasi SEBELUM migrasi apa pun
python scripts/backup_database.py --environment staging
python scripts/backup_database.py --verify <nama-file-backup-yang-baru>

# 2. jalankan migrasi (idempotent — aman dijalankan berkali-kali)
python scripts/migrate_production.py

# 3. verifikasi manual — tabel baru harus muncul di output "Verifikasi akhir"
#    dan baris "OK: tabel 'caregiver_audit_events' ... ada."

# 4. smoke test endpoint baca (read-only, aman)
python scripts/post_deploy_smoke_test.py --base-url https://<staging-domain>/api
```

Ulangi urutan yang sama persis di production SETELAH staging
dikonfirmasi baik-baik saja.

### Rollback

Karena migrasi ini CUMA nambah 1 tabel baru KOSONG (nggak ada `ALTER
TABLE` kolom di tabel lain), rollback aplikasi (kembali ke commit/deploy
sebelumnya) **aman tanpa perlu rollback database** — tabel baru yang
kosong itu nggak dipakai/dibaca kode versi lama, jadi nggak mengganggu
apa pun kalau dibiarkan ada. Kalau operator tetap ingin membuang tabelnya
secara eksplisit (opsional, TIDAK WAJIB):

```bash
# HATI-HATI: cuma jalanin ini kalau BENAR-BENAR yakin, dan SUDAH ada
# backup terverifikasi dari langkah migrasi di atas
sqlite3 ~/baby-daily-tracker/backend/instance/tracker.db "DROP TABLE IF EXISTS caregiver_audit_events;"
```

## Dampak ke verifikasi backup

`backend/scripts/db_backup_common.py:count_tables()` menghitung SEMUA
tabel di file SQLite (`SELECT count(*) FROM sqlite_master WHERE
type='table'`) sebagai proxy ringan "schema version" di metadata backup
— setelah migrasi ini, angka itu akan **naik 1** (tabel baru
`caregiver_audit_events`). Ini **perilaku yang diharapkan**, bukan tanda
korupsi/backup gagal — lihat
[`backend/docs/DATABASE_BACKUP_RESTORE.md`](DATABASE_BACKUP_RESTORE.md)
untuk detail metadata backup.

## Batasan Phase 1

- Kategori yang dikecualikan (lihat di atas) belum diaudit sama sekali —
  Phase 2.
- Nggak ada UI buat "restore ke versi sebelumnya" — audit trail ini
  CUMA histori baca, bukan version control/undo.
- Nggak ada retensi otomatis (audit event nggak pernah dihapus otomatis
  kecuali child-nya dihapus) — kalau suatu saat perlu, itu keputusan
  Phase 2 yang eksplisit, bukan default diam-diam.
- Frontend (lihat bagian UI di README utama/PR description) online-only
  di Phase 1 — nggak ada cache offline buat feed audit ini.
