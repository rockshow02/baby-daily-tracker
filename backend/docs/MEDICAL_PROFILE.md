# Child Medical Profile & Emergency Card — Phase 1

Satu tempat aman buat caregiver menyimpan info medis kritis anak (alergi,
kondisi, kontak medis/darurat) dan menghasilkan **Kartu Darurat** ringkas
buat ditunjukkan ke tenaga medis. **BUKAN** alat diagnosis/rekomendasi
medis/validasi dosis/saran penanganan darurat — murni mengorganisir data
yang caregiver sendiri masukkan (lihat disclaimer di `emergency_card_report.py`,
ditampilkan di setiap preview & PDF).

Reuse penuh, **bukan** sistem kedua: model Child yang sudah ada, helper
peran/izin `utils/access.py`, `utils/audit.py`, pola PDF ReportLab
(`utils/pdf_common.py`, diekstrak dari `consultation_pdf.py` — lihat
"Arsitektur PDF" di bawah), API client + `ApiError`, pola online/offline
`useOnlineStatus`, backup/export/import yang sudah ada, dan
`scripts/migrate_production.py`.

## Data model

Satu tabel baru, `ChildMedicalProfile` (`backend/models.py`), **satu baris
per anak** (`child_id` unique + indexed, relasi `Child.medical_profile`
`uselist=False`, `cascade="all, delete-orphan"` — profil ikut terhapus
kalau anak dihapus, diverifikasi test terpisah):

| Kolom | Tipe | Keterangan |
|---|---|---|
| `blood_type` | `String(10)`, nullable | CHECK constraint allowlist 9 nilai (lihat "Validasi") |
| `allergies` | `JSON`, default `[]` | Satu daftar, tiap entri punya `type` (drug/food/other) — **bukan** 3 kolom terpisah, lihat rasionalnya di bawah |
| `conditions` | `JSON`, default `[]` | Kondisi medis penting |
| `primary_doctor_name`, `primary_clinic_name`, `primary_clinic_phone` | `String` | Kontak medis utama |
| `emergency_contact_name`, `emergency_contact_relationship`, `emergency_contact_phone` | `String` | Kontak darurat |
| `emergency_instructions` | `Text` | Instruksi bebas caregiver (dibatasi panjang) |
| `last_reviewed_at`, `last_reviewed_by_user_id` | `DateTime`/FK | Diisi lewat endpoint `review` terpisah |

**Sengaja TIDAK ADA**: BPJS/asuransi/ID pemerintah/alamat — risiko privasi
yang tidak sepadan dengan manfaatnya buat Kartu Darurat (spesifikasi
eksplisit meminta ini dikecualikan).

**`allergies` satu struktur JSON dengan field `type`, bukan 3 kolom
terpisah** (drug/food/other): ini "desain ternormalisasi terkecil" yang
dipilih — validasi (lihat di bawah) tetap membedakan tipe lewat field,
jadi tidak kehilangan struktur, tapi tidak perlu 3 kolom/3 endpoint/3 form
terpisah buat sesuatu yang bentuknya identik selain 1 field diskriminator.

**`regular_medication_summary` BUKAN kolom tersimpan** — dihitung ulang
tiap request langsung dari `MedicationSchedule` yang `is_active=True` dan
tanggalnya masih berlaku hari itu (`utils/emergency_card_report.py:_regular_medications`).
Ini memenuhi requirement "jangan duplikasi riwayat obat" secara
arsitektural: nol kolom baru, nol risiko data basi antara 2 tabel.

## Validasi (`utils/medical_profile_engine.py`)

Satu-satunya entry point dipakai **baik** oleh route PUT **maupun** import
backup (`validate_medical_profile_payload`) — tidak ada 2 jalur validasi
yang bisa berbeda.

- **Golongan darah**: allowlist `A+/A-/B+/B-/AB+/AB-/O+/O-/unknown`/`null`
  — **tidak pernah** disimpulkan dari input lain.
- **Alergi** (maks 30): `type` ∈ {drug, food, other}, `allergen` wajib
  (dibatasi panjang), `reaction` opsional, `severity` opsional ∈
  {mild, moderate, severe, unknown} — **tidak pernah** diklasifikasi
  otomatis dari teks reaksi, `confirmed_by_professional` bool opsional.
  Deduplikasi lewat `(type, allergen.lower().strip())`. Key JSON di luar
  allowlist yang diketahui ditolak (bukan diabaikan diam-diam) — beda
  dari field top-level tak dikenal di body (lihat "Kontrak API").
