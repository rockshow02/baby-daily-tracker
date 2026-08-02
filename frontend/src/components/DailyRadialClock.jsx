const RADIUS = 120;
const CENTER = 140;
const RING_FEED = RADIUS;
const RING_SLEEP = RADIUS - 18;
const RING_DIAPER = RADIUS - 36;

/**
 * Ambil jam:menit dalam WIB, TIDAK bergantung timezone device — beda dari
 * date.getHours()/getMinutes() yang ngikutin timezone device/browser.
 * Kalau device nggak di-set WIB, itu bikin jarum & jam digital di sini
 * nunjuk ke posisi yang salah.
 */
function wibHourMinute(date) {
  const parts = new Intl.DateTimeFormat("en-GB", {
    timeZone: "Asia/Jakarta",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).formatToParts(date);
  const map = {};
  parts.forEach((p) => (map[p.type] = p.value));
  return { hour: Number(map.hour), minute: Number(map.minute) };
}

// jam 0 diletakkan di atas (jam 12), searah jarum jam — dipakai buat
// posisi TITIK aktivitas (menyusui/tidur/popok), skala 24 jam biar nggak
// ketuker pagi vs sore/malam sepanjang hari
function angleForTime(date) {
  const { hour, minute } = wibHourMinute(date);
  const hours = hour + minute / 60;
  return (hours / 24) * 360 - 90;
}

// khusus buat JARUM waktu sekarang: skala 12 jam kayak jam dinding beneran
// (puter penuh tiap 12 jam), BEDA dari angleForTime yang 24 jam di atas
function angleForNowHand(date) {
  const { hour, minute } = wibHourMinute(date);
  const hours12 = (hour % 12) + minute / 60;
  return (hours12 / 12) * 360 - 90;
}

function pointOnRing(ring, angleDeg) {
  const rad = (angleDeg * Math.PI) / 180;
  return {
    x: CENTER + ring * Math.cos(rad),
    y: CENTER + ring * Math.sin(rad),
  };
}

function polarArc(ring, startAngle, endAngle) {
  const start = pointOnRing(ring, startAngle);
  const end = pointOnRing(ring, endAngle);
  const largeArc = endAngle - startAngle <= 180 ? 0 : 1;
  return `M ${start.x} ${start.y} A ${ring} ${ring} 0 ${largeArc} 1 ${end.x} ${end.y}`;
}

const HOUR_MARKS = [0, 6, 12, 18];

/**
 * Titik-titik yang waktunya berdekatan (mis. 2x menyusui dalam beberapa
 * menit) posisinya jadi nyaris sama persis di lingkaran dan saling
 * ketumpuk. Fungsi ini "menyebarkan" titik yang sudutnya terlalu deket
 * (di bawah MIN_GAP_DEG) dengan geser radius-nya dikit keluar secara
 * bertahap, biar tetap semua kelihatan tanpa nutupin satu sama lain.
 */
function declutterAngles(items, baseRing) {
  const MIN_GAP_DEG = 7;
  const sorted = [...items].sort((a, b) => a.angle - b.angle);
  const placed = [];

  sorted.forEach((item) => {
    let ring = baseRing;
    let bump = 0;
    // selama masih ketabrak sama titik yang udah ditempatin di ring yang sama, geser keluar
    // eslint-disable-next-line no-constant-condition
    while (true) {
      const collision = placed.some(
        (p) => p.ring === ring && Math.abs(p.angle - item.angle) < MIN_GAP_DEG
      );
      if (!collision) break;
      bump += 1;
      ring = baseRing + bump * 6;
    }
    placed.push({ ...item, ring });
  });

  return placed;
}

export default function DailyRadialClock({ feedingLogs, sleepLogs, diaperLogs }) {
  const now = new Date();
  const nowAngle = angleForNowHand(now);

  const feedPoints = declutterAngles(
    feedingLogs.map((log) => ({ id: log.id, angle: angleForTime(new Date(log.timestamp)) })),
    RING_FEED
  );
  const diaperPoints = declutterAngles(
    diaperLogs.map((log) => ({ id: log.id, angle: angleForTime(new Date(log.timestamp)) })),
    RING_DIAPER
  );

  // jarum ala jam dinding: bentuk lancip solid (lebar di pangkal, runcing
  // di ujung) + ekor pendek di sisi berlawanan poros, kayak jam analog beneran
  const handLength = RADIUS + 4;
  const handTip = pointOnRing(handLength, nowAngle);
  const handTail = pointOnRing(-14, nowAngle);
  const handBaseWidth = 2;
  const perpAngle = nowAngle + 90;
  const baseLeft = {
    x: CENTER + handBaseWidth * Math.cos((perpAngle * Math.PI) / 180),
    y: CENTER + handBaseWidth * Math.sin((perpAngle * Math.PI) / 180),
  };
  const baseRight = {
    x: CENTER - handBaseWidth * Math.cos((perpAngle * Math.PI) / 180),
    y: CENTER - handBaseWidth * Math.sin((perpAngle * Math.PI) / 180),
  };

  return (
    <div className="relative flex items-center justify-center">
      <svg viewBox="0 0 280 280" className="w-full max-w-[280px]">
        {/* ring dasar */}
        <circle cx={CENTER} cy={CENTER} r={RING_FEED} fill="none" stroke="#F0E2CC" strokeWidth="1" />
        <circle cx={CENTER} cy={CENTER} r={RING_SLEEP} fill="none" stroke="#F0E2CC" strokeWidth="1" />
        <circle cx={CENTER} cy={CENTER} r={RING_DIAPER} fill="none" stroke="#F0E2CC" strokeWidth="1" />

        {/* penanda jam 00 / 06 / 12 / 18 */}
        {HOUR_MARKS.map((h) => {
          const angle = (h / 24) * 360 - 90;
          const outer = pointOnRing(RADIUS + 10, angle);
          const inner = pointOnRing(RADIUS + 2, angle);
          const label = pointOnRing(RADIUS + 22, angle);
          return (
            <g key={h}>
              <line x1={inner.x} y1={inner.y} x2={outer.x} y2={outer.y} stroke="#C7BAA9" strokeWidth="1" />
              <text
                x={label.x}
                y={label.y}
                fill="#C7BAA9"
                fontSize="9"
                fontFamily="Nunito, sans-serif"
                textAnchor="middle"
                dominantBaseline="middle"
              >
                {String(h).padStart(2, "0")}
              </text>
            </g>
          );
        })}

        {/* sesi tidur sebagai busur */}
        {sleepLogs.map((log) => {
          const start = new Date(log.start_time);
          const end = log.end_time ? new Date(log.end_time) : now;
          const startAngle = angleForTime(start);
          const endAngle = angleForTime(end);
          if (endAngle <= startAngle) return null;
          return (
            <path
              key={`sleep-${log.id}`}
              d={polarArc(RING_SLEEP, startAngle, endAngle)}
              stroke="#9B87E0"
              strokeWidth="6"
              strokeLinecap="round"
              fill="none"
              opacity="0.85"
            />
          );
        })}

        {/* menyusui sebagai titik, disebar kalau ketumpuk */}
        {feedPoints.map((pt) => {
          const p = pointOnRing(pt.ring, pt.angle);
          return <circle key={`feed-${pt.id}`} cx={p.x} cy={p.y} r="3.5" fill="#FFA733" stroke="#FFF8F0" strokeWidth="1" />;
        })}

        {/* popok sebagai titik, disebar kalau ketumpuk */}
        {diaperPoints.map((pt) => {
          const p = pointOnRing(pt.ring, pt.angle);
          return <circle key={`diaper-${pt.id}`} cx={p.x} cy={p.y} r="3" fill="#4FC9A8" stroke="#FFF8F0" strokeWidth="1" />;
        })}

        {/* jarum waktu sekarang: lancip solid + ekor kecil ala jam analog */}
        <polygon
          points={`${baseLeft.x},${baseLeft.y} ${baseRight.x},${baseRight.y} ${handTip.x},${handTip.y}`}
          fill="#4A3F35"
        />
        <line
          x1={CENTER}
          y1={CENTER}
          x2={handTail.x}
          y2={handTail.y}
          stroke="#4A3F35"
          strokeWidth="2"
          strokeLinecap="round"
        />
        <circle cx={CENTER} cy={CENTER} r="4" fill="#4A3F35" />
        <circle cx={CENTER} cy={CENTER} r="1.6" fill="#FFF8F0" />
      </svg>

      <div className="absolute flex flex-col items-center">
        <span className="font-mono text-xs tracking-widest uppercase text-ink-faint">Sekarang</span>
        <span className="text-3xl font-display text-ink">
          {now.toLocaleTimeString("id-ID", { hour: "2-digit", minute: "2-digit", timeZone: "Asia/Jakarta" })}
        </span>
      </div>
    </div>
  );
}