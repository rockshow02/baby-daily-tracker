import { useEffect, useState, useCallback } from "react";
import { api } from "../api/client";
import RelatedArticles from "../components/RelatedArticles";
import { todayWIB } from "../utils/date";

const MOODS = [
  { key: "ceria", label: "Ceria", icon: "😄" },
  { key: "baik", label: "Baik", icon: "🙂" },
  { key: "sedih", label: "Sedih", icon: "😢" },
  { key: "menangis", label: "Menangis", icon: "😭" },
];

const MILESTONE_TYPES = [
  { key: "bisa_duduk", label: "Bisa Duduk", icon: "🧎" },
  { key: "langkah_pertama", label: "Langkah Pertama", icon: "👣" },
  { key: "kata_pertama", label: "Kata Pertama", icon: "💬" },
  { key: "gigi_pertama", label: "Gigi Pertama", icon: "🦷" },
  { key: "custom", label: "Lainnya", icon: "✨" },
];

const EVAL_COLOR = {
  "Lebih awal dari umumnya": "text-sleep",
  "Sesuai rentang umumnya": "text-diaper",
  "Sedikit lebih lambat dari umumnya (masih wajar)": "text-feed",
  "Terlambat dari umumnya — baiknya diskusikan ke dokter anak": "text-warn",
};

