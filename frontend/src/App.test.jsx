import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import App from "./App";
import { enqueueRequest, getQueue, getQueueForUser, removeFromQueue } from "./utils/offlineQueue";
import { setToken, setCurrentUser, ApiError } from "./api/client";
import { cacheUserProfile, cacheChildren, setCachedActiveChildId } from "./utils/sessionCache";

// Mock semua subkomponen Dashboard yang manggil api sendiri (atau nggak
// relevan buat perilaku yang lagi dites di sini) — sama persis kayak
// pola di Dashboard.test.jsx, biar test ini fokus ke ALUR App/AuthContext
// (sesi + daftar anak + restorasi offline), bukan ke rendering fidelity
// komponen lain.
vi.mock("./components/DailyRadialClock", () => ({ default: () => null }));
vi.mock("./components/FeedingPredictionCard", () => ({ default: () => null }));
vi.mock("./components/WakeWindowCard", () => ({ default: () => null }));
vi.mock("./components/NextVaccineCard", () => ({ default: () => null }));
vi.mock("./components/RelatedArticles", () => ({ default: () => null }));
vi.mock("./components/StatusPill", () => ({ default: () => null }));
vi.mock("./components/SmartInsightsBell", () => ({ default: () => null }));
vi.mock("./components/MotorActivityCard", () => ({ default: () => null }));
// OnboardingWizard di-stub biar keliatan JELAS kapan App mutusin nampilin
// wizard ini — itu satu-satunya hal yang mau dicek, bukan detail form-nya.
vi.mock("./pages/OnboardingWizard", () => ({
  default: () => <div data-testid="onboarding-wizard-stub">onboarding</div>,
}));

const { apiMock } = vi.hoisted(() => ({
  apiMock: {
    me: vi.fn(),
    login: vi.fn(),
    register: vi.fn(),
    logout: vi.fn(),
    listChildren: vi.fn(),
    dailySummary: vi.fn(),
    listFeeding: vi.fn(),
    listSleep: vi.fn(),
    listDiaper: vi.fn(),
    listPumping: vi.fn(),
    listActivity: vi.fn(),
    listMedication: vi.fn(),
    listCaregivers: vi.fn(),
    listAuditEvents: vi.fn(),
    getStats: vi.fn(),
    photoUrl: (f) => f,
    exportPdfUrl: () => "",
    exportJsonUrl: () => "",
    downloadAuthenticated: vi.fn(),
  },
}));

// `api` di-mock, TAPI sisanya (ApiError, getToken/setToken, getCurrentUserId/
// setCurrentUser, dst) dipakai ASLI — test ini butuh localStorage yang
// sebenarnya biar skenario "cold start" (token & currentUserId udah ada
// SEBELUM App di-render) beneran valid, sama kayak browser asli.
vi.mock("./api/client", async (importOriginal) => {
  const actual = await importOriginal();
  return { ...actual, api: apiMock };
});

const testUser = { id: 5, name: "Ibu Test", email: "ibu@test.com" };
const testChild = {
  id: 10,
  name: "Anak Satu",
  nickname: "Dedek",
  birth_date: "2024-01-01",
  gender: "L",
  photo_filename: null,
  birth_weight_kg: 3.2,
  birth_height_cm: 50,
};

function todayAt(hour) {
  const now = new Date();
  now.setHours(hour, 0, 0, 0);
  return now.toISOString();
}

function setOnline(value) {
  Object.defineProperty(window.navigator, "onLine", { value, configurable: true });
}

function networkError() {
  return new ApiError({ kind: "network", status: null, message: "Nggak ada koneksi internet. Coba lagi nanti." });
}

function resetApiMock() {
  Object.values(apiMock).forEach((fn) => typeof fn?.mockReset === "function" && fn.mockReset());
  apiMock.dailySummary.mockResolvedValue({
    age_days: 100,
    guideline_label: null,
    feeding: { actual: 0 },
    sleep: { actual_hours: 0 },
    wet_diaper: { actual: 0 },
    message: null,
  });
  apiMock.listFeeding.mockResolvedValue([]);
  apiMock.listSleep.mockResolvedValue([]);
  apiMock.listDiaper.mockResolvedValue([]);
  apiMock.listPumping.mockResolvedValue([]);
  apiMock.listActivity.mockResolvedValue([]);
  apiMock.listMedication.mockResolvedValue([]);
  apiMock.listCaregivers.mockResolvedValue([]);
  apiMock.listAuditEvents.mockResolvedValue({ events: [], next_cursor: null });
  apiMock.getStats.mockResolvedValue({ days: [] });
}

