# Monthly Story — V3 Phase 1

Monthly Story membuat pratinjau cerita satu bulan dari data yang sudah ada:
jumlah foto, milestone, vaksinasi, pertumbuhan, hingga empat foto pilihan, dan
catatan orang tua opsional. Tidak ada tabel cerita baru dan PDF tidak disimpan.

Preview dan PDF menggunakan POST agar catatan maupun pilihan foto tidak masuk
query string. Token snapshot bertanda tangan berlaku 15 menit dan hanya memuat
identitas anak/pengguna, waktu preview, versi, dan digest—bukan isi catatan atau
data anak. PDF membangun ulang laporan dan membandingkan digest secara aman;
perubahan data menghasilkan 409. PDF dibuat sinkron di memori menggunakan
ReportLab, sehingga tidak memerlukan worker, cron, Redis, atau akun berbayar.

Viewer dapat membuat preview tanpa catatan privat. Hanya Owner/Editor dapat
menambahkan catatan dan mengekspor PDF. Export yang berhasil dicatat di audit
trail tanpa nilai laporan. Maksimum body 20 KB, note 1000 karakter, dan empat
foto dari anak serta bulan yang sama.
