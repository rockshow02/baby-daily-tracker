import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError } from "../api/client";
import {
  formatDateTimeWIB, formatDateWIB, formatVolumeMl, formatDurationMinutes,
  formatTemperatureC, orDash,
} from "../utils/consultationFormat";

// Pola SAMA PERSIS pages/MedicationScheduleScreen.jsx — 60 detik cukup
// responsif buat status obat/pengingat "butuh perhatian" TANPA
// membebani backend gratis (PythonAnywhere Free, tidak ada scheduler
// background). Lihat backend/docs/CAREGIVER_HANDOVER.md.
const POLL_INTERVAL_MS = 60000;
const NOTE_MAX_LEN = 1000;

// Requirement eksplisit Fase 1 — TEKS PERSIS ini, TIDAK PERNAH
// diparafrase, dipakai di SETIAP tempat layar ini butuh koneksi tapi
// sedang offline.
const OFFLINE_MESSAGE = "Butuh koneksi internet untuk membuka atau memperbarui Serah Terima Pengasuh.";

const BACKGROUND_REFRESH_WARNING = "Pembaruan otomatis gagal. Data terakhir masih ditampilkan.";

const DISCLAIMER_FALLBACK =
  "Serah terima ini merangkum catatan yang dimasukkan sendiri oleh caregiver dan bukan diagnosis, " +
  "saran pengobatan, atau rekomendasi penanganan darurat.";

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

function SectionCard({ title, children }) {
  return (
    <div className="bg-void border border-void-hairline rounded-xl2 px-4 py-3 mb-3">
      <p className="text-xs text-ink-faint font-mono uppercase tracking-wider mb-1.5">{title}</p>
      {children}
    </div>
  );
}

function Row({ label, value }) {
  return (
    <div className="flex items-center justify-between text-[13px] py-0.5">
      <span className="text-ink-muted">{label}</span>
      <span className="text-ink font-medium text-right">{value}</span>
    </div>
  );
}

function FeedingSection({ feeding }) {
  return (
    <SectionCard title="🍼 Menyusui / Minum">
      <Row label="Jumlah kejadian" value={feeding.total_events} />
      {feeding.total_events > 0 && (
        <>
          <Row label="Terakhir" value={formatDateTimeWIB(feeding.latest_timestamp)} />
          <Row label="Jenis terakhir" value={orDash(feeding.latest_feed_type)} />
          <Row label="Volume terakhir" value={feeding.latest_volume_ml != null ? formatVolumeMl(feeding.latest_volume_ml) : orDash(null)} />
          <Row label="Total volume terukur" value={feeding.measured_total_volume_ml != null ? formatVolumeMl(feeding.measured_total_volume_ml) : "Sebagian tidak tercatat"} />
        </>
      )}
      {feeding.total_events === 0 && <p className="text-[11px] text-ink-faint mt-1">Belum ada catatan menyusui/minum di 24 jam ini.</p>}
    </SectionCard>
  );
}

function SleepSection({ sleep }) {
  return (
    <SectionCard title="😴 Tidur">
      <Row label="Jumlah sesi" value={sleep.total_events} />
      {sleep.total_events > 0 && (
        <>
          <Row label="Mulai terakhir" value={formatDateTimeWIB(sleep.latest_start_time)} />
          <Row label="Status" value={sleep.latest_is_ongoing ? "Masih berlangsung" : formatDateTimeWIB(sleep.latest_end_time)} />
          <Row label="Total durasi selesai" value={formatDurationMinutes(sleep.total_completed_minutes)} />
        </>
      )}
      {sleep.total_events === 0 && <p className="text-[11px] text-ink-faint mt-1">Belum ada catatan tidur di 24 jam ini.</p>}
    </SectionCard>
  );
}

function DiaperSection({ diaper }) {
  return (
    <SectionCard title="🧷 Popok">
      <Row label="Jumlah ganti" value={diaper.total_events} />
      {diaper.total_events > 0 && (
        <>
          <Row label="Terakhir" value={formatDateTimeWIB(diaper.latest_timestamp)} />
          <Row label="Basah" value={diaper.wet_count} />
          <Row label="Kotor" value={diaper.dirty_count} />
          <Row label="Keduanya" value={diaper.mixed_count} />
        </>
      )}
      {diaper.total_events === 0 && <p className="text-[11px] text-ink-faint mt-1">Belum ada catatan popok di 24 jam ini.</p>}
    </SectionCard>
  );
}