async function drainRealQueue() {
  const all = await getQueue();
  for (const item of all) await removeFromQueue(item.id);
}

async function seedFeedingQueueItem(overrides = {}) {
  return enqueueRequest({
    method: "POST",
    url: `/children/${testChild.id}/feeding-logs`,
    body: JSON.stringify({
      feed_type: "sufor",
      volume_ml: 60,
      duration_minutes: null,
      breast_side: null,
      timestamp: todayAt(10),
    }),
    userId: testUser.id,
    clientRequestId: "app-test-key",
    ...overrides,
  });
}

// dipasang di level PROCESS Node (bukan window "unhandledrejection" jsdom,
// yang nggak selalu dipicu konsisten) — ini mekanisme runtime yang
// beneran andal buat nangkep promise yang reject tanpa pernah ditangani.
let unhandledRejections = [];
function onUnhandledRejection(reason) {
  unhandledRejections.push(reason);
}

beforeEach(async () => {
  resetApiMock();
  localStorage.clear();
  await drainRealQueue();
  setOnline(true);
  // default aman: fetch mentah (dipakai useOfflineSync buat sync antrian)
  // GAGAL jaringan kecuali test yang bersangkutan sengaja nge-override-nya
  // — biar nggak ada sisa mock fetch dari test sebelumnya yang diam-diam
  // nge-sync (dan ngapus) item antrian punya test lain.
  global.fetch = vi.fn().mockRejectedValue(new TypeError("Failed to fetch"));
  unhandledRejections = [];
  process.on("unhandledRejection", onUnhandledRejection);
});

afterEach(async () => {
  process.removeListener("unhandledRejection", onUnhandledRejection);
  vi.clearAllMocks();
  await drainRealQueue();
});

describe("App — cold start while offline (full AuthProvider + App integration)", () => {
  it("restores the correct child and the pending offline record exactly once, without unhandled rejections, when token/currentUserId/cache/IndexedDB all pre-exist and every network request fails", async () => {
    // --- state SEBELUM render, persis kondisi hard refresh sambil offline ---
    setToken("tok-5");
    setCurrentUser(5);
    cacheUserProfile(testUser);
    cacheChildren(5, [testChild]);
    setCachedActiveChildId(5, testChild.id);
    await seedFeedingQueueItem();

    apiMock.me.mockRejectedValue(networkError());
    apiMock.listChildren.mockRejectedValue(networkError());
    apiMock.dailySummary.mockRejectedValue(networkError());
    apiMock.listFeeding.mockRejectedValue(networkError());
    apiMock.listSleep.mockRejectedValue(networkError());
    apiMock.listDiaper.mockRejectedValue(networkError());
    apiMock.listPumping.mockRejectedValue(networkError());
    apiMock.listActivity.mockRejectedValue(networkError());
    apiMock.listMedication.mockRejectedValue(networkError());
    apiMock.getStats.mockRejectedValue(networkError());
    setOnline(false);

    render(<App />);

    // 16. nggak nyangkut di "Memuat..." selamanya
    await waitFor(() => expect(screen.queryByText("Memuat...")).not.toBeInTheDocument());

    // 15. BUKAN AuthScreen, BUKAN OnboardingWizard — walau /auth/me DAN
    // /children dua-duanya gagal, sesi + anak direstorasi dari cache
    expect(screen.queryByText("Baby Daily Tracker")).not.toBeInTheDocument();
    expect(screen.queryByTestId("onboarding-wizard-stub")).not.toBeInTheDocument();

    // anak yang bener yang muncul (bukan anak lain / kosong)
    expect(screen.getAllByText("Dedek").length).toBeGreaterThan(0);

    // 18/19. record pending dari IndexedDB muncul, PERSIS SEKALI
    await waitFor(() => expect(screen.getByText("Sufor")).toBeInTheDocument());
    expect(screen.getAllByText("Sufor")).toHaveLength(1);
    expect(screen.getByText("⏳ nunggu sinkron")).toBeInTheDocument();

    // 22. gagal jaringan TIDAK menghapus request yang udah diqueue
    expect(await getQueue()).toHaveLength(1);

    // 24. nggak ada unhandled promise rejection sepanjang startup offline ini
    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(unhandledRejections).toEqual([]);
  });

  it("17. offline startup WITHOUT any cached child list shows a readable offline fallback with a working retry action (never onboarding)", async () => {
    setToken("tok-5");
    setCurrentUser(5);
    cacheUserProfile(testUser); // profil ada (login pernah sukses), TAPI daftar anak belum pernah ke-cache
    apiMock.me.mockRejectedValue(networkError());
    apiMock.listChildren.mockRejectedValue(networkError());
    setOnline(false);

    render(<App />);

    await waitFor(() => expect(screen.queryByText("Memuat...")).not.toBeInTheDocument());
    expect(screen.getByText("Belum bisa dibuka offline")).toBeInTheDocument();
    expect(screen.queryByTestId("onboarding-wizard-stub")).not.toBeInTheDocument();

    // retry berhasil begitu "online" beneran bisa muat data
    apiMock.listChildren.mockResolvedValueOnce([testChild]);
    const retryBtn = screen.getByText("Coba lagi");
    await act(async () => {
      fireEvent.click(retryBtn);
    });

    await waitFor(() => expect(screen.getAllByText("Dedek").length).toBeGreaterThan(0));
  });

  it("a genuinely empty child list from a SUCCESSFUL request still shows onboarding (not broken by the new offline fallback)", async () => {
    setToken("tok-5");
    setCurrentUser(5);
    apiMock.me.mockResolvedValue(testUser);
    apiMock.listChildren.mockResolvedValue([]); // sukses, beneran kosong
    setOnline(true);

    render(<App />);

    await waitFor(() => expect(screen.getByTestId("onboarding-wizard-stub")).toBeInTheDocument());
  });
});

