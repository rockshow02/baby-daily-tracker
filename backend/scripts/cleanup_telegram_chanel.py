"""
Utilitas buat leave/hapus banyak channel Telegram sekaligus.

BEDA dari bot reminder (Xaleena_bot) — ini pakai akun Telegram KAMU SENDIRI
(login pakai nomor HP), bukan bot. Soalnya bot nggak bisa "leave channel
atas nama kamu", cuma bisa kirim pesan satu arah. Script ini terpisah total
dari project Baby Daily Tracker, jalanin di komputer kamu aja.

CARA SETUP (sekali doang):
  1. Buka https://my.telegram.org, login pakai nomor HP kamu
  2. Klik "API development tools"
  3. Isi form (nama app bebas, misal "cleanup-script"), submit
  4. Catat "api_id" (angka) dan "api_hash" (huruf+angka)
  5. pip install telethon --break-system-packages   (atau tanpa flag itu kalau di venv biasa)

CARA PAKAI:
  1. Isi API_ID dan API_HASH di bawah (atau lewat environment variable)
  2. Jalankan: python cleanup_telegram_channels.py
  3. Pertama kali jalan, diminta login (nomor HP + kode OTP dari Telegram) —
     abis itu session tersimpan di file .session, nggak perlu login ulang
  4. Script nampilin DAFTAR semua channel kamu dulu (DRY RUN, belum ada
     yang dihapus)
  5. Kamu pilih mau leave yang mana: ketik nomor-nomornya (pisah koma),
     atau "all" buat semua, atau "q" buat batal tanpa aksi apapun
  6. Baru setelah itu proses leave beneran jalan
"""
import os
import sys

try:
    from telethon.sync import TelegramClient
    from telethon.tl.types import Channel
except ImportError:
    print("Library 'telethon' belum ke-install. Jalankan dulu:")
    print("  pip install telethon")
    sys.exit(1)

API_ID = os.environ.get("TG_API_ID", "GANTI_DENGAN_API_ID_KAMU")
API_HASH = os.environ.get("TG_API_HASH", "GANTI_DENGAN_API_HASH_KAMU")
SESSION_NAME = "cleanup_session"  # bikin file cleanup_session.session di folder yang sama


def main():
    if API_ID == "GANTI_DENGAN_API_ID_KAMU" or API_HASH == "GANTI_DENGAN_API_HASH_KAMU":
        print("Isi dulu API_ID dan API_HASH di bagian atas file ini")
        print("(ambil dari https://my.telegram.org > API development tools)")
        sys.exit(1)

    with TelegramClient(SESSION_NAME, int(API_ID), API_HASH) as client:
        print("Login berhasil. Mengambil daftar channel...\n")

        channels = []
        for dialog in client.iter_dialogs():
            entity = dialog.entity
            if isinstance(entity, Channel):
                channels.append(dialog)

        if not channels:
            print("Nggak ada channel yang kamu ikuti/punya.")
            return

        print(f"Ditemukan {len(channels)} channel:\n")
        for i, dialog in enumerate(channels, start=1):
            entity = dialog.entity
            owner_tag = " [PUNYA KAMU]" if getattr(entity, "creator", False) else ""
            unread = f" ({dialog.unread_count} belum dibaca)" if dialog.unread_count else ""
            print(f"  {i}. {dialog.name}{owner_tag}{unread}")

        print("\nKetik nomor yang mau di-LEAVE (pisah koma, cth: 1,3,5)")
        print("atau ketik 'all' buat semua, atau 'q' buat batal.")
        choice = input("> ").strip().lower()

        if choice == "q" or not choice:
            print("Dibatalkan, nggak ada yang diubah.")
            return

        if choice == "all":
            selected_indices = list(range(1, len(channels) + 1))
        else:
            try:
                selected_indices = [int(x.strip()) for x in choice.split(",")]
            except ValueError:
                print("Input nggak valid. Batalkan.")
                return

        selected = [channels[i - 1] for i in selected_indices if 1 <= i <= len(channels)]

        print(f"\nBakal leave {len(selected)} channel ini:")
        for d in selected:
            print(f"  - {d.name}")
        confirm = input("\nYakin? Ini nggak bisa dibatalkan. Ketik 'ya' buat lanjut: ").strip().lower()

        if confirm != "ya":
            print("Dibatalkan, nggak ada yang diubah.")
            return

        for dialog in selected:
            try:
                client.delete_dialog(dialog.entity)
                print(f"  ✓ Berhasil leave: {dialog.name}")
            except Exception as e:
                print(f"  ✗ Gagal leave {dialog.name}: {e}")

        print("\nSelesai.")


if __name__ == "__main__":
    main()