- **Kondisi** (maks 30): `condition_name` wajib, `diagnosed_year` opsional
  (rentang tahun masuk akal), `status` opsional ∈ {active, resolved,
  unknown} — **tidak pernah** disimpulkan/didiagnosis, `note` opsional.
  Deduplikasi lewat nama ternormalisasi.
- **Kontak** (telepon dokter/klinik/darurat): whitespace dinormalisasi,
  dibatasi panjang, charset telepon konservatif — **tidak pernah**
  diverifikasi kepemilikannya (bukan validasi eksistensi nomor), **tidak
  pernah** muncul di log/audit/pesan exception.
- **Instruksi darurat**: teks polos, CRLF dinormalisasi, dibatasi panjang
  ketat, **tidak pernah** dirender sebagai HTML, di-escape sebelum masuk
  PDF, **tidak pernah** diperlakukan sebagai saran medis.

## Kontrak API

| Endpoint | Method | Keterangan |
|---|---|---|
| `/children/<id>/medical-profile` | `GET` | Baca profil + `capabilities` |
| `/children/<id>/medical-profile` | `PUT` | Snapshot atomik — 1 request ganti SEMUA field sekaligus, bukan patch parsial |
| `/children/<id>/medical-profile/review` | `POST` | Tandai "sudah diperiksa ulang" TANPA wajib mengubah field lain |
| `/children/<id>/emergency-card/preview` | `POST` | Kartu Darurat manusiawi (body kosong); respons menyertakan `snapshot_token` (lihat "Konsistensi snapshot preview → PDF") |
| `/children/<id>/emergency-card/pdf` | `POST` | PDF Kartu Darurat — body **WAJIB** `{"snapshot_token": "..."}` dari preview terakhir (lihat bagian sama) |

Body JSON malformed ditolak. Batas ukuran body **lebih ketat** dari batas
global, ditegakkan lewat bounded-stream read (pola SAMA
`_read_json_body_within_limit` dari `doctor_consultation_routes.py`,
aman walau `Content-Length` hilang/salah — lihat
`backend/docs/DOCTOR_CONSULTATION.md` buat rasionalnya lengkap), DUA
konstanta terpisah karena bentuk body-nya beda jauh:

| Endpoint | Batas | Alasan |
|---|---|---|
| `PUT .../medical-profile` | `MAX_MEDICAL_PROFILE_BODY_BYTES = 20_000` (20KB) | ≤30 entri alergi + ≤30 kondisi + beberapa field kontak/teks pendek |
| `POST .../emergency-card/pdf` | `MAX_EMERGENCY_CARD_PDF_BODY_BYTES = 4_096` (4KB) | Body cuma 1 field (`snapshot_token`) — token terpanjang pun jauh di bawah 2KB, 4KB margin sangat longgar |

Field top-level tak dikenal di body **diabaikan diam-diam** (konsisten
konvensi seluruh endpoint lain di app ini). Error terstruktur Bahasa
Indonesia — **tidak pernah** stack trace mentah/detail skema internal.
`GET`/PUT`review` response selalu menyertakan `capabilities` (dihitung
backend, frontend **wajib** memakainya langsung) dan `last_reviewed_at` +
nama tampilan penginjau (bukan raw user ID).

## Peran & kapabilitas

| Capability | Owner | Editor | Viewer |
|---|---|---|---|
| `can_view_medical_profile` | ✅ | ✅ | ❌ |
| `can_edit_medical_profile` | ✅ | ✅ | ❌ |
| `can_preview_emergency_card` | ✅ | ✅ | ❌ |
| `can_export_emergency_card` | ✅ | ✅ | ❌ |

**Viewer TIDAK PUNYA akses sama sekali secara default** ke fitur ini
(beda dari Doctor Consultation, di mana Viewer boleh preview) — GET,
preview, dan PDF SEMUA balas `403` yang **seragam**, terlepas profil
sudah ada atau belum, biar keberadaan profil **tidak pernah** bisa
disimpulkan dari luar. Pengecekan izin ini dijalankan **sebelum** body
diproses ukurannya — Viewer yang mengirim body raksasa tetap dapat `403`
yang sama persis (bukan `413` yang membocorkan bahwa ukuran sempat
diperiksa).

Frontend (`MedicalProfileScreen.jsx`) default ke `LEAST_PRIVILEGE_CAPABILITIES`
(semua `false`) sampai `GET` pertama berhasil — **tidak pernah** optimis,
konsisten pola `DoctorConsultationScreen.jsx`. Tombol edit tambahan juga
mensyaratkan `canWrite(child.role)` frontend (defense-in-depth UI, backend
tetap satu-satunya penegak sebenarnya).

