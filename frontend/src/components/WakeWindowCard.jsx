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

export default function WakeWindowCard({ childId, refreshKey }) {
  const [prediction, setPrediction] = useState(null);
  const [now, setNow] = useState(new Date());

  useEffect(() => {
    api.wakeWindowPrediction(childId).then(setPrediction);
  }, [childId, refreshKey]);

  useEffect(() => {
    const interval = setInterval(() => setNow(new Date()), 60000);
    return () => clearInterval(interval);
  }, []);

  if (!prediction) return null;

  if (prediction.is_currently_sleeping) {
    return (
      <div className="rounded-xl2 px-4 py-3.5 mb-4 border bg-sleep/10 border-sleep/30">
        <p className="text-[11px] text-ink-faint uppercase tracking-wider font-mono mb-0.5">
          Wake Window
        </p>
        <p className="font-display text-xl text-sleep">😴 Lagi tidur</p>
      </div>
    );
  }

  if (!prediction.has_prediction) return null;

  const minutesUntilMin = prediction.minutes_until_min - (new Date() - now) / 60000;
  const minutesUntilMax = prediction.minutes_until_max - (new Date() - now) / 60000;
  const isOverdue = minutesUntilMax < 0;
  const isInWindow = minutesUntilMin <= 0 && minutesUntilMax >= 0;

  let statusColor = "text-sleep";
  let statusText;
  if (isOverdue) {
    statusColor = "text-warn";
    statusText = `Udah lewat ${formatCountdown(minutesUntilMax)}`;
  } else if (isInWindow) {
    statusColor = "text-feed";
    statusText = "Mungkin udah mulai ngantuk";
  } else {
    statusText = `±${formatCountdown(minutesUntilMin)} lagi`;
  }

  return (
    <div
      className={`rounded-xl2 px-4 py-3.5 mb-4 border ${
        isOverdue ? "bg-warn/10 border-warn/30" : "bg-sleep/10 border-sleep/30"
      }`}
    >
      <div className="flex items-center justify-between">
        <div>
          <p className="text-[11px] text-ink-faint uppercase tracking-wider font-mono mb-0.5">
            Wake Window
          </p>
          <p className={`font-display text-xl ${statusColor}`}>{statusText}</p>
        </div>
        <div className="text-right">
          <p className="text-sm text-ink font-medium">
            {formatTime(prediction.predicted_min_at)} - {formatTime(prediction.predicted_max_at)}
          </p>
          <p className="text-[11px] text-ink-faint">acuan usia {prediction.guideline_label}</p>
        </div>
      </div>
    </div>
  );
}