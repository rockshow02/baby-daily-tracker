# Doctor Consultation Workflow — Phase 1

Melengkapi fitur kunjungan dokter yang sudah ada
(`routes/health_routes.py` — `doctor-visits`), **bukan** modul dokter
kedua yang terpisah. Alur lengkap:

1. **Siapkan konsultasi** — pilih periode + bagian laporan (frontend:
   tombol "🩺 Siapkan Konsultasi" di Health → tab Dokter).
2. **Review laporan terstruktur** — `POST .../doctor-consultation/preview`.
3. **Unduh PDF berkontrol-privasi** — `POST .../doctor-consultation/pdf`.
4. **Lakukan konsultasi** (di luar aplikasi).
5. **Catat hasil kunjungan** — tombol "Catat Hasil Kunjungan" membuka
   form kunjungan dokter yang **sudah ada** (`POST /children/<id>/doctor-visits`),
   **tidak ada** form kedua.

## Doctor Visit History vs Consultation Report

| | Doctor Visit History (sudah ada) | Consultation Report (fitur ini) |
|---|---|---|
| Tujuan | Catatan PERMANEN 1 kunjungan yang SUDAH terjadi (dokter, klinik, diagnosis, kontrol berikutnya) | Ringkasan SEMENTARA dari catatan lain (feeding/sleep/growth/dst) buat DIBAWA ke konsultasi BERIKUTNYA |
| Disimpan? | Ya, permanen (`doctor_visit_logs`) | Tidak — laporan dihitung ulang tiap request, tidak pernah disimpan |
| Sumber data | Diketik manual caregiver | Diagregasi otomatis dari 12+ tipe record anak yang sudah ada |
| Kapan dipakai | SETELAH konsultasi (mencatat hasil) | SEBELUM konsultasi (menyiapkan bahan) |

## Data sources

Report murni MEMBACA record yang sudah ada — **tidak ada tabel baru**
(lihat "Migrasi database" di bawah). Sumber per section ada di
`utils/consultation_report.py`, seluruhnya di-scope ke periode
`[start_date, end_date]` (kecuali `vaccination`, yang memang status
TERKINI):

| Section | Sumber |
|---|---|
| `child_summary` | `Child` + `compute_health_metrics` (jumlah aman) |
| `feeding`/`sleep`/`diaper`/`pumping`/`activity_mood` | `utils/insights_engine.py:compute_*_metrics` (REUSE, bukan query baru) |
| `growth` | `compute_growth_metrics` + `GrowthMeasurement` (dibatasi baris) |
| `temperature` | `compute_health_metrics` + agregat SQL (avg/min/max) |
| `illness`/`medication`/`doctor_visits` | Query langsung, dibatasi baris, `notes` **tidak pernah** disertakan |
| `vaccination` | `routes/children_routes.py:_build_vaccination_list` (REUSE) |
| `milestones` | `MilestoneLog`, `custom_label` **tidak pernah** disertakan |
| `insights` | `utils/insights_engine.py` (compute_* + `build_comparison` + `build_insights`, REUSE penuh) + deskripsi Indonesia allowlist BARU (`INSIGHT_CODE_DESCRIPTIONS`) |
| `questions`/`note` | Teks TRANSIEN dari request, **tidak pernah** disimpan |

## Section-selection behavior

16 kode section tetap (`utils/consultation_report.py:SECTION_CODES`).
`sections` di request: list kode, unik, dikenal, urut TETAP di respons
(bukan urutan request). Tidak dikirim/`null` → default privacy-conscious.
`sections: []` sah (laporan kosong).

## Privacy defaults

**Default (privacy-conscious, tanpa identitas medis spesifik/teks
bebas):** `child_summary`, `feeding`, `sleep`, `diaper`, `growth`,
`temperature`, `vaccination`, `milestones`.

**Opt-in eksplisit (harus dipilih manual):** `pumping`, `activity_mood`,
`insights` (bukan sensitif, cuma di luar default demi laporan ringkas),
DAN `illness`, `medication`, `doctor_visits`, `questions`, `note`
(SENSITIF — `SENSITIVE_SECTIONS`, lihat di bawah).

