import { useEffect, useRef, useState } from "react";
import { buildInsight } from "../utils/insights";

const TONE_STYLE = {
  warn: "bg-warn/10 border-warn/30 text-warn",
  info: "bg-sleep/10 border-sleep/30 text-sleep",
  good: "bg-feed/10 border-feed/30 text-feed",
};

const PANEL_WIDTH = 288; // px, harus sama kayak yang dipakai di style width panel
const VIEWPORT_MARGIN = 16; // px, jarak aman minimal dari tepi layar

export default function SmartInsightsBell({ summary, weeklyAverages }) {
  const [open, setOpen] = useState(false);
  const [panelStyle, setPanelStyle] = useState({});
  const wrapperRef = useRef(null);
  const buttonRef = useRef(null);

  // hitung posisi panel manual (bukan cuma andelin CSS "right-0") — biar
  // TETAP nggak keluar tepi kiri layar walau tombol bell-nya nggak persis
  // di ujung kanan (kasus di HP: bell + date-nav berdampingan, bell nggak
  // selalu di ujung banget)
  const computePosition = () => {
    if (!buttonRef.current) return;
    const rect = buttonRef.current.getBoundingClientRect();
    const width = Math.min(PANEL_WIDTH, window.innerWidth - VIEWPORT_MARGIN * 2);
    let left = rect.right - width; // default: rata kanan sama tombol bell
    left = Math.max(VIEWPORT_MARGIN, left); // jangan sampai kurang dari margin aman kiri
    left = Math.min(left, window.innerWidth - width - VIEWPORT_MARGIN); // jangan lewat kanan juga
    setPanelStyle({
      position: "fixed",
      top: rect.bottom + 6,
      left,
      width,
    });
  };

  const toggleOpen = () => {
    if (!open) computePosition();
    setOpen(!open);
  };

  useEffect(() => {
    if (!open) return;
    const handleClickOutside = (e) => {
      if (
        wrapperRef.current && !wrapperRef.current.contains(e.target) &&
        !document.getElementById("smart-insights-panel")?.contains(e.target)
      ) {
        setOpen(false);
      }
    };
    const handleResize = () => computePosition();
    document.addEventListener("mousedown", handleClickOutside);
    document.addEventListener("touchstart", handleClickOutside);
    window.addEventListener("resize", handleResize);
    window.addEventListener("scroll", handleResize, true);
    return () => {
      document.removeEventListener("mousedown", handleClickOutside);
      document.removeEventListener("touchstart", handleClickOutside);
      window.removeEventListener("resize", handleResize);
      window.removeEventListener("scroll", handleResize, true);
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
    <div className="relative" ref={wrapperRef}>
      <button
        ref={buttonRef}
        type="button"
        onClick={toggleOpen}
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
        <div
          id="smart-insights-panel"
          style={panelStyle}
          className="z-30 bg-void-card border border-void-hairline rounded-xl2 shadow-soft p-3 space-y-2"
        >
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