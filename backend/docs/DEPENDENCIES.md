# Dependency Maintenance — HTTP stack (`requests` dan sekitarnya)

## Root cause `RequestsDependencyWarning`

`requests` (di versi lama yang kepasang, `2.32.3`) menjalankan pengecekan
kompatibilitas internal (`check_compatibility()` di `requests/__init__.py`)
tiap kali dia di-import. Kalau `chardet` ke-import (nggak peduli apakah
`requests` beneran makein atau nggak), `requests` 2.32.3 cuma nerima versi
`chardet` di rentang `>=3.0.2, <6.0.0`.

`chardet` yang kepasang di environment ini adalah **`7.4.3`** — di ATAS
batas `6.0.0` itu — jadi pengecekannya gagal dan `requests` nge-warn:

```
RequestsDependencyWarning: urllib3 (2.7.0) or chardet (7.4.3)/charset_normalizer (3.4.9)
doesn't match a supported version!
```

`pip check` nggak nangkep ini sebagai masalah karena `reportlab` (lihat di
bawah) nggak nge-pin batas atas versi `chardet` sama sekali di metadata-nya
— jadi secara metadata pip, kombinasinya "valid". Peringatannya murni dari
pengecekan RUNTIME internal `requests`, bukan dari resolusi dependency pip.

## Kenapa `chardet` ke-install (bukan dependency langsung app ini)

```
$ pip show chardet
...
Required-by: reportlab
```

`chardet` adalah dependency TRANSITIF dari `reportlab` (dipakai buat
ekspor laporan PDF anak — `routes/report_routes.py`), BUKAN dependency
langsung project ini, BUKAN sisa install manual, dan BUKAN package sistem
PythonAnywhere. `reportlab==4.2.5` punya `Requires-Dist: chardet` TANPA
batasan versi apa pun di metadata-nya, dan beneran makein `chardet` (bukan
cuma dideklarasikan doang) di `reportlab/lib/rparsexml.py` buat deteksi
encoding XML.

Aplikasi ini sendiri **tidak pernah** `import chardet` secara langsung —
semua kode yang benar-benar bikin HTTP request (`utils/telegram.py`,
`scripts/import_piyolog.py`) makein `requests`, yang dari sisi `requests`
sendiri cuma butuh `charset-normalizer` (bukan `chardet`) buat deteksi
encoding respons HTTP.

## Solusi yang dipilih

