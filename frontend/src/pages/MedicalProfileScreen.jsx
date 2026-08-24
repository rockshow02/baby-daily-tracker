import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError } from "../api/client";
import {
  ALLERGY_TYPES, BLOOD_TYPES, CONDITION_STATUSES, describeAllergyType, describeBloodType,
  describeConditionStatus, describeSeverity, formatDateTimeWIB, MEDICAL_PROFILE_LIMITS, SEVERITY_LEVELS,
} from "../utils/medicalProfile";
import { canWrite } from "../utils/roles";

const LEAST_PRIVILEGE_CAPABILITIES = {
  can_view_medical_profile: false, can_edit_medical_profile: false,
  can_preview_emergency_card: false, can_export_emergency_card: false,
};

const SENSITIVE_NOTICE =
  "Halaman ini berisi data medis dan kontak yang sangat pribadi. Hanya Anda dan caregiver lain yang " +
  "ditambahkan sebagai Pemilik/Editor yang bisa melihatnya — jangan tunjukkan layar ini ke orang lain " +
  "kecuali memang diperlukan.";

const OFFLINE_MESSAGE =
  "Profil medis & Kartu Darurat cuma bisa diakses saat online — data ini terlalu sensitif untuk " +
  "disimpan di perangkat ini. Sambungkan ke internet dulu untuk melihat atau mengubahnya.";

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

function emptyAllergy() {
  return { type: "drug", allergen: "", reaction: "", severity: "", confirmed_by_professional: false };
}

function emptyCondition() {
  return { condition_name: "", diagnosed_year: "", status: "", note: "" };
}

/** Form field yang diketik user -> payload PUT (string kosong -> null, angka tahun -> int|null). */
function toAllergyPayload(a) {
  return {
    type: a.type,
    allergen: a.allergen.trim(),
    reaction: a.reaction.trim() || null,
    severity: a.severity || null,
    confirmed_by_professional: a.confirmed_by_professional === true,
  };
}

function toConditionPayload(c) {
  const year = c.diagnosed_year === "" || c.diagnosed_year == null ? null : Number(c.diagnosed_year);
  return {
    condition_name: c.condition_name.trim(),
    diagnosed_year: Number.isFinite(year) ? year : null,
    status: c.status || null,
    note: c.note.trim() || null,
  };
}

function profileToFormState(profile) {
  return {
    blood_type: profile?.blood_type || "",
    allergies: (profile?.allergies || []).map((a) => ({
      type: a.type, allergen: a.allergen, reaction: a.reaction || "",
      severity: a.severity || "", confirmed_by_professional: a.confirmed_by_professional === true,
    })),
    conditions: (profile?.conditions || []).map((c) => ({
      condition_name: c.condition_name, diagnosed_year: c.diagnosed_year ?? "",
      status: c.status || "", note: c.note || "",
    })),
    primary_doctor_name: profile?.primary_doctor_name || "",
    primary_clinic_name: profile?.primary_clinic_name || "",
    primary_clinic_phone: profile?.primary_clinic_phone || "",
    emergency_contact_name: profile?.emergency_contact_name || "",
    emergency_contact_relationship: profile?.emergency_contact_relationship || "",
    emergency_contact_phone: profile?.emergency_contact_phone || "",
    emergency_instructions: profile?.emergency_instructions || "",
  };
}

