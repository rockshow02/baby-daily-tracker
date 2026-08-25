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
metadata periode, 2 field teks yang masing-masing sudah dibatasi 1000
karakter, DAN — khusus endpoint PDF sejak "Doctor Consultation
Snapshot-Safe PDF Export" — 1 `snapshot_token` yang jauh di bawah 2KB)
— jauh lebih kecil dari `MAX_CONTENT_LENGTH` global aplikasi (6MB,
`config.py`, dilonggarkan buat upload foto). **Batas
`MAX_CONSULTATION_BODY_BYTES = 20_000` (20KB) TIDAK diubah/dilonggarkan**
buat mengakomodasi token — sisa ruang yang sudah ada jauh lebih dari
cukup, requirement: "account for the added token without weakening the
current consultation-specific body limit." Endpoint ini menegakkan
batas KHUSUS yang lebih ketat,
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

## Human-readable preview (frontend presentation)

**JSON tetap format API internal** — respons `POST .../preview` TIDAK
berubah sama sekali (masih field terstruktur seperti `total_events`,
`avg_events_per_day`, `truncated`, dst, lihat "Data sources" di atas).
Yang berubah CUMA cara frontend MERENDER respons itu — sebelumnya
`DoctorConsultationScreen.jsx` menampilkan tiap section lewat
`<pre>{JSON.stringify(section, null, 2)}</pre>` (dump JSON mentah,
nama field teknis kelihatan apa adanya ke caregiver) — sekarang lewat
`frontend/src/components/consultation/ConsultationPreview.jsx` yang
memformat & melabeli setiap field jadi Bahasa Indonesia yang bisa
dibaca orang awam, TIDAK PERNAH menghitung ulang data apa pun (murni
presentasional — angka/teks yang ditampilkan SELALU berasal langsung
dari field respons yang sama, cuma diformat ulang).

**Kesetaraan LOGIS preview ↔ PDF**: preview (kartu-kartu di layar) dan
PDF (`utils/consultation_pdf.py`) TIDAK PERNAH wajib identik secara
visual/CSS, TAPI keduanya SELALU merender data dari `report` yang
SAMA PERSIS (periode, section terpilih, entri, nilai ringkasan, status
pemotongan, teks pertanyaan/catatan, daftar section sensitif,
disclaimer) — sumber datanya satu (`activeSnapshot.report` di
frontend), CUMA beda "penerjemah" (komponen React vs `reportlab`).

**Arsitektur komponen** (`frontend/src/components/consultation/`):
```
ConsultationPreview        (orkestrator -- iterasi report.included_sections)
  └── ConsultationSectionCard  (judul + badge "Sensitif" + error boundary per-section)
        └── sectionRenderers.jsx  (16 renderer eksplisit, dikunci per kode section)
              ├── SummaryGrid / KeyValueRow   (ringkasan label/nilai)
              ├── DetailList / DetailListItem (daftar entri sebagai kartu bertumpuk, BUKAN tabel lebar)
              ├── EmptySectionState
              ├── PartialDataNotice           ("X dari Y sesi memiliki data ...")
              └── TruncationNotice            ("Menampilkan X dari Y catatan terbaru ...")
```
Kode section yang TIDAK dikenal (belum ada renderer-nya — versi
frontend lama vs backend baru) balikin pesan generik
"Bagian ini belum didukung pada versi aplikasi ini.", TIDAK PERNAH
nampilin object mentah.

**Formatter** (`frontend/src/utils/consultationFormat.js` +
`consultationLabels.js`): tanggal/waktu SELALU lewat
`Intl.DateTimeFormat` dengan `timeZone: "Asia/Jakarta"` EKSPLISIT
(tanggal murni "YYYY-MM-DD" malah di-parse manual sebagai string, sama
sekali TIDAK lewat `Date`, biar kebal dari reinterpretasi timezone
device pembaca) — TIDAK PERNAH mengandalkan timezone lokal browser
buat menampilkan ulang timestamp yang sudah WIB. Angka desimal pakai
koma (format Indonesia via `Intl.NumberFormat("id-ID", ...)`), durasi
menit diformat jadi "X jam Y menit" yang bisa dibaca, nilai yang nggak
ada SELALU jadi `—` (TIDAK PERNAH `null`/`undefined`/`NaN` literal).

