import { useEffect, useState, useCallback } from "react";
import { api } from "../api/client";
import GrowthChart from "../components/GrowthChart";
import RelatedArticles from "../components/RelatedArticles";
import { todayWIB } from "../utils/date";

const TYPES = [
  { key: "weight", label: "Berat", unit: "kg", field: "weight_kg", icon: "⚖️" },
  { key: "height", label: "Tinggi", unit: "cm", field: "height_cm", icon: "📏" },
  { key: "head_circumference", label: "Lingkar Kepala", unit: "cm", field: "head_circumference_cm", icon: "🎯" },
];

const STATUS_COLOR = {
  "Gizi baik (normal)": "text-diaper",
  Normal: "text-diaper",
  "Gizi kurang": "text-warn",
  "Pendek (stunted)": "text-warn",
  "Di bawah normal (perlu dipantau)": "text-warn",
  "Di atas normal (perlu dipantau)": "text-warn",
  "Risiko gizi lebih": "text-warn",
  Tinggi: "text-warn",
  "Gizi buruk (sangat kurang)": "text-warn",
  "Sangat pendek (severely stunted)": "text-warn",
};

function formatDate(iso) {
  return new Date(iso).toLocaleDateString("id-ID", { day: "2-digit", month: "short", year: "numeric" });
}