function fmtDate(iso) {
  return new Date(iso).toLocaleDateString("id-ID", { day: "2-digit", month: "short", year: "numeric" });
}
function fmtDateTime(iso) {
  return new Date(iso).toLocaleString("id-ID", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" });
}

export default function MomentsScreen({ child }) {
  const [activeTab, setActiveTab] = useState("mood");
  const [moods, setMoods] = useState([]);
  const [milestones, setMilestones] = useState([]);
  const [loading, setLoading] = useState(true);
  const [showMilestoneForm, setShowMilestoneForm] = useState(false);
  const [editingMilestone, setEditingMilestone] = useState(null);
  const [editingMood, setEditingMood] = useState(null);

  const loadAll = useCallback(async () => {
    setLoading(true);
    try {
      const [m, ms] = await Promise.all([api.listMood(child.id), api.listMilestone(child.id)]);
      setMoods(m);
      setMilestones(ms);
    } finally {
      setLoading(false);
    }
  }, [child.id]);

  useEffect(() => {
    loadAll();
  }, [loadAll]);

  const quickAddMood = async (mood) => {
    await api.createMood(child.id, { mood });
    await loadAll();
  };

  const openAddMilestone = () => {
    setEditingMilestone(null);
    setShowMilestoneForm(true);
  };

  const openEditMilestone = (ms) => {
    setEditingMilestone(ms);
    setShowMilestoneForm(true);
  };

  return (
    <div className="min-h-screen pb-32 px-6 pt-8">
      <h1 className="font-display text-3xl text-ink mb-1">Momen</h1>
      <p className="text-sm text-ink-muted mb-6">Suasana hati dan pencapaian penting</p>

      <div className="flex gap-2 mb-5">
        <button
          onClick={() => setActiveTab("mood")}
          className={`flex-1 py-3 rounded-xl2 border text-xs font-medium ${
            activeTab === "mood" ? "bg-feed/15 border-feed text-feed" : "bg-void-card border-void-hairline text-ink-muted"
          }`}
        >
          😄 Mood
        </button>
        <button
          onClick={() => setActiveTab("milestone")}
          className={`flex-1 py-3 rounded-xl2 border text-xs font-medium ${
            activeTab === "milestone" ? "bg-feed/15 border-feed text-feed" : "bg-void-card border-void-hairline text-ink-muted"
          }`}
        >
          👣 Momen Penting
        </button>
      </div>

      {loading ? (
        <p className="text-ink-faint text-sm text-center py-10">Memuat...</p>
      ) : activeTab === "mood" ? (
        <>
          {/* quick add mood buttons */}
          <div className="grid grid-cols-4 gap-2 mb-6">
            {MOODS.map((m) => (
              <button
                key={m.key}
                onClick={() => quickAddMood(m.key)}
                className="flex flex-col items-center gap-1.5 bg-void-card border border-void-hairline rounded-xl2 py-4"
              >
                <span className="text-2xl">{m.icon}</span>
                <span className="text-[11px] text-ink-muted">{m.label}</span>
              </button>
            ))}
          </div>

          <h2 className="font-mono text-xs text-ink-faint tracking-[0.2em] uppercase mb-3">Riwayat</h2>
          {moods.length === 0 ? (
            <p className="text-ink-faint text-sm">Belum ada catatan mood.</p>
          ) : (
            <div className="space-y-2">
              {moods.map((m) => {
                const info = MOODS.find((x) => x.key === m.mood);
                return (
                  <div
                    key={m.id}
                    onClick={() => setEditingMood(m)}
                    className="flex items-center justify-between bg-void-card border border-void-hairline rounded-xl2 px-4 py-3 cursor-pointer active:bg-void-raised"
                  >
                    <div className="flex items-center gap-3">
                      <span className="text-xl">{info?.icon}</span>
                      <div>
                        <p className="text-sm text-ink">{info?.label}</p>
                        <p className="text-xs text-ink-faint font-mono">{fmtDateTime(m.timestamp)}</p>
                        {m.created_by_name && (
                          <p className="text-[11px] text-ink-faint mt-0.5">oleh {m.created_by_name}</p>
                        )}
                      </div>
                    </div>
                    <button
                      onClick={async (e) => {
                        e.stopPropagation();
                        await api.deleteMood(m.id);
                        await loadAll();
                      }}
                      className="text-ink-faint text-xs"
                    >
                      Hapus
                    </button>
                  </div>
                );
              })}
            </div>
          )}
        </>
      ) : (
        <>
          {milestones.length === 0 ? (
            <p className="text-ink-faint text-sm">Belum ada momen penting tercatat.</p>
          ) : (
            <div className="space-y-2">
              {milestones.map((ms) => {
                const info = MILESTONE_TYPES.find((x) => x.key === ms.milestone_type);
                return (
                  <div key={ms.id} className="bg-void-card border border-void-hairline rounded-xl2 px-4 py-3">
                    <div
                      onClick={() => openEditMilestone(ms)}
                      className="flex items-center justify-between cursor-pointer active:opacity-70"
                    >
                      <div className="flex items-center gap-2">
                        <span className="text-lg">{info?.icon}</span>
                        <p className="text-sm text-ink font-medium">
                          {ms.milestone_type === "custom" ? ms.custom_label : info?.label}
                        </p>
                      </div>
                      <button
                        onClick={async (e) => {
                          e.stopPropagation();
                          await api.deleteMilestone(ms.id);
                          await loadAll();
                        }}
                        className="text-ink-faint text-xs"
                      >
                        Hapus
                      </button>
                    </div>
                    <p className="text-xs text-ink-faint font-mono mt-1">
                      {fmtDate(ms.achieved_date)} · usia {ms.age_months} bulan
                    </p>
                    {ms.evaluation && (
                      <p className={`text-xs font-medium mt-1 ${EVAL_COLOR[ms.evaluation.status] || "text-ink"}`}>
                        {ms.evaluation.status} <span className="text-ink-faint">(umumnya {ms.evaluation.typical_range})</span>
                      </p>
                    )}
                    {ms.notes && <p className="text-xs text-ink-muted mt-1">{ms.notes}</p>}
                    {ms.created_by_name && (
                      <p className="text-[11px] text-ink-faint mt-1">oleh {ms.created_by_name}</p>
                    )}
                  </div>
                );
              })}
            </div>
          )}
        </>
      )}

      <RelatedArticles
        category={activeTab === "milestone" ? "milestone" : "mood"}
        ageMonths={(new Date() - new Date(child.birth_date)) / (1000 * 60 * 60 * 24 * 30.4375)}
      />

      {activeTab === "milestone" && (
        <RelatedArticles
          category="motor_activity"
          title="🤸 Ide Aktivitas Sesuai Usia"
          ageMonths={(new Date() - new Date(child.birth_date)) / (1000 * 60 * 60 * 24 * 30.4375)}
        />
      )}

      {activeTab === "milestone" && (
        <button
          onClick={openAddMilestone}
          className="fixed bottom-6 right-6 w-14 h-14 rounded-full bg-feed text-white text-2xl shadow-soft flex items-center justify-center"
          aria-label="Tambah momen penting"
        >
          +
        </button>
      )}

      {showMilestoneForm && (
        <MilestoneForm
          childId={child.id}
          editingLog={editingMilestone}
          onClose={() => {
            setShowMilestoneForm(false);
            setEditingMilestone(null);
          }}
          onSaved={loadAll}
        />
      )}

      {editingMood && (
        <MoodEditSheet
          mood={editingMood}
          onClose={() => setEditingMood(null)}
          onSaved={loadAll}
        />
      )}
    </div>
  );
}

function MoodEditSheet({ mood, onClose, onSaved }) {
  const [submitting, setSubmitting] = useState(false);
  const [deleting, setDeleting] = useState(false);

  const handleChange = async (newMood) => {
    setSubmitting(true);
    try {
      await api.updateMood(mood.id, { mood: newMood });
      await onSaved();
      onClose();
    } finally {
      setSubmitting(false);
    }
  };

  const handleDelete = async () => {
    setDeleting(true);
    try {
      await api.deleteMood(mood.id);
      await onSaved();
      onClose();
    } finally {
      setDeleting(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-end sm:items-center sm:justify-center">
      <div className="absolute inset-0 bg-black/50" onClick={onClose} />
      <div className="relative w-full sm:max-w-sm bg-void-card border-t sm:border border-void-hairline rounded-t-xl2 sm:rounded-xl2 p-6 pb-8">
        <div className="w-10 h-1 bg-void-hairline rounded-full mx-auto mb-5 sm:hidden" />
        <h2 className="font-display text-2xl text-ink mb-5">Ubah Mood</h2>
        <div className="grid grid-cols-4 gap-2 mb-4">
          {MOODS.map((m) => (
            <button
              key={m.key}
              disabled={submitting}
              onClick={() => handleChange(m.key)}
              className={`flex flex-col items-center gap-1.5 rounded-xl2 py-4 border ${
                mood.mood === m.key ? "bg-feed/15 border-feed" : "bg-void border-void-hairline"
              } disabled:opacity-50`}
            >
              <span className="text-2xl">{m.icon}</span>
              <span className="text-[11px] text-ink-muted">{m.label}</span>
            </button>
          ))}
        </div>
        <button
          onClick={onClose}
          className="w-full py-3 rounded-lg border border-void-hairline text-ink-muted text-sm font-medium mb-3"
        >
          Batal
        </button>
        <button
          onClick={handleDelete}
          disabled={deleting}
          className="w-full text-center text-xs text-warn disabled:opacity-50"
        >
          {deleting ? "Menghapus..." : "Hapus catatan ini"}
        </button>
      </div>
    </div>
  );
}

function MilestoneForm({ childId, editingLog, onClose, onSaved }) {
  const isEdit = !!editingLog;
  const [milestoneType, setMilestoneType] = useState(editingLog?.milestone_type || "bisa_duduk");
  const [customLabel, setCustomLabel] = useState(editingLog?.custom_label || "");
  const [achievedDate, setAchievedDate] = useState(editingLog?.achieved_date || todayWIB());
  const [notes, setNotes] = useState(editingLog?.notes || "");
  const [submitting, setSubmitting] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [error, setError] = useState("");

  const handleDelete = async () => {
    setDeleting(true);
    try {
      await api.deleteMilestone(editingLog.id);
      await onSaved();
      onClose();
    } finally {
      setDeleting(false);
    }
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError("");
    setSubmitting(true);
    try {
      const payload = {
        milestone_type: milestoneType,
        custom_label: milestoneType === "custom" ? customLabel : null,
        achieved_date: achievedDate,
        notes: notes || null,
      };
      if (isEdit) {
        await api.updateMilestone(editingLog.id, payload);
      } else {
        await api.createMilestone(childId, payload);
      }
      await onSaved();
      onClose();
    } catch (err) {
      setError(err.message);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-end sm:items-center sm:justify-center">
      <div className="absolute inset-0 bg-black/50" onClick={onClose} />
      <form
        onSubmit={handleSubmit}
        className="relative w-full sm:max-w-sm bg-void-card border-t sm:border border-void-hairline rounded-t-xl2 sm:rounded-xl2 p-6 pb-8"
      >
        <div className="w-10 h-1 bg-void-hairline rounded-full mx-auto mb-5 sm:hidden" />
        <h2 className="font-display text-2xl text-ink mb-5">{isEdit ? "Edit Momen Penting" : "Catat Momen Penting"}</h2>

        <div className="grid grid-cols-3 gap-2 mb-3">
          {MILESTONE_TYPES.map((t) => (
            <button
              type="button"
              key={t.key}
              onClick={() => setMilestoneType(t.key)}
              className={`flex flex-col items-center gap-1 py-3 rounded-lg border text-[11px] ${
                milestoneType === t.key ? "bg-feed/20 border-feed text-feed" : "border-void-hairline text-ink-muted"
              }`}
            >
              <span className="text-lg">{t.icon}</span>
              {t.label}
            </button>
          ))}
        </div>

        {milestoneType === "custom" && (
          <>
            <label className="block text-xs text-ink-muted mb-1.5">Nama momen</label>
            <input
              type="text"
              value={customLabel}
              onChange={(e) => setCustomLabel(e.target.value)}
              placeholder="cth. Pertama kali tepuk tangan"
              required
              className="w-full bg-void border border-void-hairline rounded-lg px-3 py-2.5 text-ink placeholder:text-ink-faint mb-3"
            />
          </>
        )}

        <label className="block text-xs text-ink-muted mb-1.5">Tanggal</label>
        <input
          type="date"
          value={achievedDate}
          onChange={(e) => setAchievedDate(e.target.value)}
          max={todayWIB()}
          className="w-full bg-void border border-void-hairline rounded-lg px-3 py-2.5 text-ink mb-3"
          required
        />

        <label className="block text-xs text-ink-muted mb-1.5">
          Catatan <span className="text-ink-faint">(opsional)</span>
        </label>
        <input
          type="text"
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
          className="w-full bg-void border border-void-hairline rounded-lg px-3 py-2.5 text-ink placeholder:text-ink-faint mb-4 text-sm"
        />

        {error && <p className="text-warn text-sm mb-3">{error}</p>}

        <div className="flex gap-3">
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
            className="flex-1 py-3 rounded-lg bg-feed text-white text-sm font-semibold disabled:opacity-50"
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