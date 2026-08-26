# Development Timeline — V3 Phase 1

Endpoint read-only `GET /api/children/<id>/development-timeline` menggabungkan
Memory Journal, milestone, pertumbuhan, vaksinasi yang sudah diberikan,
catatan kesehatan, suhu, dan kunjungan dokter. Tidak ada tabel baru dan data
sumber tidak disalin.

Parameter opsional: `categories` (comma-separated), `from`, `to`, dan `limit`
(maksimal 200; default 100). Semua query dibatasi dan hasil diurutkan terbaru.

Ringkasan kesehatan memakai data struktural minimum. Nama penyakit, gejala,
diagnosis, alasan kunjungan, nama dokter/klinik, dan notes tidak dimasukkan ke
payload timeline. Endpoint tetap memerlukan akses caregiver ke anak tersebut.
