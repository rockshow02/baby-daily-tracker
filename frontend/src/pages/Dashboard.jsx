import { useEffect, useState, useCallback } from "react";
import { api } from "../api/client";
import DailyRadialClock from "../components/DailyRadialClock";
import FeedingPredictionCard from "../components/FeedingPredictionCard";
import WakeWindowCard from "../components/WakeWindowCard";
import NextVaccineCard from "../components/NextVaccineCard";
import RelatedArticles from "../components/RelatedArticles";
import StatusPill from "../components/StatusPill";
import QuickLogSheet from "../components/QuickLogSheet";
import { todayWIB, toWIBDateStr } from "../utils/date";

const todayStr = () => todayWIB();

function formatAge(days) {
  if (days < 60) return `${days} hari`;
  const months = Math.floor(days / 30.44);
  return `${months} bulan`;
}

function timeOf(iso) {
  return new Date(iso).toLocaleTimeString("id-ID", { hour: "2-digit", minute: "2-digit" });
}

/**
 * Label rentang waktu tidur, dipotong (clip) sesuai tanggal yang lagi dilihat.
 * Sesi yang mulai kemarin dan lanjut sampai hari ini bakal kelihatan
 * "00:00 - 05:00 (lanjutan)" pas dilihat di hari ini, dan "20:00 - 24:00
 * (lanjut besok)" pas dilihat di hari kemarin — bukan nampilin rentang
 * penuh yang sama persis di kedua hari (membingungkan).
 */
function sleepTimeRangeLabel(item, viewedDate) {
  const startDateStr = toWIBDateStr(new Date(item.start_time));
  const startsBeforeViewedDay = startDateStr < viewedDate;
  const startLabel = startsBeforeViewedDay ? "00:00" : timeOf(item.start_time);

  if (!item.end_time) {
    return `${startLabel} - berlangsung`;
  }

  const endDateStr = toWIBDateStr(new Date(item.end_time));
  const endsAfterViewedDay = endDateStr > viewedDate;
  const endLabel = endsAfterViewedDay ? "24:00" : timeOf(item.end_time);

  const suffix = startsBeforeViewedDay ? " (lanjutan)" : endsAfterViewedDay ? " (lanjut besok)" : "";
  return `${startLabel} - ${endLabel}${suffix}`;
}

const FEED_TYPE_LABEL = {
  asi_langsung: "ASI Langsung",
  asi_perah: "ASI Perah",
  sufor: "Sufor",
  mpasi: "MPASI",
};

const OTHER_ACTIVITIES = [
  { type: "pumping", icon: "🤱", label: "Perah ASI" },
  { type: "stroll", icon: "🚶", label: "Jalan-jalan" },
  { type: "bathing", icon: "🛁", label: "Mandi" },
  { type: "vitamin", icon: "💊", label: "Vitamin D" },
];

