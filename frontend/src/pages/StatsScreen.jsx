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

function ChartCard({ title, subtitle, accent = "feed", children }) {
  const accentClass = {
    feed: "bg-feed",
    sleep: "bg-sleep",
    diaper: "bg-diaper",
    sky: "bg-sky",
  }[accent];

  return (
    <section className="mb-4 rounded-xl2 border border-void-hairline bg-void-card p-4 shadow-soft sm:p-5">
      <div className="mb-4 flex items-start gap-3">
        <span className={`mt-1 h-8 w-1 rounded-full ${accentClass}`} aria-hidden="true" />
        <div>
          <h2 className="text-base font-bold text-ink">{title}</h2>
          {subtitle && <p className="text-xs text-ink-faint">{subtitle}</p>}
        </div>
      </div>
      {children}
    </section>
  );
}

function MetricCard({ icon, value, label, tone }) {
  return (
    <div className={`min-w-0 rounded-[1.35rem] p-3.5 ${tone}`}>
      <span className="text-xl" aria-hidden="true">{icon}</span>
      <p className="mt-2 truncate text-2xl font-bold text-ink">{value}</p>
      <p className="mt-0.5 text-[11px] leading-snug text-ink-muted">{label}</p>
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
    <div className="min-h-screen px-4 pb-28 pt-6 sm:px-6 sm:pt-8">
      <header className="mb-5">
        <p className="mb-1 text-[11px] font-bold uppercase tracking-[0.18em] text-feed">Pola harian</p>
        <h1 className="font-display text-3xl font-bold leading-tight text-ink">Statistik {child.name}</h1>
        <p className="mt-1 text-sm text-ink-muted">Kenali perubahan rutinitas dari waktu ke waktu.</p>
      </header>

      <div className="mb-5 flex rounded-2xl border border-void-hairline bg-void-card p-1 shadow-sm" aria-label="Rentang statistik">
        {RANGE_OPTIONS.map((r) => (
          <button
            key={r.key}
            onClick={() => setDays(r.key)}
            className={`flex-1 rounded-xl py-2.5 text-xs font-bold transition-colors ${
              days === r.key ? "bg-feed text-white shadow-sm" : "text-ink-muted"
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
          <section className="mb-5">
            <p className="mb-2 text-[11px] font-bold uppercase tracking-[0.16em] text-ink-faint">Rata-rata per hari</p>
            <div className="grid grid-cols-2 gap-2.5">
              <MetricCard icon="🍼" value={`${data.averages.feeding_per_day}x`} label="Susu" tone="bg-feed-soft" />
              <MetricCard icon="🌙" value={`${data.averages.sleep_hours_per_day}j`} label="Tidur" tone="bg-sleep-soft" />
              <MetricCard icon="💧" value={`${data.averages.wet_diaper_per_day}x`} label="Popok basah" tone="bg-diaper-soft" />
              <MetricCard icon="💩" value={`${data.averages.dirty_diaper_per_day}x`} label="Buang air besar" tone="bg-sky-soft" />
            </div>
          </section>

          <ChartCard title="Pola menyusu" subtitle={`Jumlah sesi dalam ${days} hari terakhir`} accent="feed">
            <div className="h-52">
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

          <ChartCard title="Durasi tidur" subtitle="Total jam tidur setiap hari" accent="sleep">
            <div className="h-52">
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

          <ChartCard title="Kebiasaan popok" subtitle="Perbandingan popok basah dan BAB" accent="diaper">
            <div className="h-52">
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
            <ChartCard title="Suasana hati" subtitle="Catatan mood selama periode ini" accent="sky">
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
