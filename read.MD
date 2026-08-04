# Baby Daily Tracker

**Aplikasi pencatatan harian tumbuh kembang bayi — full-stack, dibangun dari nol, gratis selamanya.**

---

## Ringkasan

Baby Daily Tracker adalah aplikasi web (PWA — bisa di-install ke HP) buat mencatat dan memantau aktivitas harian bayi: menyusui, tidur, popok, tumbuh kembang, vaksinasi, kesehatan, mood, dan momen penting. Dibangun khusus dengan standar Indonesia (IDAI, Kemenkes, WHO) dan bahasa Indonesia penuh.

Dikembangkan dari nol — backend, frontend, deployment, sampai automasi — semuanya berjalan di infrastruktur **gratis selamanya**, tanpa biaya bulanan.

---

## Tech Stack

| Layer | Teknologi |
|---|---|
| Frontend | React + Vite, Tailwind CSS, Recharts |
| Backend | Flask (Python) + SQLAlchemy + SQLite |
| Autentikasi | Token-based (bukan cookie session — didesain khusus buat cross-domain) |
| Hosting Backend | PythonAnywhere (free tier) |
| Hosting Frontend | Vercel (free tier) |
| Automasi terjadwal | GitHub Actions (pengganti n8n, gratis selamanya) |
| Notifikasi | Telegram Bot API |
| PWA | vite-plugin-pwa + Workbox |
| Version control | Git + GitHub, dengan environment staging & production terpisah |

---

## Fitur Utama

### 📋 Pencatatan Harian
- Menyusui (ASI langsung/perah, sufor, MPASI) dengan durasi, volume, sisi payudara
- Tidur, dengan penanganan sesi yang melewati tengah malam (dipotong per hari secara akurat)
- Popok (pipis/pup/keduanya, konsistensi, warna)
- Perah ASI, aktivitas (mandi, jalan-jalan), obat (termasuk shortcut Vitamin D)
- Input waktu kelipatan 5 menit, tidak bisa pilih waktu di masa depan
- Visualisasi jam radial 24 jam (custom, sinkron WIB)

### 📈 Tumbuh Kembang
- Kurva pertumbuhan WHO (berat, tinggi, lingkar kepala) dengan status persentil
- Milestone perkembangan motorik sesuai usia (acuan IDAI)

### 💉 Vaksinasi
- Jadwal lengkap (wajib + tambahan) sesuai rekomendasi IDAI
- Penanganan vaksin yang diberikan lebih awal (dengan alasan medis)
- Reminder vaksin jatuh tempo otomatis

### 🩺 Kesehatan
- Kunjungan dokter, suhu tubuh, riwayat sakit, obat-obatan

### 🔮 Prediksi Cerdas (tanpa AI, berbasis data)
- Prediksi jadwal menyusui berikutnya (dari rata-rata interval)
- **Wake window** — prediksi kapan bayi kemungkinan mulai ngantuk lagi, berdasarkan acuan usia (fitur premium khas app-app berbayar seperti Huckleberry, dibangun gratis)

### 📖 Artikel Edukasi
- Artikel internal (ditulis sendiri, berbasis IDAI/WHO/Kemenkes) — tampil kontekstual per fitur
- Artikel eksternal dengan link langsung ke sumber (IDAI, Kemenkes)
- Refresh otomatis dari RSS feed resmi (opsional)

### 👨‍👩‍👧 Multi-Caregiver
- Undang pasangan/pengasuh lewat kode, akses penuh ke data anak yang sama
- Role owner vs caregiver dengan batasan yang jelas
- **Atribusi** — tiap catatan menyimpan siapa yang mencatat
- **Notifikasi real-time** ke pengasuh lain saat ada yang mencatat (opsional, default mati)

### 🔔 Reminder Otomatis (Telegram)
- Ringkasan aktivitas harian (menyusui, tidur, popok) — data hari sebelumnya yang lengkap 24 jam
- Alert vaksin jatuh tempo & jadwal kontrol dokter
- Tips harian yang berotasi (tidak pernah mengulang sebelum semua tips ditampilkan)
- Dijadwalkan via GitHub Actions — **gratis selamanya**, bukan n8n (yang cuma trial 14 hari)

### 📱 PWA & Offline
- Bisa di-install ke home screen HP, ikon custom
- **Logging offline** — catatan quick-log (menyusui, tidur, popok, dll) tetap tersimpan walau tanpa koneksi internet, otomatis tersinkron begitu online lagi (pakai IndexedDB)

### 💾 Backup & Portabilitas
- Export laporan PDF, backup/restore JSON
- Import data dari PiyoLog (app tracker lain)

### 👤 Profil & Personalisasi
- Nama panggilan (nickname) buat tampilan ringkas di Dashboard
- Profil anak & profil akun terpisah

---

## Arsitektur & Praktik Engineering

- **Staging & Production terpisah total** — backend, frontend, dan database masing-masing punya environment sendiri, testing dulu sebelum naik ke production
- **Migrasi database yang aman** — script khusus buat nambah kolom/tabel baru di database production **tanpa** menghapus data yang sudah ada
- **Autentikasi token-based** — didesain ulang dari cookie session setelah ditemukan masalah cross-domain (browser modern makin ketat soal cookie pihak ketiga)
- Berbagai bug production ditemukan & diperbaiki melalui proses debugging kolaboratif: penanganan timezone WIB yang konsisten, perhitungan tidur lintas tengah malam, akurasi jam radial

---

## Perjalanan Pengembangan

Dibangun bertahap dari MVP (pencatatan dasar) sampai jadi platform lengkap dengan:
- Insiden production yang berhasil diselesaikan (bug 500, CORS, migrasi schema) tanpa kehilangan data pengguna
- Iterasi berdasarkan feedback pemakaian nyata (bukan asumsi)
- Riset kompetitor untuk memastikan fitur tetap relevan dengan standar pasar

---

*Dibangun oleh Muhamad Adiyansyah menggunakan Claude sebagai partner development — dari arsitektur, coding, testing, sampai deployment dan debugging production.*