Data-minimization **lebih ketat** dari sekadar allowlist field: field
`notes` (Text bebas) di SEMUA tipe record, dan `custom_label` milestone,
**tidak pernah** disertakan di laporan ini SAMA SEKALI — bahkan di
section yang eksplisit dipilih — beda dari field bernama sensitif lain
(nama obat/dosis/nama penyakit/gejala/nama dokter/klinik/diagnosis)
yang boleh muncul HANYA kalau section-nya dipilih.

Tidak pernah disertakan di mana pun: email caregiver, password/token/
session, ID database internal (kecuali `vaccine_schedule_id` yang sudah
publik lewat endpoint vaksinasi lain), audit detail, header request,
isi antrean offline, metadata sistem tersembunyi, data anak lain.

## Sensitive-data opt-in

`SENSITIVE_SECTIONS = {illness, medication, doctor_visits, questions, note}`.
Frontend menandai kelimanya dengan badge "Sensitif" di checklist, dan
menampilkan konfirmasi privasi sebelum unduh PDF kalau
`sensitive_sections_included` (dipantulkan backend, otoritatif — bukan
dihitung ulang di frontend) tidak kosong.

## Roles & capabilities

Reuse `utils/access.py` (`resolve_role`, `WRITE_ROLES`) — **tidak** ada
sistem izin kedua. Backend mengembalikan capability EKSPLISIT di setiap
respons (`capabilities.*`), frontend **wajib** memakainya langsung,
**tidak pernah** menyimpulkan izin dari role mentah sendiri:

| Capability | Owner | Editor | Viewer |
|---|---|---|---|
| `can_preview` | ✅ | ✅ | ✅ |
| `can_export` (PDF) | ✅ | ✅ | ❌ |
| `can_add_private_notes` (questions/note) | ✅ | ✅ | ❌ |
| `can_record_visit` | ✅ | ✅ | ❌ |

Viewer TETAP boleh lihat preview penuh (termasuk section sensitif kalau
dipilih) — data yang sama sudah bisa dibaca viewer lewat endpoint lain
yang sudah ada (daftar obat/sakit/kunjungan dokter); yang dibatasi CUMA
2 hal yang BARU di fitur ini: menambahkan teks pertanyaan/catatan
sendiri, dan mengunduh PDF. Endpoint PDF menegakkan ini SERVER-SIDE
(403 kalau `can_export` false) — tombol frontend cuma UI hint.

### Kapabilitas frontend — least-privilege sebelum ada respons (bug review Agustus 2026)

**Root cause defect (diperbaiki):** `DoctorConsultationScreen.jsx` versi
awal default-kan `canAddNotes`/`canExport`/`canRecordVisit` ke `true`
SEBELUM preview pertama pernah berhasil (`report?.capabilities ? ... :
true`) — Viewer sempat melihat field pertanyaan/catatan (dan bisa
mengetik ke situ) sebelum backend pernah bilang APA yang boleh
dilakukan. Backend tetap menolak (403) kalau isinya beneran dikirim,
TAPI kontrol frontend-nya sendiri salah nampilin privilege yang belum
tentu ada.

**Perbaikan:** ketiga capability itu SEKARANG default `false` sampai
ada respons preview yang BERHASIL DAN masih jadi snapshot aktif (lihat
`activeSnapshot` di bawah) — TIDAK PERNAH optimis. Konsekuensi UX yang
disengaja: Owner/Editor JUGA baru melihat field pertanyaan/catatan &
tombol Unduh PDF/Catat Hasil Kunjungan SETELAH preview pertama mereka
berhasil, bukan langsung dari awal — trade-off yang dipilih SENGAJA
(opsi 3 dari kebijakan yang direview) karena tidak butuh mengubah
kontrak props `HealthScreen.jsx`→`DoctorConsultationScreen.jsx` (tidak
melebar ke refactor yang tidak terkait) dan lebih aman daripada
kemungkinan Viewer sempat lihat kontrol privileged walau sebentar.
Kegagalan preview (network error ATAUPUN 403) TIDAK PERNAH mengubah
`activeSnapshot` yang sudah ada — kapabilitas yang sudah diketahui
sebelumnya TETAP dipertahankan, tidak "naik" ataupun "turun" gara-gara
1 percobaan gagal.