export default function Dashboard({ child, onOpenProfile }) {
  const [date, setDate] = useState(todayStr());
  const [summary, setSummary] = useState(null);
  const [feedingLogs, setFeedingLogs] = useState([]);
  const [sleepLogs, setSleepLogs] = useState([]);
  const [diaperLogs, setDiaperLogs] = useState([]);
  const [pumpingLogs, setPumpingLogs] = useState([]);
  const [activityLogs, setActivityLogs] = useState([]);
  const [medicationLogs, setMedicationLogs] = useState([]);
  const [sheetType, setSheetType] = useState(null); // 'feeding' | 'sleep' | 'diaper' | 'pumping' | 'stroll' | 'bathing' | 'vitamin' | null
  const [editingItem, setEditingItem] = useState(null); // item riwayat yang lagi diedit, atau null buat catat baru
  const [showMoreMenu, setShowMoreMenu] = useState(false);
  const [loading, setLoading] = useState(true);

  const isToday = date === todayStr();

  const loadAll = useCallback(async () => {
    setLoading(true);
    try {
      const [s, f, sl, d, p, a, m] = await Promise.all([
        api.dailySummary(child.id, date),
        api.listFeeding(child.id, date),
        api.listSleep(child.id, date),
        api.listDiaper(child.id, date),
        api.listPumping(child.id, date),
        api.listActivity(child.id, date),
        api.listMedication(child.id, date),
      ]);
      setSummary(s);
      setFeedingLogs(f);
      setSleepLogs(sl);
      setDiaperLogs(d);
      setPumpingLogs(p);
      setActivityLogs(a);
      setMedicationLogs(m);
    } finally {
      setLoading(false);
    }
  }, [child.id, date]);

  useEffect(() => {
    loadAll();
  }, [loadAll]);

  const handleCreate = async (type, payload) => {
    if (type === "feeding") await api.createFeeding(child.id, payload);
    if (type === "sleep") await api.createSleep(child.id, payload);
    if (type === "diaper") await api.createDiaper(child.id, payload);
    if (type === "pumping") await api.createPumping(child.id, payload);
    if (type === "stroll" || type === "bathing") await api.createActivity(child.id, payload);
    if (type === "vitamin") await api.createMedication(child.id, payload);
    await loadAll();
  };

  const handleUpdate = async (kind, id, payload) => {
    if (kind === "feeding") await api.updateFeeding(id, payload);
    if (kind === "sleep") await api.updateSleep(id, payload);
    if (kind === "diaper") await api.updateDiaper(id, payload);
    if (kind === "pumping") await api.updatePumping(id, payload);
    if (kind === "stroll" || kind === "bathing") await api.updateActivity(id, payload);
    if (kind === "vitamin") await api.updateMedication(id, payload);
    await loadAll();
  };

  const handleSheetSubmit = async (payload) => {
    if (editingItem) {
      await handleUpdate(editingItem.kind, editingItem.id, payload);
    } else {
      await handleCreate(sheetType, payload);
    }
  };

  const openEdit = (item) => {
    setSheetType(item.kind);
    setEditingItem(item);
  };

  const closeSheet = () => {
    setSheetType(null);
    setEditingItem(null);
  };

  const handleDelete = async (kind, id) => {
    if (kind === "feeding") await api.deleteFeeding(id);
    if (kind === "sleep") await api.deleteSleep(id);
    if (kind === "diaper") await api.deleteDiaper(id);
    if (kind === "pumping") await api.deletePumping(id);
    if (kind === "stroll" || kind === "bathing") await api.deleteActivity(id);
    if (kind === "vitamin") await api.deleteMedication(id);
    await loadAll();
  };

  const handleWakeUp = async (sleepLogId) => {
    await api.updateSleep(sleepLogId, { end_time: new Date().toISOString() });
    await loadAll();
  };

  const shiftDate = (deltaDays) => {
    const d = new Date(date);
    d.setDate(d.getDate() + deltaDays);
    const next = toWIBDateStr(d);
    if (next > todayStr()) return;
    setDate(next);
  };

  // gabungkan semua log jadi satu riwayat urut waktu
  const historyItems = [
    ...feedingLogs.map((l) => ({ ...l, kind: "feeding", at: l.timestamp })),
    ...diaperLogs.map((l) => ({ ...l, kind: "diaper", at: l.timestamp })),
    ...sleepLogs.map((l) => ({ ...l, kind: "sleep", at: l.start_time })),
    ...pumpingLogs.map((l) => ({ ...l, kind: "pumping", at: l.timestamp })),
    ...activityLogs.map((l) => ({ ...l, kind: l.activity_type, at: l.timestamp })),
    ...medicationLogs.map((l) => ({ ...l, kind: "vitamin", at: l.timestamp })),
  ].sort((a, b) => new Date(b.at) - new Date(a.at));

  const dotColor = (kind) => {
    if (kind === "feeding" || kind === "pumping" || kind === "vitamin") return "bg-feed";
    if (kind === "sleep" || kind === "stroll") return "bg-sleep";
    return "bg-diaper"; // diaper, bathing
  };

  // ringkasan ala PiyoLog: ASI langsung vs botol dipisah, biar lebih detail
  const nursingCount = feedingLogs.filter((l) => l.feed_type === "asi_langsung").length;
  const bottleLogs = feedingLogs.filter((l) => l.feed_type === "asi_perah" || l.feed_type === "sufor");
  const bottleCount = bottleLogs.length;
  const bottleMl = bottleLogs.reduce((sum, l) => sum + (l.volume_ml || 0), 0);
  // pakai angka dari summary.sleep.actual_hours (backend), BUKAN jumlah
  // mentah duration_minutes dari sleepLogs — soalnya sleepLogs sekarang
  // termasuk sesi yang lintas tengah malam (overlap sama hari ini), dan
  // duration_minutes-nya itu durasi PENUH sesi itu, belum dipotong sesuai
  // porsi hari yang lagi dilihat. summary.sleep.actual_hours udah bener
  // dipotong per hari (fix yang sama kayak Bug #2 sebelumnya).
  const sleepActualHours = summary ? summary.sleep.actual_hours : 0;
  const sleepH = Math.floor(sleepActualHours);
  const sleepM = Math.round((sleepActualHours % 1) * 60);
  const wetCount = diaperLogs.filter((l) => l.diaper_type === "pipis" || l.diaper_type === "keduanya").length;
  const dirtyCount = diaperLogs.filter((l) => l.diaper_type === "pup" || l.diaper_type === "keduanya").length;

  return (
    <div className="min-h-screen pb-32">
      {/* header */}
      <header className="px-6 pt-8 pb-4">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            {child.photo_filename && (
              <img
                src={api.photoUrl(child.photo_filename)}
                alt={child.name}
                className="w-12 h-12 rounded-full object-cover border border-void-hairline"
              />
            )}
            <div>
              <p className="font-mono text-xs text-ink-faint tracking-[0.2em] uppercase">
                {summary ? formatAge(summary.age_days) : "..."}
              </p>
              <h1 className="font-display text-3xl text-ink">{child.nickname || child.name}</h1>
            </div>
          </div>
          <div className="flex items-center gap-2 bg-void-card border border-void-hairline rounded-full px-1 py-1">
            <button onClick={() => shiftDate(-1)} className="w-8 h-8 flex items-center justify-center text-ink-muted">
              ‹
            </button>
            <span className="font-mono text-xs text-ink-muted min-w-[64px] text-center">
              {isToday ? "Hari ini" : new Date(date).toLocaleDateString("id-ID", { day: "2-digit", month: "short" })}
            </span>
            <button
              onClick={() => shiftDate(1)}
              disabled={isToday}
              className="w-8 h-8 flex items-center justify-center text-ink-muted disabled:opacity-30"
            >
              ›
            </button>
          </div>
        </div>
        <div className="flex items-center gap-4 mt-3">
          <a
            href={api.exportPdfUrl(child.id)}
            target="_blank"
            rel="noreferrer"
            className="inline-flex items-center gap-1.5 text-xs text-ink-muted"
          >
            📄 Export laporan PDF
          </a>
          <a
            href={api.exportJsonUrl(child.id)}
            target="_blank"
            rel="noreferrer"
            download={`backup-${child.name.toLowerCase()}.json`}
            className="inline-flex items-center gap-1.5 text-xs text-ink-muted"
          >
            💾 Backup data (JSON)
          </a>
        </div>
      </header>

      {/* ringkasan harian ala PiyoLog */}
      <div className="px-6 mb-4">
        <div className="flex items-center justify-between bg-void-card border border-void-hairline rounded-xl2 px-3 py-2.5 overflow-x-auto gap-4">
          <div className="flex flex-col items-center flex-shrink-0">
            <span className="text-base">🤱</span>
            <span className="text-[11px] text-ink font-semibold">{nursingCount}x</span>
          </div>
          <div className="w-px h-8 bg-void-hairline flex-shrink-0" />
          <div className="flex flex-col items-center flex-shrink-0">
            <span className="text-base">🍼</span>
            <span className="text-[11px] text-ink font-semibold">
              {bottleCount}x <span className="text-ink-faint font-normal">{bottleMl}ml</span>
            </span>
          </div>
          <div className="w-px h-8 bg-void-hairline flex-shrink-0" />
          <div className="flex flex-col items-center flex-shrink-0">
            <span className="text-base">🌙</span>
            <span className="text-[11px] text-ink font-semibold">
              {sleepH}j {sleepM}m
            </span>
          </div>
          <div className="w-px h-8 bg-void-hairline flex-shrink-0" />
          <div className="flex flex-col items-center flex-shrink-0">
            <span className="text-base">💧</span>
            <span className="text-[11px] text-ink font-semibold">{wetCount}x</span>
          </div>
          <div className="w-px h-8 bg-void-hairline flex-shrink-0" />
          <div className="flex flex-col items-center flex-shrink-0">
            <span className="text-base">💩</span>
            <span className="text-[11px] text-ink font-semibold">{dirtyCount}x</span>
          </div>
        </div>
      </div>

      <div className="px-6">
        <NextVaccineCard childId={child.id} />
      </div>

      {isToday && (
        <div className="px-6">
          <FeedingPredictionCard childId={child.id} refreshKey={feedingLogs.length} />
          <WakeWindowCard childId={child.id} refreshKey={sleepLogs.length} />
        </div>
      )}

      {/* info singkat anak */}
      <div className="px-6 mb-4">
        <div className="bg-void-card border border-void-hairline rounded-xl2 px-4 py-3.5 flex items-center justify-between">
          <div>
            <p className="text-sm text-ink">
              {child.nickname || child.name} · {summary ? formatAge(summary.age_days) : "..."}
            </p>
            <p className="text-xs text-ink-faint mt-0.5">
              {child.gender === "L" ? "Laki-laki" : child.gender === "P" ? "Perempuan" : ""}
              {child.birth_weight_kg && ` · Lahir ${child.birth_weight_kg} kg`}
              {child.birth_height_cm && ` / ${child.birth_height_cm} cm`}
            </p>
          </div>
          <button
            onClick={onOpenProfile}
            className="text-xs text-feed font-medium whitespace-nowrap flex-shrink-0 ml-3"
          >
            Lihat Selengkapnya →
          </button>
        </div>
      </div>

      {/* radial clock */}
      <div className="px-6 py-4 flex justify-center">
        <DailyRadialClock feedingLogs={feedingLogs} sleepLogs={sleepLogs} diaperLogs={diaperLogs} />
      </div>

      {/* legend */}
      <div className="flex justify-center gap-4 -mt-2 mb-6">
        <span className="flex items-center gap-1.5 text-xs text-ink-muted">
          <span className="w-2 h-2 rounded-full bg-feed" /> Menyusui
        </span>
        <span className="flex items-center gap-1.5 text-xs text-ink-muted">
          <span className="w-2 h-2 rounded-full bg-sleep" /> Tidur
        </span>
        <span className="flex items-center gap-1.5 text-xs text-ink-muted">
          <span className="w-2 h-2 rounded-full bg-diaper" /> Popok
        </span>
      </div>

      {/* status pills */}
      {summary?.guideline_label ? (
        <div className="px-6 flex gap-3 overflow-x-auto pb-1">
          <StatusPill
            icon="🍼"
            title="Menyusui"
            actual={summary.feeding.actual}
            unit="x"
            range={
              summary.feeding.min != null ? `${summary.feeding.min}-${summary.feeding.max}x/hari (IDAI)` : null
            }
            status={summary.feeding.status}
          />
          <StatusPill
            icon="🌙"
            title="Tidur"
            actual={summary.sleep.actual_hours}
            unit="jam"
            range={summary.sleep.min != null ? `${summary.sleep.min}-${summary.sleep.max} jam/hari` : null}
            status={summary.sleep.status}
          />
          <StatusPill
            icon="💧"
            title="BAK (pipis)"
            actual={summary.wet_diaper.actual}
            unit="x"
            range={summary.wet_diaper.min != null ? `min ${summary.wet_diaper.min}x/hari` : null}
            status={summary.wet_diaper.status}
          />
        </div>
      ) : (
        summary?.message && <p className="px-6 text-sm text-ink-faint text-center">{summary.message}</p>
      )}

      {/* riwayat */}
      <div className="px-6 mt-8">
        <h2 className="font-mono text-xs text-ink-faint tracking-[0.2em] uppercase mb-3">Riwayat</h2>
        {loading ? (
          <p className="text-ink-faint text-sm">Memuat...</p>
        ) : historyItems.length === 0 ? (
          <p className="text-ink-faint text-sm">Belum ada catatan {isToday ? "hari ini" : "di tanggal ini"}.</p>
        ) : (
          <div className="space-y-2">
            {historyItems.map((item) => (
              <div
                key={`${item.kind}-${item.id}`}
                onClick={() => openEdit(item)}
                className="flex items-center justify-between bg-void-card border border-void-hairline rounded-xl2 px-4 py-3 cursor-pointer active:bg-void-raised"
              >
                <div className="flex items-center gap-3">
                  <span className={`w-2 h-2 rounded-full ${dotColor(item.kind)}`} />
                  <div>
                    <p className="text-sm text-ink">
                      {item.kind === "feeding" && FEED_TYPE_LABEL[item.feed_type]}
                      {item.kind === "sleep" && `Tidur ${item.sleep_type}`}
                      {item.kind === "diaper" &&
                        (item.diaper_type === "pipis" ? "Pipis" : item.diaper_type === "pup" ? "Pup" : "Pipis + Pup")}
                      {item.kind === "pumping" && "Perah ASI"}
                      {item.kind === "stroll" && "Jalan-jalan"}
                      {item.kind === "bathing" && "Mandi"}
                      {item.kind === "vitamin" && (item.medication_name || "Vitamin D")}
                    </p>
                    <p className="text-xs text-ink-faint font-mono">
                      {item.kind === "sleep" ? sleepTimeRangeLabel(item, date) : timeOf(item.at)}
                      {item.kind === "feeding" && item.duration_minutes && ` · ${item.duration_minutes} mnt`}
                      {item.kind === "feeding" && item.volume_ml && ` · ${item.volume_ml} ml`}
                      {item.kind === "pumping" && ` · ${item.duration_minutes} mnt · ${item.volume_ml} ml`}
                      {(item.kind === "stroll" || item.kind === "bathing") &&
                        item.duration_minutes &&
                        ` · ${item.duration_minutes} mnt`}
                      {(item.kind === "stroll" || item.kind === "bathing") && item.notes && ` · ${item.notes}`}
                    </p>
                    {item.created_by_name && (
                      <p className="text-[11px] text-ink-faint mt-0.5">oleh {item.created_by_name}</p>
                    )}
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  {item.kind === "sleep" && !item.end_time && (
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        handleWakeUp(item.id);
                      }}
                      className="text-xs px-3 py-1.5 rounded-full bg-sleep text-white font-medium"
                    >
                      🌤️ Bangun
                    </button>
                  )}
                  <button
                    onClick={(e) => {
                      e.stopPropagation();
                      handleDelete(item.kind, item.id);
                    }}
                    className="text-ink-faint text-xs px-2 py-1"
                    aria-label="Hapus catatan"
                  >
                    Hapus
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      <div className="px-6">
        <RelatedArticles category="feeding" ageMonths={summary ? summary.age_days / 30.4375 : null} />
      </div>

      {/* quick log bar */}
      <div className="fixed bottom-0 left-0 right-0 px-6 pb-6 pt-4 bg-gradient-to-t from-void via-void to-transparent">
        <div className="max-w-sm mx-auto grid grid-cols-4 gap-2.5">
          <button
            onClick={() => { setEditingItem(null); setSheetType("feeding"); }}
            className="flex flex-col items-center gap-1.5 bg-feed text-white rounded-xl2 py-3.5 font-medium text-xs"
          >
            <span className="text-xl">🍼</span>
            Susu
          </button>
          <button
            onClick={() => { setEditingItem(null); setSheetType("sleep"); }}
            className="flex flex-col items-center gap-1.5 bg-sleep text-white rounded-xl2 py-3.5 font-medium text-xs"
          >
            <span className="text-xl">🌙</span>
            Tidur
          </button>
          <button
            onClick={() => { setEditingItem(null); setSheetType("diaper"); }}
            className="flex flex-col items-center gap-1.5 bg-diaper text-white rounded-xl2 py-3.5 font-medium text-xs"
          >
            <span className="text-xl">💧</span>
            Popok
          </button>
          <button
            onClick={() => setShowMoreMenu(true)}
            className="flex flex-col items-center gap-1.5 bg-void-raised border border-void-hairline text-ink rounded-xl2 py-3.5 font-medium text-xs"
          >
            <span className="text-xl">✚</span>
            Lainnya
          </button>
        </div>
      </div>

      {/* menu "lainnya" */}
      {showMoreMenu && (
        <div className="fixed inset-0 z-50 flex items-end sm:items-center sm:justify-center">
          <div className="absolute inset-0 bg-black/60" onClick={() => setShowMoreMenu(false)} />
          <div className="relative w-full sm:max-w-sm bg-void-card border-t sm:border border-void-hairline rounded-t-xl2 sm:rounded-xl2 p-6 pb-8">
            <div className="w-10 h-1 bg-void-hairline rounded-full mx-auto mb-5 sm:hidden" />
            <h2 className="font-display text-2xl text-ink mb-5">Aktivitas Lainnya</h2>
            <div className="grid grid-cols-3 gap-3">
              {OTHER_ACTIVITIES.map((a) => (
                <button
                  key={a.type}
                  onClick={() => {
                    setShowMoreMenu(false);
                    setEditingItem(null);
                    setSheetType(a.type);
                  }}
                  className="flex flex-col items-center gap-2 bg-void border border-void-hairline rounded-xl2 py-4 text-xs text-ink-muted"
                >
                  <span className="text-2xl">{a.icon}</span>
                  {a.label}
                </button>
              ))}
            </div>
            <button
              onClick={() => setShowMoreMenu(false)}
              className="w-full py-3 mt-6 rounded-lg border border-void-hairline text-ink-muted text-sm"
            >
              Batal
            </button>
          </div>
        </div>
      )}

      {sheetType && (
        <QuickLogSheet
          type={sheetType}
          editingLog={editingItem}
          onClose={closeSheet}
          onSubmit={handleSheetSubmit}
          onDelete={editingItem ? () => handleDelete(editingItem.kind, editingItem.id) : undefined}
        />
      )}
    </div>
  );
}