"""
Smoke test manual pasca-deploy — dijalankan operator SETELAH deploy
(staging ATAU production) buat mastiin backend beneran nyala dan sehat,
TANPA pernah mengubah data apa pun.

Cuma manggil GET <base-url>/health (endpoint publik, murah, read-only) —
TIDAK PERNAH bikin user, catatan, atau apa pun; TIDAK PERNAH ngirim token
autentikasi; TIDAK PERNAH ngikutin redirect ke host lain kecuali eksplisit
diizinkan.

CARA PAKAI:
  # dari komputer lokal, ke staging:
  python scripts/post_deploy_smoke_test.py --base-url https://xaleena.pythonanywhere.com/api

  # ke backend lokal (HANYA kalau server lokal beneran lagi jalan):
  python scripts/post_deploy_smoke_test.py --base-url http://localhost:5000/api

CATATAN PENTING soal PythonAnywhere free tier: akun free PythonAnywhere
MEMBATASI akses internet keluar (whitelist domain terbatas) — script ini
biasanya PALING GAMPANG dijalankan dari KOMPUTER LOKAL kamu ke staging/
production (bukan dari dalam Bash console PythonAnywhere itu sendiri),
kecuali domain target-nya kebetulan ada di whitelist PythonAnywhere.

Kode keluar:
  0 = semua pengecekan WAJIB lolos (WARNING boleh ada)
  1 = minimal 1 pengecekan WAJIB gagal
  2 = penggunaan command / URL tidak valid
"""

import argparse
import json
import sys
import time
from dataclasses import dataclass, field
from urllib.parse import urlsplit

import requests

STATUS_OK = "OK"
STATUS_WARNING = "WARNING"
STATUS_FAILED = "FAILED"

_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}
_ALLOWED_SCHEMES = {"http", "https"}

DEFAULT_TIMEOUT_SECONDS = 10
DEFAULT_MAX_RESPONSE_MS = 3000


@dataclass
class CheckResult:
    name: str
    status: str
    detail: str = ""
    required: bool = True


@dataclass
class Report:
    target: str
    results: list = field(default_factory=list)

    def add(self, name, status, detail="", required=True):
        self.results.append(CheckResult(name=name, status=status, detail=detail, required=required))

    def exit_code(self):
        if any(r.status == STATUS_FAILED and r.required for r in self.results):
            return 1
        return 0

    def to_dict(self):
        return {
            "target": self.target,
            "checks": [
                {"name": r.name, "status": r.status, "detail": r.detail, "required": r.required}
                for r in self.results
            ],
            "exit_code": self.exit_code(),
        }


def _print_human(report: Report):
    print(f"Post-deploy smoke test — target: {report.target}")
    print("-" * 60)
    width = max((len(r.name) for r in report.results), default=10)
    for r in report.results:
        marker = "*" if not r.required else " "
        line = f"[{r.status:<7}]{marker} {r.name:<{width}}"
        if r.detail:
            line += f" — {r.detail}"
        print(line)
    print("-" * 60)


class SmokeTestError(Exception):
    """Kesalahan penggunaan/konfigurasi (bukan hasil pengecekan) — bikin script keluar dengan kode 2."""


def validate_base_url(raw_url: str) -> str:
    """
    Validasi URL SEBELUM request apa pun dikirim — tolak skema aneh,
    kredensial ke-embed di URL (user:pass@host), dan paksa HTTPS buat host
    non-lokal. Balikin base URL yang udah dibersihkan trailing slash-nya.
    """
    if not raw_url or not raw_url.strip():
        raise SmokeTestError("--base-url kosong")

    parsed = urlsplit(raw_url.strip())

    if parsed.scheme not in _ALLOWED_SCHEMES:
        raise SmokeTestError(f"Skema URL nggak didukung: {parsed.scheme!r} (cuma http/https)")

    if parsed.username or parsed.password:
        raise SmokeTestError("URL nggak boleh mengandung kredensial ter-embed (user:pass@host)")

    if not parsed.hostname:
        raise SmokeTestError("URL nggak punya hostname yang valid")

    is_local = parsed.hostname in _LOCAL_HOSTS
    if not is_local and parsed.scheme != "https":
        raise SmokeTestError(f"HTTPS wajib buat host non-lokal ({parsed.hostname!r}) — dapat skema {parsed.scheme!r}")

    return raw_url.strip().rstrip("/")


def _same_host(url_a: str, url_b: str) -> bool:
    return urlsplit(url_a).hostname == urlsplit(url_b).hostname