### Konsistensi preview ↔ PDF — snapshot immutable (bug review Agustus 2026)

**Root cause defect (diperbaiki):** tombol Unduh PDF memanggil
`buildPayload()` ULANG dari state form TERKINI, sedangkan konfirmasi
privasi membaca `report.sensitive_sections_included` dari preview
LAMA — kalau user memilih section sensitif SETELAH preview pertama
(tanpa preview ulang), PDF yang benar-benar terkirim ke server bisa
memuat section yang TIDAK PERNAH direview ataupun dikonfirmasi
privasinya.

**Perbaikan:** `activeSnapshot` (state `{payload, report}`) adalah
SATU-SATUNYA sumber kebenaran buat export — payload baru (`sections`
terurut deterministik ngikutin urutan tetap, BUKAN Set/array yang bisa
terus dimutasi) dan hasil preview-nya disimpan BERPASANGAN dan ATOMIK
CUMA kalau respons itu masih yang TERBARU (lihat `requestSeqRef`, buat
race out-of-order) DAN tidak ada edit yang terjadi SELAGI request itu
masih terbang (lihat `editCounterRef`, ref BUKAN state React, biar
nggak kena masalah closure basi). Perubahan input APA PUN setelah
snapshot ada (periode/tanggal kustom/section/pertanyaan/catatan)
langsung menandainya `stale` — tombol Unduh PDF & Catat Hasil Kunjungan
disembunyikan, pesan `Pilihan laporan berubah. Buat pratinjau ulang
sebelum mengunduh PDF.` ditampilkan, konfirmasi privasi yang lagi
kebuka otomatis dibatalkan (bukan dimutasi diam-diam). `handleDownload`
mengirim `activeSnapshot.payload` APA ADANYA — TIDAK PERNAH membangun
ulang payload dari form. Konfirmasi privasi membaca
`activeSnapshot.report.sensitive_sections_included` (bukan state form
saat ini ataupun laporan lain manapun) dan menyebutkan LABEL section
sensitif yang beneran mau diekspor. Teks pertanyaan/catatan tetap
CUMA hidup di state React komponen ini (tidak pernah localStorage/
sessionStorage/IndexedDB/URL/log) dan lenyap otomatis begitu komponen
unmount (Health screen membungkusnya dengan render kondisional, bukan
`display:none`) ATAUPUN begitu `child` yang aktif berganti (efek
terpisah yang membersihkan snapshot+state transien+membatalkan request
yang mungkin masih terbang buat anak lama).

## Request validation & size limits

Body endpoint konsultasi SEHARUSNYA kecil (≤16 kode section pendek,
metadata periode, dan 2 field teks yang masing-masing sudah dibatasi
1000 karakter) — jauh lebih kecil dari `MAX_CONTENT_LENGTH` global
aplikasi (6MB, `config.py`, dilonggarkan buat upload foto). Endpoint
ini menegakkan batas KHUSUS yang lebih ketat,
`utils/consultation_report.py:MAX_CONSULTATION_BODY_BYTES = 20_000`
(20KB), lewat **2 LAPIS** (lihat
`routes/doctor_consultation_routes.py:_read_json_body_within_limit`) —
satu lapis header saja TERBUKTI TIDAK CUKUP (bug review Agustus 2026,
lihat di bawah):

1. **Penolakan cepat berbasis `Content-Length` terdeklarasi** (kalau
   header ini ADA) — ditolak `413` SEBELUM stream disentuh sama
   sekali, nol byte terbaca. Jalur ini murah tapi CUMA berlaku kalau
   klien/proxy jujur ngirim header ini secara akurat.
2. **Bounded read AKTUAL dari `request.stream`** — dijalankan SELALU
   (terlepas ada/tidaknya `Content-Length`), baca PALING BANYAK
   `MAX_CONSULTATION_BODY_BYTES + 1` byte. Kalau yang KEBACA lebih
   dari batas, `413` — INI yang menutup celah: body yang dikirim
   TANPA `Content-Length` (request chunked/WSGI tanpa panjang
   terdeklarasi) sebelumnya lolos lapis 1 begitu saja dan diproses
   sampai batas GLOBAL 6MB baru ketauan kegedean (lewat validasi
   panjang field questions/note yang jalan BELAKANGAN, SETELAH body-nya
   sempat di-parse JSON penuh) — sekarang tetap kena `413` di lapisan
   ini, secepat body ASLINYA (bukan cuma klaim header-nya) kelewat 20KB.

