import { useEffect, useRef, useState } from "react";
import { buildInsight } from "../utils/insights";

const TONE_STYLE = {
  warn: "bg-warn/10 border-warn/30 text-warn",
  info: "bg-sleep/10 border-sleep/30 text-sleep",
  good: "bg-feed/10 border-feed/30 text-feed",
};

export default function SmartInsightsBell({ summary, weeklyAverages }) {
  const [open, setOpen] = useState(false);
  const panelRef = useRef(null);

  // tutup panel kalau tap di luar area-nya
  useEffect(() => {
    if (!open) return;
    const handleClickOutside = (e) => {
      if (panelRef.current && !panelRef.current.contains(e.target)) {
        setOpen(false);
      }
    };
    document.addEventListener("mousedown", handleClickOutside);
    document.addEventListener("touchstart", handleClickOutside);
    return () => {
      document.removeEventListener("mousedown", handleClickOutside);
      document.removeEventListener("touchstart", handleClickOutside);
    };
  }, [open]);

  if (!summary || !summary.feeding) return null;

  const ageLabel = summary.guideline_label;
  const insights = [
    buildInsight({
      label: "Menyusui", actual: summary.feeding.actual, min: summary.feeding.min,
      max: summary.feeding.max, status: summary.feeding.status,
      weeklyAvg: weeklyAverages?.feeding, unit: "x", ageLabel,
    }),
    buildInsight({
      label: "Tidur", actual: summary.sleep.actual_hours, min: summary.sleep.min,
      max: summary.sleep.max, status: summary.sleep.status,
      weeklyAvg: weeklyAverages?.sleep, unit: " jam", ageLabel,
    }),
    buildInsight({
      label: "Popok basah", actual: summary.wet_diaper.actual, min: summary.wet_diaper.min,
      max: null, status: summary.wet_diaper.status,
      weeklyAvg: weeklyAverages?.wetDiaper, unit: "x", ageLabel,
    }),
  ].filter(Boolean);

  if (insights.length === 0) return null;

  // badge cuma hitung yang butuh perhatian (warn/info), bukan yang "good"
  // — biar orang tua nggak kaget liat badge angka 3 padahal semuanya aman
  const attentionCount = insights.filter((i) => i.tone !== "good").length;

  return (
    <div className="relative" ref={panelRef}>
      <button
        type="button"
        onClick={() => setOpen(!open)}
        className="relative w-9 h-9 flex items-center justify-center bg-void-card border border-void-hairline rounded-full"
        aria-label="Insight hari ini"
      >
        <span className="text-base">🔔</span>
        {attentionCount > 0 && (
          <span className="absolute -top-1 -right-1 w-4 h-4 rounded-full bg-warn text-white text-[10px] font-bold flex items-center justify-center">
            {attentionCount}
          </span>
        )}
      </button>

      {open && (
        <div className="absolute right-0 top-11 z-30 w-72 bg-void-card border border-void-hairline rounded-xl2 shadow-soft p-3 space-y-2">
          <p className="text-[11px] text-ink-faint uppercase tracking-wider font-mono px-1 mb-1">
            Insight Hari Ini
          </p>
          {insights.map((insight, i) => (
            <div
              key={i}
              className={`rounded-xl2 px-3 py-2.5 border text-xs flex items-start gap-2 ${TONE_STYLE[insight.tone]}`}
            >
              <span className="flex-shrink-0">{insight.icon}</span>
              <span className="text-ink">{insight.text}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}