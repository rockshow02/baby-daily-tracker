# Caregiver Roles & Permissions — Phase 1

Tiga peran caregiver: **owner**, **editor**, **viewer**. Otorisasi backend
**otoritatif** — frontend cuma boleh sembunyikan/nonaktifkan kontrol yang
nggak relevan buat pengalaman pakai, TIDAK PERNAH satu-satunya lapisan
penegakan izin.

Kode inti: [`backend/utils/access.py`](../utils/access.py) (resolusi
peran + helper otorisasi terpusat), [`backend/models.py`](../models.py)
(`ChildCaregiver`, `ChildInvite`), route di
[`backend/routes/children_routes.py`](../routes/children_routes.py)
(kelola caregiver) dan 12 tipe record (`daily_log_routes.py`,
`extra_log_routes.py`, `growth_routes.py`, `health_routes.py`,
`mood_milestone_routes.py`). Test:
`backend/tests/test_roles_permissions.py`,
`backend/tests/test_migrate_production.py`.

## Model peran & kepemilikan

- **owner** — SATU-SATUNYA sumber kebenarannya `Child.user_id` (pembuat
  anak). **TIDAK PERNAH** direpresentasikan sebagai baris
  `child_caregivers` — nggak ada baris duplikat "role=owner" yang perlu
  disinkronkan dengan `Child.user_id` (1 sumber kebenaran, bukan 2 yang
  bisa kontradiksi). `utils/access.py:resolve_role()` SELALU cek
  `Child.user_id` DULUAN sebelum nengok tabel `child_caregivers` sama
  sekali.
- **editor** — baris `child_caregivers.role == 'editor'`. Boleh baca,
  bikin, ubah record apa pun, hapus record BUATAN SENDIRI.
- **viewer** — baris `child_caregivers.role == 'viewer'`. Boleh baca
  doang, TIDAK PERNAH boleh bikin/ubah/hapus apa pun.

`child_caregivers.role` dan `child_invites.role` **CUMA boleh** `'editor'`
atau `'viewer'` — ditegakkan CHECK constraint di database (SQLite,
bukan cuma validasi Python), jadi bahkan kalau ada bug di endpoint yang
kelewat validasi, database sendiri tetap menolak nilai `'owner'` atau
apa pun di luar 2 itu.

Transfer kepemilikan (ubah `Child.user_id` ke user lain) **DI LUAR
CAKUPAN Phase 1** — nggak ada endpoint buat itu sama sekali.

## Matriks izin

| Operasi | Owner | Editor | Viewer |
|---|:---:|:---:|:---:|
| Lihat profil anak | Ya | Ya | Ya |
| Lihat catatan harian/kesehatan/pertumbuhan | Ya | Ya | Ya |
| Lihat laporan & audit trail | Ya | Ya | Ya |
| Bikin catatan (12 tipe) | Ya | Ya | Tidak |
| Ubah catatan (12 tipe) | Ya | Ya | Tidak |
| Hapus catatan BUATAN SENDIRI | Ya | Ya | Tidak |
| Hapus catatan buatan orang lain | Ya | Tidak | Tidak |
| Undang caregiver | Ya | Tidak | Tidak |
| Ubah peran caregiver | Ya | Tidak | Tidak |
| Cabut akses caregiver | Ya | Tidak | Tidak |
| Ubah profil anak (nama/foto/dst) | Ya | Tidak | Tidak |
| Hapus anak | Ya | Tidak | Tidak |
| Transfer kepemilikan | Di luar cakupan | Di luar cakupan | Di luar cakupan |

"Catatan buatan sendiri" = `created_by_user_id` record itu SAMA PERSIS
dengan user yang login. Kalau `created_by_user_id`-nya `NULL` (record
legacy dari sebelum fitur atribusi ada), **cuma owner** yang bisa
menghapusnya — editor otomatis gagal (`None == user_id` selalu `False`),
BUKAN pengecualian khusus yang perlu di-kode terpisah.

## Otorisasi terpusat (`utils/access.py`)

Satu tempat "siapa boleh apa" — route TIDAK PERNAH bandingin string role
sendiri-sendiri, cuma manggil:

- `resolve_role(child, user_id)` — `'owner' | 'editor' | 'viewer' | None`.
- `get_accessible_child(child_id, user_id)` / `get_accessible_children(user_id)`
  — akses baca (owner ATAU caregiver terdaftar).
- `require_read_access(child_id, user_id)` — `(child, role)` kalau boleh
  baca.
- `require_write_access(child_id, user_id)` — `(child, role)` kalau
  boleh create/update (`role` di `WRITE_ROLES = (owner, editor)`).
- `require_owner_access(child_id, user_id)` — `(child, role)` kalau
  ADALAH pemilik.