**Kenapa cuma cek header nggak cukup:** `request.content_length`
Flask/Werkzeug HANYA membaca header `Content-Length` yang klien kirim
— nggak ada jaminan itu akurat. Kalau header ini absen (mis. transfer
`chunked`, atau WSGI server yang nggak selalu menyertakannya), Werkzeug
akan (tergantung apakah WSGI server men-declare `wsgi.input_terminated`)
entah membalikin stream KOSONG (paling umum, aman TAPI berarti lapis 1
nggak pernah "melihat" body beneran sama sekali) ATAUPUN membungkusnya
`LimitedStream` sepanjang `MAX_CONTENT_LENGTH` GLOBAL (6MB) — either
way, lapis 1 TIDAK PERNAH bisa menyimpulkan ukuran body ASLINYA dari
header semata. Lapis 2 di atas mengatasi ini dengan MEMBACA body-nya
sendiri (dibatasi ketat), bukan percaya klaim header.

**Cara body yang sudah dibaca lapis 2 dipakai lagi tanpa baca dua
kali:** byte yang berhasil dibaca (kalau lolos batas) di-cache manual
ke `request._cached_data` — atribut internal Werkzeug yang JUGA dipakai
`request.get_data()`/`request.get_json()` sendiri buat "baca-sekali,
pakai-ulang" (lihat `werkzeug/wrappers/request.py:Request.get_data`) —
SEBELUM `request.get_json()` dipanggil, jadi ia membaca cache yang
sama, TIDAK PERNAH mencoba membaca stream lagi (yang di titik itu
sudah habis/terpakai sebagian — baca ulang bakal dapat body kosong,
bukan body lengkap).

**Semantik byte, bukan karakter:** batas 20KB diukur dari PANJANG BYTE
UTF-8 body yang benar-benar di atas kabel (`len(bytes)`), BUKAN
`len()` string Python setelah decode — 1 karakter emoji 4-byte (mis.
"🩺") tetap terhitung 4 byte, bukan 1 "karakter". Body dengan banyak
karakter multi-byte tapi encoded-nya masih ≤20000 byte tetap diterima;
body yang encoded byte-nya sudah lewat 20000 tetap ditolak walau
`len()` string Python-nya kelihatan kecil (lihat
`tests/test_doctor_consultation.py::test_multibyte_utf8_payload_measured_by_encoded_bytes_not_character_count`).

**Buffering yang TIDAK bisa dihindari sepenuhnya:** lapis 2 SELALU
membaca maksimal `MAX_CONSULTATION_BODY_BYTES + 1` byte ke memori
(bukan menunggu sampai batas global 6MB seperti sebelumnya) —
ini SUDAH bounded read yang disukai (bukan `get_data()` penuh yang bisa
sampai 6MB), jadi TIDAK ADA eksposur memori tak terduga di luar ~20KB
per request untuk endpoint ini. `MAX_CONTENT_LENGTH` global aplikasi
(6MB, buat upload foto) TETAP jadi jaring pengaman TERLUAR yang
independen (ditegakkan Werkzeug sendiri di layer stream) — batas 20KB
di sini SELALU dicek DULUAN & lebih ketat, TIDAK PERNAH menggantikan
jaring pengaman global itu; nilai `MAX_CONTENT_LENGTH` itu sendiri
TIDAK diubah oleh perbaikan ini.

**Otorisasi vs ukuran body — urutan yang disengaja:** untuk endpoint
PDF, pengecekan `can_export` (peran) TETAP dijalankan SEBELUM body
(apalagi ukurannya) disentuh — Viewer yang mengirim body raksasa dapat
`403` yang SAMA PERSIS dengan Viewer yang mengirim body kecil/valid,
tidak pernah bisa dibedakan dari luar (413 vs 403) berdasarkan ukuran
body-nya, konsisten dengan pola "cek peran dulu, validasi payload
belakangan" di SELURUH endpoint lain di app ini.

