import { useEffect, useState, useCallback } from "react";
import { api } from "../api/client";
import VaccinationScreen from "../components/VaccinationScreen";
import SteppedDateTimeInput from "../components/SteppedDateTimeInput";
import RelatedArticles from "../components/RelatedArticles";
import DoctorConsultationScreen from "../components/DoctorConsultationScreen";
import MedicationScheduleScreen from "./MedicationScheduleScreen";
import MedicalProfileScreen from "./MedicalProfileScreen";
import { todayWIB } from "../utils/date";

const SUB_TABS = [
  { key: "doctor", label: "Dokter", icon: "🩺" },
  { key: "temperature", label: "Suhu", icon: "🌡️" },
  { key: "illness", label: "Sakit", icon: "🤒" },
  { key: "medication", label: "Obat", icon: "💊" },
  { key: "vaccination", label: "Vaksin", icon: "💉" },
];

const STATUS_COLOR = {
  Normal: "text-diaper",
  "Hipotermia (terlalu dingin)": "text-sleep",
  Demam: "text-warn",
  "Demam tinggi (segera ke dokter)": "text-warn",
};

function fmtDate(iso) {
  return new Date(iso).toLocaleDateString("id-ID", { day: "2-digit", month: "short", year: "numeric" });
}
function fmtDateTime(iso) {
  return new Date(iso).toLocaleString("id-ID", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" });
}

export default function HealthScreen({ child, currentUserId }) {
  const [activeTab, setActiveTab] = useState("doctor");
  const [visits, setVisits] = useState([]);
  const [temps, setTemps] = useState([]);
  const [illnesses, setIllnesses] = useState([]);
  const [medications, setMedications] = useState([]);
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);
  const [medicationForIllness, setMedicationForIllness] = useState(null); // illness id kalau nambah obat dari kartu sakit
  const [editingLog, setEditingLog] = useState(null);
  const [editingKind, setEditingKind] = useState(null);
  const [showConsultation, setShowConsultation] = useState(false);
  const [showMedicationSchedule, setShowMedicationSchedule] = useState(false);
  const [showMedicalProfile, setShowMedicalProfile] = useState(false);

  const loadAll = useCallback(async () => {
    setLoading(true);
    try {
      const [v, t, i, m] = await Promise.all([
        api.listDoctorVisits(child.id),
        api.listTemperature(child.id),
        api.listIllness(child.id),
        api.listMedication(child.id),
      ]);
      setVisits(v);
      setTemps(t);
      setIllnesses(i);
      setMedications(m);
    } finally {
      setLoading(false);
    }
  }, [child.id]);

  useEffect(() => {
    loadAll();
  }, [loadAll]);

  const markHealed = async (illnessId) => {
    await api.updateIllness(illnessId, { end_date: todayWIB() });
    await loadAll();
  };

  const openAdd = () => {
    setMedicationForIllness(null);
    setEditingLog(null);
    setEditingKind(null);
    setShowForm(true);
  };

  const openEdit = (item, kind) => {
    setMedicationForIllness(null);
    setEditingLog(item);
    setEditingKind(kind);
    setShowForm(true);
  };

  return (
    <div className="min-h-screen pb-32 px-6 pt-8">
      <h1 className="font-display text-3xl text-ink mb-1">Kesehatan</h1>
      <p className="text-sm text-ink-muted mb-6">Kunjungan dokter, suhu, sakit, dan obat</p>

      <div className="flex gap-2 mb-5 overflow-x-auto">
        {SUB_TABS.map((t) => (
          <button
            key={t.key}
            onClick={() => setActiveTab(t.key)}
            className={`flex-1 flex flex-col items-center gap-1 py-3 rounded-xl2 border text-xs font-medium whitespace-nowrap px-2 ${
              activeTab === t.key
                ? "bg-feed/15 border-feed text-feed"
                : "bg-void-card border-void-hairline text-ink-muted"
            }`}
          >
            <span className="text-lg">{t.icon}</span>
            {t.label}
          </button>
        ))}
      </div>

      {loading ? (
        <p className="text-ink-faint text-sm text-center py-10">Memuat...</p>
      ) : (
        <>
          {activeTab === "doctor" && (
            <div className="space-y-2">
              <button
                type="button"
                onClick={() => setShowConsultation(true)}
                className="w-full py-2.5 mb-1 rounded-xl2 border border-feed text-feed text-sm font-semibold"
              >
                🩺 Siapkan Konsultasi
              </button>
              <button
                type="button"
                onClick={() => setShowMedicalProfile(true)}
                className="w-full py-2.5 mb-1 rounded-xl2 border border-feed text-feed text-sm font-semibold"
              >
                🩺 Profil Medis & Kartu Darurat
              </button>
              {visits.length === 0 && <p className="text-ink-faint text-sm">Belum ada catatan kunjungan.</p>}
              {visits.map((v) => (
                <div
                  key={v.id}
                  onClick={() => openEdit(v, "doctor")}
                  className="bg-void-card border border-void-hairline rounded-xl2 px-4 py-3 cursor-pointer active:bg-void-raised"
                >
                  <div className="flex items-center justify-between">
                    <p className="text-xs text-ink-faint font-mono">{fmtDate(v.visit_date)}</p>
                    <button
                      onClick={async (e) => {
                        e.stopPropagation();
                        await api.deleteDoctorVisit(v.id);
                        await loadAll();
                      }}
                      className="text-ink-faint text-xs"
                    >
                      Hapus
                    </button>
                  </div>
                  <p className="text-sm text-ink mt-1">
                    {v.doctor_name || "Dokter"} {v.clinic_name && `· ${v.clinic_name}`}
                  </p>
                  {v.reason && <p className="text-xs text-ink-muted mt-0.5">Keluhan: {v.reason}</p>}
                  {v.diagnosis && <p className="text-xs text-ink-muted">Diagnosis: {v.diagnosis}</p>}
                  {v.next_visit_date && (
                    <p className="text-xs text-feed mt-1">Kontrol berikutnya: {fmtDate(v.next_visit_date)}</p>
                  )}
                  {v.created_by_name && (
                    <p className="text-[11px] text-ink-faint mt-1">oleh {v.created_by_name}</p>
                  )}
                </div>
              ))}
            </div>
          )}

          {activeTab === "temperature" && (
            <div className="space-y-2">
              {temps.length === 0 && <p className="text-ink-faint text-sm">Belum ada catatan suhu.</p>}
              {temps.map((t) => (
                <div
                  key={t.id}
                  onClick={() => openEdit(t, "temperature")}
                  className="flex items-center justify-between bg-void-card border border-void-hairline rounded-xl2 px-4 py-3 cursor-pointer active:bg-void-raised"
                >
                  <div>
                    <p className="text-xs text-ink-faint font-mono">{fmtDateTime(t.timestamp)}</p>
                    <p className="text-sm text-ink mt-0.5">
                      {t.temperature_celsius}°C <span className="text-ink-faint">({t.method})</span>
                    </p>
                    <p className={`text-xs font-semibold mt-0.5 ${STATUS_COLOR[t.status] || "text-ink"}`}>
                      {t.status}
                    </p>
                    {t.created_by_name && (
                      <p className="text-[11px] text-ink-faint mt-0.5">oleh {t.created_by_name}</p>
                    )}
                  </div>
                  <button
                    onClick={async (e) => {
                      e.stopPropagation();
                      await api.deleteTemperature(t.id);
                      await loadAll();
                    }}
                    className="text-ink-faint text-xs"
                  >
                    Hapus
                  </button>
                </div>
              ))}
            </div>
          )}

          {activeTab === "illness" && (
            <div className="space-y-3">
              {illnesses.length === 0 && <p className="text-ink-faint text-sm">Belum ada catatan sakit.</p>}
              {illnesses.map((ill) => (
                <div key={ill.id} className="bg-void-card border border-void-hairline rounded-xl2 px-4 py-3">
                  <div onClick={() => openEdit(ill, "illness")} className="cursor-pointer active:opacity-70">
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-2">
                        <p className="text-sm text-ink font-medium">{ill.illness_name}</p>
                        {ill.is_ongoing && (
                          <span className="text-[10px] bg-warn/15 text-warn px-2 py-0.5 rounded-full font-medium">
                            Berlangsung
                          </span>
                        )}
                      </div>
                      <button
                        onClick={async (e) => {
                          e.stopPropagation();
                          await api.deleteIllness(ill.id);
                          await loadAll();
                        }}
                        className="text-ink-faint text-xs"
                      >
                        Hapus
                      </button>
                    </div>
                    <p className="text-xs text-ink-faint font-mono mt-1">
                      {fmtDate(ill.start_date)} {ill.end_date && `— ${fmtDate(ill.end_date)}`}
                    </p>
                    {ill.symptoms && <p className="text-xs text-ink-muted mt-1">Gejala: {ill.symptoms}</p>}
                    {ill.created_by_name && (
                      <p className="text-[11px] text-ink-faint mt-0.5">oleh {ill.created_by_name}</p>
                    )}
                  </div>

                  {ill.medications?.length > 0 && (
                    <div className="mt-2 pl-3 border-l-2 border-void-hairline space-y-1">
                      {ill.medications.map((m) => (
                        <p
                          key={m.id}
                          onClick={() => openEdit(m, "medication")}
                          className="text-xs text-ink-muted cursor-pointer active:text-ink"
                        >
                          💊 {m.medication_name} {m.dosage && `(${m.dosage})`} · {fmtDateTime(m.timestamp)}
                        </p>
                      ))}
                    </div>
                  )}

                  <div className="flex gap-2 mt-3">
                    <button
                      onClick={() => {
                        setEditingLog(null);
                        setMedicationForIllness(ill.id);
                        setShowForm(true);
                      }}
                      className="text-xs px-3 py-1.5 rounded-full border border-void-hairline text-ink-muted"
                    >
                      + Obat
                    </button>
                    {ill.is_ongoing && (
                      <button
                        onClick={() => markHealed(ill.id)}
                        className="text-xs px-3 py-1.5 rounded-full bg-diaper/15 text-diaper font-medium"
                      >
                        Tandai Sembuh
                      </button>
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}

          {activeTab === "medication" && (
            <div className="space-y-2">
              <button
                type="button"
                onClick={() => setShowMedicationSchedule(true)}
                className="w-full py-2.5 mb-1 rounded-xl2 border border-feed text-feed text-sm font-semibold"
              >
                💊 Jadwal Obat
              </button>
              {medications.length === 0 && <p className="text-ink-faint text-sm">Belum ada catatan obat.</p>}
              {medications.map((m) => (
                <div
                  key={m.id}
                  onClick={() => openEdit(m, "medication")}
                  className="flex items-center justify-between bg-void-card border border-void-hairline rounded-xl2 px-4 py-3 cursor-pointer active:bg-void-raised"
                >
                  <div>
                    <p className="text-xs text-ink-faint font-mono">{fmtDateTime(m.timestamp)}</p>
                    <p className="text-sm text-ink mt-0.5">
                      {m.medication_name} {m.dosage && `· ${m.dosage}`}
                    </p>
                    {m.created_by_name && (
                      <p className="text-[11px] text-ink-faint mt-0.5">oleh {m.created_by_name}</p>
                    )}
                  </div>
                  <button
                    onClick={async (e) => {
                      e.stopPropagation();
                      await api.deleteMedication(m.id);
                      await loadAll();
                    }}
                    className="text-ink-faint text-xs"
                  >
                    Hapus
                  </button>
                </div>
              ))}
            </div>
          )}

          {activeTab === "vaccination" && <VaccinationScreen child={child} />}
        </>
      )}

      <RelatedArticles
        category={activeTab === "vaccination" ? "vaccination" : "health"}
        ageMonths={(new Date() - new Date(child.birth_date)) / (1000 * 60 * 60 * 24 * 30.4375)}
      />

      {activeTab !== "vaccination" && (
        <button
          onClick={openAdd}
          className="fixed bottom-6 right-6 w-14 h-14 rounded-full bg-feed text-white text-2xl shadow-soft flex items-center justify-center"
          aria-label="Tambah catatan"
        >
          +
        </button>
      )}

      {showForm && (
        <HealthForm
          tab={editingLog ? editingKind : medicationForIllness ? "medication" : activeTab}
          illnessId={medicationForIllness}
          childId={child.id}
          editingLog={editingLog}
          onClose={() => {
            setShowForm(false);
            setMedicationForIllness(null);
            setEditingLog(null);
            setEditingKind(null);
          }}
          onSaved={loadAll}
        />
      )}

      {showConsultation && (
        <DoctorConsultationScreen
          child={child}
          onClose={() => setShowConsultation(false)}
          onRecordVisit={() => {
            setShowConsultation(false);
            openAdd();
          }}
        />
      )}

      {showMedicationSchedule && (
        <MedicationScheduleScreen
          child={child}
          currentUserId={currentUserId}
          onClose={() => {
            setShowMedicationSchedule(false);
            loadAll();
          }}
        />
      )}

      {showMedicalProfile && (
        <MedicalProfileScreen
          child={child}
          currentUserId={currentUserId}
          onClose={() => setShowMedicalProfile(false)}
        />
      )}
    </div>
  );
}

const toLocalInputValue = (date) => {
  const pad = (n) => String(n).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(
    date.getHours()
  )}:${pad(date.getMinutes())}`;
};

function HealthForm({ tab, illnessId, childId, editingLog, onClose, onSaved }) {
  const isEdit = !!editingLog;
  const [submitting, setSubmitting] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [error, setError] = useState("");

  // waktu kejadian buat suhu & obat — default sekarang, bisa digeser mundur
  // kalau baru sempat catat belakangan (sering lupa langsung input)
  const [eventTime, setEventTime] = useState(
    editingLog?.timestamp ? toLocalInputValue(new Date(editingLog.timestamp)) : toLocalInputValue(new Date())
  );

  // dokter
  const [visitDate, setVisitDate] = useState(editingLog?.visit_date || todayWIB());
  const [doctorName, setDoctorName] = useState(editingLog?.doctor_name || "");
  const [clinicName, setClinicName] = useState(editingLog?.clinic_name || "");
  const [reason, setReason] = useState(editingLog?.reason || "");
  const [diagnosis, setDiagnosis] = useState(editingLog?.diagnosis || "");
  const [nextVisitDate, setNextVisitDate] = useState(editingLog?.next_visit_date || "");

  // suhu
  const [temperature, setTemperature] = useState(editingLog?.temperature_celsius?.toString() || "37.0");
  const [method, setMethod] = useState(editingLog?.method || "ketiak");

  // sakit
  const [illnessName, setIllnessName] = useState(editingLog?.illness_name || "");
  const [startDate, setStartDate] = useState(editingLog?.start_date || todayWIB());
  const [symptoms, setSymptoms] = useState(editingLog?.symptoms || "");

  // obat
  const [medicationName, setMedicationName] = useState(editingLog?.medication_name || "");
  const [dosage, setDosage] = useState(editingLog?.dosage || "");

  const titles = {
    doctor: isEdit ? "Edit Kunjungan Dokter" : "Catat Kunjungan Dokter",
    temperature: isEdit ? "Edit Suhu Tubuh" : "Catat Suhu Tubuh",
    illness: isEdit ? "Edit Sakit" : "Catat Sakit",
    medication: isEdit ? "Edit Obat" : illnessId ? "Tambah Obat untuk Sakit Ini" : "Catat Obat",
  };

  const handleDelete = async () => {
    if (!editingLog) return;
    setDeleting(true);
    try {
      if (tab === "doctor") await api.deleteDoctorVisit(editingLog.id);
      else if (tab === "temperature") await api.deleteTemperature(editingLog.id);
      else if (tab === "illness") await api.deleteIllness(editingLog.id);
      else if (tab === "medication") await api.deleteMedication(editingLog.id);
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
      if (tab === "doctor") {
        const payload = {
          visit_date: visitDate,
          doctor_name: doctorName || null,
          clinic_name: clinicName || null,
          reason: reason || null,
          diagnosis: diagnosis || null,
          next_visit_date: nextVisitDate || null,
        };
        if (isEdit) await api.updateDoctorVisit(editingLog.id, payload);
        else await api.createDoctorVisit(childId, payload);
      } else if (tab === "temperature") {
        const payload = { temperature_celsius: Number(temperature), method, timestamp: new Date(eventTime).toISOString() };
        if (isEdit) await api.updateTemperature(editingLog.id, payload);
        else await api.createTemperature(childId, payload);
      } else if (tab === "illness") {
        const payload = { illness_name: illnessName, start_date: startDate, symptoms: symptoms || null };
        if (isEdit) await api.updateIllness(editingLog.id, payload);
        else await api.createIllness(childId, payload);
      } else if (tab === "medication") {
        const payload = { medication_name: medicationName, dosage: dosage || null, timestamp: new Date(eventTime).toISOString() };
        if (isEdit) {
          await api.updateMedication(editingLog.id, payload);
        } else {
          await api.createMedication(childId, { ...payload, illness_id: illnessId || null });
        }
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
        className="relative w-full sm:max-w-sm bg-void-card border-t sm:border border-void-hairline rounded-t-xl2 sm:rounded-xl2 p-6 pb-8 max-h-[85vh] overflow-y-auto"
      >
        <div className="w-10 h-1 bg-void-hairline rounded-full mx-auto mb-5 sm:hidden" />
        <h2 className="font-display text-2xl text-ink mb-5">{titles[tab]}</h2>

        {tab === "doctor" && (
          <div className="space-y-3">
            <label className="block text-xs text-ink-muted mb-1">Tanggal kunjungan</label>
            <input type="date" value={visitDate} onChange={(e) => setVisitDate(e.target.value)}
              max={todayWIB()}
              className="w-full bg-void border border-void-hairline rounded-lg px-3 py-2.5 text-ink" required />
            <label className="block text-xs text-ink-muted mb-1">Nama dokter</label>
            <input type="text" value={doctorName} onChange={(e) => setDoctorName(e.target.value)}
              placeholder="cth. dr. Sarah, Sp.A"
              className="w-full bg-void border border-void-hairline rounded-lg px-3 py-2.5 text-ink placeholder:text-ink-faint" />
            <label className="block text-xs text-ink-muted mb-1">Klinik/RS</label>
            <input type="text" value={clinicName} onChange={(e) => setClinicName(e.target.value)}
              placeholder="cth. Klinik Sehat Anak"
              className="w-full bg-void border border-void-hairline rounded-lg px-3 py-2.5 text-ink placeholder:text-ink-faint" />
            <label className="block text-xs text-ink-muted mb-1">Keluhan</label>
            <input type="text" value={reason} onChange={(e) => setReason(e.target.value)}
              placeholder="cth. Demam 2 hari"
              className="w-full bg-void border border-void-hairline rounded-lg px-3 py-2.5 text-ink placeholder:text-ink-faint" />
            <label className="block text-xs text-ink-muted mb-1">Diagnosis</label>
            <input type="text" value={diagnosis} onChange={(e) => setDiagnosis(e.target.value)}
              placeholder="cth. ISPA ringan"
              className="w-full bg-void border border-void-hairline rounded-lg px-3 py-2.5 text-ink placeholder:text-ink-faint" />
            <label className="block text-xs text-ink-muted mb-1">Jadwal kontrol berikutnya (opsional)</label>
            <input type="date" value={nextVisitDate} onChange={(e) => setNextVisitDate(e.target.value)}
              className="w-full bg-void border border-void-hairline rounded-lg px-3 py-2.5 text-ink" />
          </div>
        )}

        {tab === "temperature" && (
          <div className="space-y-3">
            <label className="block text-xs text-ink-muted mb-1">Suhu (°C)</label>
            <input type="number" step="0.1" value={temperature} onChange={(e) => setTemperature(e.target.value)}
              className="w-full bg-void border border-void-hairline rounded-lg px-3 py-2.5 text-ink font-mono" required />
            <label className="block text-xs text-ink-muted mb-1">Cara ukur</label>
            <div className="grid grid-cols-3 gap-2">
              {["ketiak", "dahi", "telinga", "mulut", "dubur"].map((m) => (
                <button type="button" key={m} onClick={() => setMethod(m)}
                  className={`py-2 rounded-lg text-xs capitalize border ${
                    method === m ? "bg-feed/20 border-feed text-feed" : "border-void-hairline text-ink-muted"
                  }`}>
                  {m}
                </button>
              ))}
            </div>
          </div>
        )}

        {tab === "illness" && (
          <div className="space-y-3">
            <label className="block text-xs text-ink-muted mb-1">Nama sakit</label>
            <input type="text" value={illnessName} onChange={(e) => setIllnessName(e.target.value)}
              placeholder="cth. Batuk Pilek" required
              className="w-full bg-void border border-void-hairline rounded-lg px-3 py-2.5 text-ink placeholder:text-ink-faint" />
            <label className="block text-xs text-ink-muted mb-1">Mulai sakit</label>
            <input type="date" value={startDate} onChange={(e) => setStartDate(e.target.value)}
              max={todayWIB()}
              className="w-full bg-void border border-void-hairline rounded-lg px-3 py-2.5 text-ink" required />
            <label className="block text-xs text-ink-muted mb-1">Gejala</label>
            <input type="text" value={symptoms} onChange={(e) => setSymptoms(e.target.value)}
              placeholder="cth. Hidung tersumbat, batuk ringan"
              className="w-full bg-void border border-void-hairline rounded-lg px-3 py-2.5 text-ink placeholder:text-ink-faint" />
          </div>
        )}

        {tab === "medication" && (
          <div className="space-y-3">
            <label className="block text-xs text-ink-muted mb-1">Nama obat</label>
            <input type="text" value={medicationName} onChange={(e) => setMedicationName(e.target.value)}
              placeholder="cth. Paracetamol drop" required
              className="w-full bg-void border border-void-hairline rounded-lg px-3 py-2.5 text-ink placeholder:text-ink-faint" />
            <label className="block text-xs text-ink-muted mb-1">Dosis</label>
            <input type="text" value={dosage} onChange={(e) => setDosage(e.target.value)}
              placeholder="cth. 0.8 ml"
              className="w-full bg-void border border-void-hairline rounded-lg px-3 py-2.5 text-ink placeholder:text-ink-faint" />
          </div>
        )}

        {(tab === "temperature" || tab === "medication") && (
          <div className="mt-4">
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

        {error && <p className="text-warn text-sm mt-3">{error}</p>}

        <div className="flex gap-3 mt-6">
          <button type="button" onClick={onClose}
            className="flex-1 py-3 rounded-lg border border-void-hairline text-ink-muted text-sm font-medium">
            Batal
          </button>
          <button type="submit" disabled={submitting}
            className="flex-1 py-3 rounded-lg bg-feed text-white text-sm font-semibold disabled:opacity-50">
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