**Section `growth` — 3 kelompok** (bug review: preview & PDF sempat
CUMA nampilin pengukuran TERAKHIR, diam-diam nge-drop pengukuran
SEBELUMNYA dan perubahan lingkar kepala walau backend SUDAH ngirim
keduanya): "Pengukuran terakhir" (tanggal/berat/tinggi/lingkar kepala/
hari sejak pengukuran), "Pengukuran sebelumnya" (CUMA muncul kalau
`previous` beneran ada — field individual yang kosong tetap tampil
`—`, BUKAN nyembunyiin seluruh kelompok), lalu "Perubahan sejak
pengukuran sebelumnya" (berat/tinggi/lingkar kepala — delta `null`
jadi `—`, delta `0` tetap tampil "0,0" apa adanya, delta negatif tetap
bertanda minus, TIDAK PERNAH dihitung ulang di frontend/PDF, TIDAK
PERNAH diberi label "normal"/"lambat"/dst). PDF (`utils/consultation_pdf.py:_render_growth`)
diperbaiki BARENGAN, kelompok yang sama, biar kesetaraan logis
preview↔PDF tetap terjaga — lihat
`backend/tests/test_consultation_pdf.py`.

**Data parsial/kosong/terpotong**: field opsional yang cuma sebagian
event punya nilai (mis. volume menyusui/memerah ASI) ditampilkan
sebagai "Total volume yang tercatat" (BUKAN "Total volume", biar nggak
kesan lengkap) + notis cakupan "X dari Y sesi memiliki data volume." —
TIDAK PERNAH menyimpulkan tren dari data yang nggak lengkap. Section
yang dibatasi baris (illness/medication/growth/milestones/doctor
visits) menampilkan "Menampilkan X dari Y catatan terbaru pada periode
ini." (dari `total_count_in_period`/panjang array `entries` yang
sesungguhnya diterima) — TIDAK PERNAH boolean `truncated` mentah.
Section yang dipilih tapi kosong SELALU menampilkan pesan kosong yang
konkret ("Tidak ada catatan obat pada periode ini.", dst), TIDAK PERNAH
disembunyikan tanpa penjelasan.

**Badge sensitif**: setiap section sensitif (illness/medication/
doctor_visits/questions/note) menampilkan badge teks "Sensitif" (bukan
warna doang) di `ConsultationSectionCard`, konsisten dengan checklist
pemilihan section & daftar konfirmasi privasi sebelum unduh PDF (label
Indonesia yang SAMA, dari `utils/consultationSections.js`, satu sumber
dipakai keduanya).

**Aksesibilitas & mobile**: heading section pakai `<h3>` semantik
berurutan logis (ngikutin `included_sections`), daftar ringkasan pakai
`<dl>`/`<dt>`/`<dd>` (struktur definisi, bukan tabel div biasa), daftar
entri (obat/sakit/kunjungan dokter/dst) dirender sebagai KARTU
BERTUMPUK (BUKAN tabel lebar) — otomatis nggak pernah butuh scroll
horizontal di layar sempit, teks panjang (nama obat/gejala/alasan
kunjungan) bebas bungkus multi-baris. `aria-live="polite"` CUMA di
pembungkus level laporan (bukan tiap section), biar screen reader
nggak ngumumin ulang seluruh laporan tiap kali render.

**Penahanan error**: `SectionErrorBoundary.jsx` (class component,
per-section, TERPISAH dari `components/ErrorBoundary.jsx` yang buat
SELURUH aplikasi) membungkus tiap renderer section — 1 section yang
gagal render (bentuk data nggak terduga) balikin
"Bagian ini tidak dapat ditampilkan." TANPA menjatuhkan section lain
ataupun tombol Unduh PDF/Catat Hasil Kunjungan.

Tidak ada perubahan skema API — perubahan ini murni frontend
(`frontend/src/components/consultation/`, `frontend/src/utils/
consultationFormat.js`, `consultationLabels.js`, `consultationSections.js`).

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

## Konsistensi snapshot preview -> PDF (token bertanda tangan)

### Risiko yang diperbaiki (Doctor Consultation Snapshot-Safe PDF Export, bug review Agustus 2026)

