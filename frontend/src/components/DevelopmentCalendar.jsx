import { useEffect, useMemo, useState } from "react";
import { api } from "../api/client";

const FILTERS = [
  ["memory", "Foto"], ["milestone", "Pencapaian"], ["growth", "Tumbuh"],
  ["vaccination", "Vaksin"], ["doctor", "Dokter"], ["reminder", "Pengingat"],
  ["medication", "Obat"], ["goal", "Tujuan"],
];
const COLORS = { memory:"bg-sky", milestone:"bg-feed", growth:"bg-emerald-400",
  vaccination:"bg-purple-400", doctor:"bg-rose-400", reminder:"bg-amber-400",
  medication:"bg-red-400", goal:"bg-indigo-400" };

function currentMonthWib() {
  const parts = new Intl.DateTimeFormat("en", { timeZone:"Asia/Jakarta", year:"numeric", month:"2-digit" }).formatToParts(new Date());
  return `${parts.find(x=>x.type==="year").value}-${parts.find(x=>x.type==="month").value}`;
}
function todayWib() {
  const parts = new Intl.DateTimeFormat("en", { timeZone:"Asia/Jakarta", year:"numeric", month:"2-digit", day:"2-digit" }).formatToParts(new Date());
  return `${parts.find(x=>x.type==="year").value}-${parts.find(x=>x.type==="month").value}-${parts.find(x=>x.type==="day").value}`;
}
function shiftMonth(value, amount) {
  const [year, month] = value.split("-").map(Number); const date = new Date(year, month - 1 + amount, 1);
  return `${date.getFullYear()}-${String(date.getMonth()+1).padStart(2,"0")}`;
}
function monthDays(month) {
  const [year, index] = month.split("-").map(Number); const total = new Date(year, index, 0).getDate();
  const offset = (new Date(year, index-1, 1).getDay()+6)%7;
  return { offset, days:Array.from({length:total},(_,i)=>`${month}-${String(i+1).padStart(2,"0")}`) };
}

export default function DevelopmentCalendar({child,onClose}) {
  const [month,setMonth]=useState(currentMonthWib); const [selected,setSelected]=useState(todayWib);
  const [enabled,setEnabled]=useState(FILTERS.map(([key])=>key)); const [data,setData]=useState({items:[]});
  const [status,setStatus]=useState("loading"); const [error,setError]=useState("");
  const params=useMemo(()=>({month,categories:enabled}),[month,enabled]);
  useEffect(()=>{let active=true;setStatus("loading");setError("");api.developmentCalendar(child.id,params)
    .then(value=>{if(active){setData(value);setStatus("ready");}})
    .catch(err=>{if(active){setError(err.message);setStatus("error");}});return()=>{active=false;};},[child.id,params]);
  useEffect(()=>{if(!selected.startsWith(month))setSelected(`${month}-01`);},[month,selected]);
  const grid=useMemo(()=>monthDays(month),[month]);
  const byDate=useMemo(()=>data.items.reduce((result,item)=>{(result[item.date]??=[]).push(item);return result;},{}),[data.items]);
  const agenda=byDate[selected]||[]; const toggle=(key)=>setEnabled(old=>old.includes(key)?old.filter(x=>x!==key):[...old,key]);
  const monthLabel=new Date(`${month}-01T00:00:00`).toLocaleDateString("id-ID",{month:"long",year:"numeric"});
  return <div className="fixed inset-0 z-[80] flex items-end justify-center bg-black/40 sm:items-center" role="dialog" aria-label="Kalender perkembangan">
    <div className="max-h-[94vh] w-full max-w-lg overflow-y-auto rounded-t-3xl bg-void p-5 sm:rounded-3xl">
      <div className="flex items-center justify-between"><div><h2 className="text-lg font-bold text-ink">Kalender perkembangan</h2><p className="text-xs text-ink-faint">Agenda dan momen {child.nickname||child.name}</p></div><button onClick={onClose} aria-label="Tutup" className="rounded-full bg-void-card px-3 py-2">✕</button></div>
      <div className="mt-5 flex items-center justify-between rounded-2xl border border-void-hairline bg-void-card p-2"><button onClick={()=>setMonth(x=>shiftMonth(x,-1))} aria-label="Bulan sebelumnya" className="px-3 py-2">‹</button><strong className="capitalize text-sm text-ink">{monthLabel}</strong><button onClick={()=>setMonth(x=>shiftMonth(x,1))} aria-label="Bulan berikutnya" className="px-3 py-2">›</button></div>
      <div className="-mx-1 mt-3 flex gap-2 overflow-x-auto px-1 pb-2">{FILTERS.map(([key,label])=><button key={key} onClick={()=>toggle(key)} className={`shrink-0 rounded-full px-3 py-1.5 text-[11px] font-semibold ${enabled.includes(key)?"bg-sleep text-white":"border border-void-hairline text-ink-faint"}`}>{label}</button>)}</div>
      <div className="mt-2 grid grid-cols-7 text-center text-[10px] font-bold text-ink-faint">{["Sen","Sel","Rab","Kam","Jum","Sab","Min"].map(x=><div key={x} className="py-2">{x}</div>)}</div>
      {status==="loading"?<p className="py-16 text-center text-sm text-ink-faint">Menyusun kalender...</p>:status==="error"?<div className="my-5 rounded-xl bg-warn/10 p-4 text-sm text-warn">{error}</div>:<div className="grid grid-cols-7 gap-1">
        {Array.from({length:grid.offset},(_,i)=><div key={`empty-${i}`} />)}
        {grid.days.map(value=>{const events=byDate[value]||[];const day=Number(value.slice(-2));return <button key={value} onClick={()=>setSelected(value)} aria-label={`Pilih tanggal ${value}`} className={`min-h-14 rounded-xl border p-1 text-left ${selected===value?"border-sleep bg-sleep/10":"border-transparent bg-void-card"}`}><span className={`flex h-6 w-6 items-center justify-center rounded-full text-xs ${value===todayWib()?"bg-feed font-bold text-white":"text-ink"}`}>{day}</span><span className="mt-1 flex flex-wrap gap-0.5">{events.slice(0,4).map(item=><i key={item.id} className={`h-1.5 w-1.5 rounded-full ${COLORS[item.type]||"bg-ink-faint"}`} />)}{events.length>4&&<small className="text-[8px] text-ink-faint">+{events.length-4}</small>}</span></button>;})}
      </div>}
      <div className="mt-5 border-t border-void-hairline pt-4"><h3 className="text-sm font-bold text-ink">Agenda {new Date(`${selected}T00:00:00`).toLocaleDateString("id-ID",{day:"numeric",month:"long"})}</h3>
        {agenda.length===0?<p className="mt-3 rounded-xl bg-void-card p-4 text-xs text-ink-faint">Belum ada agenda atau momen pada tanggal ini.</p>:<div className="mt-3 space-y-2">{agenda.map(item=><article key={item.id} className="flex gap-3 rounded-xl border border-void-hairline bg-void-card p-3"><span className="text-xl">{item.icon}</span><div><p className="text-sm font-bold text-ink">{item.title}</p><p className="text-xs text-ink-muted">{item.summary}</p></div></article>)}</div>}
      </div>
      {data.privacy_note&&<p className="mt-4 text-[10px] leading-relaxed text-ink-faint">🔒 {data.privacy_note}</p>}
    </div>
  </div>;
}