function AllergyEditor({ allergies, onChange }) {
  const update = (i, patch) => onChange(allergies.map((a, idx) => (idx === i ? { ...a, ...patch } : a)));
  const remove = (i) => onChange(allergies.filter((_, idx) => idx !== i));
  const add = () => {
    if (allergies.length >= MEDICAL_PROFILE_LIMITS.MAX_ALLERGIES) return;
    onChange([...allergies, emptyAllergy()]);
  };

  return (
    <div className="mb-5">
      <p className="text-xs text-ink-faint uppercase tracking-wider mb-2">Alergi</p>
      {allergies.length === 0 && <p className="text-xs text-ink-faint mb-2">Belum ada alergi ditambahkan.</p>}
      {allergies.map((a, i) => (
        <div key={i} className="bg-void border border-void-hairline rounded-lg p-3 mb-2">
          <div className="grid grid-cols-2 gap-2 mb-2">
            <select
              aria-label={`Jenis alergi ke-${i + 1}`}
              value={a.type}
              onChange={(e) => update(i, { type: e.target.value })}
              className="bg-void-card border border-void-hairline rounded-lg px-2.5 py-2 text-xs text-ink"
            >
              {ALLERGY_TYPES.map((t) => <option key={t} value={t}>{describeAllergyType(t)}</option>)}
            </select>
            <select
              aria-label={`Tingkat keparahan alergi ke-${i + 1}`}
              value={a.severity}
              onChange={(e) => update(i, { severity: e.target.value })}
              className="bg-void-card border border-void-hairline rounded-lg px-2.5 py-2 text-xs text-ink"
            >
              <option value="">Tingkat keparahan (opsional)</option>
              {SEVERITY_LEVELS.map((s) => <option key={s} value={s}>{describeSeverity(s)}</option>)}
            </select>
          </div>
          <input
            aria-label={`Nama alergen ke-${i + 1}`}
            type="text"
            value={a.allergen}
            onChange={(e) => update(i, { allergen: e.target.value })}
            maxLength={MEDICAL_PROFILE_LIMITS.ALLERGEN_NAME_MAX_LEN}
            placeholder="Nama alergen (wajib), cth. Amoxicillin"
            className="w-full bg-void-card border border-void-hairline rounded-lg px-2.5 py-2 text-xs text-ink mb-2"
            required
          />
          <input
            aria-label={`Reaksi alergi ke-${i + 1}`}
            type="text"
            value={a.reaction}
            onChange={(e) => update(i, { reaction: e.target.value })}
            maxLength={MEDICAL_PROFILE_LIMITS.REACTION_MAX_LEN}
            placeholder="Reaksi (opsional), cth. Ruam kulit"
            className="w-full bg-void-card border border-void-hairline rounded-lg px-2.5 py-2 text-xs text-ink mb-2"
          />
          <label className="flex items-center gap-2 text-[11px] text-ink-muted mb-2">
            <input
              type="checkbox"
              checked={a.confirmed_by_professional === true}
              onChange={(e) => update(i, { confirmed_by_professional: e.target.checked })}
            />
            Sudah dikonfirmasi tenaga medis
          </label>
          <button type="button" onClick={() => remove(i)} className="text-[11px] text-warn font-medium">
            Hapus alergi ini
          </button>
        </div>
      ))}
      {allergies.length < MEDICAL_PROFILE_LIMITS.MAX_ALLERGIES && (
        <button type="button" onClick={add} className="text-xs font-medium text-feed underline underline-offset-2">
          + Tambah alergi
        </button>
      )}
    </div>
  );
}

function ConditionEditor({ conditions, onChange }) {
  const update = (i, patch) => onChange(conditions.map((c, idx) => (idx === i ? { ...c, ...patch } : c)));
  const remove = (i) => onChange(conditions.filter((_, idx) => idx !== i));
  const add = () => {
    if (conditions.length >= MEDICAL_PROFILE_LIMITS.MAX_CONDITIONS) return;
    onChange([...conditions, emptyCondition()]);
  };

  return (
    <div className="mb-5">
      <p className="text-xs text-ink-faint uppercase tracking-wider mb-2">Kondisi Medis Penting</p>
      {conditions.length === 0 && <p className="text-xs text-ink-faint mb-2">Belum ada kondisi medis ditambahkan.</p>}
      {conditions.map((c, i) => (
        <div key={i} className="bg-void border border-void-hairline rounded-lg p-3 mb-2">
          <input
            aria-label={`Nama kondisi medis ke-${i + 1}`}
            type="text"
            value={c.condition_name}
            onChange={(e) => update(i, { condition_name: e.target.value })}
            maxLength={MEDICAL_PROFILE_LIMITS.CONDITION_NAME_MAX_LEN}
            placeholder="Nama kondisi (wajib), cth. Asma"
            className="w-full bg-void-card border border-void-hairline rounded-lg px-2.5 py-2 text-xs text-ink mb-2"
            required
          />
          <div className="grid grid-cols-2 gap-2 mb-2">
            <select
              aria-label={`Status kondisi medis ke-${i + 1}`}
              value={c.status}
              onChange={(e) => update(i, { status: e.target.value })}
              className="bg-void-card border border-void-hairline rounded-lg px-2.5 py-2 text-xs text-ink"
            >
              <option value="">Status (opsional)</option>
              {CONDITION_STATUSES.map((s) => <option key={s} value={s}>{describeConditionStatus(s)}</option>)}
            </select>
            <input
              aria-label={`Tahun diagnosis kondisi medis ke-${i + 1}`}
              type="number"
              value={c.diagnosed_year}
              onChange={(e) => update(i, { diagnosed_year: e.target.value })}
              placeholder="Tahun diagnosis"
              className="bg-void-card border border-void-hairline rounded-lg px-2.5 py-2 text-xs text-ink"
            />
          </div>
          <input
            aria-label={`Catatan kondisi medis ke-${i + 1}`}
            type="text"
            value={c.note}
            onChange={(e) => update(i, { note: e.target.value })}
            maxLength={MEDICAL_PROFILE_LIMITS.CONDITION_NOTE_MAX_LEN}
            placeholder="Catatan (opsional)"
            className="w-full bg-void-card border border-void-hairline rounded-lg px-2.5 py-2 text-xs text-ink mb-2"
          />
          <button type="button" onClick={() => remove(i)} className="text-[11px] text-warn font-medium">
            Hapus kondisi ini
          </button>
        </div>
      ))}
      {conditions.length < MEDICAL_PROFILE_LIMITS.MAX_CONDITIONS && (
        <button type="button" onClick={add} className="text-xs font-medium text-feed underline underline-offset-2">
          + Tambah kondisi medis
        </button>
      )}
    </div>
  );
}

