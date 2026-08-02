import { useEffect, useState, useCallback } from "react";
import { api } from "../api/client";
import CaregiverModal from "../components/CaregiverModal";
import { todayWIB } from "../utils/date";

function fmtDate(iso) {
  return new Date(iso).toLocaleDateString("id-ID", { day: "2-digit", month: "long", year: "numeric" });
}

function ageString(birthDate) {
  const days = Math.floor((new Date() - new Date(birthDate)) / (1000 * 60 * 60 * 24));
  if (days < 60) return `${days} hari`;
  const months = Math.floor(days / 30.44);
  if (months < 24) return `${months} bulan`;
  const years = Math.floor(months / 12);
  const remMonths = months % 12;
  return remMonths > 0 ? `${years} thn ${remMonths} bln` : `${years} tahun`;
}

export default function ChildProfileScreen({ child, currentUserId, onUpdated }) {
  const [growthLatest, setGrowthLatest] = useState(null);
  const [vaccinations, setVaccinations] = useState(null);
  const [milestoneCount, setMilestoneCount] = useState(0);
  const [caregiverCount, setCaregiverCount] = useState(0);
  const [loading, setLoading] = useState(true);
  const [showCaregivers, setShowCaregivers] = useState(false);
  const [editing, setEditing] = useState(false);

  const [name, setName] = useState(child.name);
  const [nickname, setNickname] = useState(child.nickname || "");
  const [birthDate, setBirthDate] = useState(child.birth_date);
  const [gender, setGender] = useState(child.gender || "L");
  const [weight, setWeight] = useState(child.birth_weight_kg ?? "");
  const [height, setHeight] = useState(child.birth_height_cm ?? "");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [photoFile, setPhotoFile] = useState(null);
  const [photoPreview, setPhotoPreview] = useState(null);
  const [uploadingPhoto, setUploadingPhoto] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [gl, vax, ms, cg] = await Promise.all([
        api.latestGrowthStatus(child.id),
        api.listChildVaccinations(child.id),
        api.listMilestone(child.id),
        api.listCaregivers(child.id),
      ]);
      setGrowthLatest(gl);
      setVaccinations(vax);
      setMilestoneCount(ms.length);
      setCaregiverCount(cg.length);
    } finally {
      setLoading(false);
    }
  }, [child.id]);

  useEffect(() => {
    load();
  }, [load]);

  const handleSaveInfo = async (e) => {
    e.preventDefault();
    setError("");
    setSaving(true);
    try {
      const updated = await api.updateChild(child.id, {
        name,
        nickname: nickname || null,
        birth_date: birthDate,
        gender,
        birth_weight_kg: weight === "" ? null : Number(weight),
        birth_height_cm: height === "" ? null : Number(height),
      });
      await onUpdated(updated);
      setEditing(false);
    } catch (err) {
      setError(err.message);
    } finally {
      setSaving(false);
    }
  };

  const handlePhotoChange = (e) => {
    const file = e.target.files[0];
    if (!file) return;
    setPhotoFile(file);
    setPhotoPreview(URL.createObjectURL(file));
  };

  const handlePhotoUpload = async () => {
    if (!photoFile) return;
    setUploadingPhoto(true);
    try {
      const updated = await api.uploadChildPhoto(child.id, photoFile);
      await onUpdated(updated);
      setPhotoFile(null);
      setPhotoPreview(null);
    } catch (err) {
      setError(err.message);
    } finally {
      setUploadingPhoto(false);
    }
  };

  const wajib = vaccinations?.vaccinations.filter((v) => v.category === "wajib") || [];
  const wajibGiven = wajib.filter((v) => v.given).length;
  const tambahan = vaccinations?.vaccinations.filter((v) => v.category === "tambahan") || [];
  const tambahanGiven = tambahan.filter((v) => v.given).length;

  return (
    <div className="min-h-screen px-6 pt-8 pb-16">
      <h1 className="mb-6 text-3xl font-display text-ink">Profil Anak</h1>

      <div className="flex flex-col items-center mb-6">
        <label className="cursor-pointer">
          <div className="flex items-center justify-center overflow-hidden border-2 border-dashed rounded-full w-28 h-28 border-void-hairline bg-void-card">
            {photoPreview || child.photo_filename ? (
              <img
                src={photoPreview || api.photoUrl(child.photo_filename)}
                alt={child.name}
                className="object-cover w-full h-full"
              />
            ) : (
              <span className="text-3xl">📷</span>
            )}
          </div>
          <input type="file" accept="image/png,image/jpeg,image/webp" onChange={handlePhotoChange} className="hidden" />
        </label>
        {photoFile && (
          <button
            onClick={handlePhotoUpload}
            disabled={uploadingPhoto}
            className="mt-2 text-xs font-medium text-feed disabled:opacity-50"
          >
            {uploadingPhoto ? "Mengunggah..." : "Simpan foto baru"}
          </button>
        )}
        <p className="mt-3 text-2xl font-display text-ink">{child.nickname || child.name}</p>
        {child.nickname && <p className="text-xs text-ink-faint">{child.name}</p>}
        <p className="text-sm text-ink-muted">{ageString(child.birth_date)}</p>
      </div>

      {error && <p className="mb-4 text-sm text-center text-warn">{error}</p>}

      <div className="p-4 mb-4 border bg-void-card border-void-hairline rounded-xl2 shadow-soft">
        <div className="flex items-center justify-between mb-3">
          <p className="font-mono text-xs tracking-wider uppercase text-ink-faint">Data Anak</p>
          <button onClick={() => setEditing(!editing)} className="text-xs font-medium text-feed">
            {editing ? "Batal" : "Edit"}
          </button>
        </div>

        {!editing ? (
          <div className="space-y-2 text-sm">
            <div className="flex justify-between">
              <span className="text-ink-faint">Nama lengkap</span>
              <span className="text-ink">{child.name}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-ink-faint">Nama panggilan</span>
              <span className="text-ink">{child.nickname || "-"}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-ink-faint">Tanggal lahir</span>
              <span className="text-ink">{fmtDate(child.birth_date)}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-ink-faint">Jenis kelamin</span>
              <span className="text-ink">{child.gender === "L" ? "Laki-laki" : "Perempuan"}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-ink-faint">Berat lahir</span>
              <span className="text-ink">{child.birth_weight_kg ? `${child.birth_weight_kg} kg` : "-"}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-ink-faint">Tinggi lahir</span>
              <span className="text-ink">{child.birth_height_cm ? `${child.birth_height_cm} cm` : "-"}</span>
            </div>
          </div>
        ) : (
          <form onSubmit={handleSaveInfo} className="space-y-3">
            <div>
              <label className="block mb-1 text-xs text-ink-muted">Nama lengkap</label>
              <input
                type="text"
                value={name}
                onChange={(e) => setName(e.target.value)}
                className="w-full px-3 py-2 text-sm border rounded-lg bg-void border-void-hairline text-ink"
                required
              />
            </div>
            <div>
              <label className="block mb-1 text-xs text-ink-muted">
                Nama panggilan <span className="text-ink-faint">(ditampilkan di Dashboard)</span>
              </label>
              <input
                type="text"
                value={nickname}
                onChange={(e) => setNickname(e.target.value)}
                maxLength={30}
                placeholder="cth. Lenya"
                className="w-full px-3 py-2 text-sm border rounded-lg bg-void border-void-hairline text-ink placeholder:text-ink-faint"
              />
            </div>
            <div>
              <label className="block mb-1 text-xs text-ink-muted">Tanggal lahir</label>
              <input
                type="date"
                value={birthDate}
                onChange={(e) => setBirthDate(e.target.value)}
                min={new Date(new Date().setFullYear(new Date().getFullYear() - 6)).toISOString().split("T")[0]}
                max={todayWIB()}
                className="w-full px-3 py-2 text-sm border rounded-lg bg-void border-void-hairline text-ink"
                required
              />
            </div>
            <div className="grid grid-cols-2 gap-2">
              {[["L", "Laki-laki"], ["P", "Perempuan"]].map(([val, label]) => (
                <button
                  type="button"
                  key={val}
                  onClick={() => setGender(val)}
                  className={`py-2 rounded-lg text-xs border ${
                    gender === val ? "bg-feed/20 border-feed text-feed" : "border-void-hairline text-ink-muted"
                  }`}
                >
                  {label}
                </button>
              ))}
            </div>
            <div className="grid grid-cols-2 gap-2">
              <div>
                <label className="block mb-1 text-xs text-ink-muted">Berat lahir (kg)</label>
                <input
                  type="number"
                  step="0.1"
                  value={weight}
                  onChange={(e) => setWeight(e.target.value)}
                  className="w-full px-3 py-2 text-sm border rounded-lg bg-void border-void-hairline text-ink"
                />
              </div>
              <div>
                <label className="block mb-1 text-xs text-ink-muted">Tinggi lahir (cm)</label>
                <input
                  type="number"
                  step="0.1"
                  value={height}
                  onChange={(e) => setHeight(e.target.value)}
                  className="w-full px-3 py-2 text-sm border rounded-lg bg-void border-void-hairline text-ink"
                />
              </div>
            </div>
            <button
              type="submit"
              disabled={saving}
              className="w-full py-2.5 rounded-lg bg-feed text-white text-sm font-semibold disabled:opacity-50"
            >
              {saving ? "Menyimpan..." : "Simpan Perubahan"}
            </button>
          </form>
        )}
      </div>

      {loading ? (
        <p className="py-6 text-sm text-center text-ink-faint">Memuat...</p>
      ) : (
        <div className="grid grid-cols-2 gap-3 mb-4">
          <div className="p-4 border bg-void-card border-void-hairline rounded-xl2">
            <p className="mb-1 text-xs text-ink-faint">Pertumbuhan Terbaru</p>
            {growthLatest?.latest ? (
              <>
                <p className="text-sm font-medium text-ink">
                  {growthLatest.latest.weight_kg && `${growthLatest.latest.weight_kg} kg`}
                  {growthLatest.latest.height_cm && ` / ${growthLatest.latest.height_cm} cm`}
                </p>
                {growthLatest.latest.weight_who && (
                  <p className="text-[11px] text-ink-faint mt-0.5">{growthLatest.latest.weight_who.status}</p>
                )}
              </>
            ) : (
              <p className="text-sm text-ink-faint">Belum ada data</p>
            )}
          </div>

          <div className="p-4 border bg-void-card border-void-hairline rounded-xl2">
            <p className="mb-1 text-xs text-ink-faint">Vaksinasi Wajib</p>
            <p className="text-sm font-medium text-ink">{wajibGiven} / {wajib.length}</p>
            <p className="text-[11px] text-ink-faint mt-0.5">Tambahan: {tambahanGiven} / {tambahan.length}</p>
          </div>

          <div className="p-4 border bg-void-card border-void-hairline rounded-xl2">
            <p className="mb-1 text-xs text-ink-faint">Momen Penting</p>
            <p className="text-sm font-medium text-ink">{milestoneCount} tercatat</p>
          </div>

          <button
            onClick={() => setShowCaregivers(true)}
            className="p-4 text-left border bg-void-card border-void-hairline rounded-xl2"
          >
            <p className="mb-1 text-xs text-ink-faint">Pengasuh</p>
            <p className="text-sm font-medium text-feed">{caregiverCount} orang →</p>
          </button>
        </div>
      )}

      <div className="flex items-center justify-center gap-4">
        <a href={api.exportPdfUrl(child.id)} target="_blank" rel="noreferrer" className="text-xs text-ink-muted">
          📄 Export PDF
        </a>
        <a
          href={api.exportJsonUrl(child.id)}
          target="_blank"
          rel="noreferrer"
          download={`backup-${child.name.toLowerCase()}.json`}
          className="text-xs text-ink-muted"
        >
          💾 Backup JSON
        </a>
      </div>

      {showCaregivers && (
        <CaregiverModal child={child} currentUserId={currentUserId} onClose={() => setShowCaregivers(false)} />
      )}
    </div>
  );
}