describe("App — reconnect behavior", () => {
  it("20. returning online re-validates the session and refreshes the children list", async () => {
    setToken("tok-5");
    setCurrentUser(5);
    cacheUserProfile(testUser);
    cacheChildren(5, [testChild]);
    setCachedActiveChildId(5, testChild.id);
    apiMock.me.mockRejectedValue(networkError());
    apiMock.listChildren.mockRejectedValue(networkError());
    setOnline(false);

    render(<App />);
    await waitFor(() => expect(screen.getAllByText("Dedek").length).toBeGreaterThan(0));

    const meCallsBefore = apiMock.me.mock.calls.length;
    const listChildrenCallsBefore = apiMock.listChildren.mock.calls.length;

    apiMock.me.mockResolvedValueOnce(testUser);
    apiMock.listChildren.mockResolvedValueOnce([testChild]);
    setOnline(true);
    act(() => {
      window.dispatchEvent(new Event("online"));
    });

    await waitFor(() => expect(apiMock.me.mock.calls.length).toBeGreaterThan(meCallsBefore));
    await waitFor(() => expect(apiMock.listChildren.mock.calls.length).toBeGreaterThan(listChildrenCallsBefore));
  });

  it("21. returning online syncs the queued record and replaces it with exactly one server record", async () => {
    setToken("tok-5");
    setCurrentUser(5);
    cacheUserProfile(testUser);
    cacheChildren(5, [testChild]);
    setCachedActiveChildId(5, testChild.id);
    const queueId = await seedFeedingQueueItem();

    apiMock.me.mockRejectedValue(networkError());
    apiMock.listChildren.mockRejectedValue(networkError());
    apiMock.dailySummary.mockRejectedValue(networkError());
    apiMock.listFeeding.mockRejectedValue(networkError());
    setOnline(false);

    render(<App />);
    await waitFor(() => expect(screen.getByText("Sufor")).toBeInTheDocument());
    expect(screen.getAllByText("Sufor")).toHaveLength(1);

    // koneksi balik: sinkron sukses lewat useOfflineSync (pakai fetch mentah)
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      status: 201,
      headers: { get: () => null },
      json: async () => ({ id: 501 }),
    });
    // dan refresh data server (lewat api mock) sekarang berhasil, balikin
    // record ASLI (id numerik dari server) buat feeding yang sama
    apiMock.me.mockResolvedValueOnce(testUser);
    apiMock.listChildren.mockResolvedValueOnce([testChild]);
    apiMock.dailySummary.mockResolvedValue({
      age_days: 100,
      guideline_label: null,
      feeding: { actual: 1 },
      sleep: { actual_hours: 0 },
      wet_diaper: { actual: 0 },
      message: null,
    });
    apiMock.listFeeding.mockResolvedValue([
      { id: 501, feed_type: "sufor", volume_ml: 60, duration_minutes: null, breast_side: null, timestamp: todayAt(10) },
    ]);
    setOnline(true);

    act(() => {
      window.dispatchEvent(new Event("online"));
    });

    await waitFor(async () => expect(await getQueue()).toHaveLength(0));
    await waitFor(() => expect(screen.queryByText("⏳ nunggu sinkron")).not.toBeInTheDocument());
    expect(screen.getAllByText("Sufor")).toHaveLength(1); // tetap PERSIS 1, bukan 2 (lokal + server)

    void queueId;
  });
});

