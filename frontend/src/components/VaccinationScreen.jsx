import { useEffect, useState, useCallback } from "react";
import { api } from "../api/client";
import { todayWIB } from "../utils/date";

function fmtDate(iso) {
  return new Date(iso).toLocaleDateString("id-ID", { day: "2-digit", month: "short", year: "numeric" });
}

export default function VaccinationScreen({ child }) {
  const [category, setCategory] = useState("wajib"); // 'wajib' | 'tambahan'
  const [ageMonths, setAgeMonths] = useState(0);
  const [vaccinations, setVaccinations] = useState([]);
  const [summary, setSummary] = useState(null);
  const [canUpdate, setCanUpdate] = useState(false);
  const [statusFilter, setStatusFilter] = useState("pending");
  const [disclaimer, setDisclaimer] = useState("");
  const [loading, setLoading] = useState(true);
  const [savingId, setSavingId] = useState(null);
  const [dateEditId, setDateEditId] = useState(null);
  const [dateValue, setDateValue] = useState("");
  const [notesValue, setNotesValue] = useState("");
  const [error, setError] = useState("");
  const [confirmVaccine, setConfirmVaccine] = useState(null);
  const [confirmNotes, setConfirmNotes] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await api.listChildVaccinations(child.id);
      setAgeMonths(res.age_months);
      setVaccinations(res.vaccinations);
      setSummary(res.summary || null);
      setCanUpdate(res.can_update === true);
      setDisclaimer(res.disclaimer || "");
      setError("");
    } catch (err) {
      setError(err?.message || "Gagal memuat jadwal vaksinasi.");
    } finally {
      setLoading(false);
    }
  }, [child.id]);

  useEffect(() => {
    load();
  }, [load]);

  const applyGiven = async (v, notes) => {
    setError("");
    setSavingId(v.vaccine_schedule_id);
    try {
      await api.updateChildVaccinations(child.id, [
        {
          vaccine_schedule_id: v.vaccine_schedule_id,
          given: true,
          given_date: todayWIB(),
          notes: notes || null,
        },
      ]);
      await load();
    } catch (err) {
      setError(err.message);
    } finally {
      setSavingId(null);
    }
  };

  const toggleGiven = async (v) => {
    if (!canUpdate) return;
    if (v.given) {
      setError("");
      setSavingId(v.vaccine_schedule_id);
      try {
        await api.updateChildVaccinations(child.id, [
          { vaccine_schedule_id: v.vaccine_schedule_id, given: false, given_date: null },
        ]);
        await load();
      } catch (err) {
        setError(err.message);
      } finally {
        setSavingId(null);
      }
      return;
    }

    if (!v.due) {
      setConfirmVaccine(v);
      setConfirmNotes("");
      return;
    }

    await applyGiven(v, null);
  };

  const confirmEarlyGiven = async () => {
    if (!confirmVaccine) return;
    await applyGiven(confirmVaccine, confirmNotes || null);
    setConfirmVaccine(null);
    setConfirmNotes("");
  };

  const saveGivenDate = async (v) => {
    setError("");
    setSavingId(v.vaccine_schedule_id);
    try {
      await api.updateChildVaccinations(child.id, [
        { vaccine_schedule_id: v.vaccine_schedule_id, given: true, given_date: dateValue, notes: notesValue || null },
      ]);
      await load();
      setDateEditId(null);
    } catch (err) {
      setError(err.message);
    } finally {
      setSavingId(null);
    }
  };

  const categoryItems = vaccinations.filter((v) => v.category === category);
  const filtered = categoryItems.filter((v) => {
    if (statusFilter === "all") return true;
    if (statusFilter === "given") return v.state === "given" || v.given;
    if (statusFilter === "overdue") return v.state === "overdue";
    return !v.given;
  });
  const givenCount = categoryItems.filter((v) => v.given).length;
  const overdueNotGiven = categoryItems.filter((v) => v.state === "overdue" && !v.given);

  const stateLabel = (v) => {
    const state = v.state || (v.given ? "given" : v.due ? "due" : "upcoming");
    return { given: "Sudah diberikan", upcoming: "Akan datang", due: "Waktunya", overdue: "Terlambat" }[state] || "Belum tercatat";
  };

  return (
    <div>
      <div className="flex gap-2 mb-4">
        <button
          onClick={() => setCategory("wajib")}
          className={`flex-1 py-2.5 rounded-xl2 border text-xs font-medium ${
            category === "wajib" ? "bg-feed/15 border-feed text-feed" : "bg-void-card border-void-hairline text-ink-muted"
          }`}
        >
          Wajib (Pemerintah)
        </button>
        <button
          onClick={() => setCategory("tambahan")}
          className={`flex-1 py-2.5 rounded-xl2 border text-xs font-medium ${
            category === "tambahan" ? "bg-feed/15 border-feed text-feed" : "bg-void-card border-void-hairline text-ink-muted"
          }`}
        >
          Tambahan (IDAI)
        </button>
      </div>

      <div className="flex gap-1.5 mb-4 overflow-x-auto pb-1">
        {[
          ["pending", "Belum lengkap"], ["overdue", "Terlambat"], ["given", "Sudah diberikan"], ["all", "Semua"],
        ].map(([key, label]) => (
          <button
            key={key}
            type="button"
            onClick={() => setStatusFilter(key)}
            className={`px-3 py-1.5 rounded-full border text-[11px] whitespace-nowrap ${
              statusFilter === key ? "bg-feed/15 border-feed text-feed" : "border-void-hairline text-ink-muted"
            }`}
          >
            {label}
          </button>
        ))}
      </div>

      {loading ? (
        <p className="py-10 text-sm text-center text-ink-faint">Memuat...</p>
      ) : (
        <>
          {error && (
            <div className="px-4 py-3 mb-4 border bg-warn/10 border-warn/30 rounded-xl2">
              <p className="text-xs text-warn">{error}</p>
            </div>
          )}

          <div className="p-4 mb-4 border bg-void-card border-void-hairline rounded-xl2 shadow-soft">
            <div className="flex items-center justify-between mb-2">
              <p className="text-sm font-medium text-ink">
                {givenCount} dari {filtered.length} vaksin {category === "wajib" ? "wajib" : "tambahan"}
              </p>
              <p className="text-xs text-ink-faint">usia {ageMonths} bln</p>
            </div>
            <div className="w-full h-2 overflow-hidden rounded-full bg-void-hairline">
              <div
                className="h-full transition-all bg-diaper"
                style={{ width: `${filtered.length ? (givenCount / filtered.length) * 100 : 0}%` }}
              />
            </div>
            {summary && (
              <p className="mt-2 text-[11px] text-ink-faint">
                Keseluruhan: {summary.given} diberikan · {summary.due} waktunya · {summary.overdue} terlambat
              </p>
            )}
            {overdueNotGiven.length > 0 && (
              <p className="mt-2 text-xs text-warn">
                {overdueNotGiven.length} vaksin melewati lebih dari 30 hari dari tanggal rekomendasi
              </p>
            )}
            {category === "tambahan" && (
              <p className="text-[11px] text-ink-faint mt-2">
                Vaksin tambahan bersifat rekomendasi IDAI, umumnya berbayar. Konsultasikan ke dokter anak untuk prioritas.
              </p>
            )}
          </div>

          {!canUpdate && (
            <p className="px-3 py-2 mb-4 text-[11px] text-ink-faint border border-void-hairline rounded-lg">
              Peran Anda hanya dapat melihat riwayat vaksinasi.
            </p>
          )}

          {disclaimer && <p className="mb-4 text-[11px] text-ink-faint">{disclaimer}</p>}

          <div className="space-y-1.5">
            {filtered.map((v) => (
              <div key={v.vaccine_schedule_id} className="px-4 py-3 border bg-void-card border-void-hairline rounded-xl2">
                <div className="flex items-center justify-between">
                  <button
                    onClick={() => toggleGiven(v)}
                    disabled={!canUpdate || savingId === v.vaccine_schedule_id}
                    className="flex items-center flex-1 gap-3 text-left disabled:opacity-50"
                  >
                    <div
                      className={`w-6 h-6 rounded-full border flex items-center justify-center flex-shrink-0 ${
                        v.given ? "bg-diaper border-diaper" : v.due ? "border-warn" : "border-void-hairline"
                      }`}
                    >
                      {v.given && <span className="text-xs text-white">✓</span>}
                    </div>
                    <div>
                      <div className="flex items-center gap-1.5 flex-wrap">
                        <p className={`text-sm ${v.given ? "text-ink" : v.due ? "text-warn" : "text-ink-muted"}`}>
                          {v.vaccine_name}
                        </p>
                        {v.given_early && (
                          <span className="text-[10px] bg-sleep/15 text-sleep px-1.5 py-0.5 rounded-full font-medium">
                            Lebih awal
                          </span>
                        )}
                        <span className={`text-[10px] px-1.5 py-0.5 rounded-full font-medium ${
                          v.state === "overdue" ? "bg-warn/15 text-warn" :
                          v.state === "due" ? "bg-feed/15 text-feed" :
                          v.given ? "bg-diaper/15 text-diaper" : "bg-void border border-void-hairline text-ink-faint"
                        }`}>
                          {stateLabel(v)}
                        </span>
                      </div>
                      <p className="text-[11px] text-ink-faint font-mono">
                        usia {v.recommended_age_months} bln
                        {v.recommended_date && ` · rekomendasi ${fmtDate(v.recommended_date)}`}
                        {v.is_optional && " · wilayah endemis"}
                        {v.given && v.given_date && ` · diberikan ${fmtDate(v.given_date)}`}
                        {!v.given && v.due && " · sudah waktunya"}
                        {!v.given && !v.due && " · belum waktunya"}
                      </p>
                      {v.given_notes && (
                        <p className="text-[11px] text-sleep mt-0.5">📝 {v.given_notes}</p>
                      )}
                    </div>
                  </button>
                  {canUpdate && v.given && (
                    <button
                      onClick={() => {
                        setDateEditId(v.vaccine_schedule_id);
                        setDateValue(v.given_date || todayWIB());
                        setNotesValue(v.given_notes || "");
                      }}
                      className="text-[11px] text-ink-faint px-2"
                    >
                      Ubah
                    </button>
                  )}
                </div>

                {v.notes && <p className="text-[11px] text-ink-faint mt-1.5 ml-9">{v.notes}</p>}

                {dateEditId === v.vaccine_schedule_id && (
                  <div className="mt-2 space-y-2 ml-9">
                    <input
                      type="date"
                      value={dateValue}
                      onChange={(e) => setDateValue(e.target.value)}
                      max={todayWIB()}
                      className="bg-void border border-void-hairline rounded-lg px-2 py-1.5 text-ink text-xs"
                    />
                    <input
                      type="text"
                      value={notesValue}
                      onChange={(e) => setNotesValue(e.target.value)}
                      placeholder="Catatan (opsional), cth. rekomendasi dr. Erlin"
                      className="w-full bg-void border border-void-hairline rounded-lg px-2 py-1.5 text-ink text-xs placeholder:text-ink-faint"
                    />
                    <div className="flex items-center gap-2">
                      <button
                        onClick={() => saveGivenDate(v)}
                        className="text-xs px-2.5 py-1.5 rounded-lg bg-feed text-white font-medium"
                      >
                        Simpan
                      </button>
                      <button onClick={() => setDateEditId(null)} className="text-xs text-ink-faint">
                        Batal
                      </button>
                    </div>
                  </div>
                )}
              </div>
            ))}
          </div>
          {filtered.length === 0 && (
            <p className="py-8 text-sm text-center text-ink-faint">Tidak ada vaksin pada filter ini.</p>
          )}
        </>
      )}

      {confirmVaccine && (
        <div className="fixed inset-0 z-50 flex items-end sm:items-center sm:justify-center">
          <div className="absolute inset-0 bg-black/50" onClick={() => setConfirmVaccine(null)} />
          <div className="relative w-full p-6 pb-8 border-t sm:max-w-sm bg-void-card sm:border border-void-hairline rounded-t-xl2 sm:rounded-xl2">
            <div className="w-10 h-1 mx-auto mb-5 rounded-full bg-void-hairline sm:hidden" />
            <h2 className="mb-2 text-2xl font-display text-ink">Belum Masuk Usia Rekomendasi</h2>
            <p className="mb-4 text-sm text-ink-muted">
              <span className="font-medium text-ink">{confirmVaccine.vaccine_name}</span> baru direkomendasikan
              mulai usia {confirmVaccine.recommended_age_months} bulan, sedangkan anak baru berusia {ageMonths} bulan.
              Ini normal kalau dokter sengaja mempercepat jadwal (kejar imunisasi, kombinasi vaksin, dll).
            </p>
            <label className="block text-xs text-ink-muted mb-1.5">
              Catatan/alasan <span className="text-ink-faint">(opsional, tapi disarankan)</span>
            </label>
            <input
              type="text"
              value={confirmNotes}
              onChange={(e) => setConfirmNotes(e.target.value)}
              placeholder="cth. Rekomendasi dr. Erlin, dipercepat karena akan bepergian"
              className="w-full bg-void border border-void-hairline rounded-lg px-3 py-2.5 text-ink placeholder:text-ink-faint text-sm mb-4"
            />
            <div className="flex gap-3">
              <button
                onClick={() => setConfirmVaccine(null)}
                className="flex-1 py-3 text-sm font-medium border rounded-lg border-void-hairline text-ink-muted"
              >
                Batal
              </button>
              <button
                onClick={confirmEarlyGiven}
                disabled={savingId === confirmVaccine.vaccine_schedule_id}
                className="flex-1 py-3 text-sm font-semibold text-white rounded-lg bg-feed disabled:opacity-50"
              >
                Ya, Sudah Diberikan
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
