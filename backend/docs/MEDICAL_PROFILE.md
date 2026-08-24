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
| `/children/<id>/emergency-card/preview` | `POST` | Kartu Darurat manusiawi (body kosong) |
| `/children/<id>/emergency-card/pdf` | `POST` | PDF Kartu Darurat (body kosong) |

Body JSON malformed ditolak. Batas ukuran body **lebih ketat** dari batas
global — `MAX_MEDICAL_PROFILE_BODY_BYTES = 20_000`, ditegakkan lewat
bounded-stream read (pola SAMA `_read_json_body_within_limit` dari
`doctor_consultation_routes.py`, aman walau `Content-Length` hilang/salah
— lihat `backend/docs/DOCTOR_CONSULTATION.md` buat rasionalnya lengkap).
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

## Konsistensi snapshot preview ↔ PDF

Pola **SAMA PERSIS** `activeSnapshot` immutable dari Doctor Consultation,
tapi mekanisme invalidasinya beda karena Kartu Darurat **tidak punya**
parameter request dari caregiver buat di-fingerprint (preview Doctor
Consultation berubah tiap kombinasi periode/section; preview Kartu
Darurat cuma berubah kalau PROFIL-nya sendiri berubah):

`editGenerationRef` (ref, bukan state — hindari closure basi) dinaikkan
tiap `PUT`/`review` sukses. Saat preview diambil, `editGeneration` snapshot
saat itu disimpan berpasangan dengan hasil laporan
(`{ report, editGeneration }`). Tombol Unduh PDF cuma aktif kalau
`activeSnapshot.editGeneration === editGenerationRef.current` — perubahan
profil apa pun setelah preview (bahkan lewat form edit yang secara visual
tertutup modal Kartu Darurat) langsung menandainya basi, pesan "Profil
medis sudah diubah sejak pratinjau ini dibuat" tampil, tombol Unduh PDF
disabled sampai preview diulang. `handleDownload` mengirim body kosong ke
endpoint PDF (endpoint itu sendiri membaca profil TERKINI dari database
saat generate — **bukan** payload dari frontend) TAPI baru bisa dipanggil
kalau snapshot preview masih segar, konfirmasi privasi (`window.confirm`)
WAJIB dulu, dan `pdfSubmitting` mencegah klik ganda memicu unduhan dobel.
`requestSeqRef` + `mountedRef` di `EmergencyCardModal` mencegah respons
preview basi (out-of-order) menimpa state, sama pola `MedicalProfileScreen`
level induk (`activeChildIdRef` + `mountedRef`) buat request `GET` profil.

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
      medis sudah diubah..." tampil, sampai preview diulang.
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
