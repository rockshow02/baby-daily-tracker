import { useEffect, useState } from "react";
import { api } from "../api/client";

const humanBytes = (bytes) => bytes < 1024 ? `${bytes} B` : bytes < 1024*1024 ? `${(bytes/1024).toFixed(1)} KB` : `${(bytes/1024/1024).toFixed(1)} MB`;

export default function MemoryStorageManager({ child, onClose, onChanged }) {
  const [data, setData] = useState(null); const [status, setStatus] = useState("loading");
  const [error, setError] = useState(""); const [dryRun, setDryRun] = useState(null);
  const [confirmation, setConfirmation] = useState(""); const [busy, setBusy] = useState(false);
  const load = async () => { setStatus("loading"); try { setData(await api.memoryStorage(child.id)); setStatus("ready"); } catch(e){setError(e.message);setStatus("error");} };
  useEffect(()=>{load();},[child.id]); // eslint-disable-line react-hooks/exhaustive-deps
  const previewCleanup = async () => { setBusy(true); setError(""); try { setDryRun(await api.cleanupMemoryStorage(child.id,{apply:false})); } catch(e){setError(e.message);} finally{setBusy(false);} };
  const applyCleanup = async () => { setBusy(true); setError(""); try { await api.cleanupMemoryStorage(child.id,{apply:true,confirmation}); setDryRun(null);setConfirmation("");await load(); } catch(e){setError(e.message);} finally{setBusy(false);} };
  const optimize = async (id) => { setBusy(true);setError("");try{await api.optimizeMemoryPhoto(child.id,id);await load();await onChanged?.();}catch(e){setError(e.message);}finally{setBusy(false);} };
  return <div className="fixed inset-0 z-50 overflow-y-auto bg-void"><div className="mx-auto min-h-screen max-w-lg px-4 pb-20 pt-5">
    <div className="mb-5 flex items-center justify-between"><div><p className="text-[11px] font-bold uppercase tracking-widest text-diaper">Photo Health</p><h1 className="font-display text-3xl font-bold text-ink">Penyimpanan Foto</h1></div><button onClick={onClose} className="rounded-full border border-void-hairline bg-white px-4 py-2 text-sm">Tutup</button></div>
    {status==="loading"?<p className="py-10 text-center text-sm text-ink-faint">Menghitung penyimpanan...</p>:status==="error"?<p className="rounded-xl bg-warn/10 p-4 text-sm text-warn">{error}</p>:<>
      <section className="rounded-2xl border border-void-hairline bg-white p-5"><div className="flex items-end justify-between"><div><p className="text-xs text-ink-faint">Total galeri</p><p className="text-2xl font-bold text-ink">{humanBytes(data.actual_bytes)}</p></div><p className="text-sm text-ink-muted">{data.photo_count} foto</p></div>
        <div className="mt-3 h-2 overflow-hidden rounded-full bg-void-raised"><div className={`h-full ${data.warning?"bg-warn":"bg-diaper"}`} style={{width:`${Math.min(100,data.usage_percent||0)}%`}}/></div><p className="mt-2 text-[11px] text-ink-faint">Peringatan pada {humanBytes(data.warning_bytes)} · {data.usage_percent ?? 0}% terpakai</p>
        {data.warning&&<p className="mt-3 rounded-xl bg-warn/10 p-3 text-xs text-warn">Pemakaian foto melewati batas peringatan. Optimalkan atau hapus foto yang tidak diperlukan.</p>}</section>
      <section className="mt-4 rounded-2xl border border-void-hairline bg-white p-5"><h2 className="text-sm font-bold text-ink">Kesehatan file</h2><div className="mt-3 grid grid-cols-2 gap-3"><div className="rounded-xl bg-feed-soft p-3"><b className="text-xl text-ink">{data.missing_file_count}</b><p className="text-[11px] text-ink-muted">Data tanpa file</p></div><div className="rounded-xl bg-sleep-soft p-3"><b className="text-xl text-ink">{data.orphan_file_count}</b><p className="text-[11px] text-ink-muted">File tanpa data</p></div></div>
        {data.orphan_file_count>0&&<><button disabled={busy} onClick={previewCleanup} className="mt-4 w-full rounded-xl border border-sleep py-2.5 text-xs font-bold text-sleep">Dry-run pembersihan</button>{dryRun&&<div className="mt-3 rounded-xl border border-void-hairline p-3"><p className="text-xs text-ink">Akan menghapus {dryRun.would_delete_count} file ({humanBytes(dryRun.would_delete_bytes)}).</p><input value={confirmation} onChange={(e)=>setConfirmation(e.target.value)} placeholder="Ketik BERSIHKAN" className="mt-3 w-full rounded-lg border border-void-hairline px-3 py-2 text-sm"/><button disabled={busy||confirmation!=="BERSIHKAN"} onClick={applyCleanup} className="mt-2 w-full rounded-lg bg-warn py-2.5 text-xs font-bold text-white disabled:opacity-40">Terapkan pembersihan</button></div>}</>}
      </section>
      <section className="mt-4"><h2 className="mb-2 text-sm font-bold text-ink">Foto terbesar</h2><div className="space-y-2">{data.largest.map((item)=><div key={item.id} className="flex items-center justify-between rounded-xl border border-void-hairline bg-white p-3"><div><p className="text-xs font-semibold text-ink">{item.caption||"Momen berharga"}</p><p className="text-[11px] text-ink-faint">{item.occurred_date} · {humanBytes(item.size_bytes)}</p></div><button disabled={busy} onClick={()=>optimize(item.id)} className="rounded-full bg-diaper-soft px-3 py-2 text-[11px] font-bold text-diaper">Optimalkan</button></div>)}</div></section>
      {error&&<p className="mt-4 rounded-xl bg-warn/10 p-3 text-sm text-warn">{error}</p>}
    </>}
  </div></div>;
}
