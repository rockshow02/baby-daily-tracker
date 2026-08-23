# Smart Insights & Weekly Summary — Phase 1

`GET /children/<child_id>/insights?period=7d|30d` (`routes/insights_routes.py`
+ `utils/insights_engine.py`) — ringkasan **informasional** dari catatan
7/30 hari terakhir seorang anak, plus perbandingan dengan periode
sebelumnya dan sekelompok kecil kartu observasi rule-based.

**Fitur ini BUKAN diagnosis medis.** Tidak ada label
normal/abnormal/berbahaya/terlambat/tidak sehat/aman secara medis di mana
pun di response ini, dan tidak ada machine learning/AI yang terlibat —
semua angka adalah agregat langsung dari catatan yang dimasukkan
caregiver, dan semua kartu insight adalah aturan deterministik yang bisa
dibaca langsung di `utils/insights_engine.py`.

## Kenapa mesin baru, bukan perluasan yang sudah ada

Repo ini sudah punya dua "mesin ringkasan" lain yang **sengaja tidak
diperluas** buat fitur ini, karena domainnya beda:

- `utils/summary_engine.py` — bandingin **1 hari** vs acuan IDAI/AAP
  per usia (dipakai `GET /children/<id>/daily-summary`). Domainnya
  "apakah hari ini sesuai panduan usia", bukan "bagaimana tren 7 hari
  terakhir dibanding minggu sebelumnya".
- `routes/stats_routes.py` (`GET /children/<id>/stats`) — tren N-hari
  buat grafik, **tanpa** perbandingan periode maupun kartu insight, dan
  **sengaja** menghitung sesi tidur yang masih berjalan seolah berakhir
  "sekarang" (`min(log.end_time or now_wib(), end_dt)`) — cocok buat
  grafik hari-per-hari yang harus tetap punya angka buat hari ini, tapi
  **berlawanan** dengan kebijakan modul ini (lihat bagian Sleep di
  bawah). Reuse yang beneran dipakai dari sana: pola query rentang
  tanggal ter-index dan seluruh konvensi timezone WIB.

Endpoint `/insights` yang baru ini punya modul sendiri
(`utils/insights_engine.py`) karena kombinasi kebutuhannya unik:
perbandingan periode, kebijakan nilai-hilang yang ketat, dan kartu
insight allowlist — tidak satu pun dari dua mesin di atas punya bentuk
itu.

## Otorisasi

Semua role yang **punya akses baca** ke anak ini (`owner`/`editor`/
`viewer`, lewat `utils/access.py:get_accessible_child()`) boleh lihat
insight — **tidak ada** yang disembunyikan dari viewer di Phase 1. User
yang **sama sekali tidak** punya akses (bukan owner, bukan caregiver
terdaftar) dapat `404 "Anak tidak ditemukan"` — **persis** pesan yang
sama dengan anak yang benar-benar tidak ada, jadi outsider tidak pernah
bisa membedakan "anak ini ada tapi kamu ditolak" dari "anak ini memang
tidak ada".

Endpoint ini **baca saja**: tidak pernah `db.session.add`/`commit`, jadi
melihat insight tidak pernah mengubah data anak, tidak butuh audit event
(Caregiver Audit Trail cuma mencatat create/update/delete record — lihat
`AUDIT_TRAIL.md`), dan tidak butuh idempotency key (itu cuma buat `POST`
yang bisa diantrikan offline).

## Batas tanggal & timezone

Semua batas hari dihitung dalam **WIB (Asia/Jakarta, UTC+7) lokal**,
BUKAN UTC — konsisten dengan seluruh app ini (`utils/timezone_utils.py`:
kolom timestamp di database sudah tersimpan sebagai wall-clock WIB naive
sejak awal, jadi tidak ada konversi UTC yang bisa memotong hari WIB di
tempat yang salah).