**Field top-level tak dikenal SENGAJA diabaikan diam-diam** (dibaca
lewat `data.get(...)`, TIDAK divalidasi allowlist-nya) — ini KONSISTEN
dengan konvensi SELURUH endpoint lain di app ini (`health_routes.py`,
`reminder_routes.py`, dst — semuanya baca field yang dikenal satu-satu,
TIDAK ADA yang menolak key request asing). Menambahkan kebijakan
"tolak field asing" cuma di endpoint ini akan jadi perilaku validasi
yang tidak konsisten/mengejutkan dibanding endpoint lain — keputusan
sadar untuk TIDAK melakukannya, bukan kelalaian.

## Date & timezone policy

Semua batas tanggal WIB (`Asia/Jakarta`), lewat `utils/timezone_utils.py`
(`today_wib()` dipanggil SEKALI di layer route, sama pola
`reminder_routes.py`/`insights_routes.py`). Preset `7d`/`14d`/`30d` =
N hari TERAKHIR termasuk hari ini. Custom range: `end_date >= start_date`,
`end_date <= today`, rentang maksimal **90 hari** (inklusif) —
**backend SELALU otoritatif**, validasi frontend cuma UX aid (lihat
`utils/consultation_report.py:resolve_consultation_period`, raise
`ConsultationValidationError` → `400`).

## PDF generation architecture

Sinkron, DI MEMORI, SETELAH request autentikasi — **tidak ada**
Celery/Redis/scheduled task/worker permanen/layanan dokumen eksternal,
konsisten arsitektur "tanpa background" PythonAnywhere Free di seluruh
app. Pakai `reportlab` — dependency PDF yang SAMA dipakai
`routes/report_routes.py` (laporan umum yang sudah ada), **tidak**
menambah dependency baru.

`utils/consultation_pdf.py:render_consultation_pdf(report)` menerima
dict yang SAMA PERSIS dipakai respons preview (1 sumber data, cuma beda
cara render) dan mengembalikan `io.BytesIO` siap-kirim lewat
`send_file(..., mimetype="application/pdf", as_attachment=True,
download_name=...)`. Buffer dibuang begitu response terkirim — **tidak
pernah** ditulis ke disk server, **tidak ada** URL PDF permanen.

Keamanan teks: SEMUA teks sumber-caregiver (nama obat/penyakit/dokter/
klinik, gejala, alasan, diagnosis, ATAUPUN teks transien
questions/note) di-escape (`html.escape`) SEBELUM dibungkus
`Paragraph` — `reportlab.platypus.Paragraph` menafsirkan markup
mirip-XML (`<b>`, `<br/>`, dst), jadi tanpa escaping ini teks caregiver
bisa menyuntik markup PDF (diverifikasi test
`test_html_script_content_in_questions_is_treated_as_plain_text` —
tanpa escaping, reportlab akan melempar parse error alih-alih render).

Format: A4, margin 1.5–2cm, font ≥8pt, tabel `repeatRows=1` (header
berulang tiap halaman lanjutan), teks panjang lewat `Paragraph`
(auto-wrap, tidak pernah terpotong), footer berulang tiap halaman
(nomor halaman + nama laporan/anak — lihat `_footer`), disclaimer +
catatan privasi + pernyataan "dibuat dari catatan caregiver" di awal
dokumen. **Tidak ada** nomor "Halaman X dari Y" (cuma "Halaman X") —
pola "X dari Y" butuh two-pass canvas (`NumberedCanvas`) yang belum ada
presedennya di app ini; disederhanakan demi cakupan Fase 1, bisa
ditambah nanti kalau dibutuhkan. Tidak memuat foto profil/gambar
unggahan/URL eksternal apa pun (murni tabel/teks).

## Offline limitations

