# Backup & Restore Database (SQLite) — Manual

Backend ini pakai SQLite lokal (lihat `config.py`). PythonAnywhere free tier
**tidak punya scheduled task**, jadi backup di sini **selalu dipicu manual**
dari Bash console — bukan kekurangan fitur, tapi keputusan desain: jangan
pernah nebak-nebak jadwal otomatis, biar operator yang mutusin kapan backup
dijalankan.

Semua perintah di dokumen ini aman dijalankan **sementara aplikasi web masih
hidup** (backup pakai [SQLite Backup
API](https://www.sqlite.org/backup.html) lewat `sqlite3.Connection.backup()`
Python, bukan `cp` file mentah-mentah yang bisa nyalin file di tengah
transaksi nulis dan menghasilkan file korup).

Script-nya ada di:

- `backend/scripts/backup_database.py` — backup, list, verify, prune
- `backend/scripts/restore_database.py` — restore (destruktif, banyak pengaman)
- `backend/scripts/db_backup_common.py` — modul bersama (jangan dijalankan langsung)

## 1. Setup sekali di awal

```bash
cd ~/baby-daily-tracker/backend
source ~/.virtualenvs/babytracker-venv/bin/activate
```

Folder tujuan backup default: `~/database-backups` (di LUAR folder repo git,
dan di luar direktori `backend/` — backup **tidak pernah** otomatis
tersimpan di dalam repo, dan **tidak boleh** di-commit ke Git). Bisa
di-override dengan:

- flag `--backup-dir /path/lain`, atau
- environment variable `DATABASE_BACKUP_DIR`

### Kenapa folder backup HARUS folder khusus (bukan folder sembarangan)

`--prune --apply` menghapus file berdasarkan POLA NAMA (`tracker-<env>-
<timestamp>.db`) di dalam folder yang dikonfigurasi. Kalau folder itu
kebetulan folder yang luas/sensitif — home directory, root repo, folder
`instance/` tempat database aktif hidup, dst — risiko salah hapus jadi
jauh lebih besar, walau pola namanya sendiri udah spesifik.

Karena itu, `--backup-dir` (dan env var `DATABASE_BACKUP_DIR`) **selalu**
divalidasi lewat `validate_backup_directory()` di setiap operasi (backup,
list, verify, restore, prune dry-run, prune apply) — bukan cuma sekali di
level CLI. Yang **ditolak**:

- Root filesystem (`/` di Linux/macOS, drive root kayak `C:\` di Windows)
- Home directory operator itu sendiri (`~`)
- Root repository (`baby-daily-tracker/`)
- Root folder `backend/`
- Folder `backend/instance/` (tempat `tracker.db` hidup)
- Folder induk database aktif, dan path database aktif itu sendiri
- Symlink yang RESOLVE ke salah satu lokasi di atas
- Placeholder environment variable yang belum ter-substitusi (mis. literal
  `$HOME`, `${HOME}`, `%USERPROFILE%` di `.env` — python-dotenv nggak
  melakukan shell expansion, jadi nilai itu bakal kepake APA ADANYA kalau
  nggak divalidasi)
- Path yang ternyata sebuah file biasa, bukan folder

Folder khusus di BAWAH lokasi-lokasi itu (mis. `~/database-backups` atau
`~/database-backups/staging`) **tetap valid** — yang ditolak cuma lokasi
luas itu PERSIS, bukan semua yang ada di bawahnya.

## 2. Manual backup

```bash
cd ~/baby-daily-tracker/backend
source ~/.virtualenvs/babytracker-venv/bin/activate
python scripts/backup_database.py --environment staging
```

Untuk akun production, ganti jadi `--environment production`. Kalau
`--environment` nggak dikasih, script coba deteksi dari environment variable
`BACKUP_ENVIRONMENT` / `FLASK_ENV`, fallback ke `local`.

Yang terjadi di belakang layar:

1. Load Flask app lewat `create_app()` yang sudah ada (bukan koneksi baru
   yang di-hardcode) — path database aktif diambil dari `db.engine.url`.
2. Pastikan itu benar SQLite, file-nya beneran ada, dan path-nya aman
   (bukan `/`, `$HOME`, root repo, atau `:memory:`).
3. Salin database pakai SQLite Backup API ke file **sementara** di folder
   backup.
4. Jalankan `PRAGMA integrity_check` terhadap file sementara itu.
5. **Baru** kalau integrity check `ok`, file sementara di-rename atomic
   jadi nama final `tracker-<environment>-<timestamp>.db`.
6. Kalau ada langkah manapun gagal, cuma file sementaranya yang dihapus —
   database sumber **tidak pernah** disentuh/dimodifikasi.

Contoh output:

```
Backup berhasil.
  Sumber database   : /home/xaleena/baby-daily-tracker/backend/instance/tracker.db
  File backup       : /home/xaleena/database-backups/tracker-staging-20260822-213000.db
  Environment       : staging
  Timestamp         : 20260822-213000
  Ukuran            : 262144 bytes
  Integrity check   : ok
  SHA-256           : 9f8c...
  Metadata          : /home/xaleena/database-backups/tracker-staging-20260822-213000.db.json
```

File metadata `.json` di sebelahnya (opsional, ikut dibuat otomatis) cuma
berisi nama file, timestamp, environment, jumlah tabel, ukuran, dan checksum
SHA-256 — **tidak pernah** berisi baris data, username/email user aplikasi,
password, atau token.

## 3. List backup

```bash
python scripts/backup_database.py --list
```

Nampilin nama file, environment, timestamp, ukuran, dan apakah metadata-nya
ada — **tidak pernah** membuka/menampilkan isi database. File lain yang
nyasar di folder backup (bukan hasil script ini) otomatis diabaikan.

## 4. Verifikasi backup

```bash
python scripts/backup_database.py \
  --verify ~/database-backups/tracker-staging-20260822-213000.db
```

Menjalankan `PRAGMA integrity_check` + membandingkan checksum SHA-256 (kalau
ada file metadata-nya). File yang dicek **wajib** ada di dalam folder backup
yang dikonfigurasi — kalau menunjuk ke luar folder itu, ditolak (kecuali
sengaja pakai `--allow-outside-backup-dir`, hati-hati).

## 5. Retensi / pruning (opsional, manual)

**Selalu tunjuk folder backup khusus secara eksplisit** (jangan andalkan
default kalau kamu nggak yakin `DATABASE_BACKUP_DIR` ke-set dengan benar)
— path yang direkomendasikan di PythonAnywhere:

```text
/home/xaleena/database-backups
```

Cek dulu (WAJIB) — dry-run, TIDAK menghapus apa pun:

```bash
python scripts/backup_database.py \
  --backup-dir /home/xaleena/database-backups \
  --prune --keep 10
```

**Baca daftar "Akan dihapus (proyeksi)" di outputnya baik-baik** sebelum
lanjut — itu daftar PERSIS file yang bakal kehapus kalau kamu jalanin ulang
dengan `--apply`. Kalau daftarnya keliatan aneh (lebih banyak dari
dugaan, atau ada nama yang nggak dikenal), BERHENTI dan investigasi dulu
sebelum lanjut ke langkah berikutnya.

Baru setelah dicek, beneran hapus:

```bash
python scripts/backup_database.py \
  --backup-dir /home/xaleena/database-backups \
  --prune --keep 10 \
  --apply
```

Aturan:

- `--keep` **wajib minimal 1** (`--keep 0` atau negatif ditolak, baik di
  level CLI maupun di dalam `prune_backups()` sendiri) — selalu ada
  setidaknya 1 backup yang dipertahankan eksplisit dalam 1 kali jalan.
- Backup **terbaru** tidak pernah dihapus, apa pun nilai `--keep`.
- Hanya beroperasi di dalam folder backup yang SUDAH tervalidasi (lihat
  bagian "Kenapa folder backup HARUS folder khusus" di atas), dan hanya
  menyentuh file yang cocok pola nama `tracker-<environment>-<timestamp>.db`
  hasil script ini sendiri — divalidasi ULANG tepat sebelum tiap file
  beneran dihapus (bukan cuma sekali di awal), buat jaga-jaga kalau ada
  yang berubah di folder itu di antara pengecekan awal dan eksekusi.
- **Dry-run TIDAK PERNAH menghapus apa pun** — laporannya membedakan
  jelas antara `existing` (semua backup yang ADA sekarang), `to_delete`
  (proyeksi yang AKAN dihapus), dan `remaining_after_apply` (proyeksi sisa
  KALAU seandainya di-apply). Kalau `--apply` beneran dipakai, laporannya
  cuma menyebut file yang **BENERAN** berhasil terhapus sebagai "dihapus"
  — bukan daftar yang cuma "akan" dihapus.
- Kalau penghapusan gagal di tengah jalan (mis. 1 file gagal dihapus),
  script berhenti di situ dan melaporkan dengan jujur file mana yang
  SUDAH terlanjur terhapus dan mana yang nggak — bukan pura-pura semuanya
  berhasil atau semuanya gagal.
- Penghapusan **tidak bisa dipulihkan** (bukan masuk trash/recycle bin) —
  makanya default-nya dry-run dan butuh `--apply` eksplisit.

Kalau nggak mau pakai fitur ini sama sekali, retensi manual paling
sederhana: cukup jalankan `--list` dari waktu ke waktu dan hapus file `.db` +
`.json` sepasangnya secara manual lewat `rm` untuk backup lama yang sudah
tidak diperlukan.

## 6. Prosedur restore

**Restore itu operasi DESTRUKTIF — menimpa database aktif.** Ikuti urutan
ini, jangan diloncat:

### 6.1 Sebelum mulai

1. **Konfirmasi environment PythonAnywhere yang benar.** Pastikan kamu
   login ke akun/console yang tepat (staging vs production beda akun/beda
   Bash console) — restore yang salah environment adalah cara paling gampang
   kehilangan data akun yang salah.
2. **Bikin/download backup tambahan dulu** kalau backup terakhir sudah agak
   lama:
   ```bash
   python scripts/backup_database.py --environment staging
   ```
3. **Stop atau reload web app** di tab "Web" PythonAnywhere untuk
   environment ini kalau memungkinkan, biar nggak ada request lain yang
   nulis ke database selagi di-restore.

### 6.2 Jalankan restore

```bash
cd ~/baby-daily-tracker/backend
source ~/.virtualenvs/babytracker-venv/bin/activate

python scripts/restore_database.py \
  --backup ~/database-backups/tracker-staging-20260822-213000.db \
  --environment staging
```

Script ini otomatis, berurutan:

1. Validasi path backup (harus di dalam folder backup, bukan folder/symlink
   yang nunjuk keluar).
2. `PRAGMA integrity_check` terhadap backup yang dipilih.
3. Verifikasi checksum SHA-256 kalau ada file metadata-nya.
4. Cocokkan environment backup (dari metadata atau nama file) dengan
   `--environment` yang diminta — **beda environment = ditolak**, kecuali
   sengaja pakai `--override-environment-mismatch` (HATI-HATI).
5. **Otomatis bikin 1 backup baru** dari kondisi database aktif SEKARANG
   (safety backup) — jadi walau salah pilih file restore, kondisi sebelum
   restore tetap ada.
6. Nampilin ringkasan (sumber backup, target, environment, lokasi safety
   backup) dan minta kamu **ngetik persis**:
   ```
   RESTORE staging
   ```
   Ketikan lain apa pun (termasuk "y"/"yes") membatalkan restore tanpa
   mengubah apa pun.
7. Salin backup tervalidasi ke file sementara, verifikasi ulang, baru
   `os.replace()` atomic ke path database aktif (permission file asli
   dipertahankan kalau memungkinkan).
8. Verifikasi ulang database aktif SETELAH diganti.

Kalau langkah replace gagal di tengah jalan, database aktif **tidak
berubah** (atomic — gagal di tengah = tidak berubah), dan safety backup dari
langkah 5 tetap ada buat investigasi.

### 6.3 Setelah restore

1. Reload web app di tab "Web" PythonAnywhere.
2. Panggil `GET /api/health` — pastikan balikan `{"status": "ok"}`.
3. Lakukan smoke test **read-only** lewat aplikasi (login, lihat riwayat 1
   anak) — jangan langsung mencatat data baru sebelum yakin restore-nya
   benar.
4. **Simpan dulu safety backup** (jangan langsung dihapus) sampai kamu
   yakin restore-nya berhasil dan datanya benar.

## 7. Download backup ke perangkat lain (WAJIB buat disaster recovery)

Backup yang **cuma** tersimpan di akun PythonAnywhere yang sama **bukan**
disaster recovery yang memadai — kalau akun PythonAnywhere-nya sendiri
bermasalah (kehapus, kena suspend, disk penuh, dst), backup yang ada di
situ juga ikut nggak bisa diakses.

Download berkala ke perangkat/penyimpanan lain, misalnya:

- **Lewat tab "Files" PythonAnywhere**: buka `~/database-backups/`, klik
  file `.db` yang mau diunduh, pilih Download.
- **Lewat `scp`/`rsync`** dari komputer lokal (kalau akun PythonAnywhere
  kamu punya akses SSH):
  ```bash
  scp xaleena@ssh.pythonanywhere.com:~/database-backups/tracker-staging-*.db ./local-backups/
  ```

Jangan commit file backup ke Git (lihat `.gitignore` — folder
`database-backups/` sudah diabaikan sebagai jaring pengaman tambahan, tapi
lokasi defaultnya memang di luar folder repo dari awal).

## 8. Verifikasi lokal manual (bukan lewat pytest)

Dokumentasi ini juga bisa dicoba langsung pakai database SQLite sementara —
**jangan pernah** mencoba restore ke database development biasa kamu
(`instance/tracker.db`).

```bash
cd ~/baby-daily-tracker/backend  # atau lokal di komputer kamu
source ~/.virtualenvs/babytracker-venv/bin/activate  # atau venv lokal

# 1. bikin database SQLite sementara + folder backup sementara
python - <<'PY'
import sqlite3, tempfile, os
d = tempfile.mkdtemp()
db = os.path.join(d, "smoke.db")
conn = sqlite3.connect(db)
conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, val TEXT)")
conn.execute("INSERT INTO t (val) VALUES ('hello')")
conn.commit()
conn.close()
print("DB      :", db)
print("BACKUPS :", os.path.join(d, "backups"))
PY

# 2. arahkan app ke database sementara itu (GANTI path sesuai output di atas)
export DATABASE_URL="sqlite:////path/dari/output/di/atas/smoke.db"
export DATABASE_BACKUP_DIR="/path/dari/output/di/atas/backups"

# 3. backup
python scripts/backup_database.py --environment local

# 4. verifikasi
python scripts/backup_database.py --list
python scripts/backup_database.py --verify "$DATABASE_BACKUP_DIR/<nama-file-backup>.db"

# 5. ubah database sementara (simulasikan perubahan yang mau dibatalkan)
python - <<'PY'
import sqlite3, os
conn = sqlite3.connect(os.environ["DATABASE_URL"].replace("sqlite:///", ""))
conn.execute("INSERT INTO t (val) VALUES ('perubahan yang mau dibatalkan')")
conn.commit()
conn.close()
PY

# 6. restore (konfirmasi interaktif — ketik persis "RESTORE local")
python scripts/restore_database.py \
  --backup "$DATABASE_BACKUP_DIR/<nama-file-backup>.db" \
  --environment local

# 7. hapus HANYA folder sementara di atas setelah selesai
rm -rf "$(dirname "$DATABASE_BACKUP_DIR")"
```

## 9. Automated tests

```bash
cd backend
pytest tests/test_backup_restore.py -v
```

Termasuk rangkaian test khusus `validate_backup_directory()` (root
filesystem, home directory, root repo, root backend, folder `instance/`,
folder/path database aktif, placeholder env var, symlink yang lolos ke
lokasi terlarang, `--keep` di bawah minimum, dan revalidasi tepat-sebelum-
hapus di `--prune --apply`). Semua test di file itu pakai file SQLite di
`tempfile.mkdtemp()` — **tidak pernah** membaca, menimpa, atau menghapus
`instance/tracker.db` yang sebenarnya. Test yang butuh symlink otomatis
di-skip (bukan gagal) di environment yang nggak bisa bikin symlink tanpa
privilese elevated (mis. Windows tanpa Developer Mode).
