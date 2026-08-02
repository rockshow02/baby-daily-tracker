import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from extensions import db
from models import Article

ARTICLES = [
    # ---------- FEEDING ----------
    {
        "category": "feeding",
        "title": "Tanda Bayi Cukup Menyusu",
        "summary": "Cara paling gampang mastiin ASI/sufor yang diterima bayi udah cukup.",
        "body": (
            "Banyak orang tua baru khawatir apakah bayinya cukup minum, apalagi kalau menyusui langsung "
            "sehingga volumenya nggak kelihatan. Beberapa tanda yang bisa dipantau: popok basah minimal "
            "6 kali sehari sejak usia 6 hari ke atas, berat badan naik sesuai kurva pertumbuhan, bayi "
            "terlihat tenang dan puas setelah menyusu (bukan terus-menerus rewel), dan pola BAB yang "
            "konsisten (untuk bayi ASI eksklusif, BAB bisa beberapa kali sehari atau bahkan cuma "
            "beberapa hari sekali setelah usia beberapa minggu, keduanya normal selama konsistensinya "
            "lunak). Kalau berat badan nggak naik sesuai kurva selama 2 kali penimbangan berturut-turut, "
            "atau popok basah kurang dari 6 kali sehari setelah usia 1 minggu, sebaiknya konsultasi ke "
            "dokter anak atau konselor laktasi."
        ),
        "min_age_months": None,
        "max_age_months": 12,
        "source": "IDAI",
        "order_index": 1,
    },
    {
        "category": "feeding",
        "title": "Kapan Waktu yang Tepat Mulai MPASI?",
        "summary": "IDAI merekomendasikan usia 6 bulan, ini alasan dan tanda kesiapannya.",
        "body": (
            "IDAI dan WHO merekomendasikan pemberian ASI eksklusif sampai usia 6 bulan penuh, baru "
            "setelah itu diperkenalkan Makanan Pendamping ASI (MPASI). Alasannya, sistem pencernaan "
            "bayi di bawah 6 bulan belum cukup matang buat mencerna makanan padat, dan ASI/sufor "
            "sendiri udah mencukupi seluruh kebutuhan gizi di periode itu. Tanda bayi siap MPASI selain "
            "usia: bisa duduk dengan sedikit bantuan dan kepala tegak stabil, hilangnya refleks "
            "menjulurkan lidah (tongue-thrust reflex) yang bikin makanan otomatis terdorong keluar, "
            "dan menunjukkan ketertarikan terhadap makanan (misal memperhatikan atau mencoba meraih "
            "makanan orang lain). Mulai MPASI terlalu dini (sebelum 4 bulan) berisiko meningkatkan "
            "gangguan pencernaan dan alergi, sementara terlalu telat (setelah 6 bulan) berisiko "
            "kekurangan zat besi dan nutrisi penting lainnya."
        ),
        "min_age_months": 3,
        "max_age_months": 8,
        "source": "IDAI",
        "order_index": 2,
    },
    # ---------- SLEEP ----------
    {
        "category": "sleep",
        "title": "Berapa Lama Bayi Perlu Tidur?",
        "summary": "Kebutuhan tidur berubah drastis di tahun pertama, ini panduan per usia.",
        "body": (
            "Kebutuhan tidur bayi menurun bertahap seiring usia. Bayi baru lahir (0-3 bulan) biasanya "
            "butuh 14-17 jam sehari, tersebar dalam banyak sesi pendek karena lambungnya masih kecil "
            "dan perlu menyusu tiap beberapa jam, termasuk malam hari. Usia 4-11 bulan, kebutuhan turun "
            "jadi sekitar 12-15 jam, mulai terbentuk pola tidur malam yang lebih panjang plus 2-3 kali "
            "tidur siang. Usia 1-2 tahun, kebutuhan sekitar 11-14 jam dengan 1-2 kali tidur siang. "
            "Penting diingat, ini cuma rentang umum — tiap bayi punya variasi masing-masing, jadi yang "
            "lebih penting dipantau adalah apakah bayi terlihat cukup istirahat (tidak rewel berlebihan, "
            "aktif dan responsif saat bangun) ketimbang mengejar angka jam tertentu secara kaku."
        ),
        "min_age_months": None,
        "max_age_months": 24,
        "source": "IDAI",
        "order_index": 1,
    },
    {
        "category": "sleep",
        "title": "Praktik Tidur Aman buat Bayi",
        "summary": "Beberapa langkah sederhana buat mengurangi risiko SIDS.",
        "body": (
            "Sindrom Kematian Bayi Mendadak (SIDS) jarang terjadi tapi bisa dikurangi risikonya lewat "
            "beberapa praktik tidur yang direkomendasikan: selalu tidurkan bayi dalam posisi telentang "
            "(bukan tengkurap atau menyamping) sampai usia 1 tahun, gunakan kasur yang rata dan cukup "
            "keras (bukan empuk berlebihan), hindari benda-benda lepas di area tidur seperti bantal, "
            "guling, selimut tebal, atau boneka sampai usia 1 tahun, dan sebaiknya bayi tidur di kamar "
            "yang sama dengan orang tua (bukan satu kasur) minimal 6 bulan pertama. Hindari juga suhu "
            "ruangan yang terlalu panas — kenakan pakaian tidur yang cukup tanpa berlebihan lapisannya."
        ),
        "min_age_months": None,
        "max_age_months": 12,
        "source": "WHO",
        "order_index": 2,
    },
    # ---------- DIAPER ----------
    {
        "category": "diaper",
        "title": "Warna Pup Bayi: Kapan Perlu Waspada?",
        "summary": "Sebagian besar warna itu normal, tapi ada beberapa yang perlu diperiksakan.",
        "body": (
            "Warna dan konsistensi pup bayi berubah-ubah sesuai usia dan jenis makanan, dan sebagian "
            "besar variasi itu normal. Warna kuning kecokelatan, hijau, atau kuning mustard (khas bayi "
            "ASI) semuanya masuk kategori normal. Yang perlu diwaspadai dan sebaiknya diperiksakan ke "
            "dokter: warna putih pucat/dempul (bisa menandakan masalah hati/empedu), merah terang atau "
            "hitam pekat seperti aspal di luar beberapa hari pertama kelahiran (bisa menandakan "
            "perdarahan), atau konsistensi sangat cair terus-menerus disertai tanda dehidrasi seperti "
            "popok jarang basah dan bayi lesu (bisa menandakan diare berat). Perubahan warna sesekali "
            "biasanya nggak masalah, yang penting dipantau adalah pola yang konsisten dan kondisi bayi "
            "secara keseluruhan."
        ),
        "min_age_months": None,
        "max_age_months": 12,
        "source": "IDAI",
        "order_index": 1,
    },
    {
        "category": "diaper",
        "title": "Ruam Popok: Pencegahan dan Perawatan Rumahan",
        "summary": "Kulit kemerahan di area popok itu umum, begini cara mengatasinya.",
        "body": (
            "Ruam popok (diaper rash) terjadi karena kulit area popok yang lembap dan bersentuhan lama "
            "dengan urine/feses jadi iritasi. Cara mencegah: ganti popok sesering mungkin begitu basah "
            "atau kotor, biarkan kulit kering sepenuhnya sebelum pakai popok baru, dan sesekali beri "
            "waktu tanpa popok (diaper-free time) biar kulit 'bernapas'. Kalau ruam udah muncul, oleskan "
            "krim pelindung berbahan zinc oxide tiap ganti popok, hindari tisu basah beralkohol/pewangi, "
            "dan cukup bersihkan pakai air hangat serta kain lembut. Ruam biasanya membaik dalam 2-3 "
            "hari dengan perawatan rutin. Kalau ruam disertai lepuh, nanah, semakin parah setelah 3 hari "
            "perawatan, atau bayi demam, sebaiknya periksakan ke dokter karena bisa jadi infeksi jamur "
            "atau bakteri yang butuh obat khusus."
        ),
        "min_age_months": None,
        "max_age_months": 24,
        "source": "IDAI",
        "order_index": 2,
    },
    # ---------- GROWTH ----------
    {
        "category": "growth",
        "title": "Memahami Kurva Pertumbuhan WHO",
        "summary": "Persentil itu bukan soal 'ranking', ini cara membacanya yang benar.",
        "body": (
            "Kurva pertumbuhan WHO nunjukin sebaran berat/tinggi anak-anak sehat di seluruh dunia pada "
            "usia yang sama, bukan standar 'ideal' yang harus dikejar. Kalau berat badan anak ada di "
            "persentil ke-25, artinya dari 100 anak seusianya, sekitar 25 anak punya berat lebih rendah "
            "dan 75 anak punya berat lebih tinggi — ini tetap dianggap normal, bukan kekurangan. Yang "
            "lebih penting diperhatikan bukan posisi persentil di satu titik waktu, tapi **arah tren "
            "garisnya** dari waktu ke waktu. Anak yang konsisten di persentil ke-15 selama berbulan-"
            "bulan kemungkinan besar memang punya postur tubuh yang lebih kecil secara genetik dan itu "
            "normal buatnya. Yang perlu diwaspadai adalah kalau garis pertumbuhannya turun drastis "
            "memotong beberapa garis persentil dalam waktu singkat (misal dari persentil 50 ke persentil "
            "5), itu yang sebaiknya dikonsultasikan ke dokter."
        ),
        "min_age_months": None,
        "max_age_months": None,
        "source": "WHO",
        "order_index": 1,
    },
    {
        "category": "growth",
        "title": "Pentingnya Pengukuran Rutin di Posyandu",
        "summary": "Kenapa timbang & ukur bulanan itu lebih dari sekadar catatan angka.",
        "body": (
            "Pengukuran berat, tinggi, dan lingkar kepala secara rutin (idealnya tiap bulan di tahun "
            "pertama) penting karena bisa mendeteksi masalah pertumbuhan sejak dini, jauh sebelum "
            "gejala lain muncul. Stunting (tinggi badan yang jauh di bawah standar usianya) misalnya, "
            "seringkali nggak kelihatan jelas secara kasat mata pada bayi, tapi bisa terdeteksi lewat "
            "kurva pertumbuhan. Selain berat dan tinggi, lingkar kepala juga penting dipantau karena "
            "mencerminkan perkembangan otak — pertumbuhan yang terlalu lambat atau terlalu cepat "
            "sama-sama perlu dievaluasi lebih lanjut. Membawa anak rutin ke posyandu atau dokter buat "
            "pengukuran ini, meski anaknya kelihatan sehat-sehat aja, adalah salah satu cara deteksi "
            "dini paling efektif dan murah yang bisa dilakukan orang tua."
        ),
        "min_age_months": None,
        "max_age_months": 60,
        "source": "Kemenkes RI",
        "order_index": 2,
    },
    # ---------- VACCINATION ----------
    {
        "category": "vaccination",
        "title": "Kenapa Imunisasi Sesuai Jadwal Itu Penting?",
        "summary": "Bukan cuma melindungi anak sendiri, tapi juga anak-anak di sekitarnya.",
        "body": (
            "Vaksin bekerja dengan melatih sistem imun anak mengenali dan melawan penyakit tertentu "
            "sebelum benar-benar terpapar penyakit itu di dunia nyata. Jadwal imunisasi disusun "
            "berdasarkan usia di mana risiko penyakit tertentu paling tinggi dan sistem imun anak udah "
            "cukup matang buat merespons vaksin secara optimal — makanya penting diberikan tepat waktu, "
            "bukan cuma 'yang penting suatu saat diberikan'. Selain melindungi anak yang divaksin, "
            "cakupan imunisasi yang tinggi di suatu wilayah juga menciptakan 'kekebalan kelompok' (herd "
            "immunity) yang melindungi bayi-bayi lain yang belum cukup usia buat divaksin atau punya "
            "kondisi medis yang membuat mereka nggak bisa divaksin. Menunda-nunda imunisasi tanpa "
            "alasan medis yang jelas meningkatkan risiko anak (dan lingkungan sekitarnya) terpapar "
            "penyakit yang sebenarnya bisa dicegah."
        ),
        "min_age_months": None,
        "max_age_months": None,
        "source": "Kemenkes RI",
        "order_index": 1,
    },
    {
        "category": "vaccination",
        "title": "Efek Samping Vaksin: Mana yang Normal?",
        "summary": "Demam ringan dan rewel setelah vaksin itu umum, ini yang perlu diwaspadai.",
        "body": (
            "Setelah imunisasi, cukup umum kalau anak mengalami demam ringan (biasanya di bawah 38.5°C), "
            "rewel, bengkak/kemerahan ringan di area suntikan, atau agak lesu selama 1-2 hari — ini "
            "tanda sistem imun sedang membangun perlindungan, dan biasanya hilang sendiri tanpa "
            "penanganan khusus. Kompres hangat di area suntikan dan pastikan anak cukup cairan biasanya "
            "cukup membantu. Yang perlu segera dibawa ke dokter: demam tinggi di atas 39°C, tangisan "
            "yang nggak biasa dan terus-menerus lebih dari 3 jam, kejang, ruam merah yang menyebar "
            "cepat ke seluruh tubuh, atau tanda reaksi alergi berat seperti sesak napas dan bengkak "
            "wajah/bibir (biasanya muncul dalam beberapa menit sampai jam setelah suntikan, dan ini "
            "kondisi darurat). Reaksi alergi berat ini sangat jarang terjadi, dan risikonya jauh lebih "
            "kecil dibanding risiko komplikasi penyakit yang dicegah oleh vaksin itu sendiri."
        ),
        "min_age_months": None,
        "max_age_months": None,
        "source": "IDAI",
        "order_index": 2,
    },
    # ---------- HEALTH ----------
    {
        "category": "health",
        "title": "Kapan Demam Anak Perlu Dibawa ke Dokter?",
        "summary": "Panduan umum berdasar usia dan tinggi suhu.",
        "body": (
            "Demam sebenarnya adalah respons tubuh yang normal buat melawan infeksi, bukan penyakit itu "
            "sendiri — jadi nggak semua demam perlu obat penurun panas atau ke dokter buru-buru. Namun, "
            "ada beberapa patokan kapan sebaiknya segera periksa ke dokter: bayi di bawah 3 bulan dengan "
            "suhu rektal 38°C atau lebih (di usia ini, demam sekecil apapun perlu dievaluasi karena "
            "sistem imun masih sangat rentan), anak usia berapapun dengan suhu di atas 39-40°C, demam "
            "yang bertahan lebih dari 3 hari, atau demam yang disertai gejala lain seperti kejang, ruam "
            "yang nggak hilang saat ditekan, kesulitan bernapas, muntah terus-menerus, atau anak "
            "terlihat sangat lesu/sulit dibangunkan. Selama anak masih aktif, mau minum, dan responsif "
            "meski suhunya naik, umumnya bisa dipantau dulu di rumah dengan cairan yang cukup dan "
            "istirahat."
        ),
        "min_age_months": None,
        "max_age_months": 60,
        "source": "Kemenkes RI",
        "order_index": 1,
    },
    {
        "category": "health",
        "title": "Cara Mengukur Suhu Tubuh Anak dengan Akurat",
        "summary": "Metode dan alat beda-beda, ini yang perlu diperhatikan.",
        "body": (
            "Akurasi pengukuran suhu tergantung metode dan alat yang dipakai. Termometer digital di "
            "ketiak paling praktis dan aman buat bayi, tapi hasilnya cenderung sedikit lebih rendah "
            "dibanding suhu inti tubuh (perlu ditambah sekitar 0.5°C sebagai estimasi kasar). "
            "Termometer telinga (timpani) dan dahi (temporal) lebih cepat tapi bisa kurang akurat kalau "
            "posisinya nggak pas atau anak baru habis dari luar ruangan yang beda suhu. Termometer "
            "rektal dianggap paling akurat mendekati suhu inti tubuh, terutama buat bayi di bawah 3 "
            "bulan, tapi butuh teknik yang benar. Yang penting diingat: ambang batas 'demam' berbeda "
            "tergantung metode pengukurannya, jadi sebaiknya konsisten pakai satu metode yang sama saat "
            "memantau tren suhu anak dari waktu ke waktu, dan sebutkan metode yang dipakai saat "
            "melaporkan suhu ke dokter."
        ),
        "min_age_months": None,
        "max_age_months": 60,
        "source": "IDAI",
        "order_index": 2,
    },
    # ---------- MOOD ----------
    {
        "category": "mood",
        "title": "Memahami Arti di Balik Tangisan Bayi",
        "summary": "Tangisan itu bahasa utama bayi buat berkomunikasi kebutuhannya.",
        "body": (
            "Bayi belum bisa bicara, jadi tangisan adalah cara utama mereka menyampaikan kebutuhan — "
            "bisa berarti lapar, ngantuk, popok basah, kepanasan/kedinginan, ingin digendong, atau "
            "sekadar overstimulasi dan butuh suasana tenang. Seiring waktu, orang tua biasanya mulai "
            "bisa membedakan pola tangisan berdasarkan konteks (misal tangisan lapar cenderung berirama "
            "dan berulang, sementara tangisan kesakitan biasanya tiba-tiba dan melengking). Nggak perlu "
            "khawatir kalau belum bisa langsung 'menerjemahkan' tangisan bayi — ini keterampilan yang "
            "berkembang seiring waktu lewat trial and error, dan itu normal. Yang penting, merespons "
            "tangisan bayi dengan cepat dan konsisten di bulan-bulan awal justru membangun rasa aman "
            "dan kepercayaan, bukan 'memanjakan' seperti anggapan yang salah kaprah."
        ),
        "min_age_months": None,
        "max_age_months": 12,
        "source": "IDAI",
        "order_index": 1,
    },
    {
        "category": "mood",
        "title": "Kolik pada Bayi: Kapan Dianggap Normal?",
        "summary": "Menangis berjam-jam tanpa sebab jelas itu ada namanya, dan biasanya membaik sendiri.",
        "body": (
            "Kolik adalah istilah untuk tangisan berlebihan pada bayi sehat yang nggak jelas "
            "penyebabnya — umumnya didefinisikan sebagai menangis lebih dari 3 jam sehari, lebih dari 3 "
            "hari seminggu, selama lebih dari 3 minggu (aturan 'rule of three'). Biasanya muncul di "
            "usia 2-3 minggu, memuncak sekitar usia 6 minggu, dan mereda sendiri di usia 3-4 bulan. "
            "Penyebab pastinya belum diketahui pasti, tapi bukan tanda ada yang salah secara medis "
            "selama bayi tetap tumbuh dengan baik dan sehat di luar episode menangisnya. Cara "
            "menenangkan yang bisa dicoba: gendong dengan gerakan berayun lembut, suara white noise, "
            "bedong (swaddling), atau posisi tummy-to-tummy. Yang paling penting buat orang tua: kolik "
            "itu melelahkan secara emosional, jadi jangan ragu minta bantuan pasangan/keluarga buat "
            "bergantian, dan segera konsultasi dokter kalau menangisnya disertai demam, muntah, atau "
            "tanda sakit lainnya (karena itu bukan kolik biasa)."
        ),
        "min_age_months": 0,
        "max_age_months": 5,
        "source": "IDAI",
        "order_index": 2,
    },
    # ---------- MILESTONE ----------
    {
        "category": "milestone",
        "title": "Tahapan Perkembangan Motorik di Tahun Pertama",
        "summary": "Gambaran umum urutan kemampuan fisik bayi 0-12 bulan.",
        "body": (
            "Perkembangan motorik bayi umumnya mengikuti urutan dari kepala ke kaki (cephalocaudal) dan "
            "dari tengah tubuh ke ujung (proximodistal). Gambaran umum: usia 0-3 bulan mulai bisa "
            "mengangkat kepala saat tengkurap, usia 4-6 bulan mulai berguling dan menopang badan dengan "
            "lengan, usia 6-8 bulan mulai bisa duduk dengan atau tanpa bantuan, usia 8-10 bulan mulai "
            "merangkak dan bisa berdiri berpegangan, usia 9-12 bulan mulai berjalan sambil berpegangan "
            "(cruising) sampai beberapa mulai melangkah sendiri. Penting diingat rentang ini cukup "
            "lebar dan variasinya normal — ada bayi yang lompat tahap (misal nggak pernah merangkak, "
            "langsung jalan) dan itu juga masih dalam batas normal. Yang lebih penting dipantau adalah "
            "**progres** dari waktu ke waktu, bukan mengejar 'harus bisa di usia X bulan' secara kaku."
        ),
        "min_age_months": None,
        "max_age_months": 15,
        "source": "IDAI",
        "order_index": 1,
    },
    {
        "category": "milestone",
        "title": "Kapan Perlu Konsultasi Soal Keterlambatan Perkembangan?",
        "summary": "Tanda-tanda yang sebaiknya nggak ditunggu-tunggu buat dikonsultasikan.",
        "body": (
            "Meski rentang perkembangan normal cukup lebar, ada beberapa 'tanda bahaya' (red flags) "
            "yang sebaiknya langsung dikonsultasikan ke dokter anak, bukan ditunggu sendiri: belum bisa "
            "menegakkan kepala sama sekali di usia 4 bulan, belum bisa duduk dengan bantuan di usia 9 "
            "bulan, belum ada usaha merangkak/bergerak sama sekali di usia 12 bulan, belum bisa berjalan "
            "sama sekali (bahkan berpegangan) di usia 18 bulan, atau kehilangan kemampuan yang "
            "sebelumnya udah dikuasai (misalnya sebelumnya udah bisa duduk lalu tiba-tiba nggak bisa "
            "lagi — ini beda dari sekadar belum mencapai suatu kemampuan). Deteksi dini itu penting "
            "karena banyak intervensi (terapi fisik, terapi okupasi, dll) jauh lebih efektif kalau "
            "dimulai sedini mungkin. Konsultasi ke dokter bukan berarti langsung ada yang salah — "
            "seringkali cuma buat memastikan dan memberi ketenangan pikiran orang tua."
        ),
        "min_age_months": 3,
        "max_age_months": 24,
        "source": "IDAI",
        "order_index": 2,
    },
]


def seed():
    app = create_app()
    with app.app_context():
        existing = Article.query.count()
        if existing > 0:
            print(f"Sudah ada {existing} artikel di database, dihapus dulu biar nggak dobel...")
            Article.query.delete()
            db.session.commit()

        for item in ARTICLES:
            db.session.add(Article(**item))
        db.session.commit()
        print(f"Berhasil seed {len(ARTICLES)} artikel.")


if __name__ == "__main__":
    seed()