import { useEffect, useState } from "react";
import { api, getCurrentUserId } from "../api/client";
import { todayWIB } from "../utils/date";

const draftKey = (childId) => `babytracker_memory_draft_${getCurrentUserId() || "anon"}_${childId}`;

function JournalPhoto({ entry }) {
  const [src, setSrc] = useState("");
  useEffect(() => {
    let active = true; let objectUrl;
    api.loadMemoryJournalPhoto(entry.id).then((url) => {
      objectUrl = url; if (active) setSrc(url);
    }).catch(() => {});
    return () => { active = false; if (objectUrl) URL.revokeObjectURL(objectUrl); };
  }, [entry.id]);
  return src ? <img src={src} alt={entry.caption || "Momen anak"} className="h-full w-full object-cover" />
    : <div className="flex h-full items-center justify-center bg-void-raised text-2xl">📷</div>;
}

export default function MemoryJournal({ child }) {
  const stored = (() => { try { return JSON.parse(localStorage.getItem(draftKey(child.id))) || {}; } catch { return {}; } })();
  const [data, setData] = useState({ items: [], can_create: false });
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);
  const [photo, setPhoto] = useState(null);
  const [caption, setCaption] = useState(stored.caption || "");
  const [occurredDate, setOccurredDate] = useState(stored.occurredDate || todayWIB());
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");
  const load = async () => { setLoading(true); try { setData(await api.listMemoryJournal(child.id)); } finally { setLoading(false); } };
  useEffect(() => { load(); }, [child.id]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    localStorage.setItem(draftKey(child.id), JSON.stringify({ caption, occurredDate }));
  }, [caption, occurredDate, child.id]);

  const submit = async (event) => {
    event.preventDefault(); setError("");
    if (!navigator.onLine) { setError("Foto hanya bisa diunggah saat online. Draft teks tetap tersimpan."); return; }
    if (!photo) { setError("Pilih foto terlebih dahulu."); return; }
    setSubmitting(true);
    try {
      await api.createMemoryJournal(child.id, { photo, caption, occurredDate });
      localStorage.removeItem(draftKey(child.id)); setCaption(""); setPhoto(null);
      setOccurredDate(todayWIB()); setShowForm(false); await load();
    } catch (err) { setError(err.message); } finally { setSubmitting(false); }
  };

  return <section>
    <div className="mb-4 flex items-center justify-between gap-3">
      <div><h2 className="text-base font-bold text-ink">Galeri kenangan</h2>
        <p className="text-xs text-ink-faint">Foto privat, hanya untuk caregiver {child.nickname || child.name}.</p></div>
      {data.can_create && <button onClick={() => setShowForm(true)} className="shrink-0 rounded-full bg-feed px-3.5 py-2.5 text-xs font-bold text-white">+ Foto</button>}
    </div>
    {loading ? <p className="py-10 text-center text-sm text-ink-faint">Memuat...</p> : data.items.length === 0 ?
      <div className="rounded-xl2 border border-dashed border-void-hairline bg-white/60 px-5 py-10 text-center">
        <div className="text-4xl">📸</div><p className="mt-3 text-sm font-bold text-ink">Belum ada foto kenangan</p>
        <p className="mt-1 text-xs text-ink-faint">Simpan satu momen kecil hari ini.</p></div> :
      <div className="grid grid-cols-2 gap-3">{data.items.map((entry) =>
        <article key={entry.id} className="overflow-hidden rounded-2xl border border-void-hairline bg-void-card shadow-sm">
          <div className="aspect-square"><JournalPhoto entry={entry} /></div>
          <div className="p-3"><p className="text-xs font-semibold text-ink">{entry.caption || "Momen berharga"}</p>
            <p className="mt-1 text-[11px] text-ink-faint">{new Date(`${entry.occurred_date}T00:00:00`).toLocaleDateString("id-ID")}</p>
            {entry.can_edit && <div className="mt-2 flex gap-3">
              <button onClick={async () => {
                const next = prompt("Ubah caption", entry.caption || "");
                if (next !== null) { await api.updateMemoryJournal(entry.id, { caption: next }); await load(); }
              }} className="text-[11px] text-sleep">Edit caption</button>
              <button onClick={async () => { if (confirm("Hapus foto kenangan ini?")) { await api.deleteMemoryJournal(entry.id); await load(); } }} className="text-[11px] text-warn">Hapus</button>
            </div>}
          </div></article>)}</div>}
    {showForm && <div className="fixed inset-0 z-50 flex items-end sm:items-center sm:justify-center">
      <div className="absolute inset-0 bg-black/50" onClick={() => setShowForm(false)} />
      <form onSubmit={submit} className="relative w-full rounded-t-xl2 bg-void-card p-6 pb-8 sm:max-w-sm sm:rounded-xl2">
        <h2 className="font-display text-2xl font-bold text-ink">Tambah Kenangan</h2>
        <p className="mb-4 text-xs text-ink-faint">Foto dikompresi agar hemat penyimpanan.</p>
        <label className="mb-1 block text-xs text-ink-muted">Foto (maks. 5 MB)</label>
        <input type="file" accept="image/jpeg,image/png,image/webp" onChange={(e) => setPhoto(e.target.files?.[0] || null)} className="mb-3 w-full text-sm" required />
        <label className="mb-1 block text-xs text-ink-muted">Tanggal momen</label>
        <input type="date" max={todayWIB()} value={occurredDate} onChange={(e) => setOccurredDate(e.target.value)} className="mb-3 w-full rounded-lg border border-void-hairline bg-void px-3 py-2.5" required />
        <label className="mb-1 block text-xs text-ink-muted">Caption (opsional)</label>
        <textarea maxLength={500} value={caption} onChange={(e) => setCaption(e.target.value)} className="mb-3 min-h-20 w-full rounded-lg border border-void-hairline bg-void px-3 py-2.5" />
        {error && <p className="mb-3 text-sm text-warn">{error}</p>}
        <div className="flex gap-3"><button type="button" onClick={() => setShowForm(false)} className="flex-1 rounded-lg border border-void-hairline py-3 text-sm">Batal</button>
          <button disabled={submitting} className="flex-1 rounded-lg bg-feed py-3 text-sm font-bold text-white disabled:opacity-50">{submitting ? "Menyimpan..." : "Simpan"}</button></div>
      </form></div>}
  </section>;
}
