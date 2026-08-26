import { toUserFacingErrorMessage } from "../utils/errorMessage";

const BASE_URL = import.meta.env.VITE_API_URL || "http://localhost:5000/api";

const TOKEN_KEY = "babytracker_token";
const USER_ID_KEY = "babytracker_user_id";

/**
 * Error terstruktur buat semua kegagalan request lewat request() di bawah
 * — biar caller (AuthContext, App.jsx, dst) bisa bedain SECARA ANDAL antara
 * gagal jaringan (server nggak kesentuh sama sekali) vs. server BENERAN
 * merespons dengan status error, dan status berapa persisnya. `.message`
 * tetap dipertahankan sama persis kayak sebelumnya (termasuk semua pesan
 * bahasa Indonesia yang dilempar berdasarkan data.error dari server) —
 * ApiError extends Error, jadi kode lama yang cuma baca err.message tetap
 * jalan tanpa perubahan. Cuma nyimpen status + kind + message manusiawi;
 * TIDAK PERNAH nyimpen body respons mentah, stack trace server, cookie,
 * atau token.
 */
export class ApiError extends Error {
  constructor({ kind, status = null, message }) {
    super(message);
    this.name = "ApiError";
    this.kind = kind; // "network" | "unauthorized" | "forbidden" | "validation" | "server_error" | "http_error"
    this.status = status;
  }
}

function classifyHttpError(status) {
  if (status === 401) return "unauthorized";
  if (status === 403) return "forbidden";
  if (status === 400 || status === 422) return "validation";
  if (status >= 500) return "server_error";
  return "http_error";
}

export function getToken() {
  return localStorage.getItem(TOKEN_KEY);
}

export function setToken(token) {
  if (token) localStorage.setItem(TOKEN_KEY, token);
}

export function clearToken() {
  localStorage.removeItem(TOKEN_KEY);
}

// Dipakai buat nge-tag tiap item antrian offline sama pemiliknya, TANPA
// nyimpen token di item itu sendiri (lihat queueOfflineRequest di bawah).
// syncQueue di useOfflineSync bandingin ini sama userId tersimpan pas
// nyoba sinkron, biar antrian akun lain (atau akun yang udah logout)
// nggak pernah ke-sync pakai token akun yang lagi aktif sekarang.
export function getCurrentUserId() {
  const raw = localStorage.getItem(USER_ID_KEY);
  return raw ? Number(raw) : null;
}

export function setCurrentUser(userId) {
  if (userId != null) localStorage.setItem(USER_ID_KEY, String(userId));
}

export function clearCurrentUser() {
  localStorage.removeItem(USER_ID_KEY);
}