**Preview ONLINE-ONLY di Fase 1** (bukan keterbatasan teknis biasa —
keputusan sadar): cache offline yang AMAN buat fitur ini butuh
menyaring section sensitif DAN teks transien questions/note sebelum
disimpan (requirement eksplisit), plus isolasi per user+child+periode —
kompleksitas itu di luar cakupan Fase 1 dibanding manfaatnya (laporan
ini dibuat SEBELUM konsultasi, bukan info darurat yang perlu diakses
offline). Kalau offline: layar cuma menampilkan pesan "butuh koneksi",
menonaktifkan tombol Preview/PDF, **tidak pernah** mengantre permintaan
apa pun (endpoint ini SENGAJA tidak masuk `OFFLINE_QUEUEABLE_PATHS` di
`frontend/src/api/client.js`). PDF export **selalu** online-only,
apa pun kondisi cache lainnya di app.

## Audit behavior

**CUMA export PDF yang diaudit, preview TIDAK** — preview murni baca,
dipanggil berkali-kali tiap section/tanggal di-ganti sebelum caregiver
mantap; mengaudit tiap panggilan itu jadi noise besar tanpa nilai
keamanan tambahan (pola sama seperti `GET /reminders`/`GET /insights`
yang juga tidak diaudit).

Entity type baru: `doctor_consultation_pdf_export` (`utils/audit.py`),
masuk `NO_FIELD_DIFF_ENTITY_TYPES`. `action="create"`, `entity_id=0`
(sentinel — **tidak ada** baris database yang jadi acuan PDF ini, laporan
SENGAJA tidak pernah disimpan permanen), `changed_fields_json` SELALU
`None`. **Keputusan penting**: rentang tanggal & kode section yang
dipilih **tidak** disimpan di baris audit ini — kolom
`changed_fields_json` secara arsitektur cuma untuk NAMA field yang
berubah pada event `update` (lihat `utils/audit.py` docstring:
"CUMA buat action='update'; null buat create/delete"), bukan wadah
metadata/nilai bebas; memaksakannya di sini akan melanggar invarian
yang sudah ditegakkan di seluruh modul audit. Demikian juga Request ID
**sengaja tidak** disimpan di baris audit (tabel `CaregiverAuditEvent`
secara eksplisit — lihat docstring modelnya — tidak pernah menyimpan
request ID sama sekali, untuk entity type mana pun); korelasi
request-level tetap tersedia lewat log request standar
(`utils/observability.py`) berdasarkan timestamp bila benar-benar
diperlukan untuk debugging operasional.

## Performance bounds

Semua query di-scope ke child_id + periode (memakai kolom yang sudah
diindeks — sama pola `insights_engine.py`), **tidak pernah** query
seluruh riwayat anak. Batas baris per section detail (SELALU ditandai
`truncated`+`total_count_in_period` kalau melebihi):

| Section | Batas baris |
|---|---|
| `growth` (measurements) | 20 |
| `illness` | 15 |
| `medication` | 20 |
| `milestones` | 15 |
| `doctor_visits` | 10 |

Rentang tanggal maksimal 90 hari (custom) membatasi `daily_trend`
feeding/sleep/dst juga (maks ~90 entri/section). Section `insights`
paling mahal: sampai ~14 query kecil (9 metrik periode ini + 5 metrik
periode sebelumnya, SAMA PERSIS biaya endpoint `/insights` yang sudah
ada) — CUMA jalan kalau section ini eksplisit dipilih. Tidak ada
gambar/foto/URL eksternal yang dimuat ke PDF. Tidak ada transaksi
database yang tetap terbuka selama render PDF (`build_consultation_report`
selesai baca SEBELUM `render_consultation_pdf` dipanggil — render PDF
murni CPU/memori, tidak menyentuh session database).

## PythonAnywhere Free compatibility

Tidak ada proses background/scheduler/worker persisten — PDF selalu
sinkron per-request, sama seperti seluruh app ini (lihat
`backend/docs/REMINDERS.md`/`INSIGHTS.md` untuk prinsip yang sama).
Tidak ada dependency baru (reuse `reportlab` yang sudah ada). Tidak ada
penulisan file ke disk server. `MAX_CONTENT_LENGTH` global (6MB, sudah
ada di `config.py`) membatasi ukuran request; panjang `questions`/
`additional_note` dibatasi 1000 karakter masing-masing sebagai lapis
tambahan.

## Manual QA checklist

- [ ] Health → tab Dokter menampilkan tombol "Siapkan Konsultasi".
- [ ] Preset 7/14/30 hari menghasilkan periode yang benar (bandingkan
      `period.start_date`/`end_date` di respons).
