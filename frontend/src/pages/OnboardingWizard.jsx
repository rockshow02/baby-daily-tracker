import { useEffect, useState } from "react";
import { api } from "../api/client";
import { todayWIB } from "../utils/date";

const STEPS = ["Data Anak", "Berat & Tinggi", "Vaksinasi", "Foto"];

export default function OnboardingWizard({ onComplete }) {
  const [step, setStep] = useState(0);
  const [child, setChild] = useState(null);
  const [error, setError] = useState("");
  const [showImport, setShowImport] = useState(false);
  const [importFile, setImportFile] = useState(null);
  const [importing, setImporting] = useState(false);
  const [importError, setImportError] = useState("");
  const [showJoin, setShowJoin] = useState(false);
  const [joinCode, setJoinCode] = useState("");
  const [joining, setJoining] = useState(false);
  const [joinError, setJoinError] = useState("");

  // step 1 — data dasar
  const [name, setName] = useState("");
  const [nickname, setNickname] = useState("");
  const [birthDate, setBirthDate] = useState("");
  const [gender, setGender] = useState("L");

  // step 2 — berat/tinggi
  const [weight, setWeight] = useState("");
  const [height, setHeight] = useState("");

  // step 3 — vaksinasi
  const [vaccines, setVaccines] = useState([]);
  const [loadingVaccines, setLoadingVaccines] = useState(false);

  // step 4 — foto
  const [photoFile, setPhotoFile] = useState(null);
  const [photoPreview, setPhotoPreview] = useState(null);

  const [submitting, setSubmitting] = useState(false);

  const handleImport = async () => {
    if (!importFile) {
      setImportError("Pilih file backup (.json) dulu.");
      return;
    }
    setImportError("");
    setImporting(true);
    try {
      const text = await importFile.text();
      const data = JSON.parse(text);
      const result = await api.importJson(data);
      onComplete(result.child);
    } catch (err) {
      if (err instanceof SyntaxError) {
        setImportError("File bukan format JSON backup yang valid.");
      } else {
        setImportError(err.message);
      }
    } finally {
      setImporting(false);
    }
  };

  const handleJoin = async () => {
    if (!joinCode.trim()) {
      setJoinError("Masukkan kode undangan dulu.");
      return;
    }
    setJoinError("");
    setJoining(true);
    try {
      const result = await api.joinChild(joinCode.trim());
      onComplete(result.child);
    } catch (err) {
      setJoinError(err.message);
    } finally {
      setJoining(false);
    }
  };

  // ---------- STEP 1: buat anak ----------
  const handleStep1 = async (e) => {
    e.preventDefault();
    setError("");
    setSubmitting(true);
    try {
      const created = await api.createChild({ name, nickname: nickname || null, birth_date: birthDate, gender });
      setChild(created);
      setStep(1);
    } catch (err) {
      setError(err.message);
    } finally {
      setSubmitting(false);
    }
  };

  // ---------- STEP 2: berat/tinggi (opsional) ----------
  const handleStep2 = async (e) => {
    e.preventDefault();
    setError("");
    setSubmitting(true);
    try {
      if (weight || height) {
        const payload = {};
        if (weight) payload.birth_weight_kg = Number(weight);
        if (height) payload.birth_height_cm = Number(height);
        const updated = await api.updateChild(child.id, payload);
        setChild(updated);
      }
      setStep(2);
    } catch (err) {
      setError(err.message);
    } finally {
      setSubmitting(false);
    }
  };

  // ---------- STEP 3: load & centang vaksin ----------
  useEffect(() => {
    if (step !== 2 || !child) return;
    setLoadingVaccines(true);
    api
      .listChildVaccinations(child.id)
      .then((res) => setVaccines(res.vaccinations))
      .finally(() => setLoadingVaccines(false));
  }, [step, child]);

  const toggleVaccine = (vaccineScheduleId) => {
    setVaccines((prev) =>
      prev.map((v) =>
        v.vaccine_schedule_id === vaccineScheduleId ? { ...v, given: !v.given } : v
      )
    );
  };

  const handleStep3 = async (e) => {
    e.preventDefault();
    setError("");
    setSubmitting(true);
    try {
      const items = vaccines
        .filter((v) => v.given)
        .map((v) => ({ vaccine_schedule_id: v.vaccine_schedule_id, given: true }));
      if (items.length > 0) {
        await api.updateChildVaccinations(child.id, items);
      }
      setStep(3);
    } catch (err) {
      setError(err.message);
    } finally {
      setSubmitting(false);
    }
  };

  // ---------- STEP 4: upload foto (opsional) ----------
  const handlePhotoChange = (e) => {
    const file = e.target.files[0];
    if (!file) return;
    setPhotoFile(file);
    setPhotoPreview(URL.createObjectURL(file));
  };

  const handleFinish = async () => {
    setError("");
    setSubmitting(true);
    try {
      let finalChild = child;
      if (photoFile) {
        finalChild = await api.uploadChildPhoto(child.id, photoFile);
      }
      onComplete(finalChild);
    } catch (err) {
      setError(err.message);
    } finally {
      setSubmitting(false);
    }
  };

  const dueVaccines = vaccines.filter((v) => v.due);
  const notYetDueVaccines = vaccines.filter((v) => !v.due);

  return (
    <div className="flex flex-col items-center justify-center min-h-screen px-6 py-10">
      <div className="w-full max-w-sm">
        {/* progress dots */}
        <div className="flex items-center justify-center gap-2 mb-8">
          {STEPS.map((label, i) => (
            <div key={label} className="flex items-center gap-2">
              <div
                className={`w-2 h-2 rounded-full transition-colors ${
                  i === step ? "bg-feed w-6" : i < step ? "bg-feed/50" : "bg-void-hairline"
                }`}
              />
            </div>
          ))}
        </div>

        <p className="text-center font-mono text-xs text-ink-faint tracking-[0.2em] uppercase mb-2">
          Langkah {step + 1} dari {STEPS.length}
        </p>
        <h1 className="mb-8 text-3xl text-center font-display text-ink">{STEPS[step]}</h1>

        {error && <p className="mb-4 text-sm text-center text-warn">{error}</p>}

        {/* STEP 1 */}
        {step === 0 && (
          <form onSubmit={handleStep1} className="space-y-3">
            <input
              type="text"
              placeholder="Nama anak"
              value={name}
              onChange={(e) => setName(e.target.value)}
              className="w-full px-4 py-3 border rounded-lg bg-void-card border-void-hairline text-ink placeholder:text-ink-faint"
              required
            />
            <div>
              <input
                type="text"
                placeholder="Nama panggilan (opsional)"
                value={nickname}
                onChange={(e) => setNickname(e.target.value)}
                maxLength={30}
                className="w-full px-4 py-3 border rounded-lg bg-void-card border-void-hairline text-ink placeholder:text-ink-faint"
              />
              <p className="text-[11px] text-ink-faint mt-1 ml-1">
                Buat nama panjang, ini yang ditampilkan di Dashboard biar ringkas
              </p>
            </div>
            <div>
              <label className="block text-xs text-ink-muted mb-1.5 ml-1">Tanggal lahir</label>
              <input
                type="date"
                value={birthDate}
                onChange={(e) => setBirthDate(e.target.value)}
                min={new Date(new Date().setFullYear(new Date().getFullYear() - 6)).toISOString().split("T")[0]}
                max={todayWIB()}
                className="w-full px-4 py-3 border rounded-lg bg-void-card border-void-hairline text-ink"
                required
              />
              <p className="text-[11px] text-ink-faint mt-1 ml-1">Aplikasi ini untuk anak usia 0-5 tahun</p>
            </div>
            <div className="grid grid-cols-2 gap-2">
              {[["L", "Laki-laki"], ["P", "Perempuan"]].map(([val, label]) => (
                <button
                  type="button"
                  key={val}
                  onClick={() => setGender(val)}
                  className={`py-3 rounded-lg text-sm border ${
                    gender === val ? "bg-feed/20 border-feed text-feed" : "border-void-hairline text-ink-muted"
                  }`}
                >
                  {label}
                </button>
              ))}
            </div>
            <button
              type="submit"
              disabled={submitting}
              className="w-full py-3.5 rounded-lg bg-feed text-white font-semibold mt-2 disabled:opacity-50"
            >
              {submitting ? "Menyimpan..." : "Lanjut"}
            </button>
          </form>
        )}

        {step === 0 && !showImport && !showJoin && (
          <button
            onClick={() => setShowImport(true)}
            className="w-full mt-4 text-xs text-center text-ink-faint"
          >
            Sudah punya data dari device lain? Import backup di sini
          </button>
        )}

        {step === 0 && showImport && (
          <div className="pt-4 mt-4 border-t border-void-hairline">
            <p className="mb-3 text-sm text-ink-muted">
              Pilih file backup (.json) yang sebelumnya di-export dari device lama, di menu "Backup data (JSON)" pada halaman utama.
            </p>
            <input
              type="file"
              accept="application/json"
              onChange={(e) => setImportFile(e.target.files[0])}
              className="w-full px-4 py-3 mb-3 text-sm border rounded-lg bg-void-card border-void-hairline text-ink"
            />
            {importError && <p className="mb-3 text-sm text-warn">{importError}</p>}
            <div className="flex gap-3">
              <button
                onClick={() => setShowImport(false)}
                className="flex-1 py-3 text-sm font-medium border rounded-lg border-void-hairline text-ink-muted"
              >
                Batal
              </button>
              <button
                onClick={handleImport}
                disabled={importing}
                className="flex-1 py-3 text-sm font-semibold text-white rounded-lg bg-feed disabled:opacity-50"
              >
                {importing ? "Mengimpor..." : "Import"}
              </button>
            </div>
          </div>
        )}

        {step === 0 && !showImport && !showJoin && (
          <button
            onClick={() => setShowJoin(true)}
            className="w-full mt-3 text-xs text-center text-ink-faint"
          >
            Sudah diundang orang lain? Masukkan kode undangan
          </button>
        )}

        {step === 0 && showJoin && (
          <div className="pt-4 mt-4 border-t border-void-hairline">
            <p className="mb-3 text-sm text-ink-muted">
              Masukkan kode undangan dari pasangan/pengasuh yang sudah pakai app ini duluan,
              biar kamu bisa akses data anak yang sama.
            </p>
            <input
              type="text"
              value={joinCode}
              onChange={(e) => setJoinCode(e.target.value.toUpperCase())}
              placeholder="cth. A1B2C3D4"
              className="w-full px-4 py-3 mb-3 font-mono text-sm tracking-widest uppercase border rounded-lg bg-void-card border-void-hairline text-ink placeholder:text-ink-faint"
            />
            {joinError && <p className="mb-3 text-sm text-warn">{joinError}</p>}
            <div className="flex gap-3">
              <button
                onClick={() => setShowJoin(false)}
                className="flex-1 py-3 text-sm font-medium border rounded-lg border-void-hairline text-ink-muted"
              >
                Batal
              </button>
              <button
                onClick={handleJoin}
                disabled={joining}
                className="flex-1 py-3 text-sm font-semibold text-white rounded-lg bg-feed disabled:opacity-50"
              >
                {joining ? "Bergabung..." : "Gabung"}
              </button>
            </div>
          </div>
        )}

        {/* STEP 2 */}
        {step === 1 && (
          <form onSubmit={handleStep2} className="space-y-3">
            <p className="mb-2 -mt-4 text-sm text-center text-ink-muted">
              Boleh dilewati kalau belum ada datanya di buku KIA.
            </p>
            <div>
              <label className="block text-xs text-ink-muted mb-1.5 ml-1">Berat lahir (kg)</label>
              <input
                type="number"
                step="0.1"
                placeholder="cth. 3.2"
                value={weight}
                onChange={(e) => setWeight(e.target.value)}
                className="w-full px-4 py-3 font-mono border rounded-lg bg-void-card border-void-hairline text-ink placeholder:text-ink-faint"
              />
            </div>
            <div>
              <label className="block text-xs text-ink-muted mb-1.5 ml-1">Tinggi lahir (cm)</label>
              <input
                type="number"
                step="0.1"
                placeholder="cth. 49.5"
                value={height}
                onChange={(e) => setHeight(e.target.value)}
                className="w-full px-4 py-3 font-mono border rounded-lg bg-void-card border-void-hairline text-ink placeholder:text-ink-faint"
              />
            </div>
            <button
              type="submit"
              disabled={submitting}
              className="w-full py-3.5 rounded-lg bg-feed text-white font-semibold mt-2 disabled:opacity-50"
            >
              {submitting ? "Menyimpan..." : "Lanjut"}
            </button>
          </form>
        )}

        {/* STEP 3 */}
        {step === 2 && (
          <form onSubmit={handleStep3} className="space-y-4">
            <p className="mb-2 -mt-4 text-sm text-center text-ink-muted">
              Centang vaksin yang <span className="text-ink">sudah pernah diberikan</span>. Acuan: Kemenkes RI.
            </p>

            {loadingVaccines ? (
              <p className="text-sm text-center text-ink-faint">Memuat jadwal...</p>
            ) : (
              <div className="max-h-80 overflow-y-auto space-y-1.5 pr-1">
                {dueVaccines.length > 0 && (
                  <p className="text-[11px] text-ink-faint font-mono uppercase tracking-wider mt-1 mb-1">
                    Sudah waktunya (sesuai usia)
                  </p>
                )}
                {dueVaccines.map((v) => (
                  <VaccineRow key={v.vaccine_schedule_id} v={v} onToggle={toggleVaccine} />
                ))}

                {notYetDueVaccines.length > 0 && (
                  <p className="text-[11px] text-ink-faint font-mono uppercase tracking-wider mt-4 mb-1">
                    Belum waktunya
                  </p>
                )}
                {notYetDueVaccines.map((v) => (
                  <VaccineRow key={v.vaccine_schedule_id} v={v} onToggle={toggleVaccine} dimmed />
                ))}
              </div>
            )}

            <button
              type="submit"
              disabled={submitting}
              className="w-full py-3.5 rounded-lg bg-feed text-white font-semibold mt-2 disabled:opacity-50"
            >
              {submitting ? "Menyimpan..." : "Lanjut"}
            </button>
          </form>
        )}

        {/* STEP 4 */}
        {step === 3 && (
          <div className="space-y-4">
            <p className="mb-2 -mt-4 text-sm text-center text-ink-muted">Opsional, bisa ditambah nanti juga.</p>

            <label className="block cursor-pointer">
              <div className="flex items-center justify-center w-32 h-32 mx-auto overflow-hidden border-2 border-dashed rounded-full border-void-hairline bg-void-card">
                {photoPreview ? (
                  <img src={photoPreview} alt="Preview" className="object-cover w-full h-full" />
                ) : (
                  <span className="text-3xl">📷</span>
                )}
              </div>
              <input type="file" accept="image/png,image/jpeg,image/webp" onChange={handlePhotoChange} className="hidden" />
              <p className="mt-3 text-xs text-center text-feed">
                {photoPreview ? "Ganti foto" : "Pilih foto"}
              </p>
            </label>

            <button
              onClick={handleFinish}
              disabled={submitting}
              className="w-full py-3.5 rounded-lg bg-feed text-white font-semibold mt-4 disabled:opacity-50"
            >
              {submitting ? "Menyimpan..." : photoFile ? "Selesai" : "Lewati & Selesai"}
            </button>
          </div>
        )}
      </div>
    </div>
  );
}

function VaccineRow({ v, onToggle, dimmed }) {
  return (
    <button
      type="button"
      onClick={() => onToggle(v.vaccine_schedule_id)}
      className={`w-full flex items-center justify-between px-4 py-3 rounded-lg border text-left transition-colors ${
        v.given
          ? "bg-diaper/15 border-diaper"
          : dimmed
          ? "border-void-hairline opacity-50"
          : "border-void-hairline"
      }`}
    >
      <div>
        <p className={`text-sm ${v.given ? "text-diaper" : "text-ink"}`}>{v.vaccine_name}</p>
        <p className="text-[11px] text-ink-faint font-mono">
          usia {v.recommended_age_months} bln{v.is_optional ? " · opsional" : ""}
        </p>
      </div>
      <div
        className={`w-5 h-5 rounded-full border flex items-center justify-center flex-shrink-0 ${
          v.given ? "bg-diaper border-diaper" : "border-void-hairline"
        }`}
      >
        {v.given && <span className="text-xs text-white">✓</span>}
      </div>
    </button>
  );
}