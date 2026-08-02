const BASE_URL = import.meta.env.VITE_API_URL || "http://localhost:5000/api";

const TOKEN_KEY = "babytracker_token";

export function getToken() {
  return localStorage.getItem(TOKEN_KEY);
}

export function setToken(token) {
  if (token) localStorage.setItem(TOKEN_KEY, token);
}

export function clearToken() {
  localStorage.removeItem(TOKEN_KEY);
}

async function request(path, options = {}) {
  const token = getToken();
  const headers = { "Content-Type": "application/json", ...options.headers };
  if (token) headers["Authorization"] = `Bearer ${token}`;

  const res = await fetch(`${BASE_URL}${path}`, {
    credentials: "include",
    headers,
    ...options,
  });

  let data = null;
  try {
    data = await res.json();
  } catch (_) {
    // no body
  }

  if (!res.ok) {
    const message = data?.error || `Request gagal (${res.status})`;
    throw new Error(message);
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
  exportPdfUrl: (childId) => `${BASE_URL}/children/${childId}/export-pdf`,
  exportJsonUrl: (childId) => `${BASE_URL}/children/${childId}/export-json`,
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

  // multi-caregiver
  listCaregivers: (childId) => request(`/children/${childId}/caregivers`),
  removeCaregiver: (childId, userId) =>
    request(`/children/${childId}/caregivers/${userId}`, { method: "DELETE" }),
  createInvite: (childId) =>
    request(`/children/${childId}/invite`, { method: "POST" }),
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
};