function PumpingSection({ pumping }) {
  if (pumping.total_events === 0) return null;
  return (
    <SectionCard title="🍶 Perah ASI">
      <Row label="Jumlah sesi" value={pumping.total_events} />
      <Row label="Terakhir" value={formatDateTimeWIB(pumping.latest_timestamp)} />
      <Row label="Total volume terukur" value={pumping.measured_total_volume_ml != null ? formatVolumeMl(pumping.measured_total_volume_ml) : "Sebagian tidak tercatat"} />
    </SectionCard>
  );
}

function ActivityMoodSection({ activityMood }) {
  if (activityMood.activity_total_events === 0 && activityMood.mood_total_events === 0) return null;
  return (
    <SectionCard title="🚼 Aktivitas & Suasana Hati">
      {activityMood.activity_total_events > 0 && (
        <>
          <Row label="Aktivitas" value={activityMood.activity_total_events} />
          <Row label="Terakhir" value={orDash(activityMood.latest_activity_type)} />
        </>
      )}
      {activityMood.mood_total_events > 0 && (
        <>
          <Row label="Suasana hati tercatat" value={activityMood.mood_total_events} />
          <Row label="Terakhir" value={orDash(activityMood.latest_mood)} />
        </>
      )}
    </SectionCard>
  );
}

function HealthSection({ health }) {
  const hasTemp = health.latest_temperature_celsius != null;
  const hasIllness = (health.illnesses_overlapping_window || []).length > 0;
  const hasVisit = Boolean(health.latest_doctor_visit_date);
  if (!hasTemp && !hasIllness && !hasVisit) return null;
  return (
    <SectionCard title="🩺 Kesehatan">
      {hasTemp && (
        <>
          <Row label="Suhu terakhir" value={formatTemperatureC(health.latest_temperature_celsius)} />
          <Row label="Waktu ukur" value={formatDateTimeWIB(health.latest_temperature_at)} />
        </>
      )}
      {hasIllness && (
        <div className="mt-1.5">
          <p className="text-[11px] text-ink-faint mb-1">Periode sakit yang tumpang tindih 24 jam ini:</p>
          {health.illnesses_overlapping_window.map((ill, i) => (
            <p key={i} className="text-[13px] text-ink">
              {formatDateWIB(ill.start_date)} – {ill.is_ongoing ? "masih berlangsung" : formatDateWIB(ill.end_date)}
            </p>
          ))}
        </div>
      )}
      {hasVisit && (
        <div className="mt-1.5">
          <Row label="Kunjungan dokter terakhir" value={formatDateWIB(health.latest_doctor_visit_date)} />
          {health.latest_doctor_visit_reason && <Row label="Alasan" value={health.latest_doctor_visit_reason} />}
        </div>
      )}
    </SectionCard>
  );
}

function MedicationSection({ medication }) {
  const hasAny = medication.administered_in_window.length > 0 || medication.skipped_in_window.length > 0
    || medication.overdue_as_of_as_of_at.length > 0 || medication.next_occurrence;
  if (!hasAny) return null;
  return (
    <SectionCard title="💊 Obat — Butuh Perhatian">
      {medication.overdue_as_of_as_of_at.length > 0 && (
        <div className="mb-2">
          <p className="text-[11px] text-warn font-medium mb-1">Terlambat</p>
          {medication.overdue_as_of_as_of_at.map((e, i) => (
            <p key={i} className="text-[13px] text-ink">
              {e.medication_name}{e.dose ? ` (${e.dose})` : ""} — {formatDateTimeWIB(e.occurrence_at)}
            </p>
          ))}
        </div>
      )}
      {medication.next_occurrence && (
        <div className="mb-2">
          <p className="text-[11px] text-ink-faint font-medium mb-1">Jadwal berikutnya (hari ini)</p>
          <p className="text-[13px] text-ink">
            {medication.next_occurrence.medication_name}{medication.next_occurrence.dose ? ` (${medication.next_occurrence.dose})` : ""} — {formatDateTimeWIB(medication.next_occurrence.occurrence_at)}
          </p>
        </div>
      )}
      {(medication.administered_in_window.length > 0 || medication.skipped_in_window.length > 0) && (
        <div>
          <p className="text-[11px] text-ink-faint font-medium mb-1">Sudah diproses (24 jam ini)</p>
          {medication.administered_in_window.map((e, i) => (
            <p key={`a-${i}`} className="text-[13px] text-ink">✓ {e.medication_name} — {formatDateTimeWIB(e.occurrence_at)}</p>
          ))}
          {medication.skipped_in_window.map((e, i) => (
            <p key={`s-${i}`} className="text-[13px] text-ink-faint">✗ dilewati — {e.medication_name} — {formatDateTimeWIB(e.occurrence_at)}</p>
          ))}
        </div>
      )}
    </SectionCard>
  );
}

