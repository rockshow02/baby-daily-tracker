# Family Development Check-in — V3 Phase 1

Check-in adalah refleksi bulanan per caregiver untuk lima area: gerak/motorik,
komunikasi, interaksi sosial, tidur, dan makan/minum. Pilihan yang tersedia
adalah `noticed`, `exploring`, dan `not_checked`; tidak ada skor, rekomendasi
klinis, label normal, atau label terlambat.

Setiap caregiver penulis dapat membuat satu check-in per anak per bulan. Owner
dapat mengelola semua check-in, Editor hanya miliknya sendiri, dan Viewer hanya
dapat melihat. Catatan dan pilihan untuk dibahas dengan tenaga profesional
bersifat privat serta hanya dicatat sebagai `private_details` pada audit trail.

Check-in bisa ditautkan ke Development Goal milik anak yang sama. Pembuatan dan
perubahan Phase 1 hanya tersedia saat online. Tabel dibuat secara idempotent oleh
langkah `db.create_all()` dalam `scripts/migrate_production.py`; tidak ada
scheduler atau background worker.
