import {useState} from "react";
import DevelopmentCalendar from "./DevelopmentCalendar";
import DevelopmentGoals from "./DevelopmentGoals";
import FamilyDevelopmentCheckIn from "./FamilyDevelopmentCheckIn";
import MonthlyStory from "./MonthlyStory";

const FEATURES=[
  {key:"calendar",icon:"📅",title:"Kalender",description:"Lihat agenda dan momen dalam tampilan bulanan.",tone:"bg-sleep-soft text-sleep"},
  {key:"checkin",icon:"🌱",title:"Check-in",description:"Refleksi perkembangan bulanan bersama keluarga.",tone:"bg-diaper-soft text-diaper"},
  {key:"goals",icon:"🎯",title:"Tujuan",description:"Susun rencana keluarga tanpa target medis.",tone:"bg-feed-soft text-feed"},
  {key:"story",icon:"📖",title:"Cerita Bulanan",description:"Rangkum momen pilihan menjadi cerita dan PDF.",tone:"bg-sky-soft text-sky"},
];

export default function DevelopmentHub({child,onClose}){
 const[active,setActive]=useState(null);
 if(active==="calendar")return <DevelopmentCalendar child={child} onClose={()=>setActive(null)}/>;
 if(active==="checkin")return <FamilyDevelopmentCheckIn child={child} onClose={()=>setActive(null)}/>;
 if(active==="goals")return <DevelopmentGoals child={child} onClose={()=>setActive(null)}/>;
 if(active==="story")return <MonthlyStory child={child} onClose={()=>setActive(null)}/>;
 return <div className="fixed inset-0 z-[70] overflow-y-auto bg-void"><div className="mx-auto min-h-screen max-w-lg px-4 pb-24 pt-6"><div className="flex items-start justify-between gap-4"><div><p className="text-[11px] font-bold uppercase tracking-[0.18em] text-sleep">Tumbuh bersama</p><h1 className="font-display text-3xl font-bold text-ink">Development Hub</h1><p className="mt-1 text-sm text-ink-muted">Cerita, rencana, dan refleksi {child.nickname||child.name} dalam satu tempat.</p></div><button onClick={onClose} className="shrink-0 rounded-full border border-void-hairline bg-white px-4 py-2 text-sm">Tutup</button></div><div className="mt-7 grid grid-cols-2 gap-3">{FEATURES.map(item=><button key={item.key} onClick={()=>setActive(item.key)} className="min-h-40 rounded-3xl border border-void-hairline bg-white p-4 text-left shadow-sm active:scale-[.98]"><span className={`flex h-12 w-12 items-center justify-center rounded-2xl text-2xl ${item.tone}`}>{item.icon}</span><h2 className="mt-4 text-sm font-bold text-ink">{item.title}</h2><p className="mt-1 text-xs leading-relaxed text-ink-faint">{item.description}</p></button>)}</div><div className="mt-5 rounded-2xl border border-void-hairline bg-void-card p-4"><p className="text-xs font-bold text-ink">Catatan penting</p><p className="mt-1 text-xs leading-relaxed text-ink-faint">Check-in dan tujuan adalah alat bantu keluarga, bukan diagnosis atau penilaian medis. Gunakan Persiapan Dokter untuk membawa hal yang ingin dikonsultasikan.</p></div></div></div>;
}