// Pesan Indonesia AMAN dipakai persis sama saat backend balas 409
// ("digest snapshot beda dari yang barusan dibangun ulang" --
// utils/emergency_card_snapshot.py) -- dipakai sebagai FALLBACK kalau
// karena suatu alasan respons error tidak menyertakan pesan sendiri;
// backend SELALU menyertakan pesannya sendiri di praktiknya, ini murni
// jaring pengaman.
const STALE_SNAPSHOT_MESSAGE =
  "Data Kartu Darurat berubah sejak pratinjau dibuat. Muat ulang pratinjau sebelum mengunduh PDF.";
const LOCAL_STALE_MESSAGE =
  "Profil medis sudah diubah sejak pratinjau ini dibuat. Muat ulang pratinjau sebelum mengunduh PDF.";
// Status HTTP yang SEMUANYA berarti "token pratinjau/snapshot ini tidak
// bisa lagi dipercaya buat mengunduh PDF -- WAJIB pratinjau ulang":
// 409 = digest cocok tapi datanya sudah berubah (kasus utama defect
// ini), 400/403 = token hilang/rusak/kedaluwarsa/salah anak/salah user
// (lihat backend/routes/medical_profile_routes.py). SEMUANYA dapat
// perlakuan UI yang SAMA (bukan error generik biasa) -- requirement:
// "Expired/invalid snapshot responses also require a fresh preview."
const STATUSES_REQUIRING_FRESH_PREVIEW = new Set([400, 403, 409]);

/**
 * Emergency Card -- preview manusiawi + unduh PDF. DUA lapis proteksi
 * konsistensi preview<->PDF (lihat backend/docs/MEDICAL_PROFILE.md
 * bagian "Konsistensi snapshot preview -> PDF (token bertanda tangan)"
 * buat detail lengkap kenapa 1 lapis frontend SAJA tidak cukup -- bug
 * review Agustus 2026):
 *
 *   1. LOKAL (cepat, UX doang): `editGenerationRef` (dinaikkan tiap
 *      PUT/review profil sukses LEWAT INSTANCE FRONTEND INI) --
 *      `snapshotIsFresh` jadi false SEKETIKA tanpa perlu bolak-balik ke
 *      server kalau user SENDIRI baru saja mengedit profil.
 *   2. SERVER (otoritatif, wajib): `activeSnapshot.snapshotToken` --
 *      token bertanda tangan dari preview, WAJIB dikirim balik ke
 *      endpoint PDF apa adanya. Server yang MEMBUKTIKAN kecocokan
 *      lewat digest (BUKAN cuma dipercaya klien) -- melindungi dari
 *      perubahan yang TIDAK BISA diketahui frontend ini sama sekali
 *      (caregiver LAIN mengedit/mereview profil, jadwal obat berubah)
 *      -- respons 409/400/403 dari lapis ini ditangani sebagai "harus
 *      pratinjau ulang", TIDAK PERNAH diam-diam merender PDF yang beda
 *      dari yang sudah dilihat & dikonfirmasi user.
 *
 * Kedua snapshot (report + token) SELALU diperbarui BERSAMAAN, atomik,
 * 1 `setState` (lihat `runPreview`) -- tidak pernah ada state di mana
 * report baru tapi token lama (atau sebaliknya).
 */