- **Periode sekarang** ("7 hari terakhir termasuk hari ini"):
  `start_date = today - 6 hari`, `end_date = today` (7 hari inklusif).
  Periode `30d` sama persis, cuma `29 hari` bukan `6 hari`.
- **Periode sebelumnya**: persis sepanjang periode sekarang, langsung
  sebelum `start_date` (tidak overlap sama sekali) —
  `prev_end_date = start_date - 1 hari`,
  `prev_start_date = prev_end_date - (days - 1) hari`.
- Batas per-record query pakai rentang **half-open**
  `[start_dt, end_dt_exclusive)` di mana `end_dt_exclusive` = tengah
  malam PERSIS hari setelah `end_date` — bukan `datetime.max`, biar
  catatan yang persis di ujung batas (`00:00:00.000000` di
  `start_date`, atau `23:59:59.999999` di `end_date`) selalu tertangani
  benar tanpa isu presisi.
- `today` dihitung **sekali** di layer route
  (`routes/insights_routes.py:get_insights()` manggil `today_wib()`),
  lalu diteruskan sebagai parameter murni ke seluruh
  `utils/insights_engine.py` — modul itu sendiri **tidak pernah**
  memanggil `datetime.now()`/`today_wib()` sendiri, biar seluruh mesin
  perhitungan gampang dites deterministik (`backend/tests/test_insights.py`
  monkeypatch `routes.insights_routes.today_wib`, bukan memanipulasi jam
  sistem).

## Kebijakan nilai yang hilang

- **Volume menyusui/pumping**: rata-rata **hanya** dihitung dari event
  yang beneran punya `volume_ml` — event tanpa volume **tidak pernah**
  dianggap 0 saat menghitung rata-rata. Jumlah event yang punya nilai
  selalu diekspos terpisah (`events_with_volume`), begitu juga
  totalnya (`total_volume_ml`, yang legitimately 0 kalau memang tidak
  ada satupun yang tercatat).
- **Durasi pumping/aktivitas**: sama persis — cuma event dengan
  `duration_minutes` terisi yang dijumlah; `events_with_duration`/
  `events_with_pumping_duration` diekspos terpisah.
- **Sesi tidur yang belum selesai** (`end_time IS NULL`): **tidak
  pernah** dianggap berakhir "sekarang" untuk total durasi historis —
  ini kebalikan sengaja dari `routes/stats_routes.py`. Sesi begini
  **dikecualikan total** dari `total_completed_minutes`/
  `avg_duration_minutes_per_session`/tren harian, dan dihitung terpisah
  di `unfinished_session_count`.
- **Durasi tidur negatif** (`end_time` sebelum `start_time` — data
  korup/tidak valid, tidak mungkin lewat API normal tapi bisa saja ada
  dari jalur lain seperti migrasi data lama): sesi itu **dikecualikan
  total** dari semua agregat tidur (bukan exception, bukan bikin total
  negatif, bukan dihitung sebagai sesi selesai).
- **Pengukuran pertumbuhan**: perubahan (`weight_change_kg`,
  `height_change_cm`, `head_circumference_change_cm`) **hanya** dihitung
  kalau **kedua** pengukuran pembanding punya nilai field itu — kalau
  salah satu `null`, hasilnya `null` (bukan menebak/menganggap 0).

## Formula perbandingan periode

`comparisons.<metrik>` = `{current, previous, change, percent_change}`,
dihitung dari `utils/insights_engine.py:build_comparison()`:

1. `change = current - previous` (bulat 1 desimal kalau float).
2. `percent_change = (current - previous) / previous * 100`, dibulatkan
   1 desimal — **kecuali** `previous == 0`, maka `percent_change = null`
   (tidak pernah bagi dengan nol, dan tidak pernah direpresentasikan
   sebagai "turun 100%" untuk kasus "belum pernah ada data
   pembanding").
3. `current`/`previous` **selalu** angka mentah (count/sum asli),
   **tidak pernah** placeholder untuk "data hilang" — 0 di sini artinya
   genuinely nol event tercatat pada periode itu.

Metrik yang dibandingkan (dipilih karena "reliable" — total/count murni,
bukan rata-rata yang sebagian datanya bisa hilang):
`feeding_count`, `feeding_volume_ml`, `sleep_duration_minutes`,
`diaper_count`, `pumping_volume_ml`, `activity_duration_minutes`.

**Catatan penting soal "jangan representasikan data hilang sebagai
penurunan 100%"**: aturan ini ditegakkan di **layer kartu insight**
(lihat di bawah — semua rule "menurun" mensyaratkan periode SEKARANG
punya data > 0 buat metrik itu), bukan dengan menyembunyikan angka
mentah di `comparisons`. Kalau periode sekarang genuinely 0 dan periode
sebelumnya > 0, `comparisons.<metrik>.percent_change` tetap menghitung
`-100.0` apa adanya (itu statistik yang benar), TAPI **tidak pernah** ada
kartu `*_decreased` yang digenerate dari situ — jadi tidak ada KLAIM
prosa yang menyesatkan, walau angka mentahnya tetap tersedia buat
tabel/grafik yang ingin menampilkannya secara netral. Frontend Phase 1
**tidak** menyusun kalimat sendiri dari `comparisons` mentah di luar
kartu insight yang sudah di-gate ini.

## Rounding

Rata-rata dan persentase perubahan dibulatkan **1 desimal**
(`utils/insights_engine.py:_round1()`), konsisten di seluruh modul.
Total/count tetap integer/sum mentah, **tidak** dibulatkan. Semua
pemformatan buat manusia (unit, pemisah ribuan, dsb.) dilakukan di
**frontend** — server tidak pernah mengembalikan string berformat.

## Metrik per domain

### Feeding
`total_events`, `avg_events_per_day`, `by_type` (dict 4 kategori
`asi_langsung`/`asi_perah`/`sufor`/`mpasi`, selalu ada walau 0),
`total_volume_ml`, `events_with_volume`, `avg_volume_ml_per_event`
(`null` kalau `events_with_volume == 0`), `daily_trend` (list
`{date, count}`).

### Sleep
`completed_session_count`, `unfinished_session_count`,
`total_completed_minutes`, `avg_duration_minutes_per_session` (`null`
kalau `completed_session_count == 0`), `avg_minutes_per_day`,
`daily_trend` (list `{date, total_minutes}`).

Sesi dianggap "milik" suatu periode berdasarkan `start_time`-nya (BUKAN
di-clip lintas tengah malam seperti `/stats`/`/daily-summary` — presisi
per-hari itu penting buat grafik HARIAN tunggal, tapi untuk agregat
TOTAL 7/30 hari perbedaannya tidak signifikan dan menambah kompleksitas
tanpa manfaat sepadan untuk Phase 1).

### Diaper
`total_events`, `pipis_count`, `bab_count` (keduanya **inklusif**
terhadap `diaper_type='keduanya'` — konsisten dengan konvensi yang
sudah ada di `stats_routes.py`/`daily_log_routes.py`, bukan kebijakan
baru), `combined_count` (jumlah `keduanya` saja), `avg_events_per_day`,
`daily_trend`.

### Pumping
`session_count`, `total_volume_ml`, `events_with_volume`,
`avg_volume_ml_per_event` (`null` kalau tidak ada), `total_duration_minutes`,
`events_with_duration`, `daily_trend` (list `{date, count, volume_ml}`).

### Growth
**Tidak** di-scope ke periode — query `ORDER BY measured_date DESC
LIMIT 2` (efisien walau riwayat pengukurannya panjang), karena
pengukuran pertumbuhan jarang dan "2 terakhir yang beneran ada" jauh
lebih berguna daripada "2 terakhir DALAM 7 hari" yang hampir selalu
kosong. `latest`/`previous` (masing-masing `{measured_date, weight_kg,
height_cm, head_circumference_cm}` atau `null`), 3 field perubahan
(lihat kebijakan nilai hilang di atas), `days_since_latest_measurement`
(`null` kalau belum ada pengukuran sama sekali).

### Health overview — privacy-minimal
**Hanya** count + 1 angka suhu terakhir:
`temperature_record_count` (di-scope periode), `latest_temperature_celsius`
+ `latest_temperature_at` (TIDAK di-scope periode — suhu terakhir yang
BENERAN pernah tercatat, mirror pola growth di atas), `medication_event_count`,
`doctor_visit_count`, `illness_record_count` (ketiganya di-scope periode).
**Tidak pernah** menyertakan nama obat/dosis/nama dokter/nama klinik/
alasan kunjungan/diagnosis/nama penyakit/gejala/catatan bebas apa pun —
lihat bagian Privasi di bawah.

### Activity, mood, milestones
`activity`: `session_count`, `total_duration_minutes`,
`events_with_duration`, `daily_trend`.
`mood`: `counts` (dict 4 kategori terkontrol `ceria`/`baik`/`sedih`/
`menangis`, selalu ada walau 0 — nilai mood di luar 4 ini, kalaupun ada
di data lama, tidak dihitung ke kategori mana pun), `total_events`.
`milestones`: `count_in_period`, `latest_milestone_type` (TIDAK
di-scope periode) + `latest_milestone_date` — **tidak pernah**
`custom_label` (bisa berisi teks bebas apa pun yang caregiver ketik
sendiri).

## Rule-based insight — allowlist & ambang

`insights` = list pendek (maks `MAX_INSIGHT_CARDS = 5`) objek
`{code, severity, metric, direction, value}`. `severity` selalu `"info"`
di Phase 1 (tidak ada `"warning"`/`"critical"` — tidak ada peringatan
alarmis). Urutan rule **tetap** (tidur → menyusui → popok → pumping →
aktivitas → tumbuh kembang) — kalau lebih dari 5 kandidat memenuhi
syarat, yang paling akhir dalam urutan ini yang terpotong duluan
(deterministik, bukan diacak/diprioritaskan berdasar "keparahan").

Kode yang boleh keluar — **allowlist ketat**
(`utils/insights_engine.py:INSIGHT_ALLOWLIST`), harus SELALU disinkronkan
manual dengan peta teks frontend (`frontend/src/utils/insightCodes.js`):

| Kode | Kapan |
|---|---|
| `insufficient_data` | Periode sekarang genuinely tidak punya catatan sama sekali (`data_quality.has_any_data == false`) — **satu-satunya** kartu yang muncul kalau ini terjadi, tidak ada rule lain yang dievaluasi. |
| `sleep_duration_increased` / `_decreased` | `\|Δ total_completed_minutes\| >= 30` menit, DAN periode sekarang punya minimal 1 sesi selesai. Varian "menurun" tambahan mensyaratkan periode sebelumnya juga > 0. |
| `feeding_count_increased` / `_decreased` | `\|Δ total_events\| >= 3` event, gating sama seperti di atas. |
| `diaper_count_increased` / `_decreased` | `\|Δ total_events\| >= 3` event, gating sama. |
| `pumping_volume_increased` / `_decreased` | `\|Δ total_volume_ml\| >= 100` ml, gating sama (pakai `events_with_volume > 0`). |
| `activity_duration_increased` / `_decreased` | `\|Δ total_duration_minutes\| >= 30` menit, gating sama. |
| `growth_no_recent_measurement` | Belum pernah ada pengukuran SAMA SEKALI, atau pengukuran terakhir > 30 hari yang lalu. |

**Semua ambang di atas adalah heuristik produk** (dipilih supaya kartu
tidak berisik untuk variasi kecil yang wajar hari ke hari), **bukan**
ambang klinis/medis apa pun — tidak berasal dari rekomendasi
IDAI/WHO/AAP seperti acuan di `utils/summary_engine.py`/
`utils/growth_calc.py`, dan tidak boleh dibaca seolah begitu.

**Kenapa rule "menurun" mensyaratkan `previous > 0`, tapi rule
"meningkat" tidak**: naik dari 0 ke sesuatu adalah observasi valid
(caregiver baru mulai mencatat, atau memang aktivitasnya baru mulai).
Sebaliknya, "menurun" dari periode yang **sendirinya** tidak punya data
pembanding bukan tren beneran — itu cuma artefak "belum pernah dicatat
sebelumnya". Dan setiap rule (naik maupun turun) mensyaratkan periode
**sekarang** > 0 untuk metrik itu, supaya 0 di periode sekarang (yang
kemungkinan besar cuma berarti "belum sempat dicatat") tidak pernah
diklaim sebagai "menurun" (lihat juga bagian Formula Perbandingan di
atas).

## Kontrak API

```
GET /api/children/<child_id>/insights?period=7d
```

- `period` opsional, default `7d`. Nilai lain yang didukung: `30d`.
  Nilai apa pun di luar itu (termasuk kosong-tapi-eksplisit atau typo)
  → `400`.
- Auth: header `Authorization: Bearer <token>`, sama seperti endpoint
  lain.
- Sukses → `200` dengan body:

```json
{
  "child_id": 1,
  "period": {
    "key": "7d", "start_date": "2026-08-17", "end_date": "2026-08-23",
    "timezone": "Asia/Jakarta", "days": 7
  },
  "previous_period": { "start_date": "2026-08-10", "end_date": "2026-08-16" },
  "metrics": { "feeding": {...}, "sleep": {...}, "diaper": {...}, "pumping": {...}, "growth": {...}, "health": {...}, "activity": {...}, "mood": {...}, "milestones": {...} },
  "comparisons": { "feeding_count": {...}, "feeding_volume_ml": {...}, "sleep_duration_minutes": {...}, "diaper_count": {...}, "pumping_volume_ml": {...}, "activity_duration_minutes": {...} },
  "insights": [ { "code": "sleep_duration_increased", "severity": "info", "metric": "sleep_duration_minutes", "direction": "up", "value": 45 } ],
  "data_quality": { "has_any_data": true, "days_with_records": 5, "missing_volume_count": 2, "unfinished_sleep_count": 1 },
  "generated_at": "2026-08-23T01:00:00Z",
  "request_id": "..."
}
```

- Anak tidak ada / tidak bisa diakses → `404`.
- Belum login → `401`.
- Periode tidak didukung → `400`.

`data_quality.days_with_records` = jumlah tanggal unik dalam periode
yang punya minimal 1 catatan dari salah satu domain harian (feeding/
sleep/diaper/pumping/activity/mood — growth/health/milestones tidak
ikut dihitung di sini karena bukan catatan harian). `missing_volume_count`
= `feeding.total_events - feeding.events_with_volume`.
`unfinished_sleep_count` = `sleep.unfinished_session_count`.

## Migrasi database

**Tidak ada migrasi skema yang dibutuhkan.** Endpoint ini murni membaca
tabel-tabel yang sudah ada (`feeding_logs`, `sleep_logs`, `diaper_logs`,
`pumping_logs`, `growth_measurements`, `temperature_logs`,
`medication_logs`, `doctor_visit_logs`, `illness_logs`, `activity_logs`,
`mood_logs`, `milestone_logs`) — tidak ada kolom baru, tabel baru,
ataupun tabel ringkasan tersendiri (data selalu dihitung ulang saat
diminta, bukan disimpan; lihat bagian Performa).

## Performa & query

- Setiap query di-scope ke `child_id` yang sudah divalidasi otorisasinya
  duluan, dan memakai kolom `timestamp`/`start_time`/`measured_date`
  yang **sudah** ter-index (lihat `models.py` — semua kolom ini
  `index=True`).
- Jumlah query per request **tetap kecil dan konstan**, tidak
  proporsional terhadap jumlah catatan anak (tidak ada pola N+1) —
  kira-kira 20 query tetap: 6 metrik × 2 periode (sekarang + sebelumnya,
  minus growth/health/milestones yang cuma dihitung sekali) + growth
  (`LIMIT 2`) + health (5 query kecil) + milestones (2 query). Dites di
  `backend/tests/test_insights.py:test_no_n_plus_one_query_regression`
  dengan 60 baris seed.
- Growth cukup 2 baris terakhir (`ORDER BY ... DESC LIMIT 2`), bukan
  memuat seluruh riwayat pertumbuhan.
- Tidak ada endpoint di sini yang memuat riwayat lifetime penuh cuma
  buat menghitung 7 hari — semua query dibatasi rentang tanggal.

## Cache offline frontend

Lihat bagian "Offline cache" di `frontend/src/utils/insightCache.js`
(disalin ringkasannya di sini buat referensi cepat):

- Snapshot **terakhir yang berhasil** (per periode yang terakhir
  diminta) disimpan di `localStorage`, di-namespace per
  **`(userId, childId)`** — 1 slot, ditimpa setiap fetch online sukses.
- Key menyertakan `schemaVersion` eksplisit — versi yang tidak dikenal/
  hilang ditolak dengan aman (dianggap "tidak ada cache"), bukan ditebak
  bentuknya.
- Payload yang dicache **persis** payload yang backend kembalikan — TIDAK
  ADA filtering tambahan yang perlu dilakukan di frontend, karena kontrak
  privasi sudah ditegakkan penuh di server (lihat bagian Privasi di
  bawah dan test privasi backend).
- Dihapus otomatis: (a) saat logout (bareng cache profil/anak lain,
  `AuthContext.jsx:clearSession()`), (b) saat revalidasi daftar anak
  online menemukan anak yang cache insight-nya ada tapi anaknya sudah
  tidak lagi bisa diakses user ini (`App.jsx:loadChildren()` memanggil
  `pruneInsightCacheToAccessibleChildren()`).
- **Tidak pernah** masuk antrian sinkron offline (`utils/offlineQueue.js`)
  — ini `GET`, bukan mutasi, jadi tidak relevan buat retry/replay.

## Privasi

Field berikut **tidak pernah** muncul di response endpoint ini (baik di
`metrics` maupun di mana pun), ditegakkan langsung di
`utils/insights_engine.py` (setiap fungsi `compute_*` cuma mengembalikan
count/angka/kategori terkontrol, tidak pernah kolom teks bebas):

notes, symptoms, diagnosis, nama obat, dosis, nama dokter/klinik,
`custom_label` milestone, email user, detail keanggotaan caregiver, kode
undangan, chat ID Telegram, token, isi request mentah.

Diverifikasi lewat test regresi privasi (`backend/tests/test_insights.py:
test_full_serialized_response_contains_no_seeded_sensitive_values`) yang
men-serialize **seluruh** response dan memastikan nilai sensitif yang
di-seed tidak muncul di mana pun di string JSON-nya — bukan cuma
memeriksa field yang "diketahui", biar bug di masa depan yang
menambahkan field baru sembarangan tetap tertangkap.

## Batasan Phase 1 (diketahui, sengaja belum dikerjakan)

- Tidak ada agregasi lintas-anak (1 request = 1 anak).
- `30d` memakai struktur & rule ambang **yang sama persis** dengan `7d`
  (cuma `days=30`) — tidak ada rule/ambang khusus 30-hari yang berbeda.
- Perbandingan periode SELALU membandingkan periode yang dipilih dengan
  periode setara persis sebelumnya (7 vs 7, atau 30 vs 30) — tidak ada
  mode "7 hari ini vs 30 hari lalu" atau semacamnya.
- Tidak ada personalisasi/pembelajaran dari perilaku user — rule-nya
  tetap sama untuk semua anak/user.
