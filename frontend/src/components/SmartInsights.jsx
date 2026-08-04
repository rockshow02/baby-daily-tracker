import { buildInsight } from "../utils/insights";

const TONE_STYLE = {
  warn: "bg-warn/10 border-warn/30 text-warn",
  info: "bg-sleep/10 border-sleep/30 text-sleep",
  good: "bg-feed/10 border-feed/30 text-feed",
};

export default function SmartInsights({ summary, weeklyAverages }) {
  if (!summary || !summary.feeding) return null;

  const ageLabel = summary.guideline_label;

  const insights = [
    buildInsight({
      label: "Menyusui",
      actual: summary.feeding.actual,
      min: summary.feeding.min,
      max: summary.feeding.max,
      status: summary.feeding.status,
      weeklyAvg: weeklyAverages?.feeding,
      unit: "x",
      ageLabel,
    }),
    buildInsight({
      label: "Tidur",
      actual: summary.sleep.actual_hours,
      min: summary.sleep.min,
      max: summary.sleep.max,
      status: summary.sleep.status,
      weeklyAvg: weeklyAverages?.sleep,
      unit: " jam",
      ageLabel,
    }),
    buildInsight({
      label: "Popok basah",
      actual: summary.wet_diaper.actual,
      min: summary.wet_diaper.min,
      max: null,
      status: summary.wet_diaper.status,
      weeklyAvg: weeklyAverages?.wetDiaper,
      unit: "x",
      ageLabel,
    }),
  ].filter(Boolean);

  if (insights.length === 0) return null;

  return (
    <div className="space-y-2 mb-4">
      {insights.map((insight, i) => (
        <div
          key={i}
          className={`rounded-xl2 px-4 py-3 border text-sm flex items-start gap-2 ${TONE_STYLE[insight.tone]}`}
        >
          <span className="flex-shrink-0">{insight.icon}</span>
          <span className="text-ink">{insight.text}</span>
        </div>
      ))}
    </div>
  );
}