function EmergencyCardModal({ child, capabilities, editGenerationRef, onClose }) {
  const [status, setStatus] = useState("idle"); // idle|loading|ready|error
  const [errorMessage, setErrorMessage] = useState("");
  const [activeSnapshot, setActiveSnapshot] = useState(null); // { report, snapshotToken, editGeneration }
  const [serverStaleMessage, setServerStaleMessage] = useState(null);
  const [pdfSubmitting, setPdfSubmitting] = useState(false);
  const requestSeqRef = useRef(0);
  const mountedRef = useRef(true);
  useEffect(() => {
    mountedRef.current = true;
    return () => { mountedRef.current = false; };
  }, []);

  const runPreview = useCallback(async () => {
    if (status === "loading") return; // proteksi klik ganda
    const mySeq = ++requestSeqRef.current;
    setStatus("loading");
    setErrorMessage("");
    try {
      const { snapshot_token: snapshotToken, ...report } = await api.previewEmergencyCard(child.id);
      if (!mountedRef.current || mySeq !== requestSeqRef.current) return; // respons basi (out-of-order) -- BUKAN yang terbaru, dibuang
      // Report + token diganti BERSAMAAN, 1 setState -- "atomik" (requirement: "Reloading preview replaces both report and token atomically").
      setActiveSnapshot({ report, snapshotToken, editGeneration: editGenerationRef.current });
      setServerStaleMessage(null);
      setStatus("ready");
    } catch (err) {
      if (!mountedRef.current || mySeq !== requestSeqRef.current) return;
      if (err instanceof ApiError && err.kind === "forbidden") {
        setStatus("error");
        setErrorMessage(err.message || "Anda tidak punya akses ke Kartu Darurat ini.");
        return;
      }
      setStatus("error");
      setErrorMessage(err?.message || "Gagal memuat pratinjau Kartu Darurat.");
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [child.id, status]);

  useEffect(() => {
    runPreview();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [child.id]);

  const snapshotIsFresh =
    !!activeSnapshot?.snapshotToken && activeSnapshot.editGeneration === editGenerationRef.current;
  const isStale = !snapshotIsFresh || !!serverStaleMessage;
  const staleMessage = serverStaleMessage || (!snapshotIsFresh ? LOCAL_STALE_MESSAGE : null);

  const handleDownload = async () => {
    if (!snapshotIsFresh || pdfSubmitting) return;
    if (!window.confirm(
      "Kartu ini berisi data medis dan kontak darurat yang sangat pribadi. Unduh PDF sekarang?",
    )) {
      return;
    }
    setPdfSubmitting(true);
    setErrorMessage("");
    try {
      const filename = `kartu-darurat-${(child.nickname || child.name || "anak").toLowerCase().replace(/\s+/g, "-")}.pdf`;
      // `snapshot_token` APA ADANYA dari preview yang aktif -- endpoint
      // PDF membangun ulang laporan pakai TIMESTAMP di dalam token itu
      // sendiri dan membandingkan digest-nya server-side; body JAMAK
      // KOSONG (`{}`) yang dipakai SEBELUM perbaikan ini TIDAK PERNAH
      // dikirim lagi -- lihat backend/docs/MEDICAL_PROFILE.md.
      await api.downloadAuthenticatedPost(
        api.emergencyCardPdfUrl(child.id), { snapshot_token: activeSnapshot.snapshotToken }, filename,
      );
      if (!mountedRef.current) return;
    } catch (err) {
      if (!mountedRef.current) return;
      if (STATUSES_REQUIRING_FRESH_PREVIEW.has(err?.status)) {
        setServerStaleMessage(err.message || STALE_SNAPSHOT_MESSAGE);
      } else {
        setErrorMessage(err?.message || "Gagal mengunduh PDF Kartu Darurat.");
      }
    } finally {
      if (mountedRef.current) setPdfSubmitting(false);
    }
  };

  const report = activeSnapshot?.report;

  return (
    <div className="fixed inset-0 z-[70] flex items-end sm:items-center sm:justify-center">
      <div className="absolute inset-0 bg-black/60" onClick={onClose} />
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="emergency-card-title"
        className="relative w-full sm:max-w-lg bg-void-card border-t sm:border border-void-hairline rounded-t-xl2 sm:rounded-xl2 p-6 pb-8 max-h-[88vh] overflow-y-auto"
      >
        <div className="flex items-center justify-between mb-4">
          <h2 id="emergency-card-title" className="font-display text-2xl text-ink">🚑 Kartu Darurat</h2>
          <button type="button" onClick={onClose} aria-label="Tutup" className="w-9 h-9 rounded-full border border-void-hairline text-ink-muted">✕</button>
        </div>

        {status === "loading" && <p className="text-ink-faint text-sm text-center py-8">Memuat pratinjau...</p>}

        {status === "error" && (
          <div className="text-center py-6 space-y-3">
            <p className="text-warn text-sm">{errorMessage}</p>
            <button onClick={runPreview} className="px-4 py-2 rounded-lg border border-void-hairline text-ink-muted text-sm font-medium">
              Coba lagi
            </button>
          </div>
        )}

        {status === "ready" && report && (
          <div className="space-y-4">
            {isStale && (
              <div className="text-[11px] text-warn bg-warn/10 border border-warn/30 rounded-lg px-3 py-2 space-y-1.5">
                <p>{staleMessage}</p>
                <button
                  type="button"
                  onClick={runPreview}
                  className="text-warn font-semibold underline underline-offset-2"
                >
                  Muat ulang pratinjau
                </button>
              </div>
            )}
            <div className="bg-void border border-void-hairline rounded-xl2 px-4 py-3">
              <p className="text-sm text-ink font-semibold">{report.child_display_name}</p>
              <p className="text-[11px] text-ink-faint">Lahir {report.birth_date} · Usia saat ini {report.age_now}</p>
              <p className="text-[11px] text-ink-faint mt-1">Golongan darah: <span className="text-ink">{report.blood_type_label}</span></p>
            </div>

            <div>
              <p className="text-xs text-ink-faint uppercase tracking-wider mb-1.5">Alergi</p>
              {report.allergies.length === 0 ? (
                <p className="text-xs text-ink-faint">Tidak ada alergi tercatat.</p>
              ) : (
                report.allergies.map((a, i) => (
                  <p key={i} className="text-xs text-ink mb-1">
                    {describeAllergyType(a.type)} · <span className="font-medium">{a.allergen}</span>
                    {a.severity && ` (${describeSeverity(a.severity)})`}
                    {a.reaction ? ` — ${a.reaction}` : ""}
                  </p>
                ))
              )}
            </div>

            <div>
              <p className="text-xs text-ink-faint uppercase tracking-wider mb-1.5">Kondisi Medis Penting</p>
              {report.conditions.length === 0 ? (
                <p className="text-xs text-ink-faint">Tidak ada kondisi medis penting tercatat.</p>
              ) : (
                report.conditions.map((c, i) => (
                  <p key={i} className="text-xs text-ink mb-1">
                    <span className="font-medium">{c.condition_name}</span> ({describeConditionStatus(c.status)})
                  </p>
                ))
              )}
            </div>

            <div>
              <p className="text-xs text-ink-faint uppercase tracking-wider mb-1.5">Obat Rutin Saat Ini</p>
              {report.regular_medications.length === 0 ? (
                <p className="text-xs text-ink-faint">Tidak ada obat rutin aktif tercatat.</p>
              ) : (
                report.regular_medications.map((m, i) => (
                  <p key={i} className="text-xs text-ink mb-1">
                    {m.medication_name}{m.dose ? ` · ${m.dose}` : ""}{m.times_of_day?.length ? ` · ${m.times_of_day.join(", ")}` : ""}
                  </p>
                ))
              )}
            </div>

            <div>
              <p className="text-xs text-ink-faint uppercase tracking-wider mb-1.5">Kontak Medis & Darurat</p>
              <p className="text-xs text-ink">Dokter: {report.primary_doctor_name || "-"}</p>
              <p className="text-xs text-ink">Klinik/RS: {report.primary_clinic_name || "-"}</p>
              <p className="text-xs text-ink">Telepon klinik: {report.primary_clinic_phone || "-"}</p>
              <p className="text-xs text-ink mt-1.5">Kontak darurat: {report.emergency_contact_name || "-"} ({report.emergency_contact_relationship || "-"})</p>
              <p className="text-xs text-ink">Telepon: {report.emergency_contact_phone || "-"}</p>
            </div>

            {report.emergency_instructions && (
              <div>
                <p className="text-xs text-ink-faint uppercase tracking-wider mb-1.5">Instruksi Darurat</p>
                <p className="text-xs text-ink whitespace-pre-wrap">{report.emergency_instructions}</p>
              </div>
            )}

            <p className="text-[11px] text-ink-faint">
              {report.last_reviewed_at
                ? `Terakhir diperiksa ulang: ${formatDateTimeWIB(report.last_reviewed_at)}${report.last_reviewed_by_name ? ` oleh ${report.last_reviewed_by_name}` : ""}`
                : "Belum pernah ditandai diperiksa ulang."}
            </p>

            <div className="bg-void border border-void-hairline rounded-lg px-3 py-2">
              <p className="text-[11px] text-ink-muted">{report.disclaimer}</p>
              <p className="text-[11px] text-warn mt-1">{report.privacy_note}</p>
            </div>

            {errorMessage && <p className="text-warn text-xs">{errorMessage}</p>}

            {capabilities.can_export_emergency_card && (
              <button
                type="button"
                onClick={handleDownload}
                disabled={isStale || pdfSubmitting}
                className="w-full py-3 rounded-xl2 bg-feed text-white text-sm font-semibold disabled:opacity-50"
              >
                {pdfSubmitting ? "Menyiapkan PDF..." : "Unduh PDF"}
              </button>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

/**
 * "🩺 Profil Medis & Kartu Darurat" — Child Medical Profile & Emergency
 * Card Phase 1. Lihat backend/docs/MEDICAL_PROFILE.md buat kontrak
 * lengkapnya. Dibuka sebagai overlay dari HealthScreen (tab Dokter),
 * pola SAMA PERSIS DoctorConsultationScreen.jsx.
 *
 * ONLINE-ONLY SENGAJA (lihat dokumen) -- TIDAK ADA cache offline sama
 * sekali (TIDAK PERNAH localStorage/IndexedDB/sessionStorage) buat data
 * ini, beda dari ReminderScreen/MedicationScheduleScreen. Kalau offline,
 * layar ini cuma nunjukin pesan jelas & menonaktifkan semua aksi.
 *
 * LEAST-PRIVILEGE: `capabilities` SELALU mulai dari semua-false sampai
 * GET profil pertama berhasil (server yang bilang APA yang boleh),
 * PERSIS pola DoctorConsultationScreen.jsx.
 */
export default function MedicalProfileScreen({ child, currentUserId, onClose }) {
  const isOnline = useOnlineStatus();
  const [status, setStatus] = useState("loading"); // loading|ready|forbidden|error|offline
  const [profile, setProfile] = useState(null);
  const [capabilities, setCapabilities] = useState(LEAST_PRIVILEGE_CAPABILITIES);
  const [errorMessage, setErrorMessage] = useState("");
  const [mode, setMode] = useState("view"); // view|edit
  const [form, setForm] = useState(profileToFormState(null));
  const [formError, setFormError] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [reviewSubmitting, setReviewSubmitting] = useState(false);
  const [showEmergencyCard, setShowEmergencyCard] = useState(false);

  // Dinaikkan tiap PUT/review sukses -- dipakai EmergencyCardModal buat
  // tahu "profil ini sudah diubah sejak preview diambil" (lihat
  // docstring EmergencyCardModal di atas).
  const editGenerationRef = useRef(0);

  const activeChildIdRef = useRef(child.id);
  useEffect(() => { activeChildIdRef.current = child.id; }, [child.id]);
  const mountedRef = useRef(true);
  useEffect(() => {
    mountedRef.current = true;
    return () => { mountedRef.current = false; };
  }, []);

  const load = useCallback(async () => {
    if (!isOnline) {
      setStatus("offline");
      return;
    }
    const requestedChildId = child.id;
    setStatus("loading");
    setErrorMessage("");
    try {
      const res = await api.getMedicalProfile(child.id);
      if (!mountedRef.current || requestedChildId !== activeChildIdRef.current) return;
      setProfile(res.profile);
      setCapabilities(res.capabilities);
      setForm(profileToFormState(res.profile));
      setStatus("ready");
    } catch (err) {
      if (!mountedRef.current || requestedChildId !== activeChildIdRef.current) return;
      if (err instanceof ApiError && err.kind === "network") {
        setStatus("offline");
        return;
      }
      if (err instanceof ApiError && err.kind === "forbidden") {
        setStatus("forbidden");
        setErrorMessage(err.message || "Anda tidak punya akses ke profil medis anak ini.");
        return;
      }
      setStatus("error");
      setErrorMessage(err?.message || "Gagal memuat profil medis.");
    }
  }, [child.id, isOnline]);

  // Ganti anak (ATAUPUN online/offline berubah) -- bersihkan state PROFIL
  // SEBELUM fetch baru mulai (requirement: "clear profile state
  // immediately when switching children"), biar transisi Owner-anak ->
  // Viewer-anak (atau sebaliknya) TIDAK PERNAH sempat menampilkan data
  // anak sebelumnya di bawah konteks anak yang baru barang sesaat pun.
  useEffect(() => {
    setProfile(null);
    setCapabilities(LEAST_PRIVILEGE_CAPABILITIES);
    setForm(profileToFormState(null));
    setMode("view");
    setShowEmergencyCard(false);
    editGenerationRef.current = 0;
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [child.id, isOnline]);

  // Tutup layar ATAUPUN unmount -- bersihkan state profil dari memori
  // (requirement: "clear profile state immediately when... closing the
  // screen") -- TIDAK PERNAH ada state medis yang nyangkut di komponen
  // yang sudah nggak ditampilkan.
  useEffect(() => () => {
    setProfile(null);
    setForm(profileToFormState(null));
  }, []);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setSubmitting(true);
    setFormError("");
    try {
      const payload = {
        blood_type: form.blood_type || null,
        allergies: form.allergies.map(toAllergyPayload),
        conditions: form.conditions.map(toConditionPayload),
        primary_doctor_name: form.primary_doctor_name.trim() || null,
        primary_clinic_name: form.primary_clinic_name.trim() || null,
        primary_clinic_phone: form.primary_clinic_phone.trim() || null,
        emergency_contact_name: form.emergency_contact_name.trim() || null,
        emergency_contact_relationship: form.emergency_contact_relationship.trim() || null,
        emergency_contact_phone: form.emergency_contact_phone.trim() || null,
        emergency_instructions: form.emergency_instructions.trim() || null,
      };
      const res = await api.updateMedicalProfile(child.id, payload);
      setProfile(res.profile);
      setCapabilities(res.capabilities);
      setForm(profileToFormState(res.profile));
      editGenerationRef.current += 1;
      setMode("view");
    } catch (err) {
      setFormError(err?.message || "Gagal menyimpan profil medis.");
    } finally {
      setSubmitting(false);
    }
  };

  const handleReview = async () => {
    setReviewSubmitting(true);
    setErrorMessage("");
    try {
      const res = await api.reviewMedicalProfile(child.id);
      setProfile(res.profile);
      editGenerationRef.current += 1;
    } catch (err) {
      setErrorMessage(err?.message || "Gagal menandai profil sudah diperiksa ulang.");
    } finally {
      setReviewSubmitting(false);
    }
  };

  const canEdit = capabilities.can_edit_medical_profile && canWrite(child.role);

  return (
    <div className="fixed inset-0 z-50 bg-void overflow-y-auto">
      <div className="min-h-screen pb-16 px-6 pt-8 max-w-lg mx-auto">
        <div className="flex items-center justify-between mb-1">
          <h1 className="font-display text-3xl text-ink">🩺 Profil Medis & Kartu Darurat</h1>
          <button type="button" onClick={onClose} aria-label="Tutup" className="w-9 h-9 rounded-full border border-void-hairline text-ink-muted flex items-center justify-center flex-shrink-0">✕</button>
        </div>
        <p className="text-sm text-ink-muted mb-4">{child.nickname || child.name}</p>

        <div className="bg-void border border-void-hairline rounded-xl2 px-4 py-3 mb-4">
          <p className="text-xs text-ink-muted">{SENSITIVE_NOTICE}</p>
        </div>

        {status === "offline" && (
          <div className="text-center py-10 px-4">
            <p className="text-3xl mb-3">📡</p>
            <p className="text-ink text-sm font-medium mb-1">Butuh koneksi internet</p>
            <p className="text-ink-faint text-xs">{OFFLINE_MESSAGE}</p>
          </div>
        )}

        {status === "loading" && (
          <div className="space-y-3" aria-live="polite" aria-busy="true">
            <p className="text-ink-faint text-sm text-center py-2">Memuat profil medis...</p>
            <div className="h-16 bg-void-card border border-void-hairline rounded-xl2 animate-pulse" />
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

        {status === "ready" && mode === "view" && profile && (
          <div className="space-y-4">
            {errorMessage && <p className="text-warn text-xs">{errorMessage}</p>}

            <div className="bg-void-card border border-void-hairline rounded-xl2 px-4 py-3">
              <p className="text-xs text-ink-faint uppercase tracking-wider mb-1">Golongan Darah</p>
              <p className="text-sm text-ink">{describeBloodType(profile.blood_type)}</p>
            </div>

            <div className="bg-void-card border border-void-hairline rounded-xl2 px-4 py-3">
              <p className="text-xs text-ink-faint uppercase tracking-wider mb-1.5">Alergi</p>
              {profile.allergies.length === 0 ? (
                <p className="text-xs text-ink-faint">Belum ada alergi tercatat.</p>
              ) : (
                profile.allergies.map((a, i) => (
                  <p key={i} className="text-sm text-ink mb-1">
                    {describeAllergyType(a.type)} · {a.allergen}
                    {a.severity && ` (${describeSeverity(a.severity)})`}
                  </p>
                ))
              )}
            </div>

            <div className="bg-void-card border border-void-hairline rounded-xl2 px-4 py-3">
              <p className="text-xs text-ink-faint uppercase tracking-wider mb-1.5">Kondisi Medis Penting</p>
              {profile.conditions.length === 0 ? (
                <p className="text-xs text-ink-faint">Belum ada kondisi medis tercatat.</p>
              ) : (
                profile.conditions.map((c, i) => (
                  <p key={i} className="text-sm text-ink mb-1">{c.condition_name} ({describeConditionStatus(c.status)})</p>
                ))
              )}
            </div>

            <div className="bg-void-card border border-void-hairline rounded-xl2 px-4 py-3">
              <p className="text-xs text-ink-faint uppercase tracking-wider mb-1.5">Kontak Medis & Darurat</p>
              <p className="text-sm text-ink">Dokter: {profile.primary_doctor_name || "Belum diisi"}</p>
              <p className="text-sm text-ink">Klinik/RS: {profile.primary_clinic_name || "Belum diisi"}</p>
              <p className="text-sm text-ink mt-1.5">Kontak darurat: {profile.emergency_contact_name || "Belum diisi"}</p>
              <p className="text-sm text-ink">Telepon: {profile.emergency_contact_phone || "Belum diisi"}</p>
            </div>

            <p className="text-[11px] text-ink-faint">
              {profile.last_reviewed_at
                ? `Terakhir diperiksa ulang: ${formatDateTimeWIB(profile.last_reviewed_at)}${profile.last_reviewed_by_name ? ` oleh ${profile.last_reviewed_by_name}` : ""}`
                : "Belum pernah ditandai diperiksa ulang."}
            </p>

            {canEdit && (
              <div className="flex gap-2">
                <button
                  type="button"
                  onClick={() => { setForm(profileToFormState(profile)); setFormError(""); setMode("edit"); }}
                  className="flex-1 py-3 rounded-xl2 bg-feed text-white text-sm font-semibold"
                >
                  Ubah Profil
                </button>
                <button
                  type="button"
                  onClick={handleReview}
                  disabled={reviewSubmitting}
                  className="flex-1 py-3 rounded-xl2 border border-void-hairline text-ink-muted text-sm font-semibold disabled:opacity-50"
                >
                  {reviewSubmitting ? "Menandai..." : "Tandai sudah diperiksa ulang"}
                </button>
              </div>
            )}

            {capabilities.can_preview_emergency_card && (
              <button
                type="button"
                onClick={() => setShowEmergencyCard(true)}
                className="w-full py-3 rounded-xl2 border border-feed text-feed text-sm font-semibold"
              >
                🚑 Lihat Kartu Darurat
              </button>
            )}
          </div>
        )}

        {status === "ready" && mode === "edit" && (
          <form onSubmit={handleSubmit} className="space-y-1">
            <label className="block text-xs text-ink-faint uppercase tracking-wider mb-1.5" htmlFor="medprofile-blood-type">
              Golongan Darah
            </label>
            <select
              id="medprofile-blood-type"
              value={form.blood_type}
              onChange={(e) => setForm((f) => ({ ...f, blood_type: e.target.value }))}
              className="w-full bg-void border border-void-hairline rounded-lg px-3 py-2.5 text-sm text-ink mb-4"
            >
              <option value="">Belum dicatat</option>
              {BLOOD_TYPES.map((b) => <option key={b} value={b}>{describeBloodType(b)}</option>)}
            </select>

            <AllergyEditor allergies={form.allergies} onChange={(allergies) => setForm((f) => ({ ...f, allergies }))} />
            <ConditionEditor conditions={form.conditions} onChange={(conditions) => setForm((f) => ({ ...f, conditions }))} />

            <p className="text-xs text-ink-faint uppercase tracking-wider mb-1.5">Dokter & Klinik Utama</p>
            <input type="text" value={form.primary_doctor_name} onChange={(e) => setForm((f) => ({ ...f, primary_doctor_name: e.target.value }))}
              maxLength={MEDICAL_PROFILE_LIMITS.DOCTOR_NAME_MAX_LEN} placeholder="Nama dokter (opsional)"
              className="w-full bg-void border border-void-hairline rounded-lg px-3 py-2.5 text-sm text-ink mb-2" />
            <input type="text" value={form.primary_clinic_name} onChange={(e) => setForm((f) => ({ ...f, primary_clinic_name: e.target.value }))}
              maxLength={MEDICAL_PROFILE_LIMITS.CLINIC_NAME_MAX_LEN} placeholder="Nama klinik/RS (opsional)"
              className="w-full bg-void border border-void-hairline rounded-lg px-3 py-2.5 text-sm text-ink mb-2" />
            <input type="text" value={form.primary_clinic_phone} onChange={(e) => setForm((f) => ({ ...f, primary_clinic_phone: e.target.value }))}
              maxLength={MEDICAL_PROFILE_LIMITS.PHONE_MAX_LEN} placeholder="Telepon klinik (opsional)"
              className="w-full bg-void border border-void-hairline rounded-lg px-3 py-2.5 text-sm text-ink mb-4" />

            <p className="text-xs text-ink-faint uppercase tracking-wider mb-1.5">Kontak Darurat</p>
            <input type="text" value={form.emergency_contact_name} onChange={(e) => setForm((f) => ({ ...f, emergency_contact_name: e.target.value }))}
              maxLength={MEDICAL_PROFILE_LIMITS.CONTACT_NAME_MAX_LEN} placeholder="Nama kontak darurat (opsional)"
              className="w-full bg-void border border-void-hairline rounded-lg px-3 py-2.5 text-sm text-ink mb-2" />
            <input type="text" value={form.emergency_contact_relationship} onChange={(e) => setForm((f) => ({ ...f, emergency_contact_relationship: e.target.value }))}
              maxLength={MEDICAL_PROFILE_LIMITS.RELATIONSHIP_MAX_LEN} placeholder="Hubungan dengan anak (opsional)"
              className="w-full bg-void border border-void-hairline rounded-lg px-3 py-2.5 text-sm text-ink mb-2" />
            <input type="text" value={form.emergency_contact_phone} onChange={(e) => setForm((f) => ({ ...f, emergency_contact_phone: e.target.value }))}
              maxLength={MEDICAL_PROFILE_LIMITS.PHONE_MAX_LEN} placeholder="Telepon kontak darurat (opsional)"
              className="w-full bg-void border border-void-hairline rounded-lg px-3 py-2.5 text-sm text-ink mb-4" />

            <label className="block text-xs text-ink-faint uppercase tracking-wider mb-1.5" htmlFor="medprofile-instructions">
              Instruksi Darurat
            </label>
            <textarea
              id="medprofile-instructions"
              value={form.emergency_instructions}
              onChange={(e) => setForm((f) => ({ ...f, emergency_instructions: e.target.value }))}
              maxLength={MEDICAL_PROFILE_LIMITS.EMERGENCY_INSTRUCTIONS_MAX_LEN}
              rows={3}
              placeholder="cth. Hubungi ayah dulu sebelum ke UGD (opsional)"
              className="w-full bg-void border border-void-hairline rounded-lg px-3 py-2.5 text-sm text-ink mb-4"
            />

            {formError && <p className="text-warn text-xs mb-4">{formError}</p>}

            <div className="flex gap-2">
              <button type="button" onClick={() => { setMode("view"); setFormError(""); }} className="flex-1 py-3 rounded-lg border border-void-hairline text-ink-muted text-sm font-medium">
                Batal
              </button>
              <button type="submit" disabled={submitting} className="flex-1 py-3 rounded-lg bg-feed text-white text-sm font-semibold disabled:opacity-50">
                {submitting ? "Menyimpan..." : "Simpan Profil"}
              </button>
            </div>
          </form>
        )}
      </div>

      {showEmergencyCard && (
        <EmergencyCardModal
          child={child}
          capabilities={capabilities}
          editGenerationRef={editGenerationRef}
          onClose={() => setShowEmergencyCard(false)}
        />
      )}
    </div>
  );
}
