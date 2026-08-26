# Development Calendar — V3 Phase 1

Kalender perkembangan adalah tampilan baca-saja per bulan. Endpoint `GET
/api/children/<id>/development-calendar?month=YYYY-MM` menggabungkan Memory
Journal, milestone, pengukuran pertumbuhan, vaksinasi, kunjungan/kontrol dokter,
pengingat, jadwal obat, dan tujuan keluarga tanpa menyalin data ke tabel baru.

Status kalender tidak dipersistenkan dan tidak memerlukan cron, worker, atau
scheduler. Data dihitung ketika caregiver membuka atau mengganti bulan, sehingga
sesuai dengan batasan akun PythonAnywhere Free.

## Privasi dan batasan

- Semua caregiver yang memiliki akses ke anak dapat melihat kalender.
- Nama obat, dosis, instruksi, diagnosis, gejala, notes, nama dokter, dan klinik
  tidak dikirim dalam payload kalender umum.
- Pengingat dan jadwal obat berulang diagregasi menjadi jumlah generik per hari.
- Query dibatasi satu bulan dan maksimal 200 definisi/baris per sumber.
- Phase 1 tidak menyediakan drag-and-drop atau CRUD langsung dari kalender;
  perubahan dilakukan melalui fitur sumbernya.