def run(base_url: str, timeout_seconds: float, max_response_ms: float, allow_cross_host_redirect: bool) -> Report:
    report = Report(target=base_url)
    health_url = f"{base_url}/health"

    start = time.monotonic()
    try:
        # allow_redirects=False SENGAJA — kita mau PERIKSA redirect-nya
        # sendiri (termasuk ke host lain) sebelum mutusin ngikutin apa
        # nggak, bukan diam-diam ngikutin apa pun yang dibalikin server.
        resp = requests.get(health_url, timeout=timeout_seconds, allow_redirects=False)
    except requests.exceptions.Timeout:
        report.add("http_request", STATUS_FAILED, f"Timeout setelah {timeout_seconds}s")
        return report
    except requests.exceptions.SSLError:
        report.add("http_request", STATUS_FAILED, "Sertifikat TLS nggak valid")
        return report
    except requests.exceptions.ConnectionError:
        report.add("http_request", STATUS_FAILED, "Gagal konek ke server")
        return report
    except requests.exceptions.RequestException as exc:
        report.add("http_request", STATUS_FAILED, f"Request gagal ({exc.__class__.__name__})")
        return report
    elapsed_ms = (time.monotonic() - start) * 1000

    if resp.is_redirect or resp.status_code in (301, 302, 303, 307, 308):
        location = resp.headers.get("Location", "")
        cross_host = location and not _same_host(health_url, location)
        if cross_host and not allow_cross_host_redirect:
            redirect_host = urlsplit(location).hostname or "?"
            report.add("no_unexpected_redirect", STATUS_FAILED, f"Redirect ke host lain ({redirect_host}) ditolak — pakai --allow-cross-host-redirect kalau ini disengaja")
            return report
        report.add("no_unexpected_redirect", STATUS_WARNING, "Server mengembalikan redirect (host sama atau diizinkan eksplisit)", required=False)
        # SENGAJA nggak ngikutin redirect-nya sendiri lebih jauh — laporan
        # ini cukup buat operator investigasi manual kalau perlu.
        return report
    report.add("no_unexpected_redirect", STATUS_OK, "Nggak ada redirect", required=False)

    report.add("http_status", STATUS_OK if resp.status_code == 200 else STATUS_FAILED, f"HTTP {resp.status_code}")
    if resp.status_code != 200:
        return report

    content_type = resp.headers.get("Content-Type", "")
    if "application/json" in content_type:
        report.add("content_type", STATUS_OK, content_type)
    else:
        report.add("content_type", STATUS_FAILED, f"Content-Type bukan JSON ({content_type or 'kosong'})")
        return report

    try:
        body = resp.json()
    except ValueError:
        report.add("json_body", STATUS_FAILED, "Body respons bukan JSON yang valid")
        return report
    report.add("json_body", STATUS_OK, "Body respons JSON valid")

    if not isinstance(body, dict) or "status" not in body:
        report.add("health_shape", STATUS_FAILED, "Field 'status' nggak ada di respons")
        return report

    status_value = body.get("status")
    if status_value == "ok":
        report.add("health_shape", STATUS_OK, "status: ok")
        if body.get("database") == "ok":
            report.add("database_field", STATUS_OK, "database: ok")
        else:
            report.add("database_field", STATUS_FAILED, "Field 'database' bukan 'ok'")
    else:
        report.add("health_shape", STATUS_FAILED, f"status: {status_value!r} (bukan 'ok') — deployment terdeteksi degraded/nggak sehat")
        return report

    if body.get("request_id"):
        report.add("request_id_in_body", STATUS_OK, "Field 'request_id' ada di body", required=False)
    else:
        report.add("request_id_in_body", STATUS_WARNING, "Field 'request_id' nggak ada di body", required=False)

    if resp.headers.get("X-Request-ID"):
        report.add("request_id_header", STATUS_OK, "Header X-Request-ID ada")
    else:
        report.add("request_id_header", STATUS_FAILED, "Header X-Request-ID nggak ada di respons")

    if elapsed_ms <= max_response_ms:
        report.add("response_time", STATUS_OK, f"{elapsed_ms:.0f} ms", required=False)
    else:
        report.add("response_time", STATUS_WARNING, f"{elapsed_ms:.0f} ms (batas {max_response_ms:.0f} ms)", required=False)

    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base-url", required=True, help="Base URL API, contoh: https://xaleena.pythonanywhere.com/api")
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_SECONDS, help=f"Timeout request dalam detik (default: {DEFAULT_TIMEOUT_SECONDS}).")
    parser.add_argument("--max-response-ms", type=float, default=DEFAULT_MAX_RESPONSE_MS, help=f"Batas waktu respons wajar dalam ms, cuma WARNING kalau kelewat (default: {DEFAULT_MAX_RESPONSE_MS}).")
    parser.add_argument("--allow-cross-host-redirect", action="store_true", help="Izinkan redirect ke host LAIN dari base-url (default: ditolak).")
    parser.add_argument("--json", action="store_true", help="Output JSON (tetap privacy-safe — cuma status/detail per pengecekan).")
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)

    try:
        base_url = validate_base_url(args.base_url)
    except SmokeTestError as exc:
        print(f"GAGAL: {exc}", file=sys.stderr)
        return 2

    if args.timeout <= 0:
        print("GAGAL: --timeout harus > 0", file=sys.stderr)
        return 2

    report = run(base_url, args.timeout, args.max_response_ms, args.allow_cross_host_redirect)

    if args.json:
        print(json.dumps(report.to_dict(), indent=2, sort_keys=True))
    else:
        _print_human(report)

    return report.exit_code()


if __name__ == "__main__":
    sys.exit(main())
