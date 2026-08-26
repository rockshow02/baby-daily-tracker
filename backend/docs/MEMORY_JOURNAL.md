# Memory Journal — V3 Phase 1

Memory Journal menyimpan satu foto privat per entri, caption opsional (maksimal
500 karakter), dan tanggal momen. Owner dan Editor dapat membuat entri; Owner
dapat mengubah/menghapus semua entri, sedangkan Editor hanya entri buatannya.
Viewer hanya dapat melihat.

Foto mentah dibatasi 5 MB, divalidasi dari isi file menggunakan Pillow,
dirotasi mengikuti EXIF, dikecilkan maksimal 1600 px, metadata dibuang, lalu
disimpan sebagai WebP maksimal 2 MB. Nama file tidak pernah dikirim ke klien.
Foto hanya dilayani lewat endpoint berautentikasi.

Search/Tags/Favorites memakai tabel metadata dan tag baru (tanpa ALTER tabel
foto lama). Tag dinormalisasi lowercase, maksimal lima per foto dan 30 karakter
per tag. Query mendukung `q`, `tag`, `favorite=true`, `from`, `to`,
`created_by`, dan `sort=oldest`; hasil tetap dibatasi 100 item.

Upload foto bersifat online-only. Frontend menyimpan draft caption dan tanggal
secara lokal, tetapi tidak pernah menyimpan file foto ke antrean offline.

Tabel baru `memory_journal_entries` dibuat idempoten oleh `db.create_all()` di
`scripts/migrate_production.py`; tidak ada tabel lama yang diubah. Foto jurnal
tidak masuk backup JSON Phase 1 agar data privat berukuran besar tidak tersalin
tanpa persetujuan eksplisit. Penghapusan anak menghapus baris dan file fotonya.