describe("App — logout preserves the queue but isolates it from other accounts", () => {
  it("23. explicit logout keeps the queued record intact (owned by the original user), never visible to a different account", async () => {
    setToken("tok-5");
    setCurrentUser(5);
    apiMock.me.mockResolvedValue(testUser);
    apiMock.listChildren.mockResolvedValue([testChild]);
    setOnline(true);

    render(<App />);
    await waitFor(() => expect(screen.getAllByText("Dedek").length).toBeGreaterThan(0));

    await seedFeedingQueueItem();
    vi.spyOn(window, "confirm").mockReturnValue(true);

    fireEvent.click(screen.getByText("☰"));
    const logoutBtn = await screen.findByText("Keluar");
    fireEvent.click(logoutBtn);

    // handleLogout() async (baca antrian dari IndexedDB dulu SEBELUM
    // nampilin confirm) — nggak sepenuhnya di-await sama act() bawaan
    // fireEvent, jadi tunggu lewat waitFor, bukan assert sinkron langsung
    await waitFor(() => expect(window.confirm).toHaveBeenCalled()); // ada 1 catatan nunggu sinkron -> wajib konfirmasi dulu
    await waitFor(() => expect(screen.getByText("Baby Daily Tracker")).toBeInTheDocument()); // balik ke AuthScreen

    // antrian TETAP ada (bukan dihapus tanpa konfirmasi eksplisit), dan
    // masih nempel ke user 5 — bukan ke-orphan/nempel ke siapapun yang
    // login berikutnya di perangkat yang sama
    const remaining = await getQueue();
    expect(remaining).toHaveLength(1);
    expect(remaining[0].userId).toBe(5);

    // simulasikan akun LAIN login di perangkat yang sama (id 6) — nggak
    // boleh keliatan ATAU tersinkron pakai punya user 5
    setCurrentUser(6);
    expect(await getQueueForUser(6)).toHaveLength(0);
    expect(await getQueueForUser(5)).toHaveLength(1); // tetap ada, cuma nggak keliatan/tersinkron buat user 6
  });
});

describe("App — Sync Center (single authoritative sync controller)", () => {
  async function renderAuthenticated() {
    setToken("tok-5");
    setCurrentUser(5);
    apiMock.me.mockResolvedValue(testUser);
    apiMock.listChildren.mockResolvedValue([testChild]);
    setOnline(true);
    render(<App />);
    await waitFor(() => expect(screen.getAllByText("Dedek").length).toBeGreaterThan(0));
  }

  it("is reachable from the app menu ('🔄 Status Sinkronisasi') even while sync status is idle (nothing pending)", async () => {
    await renderAuthenticated();
    expect(await getQueue()).toHaveLength(0); // status idle — nada pending sama sekali

    fireEvent.click(screen.getByText("☰"));
    const entry = await screen.findByText("Status Sinkronisasi");
    fireEvent.click(entry);

    expect(await screen.findByRole("dialog", { name: "Status Sinkronisasi" })).toBeInTheDocument();
    expect(screen.getByText("Belum pernah tersinkron")).toBeInTheDocument();
  });

  it("banner's 'Detail' action opens the exact same Sync Center dialog", async () => {
    await renderAuthenticated();
    await seedFeedingQueueItem();
    await waitFor(() => expect(screen.getByText("Detail")).toBeInTheDocument());

    fireEvent.click(screen.getByText("Detail"));

    expect(await screen.findByRole("dialog", { name: "Status Sinkronisasi" })).toBeInTheDocument();
  });

  it("Sync Center reflects a newly queued item live, with no need to reopen it — proving a single shared controller (not an isolated second instance)", async () => {
    await renderAuthenticated();

    fireEvent.click(screen.getByText("☰"));
    fireEvent.click(await screen.findByText("Status Sinkronisasi"));
    await screen.findByRole("dialog", { name: "Status Sinkronisasi" });
    expect(screen.getByText("Tidak ada catatan yang perlu disinkronkan saat ini.")).toBeInTheDocument();

    // item baru di-enqueue LANGSUNG lewat IndexedDB (dispatch
    // QUEUE_CHANGE_EVENT) — bukan lewat interaksi UI Sync Center itu
    // sendiri. Kalau AuthenticatedAppShell nge-mount 2 instance
    // useOfflineSync yang independen (1 buat banner, 1 lagi buat
    // SyncCenter), dialog yang UDAH KEBUKA ini nggak akan pernah tau ada
    // perubahan dari luar — cuma instance TERPUSAT yang dengar event global
    // ini yang bisa bikin dialog yang lagi kebuka update live begini.
    await act(async () => {
      await seedFeedingQueueItem();
    });

    await waitFor(() =>
      expect(screen.queryByText("Tidak ada catatan yang perlu disinkronkan saat ini.")).not.toBeInTheDocument(),
    );
  });

  it("a manual sync triggered from the Sync Center actually syncs the queued item exactly once", async () => {
    setToken("tok-5");
    setCurrentUser(5);
    apiMock.me.mockResolvedValue(testUser);
    apiMock.listChildren.mockResolvedValue([testChild]);
    setOnline(true);
    // fetch mentah sukses SEJAK AWAL (bukan default reject di beforeEach)
    // — biar item yang di-seed SEBELUM render nggak sempat kena backoff
    // dari percobaan gagal duluan pas mount, yang bakal bikin klik manual
    // ini nabrak jadwal retry yang belum waktunya.
    global.fetch = vi.fn().mockResolvedValue({ ok: true, status: 201, headers: { get: () => null } });
    await seedFeedingQueueItem();

    render(<App />);
    await waitFor(() => expect(screen.getAllByText("Dedek").length).toBeGreaterThan(0));
    // mount auto-sync (online + ada item) kemungkinan udah langsung
    // nyinkron duluan — tunggu itu beres dulu biar starting point-nya jelas
    await waitFor(async () => expect(await getQueue()).toHaveLength(0));

    await seedFeedingQueueItem({ clientRequestId: "app-test-key-2" });
    global.fetch.mockClear();

    fireEvent.click(screen.getByText("☰"));
    fireEvent.click(await screen.findByText("Status Sinkronisasi"));
    await screen.findByRole("dialog", { name: "Status Sinkronisasi" });

    await act(async () => {
      fireEvent.click(screen.getByText("Sinkronkan sekarang"));
    });

    await waitFor(async () => expect(await getQueue()).toHaveLength(0));
    expect(global.fetch).toHaveBeenCalledTimes(1);
  });
});

