import { useState } from "react";
import SteppedDateTimeInput from "./SteppedDateTimeInput";

const toLocalInputValue = (date) => {
  const pad = (n) => String(n).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(
    date.getHours()
  )}:${pad(date.getMinutes())}`;
};

export default function QuickLogSheet({ type, onClose, onSubmit, onDelete, editingLog }) {
  const now = new Date();
  const isEdit = !!editingLog;

  const [feedType, setFeedType] = useState(editingLog?.feed_type || "asi_langsung");
  const [breastSide, setBreastSide] = useState(editingLog?.breast_side || "kiri");
  const [durationMinutes, setDurationMinutes] = useState(editingLog?.duration_minutes ?? 15);
  const [volumeMl, setVolumeMl] = useState(editingLog?.volume_ml ?? 60);

  const [startTime, setStartTime] = useState(
    editingLog?.start_time ? toLocalInputValue(new Date(editingLog.start_time)) : toLocalInputValue(now)
  );
  const [endTime, setEndTime] = useState(
    editingLog?.end_time ? toLocalInputValue(new Date(editingLog.end_time)) : ""
  );
  const [sleepType, setSleepType] = useState(
    editingLog?.sleep_type || (now.getHours() >= 19 || now.getHours() < 6 ? "malam" : "siang")
  );

  const [diaperType, setDiaperType] = useState(editingLog?.diaper_type || "pipis");
  const [consistency, setConsistency] = useState(editingLog?.consistency || "normal");

  const [pumpDuration, setPumpDuration] = useState(editingLog?.duration_minutes ?? 15);
  const [pumpVolume, setPumpVolume] = useState(editingLog?.volume_ml ?? 60);
  const [pumpSide, setPumpSide] = useState(editingLog?.breast_side || "kedua");

  const [activityDuration, setActivityDuration] = useState(editingLog?.duration_minutes ?? 20);
  const [activityNotes, setActivityNotes] = useState(editingLog?.notes || "");

  // waktu kejadian sebenarnya — default sekarang, tapi bisa digeser mundur
  // kalau baru sempat catat setelah beberapa saat (mis. lupa waktu di luar rumah)
  const [eventTime, setEventTime] = useState(
    editingLog?.at || editingLog?.timestamp
      ? toLocalInputValue(new Date(editingLog.at || editingLog.timestamp))
      : toLocalInputValue(now)
  );

  const [submitting, setSubmitting] = useState(false);
  const [deleting, setDeleting] = useState(false);

  const titles = {
    feeding: isEdit ? "Edit Menyusui" : "Catat Menyusui",
    sleep: isEdit ? "Edit Tidur" : "Catat Tidur",
    diaper: isEdit ? "Edit Popok" : "Catat Popok",
    pumping: isEdit ? "Edit Perah ASI" : "Catat Perah ASI",
    stroll: isEdit ? "Edit Jalan-jalan" : "Catat Jalan-jalan",
    bathing: isEdit ? "Edit Mandi" : "Catat Mandi",
    vitamin: isEdit ? "Edit Vitamin D" : "Catat Vitamin D",
  };
  const accents = {
    feeding: "border-feed",
    sleep: "border-sleep",
    diaper: "border-diaper",
    pumping: "border-feed",
    stroll: "border-sleep",
    bathing: "border-diaper",
    vitamin: "border-feed",
  };

  const handleDelete = async () => {
    if (!editingLog || !onDelete) return;
    setDeleting(true);
    try {
      await onDelete();
      onClose();
    } finally {
      setDeleting(false);
    }
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    setSubmitting(true);
    try {
      if (type === "feeding") {
        await onSubmit({
          timestamp: new Date(eventTime).toISOString(),
          feed_type: feedType,
          duration_minutes: feedType === "asi_langsung" ? Number(durationMinutes) : null,
          volume_ml: feedType !== "asi_langsung" ? Number(volumeMl) : null,
          breast_side: feedType === "asi_langsung" ? breastSide : null,
        });
      } else if (type === "sleep") {
        await onSubmit({
          start_time: new Date(startTime).toISOString(),
          end_time: endTime ? new Date(endTime).toISOString() : null,
          sleep_type: sleepType,
        });
      } else if (type === "diaper") {
        await onSubmit({
          timestamp: new Date(eventTime).toISOString(),
          diaper_type: diaperType,
          consistency: diaperType !== "pipis" ? consistency : null,
        });
      } else if (type === "pumping") {
        await onSubmit({
          timestamp: new Date(eventTime).toISOString(),
          duration_minutes: Number(pumpDuration),
          volume_ml: Number(pumpVolume),
          breast_side: pumpSide,
        });
      } else if (type === "stroll" || type === "bathing") {
        await onSubmit({
          timestamp: new Date(eventTime).toISOString(),
          activity_type: type,
          duration_minutes: Number(activityDuration),
          notes: activityNotes || null,
        });
      } else if (type === "vitamin") {
        await onSubmit({
          timestamp: new Date(eventTime).toISOString(),
          medication_name: "Vitamin D",
        });
      }
      onClose();
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-end sm:items-center sm:justify-center">
      <div className="absolute inset-0 bg-black/60" onClick={onClose} />
      <form
        onSubmit={handleSubmit}
        className={`relative w-full sm:max-w-sm bg-void-card border-t sm:border ${accents[type]} border-void-hairline rounded-t-xl2 sm:rounded-xl2 p-6 pb-8 animate-[slideUp_0.2s_ease-out]`}
      >
        <div className="w-10 h-1 bg-void-hairline rounded-full mx-auto mb-5 sm:hidden" />
        <h2 className="font-display text-2xl text-ink mb-5">{titles[type]}</h2>

        {type !== "sleep" && (
          <div className="mb-4">
            <label className="block text-xs text-ink-muted mb-1.5">Waktu kejadian</label>
            <SteppedDateTimeInput
              value={eventTime}
              onChange={setEventTime}
              max={toLocalInputValue(new Date())}
              className="mb-2"
            />
            <div className="flex gap-2 flex-wrap">
              {[
                ["Baru saja", 0],
                ["-15 mnt", 15],
                ["-30 mnt", 30],
                ["-1 jam", 60],
                ["-2 jam", 120],
              ].map(([label, minutesAgo]) => (
                <button
                  type="button"
                  key={label}
                  onClick={() => {
                    const t = new Date();
                    t.setMinutes(t.getMinutes() - minutesAgo);
                    setEventTime(toLocalInputValue(t));
                  }}
                  className="px-2.5 py-1 rounded-full border border-void-hairline text-[11px] text-ink-muted"
                >
                  {label}
                </button>
              ))}
            </div>
          </div>
        )}

        {type === "feeding" && (
          <div className="space-y-4">
            <div className="grid grid-cols-2 gap-2">
              {[
                ["asi_langsung", "ASI Langsung"],
                ["asi_perah", "ASI Perah"],
                ["sufor", "Sufor"],
                ["mpasi", "MPASI"],
              ].map(([val, label]) => (
                <button
                  type="button"
                  key={val}
                  onClick={() => setFeedType(val)}
                  className={`py-2.5 rounded-lg text-sm font-medium border transition-colors ${
                    feedType === val
                      ? "bg-feed/20 border-feed text-feed"
                      : "border-void-hairline text-ink-muted"
                  }`}
                >
                  {label}
                </button>
              ))}
            </div>

            {feedType === "asi_langsung" ? (
              <>
                <label className="block text-xs text-ink-muted mb-1.5">Sisi payudara</label>
                <div className="grid grid-cols-3 gap-2 mb-4">
                  {["kiri", "kanan", "kedua"].map((s) => (
                    <button
                      type="button"
                      key={s}
                      onClick={() => setBreastSide(s)}
                      className={`py-2 rounded-lg text-sm capitalize border ${
                        breastSide === s ? "bg-feed/20 border-feed text-feed" : "border-void-hairline text-ink-muted"
                      }`}
                    >
                      {s}
                    </button>
                  ))}
                </div>
                <label className="block text-xs text-ink-muted mb-1.5">Durasi (menit)</label>
                <input
                  type="number"
                  value={durationMinutes}
                  onChange={(e) => setDurationMinutes(e.target.value)}
                  className="w-full bg-void border border-void-hairline rounded-lg px-3 py-2.5 text-ink font-mono"
                  min="1"
                />
              </>
            ) : (
              <>
                <label className="block text-xs text-ink-muted mb-1.5">Volume (ml)</label>
                <input
                  type="number"
                  value={volumeMl}
                  onChange={(e) => setVolumeMl(e.target.value)}
                  className="w-full bg-void border border-void-hairline rounded-lg px-3 py-2.5 text-ink font-mono"
                  min="1"
                />
              </>
            )}
          </div>
        )}

        {type === "sleep" && (
          <div className="space-y-4">
            <div className="grid grid-cols-2 gap-2">
              {["siang", "malam"].map((s) => (
                <button
                  type="button"
                  key={s}
                  onClick={() => setSleepType(s)}
                  className={`py-2.5 rounded-lg text-sm capitalize border ${
                    sleepType === s ? "bg-sleep/20 border-sleep text-sleep" : "border-void-hairline text-ink-muted"
                  }`}
                >
                  Tidur {s}
                </button>
              ))}
            </div>
            <label className="block text-xs text-ink-muted mb-1.5">Mulai tidur</label>
            <SteppedDateTimeInput
              value={startTime}
              onChange={setStartTime}
              max={toLocalInputValue(new Date())}
              className="mb-2"
            />
            <label className="block text-xs text-ink-muted mb-1.5">
              Selesai tidur <span className="text-ink-faint">(kosongkan jika masih tidur)</span>
            </label>
            <SteppedDateTimeInput value={endTime} onChange={setEndTime} max={toLocalInputValue(new Date())} />
          </div>
        )}

        {type === "diaper" && (
          <div className="space-y-4">
            <div className="grid grid-cols-3 gap-2">
              {[
                ["pipis", "Pipis"],
                ["pup", "Pup"],
                ["keduanya", "Keduanya"],
              ].map(([val, label]) => (
                <button
                  type="button"
                  key={val}
                  onClick={() => setDiaperType(val)}
                  className={`py-2.5 rounded-lg text-sm border ${
                    diaperType === val ? "bg-diaper/20 border-diaper text-diaper" : "border-void-hairline text-ink-muted"
                  }`}
                >
                  {label}
                </button>
              ))}
            </div>
            {diaperType !== "pipis" && (
              <>
                <label className="block text-xs text-ink-muted mb-1.5">Konsistensi</label>
                <select
                  value={consistency}
                  onChange={(e) => setConsistency(e.target.value)}
                  className="w-full bg-void border border-void-hairline rounded-lg px-3 py-2.5 text-ink text-sm"
                >
                  <option value="normal">Normal</option>
                  <option value="keras">Keras</option>
                  <option value="cair">Cair</option>
                  <option value="berlendir">Berlendir</option>
                  <option value="berdarah">Berdarah (segera ke dokter)</option>
                </select>
              </>
            )}
          </div>
        )}

        {type === "pumping" && (
          <div className="space-y-4">
            <label className="block text-xs text-ink-muted mb-1.5">Sisi payudara</label>
            <div className="grid grid-cols-3 gap-2 mb-2">
              {["kiri", "kanan", "kedua"].map((s) => (
                <button
                  type="button"
                  key={s}
                  onClick={() => setPumpSide(s)}
                  className={`py-2 rounded-lg text-sm capitalize border ${
                    pumpSide === s ? "bg-feed/20 border-feed text-feed" : "border-void-hairline text-ink-muted"
                  }`}
                >
                  {s}
                </button>
              ))}
            </div>
            <label className="block text-xs text-ink-muted mb-1.5">Durasi (menit)</label>
            <input
              type="number"
              value={pumpDuration}
              onChange={(e) => setPumpDuration(e.target.value)}
              className="w-full bg-void border border-void-hairline rounded-lg px-3 py-2.5 text-ink font-mono"
              min="1"
            />
            <label className="block text-xs text-ink-muted mb-1.5">Volume hasil perah (ml)</label>
            <input
              type="number"
              value={pumpVolume}
              onChange={(e) => setPumpVolume(e.target.value)}
              className="w-full bg-void border border-void-hairline rounded-lg px-3 py-2.5 text-ink font-mono"
              min="0"
            />
          </div>
        )}

        {(type === "stroll" || type === "bathing") && (
          <div className="space-y-4">
            <label className="block text-xs text-ink-muted mb-1.5">Durasi (menit)</label>
            <input
              type="number"
              value={activityDuration}
              onChange={(e) => setActivityDuration(e.target.value)}
              className="w-full bg-void border border-void-hairline rounded-lg px-3 py-2.5 text-ink font-mono"
              min="1"
            />
            <label className="block text-xs text-ink-muted mb-1.5">
              Catatan <span className="text-ink-faint">(opsional)</span>
            </label>
            <input
              type="text"
              value={activityNotes}
              onChange={(e) => setActivityNotes(e.target.value)}
              placeholder={type === "stroll" ? "cth. Jalan sore di komplek" : "cth. Mandi air hangat"}
              className="w-full bg-void border border-void-hairline rounded-lg px-3 py-2.5 text-ink placeholder:text-ink-faint text-sm"
            />
          </div>
        )}

        {type === "vitamin" && (
          <p className="text-sm text-ink-muted -mt-2 mb-2">Catat pemberian Vitamin D hari ini.</p>
        )}

        <div className="flex gap-3 mt-6">
          <button
            type="button"
            onClick={onClose}
            className="flex-1 py-3 rounded-lg border border-void-hairline text-ink-muted text-sm font-medium"
          >
            Batal
          </button>
          <button
            type="submit"
            disabled={submitting}
            className="flex-1 py-3 rounded-lg bg-ink text-void text-sm font-semibold disabled:opacity-50"
          >
            {submitting ? "Menyimpan..." : isEdit ? "Simpan Perubahan" : "Simpan"}
          </button>
        </div>
        {isEdit && (
          <button
            type="button"
            onClick={handleDelete}
            disabled={deleting}
            className="w-full text-center text-xs text-warn mt-3 disabled:opacity-50"
          >
            {deleting ? "Menghapus..." : "Hapus catatan ini"}
          </button>
        )}
      </form>
    </div>
  );
}