## Emergency Card — preview & PDF

Satu fungsi sumber-tunggal, `utils/emergency_card_report.py:build_emergency_card_summary(child, profile, now)`,
dipakai **baik** oleh endpoint preview standalone **maupun** section
`medical_profile` di Doctor Consultation (lihat di bawah) — kesetaraan
logis preview↔PDF terjamin karena keduanya cuma "penerjemah" beda dari
dict yang sama (pola identik `DOCTOR_CONSULTATION.md`).

Isi kartu: nama tampilan anak, tanggal lahir + usia saat ini, golongan
darah (`"Belum dicatat"` kalau kosong — **tidak pernah** ditebak), alergi
berat/penting duluan, kondisi aktif penting duluan, ringkasan obat rutin
AKTIF saat ini (dari `MedicationSchedule`, bukan riwayat), kontak
dokter/klinik utama, kontak darurat, instruksi darurat caregiver, tanggal
diperiksa ulang terakhir, catatan privasi + disclaimer medis.

**Sengaja dikecualikan**: riwayat obat lengkap, log harian umum, data
audit sensitif, ID user/anak/request, catatan caregiver yang bukan buat
kartu ini, jadwal obat yang sudah nonaktif/dihapus. **Tidak pernah**
memalsukan data yang belum diisi sebagai "tidak ada" — selalu ditandai
eksplisit "Belum dicatat"/"Belum diisi".

PDF (`utils/emergency_card_pdf.py`) sinkron, di memori (`io.BytesIO`),
**tidak pernah** ditulis ke disk — reuse helper ReportLab bersama
(`utils/pdf_common.py`, lihat "Arsitektur PDF"). Teks caregiver di-escape
sebelum masuk `Paragraph`, nama file disanitasi
(`safe_filename_component`, copy dari pola `doctor_consultation_routes.py`).

## Konsistensi snapshot preview → PDF

### Defect yang diperbaiki (bug review Agustus 2026)

Versi AWAL fitur ini mengandalkan `editGenerationRef` frontend (ref
dinaikkan tiap `PUT`/`review` SUKSES lewat instance frontend yang sama)
sebagai **satu-satunya** mekanisme invalidasi, dan endpoint PDF meng-query
ULANG profil + jadwal obat TERKINI dari database saat request PDF
datang. **Ini cacat**: `editGenerationRef` cuma tahu perubahan yang
lewat instance frontend ITU SENDIRI — kalau (1) caregiver LAIN
mengedit/mereview profil, ATAUPUN (2) jadwal obat dibuat/diubah/
dinonaktifkan/dihapus/expired di antara waktu preview & unduh PDF,
frontend TIDAK PERNAH tahu, dan endpoint PDF akan diam-diam merender
PDF yang **berbeda** dari apa yang caregiver sudah lihat & konfirmasi
privasinya di layar preview.

### Arsitektur perbaikan: token snapshot bertanda tangan (STATELESS)

PythonAnywhere Free **tidak mendukung** Redis/Celery/worker persisten/
cron/cache lintas-request — solusinya **bukan** menyimpan state
sementara di server (baik di memori maupun tabel DB baru), tapi
menandatangani snapshot-nya SENDIRI ke dalam sebuah token opaque yang
frontend bawa balik. Lihat `utils/emergency_card_snapshot.py` (modul
baru, "SATU shared backend helper" buat kanonikalisasi/digest — dipakai
BAIK oleh endpoint preview MAUPUN endpoint PDF, requirement eksplisit).

**Alur preview** (`POST .../emergency-card/preview`):
1. `now_wib()` di-sample **SEKALI** (`preview_at`).
2. Laporan dibangun (`build_emergency_card_summary(child, profile, preview_at)`) —
   sama seperti sebelumnya.
