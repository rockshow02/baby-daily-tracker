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
