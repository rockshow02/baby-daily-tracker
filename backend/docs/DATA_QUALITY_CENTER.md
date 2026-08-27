# Data Quality Center — V3 Phase 1

Data Quality Center adalah pemeriksaan read-only untuk 7, 30, atau 90 hari
terakhir. Ia mencari kemungkinan duplikat berdasarkan waktu/tanggal dan jenis
yang sama, waktu di masa depan, serta beberapa detail inti yang belum diisi.

Temuan tidak pernah mengubah atau menghapus data otomatis. Payload bersifat
generik dan tidak memuat nama obat, diagnosis, gejala, notes, nama dokter, atau
klinik. `source_ids` hanya membantu caregiver menelusuri record sumber setelah
otorisasi akses anak berhasil.

Pemeriksaan dibatasi maksimal 300 baris per sumber dan dijalankan saat endpoint
diminta. Tidak ada tabel baru, scheduler, worker, maupun migrasi. Temuan adalah
indikator kualitas pencatatan, bukan penilaian kesehatan atau saran medis.
