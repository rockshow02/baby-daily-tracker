# Memory Storage & Photo Health — V3 Phase 1

Fitur ini hanya dapat dibuka Owner dan hanya membaca/menulis folder
`uploads/memory`. Overview menampilkan jumlah/ukuran aktual foto, ambang
peringatan (default 100 MB per anak, dapat diubah lewat
`MEMORY_JOURNAL_WARNING_BYTES`), file hilang, file yatim, dan sepuluh foto
terbesar. Nama file internal tidak dikirim ke frontend.

Pembersihan file yatim wajib melalui dry-run, lalu POST kedua dengan konfirmasi
literal `BERSIHKAN`. Kandidat harus cocok persis pola
`memory_<child_id>_<32 hex>.webp`, regular file, bukan symlink, tetap berada di
direktori memory, dan tetap tidak memiliki baris database saat revalidasi tepat
sebelum unlink. File lain, foto anak lain, database, backup, dan uploads umum
tidak pernah menjadi kandidat.

Optimasi ulang berjalan sinkron dan atomik melalui temporary file +
`os.replace`; file hanya diganti bila hasil WebP quality 72 lebih kecil.
Operasi yang benar-benar mengubah foto dicatat dalam audit trail tanpa isi atau
nama file. Tidak diperlukan cron, worker, Redis, atau task terjadwal.
