"""
Restore database SQLite aktif dari 1 file backup yang dipilih — operasi
DESTRUKTIF (menimpa database aktif), makanya penuh pengaman berlapis:
validasi path, integrity check, checksum, pencocokan environment, safety
backup otomatis SEBELUM menimpa apa pun, dan konfirmasi eksplisit yang
harus DIKETIK PERSIS (bukan cuma "y").

CARA PAKAI (di Bash console PythonAnywhere, atau lokal):
  cd ~/baby-daily-tracker/backend
  source ~/.virtualenvs/babytracker-venv/bin/activate

  python scripts/restore_database.py \
    --backup ~/database-backups/tracker-staging-20260822-213000.db \
    --environment staging

Operator bakal diminta ngetik PERSIS "RESTORE staging" (huruf besar/kecil
persis, environment sesuai --environment) buat konfirmasi. Ketikan lain
apa pun (termasuk "y"/"yes") membatalkan restore TANPA mengubah apa-apa.

Buat testing otomatis (BUKAN dipakai default), lewati prompt interaktif
pakai:
  python scripts/restore_database.py --backup ... --environment staging \
    --confirm-environment staging

SEBELUM restore beneran jalan, script ini OTOMATIS bikin 1 backup lagi
dari database yang KEBURU AKTIF sekarang (pakai mekanisme yang sama kayak
backup_database.py) — jadi walau restore-nya kepilih backup yang salah,
kondisi sebelum restore tetap ada buat dipulihkan lagi.
"""

import argparse
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app  # noqa: E402
from db_backup_common import (  # noqa: E402
    BackupError,
    check_integrity,
    create_backup,
    load_metadata,
    log,
    parse_backup_filename,
    resolve_active_sqlite_path,
    resolve_and_validate_backup_path,
    resolve_backup_dir,
    sanitize_environment_label,
    sha256_of_file,
    sqlite_backup_copy,
)


class RestoreAborted(Exception):
    """Operator membatalkan (bukan kegagalan teknis)."""


def _determine_backup_environment(backup_path, metadata):
    if metadata and metadata.get("environment"):
        return sanitize_environment_label(metadata["environment"])
    parsed = parse_backup_filename(backup_path.name)
    if parsed:
        return parsed["environment"]
    raise BackupError(f"Nggak bisa menentukan environment dari file backup ini: {backup_path.name}")


def _print_confirmation_banner(source_backup, target_db, environment, safety_backup_path):
    print("")
    print("=" * 70)
    print("KONFIRMASI RESTORE DATABASE — OPERASI INI MENIMPA DATABASE AKTIF")
    print("=" * 70)
    print(f"  Backup sumber      : {source_backup}")
    print(f"  Database target    : {target_db}")
    print(f"  Environment        : {environment}")
    print(f"  Safety backup      : {safety_backup_path}")
    print("=" * 70)


def _interactive_confirm(environment) -> bool:
    phrase = f"RESTORE {environment}"
    print(f'Ketik PERSIS "{phrase}" (tanpa tanda kutip) buat lanjut, atau tekan Enter/ketik apa pun lain buat batal:')
    try:
        typed = input("> ")
    except (EOFError, KeyboardInterrupt):
        return False
    return typed == phrase