Frontend (`DoctorConsultationScreen.jsx`) sudah punya `activeSnapshot`
immutable yang mencegah EDIT LOKAL (form yang diubah user SENDIRI)
diam-diam mengubah payload yang diekspor — lihat "Human-readable
preview" & docstring komponen itu. **Ini TIDAK CUKUP**: endpoint PDF
backend TETAP membangun ulang laporan dari state DATABASE TERKINI saat
request PDF datang. Kalau caregiver LAIN mengubah data
feeding/tidur/kesehatan/obat/vaksinasi/pertumbuhan/profil medis/dll —
ATAUPUN section APA PUN yang DIPILIH user ini — di antara waktu preview
& unduh PDF, PDF yang dihasilkan **bisa berbeda** dari laporan yang
sudah caregiver review & setujui privasinya. `editCounterRef`/
`requestSeqRef` frontend cuma melindungi dari race/edit **lewat
instance frontend yang sama**, **tidak pernah** dari perubahan
**eksternal** (caregiver lain, request lain, waktu yang berlalu).

Perilaku yang WAJIB (dan sekarang TERBUKTI lewat test, bukan cuma
diklaim): export mengirim persis laporan logis yang di-preview, ATAU
ditolak dan meminta pratinjau ulang. **Tidak pernah** diam-diam
mengekspor data yang berbeda.

### Arsitektur: token snapshot bertanda tangan (STATELESS)

Pola **SAMA** dengan Child Medical Profile & Emergency Card (lihat
`backend/docs/MEDICAL_PROFILE.md`), primitif kriptografi **DI-REUSE**
lewat `utils/snapshot_token.py` (SATU implementasi tanda-tangan/
verifikasi/expiry/hashing/perbandingan timing-safe, TIDAK diduplikasi)
tapi dengan **salt & versi skema TERPISAH** khusus fitur ini
(`utils/consultation_snapshot.py:CONSULTATION_SNAPSHOT_SALT`/
`CONSULTATION_SNAPSHOT_SCHEMA_VERSION`) — token 1 fitur **tidak pernah**
valid dipakai buat fitur lain (diverifikasi test: token Emergency Card
ditolak endpoint konsultasi, dan sebaliknya). PythonAnywhere Free
**tidak mendukung** Redis/Celery/worker persisten/cron/cache
lintas-request — solusinya **bukan** menyimpan state sementara di
server, tapi menandatangani ringkasan snapshot itu sendiri ke sebuah
token opaque yang frontend bawa balik:

1. **Preview** men-sample `now_wib()` **SEKALI** (`preview_at`),
   membangun laporan penuh (`build_consultation_report`), menghitung
   digest SHA-256 dari REPRESENTASI KANONIK-nya
   (`utils/consultation_snapshot.py:canonicalize_consultation_report` +
   `digest_consultation_report`), lalu menandatangani token yang CUMA
   berisi `child_id`, `user_id`, `preview_at`, `digest`, versi skema —
   **tidak pernah** pertanyaan/catatan/data medis/penyakit/obat/
   kunjungan dokter/detail menyusui-tidur/detail vaksinasi/isi section
   apa pun. Token dikembalikan sebagai `snapshot_token` di respons
   preview.
2. **PDF** WAJIB menerima token itu balik **beserta payload yang
   dikirim ulang** (period/sections/questions/additional_note — laporan
   **tidak bisa** dibangun ulang dari token doang, token cuma bawa
   digest+identitas, **bukan** isi laporan). Token diverifikasi (tanda
   tangan + kedaluwarsa + versi skema + child/user COCOK), laporan
   DIBANGUN ULANG memakai payload yang dikirim ulang **dan** database
   TERKINI, TAPI period-nya di-resolve ulang memakai `preview_at` BEKU
   dari token (bukan `today_wib()` baru) — digest laporan yang baru
   dibangun ulang dibandingkan **timing-safe** (`hmac.compare_digest`)
   dengan digest di token; **tidak cocok** → `409`, **tidak pernah**
   merender PDF yang berbeda dari yang sudah di-preview & dikonfirmasi.

