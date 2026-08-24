import { useEffect, useState } from "react";
import { api } from "../api/client";

function fmtDate(iso) {
  return new Date(iso).toLocaleDateString("id-ID", { day: "2-digit", month: "short", year: "numeric" });
}

export default function NextVaccineCard({ childId, refreshKey }) {
  const [data, setData] = useState(null);

  useEffect(() => {
    api.nextVaccine(childId).then(setData);
  }, [childId, refreshKey]);

  if (!data || !data.has_next) return null;

  const isOverdue = data.status === "overdue";
  const isDue = data.status === "due";

  return (
    <div
      className={`rounded-xl2 px-4 py-3.5 mb-4 border ${
        isOverdue ? "bg-warn/10 border-warn/30" : "bg-sleep/10 border-sleep/30"
      }`}
    >
      <div className="flex items-center justify-between">
        <div>
          <p className="text-[11px] text-ink-faint uppercase tracking-wider font-mono mb-0.5">
            {isOverdue ? "Vaksin Wajib Terlambat" : isDue ? "Vaksin Wajib Segera" : "Vaksin Wajib Berikutnya"}
          </p>
          <p className={`font-display text-xl ${isOverdue ? "text-warn" : "text-sleep"}`}>
            💉 {data.vaccine_name}
          </p>
          {isOverdue && data.overdue_count > 1 && (
            <p className="text-[11px] text-warn mt-0.5">
              +{data.overdue_count - 1} vaksin wajib lain juga sudah jatuh tempo
            </p>
          )}
        </div>
        <div className="text-right">
          <p className="text-sm text-ink font-medium">usia {data.recommended_age_months} bln</p>
          <p className="text-[11px] text-ink-faint">
            {isOverdue ? `direkomendasikan ${fmtDate(data.estimated_date)}` : isDue ? `waktunya sekitar ${fmtDate(data.estimated_date)}` : `sekitar ${fmtDate(data.estimated_date)}`}
          </p>
        </div>
      </div>
    </div>
  );
}