- [ ] Rentang kustom: tanggal akhir < mulai ditolak, tanggal masa depan
      ditolak, rentang > 90 hari ditolak (400 dari backend, bukan cuma
      dicegah frontend).
- [ ] Default section TIDAK menyertakan obat/sakit/kunjungan dokter/
      pertanyaan/catatan.
- [ ] Memilih section sensitif menampilkan badge "Sensitif" dan
      memicu konfirmasi privasi sebelum unduh PDF.
- [ ] Viewer: preview berhasil, tombol Unduh PDF & field
      pertanyaan/catatan TIDAK muncul; kalau dipaksa lewat API
      langsung, backend balas 403.
- [ ] PDF terunduh, dibuka di pembaca PDF, judul "Laporan Konsultasi
      Dokter", nama anak & usia benar, disclaimer & catatan privasi
      terlihat, tabel tidak terpotong, teks panjang bungkus rapi.
- [ ] "Catat Hasil Kunjungan" membuka form kunjungan dokter yang
      SUDAH ADA (bukan form baru) dan tersimpan normal ke riwayat.
- [ ] Offline: layar konsultasi menampilkan pesan butuh koneksi,
      tombol Preview/PDF nonaktif; layar lain (Dashboard/Reminder
      offline cache) tidak terpengaruh.
- [ ] Klik "Unduh PDF" berkali-kali cepat TIDAK memicu unduhan ganda
      (tombol disabled selama proses).
- [ ] Setelah preview berhasil, ubah pilihan section (mis. centang
      "Riwayat Obat") TANPA preview ulang — tombol Unduh PDF & Catat
      Hasil Kunjungan hilang, muncul pesan "Pilihan laporan berubah.
      Buat pratinjau ulang sebelum mengunduh PDF."
- [ ] Sebelum preview pertama berhasil, Viewer/Owner/Editor SAMA-SAMA
      belum melihat field pertanyaan/catatan ataupun tombol Unduh
      PDF/Catat Hasil Kunjungan (least-privilege default) — Owner/Editor
      baru melihatnya SETELAH preview pertama mereka berhasil.

## Deployment steps

1. `git pull` branch `stagging` di server PythonAnywhere (tidak ada
   migrasi DB — lihat bagian di bawah).
2. Reload web app dari dashboard PythonAnywhere (`Web` tab → Reload).
3. Verifikasi `GET /api/health` tetap `200 {"status":"ok"}` (endpoint
   ini TIDAK diubah sama sekali oleh fitur ini).
4. Verifikasi manual: buka Health → Dokter, klik "Siapkan Konsultasi",
   generate preview, unduh 1 PDF percobaan.
5. Deploy frontend (Vercel) dari branch `stagging` seperti biasa —
   tidak ada environment variable baru yang dibutuhkan.

## Migrasi database

**Tidak ada migrasi** — fitur ini murni MEMBACA tabel yang sudah ada
(lihat "Data sources" di atas) dan menulis 1 baris audit BARU ke tabel
`caregiver_audit_events` yang **sudah ada** (kolom-kolomnya sudah
cukup, `entity_type` baru cuma nilai string baru di kolom yang sudah
ada, bukan kolom/tabel baru). `db.create_all()` yang sudah ada di
`scripts/migrate_production.py` tidak perlu langkah tambahan apa pun.

## Rollback steps

1. Revert commit fitur ini di branch `stagging` (`git revert` atau
   checkout commit sebelumnya), push, reload PythonAnywhere.
2. **Tidak perlu** rollback database — tidak ada skema yang berubah;
   baris `caregiver_audit_events` dengan
   `entity_type='doctor_consultation_pdf_export'` yang sudah tercatat
   sebelumnya TETAP aman dibiarkan ada (baris audit historis, bukan
   data aktif yang dipakai fitur lain) — endpoint baca audit trail
   yang sudah ada tetap bisa menampilkannya sebagai riwayat, atau
   diabaikan begitu saja kalau kode fitur ini sudah tidak ada.
3. Revert deploy frontend Vercel ke deployment sebelumnya lewat
   dashboard Vercel (instant rollback, tidak butuh rebuild).