**Satu sampel waktu per preview, TANPA KECUALI** (bug review Agustus
2026 — "midnight race"): `preview_consultation()` memanggil `now_wib()`
**TEPAT SEKALI**, disimpan ke SATU variabel lokal (`now`) yang dipakai
buat SEMUANYA — `now.date()` buat resolusi period, `build_consultation_report`
(usia, obat rutin aktif, dll), `generated_at`, DAN `preview_at` di
dalam `snapshot_token`. Endpoint ini **tidak pernah** memanggil
`today_wib()` sama sekali. Versi SEBELUMNYA memanggil `today_wib()`
duluan (buat resolusi period) baru `now_wib()` belakangan (buat isi
laporan + token) — 2 pemanggilan jam sistem TERPISAH berarti kalau
eksekusi kebetulan melewati tengah malam WIB PERSIS di antara
keduanya, `period` bisa ke-resolve pakai tanggal LAMA sementara
`generated_at`/`preview_at` token pakai tanggal BARU, membuat PDF yang
laporannya BENERAN belum berubah ditolak `409` PALSU saat diunduh.
Endpoint PDF (`export_consultation_pdf`) TIDAK terpengaruh perbaikan
ini — `today_wib()`-nya SENGAJA tetap dipanggil, murni buat validasi
bentuk/rentang payload yang dikirim ulang (lihat urutan pengecekan di
bawah), BUKAN buat isi laporan yang di-digest.

### Kontrak request PDF — bentuk FLAT (keputusan sadar)

`POST .../doctor-consultation/pdf` menerima **bentuk flat yang sama**
dengan sebelumnya (`period`, `sections`, `questions`,
`additional_note`), dengan `snapshot_token` ditambahkan **alongside**
field-field itu — **bukan** nesting baru `{"payload": {...},
"snapshot_token": "..."}`. Dipilih karena lebih kompatibel (perubahan
minimal ke bentuk request yang sudah ada, konsisten dengan cara
`_parse_request_payload` membaca body lewat `data.get(...)` satu-satu)
dan tetap membawa SEMUA yang dibutuhkan buat membangun ulang laporan.
Kontrak ini **satu-satunya** yang didukung — seluruh caller (frontend,
test) memakainya secara konsisten.

### Urutan pengecekan endpoint PDF (SENGAJA, lihat `export_consultation_pdf`)

1. Autentikasi + akses anak.
2. Otorisasi export (Owner/Editor) — **sebelum** body/token disentuh
   sama sekali, Viewer selalu dapat `403` yang sama terlepas ukuran
   body/validitas token.
3. Bounded raw-body read (batas KHUSUS, lihat "Request validation &
   size limits" di bawah — **tidak berubah**, token muat nyaman di
   dalamnya).
4. Body harus objek JSON.
5. Validasi payload & section sensitif yang **sudah ada**
   (period/sections/questions/note — pakai `today_wib()` REAL, **murni
   buat validasi bentuk/rentang**, bukan isi laporan akhir).
6. Tanda tangan + kedaluwarsa + versi skema token.
7. Token harus milik `child_id`+`user_id` yang **sama** dengan request
   sekarang.
8. Parse `preview_at` dari token secara **defensif** (praktis mustahil
   gagal — claims sudah lolos verifikasi tanda tangan — tetap ditangani
   eksplisit, bukan dipercaya buta).
9. **Bangun ulang** laporan pakai payload yang dikirim ulang + database
   TERKINI, TAPI period di-**resolve ulang** memakai `preview_at` BEKU
   (bukan `today_wib()` lagi).
10. Hash pakai helper kanonik yang **sama persis** dipakai preview.
11. Bandingkan digest **timing-safe**.
12. Render PDF **cuma** kalau cocok.
13. Audit **cuma** ditulis SETELAH semua validasi & pengecekan digest
    lolos.

**Tidak pernah** merender PDF ATAUPUN menulis baris audit buat request
yang ditolak di langkah manapun (diverifikasi test
`test_no_pdf_renderer_called_for_rejected_or_stale_requests` +
`test_no_audit_event_for_rejected_or_stale_pdf_requests`).

### Waktu beku vs waktu ekspor sebenarnya