function ReminderSection({ reminders }) {
  const hasAny = reminders.resolved_in_window.length > 0 || reminders.overdue_as_of_as_of_at.length > 0 || reminders.next_occurrence;
  if (!hasAny) return null;
  return (
    <SectionCard title="⏰ Pengingat — Butuh Perhatian">
      {reminders.overdue_as_of_as_of_at.length > 0 && (
        <div className="mb-2">
          <p className="text-[11px] text-warn font-medium mb-1">Terlambat</p>
          {reminders.overdue_as_of_as_of_at.map((e, i) => (
            <p key={i} className="text-[13px] text-ink">{e.title} — {formatDateTimeWIB(e.occurrence_at)}</p>
          ))}
        </div>
      )}
      {reminders.next_occurrence && (
        <div className="mb-2">
          <p className="text-[11px] text-ink-faint font-medium mb-1">Berikutnya</p>
          <p className="text-[13px] text-ink">{reminders.next_occurrence.title} — {formatDateTimeWIB(reminders.next_occurrence.occurrence_at)}</p>
        </div>
      )}
      {reminders.resolved_in_window.length > 0 && (
        <div>
          <p className="text-[11px] text-ink-faint font-medium mb-1">Selesai (24 jam ini)</p>
          {reminders.resolved_in_window.map((e, i) => (
            <p key={i} className="text-[13px] text-ink-faint">{e.status === "completed" ? "✓" : "✗"} {e.title} — {formatDateTimeWIB(e.occurrence_at)}</p>
          ))}
        </div>
      )}
    </SectionCard>
  );
}

function AcknowledgementList({ acknowledgements, currentUserId }) {
  return (
    <SectionCard title="✅ Sudah Membaca">
      {acknowledgements.length === 0 && <p className="text-[11px] text-ink-faint">Belum ada caregiver yang menandai sudah membaca.</p>}
      {acknowledgements.map((ack) => (
        <Row
          key={ack.id}
          label={ack.user_id === currentUserId ? `${ack.display_name} (Anda)` : ack.display_name}
          value={formatDateTimeWIB(ack.acknowledged_at)}
        />
      ))}
    </SectionCard>
  );
}

/**
 * "🤝 Serah Terima Pengasuh" — Caregiver Handover Summary Phase 1. Lihat
 * backend/docs/CAREGIVER_HANDOVER.md buat kontrak API & kebijakan
 * lengkapnya. Dibuka sebagai overlay dari Dashboard, BUKAN item
 * navigasi baru (pola SAMA PERSIS DoctorConsultationScreen/
 * MedicationScheduleScreen). ONLINE-ONLY SENGAJA — TIDAK PERNAH
 * menyimpan data handover ke localStorage/IndexedDB/service-worker
 * cache/antrean offline, TIDAK PERNAH menampilkan data basi sebagai
 * data SEKARANG selagi offline (data terpercaya yang lagi tertampil di
 * MEMORI komponen ini tetap kelihatan, tapi ditandai kemungkinan usang
 * & semua kontrol mutasi dinonaktifkan).
 */
