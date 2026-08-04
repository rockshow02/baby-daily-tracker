import { useEffect, useState } from "react";
import { api } from "../api/client";

export default function MotorActivityCard({ ageMonths }) {
  const [activities, setActivities] = useState([]);
  const [expanded, setExpanded] = useState(false);

  useEffect(() => {
    if (ageMonths == null) return;
    api.listArticles("motor_activity", ageMonths).then(setActivities);
  }, [ageMonths]);

  if (activities.length === 0) return null;

  const featured = activities[0];

  return (
    <div
      onClick={() => setExpanded(!expanded)}
      className="rounded-xl2 px-4 py-3.5 mb-4 border bg-sleep/10 border-sleep/30 cursor-pointer"
    >
      <p className="text-[11px] text-ink-faint uppercase tracking-wider font-mono mb-1">
        🤸 Ide Aktivitas Motorik Hari Ini
      </p>
      <p className="font-display text-lg text-ink">{featured.title}</p>
      {!expanded ? (
        <p className="text-sm text-ink-muted mt-0.5">{featured.summary}</p>
      ) : (
        <p className="text-sm text-ink-muted mt-1.5 leading-relaxed whitespace-pre-line">{featured.body}</p>
      )}
      {activities.length > 1 && (
        <p className="text-[11px] text-sleep mt-2">
          +{activities.length - 1} ide lain di tab Momen → Milestone
        </p>
      )}
    </div>
  );
}