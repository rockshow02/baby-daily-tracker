import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from extensions import db
from models import Article

# aktivitas stimulasi motorik per rentang usia — pelengkap milestone yang
# udah ada (milestone = target capaian, ini = CARA bantu capai target itu).
# Ditulis sendiri berdasar panduan umum stimulasi tumbuh kembang anak.
ACTIVITIES = [
    # ---------- 0-3 BULAN ----------
    {
        "category": "motor_activity",
        "title": "Tummy Time Rutin",
        "summary": "Latihan paling penting di 3 bulan pertama buat kekuatan leher & bahu.",
        "body": (
            "Telungkupkan bayi di permukaan rata beberapa menit, beberapa kali sehari (mulai dari "
            "1-2 menit, tingkatkan bertahap sesuai toleransinya). Ini melatih otot leher, bahu, dan "
            "punggung atas yang jadi fondasi buat kemampuan mengangkat kepala, lalu nanti duduk dan "
            "merangkak. Lakukan pas bayi lagi terjaga dan dalam pengawasan penuh — jangan pas ngantuk "
            "atau ditinggal sendirian. Kalau bayi rewel di awal, itu normal, coba lagi sesi pendek "
            "berikutnya, dan variasikan posisi (misal di atas dada orang tua sambil berbaring)."
        ),
        "min_age_months": 0,
        "max_age_months": 3,
        "source": "Panduan umum stimulasi tumbuh kembang",
        "order_index": 1,
    },
    {
        "category": "motor_activity",
        "title": "Mengikuti Objek dengan Mata",
        "summary": "Latihan koordinasi mata yang jadi cikal bakal koordinasi mata-tangan nanti.",
        "body": (
            "Gerakkan mainan berwarna kontras atau wajah kamu perlahan dari sisi ke sisi dalam jarak "
            "sekitar 20-30 cm dari wajah bayi, biarkan dia mengikuti gerakannya dengan mata (dan lama-"
            "lama kepala). Ini melatih kontrol otot mata dan leher, sekaligus fondasi buat kemampuan "
            "meraih benda yang berkembang beberapa bulan ke depan. Lakukan singkat aja, beberapa kali "
            "sehari, di saat bayi dalam kondisi tenang dan waspada (bukan pas ngantuk/rewel)."
        ),
        "min_age_months": 0,
        "max_age_months": 3,
        "source": "Panduan umum stimulasi tumbuh kembang",
        "order_index": 2,
    },
    # ---------- 3-6 BULAN ----------
    {
        "category": "motor_activity",
        "title": "Latihan Meraih Mainan",
        "summary": "Dorong bayi aktif meraih, bukan cuma dikasih mainan langsung ke tangan.",
        "body": (
            "Taruh mainan ringan dan mudah digenggam sedikit di luar jangkauan langsung bayi (bukan "
            "jauh banget, cukup bikin dia harus berusaha meraih). Ini melatih koordinasi mata-tangan "
            "dan kekuatan otot lengan. Variasikan tekstur dan bentuk mainan biar eksplorasi sensorik "
            "juga ikut terlatih. Kalau bayi udah bisa pegang, biarkan dia eksplorasi bebas (masukin ke "
            "mulut itu normal dan bagian dari cara bayi belajar), asal mainannya aman (nggak ada bagian "
            "kecil lepas)."
        ),
        "min_age_months": 3,
        "max_age_months": 6,
        "source": "Panduan umum stimulasi tumbuh kembang",
        "order_index": 1,
    },
    {
        "category": "motor_activity",
        "title": "Latihan Berguling",
        "summary": "Bantu bayi menemukan gerakan berguling lewat posisi dan mainan yang memancing.",
        "body": (
            "Pas bayi telentang, coba pegang mainan kesukaannya di satu sisi tubuhnya (agak tinggi, "
            "di luar jangkauan langsung) buat mancing dia muter badan ke arah situ. Bisa juga bantu "
            "gerakan awal dengan lembut menekuk satu kaki menyilang badan (jangan dipaksa). Sebagian "
            "bayi lebih dulu bisa guling dari tengkurap ke telentang, sebagian sebaliknya — keduanya "
            "normal. Selalu awasi penuh, dan pastikan area sekitarnya aman (nggak ada barang keras/"
            "tajam) karena bayi yang baru bisa guling suka kaget sama kemampuan barunya sendiri."
        ),
        "min_age_months": 3,
        "max_age_months": 6,
        "source": "Panduan umum stimulasi tumbuh kembang",
        "order_index": 2,
    },
    # ---------- 6-9 BULAN ----------
    {
        "category": "motor_activity",
        "title": "Latihan Duduk dengan Topangan Bertahap",
        "summary": "Kurangi topangan sedikit demi sedikit sambil bayi bangun keseimbangan intinya.",
        "body": (
            "Dudukkan bayi dikelilingi bantal empuk (jaga-jaga kalau oleng), atau topang punggungnya "
            "dengan tangan/lutut kamu, lalu perlahan kurangi topangan seiring waktu sambil ngasih "
            "mainan buat dia mainkan sambil duduk (ini melatih dia jaga keseimbangan sambil tangannya "
            "sibuk, mirip skill yang dia butuhin nanti). Sesi singkat tapi sering lebih efektif "
            "daripada 1 sesi lama. Kalau dia sering oleng ke satu sisi terus, itu masih normal di "
            "fase belajar — biasanya makin stabil dalam beberapa minggu latihan konsisten."
        ),
        "min_age_months": 6,
        "max_age_months": 9,
        "source": "Panduan umum stimulasi tumbuh kembang",
        "order_index": 1,
    },
    {
        "category": "motor_activity",
        "title": "Memancing Merangkak",
        "summary": "Taruh mainan sedikit di luar jangkauan pas bayi tengkurap, biar dia terdorong bergerak.",
        "body": (
            "Pas bayi tengkurap dan udah bisa nahan badan dengan tangan, taruh mainan favoritnya "
            "sedikit di depan/luar jangkauan langsungnya. Ini mendorong dia mencoba bergerak maju "
            "(awalnya sering mundur atau muter di tempat dulu sebelum beneran maju, itu normal). Kamu "
            "juga bisa jadi 'target' — duduk beberapa langkah di depannya sambil manggil/ajak "
            "interaksi. Sebagian bayi skip fase merangkak sama sekali dan langsung ke berdiri/jalan — "
            "itu juga varian normal, bukan tanda ada masalah."
        ),
        "min_age_months": 6,
        "max_age_months": 9,
        "source": "Panduan umum stimulasi tumbuh kembang",
        "order_index": 2,
    },
    # ---------- 9-12 BULAN ----------
    {
        "category": "motor_activity",
        "title": "Latihan Berdiri Berpegangan",
        "summary": "Manfaatkan furnitur rendah yang stabil buat bayi latihan menegakkan badan.",
        "body": (
            "Bantu bayi berdiri sambil berpegangan di furnitur rendah yang stabil (nggak gampang "
            "geser/jatuh) — misal sofa rendah atau meja kokoh. Taruh mainan di atas permukaan itu "
            "biar dia termotivasi berdiri buat menjangkaunya. Pastikan area sekitar empuk (karpet/"
            "matras) buat jaga-jaga kalau dia jatuh duduk (yang bakal sering terjadi, dan itu normal "
            "bagian dari proses belajar keseimbangan). Hindari baby walker beroda — itu justru bisa "
            "menghambat perkembangan otot yang dibutuhkan buat jalan sendiri."
        ),
        "min_age_months": 9,
        "max_age_months": 12,
        "source": "Panduan umum stimulasi tumbuh kembang",
        "order_index": 1,
    },
    {
        "category": "motor_activity",
        "title": "Cruising Sepanjang Furnitur",
        "summary": "Langkah transisi penting sebelum bayi berani lepas dari pegangan.",
        "body": (
            "Setelah bisa berdiri berpegangan, dorong bayi buat 'cruising' — jalan menyamping sambil "
            "berpegangan di furnitur. Taruh mainan menarik di ujung furnitur yang sama biar dia "
            "termotivasi bergerak ke arah situ. Kalau ada 2 furnitur stabil yang berjarak deket (sekitar "
            "selangkah), kamu bisa dorong dia coba 'lompat' pegangan dari satu ke yang lain — ini "
            "langkah penting sebelum berani lepas tangan sama sekali dan melangkah sendiri."
        ),
        "min_age_months": 9,
        "max_age_months": 12,
        "source": "Panduan umum stimulasi tumbuh kembang",
        "order_index": 2,
    },
    # ---------- 12-18 BULAN ----------
    {
        "category": "motor_activity",
        "title": "Latihan Jalan dengan Dorongan Ringan",
        "summary": "Pegang kedua tangan bayi dari belakang, biarkan dia yang gerakin kaki sendiri.",
        "body": (
            "Berdiri di belakang bayi, pegang kedua tangannya (bukan angkat dia), biarkan dia yang "
            "aktif melangkahkan kaki sendiri sambil dibantu keseimbangan dari pegangan itu. Latihan ini "
            "beda dari cuma 'digendong sambil kaki nempel lantai' — di sini bayi beneran latihan "
            "transfer berat badan antar kaki, skill inti buat jalan mandiri. Kurangi bantuan bertahap "
            "seiring dia makin percaya diri. Mainan dorong yang stabil (bukan yang gampang meluncur) "
            "juga bisa jadi alat bantu yang bagus di fase ini."
        ),
        "min_age_months": 12,
        "max_age_months": 18,
        "source": "Panduan umum stimulasi tumbuh kembang",
        "order_index": 1,
    },
    {
        "category": "motor_activity",
        "title": "Naik-Turun Tangga dengan Pendampingan",
        "summary": "Latihan koordinasi kaki yang lebih kompleks, selalu didampingi penuh.",
        "body": (
            "Kalau di rumah ada tangga pendek (atau bisa pakai anak tangga buatan/step stool rendah), "
            "dampingi bayi latihan naik dengan cara merangkak dulu (lebih aman) sebelum nanti jalan "
            "naik sambil berpegangan. Turun tangga biasanya lebih menakutkan buat bayi dan butuh lebih "
            "banyak waktu buat dikuasai — ajari dia turun mundur dengan merangkak dulu, itu lebih aman "
            "daripada coba jalan turun menghadap depan. WAJIB didampingi penuh setiap saat, dan pasang "
            "pagar pengaman tangga di rumah kalau belum ada."
        ),
        "min_age_months": 12,
        "max_age_months": 18,
        "source": "Panduan umum stimulasi tumbuh kembang",
        "order_index": 2,
    },
    # ---------- 18-24 BULAN ----------
    {
        "category": "motor_activity",
        "title": "Lempar dan Tendang Bola",
        "summary": "Melatih koordinasi seluruh tubuh dan keseimbangan saat bergerak.",
        "body": (
            "Main lempar-tangkap bola besar dan ringan (mudah dipegang), atau ajak dia menendang bola "
            "sambil berjalan. Ini melatih koordinasi mata-tangan/kaki, keseimbangan dinamis (jaga "
            "keseimbangan sambil bergerak, beda dari cuma berdiri diam), dan perencanaan gerak. Mulai "
            "dari jarak deket dan bola besar, tingkatkan jarak/kecilkan bola seiring kemampuannya "
            "berkembang. Aktivitas ini juga bagus buat melatih interaksi sosial gantian (lempar-balas "
            "lempar)."
        ),
        "min_age_months": 18,
        "max_age_months": 24,
        "source": "Panduan umum stimulasi tumbuh kembang",
        "order_index": 1,
    },
    {
        "category": "motor_activity",
        "title": "Lompat di Tempat",
        "summary": "Kemampuan motorik yang lebih maju, butuh koordinasi kedua kaki bersamaan.",
        "body": (
            "Contohkan lompat kecil di tempat (kedua kaki lepas dari lantai bersamaan) sambil ajak dia "
            "niru. Ini keterampilan yang lebih kompleks dari jalan/lari, jadi banyak anak di usia ini "
            "baru bisa 'lompat' dengan satu kaki masih nempel lantai — itu normal, kemampuan lompat "
            "penuh biasanya makin mantap mendekati usia 2-2.5 tahun. Lakukan di permukaan empuk (karpet/"
            "rumput) buat jaga-jaga kalau jatuh, dan jangan dipaksa kalau dia belum tertarik — anak "
            "biasanya spontan niru sendiri kalau ngeliat orang lain lompat-lompat dengan gembira."
        ),
        "min_age_months": 18,
        "max_age_months": 24,
        "source": "Panduan umum stimulasi tumbuh kembang",
        "order_index": 2,
    },
]


def seed():
    app = create_app()
    with app.app_context():
        existing = Article.query.filter_by(category="motor_activity").count()
        if existing > 0:
            print(f"Sudah ada {existing} artikel aktivitas motorik, dihapus dulu biar nggak dobel...")
            Article.query.filter_by(category="motor_activity").delete()
            db.session.commit()

        for item in ACTIVITIES:
            db.session.add(Article(**item))
        db.session.commit()
        print(f"Berhasil seed {len(ACTIVITIES)} artikel aktivitas motorik.")


if __name__ == "__main__":
    seed()