**Upgrade `requests` ke `2.34.2`** — versi ini melebarkan batas atas
pengecekan `chardet` dari `<6.0.0` jadi **`<8.0.0`** (lihat commit
[`psf/requests`](https://github.com/psf/requests) `HISTORY.md`, dan source
`check_compatibility()` di versi ini). `chardet 7.4.3` yang udah kepasang
sekarang jatuh PAS di rentang `[3.0.2, 8.0.0)` yang baru itu — jadi
peringatannya ilang **tanpa** perlu:

- menghapus `chardet` (dia beneran dipakai `reportlab`, bukan sisa/nggak
  perlu — lihat bagian di atas),
- menurunkan `chardet` ke versi lama yang mungkin punya bug/CVE yang udah
  dibenerin di versi baru,
- atau nyuppress peringatannya secara paksa.

Kombinasi final yang di-pin eksplisit di `requirements.txt` (dan
diverifikasi reproducible di venv baru — lihat "Cara verifikasi" di
bawah):

| Package             | Versi lama | Versi baru | Kenapa |
|----------------------|-----------|-----------|--------|
| `requests`           | 2.32.3    | **2.34.2** | Melebarkan batas kompatibilitas `chardet` ke `<8.0.0`; juga membawa 2 perbaikan keamanan (lihat di bawah) |
| `urllib3`             | (nggak dipin, resolve 2.7.0) | **2.7.0** (dipin) | Sudah versi terbaru & dalam rentang yang didukung `requests` 2.34.2 (`<3,>=1.26`) — nggak diubah, cuma dipin buat reproducibility |
| `charset-normalizer`  | (nggak dipin, resolve 3.4.9) | **3.4.9** (dipin) | Dalam rentang yang didukung `requests` 2.34.2 (`<4,>=2`) — nggak diubah, cuma dipin |
| `idna`                | (nggak dipin, resolve 3.18) | **3.18** (dipin) | Dalam rentang yang didukung `requests` 2.34.2 (`<4,>=2.5`) — nggak diubah, cuma dipin |
| `certifi`             | (nggak dipin, resolve terbaru) | **2026.7.22** (dipin) | Dalam rentang yang didukung `requests` 2.34.2 (`>=2023.5.7`) — nggak diubah, cuma dipin |
| `chardet`             | (nggak dipin, dependency transitif `reportlab`) | **7.4.3** (dipin eksplisit) | Genuinely dibutuhkan `reportlab` (lihat di atas) — dipin biar versi yang ke-resolve nggak diam-diam naik ke `>=8.0.0` di masa depan dan bikin warning ini balik lagi |

**`chardet` TETAP ADA di environment ini** (bukan dihapus) — itu keputusan
yang BENAR di sini, karena dia genuinely dibutuhkan `reportlab`, bukan
sisa yang bisa dihapus aman. `chardet` di-pin eksplisit di
`requirements.txt` justru buat MENCEGAH warning ini balik lagi kalau
suatu saat `pip install` narik `chardet>=8.0.0` secara otomatis.

### Dasar kompatibilitas resmi

Dicek langsung dari metadata PyPI (`pip index versions`,
`pip download --no-deps` + baca `METADATA`/source wheel) dan
`HISTORY.md` GitHub `psf/requests`, BUKAN cuma nebak versi buat
nyuprress warning:

- `requests 2.34.2` metadata: `Requires-Python: >=3.10`, dan classifier
  eksplisit nyebut Python `3.10`–`3.15` didukung. **Kompatibel sama
  Python 3.10.12 di PythonAnywhere.**
- `requests 2.34.2` `Requires-Dist`: `charset_normalizer<4,>=2`,
  `idna<4,>=2.5`, `urllib3<3,>=1.26`, `certifi>=2023.5.7` — SEMUA versi
  yang kepasang sekarang (urllib3 2.7.0, charset-normalizer 3.4.9, idna
  3.18, certifi 2026.7.22) ada DI DALAM rentang ini.
- Source `check_compatibility()` di `requests` 2.34.2 (dicek langsung
  dari isi wheel-nya): batas `chardet` dilebarkan jadi
  `(3, 0, 2) <= version < (8, 0, 0)` — `chardet 7.4.3` masuk.

### Catatan keamanan (antara `requests` 2.32.3 → 2.34.2)

Dari `HISTORY.md`/GitHub Releases resmi `psf/requests`:

- **`2.32.4`** — perbaikan **CVE-2024-47081**: URL yang sengaja dibikin
  jahat + environment tertentu bisa bikin `requests` ambil kredensial
  buat hostname/mesin yang SALAH dari file `.netrc`. Ini relevan buat
  app ini karena `utils/telegram.py` dan `scripts/import_piyolog.py`
  sama-sama bikin outbound HTTP request pakai `requests`.
- **`2.33.0`** — perbaikan **CVE-2026-25645**:
  `requests.utils.extract_zipped_paths` sekarang ekstrak ke lokasi
  non-deterministik biar nggak bisa ditimpa file jahat. App ini TIDAK
  pernah manggil `extract_zipped_paths` langsung, jadi CVE ini nggak
  langsung berdampak — tapi upgrade ke versi yang udah ada
  perbaikannya tetap lebih aman daripada tetap di versi lama.

Jadi upgrade ini BUKAN cuma nghilangin warning — dia juga nutup 2 CVE
yang genuinely relevan/berpotensi relevan buat app ini. Nggak ada
downgrade atau regresi keamanan di paket manapun yang disentuh.

## Kenapa TIDAK nyuppress warning-nya

Peringatan ini nunjukin kombinasi dependency yang beneran nggak
disupport `requests` — nyuppress-nya (lewat `warnings.filterwarnings`,
`pytest.ini` `filterwarnings`, import wrapper, atau monkeypatch
`check_compatibility`) cuma nyembunyiin GEJALA-nya, bukan benerin
penyebabnya, dan bisa nyembunyiin masalah kompatibilitas SUNGGUHAN di
masa depan (mis. `urllib3` versi baru yang beneran nggak kompatibel).
`backend/pytest.ini` yang sebelumnya punya
`filterwarnings = ignore::requests.exceptions.RequestsDependencyWarning`
sudah **dihapus** — sekarang nggak perlu lagi karena akar masalahnya
udah kebenerin, bukan ketutup.

## Cara verifikasi

### Verifikasi cepat (robust, di Python manapun)

```bash
python -c "
import warnings
with warnings.catch_warnings():
    warnings.simplefilter('error')
    import requests
    print('requests', requests.__version__, '- imported cleanly, no warning')
"
python -m pip check
```

### Catatan soal `python -W error::requests.exceptions.RequestsDependencyWarning`

Command ini (dan bentuk env var `PYTHONWARNINGS=error::...`) **secara
konsisten gagal me-resolve category dotted-name buat warning class
milik package pihak ketiga yang belum sempat ke-import** di CPython
3.13.3 yang dipakai buat development lokal di sesi ini — Python
nyetak `Invalid -W option ignored: invalid module name: '...'` ke
stderr dan MELEWATIN filter itu (bukan meng-crash, tapi juga BUKAN
berarti "terverifikasi nggak ada warning" — filter-nya emang nggak
kepasang sama sekali). Ini keterbatasan CPython yang udah dikonfirmasi
lewat pengujian langsung (`warnings._getcategory()` yang dipanggil dari
DALAM proses Python yang jalan berhasil resolve category yang SAMA
persis — jadi bukan soal nama classnya salah, tapi soal kapan `-W`
diproses relatif ke import third-party package), BUKAN bug di fix
dependency ini.

**Selalu pakai bentuk `warnings.catch_warnings()` in-process di atas
buat verifikasi definitif** — itu yang dipakai buat validasi fix ini
(dikonfirmasi BENERAN nangkep warning-nya kalau `requests` sengaja
diturunin balik ke `2.32.3`, dan BENERAN nggak nangkep apa-apa di
`2.34.2`).

### Verifikasi lengkap (venv baru, reproduksi dari nol)

```bash
cd backend
python -m venv /path/sementara/venv-baru
/path/sementara/venv-baru/bin/python -m pip install --upgrade pip
/path/sementara/venv-baru/bin/python -m pip install -r requirements-dev.txt
/path/sementara/venv-baru/bin/python -m pip freeze   # harus persis sama kombinasi versi di atas
/path/sementara/venv-baru/bin/python -m pip check     # harus "No broken requirements found."
/path/sementara/venv-baru/bin/python -m pytest         # harus semua lolos, TANPA baris RequestsDependencyWarning di ringkasan warning
```

## Batasan pengujian Python 3.10 di sesi ini

Production PythonAnywhere pakai **Python 3.10.12**. Environment
development yang dipakai buat mengerjakan fix ini cuma punya
**Python 3.13** ke-install (Docker Desktop ada tapi daemon-nya nggak
jalan, jadi nggak bisa dipakai buat spin up container Python 3.10).
Kompatibilitas Python 3.10 buat `requests 2.34.2` makanya **divalidasi
lewat metadata resmi PyPI** (`Requires-Python: >=3.10`, classifier
eksplisit nyebut `3.10`), BUKAN lewat eksekusi langsung di Python
3.10.12. Kalau memungkinkan, jalankan ulang langkah "Verifikasi
lengkap" di atas pakai Python 3.10 (lokal atau di PythonAnywhere
sendiri, TANPA nge-apply ke virtualenv production dulu) buat konfirmasi
tambahan sebelum upgrade production beneran.