export default function GrowthScreen({ child }) {
  const [activeType, setActiveType] = useState("weight");
  const [measurements, setMeasurements] = useState([]);
  const [referenceCurve, setReferenceCurve] = useState([]);
  const [showForm, setShowForm] = useState(false);
  const [editingMeasurement, setEditingMeasurement] = useState(null);
  const [loading, setLoading] = useState(true);

  // form state
  const [measuredDate, setMeasuredDate] = useState(todayWIB());
  const [weight, setWeight] = useState("");
  const [height, setHeight] = useState("");
  const [headCirc, setHeadCirc] = useState("");
  const [notes, setNotes] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  const activeTypeInfo = TYPES.find((t) => t.key === activeType);

  const loadData = useCallback(async () => {
    setLoading(true);
    try {
      const [m, curve] = await Promise.all([
        api.listGrowthMeasurements(child.id),
        api.growthReferenceCurve(activeType, child.gender || "L", 24),
      ]);
      setMeasurements(m);
      setReferenceCurve(curve);
    } finally {
      setLoading(false);
    }
  }, [child.id, child.gender, activeType]);

  useEffect(() => {
    loadData();
  }, [loadData]);

  const openAddForm = () => {
    setEditingMeasurement(null);
    setMeasuredDate(todayWIB());
    setWeight("");
    setHeight("");
    setHeadCirc("");
    setNotes("");
    setError("");
    setShowForm(true);
  };

  const openEditForm = (m) => {
    setEditingMeasurement(m);
    setMeasuredDate(m.measured_date);
    setWeight(m.weight_kg ?? "");
    setHeight(m.height_cm ?? "");
    setHeadCirc(m.head_circumference_cm ?? "");
    setNotes(m.notes || "");
    setError("");
    setShowForm(true);
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError("");
    if (!weight && !height && !headCirc) {
      setError("Isi minimal salah satu ukuran.");
      return;
    }
    setSubmitting(true);
    try {
      const payload = {
        measured_date: measuredDate,
        weight_kg: weight ? Number(weight) : null,
        height_cm: height ? Number(height) : null,
        head_circumference_cm: headCirc ? Number(headCirc) : null,
        notes: notes || null,
      };
      if (editingMeasurement) {
        await api.updateGrowthMeasurement(editingMeasurement.id, payload);
      } else {
        await api.createGrowthMeasurement(child.id, payload);
      }
      setShowForm(false);
      setEditingMeasurement(null);
      await loadData();
    } catch (err) {
      setError(err.message);
    } finally {
      setSubmitting(false);
    }
  };

  const handleDelete = async (id) => {
    await api.deleteGrowthMeasurement(id);
    setShowForm(false);
    setEditingMeasurement(null);
    await loadData();
  };

  // titik untuk chart tipe yang sedang aktif
  const childPoints = measurements
    .filter((m) => m[activeTypeInfo.field] != null)
    .map((m) => ({
      age_months: (new Date(m.measured_date) - new Date(child.birth_date)) / (1000 * 60 * 60 * 24 * 30.4375),
      value: m[activeTypeInfo.field],
    }));

  const latestForType = [...measurements].reverse().find((m) => m[activeTypeInfo.field] != null);
  const latestWho = latestForType ? latestForType[`${activeType}_who`] : null;

  return (
    <div className="min-h-screen px-6 pt-8 pb-32">
      <h1 className="mb-1 text-3xl font-display text-ink">Tumbuh Kembang</h1>
      <p className="mb-6 text-sm text-ink-muted">Acuan: WHO Child Growth Standards</p>

      {/* tab jenis ukuran */}
      <div className="flex gap-2 mb-5">
        {TYPES.map((t) => (
          <button
            key={t.key}
            onClick={() => setActiveType(t.key)}
            className={`flex-1 flex flex-col items-center gap-1 py-3 rounded-xl2 border text-xs font-medium ${
              activeType === t.key
                ? "bg-feed/15 border-feed text-feed"
                : "bg-void-card border-void-hairline text-ink-muted"
            }`}
          >
            <span className="text-lg">{t.icon}</span>
            {t.label}
          </button>
        ))}
      </div>

      {/* status terbaru */}
      {latestWho && (
        <div className="p-4 mb-4 border bg-void-card border-void-hairline rounded-xl2 shadow-soft">
          <div className="flex items-center justify-between">
            <div>
              <p className="mb-1 text-xs text-ink-faint">
                Terbaru · {formatDate(latestForType.measured_date)}
              </p>
              <p className="text-2xl font-display text-ink">
                {latestForType[activeTypeInfo.field]} <span className="text-sm text-ink-muted">{activeTypeInfo.unit}</span>
              </p>
            </div>
            <div className="text-right">
              <p className={`text-sm font-semibold ${STATUS_COLOR[latestWho.status] || "text-ink"}`}>
                {latestWho.status}
              </p>
              <p className="text-xs text-ink-faint">Persentil {latestWho.percentile}</p>
            </div>
          </div>
        </div>
      )}

      {/* chart */}
      {loading ? (
        <p className="py-10 text-sm text-center text-ink-faint">Memuat grafik...</p>
      ) : (
        <div className="p-4 mb-6 border bg-void-card border-void-hairline rounded-xl2 shadow-soft">
          <GrowthChart measurementType={activeType} referenceCurve={referenceCurve} childPoints={childPoints} />
          <div className="flex justify-center gap-4 mt-2">
            <span className="flex items-center gap-1.5 text-[11px] text-ink-muted">
              <span className="w-3 h-0.5 bg-feed inline-block" /> {child.name}
            </span>
            <span className="flex items-center gap-1.5 text-[11px] text-ink-muted">
              <span className="w-3 h-0.5 bg-diaper/50 inline-block" /> Batas normal WHO
            </span>
          </div>
        </div>
      )}

      {/* riwayat */}
      <h2 className="font-mono text-xs text-ink-faint tracking-[0.2em] uppercase mb-3">Riwayat Pengukuran</h2>
      {measurements.length === 0 ? (
        <p className="text-sm text-ink-faint">Belum ada pengukuran tercatat.</p>
      ) : (
        <div className="space-y-2">
          {[...measurements].reverse().map((m) => (
            <div
              key={m.id}
              onClick={() => openEditForm(m)}
              className="flex items-center justify-between px-4 py-3 border cursor-pointer bg-void-card border-void-hairline rounded-xl2 active:bg-void-raised"
            >
              <div>
                <p className="font-mono text-xs text-ink-faint">{formatDate(m.measured_date)}</p>
                <p className="text-sm text-ink mt-0.5">
                  {m.weight_kg != null && `${m.weight_kg} kg`}
                  {m.height_cm != null && ` · ${m.height_cm} cm`}
                  {m.head_circumference_cm != null && ` · LK ${m.head_circumference_cm} cm`}
                </p>
                {m.notes && <p className="text-xs text-ink-faint mt-0.5">{m.notes}</p>}
                {m.created_by_name && (
                  <p className="text-[11px] text-ink-faint mt-0.5">oleh {m.created_by_name}</p>
                )}
              </div>
              <button
                onClick={(e) => {
                  e.stopPropagation();
                  handleDelete(m.id);
                }}
                className="px-2 py-1 text-xs text-ink-faint"
                aria-label="Hapus catatan"
              >
                Hapus
              </button>
            </div>
          ))}
        </div>
      )}

      <RelatedArticles
        category="growth"
        ageMonths={(new Date() - new Date(child.birth_date)) / (1000 * 60 * 60 * 24 * 30.4375)}
      />

      {/* tombol tambah */}
      <button
        onClick={openAddForm}
        className="fixed flex items-center justify-center text-2xl text-white rounded-full bottom-6 right-6 w-14 h-14 bg-feed shadow-soft"
        aria-label="Tambah pengukuran"
      >
        +
      </button>

      {/* form tambah/edit pengukuran */}
      {showForm && (
        <div className="fixed inset-0 z-50 flex items-end sm:items-center sm:justify-center">
          <div
            className="absolute inset-0 bg-black/50"
            onClick={() => {
              setShowForm(false);
              setEditingMeasurement(null);
            }}
          />
          <form
            onSubmit={handleSubmit}
            className="relative w-full p-6 pb-8 border-t sm:max-w-sm bg-void-card sm:border border-void-hairline rounded-t-xl2 sm:rounded-xl2"
          >
            <div className="w-10 h-1 mx-auto mb-5 rounded-full bg-void-hairline sm:hidden" />
            <h2 className="mb-5 text-2xl font-display text-ink">
              {editingMeasurement ? "Edit Pengukuran" : "Catat Pengukuran"}
            </h2>

            <label className="block text-xs text-ink-muted mb-1.5">Tanggal ukur</label>
            <input
              type="date"
              value={measuredDate}
              onChange={(e) => setMeasuredDate(e.target.value)}
              max={todayWIB()}
              className="w-full bg-void border border-void-hairline rounded-lg px-3 py-2.5 text-ink mb-3"
              required
            />

            <label className="block text-xs text-ink-muted mb-1.5">Berat (kg)</label>
            <input
              type="number"
              step="0.01"
              placeholder="cth. 7.9"
              value={weight}
              onChange={(e) => setWeight(e.target.value)}
              className="w-full bg-void border border-void-hairline rounded-lg px-3 py-2.5 text-ink placeholder:text-ink-faint mb-3"
            />

            <label className="block text-xs text-ink-muted mb-1.5">Tinggi/Panjang (cm)</label>
            <input
              type="number"
              step="0.1"
              placeholder="cth. 65"
              value={height}
              onChange={(e) => setHeight(e.target.value)}
              className="w-full bg-void border border-void-hairline rounded-lg px-3 py-2.5 text-ink placeholder:text-ink-faint mb-3"
            />

            <label className="block text-xs text-ink-muted mb-1.5">Lingkar Kepala (cm)</label>
            <input
              type="number"
              step="0.1"
              placeholder="cth. 43"
              value={headCirc}
              onChange={(e) => setHeadCirc(e.target.value)}
              className="w-full bg-void border border-void-hairline rounded-lg px-3 py-2.5 text-ink placeholder:text-ink-faint mb-3"
            />

            <label className="block text-xs text-ink-muted mb-1.5">
              Catatan <span className="text-ink-faint">(opsional)</span>
            </label>
            <input
              type="text"
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              placeholder="cth. Posyandu bulanan"
              className="w-full bg-void border border-void-hairline rounded-lg px-3 py-2.5 text-ink placeholder:text-ink-faint mb-4 text-sm"
            />

            {error && <p className="mb-3 text-sm text-warn">{error}</p>}

            <div className="flex gap-3">
              <button
                type="button"
                onClick={() => {
                  setShowForm(false);
                  setEditingMeasurement(null);
                }}
                className="flex-1 py-3 text-sm font-medium border rounded-lg border-void-hairline text-ink-muted"
              >
                Batal
              </button>
              <button
                type="submit"
                disabled={submitting}
                className="flex-1 py-3 text-sm font-semibold text-white rounded-lg bg-feed disabled:opacity-50"
              >
                {submitting ? "Menyimpan..." : editingMeasurement ? "Simpan Perubahan" : "Simpan"}
              </button>
            </div>
            {editingMeasurement && (
              <button
                type="button"
                onClick={() => handleDelete(editingMeasurement.id)}
                className="w-full mt-3 text-xs text-center text-warn"
              >
                Hapus catatan ini
              </button>
            )}
          </form>
        </div>
      )}
    </div>
  );
}