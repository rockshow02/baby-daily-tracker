import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, ApiError } from "../api/client";
import {
  cacheMedicationScheduleSnapshot, getCachedMedicationScheduleSnapshot,
} from "../utils/medicationScheduleCache";
import {
  describeOccurrenceState, DOSE_UNITS, describeDoseUnit, formatAdherencePercentage,
  formatDose, formatOccurrenceDateTime, formatTimesOfDay,
} from "../utils/medicationSchedule";
import { QUEUE_CHANGE_EVENT } from "../utils/offlineQueue";
import { canWrite } from "../utils/roles";

const MAX_TIMES_PER_DAY = 6;
const MEDICATION_NAME_MAX_LEN = 150;
const INSTRUCTIONS_MAX_LEN = 500;

// "Efisien & terbatas" -- PythonAnywhere Free nggak punya scheduler
// background, jadi frontend inilah yang berkala nanya ulang status
// SELAGI layar ini terbuka & tab-nya kelihatan (lihat
// backend/docs/MEDICATION_SCHEDULE.md, pola SAMA PERSIS
// hooks/useReminderMonitor.js yang sudah ada). 60 detik cukup
// responsif buat ambang upcoming/due/overdue (hitungan menit),
// TANPA membebani backend gratis dengan polling kelewat sering.
const POLL_INTERVAL_MS = 60000;

const DISCLAIMER =
  "Jadwal ini hanya mencerminkan instruksi yang dimasukkan sendiri oleh caregiver — bukan resep " +
  "atau saran medis. Selalu ikuti petunjuk dokter/apoteker untuk dosis dan jadwal pemberian obat.";

function useOnlineStatus() {
  const [isOnline, setIsOnline] = useState(navigator.onLine);
  useEffect(() => {
    const goOnline = () => setIsOnline(true);
    const goOffline = () => setIsOnline(false);
    window.addEventListener("online", goOnline);
    window.addEventListener("offline", goOffline);
    return () => {
      window.removeEventListener("online", goOnline);
      window.removeEventListener("offline", goOffline);
    };
  }, []);
  return isOnline;
}

function occurrenceIdentity(scheduleId, occurrenceKey) {
  return `${scheduleId}:${occurrenceKey}`;
}