- `can_delete_record(role, created_by_user_id, user_id)` — `bool`,
  kebijakan hapus di atas.

Role **TIDAK PERNAH** dipercaya dari body/header/query-string request
klien manapun — SELALU hasil query database segar per-request (nggak
ada cache role di server, jadi demosi/pencabutan langsung berlaku di
request BERIKUTNYA, termasuk replay antrian offline — lihat di bawah).

### Kode status

- `401` — belum login / sesi nggak valid.
- `403` — user dikenal, tapi role-nya nggak izinin aksi ini (viewer
  nyoba nulis, editor nyoba hapus punya orang, non-owner nyoba kelola
  caregiver/anak).
- `404` — konsisten sama pola yang UDAH ADA sebelum Phase 1 ini: dipakai
  di endpoint BACA (`GET /children/<id>`, list record, dst) buat anak
  yang nggak ada ATAU nggak bisa diakses SAMA SEKALI, biar user yang
  nggak berwenang nggak bisa mbedain "anak ini nggak ada" dari "ada tapi
  kamu nggak boleh lihat". Endpoint MUTASI record (`PUT`/`DELETE`
  `/feeding-logs/<id>` dkk) sudah lama pakai `403` buat kasus "nggak ada
  akses ke anak ini sama sekali" (pola pra-Phase-1 yang dipertahankan) —
  Phase 1 nambah 403 BARU di atasnya buat "ada akses baca, tapi role-nya
  nggak cukup".

## Migrasi database

`scripts/migrate_production.py` (idempotent, aman rerun) nambah 2
langkah SEBELUM `db.create_all()`:

1. **`child_invites.role`** (kolom baru) — `ALTER TABLE ... ADD COLUMN
   role VARCHAR(15) NOT NULL DEFAULT 'editor'` lewat mekanisme
   `COLUMNS_TO_ENSURE` yang udah ada. Undangan LAMA (dibikin sebelum
   kolom ini ada) otomatis dapet `'editor'` — PERSIS perilaku lama
   (caregiver yang gabung lewat undangan lama selalu bisa
   create/update/delete).
2. **`child_caregivers`** (bangun ulang tabel — SQLite nggak bisa `ALTER
   TABLE` nambah CHECK constraint ke tabel yang udah ada) —
   `_migrate_child_caregiver_roles()`:
   - Baris `role='owner'` **DIBUANG** (redundan — pemiliknya udah jelas
     dari `Child.user_id`).
   - Baris `role='caregiver'` **diubah jadi `'editor'`**.
   - CHECK constraint `role IN ('editor','viewer')` ditegakkan di skema
     barunya.
   - Data lain (child_id, user_id, created_at) disalin APA ADANYA, TIDAK
     ADA baris yang hilang selain baris 'owner' yang memang redundan.

Idempoten lewat deteksi `sqlite_master.sql` mentah (ada substring
`CHECK` atau nggak) — kalau udah termigrasi, skip total.

**Fresh database** (`db.create_all()` dari model terbaru, tanpa tabel
lama sama sekali) langsung dapet skema yang benar (CHECK constraint +
kolom `role`) TANPA butuh langkah migrasi tambahan — dites eksplisit di
`test_fresh_and_migrated_schemas_have_the_same_effective_child_caregivers_shape`.

### Prosedur PythonAnywhere (staging DULU, baru production)

```bash
cd ~/baby-daily-tracker/backend
source ~/.virtualenvs/babytracker-venv/bin/activate

# 1. WAJIB: backup terverifikasi SEBELUM migrasi apa pun
python scripts/backup_database.py --environment staging
python scripts/backup_database.py --verify <nama-file-backup-yang-baru>

# 2. jalankan migrasi (idempotent — aman dijalankan berkali-kali)
python scripts/migrate_production.py

# 3. verifikasi manual — output harus nunjukin baris "'child_caregivers'
#    dibangun ulang — baris 'owner' dibuang, 'caregiver' jadi 'editor',
#    CHECK constraint aktif." (atau "dilewatin" kalau udah pernah jalan)

# 4. smoke test endpoint baca (read-only, aman)
python scripts/post_deploy_smoke_test.py --base-url https://<staging-domain>/api
```

Ulangi urutan yang sama persis di production SETELAH staging
dikonfirmasi baik-baik saja.

### Rollback

Migrasi `child_invites.role` cuma nambah kolom (aditif, aman dibiarkan
kalau rollback aplikasi). Migrasi `child_caregivers` **membuang baris
`role='owner'`** — kalau operator butuh rollback KODE APLIKASI ke versi
SEBELUM Phase 1 ini (yang masih baca `role='owner'` dari tabel ini buat
nentuin pemilik), baris itu udah nggak ada lagi, jadi versi lama bakal
salah nganggep pemilik anak "bukan caregiver anak ini sama sekali".
**Rekomendasi**: kalau perlu rollback kode ke sebelum Phase 1, pulihkan
dari backup terverifikasi SEBELUM migrasi ini dijalankan (langkah 1 di
atas) — jangan cuma rollback kode di atas database yang udah termigrasi.