## Langkah upgrade PythonAnywhere (JANGAN dijalankan otomatis — manual, operator yang mutusin kapan)

`pip install -r requirements.txt` biasa **TIDAK** menghapus package yang
udah kepasang duluan di environment tapi udah nggak ada di
`requirements.txt` (di kasus ini nggak relevan karena `chardet` TETAP
ada di `requirements.txt`, tapi tetap penting diketahui buat maintenance
selanjutnya).

```bash
cd ~/baby-daily-tracker/backend
source ~/.virtualenvs/babytracker-venv/bin/activate

# 1. cek dulu state SEKARANG sebelum apa-apa
python -m pip show requests urllib3 chardet charset-normalizer idna certifi
python -m pip check

# 2. upgrade ke kombinasi yang udah tervalidasi
python -m pip install --upgrade -r requirements.txt

# 3. verifikasi — HARUS nggak ada RequestsDependencyWarning, HARUS pip check bersih, HARUS semua test lolos
python -c "
import warnings
with warnings.catch_warnings():
    warnings.simplefilter('error')
    import requests
    print('requests', requests.__version__, '- no warning')
"
python -m pip check
python -m pytest
```

Kalau nanti (di masa depan) ternyata `chardet` beneran udah nggak
dibutuhkan lagi (mis. `reportlab` di-upgrade ke versi yang nggak
minta `chardet` lagi), baru aman jalanin:

```bash
python -m pip uninstall -y chardet
python -m pip install --upgrade -r requirements.txt
```

**JANGAN** jalanin `pip uninstall -y chardet` selama `reportlab` masih
di `requirements.txt` dengan dependency `chardet`-nya — itu bakal
bikin ekspor PDF (`report_routes.py`) berisiko error di runtime kalau
kebetulan kena code path yang makein `chardet` (`rparsexml.py`).

### Rollback (kalau upgrade di atas bermasalah)

Set kombinasi versi balik ke yang lama secara eksplisit (BUKAN nebak),
lalu reload web app:

```bash
python -m pip install \
  "requests==2.32.3" \
  "urllib3==2.7.0" \
  "charset-normalizer==3.4.9" \
  "idna==3.18" \
  "certifi==2026.7.22" \
  "chardet==7.4.3"
python -m pip check
python -m pytest
```

(Rollback ini SENGAJA cuma balikin versi `requests`-nya doang ke
`2.32.3` — package lain di daftar itu sama persis kayak versi baru,
soalnya emang nggak diubah oleh fix ini. Peringatan `RequestsDependencyWarning`
bakal MUNCUL LAGI setelah rollback ini — itu ekspektasi normal, bukan
tanda ada yang salah sama langkah rollback-nya.)

Restart/reload web app PythonAnywhere dari tab "Web" setelah salah satu
dari 2 langkah di atas (upgrade ATAU rollback), biar proses WSGI yang
lagi jalan makein package versi yang baru diinstall.
