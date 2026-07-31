import { useEffect, useState, useCallback } from "react";
import {
  BarChart, Bar, LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, PieChart, Pie, Cell,
} from "recharts";
import { api } from "../api/client";

const RANGE_OPTIONS = [
  { key: 7, label: "7 Hari" },
  { key: 30, label: "30 Hari" },
];

const MOOD_LABEL = { ceria: "Ceria", baik: "Baik", sedih: "Sedih", menangis: "Menangis" };
const MOOD_COLOR = { ceria: "#FFA733", baik: "#4FC9A8", sedih: "#9B87E0", menangis: "#FF7A5C" };

function fmtDay(iso) {
  return new Date(iso).toLocaleDateString("id-ID", { day: "2-digit", month: "short" });
}

function ChartCard({ title, children }) {
  return (
    <div className="bg-void-card border border-void-hairline rounded-xl2 p-4 mb-4 shadow-soft">
      <p className="text-xs text-ink-faint font-mono uppercase tracking-wider mb-3">{title}</p>
      {children}
    </div>
  );
}

function CustomTooltip({ active, payload, label, unit }) {
  if (!active || !payload || payload.length === 0) return null;
  return (
    <div className="bg-void-card border border-void-hairline rounded-lg px-3 py-2 shadow-soft">
      <p className="text-xs text-ink-faint mb-1">{fmtDay(label)}</p>
      {payload.map((p) => (
        <p key={p.dataKey} className="text-sm text-ink font-semibold" style={{ color: p.color }}>
          {p.value} {unit}
        </p>
      ))}
    </div>
  );
}