def restore(args) -> int:
    try:
        requested_environment = sanitize_environment_label(args.environment)

        app = create_app()
        active_db_path = resolve_active_sqlite_path(app)
        backup_dir = resolve_backup_dir(args.backup_dir, create=True)

        backup_path = resolve_and_validate_backup_path(args.backup, backup_dir, allow_outside=args.allow_outside_backup_dir)

        log(f"restore start — environment={requested_environment} backup={backup_path} target={active_db_path}")

        ok, detail = check_integrity(backup_path)
        if not ok:
            raise BackupError(f"Backup yang dipilih GAGAL integrity check ({detail}) — restore dibatalkan.")

        metadata = load_metadata(backup_path)
        if metadata and metadata.get("sha256"):
            actual = sha256_of_file(backup_path)
            if actual != metadata["sha256"]:
                raise BackupError("Checksum SHA-256 backup TIDAK COCOK dengan metadata — file mungkin rusak/berubah. Restore dibatalkan.")

        backup_environment = _determine_backup_environment(backup_path, metadata)
        if backup_environment != requested_environment:
            if not args.override_environment_mismatch:
                raise BackupError(
                    f"Environment backup ini ({backup_environment!r}) TIDAK COCOK dengan --environment "
                    f"({requested_environment!r}). Kalau ini beneran disengaja, ulangi dengan "
                    "--override-environment-mismatch."
                )
            print(
                f"\n⚠️  PERINGATAN: backup ini berlabel environment {backup_environment!r}, tapi kamu minta "
                f"restore ke {requested_environment!r}. Dilanjutkan karena --override-environment-mismatch dikasih.\n"
            )

        # safety backup dari database yang LAGI AKTIF, SEBELUM disentuh sama sekali
        log("membuat safety backup dari database aktif sebelum restore...")
        safety_result = create_backup(active_db_path, backup_dir, requested_environment)
        log(f"safety backup ok — file={safety_result.filename} size_bytes={safety_result.size_bytes}")

        _print_confirmation_banner(backup_path, active_db_path, requested_environment, safety_result.path)
        print("\nSebelum lanjut: pastikan web app PythonAnywhere untuk environment ini SUDAH di-stop/reload")
        print("kalau memungkinkan, biar nggak ada proses lain yang nulis ke database selama restore.\n")

        if args.confirm_environment:
            confirm_env = sanitize_environment_label(args.confirm_environment)
            if confirm_env != requested_environment:
                raise BackupError(
                    f"--confirm-environment ({confirm_env!r}) tidak cocok dengan --environment ({requested_environment!r}) — restore dibatalkan."
                )
            log("confirm — non-interaktif via --confirm-environment (dipakai buat testing)")
        else:
            if not _interactive_confirm(requested_environment):
                log("restore dibatalkan oleh operator (konfirmasi tidak cocok)")
                print("\nDibatalkan. Database aktif TIDAK diubah. Safety backup di atas tetap tersimpan.")
                raise RestoreAborted()

        # restore beneran: salin backup TERVALIDASI -> file sementara di
        # folder yang SAMA dengan database aktif (biar os.replace() atomic,
        # butuh 1 filesystem yang sama) -> verifikasi ULANG -> baru replace
        tmp_restore_path = active_db_path.parent / f".{active_db_path.name}.restoring-{os.getpid()}.tmp"
        if tmp_restore_path.exists():
            tmp_restore_path.unlink()

        original_mode = None
        try:
            original_mode = active_db_path.stat().st_mode
        except OSError:
            pass

        # tahap SALIN + VERIFIKASI — kalau gagal di sini, file sementaranya
        # cuma sampah percobaan yang gagal, aman dibuang langsung. Database
        # aktif belum tersentuh sama sekali sampai titik ini.
        try:
            sqlite_backup_copy(backup_path, tmp_restore_path)
        except sqlite3.Error as exc:
            tmp_restore_path.unlink(missing_ok=True)
            raise BackupError(f"Gagal menyalin backup ke file restore sementara: {exc}") from exc

        ok2, detail2 = check_integrity(tmp_restore_path)
        if not ok2:
            tmp_restore_path.unlink(missing_ok=True)
            raise BackupError(f"Salinan restore sementara GAGAL integrity check ({detail2}) — dibatalkan sebelum menimpa apa pun.")

        # tahap REPLACE — titik tak-berbalik. Kalau os.replace() gagal,
        # JANGAN hapus tmp_restore_path (itu satu-satunya salinan hasil
        # restore yang udah tervalidasi) — pesan errornya menyebut lokasinya
        # eksplisit buat investigasi/percobaan ulang manual.
        try:
            os.replace(tmp_restore_path, active_db_path)
        except OSError as exc:
            raise BackupError(
                f"GAGAL mengganti database aktif ({exc}). Database aktif TIDAK diubah "
                f"(replace atomic, gagal-di-tengah = tidak berubah). File sementara hasil restore "
                f"disimpan di {tmp_restore_path} buat investigasi/percobaan ulang. Safety backup: {safety_result.path}"
            )

        if original_mode is not None:
            try:
                os.chmod(active_db_path, original_mode)
            except OSError:
                log("peringatan: gagal mempertahankan permission file asli (dilanjutkan, bukan fatal)")

        # verifikasi akhir: database aktif SETELAH diganti
        ok3, detail3 = check_integrity(active_db_path)
        if not ok3:
            raise BackupError(
                f"Database aktif SETELAH restore GAGAL integrity check ({detail3}) — ini KRITIS. "
                f"Safety backup (kondisi SEBELUM restore) masih ada di {safety_result.path}, pulihkan manual dari sana."
            )

        log(f"restore ok — target={active_db_path} integrity=ok safety_backup={safety_result.path}")
        print("\nRestore berhasil.")
        print(f"  Database aktif       : {active_db_path}")
        print(f"  Dipulihkan dari      : {backup_path}")
        print(f"  Environment          : {requested_environment}")
        print(f"  Integrity check      : ok")
        print(f"  Safety backup (lama) : {safety_result.path}")
        print("\nLangkah selanjutnya: reload web app PythonAnywhere, panggil GET /api/health,")
        print("lalu lakukan smoke test read-only sebelum menghapus safety backup di atas.")
        return 0

    except RestoreAborted:
        return 1
    except BackupError as exc:
        log(f"restore GAGAL — {exc}")
        print(f"\nRestore GAGAL: {exc}", file=sys.stderr)
        return 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--backup", required=True, metavar="PATH", help="Path file backup yang mau dipulihkan.")
    parser.add_argument("--environment", required=True, help="Environment target restore (harus cocok dengan environment backup, kecuali di-override).")
    parser.add_argument("--backup-dir", default=None, help="Override folder backup (default: ~/database-backups, atau env var DATABASE_BACKUP_DIR).")
    parser.add_argument(
        "--allow-outside-backup-dir",
        action="store_true",
        help="Izinkan --backup menunjuk file DI LUAR folder backup yang dikonfigurasi. Hati-hati.",
    )
    parser.add_argument(
        "--override-environment-mismatch",
        action="store_true",
        help="Izinkan restore walau environment backup nggak cocok dengan --environment. HATI-HATI.",
    )
    parser.add_argument(
        "--confirm-environment",
        default=None,
        metavar="ENVIRONMENT",
        help="Lewati prompt konfirmasi interaktif (HANYA buat testing/otomasi) — nilainya harus SAMA "
        "PERSIS dengan --environment, atau restore dibatalkan. JANGAN dipakai buat restore manual biasa.",
    )
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    return restore(args)


if __name__ == "__main__":
    sys.exit(main())
