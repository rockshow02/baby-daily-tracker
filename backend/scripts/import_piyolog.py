"""
Import data riwayat dari file PDF export PiyoLog ke Baby Daily Tracker.

PiyoLog menyimpan tiap hari dalam 2 kolom (pagi & sore/malam) plus kolom jam
dekoratif di kanan. Script ini membaca posisi X tiap kata buat misahin kolom,
gabungin ulang berdasar urutan waktu sebenarnya, lalu kirim ke API app ini.

Yang di-import otomatis:
  - Menyusui/botol (ml)      -> feeding-logs
  - Sleep / Wake-up (durasi) -> sleep-logs (dipasangkan start & end)
  - Pee / Poop                -> diaper-logs
  - Baths                     -> activity-logs (bathing)
  - Vitamin D                 -> medication-logs
  - Suhu (°C)                 -> temperature-logs
  - Tinggi (cm) / Berat (kg)  -> growth-measurements (digabung per hari)

Yang TIDAK bisa di-import otomatis (dicatat di ringkasan akhir buat
dimasukkan manual, karena nama vaksin spesifiknya nggak tercatat di PDF):
  - "Vaccine" (generik, tanpa nama vaksin)

CARA PAKAI:
    pip install pdfplumber requests --break-system-packages
    python import_piyolog.py \
        --pdf piyolog-export.pdf \
        --api-url http://localhost:5000/api \
        --email kamu@email.com \
        --password rahasia \
        --child-name "xaleena" \
        --feed-type sufor \
        --dry-run

Hapus --dry-run kalau hasil ringkasannya udah sesuai ekspektasi dan siap
beneran diimport.
"""
import argparse
import re
from collections import defaultdict
from datetime import datetime, timedelta

import pdfplumber
import requests


DATE_RE = re.compile(r"^([A-Za-z]{3}, \d{1,2} [A-Za-z]{3} \d{4})")
FULL_TIME_RE = re.compile(r"^(\d{1,2}):(\d{2})\s+(.*)$")
PARTIAL_TIME_RE = re.compile(r"^:(\d{2})\s+(.*)$")
ML_RE = re.compile(r"^(\d+)ml$")
WAKEUP_RE = re.compile(r"^Wake-up \((\d+)h (\d+)m\)$")
TEMP_RE = re.compile(r"^([\d.]+)°C$")
CM_RE = re.compile(r"^([\d.]+)cm$")
KG_RE = re.compile(r"^([\d.]+)kg$")

MONTH_MAP = {
    "Jan": 1, "Feb": 2, "Mar": 3, "Apr": 4, "May": 5, "Jun": 6,
    "Jul": 7, "Aug": 8, "Sep": 9, "Oct": 10, "Nov": 11, "Dec": 12,
}


def parse_date_header(line):
    """'Fri, 5 Jun 2026 0 mo 0 d' -> date(2026, 6, 5)"""
    m = DATE_RE.match(line)
    if not m:
        return None
    parts = line.split(",")[1].strip().split()
    day, mon, year = int(parts[0]), MONTH_MAP[parts[1]], int(parts[2])
    return datetime(year, mon, day).date()


def reconstruct_column(words, x_min, x_max):
    """Gabungin kata-kata dalam rentang X jadi baris teks, urut dari atas ke bawah."""
    col_words = [w for w in words if x_min <= w["x0"] < x_max]
    col_words.sort(key=lambda w: (round(w["top"]), w["x0"]))
    lines = {}
    for w in col_words:
        key = round(w["top"] / 3) * 3  # toleransi biar kata di baris sama nggak kepisah
        lines.setdefault(key, []).append(w)
    out = []
    for key in sorted(lines.keys()):
        row = sorted(lines[key], key=lambda w: w["x0"])
        out.append(" ".join(w["text"] for w in row))
    return out


def parse_timeline(lines):
    """
    Parse baris-baris 'H:MM Label' / ':MM Label' jadi list (hour, minute, label).
    Baris yang nggak cocok pola waktu (header, ringkasan) dilewati.
    """
    events = []
    current_hour = None
    for line in lines:
        m = FULL_TIME_RE.match(line)
        if m:
            current_hour = int(m.group(1))
            minute = int(m.group(2))
            rest = m.group(3).strip()
            events.append((current_hour, minute, rest))
            continue
        m = PARTIAL_TIME_RE.match(line)
        if m and current_hour is not None:
            minute = int(m.group(1))
            rest = m.group(2).strip()
            events.append((current_hour, minute, rest))
    return events