/** Form buat bikin/ubah 1 jadwal obat — dipakai bareng create & edit (pola sama ReminderFormModal). */
function ScheduleFormModal({ initial, onClose, onSubmit, onDelete, submitting, deleting, errorMessage }) {
  const [medicationName, setMedicationName] = useState(initial?.medication_name || "");
  const [doseValue, setDoseValue] = useState(initial?.dose_value != null ? String(initial.dose_value) : "");
  const [doseUnit, setDoseUnit] = useState(initial?.dose_unit || "");
  const [instructions, setInstructions] = useState(initial?.instructions || "");
  const [startDate, setStartDate] = useState(initial?.start_date || "");
  const [endDate, setEndDate] = useState(initial?.end_date || "");
  const [timesOfDay, setTimesOfDay] = useState(
    initial?.times_of_day?.length ? [...initial.times_of_day] : ["08:00"],
  );

  const isEdit = Boolean(initial?.id);

  const updateTime = (i, value) => {
    setTimesOfDay((prev) => prev.map((t, idx) => (idx === i ? value : t)));
  };
  const addTime = () => {
    if (timesOfDay.length >= MAX_TIMES_PER_DAY) return;
    setTimesOfDay((prev) => [...prev, "12:00"]);
  };
  const removeTime = (i) => {
    setTimesOfDay((prev) => (prev.length > 1 ? prev.filter((_, idx) => idx !== i) : prev));
  };

  const handleSubmit = (e) => {
    e.preventDefault();
    onSubmit({
      medication_name: medicationName.trim(),
      dose_value: doseValue.trim() ? Number(doseValue) : null,
      dose_unit: doseValue.trim() ? doseUnit || null : null,
      instructions: instructions.trim() || null,
      start_date: startDate,
      end_date: endDate || null,
      times_of_day: timesOfDay,
    });
  };

  return (
    <div className="fixed inset-0 z-[60] flex items-end sm:items-center sm:justify-center">
      <div className="absolute inset-0 bg-black/50" onClick={onClose} />
      <form
        onSubmit={handleSubmit}
        role="dialog"
        aria-modal="true"
        aria-labelledby="medschedule-form-title"
        className="relative w-full sm:max-w-md bg-void-card border-t sm:border border-void-hairline rounded-t-xl2 sm:rounded-xl2 p-6 pb-8 max-h-[85vh] overflow-y-auto"
      >
        <h2 id="medschedule-form-title" className="font-display text-2xl text-ink mb-4">
          {isEdit ? "Ubah Jadwal Obat" : "Jadwal Obat Baru"}
        </h2>

        <label className="block text-xs text-ink-faint uppercase tracking-wider mb-1.5" htmlFor="medschedule-name">
          Nama Obat
        </label>
        <input
          id="medschedule-name"
          type="text"
          value={medicationName}
          onChange={(e) => setMedicationName(e.target.value)}
          maxLength={MEDICATION_NAME_MAX_LEN}
          placeholder="cth. Paracetamol drop"
          className="w-full bg-void border border-void-hairline rounded-lg px-3 py-2.5 text-sm text-ink mb-4"
          required
        />

        <div className="grid grid-cols-2 gap-2 mb-4">
          <div>
            <label className="block text-xs text-ink-faint uppercase tracking-wider mb-1.5" htmlFor="medschedule-dose-value">
              Dosis (opsional)
            </label>
            <input
              id="medschedule-dose-value"
              type="number"
              step="any"
              min="0"
              value={doseValue}
              onChange={(e) => setDoseValue(e.target.value)}
              placeholder="cth. 0.8"
              className="w-full bg-void border border-void-hairline rounded-lg px-3 py-2.5 text-sm text-ink"
            />
          </div>
          <div>
            <label className="block text-xs text-ink-faint uppercase tracking-wider mb-1.5" htmlFor="medschedule-dose-unit">
              Satuan
            </label>
            <select
              id="medschedule-dose-unit"
              value={doseUnit}
              onChange={(e) => setDoseUnit(e.target.value)}
              disabled={!doseValue.trim()}
              className="w-full bg-void border border-void-hairline rounded-lg px-3 py-2.5 text-sm text-ink disabled:opacity-50"
            >
              <option value="">Pilih satuan</option>
              {DOSE_UNITS.map((u) => (
                <option key={u} value={u}>{describeDoseUnit(u)}</option>
              ))}
            </select>
          </div>
        </div>

        <label className="block text-xs text-ink-faint uppercase tracking-wider mb-1.5">
          Jam Pemberian per Hari
        </label>
        <div className="space-y-2 mb-1.5">
          {timesOfDay.map((t, i) => (
            <div key={i} className="flex items-center gap-2">
              <input
                type="time"
                value={t}
                onChange={(e) => updateTime(i, e.target.value)}
                className="flex-1 bg-void border border-void-hairline rounded-lg px-3 py-2.5 text-sm text-ink"
                required
              />
              {timesOfDay.length > 1 && (
                <button
                  type="button"
                  onClick={() => removeTime(i)}
                  aria-label={`Hapus jam ke-${i + 1}`}
                  className="px-2.5 py-2 rounded-lg border border-void-hairline text-warn text-xs"
                >
                  Hapus
                </button>
              )}
            </div>
          ))}
        </div>
        {timesOfDay.length < MAX_TIMES_PER_DAY && (
          <button
            type="button"
            onClick={addTime}
            className="text-xs font-medium text-feed underline underline-offset-2 mb-4"
          >
            + Tambah jam
          </button>
        )}
        {timesOfDay.length >= MAX_TIMES_PER_DAY && (
          <p className="text-[11px] text-ink-faint mb-4">Maksimal {MAX_TIMES_PER_DAY} jam pemberian per hari.</p>
        )}

        <div className="grid grid-cols-2 gap-2 mb-4">
          <div>
            <label className="block text-xs text-ink-faint uppercase tracking-wider mb-1.5" htmlFor="medschedule-start">
              Mulai
            </label>
            <input
              id="medschedule-start"
              type="date"
              value={startDate}
              onChange={(e) => setStartDate(e.target.value)}
              className="w-full bg-void border border-void-hairline rounded-lg px-3 py-2.5 text-sm text-ink"
              required
            />
          </div>
          <div>
            <label className="block text-xs text-ink-faint uppercase tracking-wider mb-1.5" htmlFor="medschedule-end">
              Selesai (opsional)
            </label>
            <input
              id="medschedule-end"
              type="date"
              value={endDate}
              onChange={(e) => setEndDate(e.target.value)}
              min={startDate || undefined}
              className="w-full bg-void border border-void-hairline rounded-lg px-3 py-2.5 text-sm text-ink"
            />
          </div>
        </div>

        <label className="block text-xs text-ink-faint uppercase tracking-wider mb-1.5" htmlFor="medschedule-instructions">
          Instruksi (opsional)
        </label>
        <textarea
          id="medschedule-instructions"
          value={instructions}
          onChange={(e) => setInstructions(e.target.value)}
          maxLength={INSTRUCTIONS_MAX_LEN}
          rows={2}
          placeholder="cth. Berikan setelah makan"
          className="w-full bg-void border border-void-hairline rounded-lg px-3 py-2.5 text-sm text-ink mb-4"
        />

        {errorMessage && <p className="text-warn text-xs mb-4">{errorMessage}</p>}

        <div className="flex gap-2">
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
            {submitting ? "Menyimpan..." : "Simpan"}
          </button>
        </div>
        {isEdit && onDelete && (
          <button
            type="button"
            onClick={onDelete}
            disabled={deleting}
            className="w-full text-center text-xs text-warn mt-3 disabled:opacity-50"
          >
            {deleting ? "Menghapus..." : "Hapus jadwal ini"}
          </button>
        )}
      </form>
    </div>
  );
}