export default function StatsScreen({ child }) {
  const [days, setDays] = useState(7);
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await api.getStats(child.id, days);
      setData(res);
    } finally {
      setLoading(false);
    }
  }, [child.id, days]);

  useEffect(() => {
    load();
  }, [load]);

  const moodData = data
    ? Object.entries(data.mood_distribution).map(([mood, count]) => ({
        name: MOOD_LABEL[mood] || mood,
        value: count,
        color: MOOD_COLOR[mood] || "#C7BAA9",
      }))
    : [];

  return (
    <div className="min-h-screen pb-16 px-6 pt-8">
      <h1 className="font-display text-3xl text-ink mb-1">Statistik</h1>
      <p className="text-sm text-ink-muted mb-6">Pola dan tren aktivitas {child.name}</p>

      <div className="flex gap-2 mb-5">
        {RANGE_OPTIONS.map((r) => (
          <button
            key={r.key}
            onClick={() => setDays(r.key)}
            className={`flex-1 py-2.5 rounded-xl2 border text-xs font-medium ${
              days === r.key ? "bg-feed/15 border-feed text-feed" : "bg-void-card border-void-hairline text-ink-muted"
            }`}
          >
            {r.label}
          </button>
        ))}
      </div>

      {loading || !data ? (
        <p className="text-ink-faint text-sm text-center py-10">Memuat...</p>
      ) : (
        <>
          <div className="grid grid-cols-2 gap-3 mb-4">
            <div className="bg-void-card border border-void-hairline rounded-xl2 p-4">
              <p className="text-2xl font-display text-ink">{data.averages.feeding_per_day}</p>
              <p className="text-xs text-ink-faint">rata-rata menyusui/hari</p>
            </div>
            <div className="bg-void-card border border-void-hairline rounded-xl2 p-4">
              <p className="text-2xl font-display text-ink">{data.averages.sleep_hours_per_day}</p>
              <p className="text-xs text-ink-faint">rata-rata tidur (jam)/hari</p>
            </div>
            <div className="bg-void-card border border-void-hairline rounded-xl2 p-4">
              <p className="text-2xl font-display text-ink">{data.averages.wet_diaper_per_day}</p>
              <p className="text-xs text-ink-faint">rata-rata pipis/hari</p>
            </div>
            <div className="bg-void-card border border-void-hairline rounded-xl2 p-4">
              <p className="text-2xl font-display text-ink">{data.averages.dirty_diaper_per_day}</p>
              <p className="text-xs text-ink-faint">rata-rata pup/hari</p>
            </div>
          </div>

          <ChartCard title="Tren Menyusui">
            <div className="h-48">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={data.days} margin={{ top: 5, right: 5, left: -25, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#F0E2CC" vertical={false} />
                  <XAxis dataKey="date" tickFormatter={fmtDay} tick={{ fontSize: 10, fill: "#9C8F82" }} tickLine={false} axisLine={{ stroke: "#F0E2CC" }} />
                  <YAxis tick={{ fontSize: 10, fill: "#9C8F82" }} tickLine={false} axisLine={false} width={30} allowDecimals={false} />
                  <Tooltip content={<CustomTooltip unit="kali" />} />
                  <Bar dataKey="feeding_count" fill="#FFA733" radius={[4, 4, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </ChartCard>

          <ChartCard title="Tren Tidur (jam)">
            <div className="h-48">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={data.days} margin={{ top: 5, right: 5, left: -25, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#F0E2CC" vertical={false} />
                  <XAxis dataKey="date" tickFormatter={fmtDay} tick={{ fontSize: 10, fill: "#9C8F82" }} tickLine={false} axisLine={{ stroke: "#F0E2CC" }} />
                  <YAxis tick={{ fontSize: 10, fill: "#9C8F82" }} tickLine={false} axisLine={false} width={30} />
                  <Tooltip content={<CustomTooltip unit="jam" />} />
                  <Line dataKey="sleep_hours" stroke="#9B87E0" strokeWidth={2.5} dot={{ r: 3, fill: "#9B87E0" }} />
                </LineChart>
              </ResponsiveContainer>
            </div>
          </ChartCard>

          <ChartCard title="Tren Popok (pipis vs pup)">
            <div className="h-48">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={data.days} margin={{ top: 5, right: 5, left: -25, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#F0E2CC" vertical={false} />
                  <XAxis dataKey="date" tickFormatter={fmtDay} tick={{ fontSize: 10, fill: "#9C8F82" }} tickLine={false} axisLine={{ stroke: "#F0E2CC" }} />
                  <YAxis tick={{ fontSize: 10, fill: "#9C8F82" }} tickLine={false} axisLine={false} width={30} allowDecimals={false} />
                  <Tooltip content={<CustomTooltip unit="kali" />} />
                  <Bar dataKey="wet_diaper_count" fill="#4FC9A8" radius={[4, 4, 0, 0]} name="Pipis" />
                  <Bar dataKey="dirty_diaper_count" fill="#FF7A5C" radius={[4, 4, 0, 0]} name="Pup" />
                </BarChart>
              </ResponsiveContainer>
            </div>
            <div className="flex justify-center gap-4 mt-2">
              <span className="flex items-center gap-1.5 text-[11px] text-ink-muted">
                <span className="w-2 h-2 rounded-full bg-diaper" /> Pipis
              </span>
              <span className="flex items-center gap-1.5 text-[11px] text-ink-muted">
                <span className="w-2 h-2 rounded-full bg-warn" /> Pup
              </span>
            </div>
          </ChartCard>

          {moodData.length > 0 && (
            <ChartCard title="Distribusi Mood">
              <div className="h-48 flex items-center justify-center">
                <ResponsiveContainer width="100%" height="100%">
                  <PieChart>
                    <Pie data={moodData} dataKey="value" nameKey="name" cx="50%" cy="50%" outerRadius={70} label={(e) => `${e.name} (${e.value})`}>
                      {moodData.map((entry, i) => (
                        <Cell key={i} fill={entry.color} />
                      ))}
                    </Pie>
                    <Tooltip />
                  </PieChart>
                </ResponsiveContainer>
              </div>
            </ChartCard>
          )}

          {data.total_records === 0 && (
            <p className="text-ink-faint text-sm text-center py-6">
              Belum ada cukup data di rentang ini. Catat aktivitas harian dulu di tab Harian.
            </p>
          )}
        </>
      )}
    </div>
  );
}