export default function CaregiverHandoverScreen({ child, currentUserId, onClose }) {
  const isOnline = useOnlineStatus();
  const [status, setStatus] = useState("loading"); // loading | ready | forbidden | error
  const [data, setData] = useState(null); // { handover, summary, acknowledgements, capabilities }
  const [errorMessage, setErrorMessage] = useState("");
  const [backgroundWarning, setBackgroundWarning] = useState("");
  const [noteDraft, setNoteDraft] = useState("");
  const [editingNote, setEditingNote] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [ackSubmitting, setAckSubmitting] = useState(false);
  const [closeSubmitting, setCloseSubmitting] = useState(false);
  const [confirmingClose, setConfirmingClose] = useState(false);

  const statusRef = useRef(status);
  useEffect(() => { statusRef.current = status; }, [status]);

  // Proteksi request tumpang-tindih -- pola SAMA PERSIS
  // pages/MedicationScheduleScreen.jsx: tidak pernah ada 2 request GET
  // yang beneran jalan bersamaan buat komponen ini.
  const loadInFlightRef = useRef(false);
  const pendingLoadRef = useRef(null);

  // Anak aktif SEKARANG -- respons yang datang buat anak yang SUDAH
  // BUKAN anak aktif lagi (pergantian anak cepat selagi request lama
  // masih menggantung) dibuang diam-diam, tidak pernah menimpa
  // tampilan anak yang baru.
  const activeChildIdRef = useRef(child.id);
  useEffect(() => {
    activeChildIdRef.current = child.id;
    setData(null);
    setStatus("loading");
    setErrorMessage("");
    setBackgroundWarning("");
    setEditingNote(false);
    setNoteDraft("");
    setConfirmingClose(false);
  }, [child.id]);

  const mountedRef = useRef(true);
  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      pendingLoadRef.current = null;
    };
  }, []);

  const load = useCallback(async (opts = {}) => {
    const silent = opts.silent === true;
    const requestedChildId = child.id;

    if (!isOnline) return; // Fase 1 online-only -- tidak pernah fetch/cache selagi offline, lihat render offline di bawah.

    if (loadInFlightRef.current) {
      const pending = { silent, run: () => load(opts) };
      if (!silent || !pendingLoadRef.current || pendingLoadRef.current.silent) {
        pendingLoadRef.current = pending;
      }
      return;
    }
    loadInFlightRef.current = true;

    const hadTrustedData = statusRef.current === "ready";
    if (!silent) {
      setStatus((prev) => (prev === "ready" ? prev : "loading"));
      setErrorMessage("");
    }

    try {
      const res = await api.getCaregiverHandover(child.id);
      if (!mountedRef.current || requestedChildId !== activeChildIdRef.current) return;
      setData(res);
      setStatus("ready");
      setBackgroundWarning("");
    } catch (err) {
      if (!mountedRef.current || requestedChildId !== activeChildIdRef.current) return;

      if (silent && hadTrustedData) {
        // Kegagalan refresh LATAR BELAKANG selagi data terpercaya masih
        // tertampil -- TIDAK PERNAH menimpa data/errorMessage/pesan
        // konflik yang sedang ditampilkan, cuma peringatan non-destruktif.
        setBackgroundWarning(BACKGROUND_REFRESH_WARNING);
        return;
      }
      if (err instanceof ApiError && (err.kind === "forbidden" || err.status === 404)) {
        setStatus("forbidden");
        setErrorMessage(err?.message || "Anda tidak punya akses ke Serah Terima Pengasuh anak ini.");
        return;
      }
      if (err instanceof ApiError && err.kind === "network") {
        // Fetch beneran gagal jaringan (bukan cuma navigator.onLine=false)
        // -- TETAP tidak pernah cache, cukup tampilkan error biasa kalau
        // belum ada data terpercaya.
        if (hadTrustedData) { setBackgroundWarning(BACKGROUND_REFRESH_WARNING); return; }
        setStatus("error");
        setErrorMessage("Nggak ada koneksi internet. Coba lagi nanti.");
        return;
      }
      setStatus("error");
      setErrorMessage(err?.message || "Gagal memuat Serah Terima Pengasuh.");
    } finally {
      loadInFlightRef.current = false;
      const pending = pendingLoadRef.current;
      pendingLoadRef.current = null;
      if (mountedRef.current && pending) pending.run();
    }
  }, [child.id, isOnline]);

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [child.id, isOnline]);

  // Polling 60 detik, CUMA selagi online + komponen ini terpasang +
  // tab kelihatan -- pola SAMA PERSIS pages/MedicationScheduleScreen.jsx.
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

  const handleCreate = async () => {
    if (submitting) return;
    setSubmitting(true);
    setErrorMessage("");
    try {
      const res = await api.createCaregiverHandover(child.id, noteDraft.trim() || null);
      if (!mountedRef.current || child.id !== activeChildIdRef.current) return;
      setData(res);
      setStatus("ready");
      setNoteDraft("");
    } catch (err) {
      if (!mountedRef.current) return;
      if (err instanceof ApiError && err.status === 409) {
        await load();
        setErrorMessage("Sudah ada Serah Terima Pengasuh yang terbuka untuk anak ini. Data sudah diperbarui.");
        return;
      }
      setErrorMessage(err?.message || "Gagal membuat Serah Terima Pengasuh.");
    } finally {
      if (mountedRef.current) setSubmitting(false);
    }
  };

  const handleSaveNote = async () => {
    if (submitting || !data?.handover) return;
    setSubmitting(true);
    setErrorMessage("");
    try {
      const res = await api.updateCaregiverHandover(data.handover.id, noteDraft.trim() || null);
      if (!mountedRef.current || child.id !== activeChildIdRef.current) return;
      setData(res);
      setEditingNote(false);
    } catch (err) {
      if (!mountedRef.current) return;
      if (err instanceof ApiError && err.status === 400) {
        await load();
        setErrorMessage("Serah Terima Pengasuh ini sudah ditutup. Data sudah diperbarui.");
        setEditingNote(false);
        return;
      }
      setErrorMessage(err?.message || "Gagal menyimpan catatan.");
    } finally {
      if (mountedRef.current) setSubmitting(false);
    }
  };

  const handleAcknowledge = async () => {
    if (ackSubmitting || !data?.handover) return;
    setAckSubmitting(true);
    setErrorMessage("");
    try {
      await api.acknowledgeCaregiverHandover(data.handover.id);
      if (!mountedRef.current || child.id !== activeChildIdRef.current) return;
      await load();
    } catch (err) {
      if (!mountedRef.current) return;
      setErrorMessage(err?.message || "Gagal menandai sudah membaca.");
    } finally {
      if (mountedRef.current) setAckSubmitting(false);
    }
  };

  const handleClose = async () => {
    if (closeSubmitting || !data?.handover) return;
    setCloseSubmitting(true);
    setErrorMessage("");
    setConfirmingClose(false);
    try {
      await api.closeCaregiverHandover(data.handover.id);
      if (!mountedRef.current || child.id !== activeChildIdRef.current) return;
      await load();
    } catch (err) {
      if (!mountedRef.current) return;
      setErrorMessage(err?.message || "Gagal menutup Serah Terima Pengasuh.");
    } finally {
      if (mountedRef.current) setCloseSubmitting(false);
    }
  };

  const capabilities = data?.capabilities || null;
  const handover = data?.handover || null;
  const summary = data?.summary || null;
  const acknowledgements = data?.acknowledgements || [];
  const alreadyAcknowledged = handover ? acknowledgements.some((a) => a.user_id === currentUserId) : false;
  // Data terpercaya lagi tertampil TAPI koneksi barusan putus -- tandai
  // usang & nonaktifkan SEMUA mutasi, JANGAN pernah tampilkan seolah
  // ini data yang masih berlaku sekarang (requirement offline).
  const showOutdatedBanner = !isOnline && status === "ready";
  const mutationsDisabled = !isOnline;

  return (
    <div className="fixed inset-0 z-50 bg-void overflow-y-auto">
      <div className="min-h-screen pb-16 px-6 pt-8 max-w-lg mx-auto">
        <div className="flex items-center justify-between mb-1">
          <h1 className="font-display text-2xl text-ink">🤝 Serah Terima Pengasuh</h1>
          <button
            type="button"
            onClick={onClose}
            aria-label="Tutup"
            className="w-9 h-9 rounded-full border border-void-hairline text-ink-muted flex items-center justify-center flex-shrink-0"
          >
            ✕
          </button>
        </div>
        <p className="text-sm text-ink-muted mb-4">{child.nickname || child.name}</p>

        {!isOnline && status !== "ready" && (
          <div className="text-center py-10 px-4">
            <p className="text-3xl mb-3">📡</p>
            <p className="text-ink-faint text-xs">{OFFLINE_MESSAGE}</p>
          </div>
        )}

        {isOnline && status === "loading" && (
          <div className="space-y-3" aria-live="polite" aria-busy="true">
            <p className="text-ink-faint text-sm text-center py-2">Memuat...</p>
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

        {isOnline && status === "error" && (
          <div className="text-center py-6 space-y-3">
            <p className="text-warn text-sm">{errorMessage}</p>
            <button onClick={() => load()} className="px-4 py-2 rounded-lg border border-void-hairline text-ink-muted text-sm font-medium">
              Coba lagi
            </button>
          </div>
        )}

        {(status === "ready" || showOutdatedBanner) && data && (
          <>
            {showOutdatedBanner && (
              <p className="text-[11px] text-warn bg-warn/10 border border-warn/30 rounded-lg px-3 py-2 mb-3">
                {OFFLINE_MESSAGE} Data di bawah mungkin sudah usang.
              </p>
            )}
            {backgroundWarning && (
              <p className="text-[11px] text-ink-faint bg-void border border-void-hairline rounded-lg px-3 py-2 mb-3">
                {backgroundWarning}
              </p>
            )}
            {errorMessage && <p className="text-warn text-xs mb-3">{errorMessage}</p>}

            {!handover && (
              <div className="text-center py-6 px-4">
                <p className="text-3xl mb-3">📭</p>
                <p className="text-ink text-sm font-medium mb-1">Belum ada Serah Terima yang terbuka</p>
                <p className="text-ink-faint text-xs mb-4">
                  Buat Serah Terima buat merangkum 24 jam terakhir untuk caregiver berikutnya.
                </p>
                {capabilities?.can_create && !mutationsDisabled && (
                  <div className="text-left">
                    <textarea
                      value={noteDraft}
                      onChange={(e) => setNoteDraft(e.target.value.slice(0, NOTE_MAX_LEN))}
                      maxLength={NOTE_MAX_LEN}
                      rows={3}
                      placeholder="Catatan buat caregiver berikutnya (opsional)"
                      className="w-full bg-void-card border border-void-hairline rounded-lg px-3 py-2.5 text-sm text-ink mb-3"
                    />
                    <button
                      type="button"
                      onClick={handleCreate}
                      disabled={submitting}
                      className="w-full py-3 rounded-xl2 bg-feed text-white text-sm font-semibold disabled:opacity-50"
                    >
                      {submitting ? "Membuat..." : "Buat Serah Terima"}
                    </button>
                  </div>
                )}
              </div>
            )}

            {handover && summary && (
              <>
                <SectionCard title="ℹ️ Ringkasan">
                  <Row label="Dibuat oleh" value={handover.created_by_name || "—"} />
                  <Row label="Dibuat" value={formatDateTimeWIB(handover.created_at)} />
                  <Row label="Periode" value={`${formatDateTimeWIB(summary.window_start)} – ${formatDateTimeWIB(summary.as_of_at)}`} />
                  <Row label="Status" value={handover.status === "open" ? "Terbuka" : "Ditutup"} />
                  {handover.status === "closed" && handover.closed_by_name && (
                    <Row label="Ditutup oleh" value={handover.closed_by_name} />
                  )}
                </SectionCard>

                <div className="bg-void-card border border-void-hairline rounded-xl2 px-4 py-3 mb-3">
                  <p className="text-xs text-ink-muted">{summary.disclaimer || DISCLAIMER_FALLBACK}</p>
                </div>

                <SectionCard title="📝 Catatan Serah Terima">
                  {!editingNote && (
                    <>
                      <p className="text-[13px] text-ink whitespace-pre-wrap break-words">
                        {handover.note || "Tidak ada catatan."}
                      </p>
                      {capabilities?.can_edit && !mutationsDisabled && (
                        <button
                          type="button"
                          onClick={() => { setNoteDraft(handover.note || ""); setEditingNote(true); }}
                          className="text-xs font-medium text-feed underline underline-offset-2 mt-2"
                        >
                          Ubah catatan
                        </button>
                      )}
                    </>
                  )}
                  {editingNote && (
                    <div>
                      <textarea
                        value={noteDraft}
                        onChange={(e) => setNoteDraft(e.target.value.slice(0, NOTE_MAX_LEN))}
                        maxLength={NOTE_MAX_LEN}
                        rows={3}
                        className="w-full bg-void-card border border-void-hairline rounded-lg px-3 py-2.5 text-sm text-ink mb-2"
                      />
                      <div className="flex gap-2">
                        <button
                          type="button"
                          onClick={() => setEditingNote(false)}
                          className="flex-1 py-2 rounded-lg border border-void-hairline text-ink-muted text-xs font-medium"
                        >
                          Batal
                        </button>
                        <button
                          type="button"
                          onClick={handleSaveNote}
                          disabled={submitting}
                          className="flex-1 py-2 rounded-lg bg-feed text-white text-xs font-semibold disabled:opacity-50"
                        >
                          {submitting ? "Menyimpan..." : "Simpan"}
                        </button>
                      </div>
                    </div>
                  )}
                </SectionCard>

                <FeedingSection feeding={summary.feeding} />
                <SleepSection sleep={summary.sleep} />
                <DiaperSection diaper={summary.diaper} />
                <PumpingSection pumping={summary.pumping} />
                <ActivityMoodSection activityMood={summary.activity_mood} />
                <HealthSection health={summary.health} />
                <MedicationSection medication={summary.medication} />
                <ReminderSection reminders={summary.reminders} />

                <AcknowledgementList acknowledgements={acknowledgements} currentUserId={currentUserId} />

                <div className="bg-void border border-void-hairline rounded-xl2 px-4 py-3 mb-3">
                  <p className="text-[11px] text-ink-faint">{summary.privacy_note}</p>
                </div>

                {mutationsDisabled && (
                  <p className="text-[11px] text-ink-faint mb-4">{OFFLINE_MESSAGE}</p>
                )}

                {!mutationsDisabled && capabilities?.can_acknowledge && (
                  <button
                    type="button"
                    onClick={handleAcknowledge}
                    disabled={ackSubmitting || alreadyAcknowledged}
                    className="w-full py-3 mb-3 rounded-xl2 bg-feed text-white text-sm font-semibold disabled:opacity-50"
                  >
                    {alreadyAcknowledged ? "✓ Sudah ditandai dibaca" : ackSubmitting ? "Menandai..." : "Tandai sudah dibaca"}
                  </button>
                )}

                {!mutationsDisabled && capabilities?.can_close && !confirmingClose && (
                  <button
                    type="button"
                    onClick={() => setConfirmingClose(true)}
                    className="w-full py-2.5 rounded-xl2 border border-void-hairline text-ink-muted text-sm font-medium"
                  >
                    Tutup Serah Terima
                  </button>
                )}
                {!mutationsDisabled && capabilities?.can_close && confirmingClose && (
                  <div className="bg-void-card border border-void-hairline rounded-xl2 px-4 py-3">
                    <p className="text-xs text-ink mb-3">
                      Yakin mau menutup Serah Terima ini? Caregiver baru bisa membuat Serah Terima baru setelahnya.
                    </p>
                    <div className="flex gap-2">
                      <button
                        type="button"
                        onClick={() => setConfirmingClose(false)}
                        className="flex-1 py-2 rounded-lg border border-void-hairline text-ink-muted text-xs font-medium"
                      >
                        Batal
                      </button>
                      <button
                        type="button"
                        onClick={handleClose}
                        disabled={closeSubmitting}
                        className="flex-1 py-2 rounded-lg bg-warn text-white text-xs font-semibold disabled:opacity-50"
                      >
                        {closeSubmitting ? "Menutup..." : "Ya, tutup"}
                      </button>
                    </div>
                  </div>
                )}
              </>
            )}
          </>
        )}
      </div>
    </div>
  );
}
