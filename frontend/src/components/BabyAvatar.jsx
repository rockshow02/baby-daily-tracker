const STAGES = [
  { key: "newborn", maxMonths: 3, label: "Baru Lahir" },
  { key: "headup", maxMonths: 6, label: "Mulai Angkat Kepala" },
  { key: "sitting", maxMonths: 9, label: "Bisa Duduk" },
  { key: "crawling", maxMonths: 12, label: "Mulai Merangkak" },
  { key: "standing", maxMonths: Infinity, label: "Belajar Berdiri" },
];

function getStage(ageMonths) {
  return STAGES.find((s) => ageMonths < s.maxMonths) || STAGES[STAGES.length - 1];
}

// warna aksen badan gantian per tahap, biar tiap fase kelihatan beda momennya
const OUTFIT_COLOR = {
  newborn: "#FFA733",
  headup: "#9B87E0",
  sitting: "#4FC9A8",
  crawling: "#FFA733",
  standing: "#9B87E0",
};

const SKIN = "#FFD9B3";
const CHEEK = "#FF9B85";

function Face({ cx, cy, sleepy }) {
  return (
    <g>
      {sleepy ? (
        <>
          <path d={`M ${cx - 12} ${cy} q 6 5 12 0`} stroke="#7A5C3E" strokeWidth="2.5" fill="none" strokeLinecap="round" />
          <path d={`M ${cx + 2} ${cy} q 6 5 12 0`} stroke="#7A5C3E" strokeWidth="2.5" fill="none" strokeLinecap="round" />
        </>
      ) : (
        <>
          <circle cx={cx - 9} cy={cy} r="3" fill="#4A3F35" />
          <circle cx={cx + 9} cy={cy} r="3" fill="#4A3F35" />
        </>
      )}
      <circle cx={cx - 16} cy={cy + 10} r="5" fill={CHEEK} opacity="0.5" />
      <circle cx={cx + 16} cy={cy + 10} r="5" fill={CHEEK} opacity="0.5" />
      <path d={`M ${cx - 7} ${cy + 12} q 7 6 14 0`} stroke="#7A5C3E" strokeWidth="2.5" fill="none" strokeLinecap="round" />
    </g>
  );
}

export default function BabyAvatar({ birthDate }) {
  if (!birthDate) return null;

  const ageDays = Math.max(0, (new Date() - new Date(birthDate)) / (1000 * 60 * 60 * 24));
  const ageMonths = ageDays / 30.4375;
  const stage = getStage(ageMonths);
  const color = OUTFIT_COLOR[stage.key];

  return (
    <div className="flex flex-col items-center">
      <div className="baby-float">
        <svg viewBox="0 0 200 200" className="w-32 h-32">
          {stage.key === "newborn" && (
            <g>
              {/* bedong: bundel bulat, cuma kepala yg keliatan */}
              <ellipse cx="100" cy="125" rx="42" ry="48" fill={color} />
              <path d="M 60 110 Q 100 95 140 110 L 140 140 Q 100 155 60 140 Z" fill={color} opacity="0.85" />
              <circle cx="100" cy="85" r="34" fill={SKIN} />
              <Face cx="100" cy="88" sleepy />
            </g>
          )}

          {stage.key === "headup" && (
            <g>
              <ellipse cx="100" cy="140" rx="38" ry="30" fill={color} />
              {/* lengan nyender ke depan, kepala terangkat */}
              <ellipse cx="72" cy="150" rx="9" ry="16" fill={SKIN} transform="rotate(-25 72 150)" />
              <ellipse cx="128" cy="150" rx="9" ry="16" fill={SKIN} transform="rotate(25 128 150)" />
              <circle cx="100" cy="95" r="34" fill={SKIN} />
              <Face cx="100" cy="98" />
            </g>
          )}

          {stage.key === "sitting" && (
            <g>
              <ellipse cx="100" cy="150" rx="36" ry="26" fill={color} />
              <ellipse cx="66" cy="120" rx="10" ry="18" fill={SKIN} transform="rotate(-35 66 120)" />
              <ellipse cx="134" cy="120" rx="10" ry="18" fill={SKIN} transform="rotate(35 134 120)" />
              <ellipse cx="78" cy="172" rx="11" ry="9" fill={SKIN} />
              <ellipse cx="122" cy="172" rx="11" ry="9" fill={SKIN} />
              <circle cx="100" cy="90" r="34" fill={SKIN} />
              <Face cx="100" cy="93" />
            </g>
          )}

          {stage.key === "crawling" && (
            <g>
              <ellipse cx="105" cy="130" rx="42" ry="24" fill={color} />
              <ellipse cx="70" cy="150" rx="9" ry="15" fill={SKIN} transform="rotate(-15 70 150)" />
              <ellipse cx="140" cy="150" rx="9" ry="15" fill={SKIN} transform="rotate(15 140 150)" />
              <ellipse cx="80" cy="105" rx="9" ry="15" fill={SKIN} transform="rotate(-70 80 105)" />
              <ellipse cx="130" cy="105" rx="9" ry="15" fill={SKIN} transform="rotate(70 130 105)" />
              <circle cx="70" cy="95" r="30" fill={SKIN} />
              <Face cx="70" cy="98" />
            </g>
          )}

          {stage.key === "standing" && (
            <g>
              <ellipse cx="100" cy="140" rx="32" ry="34" fill={color} />
              <ellipse cx="72" cy="120" rx="9" ry="17" fill={SKIN} transform="rotate(-45 72 120)" />
              <ellipse cx="128" cy="120" rx="9" ry="17" fill={SKIN} transform="rotate(45 128 120)" />
              <ellipse cx="85" cy="178" rx="10" ry="14" fill={SKIN} />
              <ellipse cx="115" cy="178" rx="10" ry="14" fill={SKIN} />
              <circle cx="100" cy="85" r="34" fill={SKIN} />
              <Face cx="100" cy="88" />
            </g>
          )}
        </svg>
      </div>
      <p className="mt-1 text-xs text-ink-muted">{stage.label}</p>
    </div>
  );
}