`preview_at` (dari token) dipakai buat **SEMUA** hal yang memengaruhi
isi laporan: `generated_at`, perhitungan usia, resolusi period (preset
"7d" dkk **tetap** merujuk rentang tanggal yang SAMA PERSIS kayak saat
preview, bukan "7 hari dari sekarang" yang baru), dan field
time-sensitive lain manapun. `now_wib()` yang FRESH (`export_now`,
disample TERPISAH) **cuma** dipakai buat metadata audit
(`recorded_at`) + tanggal di nama file unduhan — dua hal itu **bukan**
bagian dari digest, jadi wall-clock yang lebih belakangan **tidak
pernah** membuat snapshot yang sebenarnya masih valid ditolak keliru
(diverifikasi test
`test_later_wall_clock_alone_does_not_invalidate_unchanged_snapshot`).

### Kebijakan kanonikalisasi (`utils/consultation_snapshot.py`)

Satu helper kanonikalisasi/digest EKSPLISIT, dipakai **SAMA PERSIS**
oleh preview MAUPUN PDF.

**DIMASUKKAN** (semua field yang tampil di preview JSON maupun PDF):
`child_id`, `child_display_name`, `period` (hasil resolusi — termasuk
`start_date`/`end_date`), `generated_at`, `disclaimer`, `privacy_note`,
`generated_statement`, `included_sections`, `sensitive_sections_included`,
dan `sections` (SELURUH isi tiap section yang TERPILIH — termasuk field
truncation/`total_count_in_period` per section; termasuk teks
`questions`/`note` TRANSIEN kalau section-nya dipilih; termasuk isi
section `medical_profile` kalau dipilih).

**DIKECUALIKAN**: `capabilities` (response-only, tergantung role
pemanggil SAAT ITU), `request_id`, `sensitive_section_codes`
(allowlist TETAP, bukan isi laporan) — ketiganya ditambahkan ROUTE
**setelah** `build_consultation_report()` selesai, jadi otomatis tidak
pernah tersentuh fungsi kanonikalisasi. `snapshot_token` itu sendiri
jelas bukan bagian konten.

**Allowlist di level KODE SECTION, bukan per-field nested** — keputusan
SADAR: 16 kode section bentuknya SANGAT heterogen (metrik agregat/
daftar entri/status vaksinasi/kartu insight/dll). Meng-hand-allowlist
SETIAP field nested-nya akan jadi TIDAK SINKRON kalau
`utils/consultation_report.py` menambah field baru ke salah satu
section builder di masa depan (field baru itu diam-diam **tidak** ikut
ke digest — rasa aman PALSU, kebalikan dari tujuan fitur ini).
Menyertakan isi section APA ADANYA (dibatasi ke KODE section yang
DIKENAL saja) justru LEBIH KONSERVATIF: perubahan field apa pun di
section manapun otomatis ikut memengaruhi digest. Ini aman karena tiap
section builder SUDAH menerapkan data-minimization-nya sendiri SEBELUM
mengembalikan datanya (`notes` bebas-teks/`custom_label`/dll tidak
pernah disertakan — lihat "Data-minimization" di atas modul
`consultation_report.py`) — isi section yang sampai ke sini sudah
berupa permukaan yang di-vetting aman untuk laporan.

Deterministik: `json.dumps(sort_keys=True, ensure_ascii=False,
separators=(",",":"), default=str)` (lihat
`utils/snapshot_token.py:compute_sha256_digest`) menormalkan urutan KEY
di semua level nested — urutan insersi dict Python TIDAK berpengaruh.
`None`/`""`/`[]`/angka/boolean dibedakan APA ADANYA. `default=str`
adalah jaring pengaman DEFENSIF (bukan perilaku normal — semua builder
laporan SUDAH `.isoformat()` sebelum mengembalikan data) buat
permukaan laporan yang jauh lebih besar dari Emergency Card.

**Server TIDAK PERNAH mempercayai laporan lengkap yang dikirim balik
browser sebagai konten PDF** — endpoint PDF cuma menerima `period`/
`sections`/`questions`/`additional_note`/`snapshot_token` (parameter
buat MEMBANGUN ULANG laporan), **bukan** laporan itu sendiri; server
SELALU membangun ulang dari database + memvalidasi lewat digest,
sesuai requirement "do not trust a complete report sent back by the
browser as PDF content."

### Urutan database deterministik