3. Representasi KANONIK laporan itu dihitung
   (`canonicalize_emergency_card_report`, lihat "Kebijakan
   kanonikalisasi" di bawah), lalu di-hash SHA-256
   (`digest_emergency_card_report`).
4. Token opaque ditandatangani (`itsdangerous.URLSafeTimedSerializer`,
   `SECRET_KEY` Flask yang **sudah ada** — **tidak ada** kriptografi
   custom) berisi claims MINIMAL: `child_id`, `user_id` (dari sesi
   terautentikasi), `preview_at` (ISO string), `digest` (hex SHA-256),
   `v` (versi skema token). **TIDAK PERNAH** golongan darah/alergi/
   kondisi/kontak/instruksi darurat/nilai medis APA PUN di dalam token
   (diverifikasi test `test_snapshot_token_claims_never_contain_medical_or_contact_values`).
5. Token dikembalikan sebagai `snapshot_token` di respons JSON preview,
   BERSAMA laporan yang sama seperti sebelumnya.

**Alur PDF** (`POST .../emergency-card/pdf`), urutan pengecekan
SENGAJA (lihat `routes/medical_profile_routes.py:export_emergency_card_pdf`):
1. Login + akses anak.
2. Otorisasi export Owner/Editor (Viewer ditolak `403` di sini, SEBELUM
   body/token disentuh sama sekali — lihat "Peran & kapabilitas").
3. Bounded body read (`MAX_EMERGENCY_CARD_PDF_BODY_BYTES = 4_096` — lihat tabel batas ukuran di "Kontrak API" di atas).
4. Body harus objek JSON.
5. Tanda tangan + masa berlaku token diverifikasi
   (`decode_snapshot_token`) — token hilang/rusak/kedaluwarsa/versi
   skema tidak cocok → `400`.
6. Claims token harus `child_id`+`user_id` **PERSIS** sama dengan
   request SEKARANG → kalau tidak, `403` (token curian/salah tempel
   dari anak/sesi lain SELALU ditolak walau tanda tangannya sah).
7. Laporan DIBANGUN ULANG memakai `preview_at` **DARI TOKEN**
   (`datetime.fromisoformat(claims["preview_at"])`) — **BUKAN**
   `now_wib()` baru. Ini yang membuat `generated_at`/usia/pilihan obat
   rutin aktif ikut **IDENTIK** dengan preview, tanpa perlu menyimpan
   laporan itu sendiri di mana pun.
8. Digest laporan yang BARU dibangun ulang dihitung pakai **helper
   kanonikalisasi yang SAMA PERSIS** dipakai preview.
9. Dibandingkan dengan digest di dalam token pakai **`hmac.compare_digest`**
   (timing-safe — bukan `==` biasa).
10. **Cocok** → PDF dirender & diaudit. **Tidak cocok** → `409` dengan
    pesan `"Data Kartu Darurat berubah sejak pratinjau dibuat. Muat
    ulang pratinjau sebelum mengunduh PDF."` — **TIDAK PERNAH** merender
    PDF ATAUPUN menulis baris audit buat request yang ditolak di
    langkah manapun (5–10).

Waktu EKSPOR sebenarnya (`export_now = now_wib()`, disample TERPISAH
dari `preview_at`) dipakai **CUMA** buat `recorded_at` baris audit &
nama file unduhan — dua hal ini **BUKAN** bagian dari digest, jadi
wall-clock yang lebih belakangan **TIDAK PERNAH** membuat snapshot yang
sebenarnya masih valid ditolak keliru (diverifikasi test
`test_unchanged_data_with_later_wall_clock_still_exports_previewed_snapshot`).

**Masa berlaku token**: `SNAPSHOT_TOKEN_MAX_AGE_SECONDS = 15 * 60` (15
menit) — cukup buat caregiver membaca preview & memutuskan unduh,
cukup pendek biar token lama tidak jadi risiko praktis. Token yang
kedaluwarsa WAJIB pratinjau ulang (frontend menampilkan pesan &
tombol "Muat ulang pratinjau" yang sama seperti kasus `409`).

### Kebijakan kanonikalisasi (`canonicalize_emergency_card_report`)

**DIMASUKKAN** (semua field yang tampil di preview JSON MAUPUN PDF):
`child_display_name`, `birth_date`, `age_now`, `blood_type`,
`blood_type_label`, `allergies` (lengkap tiap entri), `conditions`
(lengkap tiap entri), `regular_medications` (lengkap tiap entri —
daftar obat rutin AKTIF yang DIDERIVASI, requirement eksplisit "include
the derived regular medication list"), `primary_doctor_name`,
`primary_clinic_name`, `primary_clinic_phone`, `emergency_contact_name`,
`emergency_contact_relationship`, `emergency_contact_phone`,
`emergency_instructions`, `last_reviewed_at`, `last_reviewed_by_name`
(jadi aksi "review" IKUT membatalkan snapshot lama, walau tidak
mengubah field profil lain), `has_profile`, `generated_at` (= `preview_at`,
dipakai ulang APA ADANYA saat rebuild), `disclaimer`, `privacy_note`.

**DIKECUALIKAN**: `capabilities` (response-only, tergantung ROLE
pemanggil SAAT ITU — bukan bagian isi laporan; secara struktural TIDAK
PERNAH tersentuh fungsi kanonikalisasi karena field ini ditambahkan
route SETELAH `build_emergency_card_summary()` selesai) dan
`snapshot_token` itu sendiri.

Deterministik: `json.dumps(..., sort_keys=True, ensure_ascii=False,
separators=(",", ":"))` menormalkan urutan KEY di semua level (nested
dict alergi/kondisi/obat termasuk) — urutan insersi dict Python di
kode TIDAK memengaruhi digest (diverifikasi
`test_canonicalization_is_stable_regardless_of_dict_key_order`).
`None`/`[]`/`""`/angka/boolean dibedakan APA ADANYA (encoder JSON
bawaan Python, tidak dinormalisasi manual). Urutan LIST alergi/kondisi
sudah deterministik dari sumbernya (`_sorted_allergies`/`_sorted_conditions`,
diurut berdasar severity/status rank, BUKAN diacak ulang fungsi ini);
daftar obat rutin diurutkan `medication_name` + `id` SEKUNDER (bukan
cuma `medication_name`) — tie-breaker ini krusial menghindari urutan
ORM yang tidak stabil untuk 2 jadwal dengan nama identik (requirement:
"avoid unstable ORM ordering").

### Perilaku frontend (`MedicalProfileScreen.jsx:EmergencyCardModal`)

**DUA lapis** proteksi konsistensi, saling melengkapi (bukan salah satu
saja):

1. **LOKAL (cepat, UX doang)**: `editGenerationRef` (dinaikkan tiap
   `PUT`/`review` SUKSES lewat instance frontend ini) — `snapshotIsFresh`
   jadi `false` SEKETIKA (tanpa bolak-balik server) begitu USER SENDIRI
   baru saja mengedit profil, bahkan kalau editnya terjadi lewat form
   yang secara visual tertutup modal Kartu Darurat (modal & layar utama
   berbagi 1 pohon komponen, keduanya tetap "hidup" di DOM).
2. **SERVER (otoritatif, wajib)**: `activeSnapshot.snapshotToken` — token
   dari preview, dikirim APA ADANYA ke endpoint PDF
   (`{ snapshot_token }`, **bukan** body kosong seperti sebelumnya).
   Respons `409`/`400`/`403` dari endpoint PDF (lihat urutan pengecekan
   di atas) **SEMUANYA** ditangani dengan perlakuan UI yang SAMA:
   `activeSnapshot.report` yang SUDAH ditampilkan **tetap kelihatan**
   (buat perbandingan, TIDAK dibuang), tombol Unduh PDF **dinonaktifkan**,
   pesan aman Bahasa Indonesia ditampilkan (dari server kalau ada,
   fallback lokal kalau tidak), dan tombol **"Muat ulang pratinjau"**
   yang eksplisit memanggil `runPreview()` ulang.

`runPreview()` mengganti `report` + `snapshotToken` **BERSAMAAN, 1
`setState`** (destructuring `{ snapshot_token, ...report }` dari
respons) — **atomik**, tidak pernah ada state antara di mana report
baru tapi token lama (atau sebaliknya), dan otomatis membersihkan
`serverStaleMessage` lama. `requestSeqRef` + `mountedRef` di
`EmergencyCardModal` (plus `activeChildIdRef` + `mountedRef` level
`MedicalProfileScreen` buat request `GET` profil) mencegah respons
preview basi (out-of-order — mis. React StrictMode yang meng-invoke
efek mount 2×) menimpa snapshot yang lebih baru. `handleDownload` WAJIB
`activeSnapshot.snapshotToken` ada (token hilang → tombol disabled),
konfirmasi privasi (`window.confirm`) WAJIB dulu, dan `pdfSubmitting`
mencegah klik ganda memicu unduhan dobel — kedua proteksi ini
**dipertahankan** dari versi sebelumnya, tidak berubah.

## Kebijakan offline — ONLINE-ONLY (Fase 1)

**Sengaja tanpa cache offline sama sekali** — beda dari
`MedicationScheduleScreen`/`ReminderScreen` yang punya cache lokal.
`MedicalProfileScreen.jsx` **tidak pernah** menyimpan profil ke
localStorage/IndexedDB/sessionStorage, **tidak pernah** mengantre
edit/PDF ke offline queue (`getMedicalProfile`/`updateMedicalProfile`/
`reviewMedicalProfile`/`previewEmergencyCard` **sengaja tidak**
didaftarkan di `OFFLINE_QUEUEABLE_PATHS`, `frontend/src/api/client.js`).
Alasan: data ini (alergi, kontak darurat, instruksi darurat) terlalu
sensitif buat disimpan di penyimpanan device yang tidak terenkripsi
sungguhan — app ini **tidak** mengklaim enkripsi kecuali benar-benar
diimplementasikan dengan manajemen kunci yang autentik, jadi klaim
"terenkripsi" palsu tidak pernah dibuat.

Kalau offline: pesan Bahasa Indonesia jelas ("Butuh koneksi internet"),
**tidak ada** data pribadi basi dari user/anak lain yang sempat tampil,
**tidak ada** permintaan yang diantre. Ini keterbatasan Fase 1 yang
didokumentasikan sadar, bukan bug — lihat "Keterbatasan yang diketahui".

## Integrasi Doctor Consultation

Section BARU `medical_profile` (`SECTION_MEDICAL_PROFILE`,
`utils/consultation_report.py`) — **default OFF**, opt-in eksplisit,
ditandai sensitif di pemilih section (`SECTION_DEFS`, frontend). **LEBIH
KETAT** dari section sensitif lain: Owner/Editor **saja** yang boleh
menyertakannya (`can_include_medical_profile`, `doctor_consultation_routes.py`)
— Viewer **tidak bisa** menyertakan section ini sama sekali, walau Viewer
BOLEH menyertakan section sensitif lain (illness/medication/dst) di
laporan yang sama. Kalau Viewer mencoba, `403` dilempar **khusus** untuk
section ini (bukan seluruh request preview) di `_parse_request_payload`,
sebelum laporan mana pun dibangun.

Frontend (`DoctorConsultationScreen.jsx`) menonaktifkan + otomatis
mencentang-mundur checkbox `medical_profile` begitu sebuah preview
mengonfirmasi `can_include_medical_profile: false` (mencegah state
"tercentang tapi disabled" yang membingungkan), dengan catatan inline
"Peran Anda tidak bisa mengakses ini". Sebelum preview pertama, checkbox
ini tetap bisa dicentang (least-privilege belum dikonfirmasi bukan berarti
"pasti ditolak") — sama pola least-privilege capability lain di layar itu.

Isi section ini di laporan konsultasi **sama persis** hasil
`build_emergency_card_summary` (fungsi sumber-tunggal yang sama dipakai
Kartu Darurat standalone) — hanya field yang layak buat kartu darurat,
**tidak pernah** catatan internal mentah kecuali memang dimaksudkan.
Snapshot immutable Doctor Consultation yang sudah ada **tidak berubah**
sama sekali — mengedit profil medis SETELAH sebuah preview konsultasi
diambil **tidak pernah** diam-diam mengubah snapshot yang sudah direview
(pola `activeSnapshot` Doctor Consultation, lihat `DOCTOR_CONSULTATION.md`).

## Arsitektur PDF — `utils/pdf_common.py`

Refactor murni (nol perubahan perilaku, diverifikasi re-run penuh
`test_consultation_pdf.py` + `test_doctor_consultation.py`, 77/77 lulus):
helper ReportLab bersama (`safe`, `safe_multiline`, `fmt_num`,
`BaseStyles`, `kv_table`, `entries_table`, warna) diekstrak dari
`utils/consultation_pdf.py` ke modul baru `utils/pdf_common.py`, lalu
`consultation_pdf.py` mengimpornya kembali lewat alias
(`BaseStyles as _Styles`, dst) — nama underscore-prefixed lama & seluruh
test yang sudah ada **tidak berubah**. `utils/emergency_card_pdf.py` dan
section `medical_profile` di `consultation_pdf.py` (`_render_medical_profile`)
sama-sama memakai helper bersama ini — **tidak ada** framework PDF kedua.

## Audit trail

Diaudit: pembuatan profil, update profil, aksi "diperiksa ulang" (entity
type terpisah `medical_profile_reviewed`, masuk
`NO_FIELD_DIFF_ENTITY_TYPES` karena aksi ini tidak wajib mengubah field
lain), ekspor PDF Kartu Darurat (`emergency_card_pdf_export`, juga
`NO_FIELD_DIFF_ENTITY_TYPES`, `entity_id=0` — sentinel, tidak ada baris
DB acuan tunggal buat 1 PDF), dan ekspor konsultasi dokter yang menyertakan
section `medical_profile` (lewat aturan audit konsultasi yang **sudah
ada**, tidak ada aturan baru).

**Setiap field profil medis dianggap privasi-sensitif** — `SAFE_CHANGED_FIELDS["medical_profile"]`
sengaja diisi **set kosong** (bukan dihilangkan — kehadirannya wajib
supaya lolos guard allowlist entity type `record_audit_event`), sehingga
SEMUA field yang berubah (golongan darah, alergi, kondisi, nama/telepon
kontak, instruksi darurat) selalu masuk `PRIVATE_CHANGED_FIELDS`, direkam
sebagai marker generik `private_details` — **tidak pernah** nilai medis/
nama alergen/kondisi/obat/kontak/telepon/instruksi mentah tersimpan di
baris audit. Update tanpa perubahan nyata (`diff_snapshots` kosong)
**tidak** membuat baris audit baru. Preview **tidak** diaudit (pola sama
`DOCTOR_CONSULTATION.md` — baca murni, dipanggil berkali-kali, noise tanpa
nilai keamanan tambahan).

## Backup/export/import

Diperiksa dulu implementasi yang sudah ada (`routes/backup_routes.py`) —
diperluas, **bukan** dibuat sistem backup kedua. Profil medis
disertakan **HANYA** di backup privat anak yang terautentikasi (**tidak
pernah** di endpoint laporan/publik umum), dan **hanya** kalau peran
pengekspor Owner/Editor (`resolve_role(...) in WRITE_ROLES`) — Viewer yang
mengekspor backup anak yang sama **tidak** mendapat bagian `medical_profile`
sama sekali, walau baris profilnya ada di database.

**`last_reviewed_at`/`last_reviewed_by_user_id` SENGAJA TIDAK diekspor** —
identitas "siapa yang mereview" dari akun sumber tidak bermakna (dan
berpotensi bocor info) di konteks akun tujuan import; profil yang
di-import **selalu** dianggap "belum pernah direview" di konteks baru.

Import memvalidasi payload lewat **fungsi validasi yang sama persis**
dipakai endpoint PUT (`validate_medical_profile_payload`) — **tidak ada**
jalur validasi kedua yang bisa longgar/berbeda. Import atomik (gagal
validasi = seluruh import gagal, **tidak pernah** menyimpan sebagian).
Backup lama tanpa `medical_profile` (dibuat sebelum fitur ini ada) tetap
kompatibel — field ini `None`/absen di backup lama, import melewatinya
begitu saja tanpa error, diverifikasi test round-trip khusus.

## Migrasi database

Satu tabel baru, `child_medical_profiles` — **tidak ada** kolom baru di
tabel yang sudah ada, jadi **tidak ada** entri baru yang perlu ditambahkan
ke `COLUMNS_TO_ENSURE`. `db.create_all()` di `scripts/migrate_production.py`
(langkah yang sudah ada) otomatis membuat tabel ini kalau belum ada —
persis pola `medication_schedules`/`medication_dose_actions` sebelumnya.
Aman dijalankan berkali-kali (idempoten), diverifikasi
`tests/test_migrate_production.py` (kolom, index, unique constraint pada
`child_id`, CHECK constraint golongan darah, re-run aman, data tabel lain
tidak tersentuh, **tidak pernah** menyentuh `backend/instance/tracker.db`
asli).

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
ada** langkah scheduled-task/cron yang perlu dikonfigurasi (fitur ini
sepenuhnya sinkron per-request, konsisten prinsip "tanpa background"
PythonAnywhere Free — tidak ada Celery/Redis/worker persisten/WebSocket).

### Rollback

Karena migrasi ini cuma menambah 1 tabel baru:

1. `git checkout <commit-sebelumnya>` di server.
2. Reload web app.
3. Tabel `child_medical_profiles` yang sudah terlanjur dibuat **boleh
   dibiarkan** (kode lama tidak pernah menyentuhnya) — atau, kalau ingin
   benar-benar bersih, hapus manual lewat SQLite console SETELAH
   memverifikasi tidak ada data yang masih ingin disimpan. **Tidak
   pernah** menjalankan `DROP TABLE` sebagai bagian dari script migrasi
   otomatis.

## Manual QA checklist

- [ ] Health → tab Dokter menampilkan tombol "🩺 Profil Medis & Kartu
      Darurat" di sebelah tombol "🩺 Siapkan Konsultasi" yang sudah ada.
- [ ] Owner: buka profil kosong, semua field menampilkan "Belum
      dicatat"/"Belum diisi" (bukan JSON kosong/null mentah).
- [ ] Tambah alergi + kondisi terstruktur, isi kontak medis & darurat,
      simpan — profil tampil benar setelah reload.
- [ ] "Tandai sudah diperiksa ulang" memperbarui tanggal + nama
      penginjau tanpa perlu mengubah field lain.
- [ ] Viewer: GET/preview/PDF profil anak yang sama **semua** balas
      "Tidak punya akses" (403 seragam), tombol edit/preview tidak
      pernah muncul.
- [ ] Lihat Kartu Darurat → preview manusiawi tampil (bukan JSON), alergi
      berat & kondisi aktif tampil duluan, obat rutin AKTIF saat ini
      tampil benar.
- [ ] Edit profil SAAT modal Kartu Darurat masih terbuka dengan preview
      lama — setelah simpan, tombol Unduh PDF nonaktif + pesan "Profil
      medis sudah diubah..." + tombol "Muat ulang pratinjau" tampil,
      sampai preview diulang.
- [ ] Buka Kartu Darurat di 2 tab/perangkat berbeda sebagai 2 caregiver
      (Owner+Editor) untuk anak yang SAMA — di tab pertama, preview dulu;
      di tab KEDUA, edit profil (atau tambah jadwal obat baru) SETELAH
      preview tab pertama diambil; kembali ke tab pertama, klik Unduh
      PDF → **409**, pesan "Data Kartu Darurat berubah sejak pratinjau
      dibuat...", preview lama TETAP kelihatan (bukan hilang), tombol
      "Muat ulang pratinjau" berfungsi & memulihkan alur normal.
- [ ] Klik Unduh PDF → konfirmasi privasi muncul dulu; batalkan → tidak
      ada unduhan; konfirmasi → 1 PDF terunduh, klik cepat berkali-kali
      tidak memicu unduhan ganda.
- [ ] Offline (matikan koneksi) → pesan "Butuh koneksi internet" tampil,
      tidak ada request terkirim/terantre.
- [ ] Doctor Consultation: centang section "Profil Medis & Kartu
      Darurat" sebagai Owner → tersedia & masuk laporan/PDF. Sebagai
      Viewer → dinonaktifkan otomatis setelah preview + catatan "Peran
      Anda tidak bisa mengakses ini".
- [ ] Backup: export sebagai Owner menyertakan `medical_profile`; import
      backup itu ke anak lain (atau akun lain) mengembalikan profil
      dengan benar, status "belum pernah direview".
- [ ] Ganti anak aktif SAAT profil anak lama masih tampil — data anak
      lama langsung hilang dari layar, tidak pernah tercampur dengan
      data anak baru walau sebentar.

## Keterbatasan yang diketahui (Fase 1)

- **Online-only** — tidak ada akses/edit/PDF offline sama sekali (lihat
  "Kebijakan offline" di atas); ini keputusan privasi sadar, bukan
  keterbatasan teknis sementara.
- **Tidak ada klaim enkripsi** — data disimpan di database aplikasi yang
  sama seperti record lain, **tidak** ada lapisan enkripsi tambahan
  khusus fitur ini (konsisten seluruh app; klaim enkripsi palsu sengaja
  dihindari).
- **`regular_medication_summary` derivatif, bukan snapshot beku** — kalau
  jadwal obat berubah SETELAH sebuah PDF diunduh, PDF lama (yang sudah
  ada di device pengguna) tetap menampilkan data lama; ini konsisten
  dengan sifat dokumen PDF (statis begitu diunduh), bukan bug.
  "Refresh" berarti unduh PDF baru.
- **Tidak ada riwayat perubahan/undo** buat status "sudah diperiksa
  ulang" — cuma tanggal+penginjau TERAKHIR yang disimpan, bukan log tiap
  kali ditandai.
- **Golongan darah/alergi/kondisi murni entri caregiver** — sistem
  **tidak pernah** memvalidasi kebenaran medisnya (mis. interaksi
  alergen-obat), sesuai batas cakupan Fase 1 yang eksplisit diminta.
- **Token snapshot preview → PDF kedaluwarsa dalam 15 menit** — kalau
  caregiver membiarkan modal Kartu Darurat terbuka lebih lama dari itu
  sebelum klik Unduh PDF, mereka akan diminta pratinjau ulang (`400`,
  ditangani sama seperti kasus `409` di frontend) — trade-off sadar
  antara keamanan (token lama tidak menumpuk jadi risiko) dan
  kenyamanan; 15 menit dianggap lebih dari cukup buat alur baca-lalu-
  putuskan-unduh yang biasa.
