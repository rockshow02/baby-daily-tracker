import { useEffect, useState } from "react";
import { api, ApiError } from "../api/client";

/**
 * Doctor Consultation Workflow — Phase 1. Alur: pilih periode + section
 * -> preview (server-side, backend TETAP otoritatif buat validasi
 * rentang tanggal & kelayakan section) -> unduh PDF (opsional) ->
 * "Catat Hasil Kunjungan" (buka form kunjungan dokter yang SUDAH ADA,
 * lewat `onRecordVisit`, BUKAN form kedua).
 *
 * SENGAJA online-only (TIDAK ADA cache offline buat preview) — cache
 * yang aman (nggak boleh nyimpen section sensitif/teks transien secara
 * default, nggak boleh lintas anak/user) butuh kompleksitas ekstra yang
 * di luar cakupan Fase 1; kalau offline, layar ini cuma nunjukin pesan
 * "butuh koneksi" dan menonaktifkan preview/PDF — TIDAK PERNAH
 * menyimpan/mengantrekan permintaan ini (lihat backend/docs/DOCTOR_CONSULTATION.md
 * bagian "Offline").
 *
 * Section code DAN status "sensitif"-nya di SECTION_DEFS di bawah HARUS
 * disinkronkan manual sama utils/consultation_report.py:SECTION_CODES/
 * SENSITIVE_SECTIONS di backend (persis pola frontend/src/utils/insightCodes.js
 * vs backend INSIGHT_ALLOWLIST) — backend TETAP validasi otoritatif,
 * daftar ini CUMA buat UI checkbox.
 */
const PERIOD_PRESETS = [
  { key: "7d", label: "7 Hari Terakhir" },
  { key: "14d", label: "14 Hari Terakhir" },
  { key: "30d", label: "30 Hari Terakhir" },
  { key: "custom", label: "Rentang Kustom" },
];

const SECTION_DEFS = [
  { code: "child_summary", label: "Ringkasan Anak", sensitive: false, defaultOn: true },
  { code: "feeding", label: "Menyusui / Makan", sensitive: false, defaultOn: true },
  { code: "sleep", label: "Tidur", sensitive: false, defaultOn: true },
  { code: "diaper", label: "Popok", sensitive: false, defaultOn: true },
  { code: "pumping", label: "Memerah ASI", sensitive: false, defaultOn: false },
  { code: "activity_mood", label: "Aktivitas & Suasana Hati", sensitive: false, defaultOn: false },
  { code: "growth", label: "Pertumbuhan", sensitive: false, defaultOn: true },
  { code: "temperature", label: "Ringkasan Suhu", sensitive: false, defaultOn: true },
  { code: "vaccination", label: "Status Vaksinasi", sensitive: false, defaultOn: true },
  { code: "milestones", label: "Tumbuh Kembang", sensitive: false, defaultOn: true },
  { code: "insights", label: "Ringkasan Smart Insights", sensitive: false, defaultOn: false },
  { code: "illness", label: "Riwayat Sakit", sensitive: true, defaultOn: false },
  { code: "medication", label: "Riwayat Obat", sensitive: true, defaultOn: false },
  { code: "doctor_visits", label: "Kunjungan Dokter Sebelumnya", sensitive: true, defaultOn: false },
  { code: "questions", label: "Pertanyaan untuk Dokter", sensitive: true, defaultOn: false },
  { code: "note", label: "Catatan Tambahan Caregiver", sensitive: true, defaultOn: false },
];

const QUESTIONS_MAX_LEN = 1000;
const NOTE_MAX_LEN = 1000;

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

function todayWibIsoDate() {
  // Perkiraan tanggal WIB dari device (CUMA buat batas maksimal input
  // date picker di UI, bukan sumber kebenaran) — backend TETAP yang
  // menegakkan validasi rentang beneran, lihat docstring modul.
  const wib = new Date(Date.now() + 7 * 60 * 60 * 1000);
  return wib.toISOString().slice(0, 10);
}