Diaudit SEMUA section yang melakukan query list (`_growth_section`,
`_illness_section`, `_medication_section`, `_milestones_section`,
`_doctor_visits_section` di `utils/consultation_report.py`; query
"terbaru"/"2 terakhir" di `utils/insights_engine.py:compute_growth_metrics`/
`compute_health_metrics`/`compute_milestone_metrics`; daftar vaksinasi
di `routes/children_routes.py:_build_vaccination_list`) — SEMUA
sekarang punya tie-breaker `id` SEKUNDER (mis.
`.order_by(IllnessLog.start_date.desc(), IllnessLog.id.desc())`), BUKAN
cuma kolom tanggal/timestamp SENDIRIAN. Tanpa ini, 2 record dengan
tanggal PERSIS sama urutannya TIDAK DIJAMIN stabil oleh SQLite —
preview & rebuild PDF bisa saja membaca urutan yang beda walau DATANYA
sama sekali tidak berubah, menghasilkan digest yang beda (`409` PALSU
buat data yang sebenarnya tidak berubah). Diverifikasi test
`test_deterministic_ordering_prevents_false_mismatch_for_same_date_records`.

### Tanda tangan, BUKAN enkripsi

`itsdangerous.URLSafeTimedSerializer` CUMA menjamin claims **tidak bisa
diubah tanpa ketahuan** dan timestamp-nya **tidak bisa dipalsukan** —
isinya sendiri cuma di-encode base64url, **bukan** dienkripsi. **Siapa
pun** yang memegang string token bisa MEMBACA payload-nya (base64-decode
biasa, tanpa kunci apa pun). Keamanannya bergantung **sepenuhnya** pada
tidak pernah menaruh nilai sensitif di claims (lihat daftar field yang
dikecualikan di atas) — **bukan** kerahasiaan token itu sendiri. Lihat
juga docstring `utils/snapshot_token.py`.

### `409` & error token — respons aman

Digest tidak cocok → `409`, pesan: `"Data laporan konsultasi berubah
sejak pratinjau dibuat. Buat pratinjau ulang sebelum mengunduh PDF."`
Token hilang/rusak/kedaluwarsa/versi skema tidak cocok → `400`. Token
sah TAPI buat anak/user LAIN → `403`. **Tidak ada** dari respons ini
yang membocorkan isi claims/detail tanda tangan/kenapa persisnya
ditolak — pesan generik & aman di semua kasus.

### Kapabilitas Emergency Card — TIDAK berubah

Refactor ini murni ekstraksi primitif GENERIK
(`utils/snapshot_token.py`) — API publik `utils/emergency_card_snapshot.py`
(nama fungsi, signature, perilaku) **tidak berubah sama sekali**,
diverifikasi: seluruh test Emergency Card yang sudah ada tetap hijau
TANPA modifikasi assertion.

### Keterbatasan & risiko yang tersisa

**JANGAN mengklaim "konsistensi snapshot sempurna" secara mutlak** —
yang benar-benar diimplementasikan & dibuktikan test adalah: (1)
SELURUH field yang tampil di preview JSON maupun PDF (termasuk isi tiap
section terpilih, section `medical_profile`, teks transien
questions/note) ikut ke digest, dan (2) perubahan APA PUN pada field
itu — via endpoint mana pun di app ini, oleh caregiver mana pun —
menghasilkan `409` sebelum PDF dirender. Bukan berarti "byte PDF
akhirnya dijamin identik" pada tingkat presentasi (font-rendering
reportlab dkk di luar cakupan ini) — kesetaraan yang dijamin adalah
**LOGIS** (data sumbernya), persis prinsip "kesetaraan logis
preview<->PDF" yang sudah didokumentasikan di atas.

- **Jendela 15 menit tetap ada risiko residual kecil**: kalau data
  berubah dan berubah KEMBALI ke nilai yang PERSIS SAMA (secara logis,
  byte demi byte) dalam jendela itu, digest akan cocok lagi dan PDF
  akan berhasil diunduh — App ini TIDAK mendeteksi "sempat berubah lalu
  kembali", cuma "beda dari kondisi terakhir dipreview vs kondisi
  sekarang". Risiko ini dianggap dapat diterima (skenario yang sangat
  spesifik & tidak berbahaya — datanya toh sama).