function OccurrenceCard({ schedule, occurrence, onAdminister, onSkip, pendingSync, actionPending }) {
  const isPending = pendingSync;
  // `occurrence.can_act` datang LANGSUNG dari backend (lihat
  // routes/medication_schedule_routes.py:_occurrence_to_json) — sudah
  // menggabungkan role, status okurensi INI, DAN kelayakan tanggal/jam.
  // Frontend TIDAK PERNAH menghitung ulang eligibility sendiri.
  // `actionPending` = request administer/skip ONLINE lagi berjalan buat
  // okurensi INI (belum tentu offline) -- proteksi klik ganda: tombol
  // disembunyikan sampai request-nya selesai (bukan cuma disabled),
  // biar nggak bisa nge-tap dua kali sebelum respons pertama balik.
  const canAct = occurrence.can_act && !isPending && !actionPending;
  const dose = formatDose(schedule.dose_value, schedule.dose_unit);

  return (
    <div className="bg-void border border-void-hairline rounded-xl2 px-4 py-3 mb-2">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="text-sm text-ink font-medium truncate">💊 {schedule.medication_name}</p>
          <p className="text-[11px] text-ink-faint">
            {formatOccurrenceDateTime(occurrence.occurrence_at)}{dose ? ` · ${dose}` : ""}
          </p>
        </div>
        <span
          className={`flex-shrink-0 text-[11px] font-semibold px-2 py-1 rounded-full ${
            occurrence.state === "overdue" ? "bg-warn/15 text-warn"
            : occurrence.state === "due" ? "bg-feed/15 text-feed"
            : occurrence.state === "administered" ? "bg-feed/10 text-feed"
            : occurrence.state === "skipped" ? "bg-void-hairline text-ink-faint"
            : "bg-void-hairline text-ink-muted"
          }`}
        >
          {isPending ? "Menunggu sinkron" : describeOccurrenceState(occurrence.state)}
        </span>
      </div>

      {occurrence.status && occurrence.acted_by_name && (
        <p className="text-[11px] text-ink-faint mt-1">oleh {occurrence.acted_by_name}</p>
      )}

      {canAct && (
        <div className="flex gap-2 mt-2.5">
          <div className="flex-1" />
          <button
            type="button"
            onClick={() => onSkip(schedule, occurrence)}
            className="px-3 py-1.5 rounded-lg border border-void-hairline text-ink-muted text-xs font-medium"
          >
            Lewati
          </button>
          <button
            type="button"
            onClick={() => onAdminister(schedule, occurrence)}
            className="px-3 py-1.5 rounded-lg bg-feed text-white text-xs font-semibold"
          >
            Sudah diberikan
          </button>
        </div>
      )}
    </div>
  );
}

