# Privacy & Data Management Center — Phase 1

Fitur ini berjalan sepenuhnya berdasarkan request pengguna; tidak membutuhkan scheduler, worker, Redis, atau task terjadwal sehingga sesuai untuk PythonAnywhere Free.

## Fitur

- Inventaris jumlah data per anak tanpa mengirim isi catatan.
- Backup JSON melalui endpoint ekspor yang sudah ada.
- Editor/Viewer dapat keluar dari akses anak setelah re-autentikasi.
- Owner dapat menghapus seluruh data anak setelah memasukkan password dan mengetik nama anak persis.
- Akun dapat dihapus setelah tidak lagi memiliki profil anak.

Semua aksi destruktif online-only dan tidak masuk antrean offline. UI memblokir aksi bila masih ada mutasi offline terkait yang menunggu sinkronisasi.

## Kontrak keamanan penghapusan anak

`POST /api/privacy/children/<id>/delete` menerima `password` dan `confirmation`. Server memeriksa ulang autentikasi dan ownership. Database dihapus/commit terlebih dahulu; file foto yang path-nya tervalidasi baru dihapus sesudah commit. Kegagalan cleanup file tidak mengubah keberhasilan transaksi database dan dilaporkan sebagai `file_cleanup: warning`. Endpoint `DELETE /api/children/<id>` lama tidak lagi menghapus data tanpa konfirmasi.

## Makna “hapus akun”

Ini adalah **penghapusan identitas + deaktivasi permanen**, bukan hard-delete baris `users`. Nama, email, Telegram ID, dan kredensial dihapus/diganti nilai acak; seluruh membership aktif dicabut; `is_active=false`; semua token lama langsung ditolak. Placeholder teknis `Akun dihapus` dipertahankan agar atribusi catatan bersama caregiver lain tidak dipalsukan, dipindahkan ke orang lain, atau merusak foreign key historis.

Owner harus menghapus profil anak yang dimilikinya terlebih dahulu. Phase 1 belum menyediakan transfer ownership.

## Batas payload

Payload konfirmasi dibatasi 8 KiB pada byte mentah, termasuk ketika `Content-Length` tidak tersedia. Pembacaan stream berhenti di 8 KiB + 1 byte. Password maupun teks konfirmasi tidak disimpan dan tidak dicatat ke log/audit.