- **Token TIDAK BISA dicabut lebih awal** (server tidak menyimpan
  state) — kalau caregiver ingin "membatalkan" sebuah preview
  (mis. karena salah pilih section sensitif), satu-satunya cara adalah
  menunggu token itu kedaluwarsa (maks 15 menit) atau membuat preview
  baru (yang secara otomatis menggantikan token lama di frontend, TAPI
  token lama itu sendiri SECARA TEKNIS tetap "sah" di server sampai
  kedaluwarsa kalau digest-nya kebetulan masih cocok). Ini bukan
  kerentanan (token tetap terikat child_id+user_id+SECRET_KEY server),
  cuma keterbatasan model stateless yang disengaja.
- **Allowlist di level kode section** (bukan per-field, lihat di atas)
  berarti kalau SUATU SAAT sebuah section builder di
  `utils/consultation_report.py` mulai mengembalikan nilai NON-JSON-safe
  (mis. objek custom), `default=str` di `compute_sha256_digest` akan
  mendiamkannya jadi string alih-alih gagal keras — trade-off sadar
  demi ketahanan (lihat "Kebijakan kanonikalisasi" di atas), TAPI berarti
  developer yang menambah field baru tetap perlu memastikan nilainya
  `.isoformat()`/primitif JSON sebelum dikembalikan, konsisten konvensi
  yang SUDAH ditegakkan di seluruh modul ini.
- **Doctor Visit History yang sudah ada** (dicatat lewat "Catat Hasil
  Kunjungan") sama sekali TIDAK terpengaruh mekanisme ini — itu tetap
  endpoint CRUD biasa, bukan bagian dari snapshot preview/PDF.

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

**Urutan penulisan audit vs verifikasi snapshot** (Doctor Consultation
Snapshot-Safe PDF Export): baris audit `doctor_consultation_pdf_export`
CUMA ditulis SETELAH seluruh urutan pengecekan endpoint PDF lolos
(termasuk pengecekan digest terakhir) — lihat "Konsistensi snapshot
preview -> PDF" di atas. Request yang ditolak di langkah manapun
(otorisasi/ukuran body/validasi payload/token/digest tidak cocok)
**tidak pernah** menulis baris audit ATAUPUN merender PDF, diverifikasi
langsung lewat test (bukan cuma diasumsikan dari urutan kode).

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

Token snapshot (Doctor Consultation Snapshot-Safe PDF Export) **TIDAK
menambah kebutuhan infrastruktur apa pun**: tanda tangan/verifikasi
`itsdangerous` murni komputasi CPU (HMAC), tidak ada I/O jaringan/disk
tambahan; token itu sendiri **tidak pernah** disimpan di server (server
CUMA menghitung digest & menandatangani/memverifikasi, state-nya
sepenuhnya hidup di string token yang dibawa klien) — nol tabel
database baru, nol cache lintas-request, nol dependency Python baru
(`itsdangerous` **sudah** jadi dependency Flask sendiri, dipakai
`utils/auth.py:generate_token` sejak awal).

## Manual QA checklist

- [ ] Pratinjau menampilkan kartu-kartu terbaca (label Bahasa Indonesia,
      angka/tanggal/durasi diformat), TIDAK PERNAH JSON mentah/nama
      field teknis di layar mana pun.
- [ ] Di layar sempit (mobile), daftar obat/sakit/kunjungan dokter
      tampil sebagai kartu bertumpuk (bukan tabel yang perlu digeser
      ke samping), teks panjang bungkus rapi.
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
- [ ] Buka laporan konsultasi di 2 tab/perangkat berbeda sebagai 2
      caregiver (Owner+Editor) untuk anak yang SAMA — di tab pertama,
      preview dulu (mis. dengan section "Riwayat Obat" dicentang); di
      tab KEDUA, tambah/ubah/hapus 1 log obat SETELAH preview tab
      pertama diambil; kembali ke tab pertama, klik Unduh PDF → **409**,
      pesan "Data laporan konsultasi berubah sejak pratinjau dibuat...",
      preview lama TETAP kelihatan (bukan hilang), tombol "Buat
      pratinjau ulang" berfungsi & memulihkan alur normal.
- [ ] Preview, tunggu >15 menit (ATAU restart backend dengan
      `SNAPSHOT_TOKEN_MAX_AGE_SECONDS` sementara diperkecil buat uji
      cepat), lalu coba Unduh PDF — token kedaluwarsa, pesan aman
      "Buat pratinjau ulang" tampil, TIDAK ada stack trace/detail token
      yang bocor ke layar.

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