## Perilaku undangan

1. Owner **wajib** milih `role` (`'editor'` atau `'viewer'`) pas bikin
   undangan (`POST /children/<id>/invite`) — endpoint ini sekarang
   **owner-only** (sebelumnya semua caregiver boleh bikin undangan;
   Phase 1 mengubahnya jadi keputusan pemilik, konsisten sama kelola
   caregiver lainnya).
2. Backend validasi `role` lewat allowlist ketat (`MEMBERSHIP_ROLES`) —
   nilai lain (termasuk `'owner'`) ditolak `400`.
3. `POST /children/join` menerapkan `invite.role` APA ADANYA ke baris
   `ChildCaregiver` baru — **user yang nerima TIDAK PERNAH bisa milih
   perannya sendiri** (endpoint ini nggak baca field `role` dari body
   request sama sekali, biar pun dikirim).
4. Undangan kedaluwarsa/udah dipakai/kode salah tetap pakai respons aman
   yang sudah ada (`400`/`404` generik, nggak bocorin detail).
5. Ganti peran SETELAH caregiver gabung **TIDAK PERNAH** mengubah
   `created_by_user_id` record-record lama yang udah dibuat caregiver
   itu — atribusi historis "siapa yang bikin" tetap seperti aslinya,
   terpisah total dari peran AKTIF-nya sekarang.

## API kelola caregiver (owner-only)

- `GET /children/<id>/caregivers` — daftar caregiver + peran (owner
  disintesis dari `Child.user_id`, digabung sama baris
  `child_caregivers`). Semua role bisa baca ini (bukan cuma owner).
- `PUT /children/<id>/caregivers/<user_id>` — ubah peran editor<->viewer.
  Owner-only. Menolak: menetapkan `'owner'`, mengubah non-member,
  membership anak LAIN (IDOR — query difilter `child_id` + `user_id`
  sekaligus), owner ubah perannya sendiri (`400`, dia nggak punya baris
  di tabel ini).
- `DELETE /children/<id>/caregivers/<user_id>` — cabut akses. Owner-only,
  owner nggak bisa cabut dirinya sendiri.

Respons endpoint di atas **TIDAK PERNAH** menambahkan field baru yang
bocorin data privat di luar yang sudah ada sebelumnya (`user_id`, nama,
email, role) — email TETAP ada di respons (fitur existing, dipakai owner
buat kenalin siapa caregivernya), tapi endpoint BARU (ubah peran/cabut)
cuma balikin field minimal yang perlu.

## Integrasi Audit Trail

3 kejadian keamanan membership diaudit lewat perluasan MINIMAL &
KOMPATIBEL ke skema Caregiver Audit Trail yang sudah ada (lihat
[`AUDIT_TRAIL.md`](AUDIT_TRAIL.md)):

