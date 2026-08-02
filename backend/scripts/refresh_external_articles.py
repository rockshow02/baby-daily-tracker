"""
Refresh otomatis artikel eksternal dari RSS feed resmi.

CATATAN PENTING soal cakupan: script ini nge-monitor RSS feed dari sumber
yang UDAH DIVERIFIKASI (Kemenkes RI), bukan "nyari di seluruh internet".
Nyari otomatis di seluruh internet butuh API pencarian (Google/Bing Custom
Search) yang berbayar buat pemakaian rutin, jadi nggak dipakai di sini biar
tetap gratis. Kalau nemu RSS feed sumber terpercaya lain (IDAI, rumah sakit
anak, dll), tambahin aja ke FEED_URLS di bawah.

Cara kerja:
  1. Ambil semua entry dari tiap RSS feed di FEED_URLS
  2. Cocokkan judul+ringkasan tiap entry ke kata kunci per kategori
  3. Entry yang cocok & belum ada di database (dicek dari source_url)
     otomatis ditambahkan sebagai artikel eksternal baru
  4. Entry yang nggak cocok kata kunci manapun dilewati (biar nggak
     kebanjiran berita kesehatan umum yang nggak relevan buat bayi)

CARA JALANIN:
  Manual:
    python scripts/refresh_external_articles.py

  Terjadwal (PythonAnywhere, gratis 1 task/hari):
    1. Buka tab "Tasks" di dashboard PythonAnywhere
    2. Command: python3.10 /home/USERNAME/baby-daily-tracker/backend/scripts/refresh_external_articles.py
    3. Set jam berapa aja (misal jam 03:00 pagi)
    Script ini aman dijalanin tiap hari (idempotent, skip yang udah ada),
    jadi walau "jadwal"-nya harian, efeknya sama kayak refresh mingguan/
    bulanan — cuma nambah kalau beneran ada artikel baru yang relevan.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import feedparser

from app import create_app
from extensions import db
from models import Article

FEED_URLS = [
    "https://upk.kemkes.go.id/new/feed/rss.php?cat=j",  # Kemenkes - Artikel
    "https://upk.kemkes.go.id/new/feed/rss.php?cat=l",  # Kemenkes - Berita
]

# kata kunci per kategori — entry RSS dicocokkan ke sini (case-insensitive)
CATEGORY_KEYWORDS = {
    "feeding": ["asi", "menyusui", "mpasi", "susu formula", "nutrisi bayi", "gizi bayi"],
    "sleep": ["tidur bayi", "tidur anak", "insomnia anak"],
    "diaper": ["popok", "ruam popok", "diare bayi"],
    "growth": ["tumbuh kembang", "stunting", "berat badan anak", "tinggi badan anak", "gizi buruk", "obesitas anak"],
    "vaccination": ["imunisasi", "vaksin anak", "vaksinasi bayi"],
    "health": ["demam anak", "sakit anak", "batuk pilek anak", "kejang demam", "penyakit anak"],
    "mood": ["menangis bayi", "kolik", "rewel"],
    "milestone": ["motorik anak", "perkembangan anak", "keterlambatan bicara", "merangkak", "belajar jalan"],
}


import re


def match_category(title, summary):
    text = f"{title} {summary}".lower()
    for category, keywords in CATEGORY_KEYWORDS.items():
        for kw in keywords:
            # \b (word boundary) biar "asi" nggak ke-match di dalam kata
            # "imunisasi", "vaksinasi", "mengatasi", dst — cuma cocok
            # kalau "asi" berdiri sebagai kata/frasa utuh
            pattern = r"\b" + re.escape(kw) + r"\b"
            if re.search(pattern, text):
                return category
    return None


def refresh():
    app = create_app()
    with app.app_context():
        existing_urls = {a.source_url for a in Article.query.filter(Article.source_url.isnot(None)).all()}

        added = 0
        skipped_existing = 0
        skipped_irrelevant = 0
        errors = 0

        for feed_url in FEED_URLS:
            print(f"Mengambil feed: {feed_url}")
            try:
                parsed = feedparser.parse(feed_url)
            except Exception as e:
                print(f"  GAGAL ambil feed: {e}")
                errors += 1
                continue

            if parsed.bozo:
                print(f"  Peringatan: feed mungkin malformed ({parsed.bozo_exception})")

            for entry in parsed.entries:
                link = entry.get("link")
                title = entry.get("title", "").strip()
                summary_raw = entry.get("summary", "") or entry.get("description", "")
                # ringkasan RSS kadang ada tag HTML, dibersihin kasar
                summary = summary_raw.replace("<p>", "").replace("</p>", " ").strip()[:250]

                if not link or not title:
                    continue

                if link in existing_urls:
                    skipped_existing += 1
                    continue

                category = match_category(title, summary)
                if not category:
                    skipped_irrelevant += 1
                    continue

                db.session.add(Article(
                    category=category,
                    title=title,
                    summary=summary or title,
                    body=summary or title,
                    source="Kemenkes RI (RSS)",
                    source_url=link,
                    order_index=50,  # taruh di bawah artikel kurasi manual
                ))
                existing_urls.add(link)
                added += 1
                print(f"  + [{category}] {title}")

        db.session.commit()
        print(f"\nSelesai. Ditambahkan: {added}, sudah ada: {skipped_existing}, "
              f"tidak relevan: {skipped_irrelevant}, error feed: {errors}")


if __name__ == "__main__":
    refresh()