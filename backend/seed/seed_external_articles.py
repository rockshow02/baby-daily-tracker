"""
Seed artikel EKSTERNAL — beda dari seed_articles.py (yang isinya ditulis sendiri
dan dibaca langsung di app), artikel di sini nunjuk ke artikel ASLI di situs
IDAI/Kemenkes. Card-nya di app cuma nampilin ringkasan pendek + tombol
"Baca Selengkapnya" yang redirect ke sumber aslinya (source_url keisi).

Aman dijalankan berulang kali — cuma hapus & ganti artikel yang source_url-nya
keisi (nggak ganggu artikel hasil seed_articles.py yang source_url-nya kosong).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from extensions import db
from models import Article

EXTERNAL_ARTICLES = [
    # ---------- FEEDING ----------
    {
        "category": "feeding",
        "title": "Nilai Menyusui",
        "summary": "IDAI membahas manfaat ASI eksklusif dan tanda-tanda bayi tercukupi ASI-nya.",
        "body": (
            "Artikel resmi IDAI ini menjelaskan kenapa ASI eksklusif 6 bulan direkomendasikan, "
            "termasuk daftar tanda praktis buat cek apakah bayi udah cukup ASI (jumlah popok basah, "
            "kenaikan berat badan, dsb)."
        ),
        "source": "IDAI",
        "source_url": "https://www.idai.or.id/artikel/klinik/asi/nilai-menyusui",
        "order_index": 10,
    },
    {
        "category": "feeding",
        "title": "ASI Saya Kurang?",
        "summary": "Panduan IDAI buat orang tua yang khawatir produksi ASI-nya nggak cukup.",
        "body": (
            "Membahas cara meningkatkan produksi ASI lewat menyusui on-demand, serta menjelaskan "
            "kekhawatiran umum ibu baru soal kecukupan ASI yang seringkali nggak beralasan secara medis."
        ),
        "source": "IDAI",
        "source_url": "https://www.idai.or.id/artikel/klinik/pengasuhan-anak/asi-saya-kurang",
        "order_index": 11,
    },
    # ---------- SLEEP ----------
    {
        "category": "sleep",
        "title": "Perkembangan Tidur Normal Pada Batita",
        "summary": "IDAI menjelaskan bagaimana pola tidur bayi berkembang dari lahir sampai usia 3 tahun.",
        "body": (
            "Menjelaskan tahapan perkembangan ritme tidur-bangun bayi, dari yang belum teratur di awal "
            "kelahiran, sampai terbentuknya pola tidur malam yang lebih konsolidasi seiring usia."
        ),
        "source": "IDAI",
        "source_url": "https://www.idai.or.id/artikel/seputar-kesehatan-anak/perkembangan-tidur-normal-pada-batita",
        "order_index": 10,
    },
    {
        "category": "sleep",
        "title": "Bolehkah Bayi Tidur Tengkurap di Rumah?",
        "summary": "IDAI menjawab pertanyaan umum soal posisi tidur bayi dan pencegahan SIDS.",
        "body": (
            "Membahas rekomendasi posisi tidur telentang buat bayi, kapan tummy time boleh dilakukan "
            "(saat terjaga & diawasi), dan faktor-faktor lain yang berperan menurunkan risiko SIDS."
        ),
        "source": "IDAI",
        "source_url": "https://www.idai.or.id/artikel/klinik/pengasuhan-anak/bolehkah-bayi-tidur-tengkurap-di-rumah",
        "order_index": 11,
    },
    # ---------- DIAPER ----------
    {
        "category": "diaper",
        "title": "Cara Tepat Merawat Ruam Popok agar Si Kecil Kembali Nyaman",
        "summary": "Kemenkes RI membahas penyebab dan cara menangani ruam popok di rumah.",
        "body": (
            "Menjelaskan penyebab utama ruam popok (kontak lama dengan urine/feses), langkah pencegahan "
            "harian, dan kapan sebaiknya ruam popok diperiksakan ke tenaga kesehatan."
        ),
        "source": "Kemenkes RI",
        "source_url": "https://ayosehat.kemkes.go.id/cara-tepat-merawat-ruam-popok-agar-si-kecil-kembali-nyaman",
        "order_index": 10,
    },
    # ---------- GROWTH ----------
    {
        "category": "growth",
        "title": "IDAI Tekankan Pentingnya Kurva Pertumbuhan Anak",
        "summary": "Liputan pernyataan resmi IDAI soal cara membaca kurva pertumbuhan yang benar.",
        "body": (
            "IDAI mengingatkan pentingnya memakai kurva pertumbuhan yang sesuai populasi biar nggak "
            "salah diagnosis stunting, dan pentingnya pengukuran berulang buat melihat tren, bukan cuma "
            "satu titik waktu."
        ),
        "source": "Media Indonesia (liputan IDAI)",
        "source_url": "https://mediaindonesia.com/humaniora/880520/idai-tekankan-pentingnya-kurva-pertumbuhan-anak-untuk-deteksi-dini-gangguan-kesehatan",
        "order_index": 10,
    },
    {
        "category": "growth",
        "title": "Mengenal Apa Itu Stunting",
        "summary": "Kemenkes RI menjelaskan definisi, penyebab, dan pencegahan stunting.",
        "body": (
            "Membahas definisi stunting menurut WHO, cara membedakan anak stunting dari anak yang "
            "memang berpostur pendek secara genetik, dan pentingnya deteksi dini di 1000 hari pertama "
            "kehidupan."
        ),
        "source": "Kemenkes RI",
        "source_url": "https://yankes.kemkes.go.id/view_artikel/1388/mengenal-apa-itu-stunting",
        "order_index": 11,
    },
    # ---------- VACCINATION ----------
    {
        "category": "vaccination",
        "title": "Jadwal Imunisasi Anak IDAI",
        "summary": "Jadwal imunisasi resmi terbaru dari Ikatan Dokter Anak Indonesia.",
        "body": (
            "Jadwal lengkap dan resmi seluruh vaksin wajib dan tambahan menurut rekomendasi IDAI, "
            "termasuk vaksin kombinasi dan catch-up buat anak yang jadwalnya sempat tertunda."
        ),
        "source": "IDAI",
        "source_url": "https://www.idai.or.id/artikel/klinik/imunisasi/jadwal-imunisasi-anak-idai",
        "order_index": 10,
    },
    # ---------- HEALTH ----------
    {
        "category": "health",
        "title": "Penanganan Demam pada Anak",
        "summary": "IDAI menjelaskan cara menangani demam anak di rumah dan kapan harus ke dokter.",
        "body": (
            "Membahas kapan sebaiknya memberi obat penurun panas, penanganan non-obat seperti kompres "
            "dan cukup cairan, serta tanda-tanda yang perlu diwaspadai saat anak demam."
        ),
        "source": "IDAI",
        "source_url": "https://www.idai.or.id/artikel/klinik/keluhan-anak/penanganan-demam-pada-anak",
        "order_index": 10,
    },
    {
        "category": "health",
        "title": "Mengenal Kejang Demam pada Anak",
        "summary": "Kemenkes RI menjelaskan kejang demam, penyebab, dan pertolongan pertamanya.",
        "body": (
            "Membahas apa itu kejang demam, kelompok usia yang paling berisiko, dan langkah pertolongan "
            "pertama yang aman dilakukan orang tua sebelum mendapat bantuan medis."
        ),
        "source": "Kemenkes RI",
        "source_url": "https://keslan.kemkes.go.id/view_artikel/4179/mengenal-kejang-demam-pada-anak",
        "order_index": 11,
    },
    # ---------- MOOD ----------
    {
        "category": "mood",
        "title": "Kolik pada Bayi: Kenali Ciri, Penyebab, dan Cara Atasinya",
        "summary": "Penjelasan lengkap soal kolik, kondisi umum di balik tangisan bayi berjam-jam.",
        "body": (
            "Menjelaskan definisi kolik, kenapa itu bukan tanda penyakit, dan berbagai cara menenangkan "
            "bayi kolik yang bisa dicoba di rumah, sekaligus pentingnya orang tua juga menjaga "
            "kesejahteraan diri sendiri di fase ini."
        ),
        "source": "Nutriclub",
        "source_url": "https://www.nutriclub.co.id/artikel/kesehatan/4-6-bulan/redakan-kolik-pada-bayi",
        "order_index": 10,
    },
    # ---------- MILESTONE ----------
    {
        "category": "milestone",
        "title": "Milestones Bayi dan Hal-hal yang Perlu Bunda Pahami",
        "summary": "Panduan tahapan perkembangan bayi 0-12 bulan dari sisi emosional dan motorik.",
        "body": (
            "Membahas capaian perkembangan yang umum dilihat tiap rentang usia di tahun pertama, "
            "beserta cara sederhana orang tua bisa mendukung perkembangan itu di rumah."
        ),
        "source": "akudankau.co.id",
        "source_url": "https://www.akudankau.co.id/artikel/0-12-bulan/milestones-bayi",
        "order_index": 10,
    },
]


def seed():
    app = create_app()
    with app.app_context():
        existing = Article.query.filter(Article.source_url.isnot(None)).count()
        if existing > 0:
            print(f"Sudah ada {existing} artikel eksternal, dihapus dulu biar nggak dobel...")
            Article.query.filter(Article.source_url.isnot(None)).delete()
            db.session.commit()

        for item in EXTERNAL_ARTICLES:
            db.session.add(Article(**item))
        db.session.commit()
        print(f"Berhasil seed {len(EXTERNAL_ARTICLES)} artikel eksternal.")


if __name__ == "__main__":
    seed()