import { useEffect, useState } from "react";
import { api } from "../api/client";

function formatCountdown(minutes) {
  const abs = Math.abs(Math.round(minutes));
  const h = Math.floor(abs / 60);
  const m = abs % 60;
  if (h === 0) return `${m} menit`;
  if (m === 0) return `${h} jam`;
  return `${h} jam ${m} menit`;
}

function formatTime(iso) {
  return new Date(iso).toLocaleTimeString("id-ID", { hour: "2-digit", minute: "2-digit" });
}

export default function FeedingPredictionCard({ childId, refreshKey }) {
  const [prediction, setPrediction] = useState(null);
  const [now, setNow] = useState(new Date());

  useEffect(() => {
    api.feedingPrediction(childId).then(setPrediction);
  }, [childId, refreshKey]);

  // update tampilan tiap menit biar countdown-nya jalan tanpa refetch
  useEffect(() => {
    const interval = setInterval(() => setNow(new Date()), 60000);
    return () => clearInterval(interval);
  }, []);

  if (!prediction) return null;
  if (!prediction.has_prediction) return null;

  const minutesUntilNext =
    (new Date(prediction.predicted_next_at) - now) / 60000;
  const isOverdue = minutesUntilNext < 0;

  return (
    <div
      className={`rounded-xl2 px-4 py-3.5 mb-4 border ${
        isOverdue ? "bg-warn/10 border-warn/30" : "bg-feed/10 border-feed/30"
      }`}
    >
      <div className="flex items-center justify-between">
        <div>
          <p className="text-[11px] text-ink-faint uppercase tracking-wider font-mono mb-0.5">
            Perkiraan Menyusui Berikutnya
          </p>
          <p className={`font-display text-xl ${isOverdue ? "text-warn" : "text-feed"}`}>
            {isOverdue
              ? `Sudah lewat ${formatCountdown(minutesUntilNext)}`
              : `±${formatCountdown(minutesUntilNext)} lagi`}
          </p>
        </div>
        <div className="text-right">
          <p className="text-sm text-ink font-medium">{formatTime(prediction.predicted_next_at)}</p>
          <p className="text-[11px] text-ink-faint">
            rata-rata {Math.round(prediction.average_interval_minutes / 60 * 10) / 10} jam
          </p>
        </div>
      </div>
    </div>
  );
}