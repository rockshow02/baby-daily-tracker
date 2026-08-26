import { useEffect, useMemo, useState } from "react";
import { api } from "../api/client";
import MonthlyStory from "./MonthlyStory";
import DevelopmentGoals from "./DevelopmentGoals";
import DevelopmentCalendar from "./DevelopmentCalendar";

const FILTERS = [
  ["all", "Semua"], ["memory", "Foto"], ["milestone", "Pencapaian"],
  ["growth", "Tumbuh"], ["vaccination", "Vaksin"], ["health", "Kesehatan"], ["doctor", "Dokter"],
];

function TimelinePhoto({ entryId }) {
  const [src, setSrc] = useState("");
  useEffect(() => {
    let active = true; let url;
    api.loadMemoryJournalPhoto(entryId).then((value) => { url = value; if (active) setSrc(value); }).catch(() => {});
    return () => { active = false; if (url) URL.revokeObjectURL(url); };
  }, [entryId]);
  return src ? <img src={src} alt="Kenangan anak" className="mt-3 aspect-[16/10] w-full rounded-xl object-cover" /> : null;
}

export default function DevelopmentTimeline({ child }) {
  const [filter, setFilter] = useState("all");
  const [period, setPeriod] = useState("all");
  const [data, setData] = useState({ items: [], has_more: false });
  const [status, setStatus] = useState("loading");
  const [error, setError] = useState("");
  const [showStory, setShowStory] = useState(false);
  const [showGoals, setShowGoals] = useState(false);
  const [showCalendar, setShowCalendar] = useState(false);
  const params = useMemo(() => {
    const result = { limit: 100 };
    if (filter !== "all") result.categories = [filter];
    if (period !== "all") {
      const from = new Date(); from.setDate(from.getDate() - Number(period));
      result.from = from.toISOString().slice(0, 10);
    }
    return result;
  }, [filter, period]);
  useEffect(() => {
    let active = true; setStatus("loading"); setError("");
    api.developmentTimeline(child.id, params).then((value) => {
      if (active) { setData(value); setStatus("ready"); }
    }).catch((err) => { if (active) { setError(err.message); setStatus("error"); } });
    return () => { active = false; };
  }, [child.id, params]);

  return <section>
    <div className="mb-4 flex items-start justify-between gap-3"><div><h2 className="text-base font-bold text-ink">Linimasa perkembangan</h2>
      <p className="text-xs text-ink-faint">Cerita pertumbuhan {child.nickname || child.name} dalam satu tempat.</p></div>
      <div className="flex shrink-0 flex-col gap-2"><button onClick={()=>setShowCalendar(true)} className="rounded-full bg-sleep px-3 py-2 text-xs font-bold text-white">Kalender</button><button onClick={()=>setShowStory(true)} className="rounded-full bg-feed px-3 py-2 text-xs font-bold text-white">Cerita Bulanan</button><button onClick={()=>setShowGoals(true)} className="rounded-full border border-sleep px-3 py-2 text-xs font-bold text-sleep">Tujuan</button></div></div>
    <div className="-mx-4 mb-3 flex gap-2 overflow-x-auto px-4 pb-1">
      {FILTERS.map(([key, label]) => <button key={key} onClick={() => setFilter(key)}
        className={`shrink-0 rounded-full px-3 py-2 text-xs font-semibold ${filter === key ? "bg-sleep text-white" : "border border-void-hairline bg-void-card text-ink-muted"}`}>{label}</button>)}
    </div>
    <select value={period} onChange={(e) => setPeriod(e.target.value)} className="mb-5 rounded-lg border border-void-hairline bg-void-card px-3 py-2 text-xs text-ink">
      <option value="all">Semua waktu</option><option value="30">30 hari terakhir</option>
      <option value="90">90 hari terakhir</option><option value="365">1 tahun terakhir</option>
    </select>
    {status === "loading" ? <p className="py-10 text-center text-sm text-ink-faint">Menyusun linimasa...</p> :
      status === "error" ? <div className="rounded-xl border border-warn/30 bg-warn/5 p-4 text-sm text-warn">{error}</div> :
      data.items.length === 0 ? <div className="rounded-xl2 border border-dashed border-void-hairline p-8 text-center"><div className="text-4xl">🌱</div><p className="mt-2 text-sm font-bold text-ink">Belum ada cerita pada filter ini</p></div> :
      <div className="relative space-y-3 before:absolute before:bottom-5 before:left-5 before:top-5 before:w-px before:bg-void-hairline">
        {data.items.map((item) => <article key={item.id} className="relative ml-10 rounded-2xl border border-void-hairline bg-void-card p-4 shadow-sm">
          <span className="absolute -left-[2.75rem] top-4 flex h-9 w-9 items-center justify-center rounded-full bg-white text-lg ring-4 ring-void">{item.icon}</span>
          <p className="text-[11px] font-mono text-ink-faint">{new Date(`${item.date}T00:00:00`).toLocaleDateString("id-ID", { day: "2-digit", month: "long", year: "numeric" })}</p>
          <h3 className="mt-1 text-sm font-bold text-ink">{item.title}</h3>
          {item.summary && <p className="mt-0.5 text-xs text-ink-muted">{item.summary}</p>}
          {item.is_favorite&&<span className="mt-2 inline-block text-xs" aria-label="Favorit">⭐ Favorit</span>}
          {item.tags?.length>0&&<div className="mt-2 flex flex-wrap gap-1">{item.tags.map(tag=><span key={tag} className="rounded-full bg-sky-soft px-2 py-1 text-[10px] text-sky">#{tag}</span>)}</div>}
          {item.photo_entry_id && <TimelinePhoto entryId={item.photo_entry_id} />}
        </article>)}
      </div>}
    {data.has_more && <p className="mt-4 text-center text-xs text-ink-faint">Menampilkan 100 momen terbaru. Gunakan filter untuk mempersempit.</p>}
    {showStory && <MonthlyStory child={child} onClose={()=>setShowStory(false)} />}
    {showGoals && <DevelopmentGoals child={child} onClose={()=>setShowGoals(false)} />}
    {showCalendar && <DevelopmentCalendar child={child} onClose={()=>setShowCalendar(false)} />}
  </section>;
}