- `entity_type = "caregiver_membership"` — TERPISAH dari 12 tipe record
  (biar nggak nyampur makna "record medis anak" vs "kejadian keamanan
  siapa yang boleh akses").
- REUSE 3 `action` yang UDAH ADA (nggak nambah action baru): `create` =
  caregiver diundang, `update` = peran diubah, `delete` = akses dicabut.
- `entity_id` = `ChildInvite.id` (diundang) atau `ChildCaregiver.id`
  (diubah/dicabut) — persis pola "id record aslinya" di 12 tipe lain.
- `changed_fields` **SELALU** `null`/kosong buat ketiganya — kode undangan,
  email, dan nilai peran lama/baru **TIDAK PERNAH** tersimpan di audit
  trail sama sekali, cuma metadata "APA yang kejadian, SIAPA pelakunya,
  KAPAN".

Mutasi membership (invite/ubah peran/cabut) dan audit event-nya berbagi
transaksi database yang SAMA (lewat `record_audit_event()` yang sudah
ada) — mutasi gagal berarti nggak ada audit event, dan sebaliknya.
No-op (role diubah ke nilai yang SAMA) nggak menghasilkan audit event
sama sekali, konsisten sama kebijakan update record biasa.

## Antrian offline & pencabutan/penurunan peran

**Kritis**: user bisa antre catatan pas offline, lalu kehilangan akses
tulis SEBELUM sempat online lagi (didemosi ke viewer, atau dicabut
total). Kebijakannya:

- **Setiap** mutasi yang di-replay dari antrian offline (`useOfflineSync.js`)
  di-otorisasi ULANG oleh backend PERSIS sama seperti request baru —
  role SELALU dibaca segar dari database per-request, TIDAK PERNAH
  dipercaya dari cache/state frontend.
- Otorisasi yang gagal (403) **TIDAK PERNAH** memutasi data ataupun
  bikin audit event — pengecekan role terjadi SEBELUM baris apa pun
  di-`add()`/di-`delete()`.
- Frontend (`useOfflineSync.js`, sudah ada dari fitur antrian offline
  sebelumnya) membedakan `401` (sesi abis — stop total, tunggu login
  ulang) dari `403` (kemungkinan peran berubah/akses dicabut — item
  ditandai `needs_review` dengan alasan `access_revoked`, TIDAK
  di-retry otomatis, lanjut ke item berikutnya). Item yang ditolak tetap
  kesimpen (bukan dihapus diam-diam) buat ditinjau manual lewat Sync
  Center (`QueueReviewPanel.jsx`) — pesannya menjelaskan kemungkinan
  akses/peran berubah.
- Begitu koneksi balik, `App.jsx` otomatis muat ulang daftar anak dari
  server (`loadChildren()`, dipicu event `online`) — anak yang udah
  nggak bisa diakses lagi otomatis HILANG dari state UI aktif DAN cache
  lokal (`cacheChildren()` nge-overwrite cache lama dengan daftar
  terbaru), TANPA pernah menghapus item antrian yang ditolak secara diam
  -diam (tetap ada di Sync Center buat ditinjau user).
- Replay dengan idempotency key yang SAMA setelah demosi/pencabutan
  ditolak backend (bukan diam-diam dianggap sukses via mekanisme
  idempotency) — dites eksplisit di
  `test_queued_idempotent_replay_is_reauthorized_after_demotion`.

## Respons API — role efektif

`Child.to_dict()` + field `role` (peran EFEKTIF user yang login,
disuntik di layer route lewat `_child_dict_with_role()`, BUKAN di model)
dikembalikan di SEMUA respons child-scoped yang sudah dipakai frontend
(`GET /children`, `GET /children/<id>`, `POST /children`, `PUT
/children/<id>`, `POST /children/join`) — frontend nggak pernah perlu
ngitung ulang role sendiri dari data lain.

Cache offline (`sessionCache.js`) ikut nyimpen field `role` ini. Objek
anak lama yang di-cache SEBELUM field ini ada (nggak punya `role` sama
sekali) di-fallback ke **read-only** di UI sampai backend
mengonfirmasi ulang lewat request online berikutnya — TIDAK PERNAH
diasumsikan `owner`/`editor` cuma karena field-nya nggak ada.

## Batasan Phase 1

- Transfer kepemilikan anak — di luar cakupan, nggak ada endpoint sama
  sekali.
- Nggak ada peran custom/granular per fitur (mis. "boleh lihat kesehatan
  tapi nggak boleh lihat pertumbuhan") — cuma 3 peran flat.
- Operasi kelola caregiver (undang/ubah peran/cabut) SENGAJA TIDAK
  didukung offline — selalu butuh koneksi (owner-only, jarang dipakai,
  dan konsekuensi keamanannya lebih tinggi kalau di-antrikan offline).
- Rollback kode ke sebelum Phase 1 di atas database yang udah termigrasi
  butuh restore dari backup (lihat bagian Migrasi di atas) — bukan
  operasi yang aman dilakukan langsung.

## Checklist QA manual

- [ ] Owner bikin anak -> `GET /children/<id>` balikin `role: "owner"`.
- [ ] Owner undang caregiver, pilih Editor -> caregiver join, `role:
      "editor"` di respons join.
- [ ] Owner undang caregiver, pilih Hanya melihat -> caregiver join,
      `role: "viewer"`.
- [ ] Viewer buka Dashboard: catatan keliatan, tombol tambah/hapus
      nggak muncul.
- [ ] Editor buka Dashboard: tombol tambah muncul, tombol hapus CUMA
      muncul di catatan buatan sendiri.
- [ ] Editor coba hapus catatan buatan owner lewat UI (kalau tombolnya
      somehow keliatan) -> backend balikin 403, UI nampilin pesan jelas,
      TIDAK logout paksa.
- [ ] Owner ubah caregiver dari Editor ke Hanya melihat -> caregiver
      langsung nggak bisa nyimpen catatan baru (request berikutnya
      langsung 403, bukan nunggu logout/login ulang).
- [ ] Owner cabut akses caregiver -> caregiver nggak lagi lihat anak itu
      di daftar anaknya.
- [ ] Editor antre 1 catatan offline, DIDEMOSI ke viewer oleh owner
      (dari device lain), baru online lagi -> item masuk "Perlu
      ditinjau" di Sync Center, BUKAN otomatis tersimpan.
- [ ] Audit trail nunjukin event "caregiver diundang/diubah/dicabut"
      tanpa nampilin email/kode undangan/nilai peran mentah.