def parse_pdf(pdf_path):
    """Return list of dict {date, events: [(datetime, label), ...]}"""
    days = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            first_line = text.split("\n")[0] if text else ""
            day_date = parse_date_header(first_line)
            if not day_date:
                continue  # halaman cover / growth chart, bukan halaman harian

            words = page.extract_words()
            left_lines = reconstruct_column(words, 0, 260)
            right_lines = reconstruct_column(words, 260, 440)

            raw_events = parse_timeline(left_lines) + parse_timeline(right_lines)
            events = []
            for hour, minute, label in raw_events:
                dt = datetime(day_date.year, day_date.month, day_date.day, hour, minute)
                events.append((dt, label))
            events.sort(key=lambda e: e[0])
            days.append({"date": day_date, "events": events})
    return days


def structure_events(days, feed_type_for_bottle):
    """
    Ubah events mentah jadi list record terstruktur siap dikirim ke API.
    Return dict per kategori + summary.
    """
    feeding = []
    sleep_pairs = []
    diaper = []
    activity = []
    medication = []
    temperature = []
    growth_by_date = defaultdict(dict)
    unmatched_vaccine = []
    skipped = []

    pending_sleep_start = None

    all_events = []
    for day in days:
        all_events.extend(day["events"])
    all_events.sort(key=lambda e: e[0])

    for dt, label in all_events:
        m = ML_RE.match(label)
        if m:
            feeding.append({"timestamp": dt, "feed_type": feed_type_for_bottle, "volume_ml": int(m.group(1))})
            continue

        if label == "Sleep":
            pending_sleep_start = dt
            continue

        m = WAKEUP_RE.match(label)
        if m:
            if pending_sleep_start:
                sleep_pairs.append({"start_time": pending_sleep_start, "end_time": dt})
                pending_sleep_start = None
            # kalau nggak ada pending_sleep_start (Wake-up pertama tanpa Sleep sebelumnya,
            # biasanya karena tidur dimulai di hari sebelumnya / sebelum rentang PDF), dilewati
            continue

        if label == "Pee":
            diaper.append({"timestamp": dt, "diaper_type": "pipis"})
            continue
        if label == "Poop":
            diaper.append({"timestamp": dt, "diaper_type": "pup"})
            continue
        if label == "Baths":
            activity.append({"timestamp": dt, "activity_type": "bathing"})
            continue
        if label == "Vitamin D":
            medication.append({"timestamp": dt, "medication_name": "Vitamin D"})
            continue
        if label == "Vaccine":
            unmatched_vaccine.append(dt)
            continue

        m = TEMP_RE.match(label)
        if m:
            temperature.append({"timestamp": dt, "temperature_celsius": float(m.group(1)), "method": "ketiak"})
            continue

        m = CM_RE.match(label)
        if m:
            growth_by_date[dt.date()]["height_cm"] = float(m.group(1))
            continue

        m = KG_RE.match(label)
        if m:
            growth_by_date[dt.date()]["weight_kg"] = float(m.group(1))
            continue

        skipped.append((dt, label))

    growth = [{"measured_date": d, **vals} for d, vals in sorted(growth_by_date.items())]

    return {
        "feeding": feeding,
        "sleep": sleep_pairs,
        "diaper": diaper,
        "activity": activity,
        "medication": medication,
        "temperature": temperature,
        "growth": growth,
        "unmatched_vaccine": unmatched_vaccine,
        "skipped": skipped,
    }


def print_summary(structured):
    print("\n=== RINGKASAN HASIL PARSING ===")
    print(f"Menyusui/botol : {len(structured['feeding'])} entri")
    print(f"Tidur          : {len(structured['sleep'])} sesi")
    print(f"Popok          : {len(structured['diaper'])} entri")
    print(f"Aktivitas      : {len(structured['activity'])} entri (mandi)")
    print(f"Obat/Vitamin   : {len(structured['medication'])} entri")
    print(f"Suhu           : {len(structured['temperature'])} entri")
    print(f"Pertumbuhan    : {len(structured['growth'])} hari punya data berat/tinggi")
    if structured["unmatched_vaccine"]:
        print(f"\n⚠️  {len(structured['unmatched_vaccine'])} catatan 'Vaccine' generik TIDAK di-import otomatis")
        print("   (nama vaksin spesifiknya nggak ada di PDF). Tanggalnya:")
        for dt in structured["unmatched_vaccine"]:
            print(f"     - {dt.date()} — isi manual di tab Sehat > Vaksin")
    if structured["skipped"]:
        print(f"\n⚠️  {len(structured['skipped'])} baris nggak dikenali polanya (dilewati):")
        for dt, label in structured["skipped"][:20]:
            print(f"     - {dt} : {label}")


