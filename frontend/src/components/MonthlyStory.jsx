import { useEffect, useState } from "react";
import { api } from "../api/client";

const currentMonth = () => new Date().toLocaleDateString("en-CA", { timeZone: "Asia/Jakarta", year: "numeric", month: "2-digit" }).slice(0, 7);

function PreviewPhoto({ id }) {
  const [src, setSrc] = useState("");
  useEffect(() => { let active = true; let url; api.loadMemoryJournalPhoto(id).then((x) => { url=x; if(active)setSrc(x); }).catch(()=>{});
    return () => { active=false; if(url) URL.revokeObjectURL(url); }; }, [id]);
  return src ? <img src={src} alt="Kenangan pilihan" className="aspect-square w-full rounded-xl object-cover" /> : <div className="aspect-square rounded-xl bg-void-raised" />;
}

export default function MonthlyStory({ child, onClose }) {
  const canWrite = child.role !== "viewer";
  const [month, setMonth] = useState(currentMonth());
  const [note, setNote] = useState("");
  const [photos, setPhotos] = useState([]);
  const [selected, setSelected] = useState([]);
  const [snapshot, setSnapshot] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => { api.listMemoryJournal(child.id).then((x) => setPhotos(x.items || [])).catch(() => setPhotos([])); }, [child.id]);
  const invalidate = () => setSnapshot(null);
  const payload = { month, parent_note: note, selected_photo_ids: selected };
  const makePreview = async () => {
    setLoading(true); setError("");
    try { const result = await api.previewMonthlyStory(child.id, payload); setSnapshot({ report: result, payload: { ...payload, selected_photo_ids: [...selected] } }); }
    catch (err) { setError(err.message); } finally { setLoading(false); }
  };
  const download = async () => {
    if (!snapshot) return;
    setLoading(true); setError("");
    try { await api.downloadAuthenticatedPost(api.monthlyStoryPdfUrl(child.id),
      { ...snapshot.payload, snapshot_token: snapshot.report.snapshot_token }, `cerita-${child.nickname || child.name}-${month}.pdf`); }
    catch (err) { setError(err.message); if ([400,409].includes(err.status)) setSnapshot(null); }
    finally { setLoading(false); }
  };
  const report = snapshot?.report;
  return <div className="fixed inset-0 z-50 overflow-y-auto bg-void">
    <div className="mx-auto min-h-screen max-w-lg px-4 pb-24 pt-5">
      <div className="mb-5 flex items-center justify-between"><div><p className="text-[11px] font-bold uppercase tracking-widest text-feed">V3 Monthly Story</p><h1 className="font-display text-3xl font-bold text-ink">Cerita Bulanan</h1></div>
        <button onClick={onClose} className="rounded-full border border-void-hairline bg-white px-4 py-2 text-sm">Tutup</button></div>
      <section className="mb-5 rounded-2xl border border-void-hairline bg-void-card p-4">
        <label className="mb-1 block text-xs text-ink-muted">Bulan</label><input type="month" max={currentMonth()} value={month} onChange={(e)=>{setMonth(e.target.value);invalidate();}} className="mb-4 w-full rounded-lg border border-void-hairline bg-void px-3 py-2.5" />
        {canWrite && <><label className="mb-1 block text-xs text-ink-muted">Catatan orang tua (opsional)</label><textarea maxLength={1000} value={note} onChange={(e)=>{setNote(e.target.value);invalidate();}} className="mb-4 min-h-20 w-full rounded-lg border border-void-hairline bg-void px-3 py-2.5" /></>}
        <p className="mb-2 text-xs font-semibold text-ink">Pilih hingga 4 foto</p>
        <div className="grid grid-cols-4 gap-2">{photos.filter((x)=>x.occurred_date.startsWith(month)).map((item)=><button key={item.id} type="button" onClick={()=>{
          setSelected((old)=>old.includes(item.id)?old.filter((x)=>x!==item.id):old.length<4?[...old,item.id]:old); invalidate();
        }} className={`relative overflow-hidden rounded-xl border-2 ${selected.includes(item.id)?"border-feed":"border-transparent"}`}><PreviewPhoto id={item.id}/>{selected.includes(item.id)&&<span className="absolute right-1 top-1 rounded-full bg-feed px-1.5 text-xs text-white">✓</span>}</button>)}</div>
        <button onClick={makePreview} disabled={loading} className="mt-4 w-full rounded-xl bg-feed py-3 text-sm font-bold text-white disabled:opacity-50">{loading?"Menyiapkan...":"Buat Pratinjau"}</button>
      </section>
      {error && <p className="mb-4 rounded-xl bg-warn/10 p-3 text-sm text-warn">{error}</p>}
      {report && <section className="rounded-2xl border border-void-hairline bg-white p-5 shadow-sm">
        <p className="text-xs uppercase tracking-widest text-ink-faint">{report.month}</p><h2 className="font-display text-2xl font-bold text-ink">Cerita {report.child.display_name}</h2>
        <div className="my-4 grid grid-cols-3 gap-2">{[["📷",report.counts.photos,"Foto"],["✨",report.counts.milestones,"Momen"],["💉",report.counts.vaccinations,"Vaksin"]].map(([icon,value,label])=><div key={label} className="rounded-xl bg-feed-soft p-3 text-center"><div>{icon}</div><b className="text-xl text-ink">{value}</b><p className="text-[10px] text-ink-muted">{label}</p></div>)}</div>
        <p className="mb-4 text-xs text-ink-faint">Bulan sebelumnya: {report.previous_counts.photos} foto · {report.previous_counts.milestones} momen · {report.previous_counts.vaccinations} vaksin</p>
        {report.milestones.length>0&&<><h3 className="text-sm font-bold text-ink">Pencapaian</h3><ul className="mt-2 space-y-1 text-xs text-ink-muted">{report.milestones.map((x)=><li key={`${x.date}-${x.label}`}>✨ {x.date} — {x.label.replaceAll("_"," ")}</li>)}</ul></>}
        {report.growth.length>0&&<><h3 className="mt-4 text-sm font-bold text-ink">Pertumbuhan</h3><div className="mt-2 space-y-1 text-xs text-ink-muted">{report.growth.map((x)=><p key={x.date}>📈 {x.date}: {x.weight_kg??"-"} kg · {x.height_cm??"-"} cm</p>)}</div></>}
        {report.selected_photos.length>0&&<div className="mt-4 grid grid-cols-2 gap-2">{report.selected_photos.map((x)=><PreviewPhoto key={x.id} id={x.id}/>)}</div>}
        {report.parent_note&&<div className="mt-4 rounded-xl bg-sleep-soft p-4"><p className="text-xs font-bold text-ink">Catatan orang tua</p><p className="mt-1 whitespace-pre-wrap text-sm text-ink-muted">{report.parent_note}</p></div>}
        <p className="mt-4 text-[11px] text-ink-faint">{report.disclaimer}</p>
        {report.capabilities.can_export&&<button onClick={download} disabled={loading} className="mt-5 w-full rounded-xl bg-sleep py-3 text-sm font-bold text-white disabled:opacity-50">Unduh PDF</button>}
      </section>}
    </div></div>;
}
