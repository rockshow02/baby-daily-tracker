"""
Backup manual database SQLite aktif — aman dijalankan sementara aplikasi
web masih jalan (pakai SQLite Backup API lewat Connection.backup(),
BUKAN cp file mentah-mentah).

PythonAnywhere free tier nggak punya scheduled task, jadi backup ini
SENGAJA cuma bisa dipicu manual dari Bash console — bukan hilang fitur,
tapi keputusan desain: jangan pernah nebak-nebak jadwal, biar operator
yang mutusin kapan.

CARA PAKAI (di Bash console PythonAnywhere, atau lokal):
  cd ~/baby-daily-tracker/backend
  source ~/.virtualenvs/babytracker-venv/bin/activate

  # bikin backup baru dari database yang lagi dikonfigurasi app ini
  python scripts/backup_database.py --environment staging

  # override folder tujuan (default: ~/database-backups, atau env var
  # DATABASE_BACKUP_DIR)
  python scripts/backup_database.py --environment staging --backup-dir /path/lain

  # lihat daftar backup yang ada
  python scripts/backup_database.py --list

  # verifikasi 1 backup tertentu (integrity check + checksum kalau ada metadata)
  python scripts/backup_database.py --verify ~/database-backups/tracker-staging-20260822-213000.db

  # lihat backup mana yang AKAN dihapus kalau retensi diterapkan (dry-run, DEFAULT)
  python scripts/backup_database.py --prune --keep 10

  # BENERAN hapus (wajib --apply eksplisit)
  python scripts/backup_database.py --prune --keep 10 --apply

TIDAK PERNAH mencetak isi baris database — cuma metadata struktural
(nama file, ukuran, timestamp, hasil integrity check).
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app  # noqa: E402
from db_backup_common import (  # noqa: E402
    MIN_KEEP,
    BackupError,
    create_backup,
    list_backups,
    log,
    prune_backups,
    resolve_active_sqlite_path,
    resolve_backup_dir,
    resolve_environment_label,
    verify_backup,
)


def _resolve_active_db_path_best_effort():
    """
    Dipakai cuma buat validasi TAMBAHAN folder backup (menolak folder induk/
    path database aktif itu sendiri) di --list/--verify/--prune — operasi
    ini SENDIRI nggak butuh app Flask buat kerjanya (baca file backup, bukan
    database aktif), jadi kalau resolusi app/database aktif gagal karena
    sebab lain, itu JANGAN sampai bikin --list/--verify/--prune ikut gagal
    total. Validasi folder backup yang lain (root filesystem, home, repo,
    dst) tetap jalan penuh terlepas dari ini.
    """
    try:
        app = create_app()
        return resolve_active_sqlite_path(app)
    except Exception:
        return None


def run_backup(args) -> int:
    app = create_app()
    try:
        source_path = resolve_active_sqlite_path(app)
        backup_dir = resolve_backup_dir(args.backup_dir, create=True, active_db_path=source_path)
        environment = resolve_environment_label(args.environment)

        log(f"backup start — environment={environment} source={source_path} dest_dir={backup_dir}")

        result = create_backup(source_path, backup_dir, environment)

        log(
            "backup ok — "
            f"file={result.filename} size_bytes={result.size_bytes} "
            f"integrity=ok sha256={result.sha256}"
        )
        print("")
        print("Backup berhasil.")
        print(f"  Sumber database   : {source_path}")
        print(f"  File backup       : {result.path}")
        print(f"  Environment       : {result.environment}")
        print(f"  Timestamp         : {result.timestamp}")
        print(f"  Ukuran            : {result.size_bytes} bytes")
        print(f"  Integrity check   : ok")
        print(f"  SHA-256           : {result.sha256}")
        if result.metadata_path:
            print(f"  Metadata          : {result.metadata_path}")
        return 0
    except BackupError as exc:
        log(f"backup GAGAL — {exc}")
        print(f"\nBackup GAGAL: {exc}", file=sys.stderr)
        return 1


def run_list(args) -> int:
    try:
        backup_dir = resolve_backup_dir(args.backup_dir, create=False, active_db_path=_resolve_active_db_path_best_effort())
        entries = list_backups(backup_dir)
    except BackupError as exc:
        log(f"list GAGAL — {exc}")
        print(f"\nGAGAL: {exc}", file=sys.stderr)
        return 1

    log(f"list — dir={backup_dir} count={len(entries)}")
    print(f"Folder backup: {backup_dir}")
    if not entries:
        print("(belum ada backup)")
        return 0

    print(f"{'FILENAME':<40} {'ENVIRONMENT':<12} {'TIMESTAMP':<16} {'SIZE (bytes)':>14}  METADATA")
    for e in entries:
        print(
            f"{e['filename']:<40} {e['environment']:<12} {e['timestamp']:<16} "
            f"{e['size_bytes']:>14}  {'ada' if e['has_metadata'] else 'tidak ada'}"
        )
    return 0


def run_verify(args) -> int:
    try:
        backup_dir = resolve_backup_dir(args.backup_dir, create=False, active_db_path=_resolve_active_db_path_best_effort())
        result = verify_backup(args.verify, backup_dir, allow_outside=args.allow_outside_backup_dir)
    except BackupError as exc:
        log(f"verify GAGAL — {exc}")
        print(f"\nVerifikasi GAGAL: {exc}", file=sys.stderr)
        return 1

    log(
        f"verify — file={result.path.name} integrity={'ok' if result.integrity_ok else 'GAGAL'} "
        f"checksum={'ok' if result.checksum_ok else ('GAGAL' if result.checksum_ok is False else 'n/a')}"
    )
    print(f"File               : {result.path}")
    print(f"Integrity check    : {'ok' if result.integrity_ok else f'GAGAL ({result.integrity_detail})'}")
    if result.checksum_ok is None:
        print("Checksum SHA-256   : tidak ada metadata buat dibandingkan")
    else:
        print(f"Checksum SHA-256   : {'cocok' if result.checksum_ok else 'TIDAK COCOK — file mungkin rusak/berubah'}")
    if result.metadata:
        print(f"Environment (meta) : {result.metadata.get('environment')}")
        print(f"Dibuat (meta)      : {result.metadata.get('created_at')}")

    if not result.integrity_ok or result.checksum_ok is False:
        return 1
    return 0


def run_prune(args) -> int:
    if args.keep < MIN_KEEP:
        print(f"\nGAGAL: --keep harus >= {MIN_KEEP} (minimal 1 backup wajib dipertahankan eksplisit), dapat: {args.keep}", file=sys.stderr)
        return 1

    try:
        backup_dir = resolve_backup_dir(args.backup_dir, create=False, active_db_path=_resolve_active_db_path_best_effort())
        result = prune_backups(backup_dir, args.keep, apply=args.apply)
    except BackupError as exc:
        log(f"prune GAGAL — {exc}")
        print(f"\nPrune GAGAL: {exc}", file=sys.stderr)
        return 1

    mode = "APPLY (menghapus beneran)" if args.apply else "DRY RUN (tidak menghapus apa pun)"
    log(
        f"prune — dir={backup_dir} keep={args.keep} mode={'apply' if args.apply else 'dry-run'} "
        f"to_delete={len(result['to_delete'])} deleted={len(result['deleted'])} aborted={result['aborted']}"
    )
    print(f"Mode                    : {mode}")
    print(f"Folder backup           : {backup_dir}")
    print(f"Backup saat ini         : {len(result['existing'])}")
    if args.apply:
        print(f"Berhasil dihapus        : {len(result['deleted'])} backup")
        for e in result["deleted"]:
            print(f"  - {e['filename']} ({e['size_bytes']} bytes)")
    else:
        print(f"Akan dihapus (proyeksi) : {len(result['to_delete'])} backup")
        for e in result["to_delete"]:
            print(f"  - {e['filename']} ({e['size_bytes']} bytes)")
    print(f"Sisa setelah operasi    : {len(result['remaining_after_apply'])} backup")

    if result["aborted"]:
        print(f"\nDIHENTIKAN DI TENGAH JALAN: {result['abort_reason']}")
        print(
            f"{len(result['deleted'])} dari {len(result['to_delete'])} kandidat SUDAH terhapus sebelum "
            "penghentian ini — sisanya TIDAK disentuh."
        )
        log(f"prune ABORTED — {result['abort_reason']}")
        return 1

    if result["to_delete"] or result["existing"]:
        print("\nCatatan: penghapusan file backup TIDAK bisa dipulihkan (bukan masuk trash/recycle bin).")
    if not args.apply and result["to_delete"]:
        print("Ini masih dry-run — tidak ada yang dihapus. Tambahkan --apply buat beneran menghapus setelah dicek daftarnya.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--environment",
        default=None,
        help="Label environment buat nama file backup (local/staging/production, dst). "
        "Kalau nggak dikasih, dicoba dideteksi dari env var BACKUP_ENVIRONMENT / FLASK_ENV, fallback 'local'.",
    )
    parser.add_argument(
        "--backup-dir",
        default=None,
        help="Override folder backup (default: ~/database-backups, atau env var DATABASE_BACKUP_DIR).",
    )
    parser.add_argument("--list", action="store_true", help="Tampilkan daftar backup yang ada, jangan bikin backup baru.")
    parser.add_argument("--verify", metavar="PATH", default=None, help="Verifikasi 1 file backup tertentu, jangan bikin backup baru.")
    parser.add_argument(
        "--allow-outside-backup-dir",
        action="store_true",
        help="Izinkan --verify menunjuk file DI LUAR folder backup yang dikonfigurasi. Hati-hati.",
    )
    parser.add_argument("--prune", action="store_true", help="Mode pruning (hapus backup lama). Dry-run kecuali --apply dikasih.")
    parser.add_argument(
        "--keep",
        type=int,
        default=10,
        help="Jumlah backup terbaru yang dipertahankan saat --prune (default: 10, minimal 1 — nggak boleh 0/negatif).",
    )
    parser.add_argument("--apply", action="store_true", help="Beneran hapus file saat --prune. Tanpa ini, --prune cuma dry-run.")
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)

    if args.list:
        return run_list(args)
    if args.verify:
        return run_verify(args)
    if args.prune:
        return run_prune(args)
    return run_backup(args)


if __name__ == "__main__":
    sys.exit(main())