export default function DoctorConsultationScreen({ child, onRecordVisit, onClose }) {
  const isOnline = useOnlineStatus();
  const [presetKey, setPresetKey] = useState("7d");
  const [customStart, setCustomStart] = useState("");
  const [customEnd, setCustomEnd] = useState("");
  const [selectedSections, setSelectedSections] = useState(
    () => new Set(SECTION_DEFS.filter((s) => s.defaultOn).map((s) => s.code)),
  );
  const [questions, setQuestions] = useState("");
  const [note, setNote] = useState("");
  const [status, setStatus] = useState("idle"); // idle | loading | ready | error
  const [errorMessage, setErrorMessage] = useState("");
  const [report, setReport] = useState(null);
  const [downloading, setDownloading] = useState(false);
  const [downloadError, setDownloadError] = useState("");
  const [confirmingExport, setConfirmingExport] = useState(false);

  const todayIso = todayWibIsoDate();
  const customRangeError =
    presetKey === "custom" && customStart && customEnd && customEnd < customStart
      ? "Tanggal akhir tidak boleh sebelum tanggal mulai."
      : presetKey === "custom" && customEnd && customEnd > todayIso
        ? "Tanggal akhir tidak boleh di masa depan."
        : presetKey === "custom" && customStart && customEnd &&
            (new Date(customEnd) - new Date(customStart)) / 86400000 + 1 > 90
          ? "Rentang tanggal maksimal 90 hari."
          : "";

  const toggleSection = (code) => {
    setSelectedSections((prev) => {
      const next = new Set(prev);
      if (next.has(code)) next.delete(code);
      else next.add(code);
      return next;
    });
  };

  const selectAllOptional = () => setSelectedSections(new Set(SECTION_DEFS.map((s) => s.code)));
  const clearOptional = () => setSelectedSections(new Set(SECTION_DEFS.filter((s) => s.defaultOn).map((s) => s.code)));

  const buildPeriod = () => {
    if (presetKey === "custom") return { preset: "custom", start_date: customStart, end_date: customEnd };
    return { preset: presetKey };
  };

  const buildPayload = () => {
    const canAddNotes = report?.capabilities ? report.capabilities.can_add_private_notes : true;
    return {
      period: buildPeriod(),
      sections: Array.from(selectedSections),
      questions: canAddNotes ? questions : "",
      additional_note: canAddNotes ? note : "",
    };
  };

  const runPreview = async () => {
    if (!isOnline) return;
    if (presetKey === "custom" && (!customStart || !customEnd || customRangeError)) {
      setStatus("error");
      setErrorMessage(customRangeError || "Isi tanggal mulai dan akhir terlebih dahulu.");
      return;
    }
    setStatus("loading");
    setErrorMessage("");
    try {
      const res = await api.previewDoctorConsultation(child.id, buildPayload());
      setReport(res);
      setStatus("ready");
    } catch (err) {
      setStatus("error");
      setErrorMessage(err?.message || "Gagal membuat pratinjau konsultasi.");
    }
  };

  const handleDownload = async () => {
    if (downloading || !isOnline || !report?.capabilities?.can_export) return;
    setDownloadError("");
    setDownloading(true);
    try {
      const filename = `konsultasi-${(child.nickname || child.name).toLowerCase().replace(/\s+/g, "-")}-${report.period.end_date}.pdf`;
      await api.downloadAuthenticatedPost(api.doctorConsultationPdfUrl(child.id), buildPayload(), filename);
    } catch (err) {
      setDownloadError(err?.message || "Gagal mengunduh PDF.");
    } finally {
      setDownloading(false);
      setConfirmingExport(false);
    }
  };

  const requestDownload = () => {
    // Sumber kebenaran "section sensitif mana yang KEBENERAN kepilih"
    // dari `report.sensitive_sections_included` (dipantulkan backend,
    // lihat routes/doctor_consultation_routes.py) -- BUKAN dihitung
    // ulang dari state `selectedSections` lokal, biar konfirmasi ini
    // selalu cocok sama isi laporan yang beneran mau diunduh.
    const hasSensitive = (report?.sensitive_sections_included || []).length > 0;
    if (hasSensitive && !confirmingExport) {
      setConfirmingExport(true);
      return;
    }
    handleDownload();
  };

  const canAddNotes = report?.capabilities ? report.capabilities.can_add_private_notes : true;
  const canExport = report?.capabilities ? report.capabilities.can_export : true;
  const canRecordVisit = report?.capabilities ? report.capabilities.can_record_visit : true;

  return (
    <div className="fixed inset-0 z-40 bg-void overflow-y-auto">
      <div className="max-w-lg mx-auto px-4 py-4">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-lg font-semibold text-ink">Siapkan Konsultasi</h2>
          <button type="button" onClick={onClose} aria-label="Tutup" className="text-ink-faint text-sm px-2 py-1">
            Tutup
          </button>
        </div>

        {!isOnline && (
          <p role="status" className="text-[11px] text-warn bg-warn/10 border border-warn/30 rounded-lg px-3 py-2 mb-4">
            Butuh koneksi internet untuk membuat pratinjau konsultasi. Unduh PDF juga hanya bisa dilakukan saat online.
          </p>
        )}

        <fieldset className="mb-4" disabled={!isOnline}>
          <legend className="text-xs text-ink-faint font-mono uppercase tracking-wider mb-2">Periode</legend>
          <div className="flex flex-wrap gap-2 mb-2">
            {PERIOD_PRESETS.map((p) => (
              <button
                key={p.key}
                type="button"
                onClick={() => setPresetKey(p.key)}
                aria-pressed={presetKey === p.key}
                className={`px-3 py-1.5 rounded-full text-xs font-medium border ${
                  presetKey === p.key ? "bg-feed/15 border-feed text-feed" : "border-void-hairline text-ink-muted"
                }`}
              >
                {p.label}
              </button>
            ))}
          </div>
          {presetKey === "custom" && (
            <div className="flex gap-2 items-start">
              <label className="flex-1 text-xs text-ink-muted">
                Mulai
                <input
                  type="date"
                  value={customStart}
                  max={todayIso}
                  onChange={(e) => setCustomStart(e.target.value)}
                  className="mt-1 w-full bg-void-card border border-void-hairline rounded-lg px-2 py-1.5 text-sm text-ink"
                />
              </label>
              <label className="flex-1 text-xs text-ink-muted">
                Akhir
                <input
                  type="date"
                  value={customEnd}
                  max={todayIso}
                  onChange={(e) => setCustomEnd(e.target.value)}
                  className="mt-1 w-full bg-void-card border border-void-hairline rounded-lg px-2 py-1.5 text-sm text-ink"
                />
              </label>
            </div>
          )}
          {customRangeError && <p className="text-warn text-xs mt-2">{customRangeError}</p>}
        </fieldset>

        <fieldset className="mb-4" disabled={!isOnline}>
          <legend className="text-xs text-ink-faint font-mono uppercase tracking-wider mb-2">Bagian Laporan</legend>
          <div className="flex gap-2 mb-2">
            <button type="button" onClick={selectAllOptional} className="text-xs text-feed underline underline-offset-2">
              Pilih semua
            </button>
            <button type="button" onClick={clearOptional} className="text-xs text-ink-faint underline underline-offset-2">
              Bagian dasar saja
            </button>
          </div>
          <div className="space-y-1.5">
            {SECTION_DEFS.map((s) => {
              const inputId = `consult-section-${s.code}`;
              return (
                <div key={s.code} className="flex items-center gap-2">
                  <input
                    id={inputId}
                    type="checkbox"
                    checked={selectedSections.has(s.code)}
                    onChange={() => toggleSection(s.code)}
                    className="h-4 w-4"
                  />
                  <label htmlFor={inputId} className="text-sm text-ink flex-1">
                    {s.label}
                  </label>
                  {s.sensitive && (
                    <span className="text-[10px] font-medium text-warn bg-warn/10 border border-warn/30 rounded-full px-2 py-0.5">
                      Sensitif
                    </span>
                  )}
                </div>
              );
            })}
          </div>
        </fieldset>

        {canAddNotes ? (
          <>
            <label className="block mb-3 text-xs text-ink-muted" htmlFor="consult-questions">
              Pertanyaan untuk dokter (opsional, tidak disimpan permanen)
              <textarea
                id="consult-questions"
                value={questions}
                maxLength={QUESTIONS_MAX_LEN}
                onChange={(e) => setQuestions(e.target.value)}
                disabled={!isOnline}
                rows={3}
                className="mt-1 w-full bg-void-card border border-void-hairline rounded-lg px-2 py-1.5 text-sm text-ink"
              />
              <span className="text-[10px] text-ink-faint">{questions.length}/{QUESTIONS_MAX_LEN}</span>
            </label>
            <label className="block mb-4 text-xs text-ink-muted" htmlFor="consult-note">
              Catatan tambahan (opsional, tidak disimpan permanen)
              <textarea
                id="consult-note"
                value={note}
                maxLength={NOTE_MAX_LEN}
                onChange={(e) => setNote(e.target.value)}
                disabled={!isOnline}
                rows={3}
                className="mt-1 w-full bg-void-card border border-void-hairline rounded-lg px-2 py-1.5 text-sm text-ink"
              />
              <span className="text-[10px] text-ink-faint">{note.length}/{NOTE_MAX_LEN}</span>
            </label>
          </>
        ) : (
          <p className="text-[11px] text-ink-faint mb-4">
            Peran Anda hanya bisa melihat pratinjau, tidak bisa menambahkan pertanyaan/catatan atau mengunduh PDF.
          </p>
        )}

        <button
          type="button"
          onClick={runPreview}
          disabled={!isOnline || status === "loading"}
          className="w-full py-3 mb-4 rounded-xl2 bg-feed text-white text-sm font-semibold disabled:opacity-50"
        >
          {status === "loading" ? "Membuat pratinjau..." : "Buat Pratinjau"}
        </button>

        {status === "error" && (
          <div role="alert" className="text-center py-4 space-y-2 mb-4">
            <p className="text-warn text-sm">{errorMessage}</p>
            <button type="button" onClick={runPreview} className="px-4 py-2 rounded-lg border border-void-hairline text-ink-muted text-sm font-medium">
              Coba lagi
            </button>
          </div>
        )}

        {status === "ready" && report && (
          <div aria-live="polite">
            <div className="bg-void-card border border-void-hairline rounded-xl2 px-4 py-3 mb-4">
              <p className="text-sm text-ink font-medium mb-1">
                {report.child_display_name} · {report.period.start_date} s/d {report.period.end_date}
              </p>
              <p className="text-[11px] text-ink-faint">{report.disclaimer}</p>
            </div>

            {report.sensitive_sections_included.length > 0 && (
              <p className="text-[11px] text-warn bg-warn/10 border border-warn/30 rounded-lg px-3 py-2 mb-4">
                Laporan ini menyertakan bagian sensitif: {report.sensitive_sections_included.join(", ")}.
              </p>
            )}

            {Object.entries(report.sections).map(([code, section]) => {
              const def = SECTION_DEFS.find((s) => s.code === code);
              return (
                <div key={code} className="mb-3">
                  <p className="text-xs text-ink-faint font-mono uppercase tracking-wider mb-1">
                    {def ? def.label : code}
                  </p>
                  <pre className="text-[11px] text-ink-muted bg-void-card border border-void-hairline rounded-lg p-2 overflow-x-auto whitespace-pre-wrap break-words">
                    {JSON.stringify(section, null, 2)}
                  </pre>
                </div>
              );
            })}

            {canExport && (
              <>
                {confirmingExport && (
                  <div role="alertdialog" aria-label="Konfirmasi privasi" className="bg-warn/10 border border-warn/30 rounded-xl2 px-3 py-3 mb-3">
                    <p className="text-xs text-ink mb-2">
                      PDF ini akan berisi bagian sensitif yang Anda pilih. Lanjutkan unduh?
                    </p>
                    <div className="flex gap-2">
                      <button type="button" onClick={() => setConfirmingExport(false)} className="px-3 py-1.5 rounded-lg border border-void-hairline text-ink-muted text-xs font-medium">
                        Batal
                      </button>
                      <button type="button" onClick={handleDownload} className="px-3 py-1.5 rounded-lg bg-warn text-white text-xs font-semibold">
                        Ya, unduh
                      </button>
                    </div>
                  </div>
                )}
                <button
                  type="button"
                  onClick={requestDownload}
                  disabled={!isOnline || downloading}
                  className="w-full py-3 mb-3 rounded-xl2 border border-feed text-feed text-sm font-semibold disabled:opacity-50"
                >
                  {downloading ? "Mengunduh PDF..." : "Unduh PDF"}
                </button>
                {downloadError && <p className="text-warn text-xs mb-3">{downloadError}</p>}
              </>
            )}

            {canRecordVisit && (
              <button
                type="button"
                onClick={onRecordVisit}
                className="w-full py-3 mb-2 rounded-xl2 bg-void-card border border-void-hairline text-ink text-sm font-semibold"
              >
                Catat Hasil Kunjungan
              </button>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
