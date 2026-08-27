# Appointment Preparation Checklist — V3 Phase 1

Checklist persiapan dokter tersedia di Kesehatan → Dokter. Caregiver dapat
menyiapkan buku kesehatan, identitas/asuransi, daftar obat, hasil pemeriksaan,
dan perlengkapan anak; menyimpan maksimal 10 pertanyaan; serta membawa refleksi
Family Check-in yang sebelumnya ditandai untuk dibahas dengan tenaga profesional.
Tanggal persiapan juga muncul secara generik di Development Calendar tanpa isi
pertanyaan maupun refleksi.

Status `not_started`, `in_progress`, dan `ready` dihitung dari checklist setiap
kali data dibaca dan tidak disimpan sebagai state turunan. Setiap caregiver dapat
membuat satu persiapan per anak per tanggal. Owner dapat mengelola semua record,
Editor hanya miliknya, dan Viewer hanya melihat.

Pertanyaan dan sumber refleksi diperlakukan privat pada audit trail. Fitur ini
online-only, tidak membutuhkan scheduler/background worker, dan tabel baru dibuat
secara idempotent oleh `scripts/migrate_production.py` melalui `db.create_all()`.
