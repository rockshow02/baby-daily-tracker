# Growth & Milestone Goals — V3 Phase 1

Tujuan perkembangan adalah rencana keluarga, bukan target berat/tinggi,
diagnosis, atau patokan medis. Kategori dibatasi ke milestone, check-in
pertumbuhan, rutinitas, dan custom. Status tidak disimpan terpisah: completed
bila sudah selesai; overdue setelah target; due dari target hari ini sampai
tujuh hari; selain itu upcoming. Status dihitung ketika endpoint dibaca, tanpa
scheduler.

Owner/Editor dapat membuat dan menyelesaikan tujuan; Viewer hanya melihat.
Owner dapat edit/hapus semua, Editor hanya definisi buatannya. Penyelesaian
idempoten dan dapat dibuka kembali. Judul/note diperlakukan privat pada audit.
Tabel baru dibuat lewat `db.create_all()` dan tidak mengubah tabel lama.
Tujuan dihitung dalam Privacy Data inventory tetapi sengaja tidak dimasukkan ke
backup JSON Phase 1, konsisten dengan reminder dan jadwal obat.