// Diekspor (bukan cuma dipakai internal) — dipakai juga buat ngasih
// idempotency key baru ke item antrian legacy yang belum punya satu
// (lihat claimLegacyItem di hooks/useOfflineSync.js).
export function generateRequestId() {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }
  // fallback buat runtime tanpa crypto.randomUUID (browser lama, atau
  // lingkungan test) — nggak perlu kriptografis, cuma perlu unik per klien
  return `${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

// endpoint "quick log" yang boleh diantrikan offline — sengaja dibatasi
// ke aksi yang paling sering dicatat real-time (bukan semua endpoint),
// biar nggak ribet nanganin kasus edge yang lebih kompleks (edit, hapus,
// dll) buat versi pertama fitur ini
const OFFLINE_QUEUEABLE_PATHS = [
  /\/children\/\d+\/feeding-logs$/,
  /\/children\/\d+\/sleep-logs$/,
  /\/children\/\d+\/diaper-logs$/,
  /\/children\/\d+\/pumping-logs$/,
  /\/children\/\d+\/activity-logs$/,
  /\/children\/\d+\/medication-logs$/,
  // Care Reminders & Schedules Phase 1 — CUMA aksi selesai/lewati
  // occurrence yang boleh diantrikan offline (requirement eksplisit).
  // Membuat/mengubah/menghapus DEFINISI reminder sengaja TIDAK masuk
  // sini — nunggu online (tombolnya nonaktif offline, lihat
  // ReminderScreen.jsx) biar nggak perlu nanganin kasus edge form
  // penuh + validasi server offline buat versi pertama fitur ini.
  /\/children\/\d+\/reminders\/\d+\/occurrences\/[^/]+\/complete$/,
  /\/children\/\d+\/reminders\/\d+\/occurrences\/[^/]+\/skip$/,
  // Medication Schedule & Adherence Phase 1 — pola SAMA PERSIS reminder
  // di atas: CUMA aksi kasih/lewati dosis yang boleh diantrikan offline.
  // Membuat/mengubah/menghapus DEFINISI jadwal obat sengaja TIDAK masuk
  // sini (tetap online-only, lihat backend/docs/MEDICATION_SCHEDULE.md).
  /\/children\/\d+\/medication-schedules\/\d+\/occurrences\/[^/]+\/administer$/,
  /\/children\/\d+\/medication-schedules\/\d+\/occurrences\/[^/]+\/skip$/,
];

function isOfflineQueueable(path, method) {
  return (
    method === "POST" && OFFLINE_QUEUEABLE_PATHS.some((re) => re.test(path))
  );
}

async function queueOfflineRequest(path, method, body, clientRequestId) {
  const { enqueueRequest } = await import("../utils/offlineQueue");
  // SENGAJA nggak nyimpen header Authorization di sini — item antrian
  // cuma nyimpen userId pemiliknya, token diambil FRESH dari localStorage
  // pas beneran mau di-sync (lihat useOfflineSync), biar nggak ada token
  // yang nongkrong di IndexedDB.
  const queueId = await enqueueRequest({
    method,
    url: path,
    body: body || null,
    userId: getCurrentUserId(),
    clientRequestId,
  });

  let optimisticData = {};
  try {
    optimisticData = body ? JSON.parse(body) : {};
  } catch (_) {
    // body bukan JSON valid, biarin optimisticData kosong
  }

  // response "optimistic" — biar UI langsung kelihatan kesimpen, dengan
  // id lokal (bukan id asli dari server, soalnya belum beneran nyampe
  // ke server) dan flag _offlineQueued biar UI bisa nampilin indikator
  return { ...optimisticData, id: `local-${queueId}`, _offlineQueued: true };
}

async function request(path, options = {}) {
  const token = getToken();
  const headers = { "Content-Type": "application/json", ...options.headers };
  if (token) headers["Authorization"] = `Bearer ${token}`;
  const method = options.method || "GET";

  // Idempotency key: dibuat SEKALI di sini, sebelum fetch pertama kali
  // dicoba, buat request yang bisa diantrikan offline. Kalau request ini
  // sukses sampai server tapi responsnya ilang di tengah jalan (koneksi
  // putus), retry berikutnya (baik langsung atau lewat antrian offline)
  // ngirim ulang key yang SAMA — backend bakal balikin hasil yang lama,
  // bukan bikin record dobel.
  let idempotencyKey = null;
  if (isOfflineQueueable(path, method)) {
    idempotencyKey = generateRequestId();
    headers["X-Idempotency-Key"] = idempotencyKey;
  }

  let res;
  try {
    res = await fetch(`${BASE_URL}${path}`, {
      credentials: "include",
      headers,
      ...options,
    });
  } catch (networkError) {
    // fetch cuma throw kalau BENERAN nggak nyambung ke server sama
    // sekali (offline, DNS gagal, dll) — beda dari server yang sempat
    // merespons dengan status error (itu diurus di bagian !res.ok bawah,
    // nggak masuk sini)
    if (isOfflineQueueable(path, method)) {
      return await queueOfflineRequest(path, method, options.body, idempotencyKey);
    }
    throw new ApiError({
      kind: "network",
      status: null,
      message: "Nggak ada koneksi internet. Coba lagi nanti.",
    });
  }

  let data = null;
  try {
    data = await res.json();
  } catch (_) {
    // no body
  }

  if (!res.ok) {
    const message = toUserFacingErrorMessage(data?.error, `Request gagal (${res.status})`);
    throw new ApiError({ kind: classifyHttpError(res.status), status: res.status, message });
  }
  return data;
}

export const api = {
  // auth
  register: (payload) =>
    request("/auth/register", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  login: (payload) =>
    request("/auth/login", { method: "POST", body: JSON.stringify(payload) }),
  logout: () => request("/auth/logout", { method: "POST" }),
  updateProfile: (payload) =>
    request("/auth/me", { method: "PUT", body: JSON.stringify(payload) }),
  testTelegram: () => request("/auth/me/telegram/test", { method: "POST" }),
  changePassword: (currentPassword, newPassword) =>
    request("/auth/me/password", {
      method: "PUT",
      body: JSON.stringify({
        current_password: currentPassword,
        new_password: newPassword,
      }),
    }),
  me: () => request("/auth/me"),

  // Privacy & Data Management Center — semua aksi destruktif online-only.
  privacyOverview: () => request("/privacy/overview"),
  leaveChildAccess: (childId, payload) =>
    request(`/privacy/children/${childId}/leave`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  deleteChildData: (childId, payload) =>
    request(`/privacy/children/${childId}/delete`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  deleteAccount: (payload) =>
    request("/privacy/account/delete", {
      method: "POST",
      body: JSON.stringify(payload),
    }),

  // children
  listChildren: () => request("/children"),
  createChild: (payload) =>
    request("/children", { method: "POST", body: JSON.stringify(payload) }),
  updateChild: (childId, payload) =>
    request(`/children/${childId}`, {
      method: "PUT",
      body: JSON.stringify(payload),
    }),

  // foto anak
  uploadChildPhoto: async (childId, file) => {
    const formData = new FormData();
    formData.append("photo", file);
    const token = getToken();
    const headers = token ? { Authorization: `Bearer ${token}` } : {};
    const res = await fetch(`${BASE_URL}/children/${childId}/photo`, {
      method: "POST",
      credentials: "include",
      headers,
      body: formData,
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data?.error || "Upload foto gagal");
    return data;
  },
  photoUrl: (filename) => `${BASE_URL}/uploads/${filename}`,
  listMemoryJournal: (childId) => request(`/children/${childId}/memory-journal`),
  developmentTimeline: (childId, params = {}) => {
    const search = new URLSearchParams();
    if (params.categories?.length) search.set("categories", params.categories.join(","));
    if (params.from) search.set("from", params.from);
    if (params.to) search.set("to", params.to);
    if (params.limit) search.set("limit", String(params.limit));
    const suffix = search.toString() ? `?${search}` : "";
    return request(`/children/${childId}/development-timeline${suffix}`);
  },
  previewMonthlyStory: (childId, payload) => request(`/children/${childId}/monthly-story/preview`, {
    method: "POST", body: JSON.stringify(payload),
  }),
  monthlyStoryPdfUrl: (childId) => `${BASE_URL}/children/${childId}/monthly-story/pdf`,
  memoryStorage: (childId) => request(`/children/${childId}/memory-storage`),
  cleanupMemoryStorage: (childId, payload) => request(`/children/${childId}/memory-storage/cleanup`, {
    method: "POST", body: JSON.stringify(payload),
  }),
  optimizeMemoryPhoto: (childId, entryId) => request(`/children/${childId}/memory-storage/${entryId}/optimize`, {
    method: "POST",
  }),
  createMemoryJournal: async (childId, { photo, caption, occurredDate }) => {
    const formData = new FormData();
    formData.append("photo", photo);
    formData.append("caption", caption || "");
    formData.append("occurred_date", occurredDate);
    const token = getToken();
    let res;
    try {
      res = await fetch(`${BASE_URL}/children/${childId}/memory-journal`, {
        method: "POST", credentials: "include",
        headers: token ? { Authorization: `Bearer ${token}` } : {}, body: formData,
      });
    } catch (_) {
      throw new ApiError({ kind: "network", message: "Foto hanya bisa diunggah saat online." });
    }
    const data = await res.json().catch(() => null);
    if (!res.ok) throw new ApiError({ kind: classifyHttpError(res.status), status: res.status,
      message: toUserFacingErrorMessage(data?.error, "Upload foto gagal") });
    return data;
  },
  updateMemoryJournal: (entryId, payload) => request(`/memory-journal/${entryId}`, {
    method: "PUT", body: JSON.stringify(payload),
  }),
  deleteMemoryJournal: (entryId) => request(`/memory-journal/${entryId}`, { method: "DELETE" }),
  loadMemoryJournalPhoto: async (entryId) => {
    const token = getToken();
    const res = await fetch(`${BASE_URL}/memory-journal/${entryId}/photo`, {
      credentials: "include", headers: token ? { Authorization: `Bearer ${token}` } : {},
    });
    if (!res.ok) throw new Error("Foto tidak dapat dimuat");
    return URL.createObjectURL(await res.blob());
  },
  exportPdfUrl: (childId) => `${BASE_URL}/children/${childId}/export-pdf`,
  exportJsonUrl: (childId) => `${BASE_URL}/children/${childId}/export-json`,

  /**
   * Download file yang butuh autentikasi (export PDF/JSON) — TIDAK bisa
   * pakai <a href> biasa, soalnya navigasi link biasa nggak nyertain
   * header Authorization (token auth kita bukan cookie session), bikin
   * request-nya keanggep belum login dan gagal "anak tidak ditemukan".
   * Fetch manual dengan token, ambil sebagai Blob, baru trigger download.
   */
  downloadAuthenticated: async (url, filename) => {
    const token = getToken();
    const res = await fetch(url, {
      credentials: "include",
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    });
    if (!res.ok) {
      let message = `Gagal download (${res.status})`;
      try {
        const data = await res.json();
        if (data?.error) message = data.error;
      } catch (_) {
        // body bukan JSON, biarin pesan default
      }
      throw new Error(message);
    }
    const blob = await res.blob();
    const objectUrl = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = objectUrl;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(objectUrl);
  },
  importJson: (data) =>
    request("/children/import-json", {
      method: "POST",
      body: JSON.stringify(data),
    }),

  // vaksinasi
  listVaccineSchedule: () => request("/vaccine-schedule"),
  listChildVaccinations: (childId) =>
    request(`/children/${childId}/vaccinations`),
  updateChildVaccinations: (childId, items) =>
    request(`/children/${childId}/vaccinations`, {
      method: "POST",
      body: JSON.stringify({ items }),
    }),
  nextVaccine: (childId) => request(`/children/${childId}/next-vaccine`),

  // tumbuh kembang (growth)
  listGrowthMeasurements: (childId) =>
    request(`/children/${childId}/growth-measurements`),
  createGrowthMeasurement: (childId, payload) =>
    request(`/children/${childId}/growth-measurements`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  deleteGrowthMeasurement: (id) =>
    request(`/growth-measurements/${id}`, { method: "DELETE" }),
  updateGrowthMeasurement: (id, payload) =>
    request(`/growth-measurements/${id}`, {
      method: "PUT",
      body: JSON.stringify(payload),
    }),
  latestGrowthStatus: (childId) =>
    request(`/children/${childId}/growth-latest`),
  growthReferenceCurve: (measurementType, gender, maxMonths = 24) =>
    request(
      `/growth-reference-curve?measurement_type=${measurementType}&gender=${gender}&max_months=${maxMonths}`,
    ),

  // health: kunjungan dokter
  listDoctorVisits: (childId) => request(`/children/${childId}/doctor-visits`),
  createDoctorVisit: (childId, payload) =>
    request(`/children/${childId}/doctor-visits`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  deleteDoctorVisit: (id) =>
    request(`/doctor-visits/${id}`, { method: "DELETE" }),
  updateDoctorVisit: (id, payload) =>
    request(`/doctor-visits/${id}`, {
      method: "PUT",
      body: JSON.stringify(payload),
    }),

  // Doctor Consultation Workflow — Phase 1. POST (bukan GET) SENGAJA
  // dipakai buat preview juga (bukan cuma PDF) — payload-nya bisa
  // memuat pilihan section + teks transien questions/additional_note
  // yang nggak boleh nongol di query string/riwayat browser/log proxy.
  previewDoctorConsultation: (childId, payload) =>
    request(`/children/${childId}/doctor-consultation/preview`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  doctorConsultationPdfUrl: (childId) => `${BASE_URL}/children/${childId}/doctor-consultation/pdf`,

  /**
   * Sama seperti `downloadAuthenticated` di atas, TAPI POST + JSON body
   * (endpoint PDF konsultasi butuh payload periode/section/teks
   * transien, jadi nggak bisa GET biasa). PDF export SENGAJA online-only
   * — nggak pernah masuk antrean offline (lihat utils/offlineQueue.js).
   */
  downloadAuthenticatedPost: async (url, body, filename) => {
    const token = getToken();
    const res = await fetch(url, {
      method: "POST",
      credentials: "include",
      headers: {
        "Content-Type": "application/json",
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: JSON.stringify(body),
    });
    if (!res.ok) {
      let message = `Gagal download (${res.status})`;
      try {
        const data = await res.json();
        if (data?.error) message = data.error;
      } catch (_) {
        // body bukan JSON, biarin pesan default
      }
      // `.status` ditempel di error (BUKAN cuma di pesan teks) biar
      // caller (mis. MedicalProfileScreen.jsx:EmergencyCardModal) bisa
      // membedakan SECARA ANDAL kode status tertentu (409 "snapshot
      // Kartu Darurat basi", 400/403 token pratinjau tidak valid) dari
      // error lain, tanpa perlu menebak dari isi pesan Indonesia yang
      // bisa berubah kapan saja -- purely additive, caller lama yang
      // cuma baca `.message` (mis. DoctorConsultationScreen.jsx) tetap
      // jalan tanpa perubahan.
      const err = new Error(message);
      err.status = res.status;
      throw err;
    }
    const blob = await res.blob();
    const objectUrl = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = objectUrl;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(objectUrl);
  },

  // health: suhu tubuh
  listTemperature: (childId) =>
    request(`/children/${childId}/temperature-logs`),
  createTemperature: (childId, payload) =>
    request(`/children/${childId}/temperature-logs`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  deleteTemperature: (id) =>
    request(`/temperature-logs/${id}`, { method: "DELETE" }),
  updateTemperature: (id, payload) =>
    request(`/temperature-logs/${id}`, {
      method: "PUT",
      body: JSON.stringify(payload),
    }),

  // health: sakit/penyakit
  listIllness: (childId) => request(`/children/${childId}/illness-logs`),
  createIllness: (childId, payload) =>
    request(`/children/${childId}/illness-logs`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  updateIllness: (id, payload) =>
    request(`/illness-logs/${id}`, {
      method: "PUT",
      body: JSON.stringify(payload),
    }),
  deleteIllness: (id) => request(`/illness-logs/${id}`, { method: "DELETE" }),

  // health: obat
  listMedication: (childId, date) =>
    request(
      `/children/${childId}/medication-logs${date ? `?date=${date}` : ""}`,
    ),
  createMedication: (childId, payload) =>
    request(`/children/${childId}/medication-logs`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  deleteMedication: (id) =>
    request(`/medication-logs/${id}`, { method: "DELETE" }),
  updateMedication: (id, payload) =>
    request(`/medication-logs/${id}`, {
      method: "PUT",
      body: JSON.stringify(payload),
    }),

  // mood
  listMood: (childId) => request(`/children/${childId}/mood-logs`),
  createMood: (childId, payload) =>
    request(`/children/${childId}/mood-logs`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  deleteMood: (id) => request(`/mood-logs/${id}`, { method: "DELETE" }),
  updateMood: (id, payload) =>
    request(`/mood-logs/${id}`, {
      method: "PUT",
      body: JSON.stringify(payload),
    }),

  // milestone
  listMilestone: (childId) => request(`/children/${childId}/milestone-logs`),
  createMilestone: (childId, payload) =>
    request(`/children/${childId}/milestone-logs`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  deleteMilestone: (id) =>
    request(`/milestone-logs/${id}`, { method: "DELETE" }),
  updateMilestone: (id, payload) =>
    request(`/milestone-logs/${id}`, {
      method: "PUT",
      body: JSON.stringify(payload),
    }),
  milestoneReference: () => request("/milestone-reference"),

  // statistik & tren
  getStats: (childId, days = 7) =>
    request(`/children/${childId}/stats?days=${days}`),

  // Smart Insights & Weekly Summary (Phase 1) — BACA SAJA, `period`
  // cuma "7d" | "30d" (server menolak nilai lain dengan 400).
  getInsights: (childId, period = "7d") =>
    request(`/children/${childId}/insights?period=${period}`),

  // Care Reminders & Schedules (Phase 1) — lihat backend/docs/REMINDERS.md.
  listReminders: (childId) => request(`/children/${childId}/reminders`),
  createReminder: (childId, payload) =>
    request(`/children/${childId}/reminders`, { method: "POST", body: JSON.stringify(payload) }),
  updateReminder: (childId, reminderId, payload) =>
    request(`/children/${childId}/reminders/${reminderId}`, { method: "PATCH", body: JSON.stringify(payload) }),
  deleteReminder: (childId, reminderId) =>
    request(`/children/${childId}/reminders/${reminderId}`, { method: "DELETE" }),
  // `payload` opsional: { linked_log_type, linked_log_id } buat alur
  // "Catat sekarang" — dua-duanya BOLEH diantrikan offline (lihat
  // OFFLINE_QUEUEABLE_PATHS di atas).
  completeReminderOccurrence: (childId, reminderId, occurrenceKey, payload) =>
    request(`/children/${childId}/reminders/${reminderId}/occurrences/${occurrenceKey}/complete`, {
      method: "POST", body: JSON.stringify(payload || {}),
    }),
  skipReminderOccurrence: (childId, reminderId, occurrenceKey, payload) =>
    request(`/children/${childId}/reminders/${reminderId}/occurrences/${occurrenceKey}/skip`, {
      method: "POST", body: JSON.stringify(payload || {}),
    }),

  // Medication Schedule & Adherence (Phase 1) — lihat
  // backend/docs/MEDICATION_SCHEDULE.md. Create/update/delete jadwal
  // SENGAJA online-only (TIDAK ada di OFFLINE_QUEUEABLE_PATHS) — cuma
  // administer/skip occurrence yang boleh diantrikan offline.
  listMedicationSchedules: (childId) => request(`/children/${childId}/medication-schedules`),
  createMedicationSchedule: (childId, payload) =>
    request(`/children/${childId}/medication-schedules`, { method: "POST", body: JSON.stringify(payload) }),
  updateMedicationSchedule: (childId, scheduleId, payload) =>
    request(`/children/${childId}/medication-schedules/${scheduleId}`, { method: "PATCH", body: JSON.stringify(payload) }),
  deleteMedicationSchedule: (childId, scheduleId) =>
    request(`/children/${childId}/medication-schedules/${scheduleId}`, { method: "DELETE" }),
  administerMedicationDose: (childId, scheduleId, occurrenceKey) =>
    request(`/children/${childId}/medication-schedules/${scheduleId}/occurrences/${occurrenceKey}/administer`, {
      method: "POST", body: JSON.stringify({}),
    }),
  skipMedicationDose: (childId, scheduleId, occurrenceKey) =>
    request(`/children/${childId}/medication-schedules/${scheduleId}/occurrences/${occurrenceKey}/skip`, {
      method: "POST", body: JSON.stringify({}),
    }),
  getMedicationAdherence: (childId, period = "7d") =>
    request(`/children/${childId}/medication-schedules/adherence?period=${period}`),

  // Child Medical Profile & Emergency Card (Phase 1) — lihat
  // backend/docs/MEDICAL_PROFILE.md. ONLINE-ONLY SENGAJA: TIDAK SATU
  // PUN path di bawah ini pernah masuk OFFLINE_QUEUEABLE_PATHS (lihat
  // atas) — data medis+kontak darurat lengkap terlalu sensitif buat
  // antrian offline yang didesain buat mutasi terbatas biasa.
  getMedicalProfile: (childId) => request(`/children/${childId}/medical-profile`),
  updateMedicalProfile: (childId, payload) =>
    request(`/children/${childId}/medical-profile`, { method: "PUT", body: JSON.stringify(payload) }),
  reviewMedicalProfile: (childId) =>
    request(`/children/${childId}/medical-profile/review`, { method: "POST", body: JSON.stringify({}) }),
  previewEmergencyCard: (childId) =>
    request(`/children/${childId}/emergency-card/preview`, { method: "POST", body: JSON.stringify({}) }),
  emergencyCardPdfUrl: (childId) => `${BASE_URL}/children/${childId}/emergency-card/pdf`,

  // Caregiver Handover Summary (Phase 1) — lihat
  // backend/docs/CAREGIVER_HANDOVER.md. ONLINE-ONLY SENGAJA: TIDAK SATU
  // PUN path di bawah ini pernah masuk OFFLINE_QUEUEABLE_PATHS (lihat
  // atas) — create/update/acknowledge/close TIDAK PERNAH diantrikan
  // offline (requirement eksplisit Phase 1: online-only, tidak pernah
  // disimpan ke localStorage/IndexedDB/antrean offline).
  getCaregiverHandover: (childId) => request(`/children/${childId}/caregiver-handover`),
  createCaregiverHandover: (childId, note) =>
    request(`/children/${childId}/caregiver-handover`, {
      method: "POST", body: JSON.stringify(note != null ? { note } : {}),
    }),
  updateCaregiverHandover: (handoverId, note) =>
    request(`/caregiver-handovers/${handoverId}`, {
      method: "PUT", body: JSON.stringify({ note }),
    }),
  acknowledgeCaregiverHandover: (handoverId) =>
    request(`/caregiver-handovers/${handoverId}/acknowledge`, {
      method: "POST", body: JSON.stringify({}),
    }),
  closeCaregiverHandover: (handoverId) =>
    request(`/caregiver-handovers/${handoverId}/close`, {
      method: "POST", body: JSON.stringify({}),
    }),

  // multi-caregiver (Caregiver Roles & Permissions Phase 1 — lihat
  // backend/docs/ROLES_PERMISSIONS.md)
  listCaregivers: (childId) => request(`/children/${childId}/caregivers`),
  removeCaregiver: (childId, userId) =>
    request(`/children/${childId}/caregivers/${userId}`, { method: "DELETE" }),
  // `role` WAJIB — "editor" | "viewer", dipilih pemilik. Backend
  // memvalidasi lewat allowlist ketat; frontend TIDAK PERNAH nawarin
  // "owner" sebagai pilihan.
  updateCaregiverRole: (childId, userId, role) =>
    request(`/children/${childId}/caregivers/${userId}`, {
      method: "PUT",
      body: JSON.stringify({ role }),
    }),
  createInvite: (childId, role) =>
    request(`/children/${childId}/invite`, {
      method: "POST",
      body: JSON.stringify({ role }),
    }),
  joinChild: (code) =>
    request("/children/join", {
      method: "POST",
      body: JSON.stringify({ code }),
    }),

  // artikel edukasi
  listArticles: (category, ageMonths) =>
    request(
      `/articles?category=${category}${ageMonths != null ? `&age_months=${ageMonths}` : ""}`,
    ),

  // feeding
  listFeeding: (childId, date) =>
    request(`/children/${childId}/feeding-logs?date=${date}`),
  createFeeding: (childId, payload) =>
    request(`/children/${childId}/feeding-logs`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  deleteFeeding: (logId) =>
    request(`/feeding-logs/${logId}`, { method: "DELETE" }),
  updateFeeding: (logId, payload) =>
    request(`/feeding-logs/${logId}`, {
      method: "PUT",
      body: JSON.stringify(payload),
    }),
  feedingPrediction: (childId) =>
    request(`/children/${childId}/feeding-prediction`),
  wakeWindowPrediction: (childId) =>
    request(`/children/${childId}/wake-window-prediction`),

  // pumping (perah ASI)
  listPumping: (childId, date) =>
    request(`/children/${childId}/pumping-logs?date=${date}`),
  createPumping: (childId, payload) =>
    request(`/children/${childId}/pumping-logs`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  deletePumping: (logId) =>
    request(`/pumping-logs/${logId}`, { method: "DELETE" }),
  updatePumping: (logId, payload) =>
    request(`/pumping-logs/${logId}`, {
      method: "PUT",
      body: JSON.stringify(payload),
    }),

  // activity (jalan-jalan, mandi)
  listActivity: (childId, date) =>
    request(`/children/${childId}/activity-logs?date=${date}`),
  createActivity: (childId, payload) =>
    request(`/children/${childId}/activity-logs`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  deleteActivity: (logId) =>
    request(`/activity-logs/${logId}`, { method: "DELETE" }),
  updateActivity: (logId, payload) =>
    request(`/activity-logs/${logId}`, {
      method: "PUT",
      body: JSON.stringify(payload),
    }),

  // sleep
  listSleep: (childId, date) =>
    request(`/children/${childId}/sleep-logs?date=${date}`),
  createSleep: (childId, payload) =>
    request(`/children/${childId}/sleep-logs`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  updateSleep: (logId, payload) =>
    request(`/sleep-logs/${logId}`, {
      method: "PUT",
      body: JSON.stringify(payload),
    }),
  deleteSleep: (logId) => request(`/sleep-logs/${logId}`, { method: "DELETE" }),

  // diaper
  listDiaper: (childId, date) =>
    request(`/children/${childId}/diaper-logs?date=${date}`),
  createDiaper: (childId, payload) =>
    request(`/children/${childId}/diaper-logs`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  deleteDiaper: (logId) =>
    request(`/diaper-logs/${logId}`, { method: "DELETE" }),
  updateDiaper: (logId, payload) =>
    request(`/diaper-logs/${logId}`, {
      method: "PUT",
      body: JSON.stringify(payload),
    }),

  // summary
  dailySummary: (childId, date) =>
    request(`/children/${childId}/daily-summary?date=${date}`),

  // Caregiver Audit Trail (Phase 1) — BACA SAJA, endpoint nggak pernah
  // nerima create/update/delete. `params` opsional: { cursor, limit,
  // action, entity_type, actor_user_id } — dibuang kalau null/undefined
  // biar nggak ngirim query string kosong (mis. "?cursor=undefined").
  listAuditEvents: (childId, params = {}) => {
    const search = new URLSearchParams();
    for (const [key, value] of Object.entries(params)) {
      if (value !== null && value !== undefined && value !== "") {
        search.set(key, String(value));
      }
    }
    const qs = search.toString();
    return request(`/children/${childId}/audit-events${qs ? `?${qs}` : ""}`);
  },
};
