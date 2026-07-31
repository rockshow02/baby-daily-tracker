const RADIUS = 120;
const CENTER = 140;
const RING_FEED = RADIUS;
const RING_SLEEP = RADIUS - 18;
const RING_DIAPER = RADIUS - 36;

// jam 0 diletakkan di atas (jam 12), searah jarum jam
function angleForTime(date) {
  const hours = date.getHours() + date.getMinutes() / 60;
  return (hours / 24) * 360 - 90;
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

export default function DailyRadialClock({ feedingLogs, sleepLogs, diaperLogs }) {
  const now = new Date();
  const nowAngle = angleForTime(now);

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

        {/* menyusui sebagai titik */}
        {feedingLogs.map((log) => {
          const p = pointOnRing(RING_FEED, angleForTime(new Date(log.timestamp)));
          return <circle key={`feed-${log.id}`} cx={p.x} cy={p.y} r="4" fill="#FFA733" />;
        })}

        {/* popok sebagai titik */}
        {diaperLogs.map((log) => {
          const p = pointOnRing(RING_DIAPER, angleForTime(new Date(log.timestamp)));
          return <circle key={`diaper-${log.id}`} cx={p.x} cy={p.y} r="3.5" fill="#4FC9A8" />;
        })}

        {/* jarum waktu sekarang */}
        <line
          x1={CENTER}
          y1={CENTER}
          x2={pointOnRing(RADIUS + 6, nowAngle).x}
          y2={pointOnRing(RADIUS + 6, nowAngle).y}
          stroke="#4A3F35"
          strokeWidth="1.5"
          opacity="0.5"
        />
      </svg>

      <div className="absolute flex flex-col items-center">
        <span className="font-mono text-xs text-ink-faint tracking-widest uppercase">Sekarang</span>
        <span className="font-display text-3xl text-ink">
          {now.toLocaleTimeString("id-ID", { hour: "2-digit", minute: "2-digit" })}
        </span>
      </div>
    </div>
  );
}