function OccurrenceSection({ title, items, ...handlers }) {
  if (items.length === 0) return null;
  return (
    <div className="mb-4">
      <p className="text-xs text-ink-faint font-mono uppercase tracking-wider mb-2">{title}</p>
      {items.map(({ schedule, occurrence }) => (
        <OccurrenceCard
          key={occurrenceIdentity(schedule.id, occurrence.occurrence_key)}
          schedule={schedule}
          occurrence={occurrence}
          pendingSync={handlers.pendingSyncKeys.has(occurrenceIdentity(schedule.id, occurrence.occurrence_key))}
          actionPending={handlers.pendingActionKeys.has(occurrenceIdentity(schedule.id, occurrence.occurrence_key))}
          onAdminister={handlers.onAdminister}
          onSkip={handlers.onSkip}
        />
      ))}
    </div>
  );
}

function AdherenceSummaryWidget({ childId, isOnline }) {
  const [period, setPeriod] = useState("7d");
  const [summary, setSummary] = useState(null);
  const [status, setStatus] = useState("loading");

  useEffect(() => {
    if (!isOnline) {
      setStatus("offline");
      return;
    }
    let cancelled = false;
    setStatus("loading");
    api.getMedicationAdherence(childId, period)
      .then((res) => {
        if (cancelled) return;
        setSummary(res);
        setStatus("ready");
      })
      .catch(() => {
        if (cancelled) return;
        setStatus("error");
      });
    return () => { cancelled = true; };
  }, [childId, period, isOnline]);

  return (
    <div className="bg-void-card border border-void-hairline rounded-xl2 px-4 py-3 mb-4">
      <div className="flex items-center justify-between mb-2">
        <p className="text-xs text-ink-faint font-mono uppercase tracking-wider">Ringkasan Kepatuhan</p>
        <div className="flex gap-1">
          {["7d", "30d"].map((p) => (
            <button
              key={p}
              type="button"
              onClick={() => setPeriod(p)}
              className={`px-2.5 py-1 rounded-full text-[11px] font-medium border ${
                period === p ? "bg-feed/15 border-feed text-feed" : "border-void-hairline text-ink-muted"
              }`}
            >
              {p === "7d" ? "7 Hari" : "30 Hari"}
            </button>
          ))}
        </div>
      </div>

      {status === "offline" && <p className="text-[11px] text-ink-faint">Butuh koneksi internet untuk memuat ringkasan kepatuhan.</p>}
      {status === "loading" && <p className="text-[11px] text-ink-faint">Memuat...</p>}
      {status === "error" && <p className="text-[11px] text-warn">Gagal memuat ringkasan kepatuhan.</p>}
      {status === "ready" && summary && (
        summary.expected_count === 0 ? (
          <p className="text-[11px] text-ink-faint">Belum ada dosis yang dijadwalkan pada periode ini.</p>
        ) : (
          <div className="grid grid-cols-2 gap-x-4 gap-y-1.5 text-[11px]">
            <p className="text-ink-muted">Dijadwalkan <span className="text-ink font-medium">{summary.expected_count}</span></p>
            <p className="text-ink-muted">Diberikan <span className="text-ink font-medium">{summary.administered_count}</span></p>
            <p className="text-ink-muted">Dilewati <span className="text-ink font-medium">{summary.skipped_count}</span></p>
            <p className="text-ink-muted">Belum selesai <span className="text-ink font-medium">{summary.overdue_unresolved_count}</span></p>
            <p className="text-ink-muted col-span-2">
              Kepatuhan <span className="text-feed font-semibold">{formatAdherencePercentage(summary.adherence_percentage)}</span>
            </p>
          </div>
        )
      )}
    </div>
  );
}

/**
 * "💊 Jadwal Obat" — Medication Schedule & Adherence Phase 1. Lihat
 * backend/docs/MEDICATION_SCHEDULE.md buat kontrak API & kebijakan
 * lengkapnya. Status due/overdue SELALU dari server (dihitung ulang tiap
 * fetch) — layar ini TIDAK PERNAH menghitung status sendiri dari waktu
 * lokal browser. Dibuka sebagai overlay dari HealthScreen (tab Obat),
 * bukan item navigasi baru — pola SAMA PERSIS DoctorConsultationScreen.
 */