def run_import(base_url, session, child_id, structured):
    def post(path, payload):
        payload = dict(payload)
        for k in ("timestamp", "start_time", "end_time", "measured_date"):
            if k in payload and hasattr(payload[k], "isoformat"):
                payload[k] = payload[k].isoformat()
        r = session.post(f"{base_url}{path}", json=payload)
        if not r.ok:
            print(f"  GAGAL {path}: {r.status_code} {r.text[:200]}")
        return r

    print("\n=== MENGIMPOR ===")
    for item in structured["feeding"]:
        post(f"/children/{child_id}/feeding-logs", item)
    print(f"  feeding: {len(structured['feeding'])} selesai")

    for item in structured["sleep"]:
        post(f"/children/{child_id}/sleep-logs", item)
    print(f"  sleep: {len(structured['sleep'])} selesai")

    for item in structured["diaper"]:
        post(f"/children/{child_id}/diaper-logs", item)
    print(f"  diaper: {len(structured['diaper'])} selesai")

    for item in structured["activity"]:
        post(f"/children/{child_id}/activity-logs", item)
    print(f"  activity: {len(structured['activity'])} selesai")

    for item in structured["medication"]:
        post(f"/children/{child_id}/medication-logs", item)
    print(f"  medication: {len(structured['medication'])} selesai")

    for item in structured["temperature"]:
        post(f"/children/{child_id}/temperature-logs", item)
    print(f"  temperature: {len(structured['temperature'])} selesai")

    for item in structured["growth"]:
        post(f"/children/{child_id}/growth-measurements", item)
    print(f"  growth: {len(structured['growth'])} selesai")

    print("\n✅ Import selesai.")


def main():
    parser = argparse.ArgumentParser(description="Import export PDF PiyoLog ke Baby Daily Tracker")
    parser.add_argument("--pdf", required=True)
    parser.add_argument("--api-url", required=True, help="cth. http://localhost:5000/api")
    parser.add_argument("--email", required=True)
    parser.add_argument("--password", required=True)
    parser.add_argument("--child-id", type=int, help="ID anak tujuan (lihat di app/GET /children)")
    parser.add_argument("--child-name", help="Nama anak tujuan (dicari otomatis kalau --child-id kosong)")
    parser.add_argument("--feed-type", default="sufor", choices=["sufor", "asi_perah"],
                         help="Semua entri Nml di PDF akan diimport sebagai jenis ini (default: sufor)")
    parser.add_argument("--dry-run", action="store_true", help="Cuma tampilkan ringkasan, jangan kirim ke API")
    args = parser.parse_args()

    print("Membaca PDF...")
    days = parse_pdf(args.pdf)
    print(f"Ditemukan {len(days)} halaman harian.")

    structured = structure_events(days, args.feed_type)
    print_summary(structured)

    if args.dry_run:
        print("\n(--dry-run aktif, tidak ada data yang dikirim ke server)")
        return

    session = requests.Session()
    login = session.post(f"{args.api_url}/auth/login", json={"email": args.email, "password": args.password})
    if not login.ok:
        print(f"Login gagal: {login.status_code} {login.text}")
        return

    child_id = args.child_id
    if not child_id:
        children = session.get(f"{args.api_url}/children").json()
        matches = [c for c in children if c["name"].lower() == (args.child_name or "").lower()]
        if not matches:
            print(f"Anak dengan nama '{args.child_name}' tidak ditemukan. Anak yang ada: {[c['name'] for c in children]}")
            return
        child_id = matches[0]["id"]
        print(f"Anak ditemukan: {matches[0]['name']} (id={child_id})")

    run_import(args.api_url, session, child_id, structured)


if __name__ == "__main__":
    main()