describe("App — Aktivitas Pengasuh (Caregiver Audit Trail menu entry)", () => {
  async function renderAuthenticated() {
    setToken("tok-5");
    setCurrentUser(5);
    apiMock.me.mockResolvedValue(testUser);
    apiMock.listChildren.mockResolvedValue([testChild]);
    setOnline(true);
    render(<App />);
    await waitFor(() => expect(screen.getAllByText("Dedek").length).toBeGreaterThan(0));
  }

  it("is reachable from the app menu ('🕘 Aktivitas Pengasuh')", async () => {
    await renderAuthenticated();

    fireEvent.click(screen.getByText("☰"));
    const entry = await screen.findByText("Aktivitas Pengasuh");
    fireEvent.click(entry);

    expect(await screen.findByRole("dialog", { name: "Aktivitas Pengasuh" })).toBeInTheDocument();
    await waitFor(() => expect(apiMock.listAuditEvents).toHaveBeenCalledWith(testChild.id, expect.any(Object)));
  });

  it("opening it does not disrupt the Sync Center's live queue updates (proves it reuses the single shared sync controller, not a second useOfflineSync instance)", async () => {
    await renderAuthenticated();

    // Buka & tutup Aktivitas Pengasuh dulu.
    fireEvent.click(screen.getByText("☰"));
    fireEvent.click(await screen.findByText("Aktivitas Pengasuh"));
    await screen.findByRole("dialog", { name: "Aktivitas Pengasuh" });
    fireEvent.click(screen.getAllByRole("button", { name: "Tutup" })[0]);
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "Aktivitas Pengasuh" })).not.toBeInTheDocument());

    // Sync Center masih berfungsi normal sesudahnya — live update tetap jalan.
    fireEvent.click(screen.getByText("☰"));
    fireEvent.click(await screen.findByText("Status Sinkronisasi"));
    await screen.findByRole("dialog", { name: "Status Sinkronisasi" });
    expect(screen.getByText("Tidak ada catatan yang perlu disinkronkan saat ini.")).toBeInTheDocument();

    await act(async () => {
      await seedFeedingQueueItem();
    });

    await waitFor(() =>
      expect(screen.queryByText("Tidak ada catatan yang perlu disinkronkan saat ini.")).not.toBeInTheDocument(),
    );
  });
});