export default function MedicationScheduleScreen({ child, currentUserId, onClose }) {
  const isOnline = useOnlineStatus();
  const [status, setStatus] = useState("loading");
  const [data, setData] = useState(null);
  const [cachedAt, setCachedAt] = useState(null);
  const [errorMessage, setErrorMessage] = useState("");
  const [showForm, setShowForm] = useState(false);
  const [editingSchedule, setEditingSchedule] = useState(null);
  const [formError, setFormError] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [manageFilter, setManageFilter] = useState("active");
  const [pendingSyncKeys, setPendingSyncKeys] = useState(new Set());
  const [pendingActionKeys, setPendingActionKeys] = useState(new Set());
  // Proteksi request tumpang-tindih (Defect 2 review) -- ref biasa,
  // BUKAN state (nggak perlu re-render buat ini), dicek SEBELUM
  // `load()` beneran mulai fetch baru: tick polling 60 detik yang
  // kebetulan bareng sama visibilitychange, ATAUPUN reload manual yang
  // masih nunggu respons sebelumnya, TIDAK PERNAH memicu 2 request
  // `GET .../medication-schedules` yang tumpang tindih.
  const loadInFlightRef = useRef(false);

  const loadFromCache = useCallback(() => {
    const cached = getCachedMedicationScheduleSnapshot(currentUserId, child.id);
    if (cached) {
      setData(cached.data);
      setCachedAt(cached.cachedAt);
      setStatus("offline_cached");
    } else {
      setData(null);
      setCachedAt(null);
      setStatus("offline_no_cache");
    }
  }, [currentUserId, child.id]);

  const load = useCallback(async (opts = {}) => {
    // `silent`: dipakai refresh LATAR BELAKANG (polling 60 detik &
    // balik-jadi-visible, lihat useEffect di bawah) -- BEDA dari reload
    // yang dipicu user (buka layar, ganti anak, "Coba lagi", aksi
    // administer/skip) yang WAJAR mulai dari keadaan bersih. Refresh
    // diam-diam TIDAK PERNAH menghapus pesan error/konflik yang lagi
    // ditampilkan HANYA karena timer-nya kebetulan jalan (requirement
    // review: "do not clear a meaningful conflict/error message because
    // a background refresh started").
    const silent = opts.silent === true;
    if (!isOnline) {
      loadFromCache();
      return;
    }
    if (loadInFlightRef.current) return; // proteksi tumpang tindih, lihat deklarasi ref di atas
    loadInFlightRef.current = true;
    setStatus((prev) => (prev === "ready" || prev === "offline_cached" ? prev : "loading"));
    if (!silent) setErrorMessage("");
    try {
      const res = await api.listMedicationSchedules(child.id);
      setData(res);
      setCachedAt(null);
      setStatus("ready");
      cacheMedicationScheduleSnapshot(currentUserId, child.id, res);
    } catch (err) {
      if (err instanceof ApiError && err.kind === "network") {
        loadFromCache();
        return;
      }
      if (err instanceof ApiError && err.kind === "forbidden") {
        setStatus("forbidden");
        setErrorMessage(err?.message || "Anda tidak punya akses ke jadwal obat anak ini.");
        return;
      }
      setStatus("error");
      setErrorMessage(err?.message || "Gagal memuat jadwal obat.");
    } finally {
      loadInFlightRef.current = false;
    }
  }, [child.id, isOnline, currentUserId, loadFromCache]);

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [child.id, isOnline]);

  // Antrian offline berubah (item baru masuk ATAU berhasil disinkron) —
  // muat ulang biar status okurensi yang barusan disinkron ke-refresh,
  // dan bersihin penanda "menunggu sinkron" buat yang udah kelar.
  useEffect(() => {
    const onQueueChange = () => {
      setPendingSyncKeys((prev) => (prev.size > 0 ? new Set() : prev));
      load();
    };
    window.addEventListener(QUEUE_CHANGE_EVENT, onQueueChange);
    return () => window.removeEventListener(QUEUE_CHANGE_EVENT, onQueueChange);
  }, [load]);

  // Monitor terbatas (Defect 2 review) -- status due/overdue backend
  // BISA basi kalau layar ini dibiarkan terbuka lama tanpa interaksi
  // apa pun. Pola SAMA PERSIS hooks/useReminderMonitor.js, DITAMBAH 2
  // penyempurnaan yang eksplisit diminta review: (1) TIDAK PERNAH
  // polling selagi offline (effect ini nggak dipasang sama sekali kalau
  // `isOnline` false -- bukan cuma "polling tapi hasilnya dibuang"),
  // (2) TIDAK PERNAH benar-benar fetch selagi tab tersembunyi (interval
  // TETAP jalan supaya nggak perlu dipasang/dicabut berkali-kali, tapi
  // tick-nya sendiri no-op kalau `document.visibilityState !== "visible"`).
  // TIDAK ADA WebSocket/worker/cron/Celery/Redis/koneksi persisten --
  // ini MURNI polling REST biasa selagi tab terbuka & online, konsisten
  // sama arsitektur "tanpa scheduler" seluruh fitur ini.
  useEffect(() => {
    if (!isOnline) return undefined;

    const tick = () => {
      if (document.visibilityState === "visible") load({ silent: true });
    };
    const interval = setInterval(tick, POLL_INTERVAL_MS);

    const onVisibility = () => {
      if (document.visibilityState === "visible") load({ silent: true });
    };
    document.addEventListener("visibilitychange", onVisibility);

    return () => {
      clearInterval(interval);
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, [isOnline, load]);

  const handleAct = async (schedule, occurrence, action) => {
    const key = occurrenceIdentity(schedule.id, occurrence.occurrence_key);
    // Proteksi klik ganda: request ONLINE buat okurensi INI masih
    // berjalan -- abaikan tap kedua sama sekali (tombolnya sendiri juga
    // udah disembunyikan lewat `actionPending`, ini lapis kedua kalau
    // event sempat nembus sebelum re-render).
    if (pendingActionKeys.has(key)) return;
    setPendingActionKeys((prev) => new Set(prev).add(key));
    try {
      const call = action === "administer" ? api.administerMedicationDose : api.skipMedicationDose;
      const result = await call(child.id, schedule.id, occurrence.occurrence_key);
      if (result && result._offlineQueued) {
        setPendingSyncKeys((prev) => new Set(prev).add(key));
      } else {
        load();
      }
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        // `load()` sendiri nge-clear `errorMessage` di awal (biar retry
        // "Coba lagi" biasa mulai bersih) -- WAJIB ditunggu SELESAI dulu
        // sebelum nyetel pesan konflik ini, kalau nggak race: pesannya
        // ke-timpa balik jadi kosong oleh `load()` yang jalan belakangan.
        await load();
        setErrorMessage("Dosis ini sudah ditandai oleh caregiver lain. Daftar sudah diperbarui.");
        return;
      }
      setErrorMessage(err?.message || "Aksi gagal, coba lagi.");
    } finally {
      setPendingActionKeys((prev) => {
        if (!prev.has(key)) return prev;
        const next = new Set(prev);
        next.delete(key);
        return next;
      });
    }
  };

  const handleCreateOrUpdate = async (payload) => {
    setSubmitting(true);
    setFormError("");
    try {
      if (editingSchedule) {
        await api.updateMedicationSchedule(child.id, editingSchedule.id, payload);
      } else {
        await api.createMedicationSchedule(child.id, payload);
      }
      setShowForm(false);
      setEditingSchedule(null);
      load();
    } catch (err) {
      setFormError(err?.message || "Gagal menyimpan jadwal obat.");
    } finally {
      setSubmitting(false);
    }
  };

  const handleDelete = async () => {
    if (!editingSchedule) return;
    if (!window.confirm(`Hapus jadwal obat "${editingSchedule.medication_name}"? Riwayat pemberian obat yang sudah tercatat tidak akan terhapus.`)) return;
    setDeleting(true);
    try {
      await api.deleteMedicationSchedule(child.id, editingSchedule.id);
      setShowForm(false);
      setEditingSchedule(null);
      load();
    } catch (err) {
      setFormError(err?.message || "Gagal menghapus jadwal obat.");
    } finally {
      setDeleting(false);
    }
  };

  const handleToggleActive = async (schedule) => {
    try {
      await api.updateMedicationSchedule(child.id, schedule.id, { is_active: !schedule.is_active });
      load();
    } catch (err) {
      setErrorMessage(err?.message || "Gagal mengubah jadwal obat.");
    }
  };

  const grouped = useMemo(() => {
    const buckets = { overdue: [], due: [], upcoming: [], resolved: [] };
    for (const schedule of data?.schedules || []) {
      for (const occurrence of schedule.occurrences || []) {
        const entry = { schedule, occurrence };
        if (occurrence.state === "overdue") buckets.overdue.push(entry);
        else if (occurrence.state === "due") buckets.due.push(entry);
        else if (occurrence.state === "upcoming") buckets.upcoming.push(entry);
        else buckets.resolved.push(entry);
      }
    }
    buckets.overdue.sort((a, b) => a.occurrence.occurrence_at.localeCompare(b.occurrence.occurrence_at));
    buckets.due.sort((a, b) => a.occurrence.occurrence_at.localeCompare(b.occurrence.occurrence_at));
    buckets.upcoming.sort((a, b) => a.occurrence.occurrence_at.localeCompare(b.occurrence.occurrence_at));
    buckets.resolved.sort((a, b) => (b.occurrence.acted_at || "").localeCompare(a.occurrence.acted_at || ""));
    return buckets;
  }, [data]);

  const manageableSchedules = (data?.schedules || []).filter((s) => manageFilter === "all" || s.is_active);
  const canCreate = canWrite(child.role);

  return (
    <div className="fixed inset-0 z-50 bg-void overflow-y-auto">
      <div className="min-h-screen pb-16 px-6 pt-8 max-w-lg mx-auto">
        <div className="flex items-center justify-between mb-1">
          <h1 className="font-display text-3xl text-ink">💊 Jadwal Obat</h1>
          <button
            type="button"
            onClick={onClose}
            aria-label="Tutup"
            className="w-9 h-9 rounded-full border border-void-hairline text-ink-muted flex items-center justify-center flex-shrink-0"
          >
            ✕
          </button>
        </div>
        <p className="text-sm text-ink-muted mb-4">Jadwal pemberian obat {child.nickname || child.name}</p>

        <div className="bg-void border border-void-hairline rounded-xl2 px-4 py-3 mb-4">
          <p className="text-xs text-ink-muted">{DISCLAIMER}</p>
        </div>

        {status === "offline_cached" && (
          <p className="text-[11px] text-warn bg-warn/10 border border-warn/30 rounded-lg px-3 py-2 mb-4">
            Menampilkan jadwal obat terakhir saat offline — dibuat {formatOccurrenceDateTime(cachedAt)}.
          </p>
        )}

        {status === "loading" && (
          <div className="space-y-3" aria-live="polite" aria-busy="true">
            <p className="text-ink-faint text-sm text-center py-2">Memuat jadwal obat...</p>
            {[0, 1].map((i) => (
              <div key={i} className="h-16 bg-void-card border border-void-hairline rounded-xl2 animate-pulse" />
            ))}
          </div>
        )}

        {status === "forbidden" && (
          <div className="text-center py-10 px-4">
            <p className="text-3xl mb-3">🔒</p>
            <p className="text-ink text-sm font-medium mb-1">Tidak punya akses</p>
            <p className="text-ink-faint text-xs">{errorMessage}</p>
          </div>
        )}

        {status === "error" && (
          <div className="text-center py-6 space-y-3">
            <p className="text-warn text-sm">{errorMessage}</p>
            <button onClick={load} className="px-4 py-2 rounded-lg border border-void-hairline text-ink-muted text-sm font-medium">
              Coba lagi
            </button>
          </div>
        )}

        {status === "offline_no_cache" && (
          <div className="text-center py-10 px-4">
            <p className="text-3xl mb-3">📡</p>
            <p className="text-ink text-sm font-medium mb-1">Belum ada jadwal obat tersimpan</p>
            <p className="text-ink-faint text-xs">Sambungkan ke internet dulu untuk memuat jadwal obat.</p>
          </div>
        )}

        {(status === "ready" || status === "offline_cached") && data && (
          <>
            {errorMessage && <p className="text-warn text-xs mb-3">{errorMessage}</p>}

            {isOnline && <AdherenceSummaryWidget childId={child.id} isOnline={isOnline} />}

            {isOnline && canCreate && (
              <button
                type="button"
                onClick={() => { setEditingSchedule(null); setFormError(""); setShowForm(true); }}
                className="w-full py-3 mb-4 rounded-xl2 bg-feed text-white text-sm font-semibold"
              >
                + Jadwal Obat Baru
              </button>
            )}
            {!isOnline && (
              <p className="text-[11px] text-ink-faint mb-4">
                Membuat/mengubah/menghapus jadwal obat butuh koneksi internet. Menandai obat
                sudah diberikan atau dilewati tetap bisa dilakukan offline.
              </p>
            )}

            {grouped.overdue.length === 0 && grouped.due.length === 0 && grouped.upcoming.length === 0
              && grouped.resolved.length === 0 && (data.schedules || []).length === 0 && (
              <p className="text-ink-faint text-sm text-center py-10">
                Belum ada jadwal obat. Buat jadwal pertama untuk mulai memantau pemberian obat.
              </p>
            )}

            <OccurrenceSection
              title="Terlambat"
              items={grouped.overdue}
              onAdminister={(s, o) => handleAct(s, o, "administer")}
              onSkip={(s, o) => handleAct(s, o, "skip")}
              pendingSyncKeys={pendingSyncKeys}
              pendingActionKeys={pendingActionKeys}
            />
            <OccurrenceSection
              title="Jatuh Tempo"
              items={grouped.due}
              onAdminister={(s, o) => handleAct(s, o, "administer")}
              onSkip={(s, o) => handleAct(s, o, "skip")}
              pendingSyncKeys={pendingSyncKeys}
              pendingActionKeys={pendingActionKeys}
            />
            <OccurrenceSection
              title="Akan Datang"
              items={grouped.upcoming}
              onAdminister={(s, o) => handleAct(s, o, "administer")}
              onSkip={(s, o) => handleAct(s, o, "skip")}
              pendingSyncKeys={pendingSyncKeys}
              pendingActionKeys={pendingActionKeys}
            />
            <OccurrenceSection
              title="Riwayat Terkini"
              items={grouped.resolved.slice(0, 10)}
              onAdminister={(s, o) => handleAct(s, o, "administer")}
              onSkip={(s, o) => handleAct(s, o, "skip")}
              pendingSyncKeys={pendingSyncKeys}
              pendingActionKeys={pendingActionKeys}
            />

            {(data.schedules || []).length > 0 && (
              <div className="mt-6">
                <div className="flex items-center justify-between mb-2">
                  <p className="text-xs text-ink-faint font-mono uppercase tracking-wider">Kelola Jadwal</p>
                  <div className="flex gap-1">
                    {["active", "all"].map((f) => (
                      <button
                        key={f}
                        type="button"
                        onClick={() => setManageFilter(f)}
                        className={`px-2.5 py-1 rounded-full text-[11px] font-medium border ${
                          manageFilter === f ? "bg-feed/15 border-feed text-feed" : "border-void-hairline text-ink-muted"
                        }`}
                      >
                        {f === "active" ? "Aktif" : "Semua"}
                      </button>
                    ))}
                  </div>
                </div>
                {manageableSchedules.map((s) => (
                  <div key={s.id} className="bg-void-card border border-void-hairline rounded-xl2 px-4 py-3 mb-2 flex items-center justify-between gap-2">
                    <div className="min-w-0">
                      <p className="text-sm text-ink truncate">💊 {s.medication_name}</p>
                      <p className="text-[11px] text-ink-faint">
                        {formatTimesOfDay(s.times_of_day)}
                        {!s.is_active && " · Nonaktif"}
                      </p>
                    </div>
                    {(s.can_edit || s.can_delete) && isOnline && (
                      <div className="flex gap-1.5 flex-shrink-0">
                        {s.can_edit && (
                          <button
                            type="button"
                            onClick={() => handleToggleActive(s)}
                            className="px-2.5 py-1.5 rounded-lg border border-void-hairline text-ink-muted text-[11px] font-medium"
                          >
                            {s.is_active ? "Nonaktifkan" : "Aktifkan"}
                          </button>
                        )}
                        {s.can_edit && (
                          <button
                            type="button"
                            onClick={() => { setEditingSchedule(s); setFormError(""); setShowForm(true); }}
                            className="px-2.5 py-1.5 rounded-lg border border-void-hairline text-ink-muted text-[11px] font-medium"
                          >
                            Ubah
                          </button>
                        )}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            )}
          </>
        )}

        {showForm && (
          <ScheduleFormModal
            initial={editingSchedule}
            onClose={() => { setShowForm(false); setEditingSchedule(null); }}
            onSubmit={handleCreateOrUpdate}
            onDelete={editingSchedule?.can_delete ? handleDelete : null}
            submitting={submitting}
            deleting={deleting}
            errorMessage={formError}
          />
        )}
      </div>
    </div>
  );
}
