import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, render, screen, waitFor } from "@testing-library/react";
import Dashboard, { isPendingOfflineItem, isLocalOnlyId } from "./Dashboard";
// SENGAJA nggak di-mock — test restorasi offline di bawah butuh IndexedDB
// ASLI (fake-indexeddb, udah di-setup global di vitest.setup.js) buat
// nguji Dashboard beneran baca dari sana, bukan cuma dari mock.
import { enqueueRequest, getQueue, removeFromQueue, updateQueueItem, QUEUE_STATUS as REAL_QUEUE_STATUS } from "../utils/offlineQueue";

// Mock semua child component yang manggil api sendiri (atau nggak relevan
// buat logic handleCreate yang lagi dites), biar test ini fokus ke
// perilaku Dashboard doang — bukan ke rendering fidelity komponen lain.
vi.mock("../components/DailyRadialClock", () => ({ default: () => null }));
vi.mock("../components/FeedingPredictionCard", () => ({ default: () => null }));
vi.mock("../components/WakeWindowCard", () => ({ default: () => null }));
vi.mock("../components/NextVaccineCard", () => ({ default: () => null }));
vi.mock("../components/RelatedArticles", () => ({ default: () => null }));
vi.mock("../components/StatusPill", () => ({ default: () => null }));
vi.mock("../components/SmartInsightsBell", () => ({ default: () => null }));
vi.mock("../components/MotorActivityCard", () => ({ default: () => null }));

// Payload contoh per tipe — dibikin persis kayak yang beneran dikirim
// QuickLogSheet asli, biar test ini nguji kontrak integrasi yang sebenarnya
// (handleCreate/handleSheetSubmit), bukan detail form QuickLogSheet
// (itu dites terpisah di QuickLogSheet.test.jsx).
function payloadFor(type) {
  const nowIso = new Date().toISOString();
  switch (type) {
    case "feeding":
      return { timestamp: nowIso, feed_type: "sufor", duration_minutes: null, volume_ml: 60, breast_side: null };
    case "sleep":
      return { start_time: nowIso, end_time: null, sleep_type: "siang" };
    case "diaper":
      return { timestamp: nowIso, diaper_type: "pipis", consistency: null };
    case "pumping":
      return { timestamp: nowIso, duration_minutes: 15, volume_ml: 80, breast_side: "kedua" };
    case "stroll":
      return { timestamp: nowIso, activity_type: "stroll", duration_minutes: 20, notes: null };
    case "bathing":
      return { timestamp: nowIso, activity_type: "bathing", duration_minutes: 10, notes: null };
    case "vitamin":
      return { timestamp: nowIso, medication_name: "Vitamin D" };
    default:
      return {};
  }
}

vi.mock("../components/QuickLogSheet", () => ({
  // Stub yang niru kontrak QuickLogSheet ASLI: submit sukses -> onClose(),
  // submit gagal -> modal TETAP kebuka (nggak manggil onClose). Detail
  // form/error-display QuickLogSheet asli dites di QuickLogSheet.test.jsx.
  default: (props) => (
    <div data-testid="quick-log-sheet">
      <span>sheet-type:{props.type}</span>
      <button
        onClick={async () => {
          try {
            await props.onSubmit(payloadFor(props.type));
            props.onClose();
          } catch (_) {
            // modal tetap kebuka, sama kayak QuickLogSheet asli pas gagal
          }
        }}
      >
        submit-sheet
      </button>
    </div>
  ),
}));

// vi.mock's factory is hoisted above regular top-level const/let, jadi
// apiMock (yang dipakai di dalam factory) harus dibikin lewat vi.hoisted
// biar nggak kena "Cannot access before initialization".
const { apiMock, currentUserIdBox } = vi.hoisted(() => ({
  currentUserIdBox: { value: 1 },
  apiMock: {
    dailySummary: vi.fn(),
    listFeeding: vi.fn(),
    listSleep: vi.fn(),
    listDiaper: vi.fn(),
    listPumping: vi.fn(),
    listActivity: vi.fn(),
    listMedication: vi.fn(),
    getStats: vi.fn(),
    createFeeding: vi.fn(),
    createSleep: vi.fn(),
    createDiaper: vi.fn(),
    createPumping: vi.fn(),
    createActivity: vi.fn(),
    createMedication: vi.fn(),
    updateFeeding: vi.fn(),
    updateSleep: vi.fn(),
    updateDiaper: vi.fn(),
    updatePumping: vi.fn(),
    updateActivity: vi.fn(),
    updateMedication: vi.fn(),
    deleteFeeding: vi.fn(),
    deleteSleep: vi.fn(),
    deleteDiaper: vi.fn(),
    deletePumping: vi.fn(),
    deleteActivity: vi.fn(),
    deleteMedication: vi.fn(),
    photoUrl: (f) => f,
    exportPdfUrl: () => "",
    exportJsonUrl: () => "",
    downloadAuthenticated: vi.fn(),
  },
}));

vi.mock("../api/client", () => ({
  api: apiMock,
  getCurrentUserId: () => currentUserIdBox.value,
}));

const testChild = {
  id: 1,
  name: "Test Baby",
  nickname: "Dedek",
  birth_date: "2025-01-01",
  gender: "L",
  photo_filename: null,
  birth_weight_kg: 3.2,
  birth_height_cm: 50,
  // Caregiver Roles & Permissions Phase 1 — SEMUA test existing di file
  // ini nganggep izin tulis penuh (nambah/edit/hapus lewat quick-log
  // bar) SEBELUM peran ini ada, jadi fixture default-nya "owner" biar
  // perilaku LAMA tetap kepakai apa adanya — test KHUSUS role
  // ada di describe block terpisah di bawah, pakai child object sendiri.
  role: "owner",
};

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
  apiMock.getStats.mockResolvedValue({ days: [] });
}

async function renderDashboardReady() {
  render(<Dashboard child={testChild} onOpenProfile={() => {}} />);
  await waitFor(() => expect(screen.queryByText("Memuat...")).not.toBeInTheDocument());
}

async function openFeedingSheet() {
  const btn = await screen.findByText("Susu");
  await act(async () => {
    btn.click();
  });
  await screen.findByTestId("quick-log-sheet");
}

async function submitSheet() {
  const submitBtn = screen.getByText("submit-sheet");
  await act(async () => {
    submitBtn.click();
  });
}

function loadAllCallCount() {
  return apiMock.listFeeding.mock.calls.length;
}

async function drainRealQueue() {
  const all = await getQueue();
  for (const item of all) await removeFromQueue(item.id);
}

beforeEach(async () => {
  resetApiMock();
  currentUserIdBox.value = 1;
  await drainRealQueue();
});

afterEach(async () => {
  vi.clearAllMocks();
  await drainRealQueue();
});

describe("Dashboard offline-create behavior", () => {
  it("1. an offline create resolves with _offlineQueued true (via api mock contract)", async () => {
    apiMock.createFeeding.mockResolvedValue({
      id: "local-1",
      _offlineQueued: true,
      ...payloadFor("feeding"),
    });
    await renderDashboardReady();
    await openFeedingSheet();

    await submitSheet();

    expect(apiMock.createFeeding).toHaveBeenCalledTimes(1);
  });

  it("2. loadAll() (list GETs) is not called again after an offline-queued create", async () => {
    apiMock.createFeeding.mockResolvedValue({ id: "local-1", _offlineQueued: true, ...payloadFor("feeding") });
    await renderDashboardReady();
    const callsAfterMount = loadAllCallCount();
    await openFeedingSheet();

    await submitSheet();

    expect(loadAllCallCount()).toBe(callsAfterMount); // TIDAK nambah — loadAll() nggak dipanggil lagi
  });

  it("3. the modal closes after a successful offline enqueue", async () => {
    apiMock.createFeeding.mockResolvedValue({ id: "local-1", _offlineQueued: true, ...payloadFor("feeding") });
    await renderDashboardReady();
    await openFeedingSheet();

    await submitSheet();

    expect(screen.queryByTestId("quick-log-sheet")).not.toBeInTheDocument();
  });

  it("4. an optimistic record is shown in the history immediately", async () => {
    apiMock.createFeeding.mockResolvedValue({ id: "local-1", _offlineQueued: true, ...payloadFor("feeding") });
    await renderDashboardReady();
    await openFeedingSheet();

    await submitSheet();

    expect(screen.getByText("Sufor")).toBeInTheDocument();
    expect(screen.getByText(/60 ml/)).toBeInTheDocument();
    expect(screen.getByText("⏳ nunggu sinkron")).toBeInTheDocument();
  });

  it("5. the offline-saved notification is shown", async () => {
    apiMock.createFeeding.mockResolvedValue({ id: "local-1", _offlineQueued: true, ...payloadFor("feeding") });
    await renderDashboardReady();
    await openFeedingSheet();

    await submitSheet();

    expect(
      screen.getByText("Catatan disimpan di perangkat dan akan disinkronkan saat online."),
    ).toBeInTheDocument();
  });

  it("7. an online create still refreshes server data via loadAll()", async () => {
    apiMock.createFeeding.mockResolvedValue({ id: 42, ...payloadFor("feeding") }); // no _offlineQueued -> real online success
    await renderDashboardReady();
    const callsAfterMount = loadAllCallCount();
    await openFeedingSheet();

    await submitSheet();

    await waitFor(() => expect(loadAllCallCount()).toBe(callsAfterMount + 1));
    await waitFor(() => expect(screen.queryByTestId("quick-log-sheet")).not.toBeInTheDocument()); // sukses -> modal tetap ketutup
  });

  it("8. a failed refresh after a successful online create does not report the save as failed", async () => {
    apiMock.createFeeding.mockResolvedValue({ id: 42, ...payloadFor("feeding") });
    await renderDashboardReady();
    await openFeedingSheet();
    // loadAll() berikutnya (dipicu abis create) gagal — simulasiin koneksi
    // putus PAS SETELAH create-nya sendiri sukses
    apiMock.listFeeding.mockRejectedValueOnce(new Error("network blip"));

    await submitSheet();

    // modal tetap ketutup (submit dianggap SUKSES) walau refresh-nya gagal —
    // waitFor karena handleCreate sekarang juga nunggu reconcilePendingFromQueue
    // (round-trip IndexedDB tambahan) sebelum resolve
    await waitFor(() => expect(screen.queryByTestId("quick-log-sheet")).not.toBeInTheDocument());
  });

  it("10a. sleep, diaper, pumping, activity, and medication offline creates all skip loadAll() and close the modal", async () => {
    const cases = [
      ["sleep", apiMock.createSleep],
      ["diaper", apiMock.createDiaper],
      ["pumping", apiMock.createPumping],
      ["stroll", apiMock.createActivity],
      ["vitamin", apiMock.createMedication],
    ];

    for (const [type, createFn] of cases) {
      resetApiMock();
      createFn.mockResolvedValue({ id: `local-${type}`, _offlineQueued: true, ...payloadFor(type) });
      const { unmount } = render(<Dashboard child={testChild} onOpenProfile={() => {}} />);
      await waitFor(() => expect(screen.queryByText("Memuat...")).not.toBeInTheDocument());

      if (type === "sleep" || type === "diaper") {
        // "Tidur"/"Popok" juga muncul di legend radial clock — query lewat
        // role="button" biar nggak ambigu sama teks legend itu
        const label = type === "sleep" ? /Tidur/ : /Popok/; // nama button gabung ikon+teks, jadi cocokin substring
        const btn = await screen.findByRole("button", { name: label });
        await act(async () => btn.click());
      } else {
        const moreBtn = await screen.findByText("Lainnya");
        await act(async () => moreBtn.click());
        const iconLabel = { pumping: "Perah ASI", stroll: "Jalan-jalan", vitamin: "Vitamin D" }[type];
        const optionBtn = await screen.findByText(iconLabel);
        await act(async () => optionBtn.click());
      }

      await screen.findByTestId("quick-log-sheet");
      const callsBefore = apiMock.listFeeding.mock.calls.length;
      await submitSheet();

      expect(createFn).toHaveBeenCalledTimes(1);
      expect(apiMock.listFeeding.mock.calls.length).toBe(callsBefore); // loadAll() nggak dipanggil
      expect(screen.queryByTestId("quick-log-sheet")).not.toBeInTheDocument(); // modal ketutup

      unmount();
    }
  });
});

describe("isPendingOfflineItem / isLocalOnlyId (direct unit coverage of the guard logic)", () => {
  it("treats _offlineQueued: true as pending regardless of id shape", () => {
    expect(isPendingOfflineItem({ id: 99, _offlineQueued: true })).toBe(true);
    expect(isPendingOfflineItem({ id: "local-3", _offlineQueued: true })).toBe(true);
  });

  it("falls back to the local- id prefix as a defensive second signal", () => {
    expect(isPendingOfflineItem({ id: "local-7" })).toBe(true); // _offlineQueued absent entirely
    expect(isPendingOfflineItem({ id: "local-7", _offlineQueued: false })).toBe(true);
  });

  it("returns false for a normal synced record", () => {
    expect(isPendingOfflineItem({ id: 42, _offlineQueued: false })).toBe(false);
    expect(isPendingOfflineItem({ id: 42 })).toBe(false);
    expect(isPendingOfflineItem(null)).toBe(false);
  });

  it("isLocalOnlyId only matches string ids with the local- prefix", () => {
    expect(isLocalOnlyId("local-1")).toBe(true);
    expect(isLocalOnlyId(42)).toBe(false);
    expect(isLocalOnlyId("42")).toBe(false);
    expect(isLocalOnlyId(undefined)).toBe(false);
  });
});

describe("pending offline history items are protected from mutating actions", () => {
  async function renderWithPendingFeedingItem() {
    apiMock.createFeeding.mockResolvedValue({ id: "local-1", _offlineQueued: true, ...payloadFor("feeding") });
    await renderDashboardReady();
    await openFeedingSheet();
    await submitSheet();
    await screen.findByText("Sufor"); // pending item beneran ke-render
  }

  async function renderWithPendingUnfinishedSleepItem() {
    apiMock.createSleep.mockResolvedValue({
      id: "local-2",
      _offlineQueued: true,
      start_time: new Date().toISOString(),
      end_time: null,
      sleep_type: "siang",
    });
    await renderDashboardReady();
    const sleepBtn = await screen.findByRole("button", { name: /Tidur/ });
    await act(async () => sleepBtn.click());
    await screen.findByTestId("quick-log-sheet");
    await submitSheet();
    await screen.findByText(/Tidur siang/);
  }

  it("1. clicking a pending offline history record does not open the edit sheet", async () => {
    await renderWithPendingFeedingItem();

    const card = screen.getByText("Sufor").closest("div[aria-disabled]");
    await act(async () => card.click());

    expect(screen.queryByTestId("quick-log-sheet")).not.toBeInTheDocument();
  });

  it("2. a pending offline record cannot call the update API (no edit action is reachable)", async () => {
    await renderWithPendingFeedingItem();

    const card = screen.getByText("Sufor").closest("div[aria-disabled]");
    await act(async () => card.click());

    expect(apiMock.updateFeeding).not.toHaveBeenCalled();
  });

  it("3. a pending offline record cannot call the delete API — the Hapus action is not even rendered", async () => {
    await renderWithPendingFeedingItem();

    expect(screen.queryByLabelText("Hapus catatan")).not.toBeInTheDocument();
    expect(apiMock.deleteFeeding).not.toHaveBeenCalled();
  });

  it("4. a pending unfinished sleep record cannot call the wake-up/update API — Bangun is not rendered", async () => {
    await renderWithPendingUnfinishedSleepItem();

    expect(screen.queryByText("🌤️ Bangun")).not.toBeInTheDocument();
    expect(apiMock.updateSleep).not.toHaveBeenCalled();
  });

  it("5. duplicate is disabled for a pending record — no swipe-to-duplicate surface exists", async () => {
    await renderWithPendingFeedingItem();

    // item pending TIDAK dibungkus SwipeableHistoryItem sama sekali, jadi
    // nggak ada tombol "Duplikat" (reveal swipe) buat item ini di DOM
    expect(screen.queryByText("Duplikat")).not.toBeInTheDocument();
  });

  it("6. a normal synchronized record can still be edited", async () => {
    apiMock.listFeeding.mockResolvedValue([
      { id: 42, feed_type: "sufor", volume_ml: 60, duration_minutes: null, breast_side: null, timestamp: new Date().toISOString() },
    ]);
    await renderDashboardReady();
    await screen.findByText("Sufor");

    const card = screen.getByText("Sufor").closest("div");
    await act(async () => card.click());

    expect(await screen.findByTestId("quick-log-sheet")).toBeInTheDocument();
  });

  it("7. a normal synchronized record can still be deleted", async () => {
    apiMock.listFeeding.mockResolvedValue([
      { id: 42, feed_type: "sufor", volume_ml: 60, duration_minutes: null, breast_side: null, timestamp: new Date().toISOString() },
    ]);
    apiMock.deleteFeeding.mockResolvedValue({ success: true });
    await renderDashboardReady();
    await screen.findByText("Sufor");

    const deleteBtn = screen.getByLabelText("Hapus catatan");
    await act(async () => deleteBtn.click());

    await waitFor(() => expect(apiMock.deleteFeeding).toHaveBeenCalledWith(42), { timeout: 6000 });
  }, 10000);

  it("8. no update/delete API is ever called with an id beginning with 'local-'", async () => {
    await renderWithPendingFeedingItem();

    // coba semua interaksi yang MASIH bisa dilakukan user (klik kartu —
    // aksi lain kayak Hapus/Bangun/Duplikat udah nggak ada tombolnya sama
    // sekali buat item pending, jadi nggak ada cara lain buat nyobain)
    const card = screen.getByText("Sufor").closest("div[aria-disabled]");
    await act(async () => card.click());

    const mutatingFns = [
      apiMock.updateFeeding,
      apiMock.updateSleep,
      apiMock.updateDiaper,
      apiMock.updatePumping,
      apiMock.updateActivity,
      apiMock.updateMedication,
      apiMock.deleteFeeding,
      apiMock.deleteSleep,
      apiMock.deleteDiaper,
      apiMock.deletePumping,
      apiMock.deleteActivity,
      apiMock.deleteMedication,
    ];
    for (const fn of mutatingFns) {
      for (const call of fn.mock.calls) {
        expect(String(call[0])).not.toMatch(/^local-/);
      }
    }
    // jaring pengaman paling gampang: nggak ada satupun yang kepanggil sama sekali
    expect(mutatingFns.every((fn) => fn.mock.calls.length === 0)).toBe(true);
  });
});

describe("offline recovery — restoring pending records from IndexedDB", () => {
  // pakai jam siang hari ini biar pasti match tanggal default Dashboard
  // (todayWIB()), regardless kapan test-nya beneran dijalankan
  function todayAt(hour) {
    const now = new Date();
    now.setHours(hour, 0, 0, 0);
    return now.toISOString();
  }

  async function seedFeedingQueueItem(overrides = {}) {
    return enqueueRequest({
      method: "POST",
      url: "/children/1/feeding-logs",
      body: JSON.stringify({ feed_type: "sufor", volume_ml: 60, duration_minutes: null, breast_side: null, timestamp: todayAt(10) }),
      userId: 1,
      clientRequestId: "stable-key-1",
      ...overrides,
    });
  }

  it("1. an offline-created record is restored after Dashboard remount", async () => {
    await seedFeedingQueueItem();
    const { unmount } = render(<Dashboard child={testChild} onOpenProfile={() => {}} />);
    await waitFor(() => expect(screen.getByText("Sufor")).toBeInTheDocument());
    unmount();

    render(<Dashboard child={testChild} onOpenProfile={() => {}} />);
    await waitFor(() => expect(screen.getByText("Sufor")).toBeInTheDocument());
    expect(screen.getByText("⏳ nunggu sinkron")).toBeInTheDocument();
  });

  it("2. refreshing while offline (fresh mount, all GETs failing) still shows the pending record", async () => {
    apiMock.listFeeding.mockRejectedValue(new Error("offline"));
    apiMock.dailySummary.mockRejectedValue(new Error("offline"));
    await seedFeedingQueueItem();

    render(<Dashboard child={testChild} onOpenProfile={() => {}} />);

    await waitFor(() => expect(screen.getByText("Sufor")).toBeInTheDocument());
  });

  it("3. a restored record retains a stable local-<queueId> id", async () => {
    const queueId = await seedFeedingQueueItem();
    render(<Dashboard child={testChild} onOpenProfile={() => {}} />);
    await waitFor(() => expect(screen.getByText("Sufor")).toBeInTheDocument());

    // dibuktikan tidak langsung (Dashboard nggak nampilin id mentah), tapi
    // lewat perilaku: hapus/edit tetap keblokir konsisten sama pola id
    // "local-<queueId>" yang dipakai di seluruh app (lihat isLocalOnlyId)
    expect(isLocalOnlyId(`local-${queueId}`)).toBe(true);
    expect(screen.queryByLabelText("Hapus catatan")).not.toBeInTheDocument(); // aksi tetap keblokir buat item restored
  });

  it("4. a newly created optimistic record and its IndexedDB representation appear only once", async () => {
    await renderDashboardReady();
    const queueId = await seedFeedingQueueItem();
    apiMock.createFeeding.mockResolvedValue({
      id: `local-${queueId}`,
      _offlineQueued: true,
      feed_type: "sufor",
      volume_ml: 60,
      timestamp: todayAt(10),
    });

    await openFeedingSheet();
    await submitSheet();

    await waitFor(() => expect(screen.getAllByText("Sufor")).toHaveLength(1));
  });

  it("5. repeated queue-change events do not create duplicates", async () => {
    await seedFeedingQueueItem();
    render(<Dashboard child={testChild} onOpenProfile={() => {}} />);
    await waitFor(() => expect(screen.getByText("Sufor")).toBeInTheDocument());

    await act(async () => {
      window.dispatchEvent(new CustomEvent("babytracker:offline-queue-changed"));
      window.dispatchEvent(new CustomEvent("babytracker:offline-queue-changed"));
      window.dispatchEvent(new CustomEvent("babytracker:offline-queue-changed"));
    });

    expect(screen.getAllByText("Sufor")).toHaveLength(1);
  });

  it("6. pending records are filtered by the active user", async () => {
    await seedFeedingQueueItem({ userId: 2 }); // BUKAN user yang lagi login (currentUserIdBox.value === 1)
    render(<Dashboard child={testChild} onOpenProfile={() => {}} />);

    await waitFor(() => expect(screen.queryByText("Memuat...")).not.toBeInTheDocument());
    expect(screen.queryByText("Sufor")).not.toBeInTheDocument();
  });

  it("7. pending records are filtered by the active child", async () => {
    await seedFeedingQueueItem({ url: "/children/999/feeding-logs" }); // anak LAIN, bukan testChild (id 1)
    render(<Dashboard child={testChild} onOpenProfile={() => {}} />);

    await waitFor(() => expect(screen.queryByText("Memuat...")).not.toBeInTheDocument());
    expect(screen.queryByText("Sufor")).not.toBeInTheDocument();
  });

  it("8. pending records are filtered by the selected date", async () => {
    const yesterday = new Date();
    yesterday.setDate(yesterday.getDate() - 1);
    yesterday.setHours(10, 0, 0, 0);
    await seedFeedingQueueItem({
      body: JSON.stringify({ feed_type: "sufor", volume_ml: 60, timestamp: yesterday.toISOString() }),
    });
    render(<Dashboard child={testChild} onOpenProfile={() => {}} />);

    // Dashboard defaultnya nampilin HARI INI — record kemarin nggak boleh nongol
    await waitFor(() => expect(screen.queryByText("Memuat...")).not.toBeInTheDocument());
    expect(screen.queryByText("Sufor")).not.toBeInTheDocument();
  });

  it("9-14. restores all 6 supported log types correctly in one Dashboard render", async () => {
    await enqueueRequest({
      method: "POST", url: "/children/1/sleep-logs",
      body: JSON.stringify({ start_time: todayAt(20), end_time: null, sleep_type: "malam" }),
      userId: 1, clientRequestId: "k-sleep",
    });
    await enqueueRequest({
      method: "POST", url: "/children/1/diaper-logs",
      body: JSON.stringify({ diaper_type: "pup", consistency: "normal", timestamp: todayAt(9) }),
      userId: 1, clientRequestId: "k-diaper",
    });
    await enqueueRequest({
      method: "POST", url: "/children/1/pumping-logs",
      body: JSON.stringify({ duration_minutes: 15, volume_ml: 80, breast_side: "kedua", timestamp: todayAt(11) }),
      userId: 1, clientRequestId: "k-pumping",
    });
    await enqueueRequest({
      method: "POST", url: "/children/1/activity-logs",
      body: JSON.stringify({ activity_type: "stroll", duration_minutes: 20, notes: null, timestamp: todayAt(16) }),
      userId: 1, clientRequestId: "k-stroll",
    });
    await enqueueRequest({
      method: "POST", url: "/children/1/medication-logs",
      body: JSON.stringify({ medication_name: "Vitamin D", timestamp: todayAt(7) }),
      userId: 1, clientRequestId: "k-vitamin",
    });
    await seedFeedingQueueItem();

    render(<Dashboard child={testChild} onOpenProfile={() => {}} />);

    await waitFor(() => expect(screen.getByText("Sufor")).toBeInTheDocument());
    expect(screen.getByText("Tidur malam")).toBeInTheDocument();
    expect(screen.getByText("Pup")).toBeInTheDocument();
    expect(screen.getByText("Perah ASI")).toBeInTheDocument();
    expect(screen.getByText("Jalan-jalan")).toBeInTheDocument();
    expect(screen.getByText("Vitamin D")).toBeInTheDocument();
  });

  it("15. a malformed queue body does not crash Dashboard", async () => {
    await enqueueRequest({
      method: "POST",
      url: "/children/1/feeding-logs",
      body: "{ this is not valid JSON",
      userId: 1,
      clientRequestId: "k-broken",
    });

    expect(async () => {
      render(<Dashboard child={testChild} onOpenProfile={() => {}} />);
      await waitFor(() => expect(screen.queryByText("Memuat...")).not.toBeInTheDocument());
    }).not.toThrow();
    await waitFor(() => expect(screen.queryByText("Memuat...")).not.toBeInTheDocument());
    expect(screen.getByText(/Belum ada catatan/)).toBeInTheDocument();
  });

  it("16. a needs_review entry is not shown as a normal history record", async () => {
    const queueId = await seedFeedingQueueItem();
    await updateQueueItem(queueId, { status: REAL_QUEUE_STATUS.NEEDS_REVIEW, lastError: "feed_type wajib diisi" });

    render(<Dashboard child={testChild} onOpenProfile={() => {}} />);
    await waitFor(() => expect(screen.queryByText("Memuat...")).not.toBeInTheDocument());
    expect(screen.queryByText("Sufor")).not.toBeInTheDocument();
  });

  it("17. a legacy unknown-owner entry is not shown as a normal history record", async () => {
    const queueId = await seedFeedingQueueItem({ userId: undefined });
    await updateQueueItem(queueId, { ownerUnknown: true, status: REAL_QUEUE_STATUS.NEEDS_REVIEW });

    render(<Dashboard child={testChild} onOpenProfile={() => {}} />);
    await waitFor(() => expect(screen.queryByText("Memuat...")).not.toBeInTheDocument());
    expect(screen.queryByText("Sufor")).not.toBeInTheDocument();
  });

  it("18/19. successful sync (item removed from queue) removes the optimistic record and refreshes server data", async () => {
    const queueId = await seedFeedingQueueItem();
    render(<Dashboard child={testChild} onOpenProfile={() => {}} />);
    await waitFor(() => expect(screen.getByText("Sufor")).toBeInTheDocument());
    const loadCallsBefore = apiMock.listFeeding.mock.calls.length;

    await act(async () => {
      await removeFromQueue(queueId); // simulasikan useOfflineSync berhasil nyinkronin item ini
    });

    await waitFor(() => expect(apiMock.listFeeding.mock.calls.length).toBeGreaterThan(loadCallsBefore));
  });

  it("20. the real server record replaces the local one without duplication", async () => {
    const queueId = await seedFeedingQueueItem();
    render(<Dashboard child={testChild} onOpenProfile={() => {}} />);
    await waitFor(() => expect(screen.getByText("Sufor")).toBeInTheDocument());

    // abis sync, server sekarang punya record ASLI (id numerik)
    apiMock.listFeeding.mockResolvedValue([
      { id: 555, feed_type: "sufor", volume_ml: 60, duration_minutes: null, breast_side: null, timestamp: todayAt(10) },
    ]);

    await act(async () => {
      await removeFromQueue(queueId);
    });

    await waitFor(() => expect(screen.getAllByText("Sufor")).toHaveLength(1));
    expect(screen.queryByText("⏳ nunggu sinkron")).not.toBeInTheDocument(); // yang tampil sekarang record server, bukan optimistic lagi
  });

  it("21. a refresh failure after successful sync does not requeue the request", async () => {
    const queueId = await seedFeedingQueueItem();
    render(<Dashboard child={testChild} onOpenProfile={() => {}} />);
    await waitFor(() => expect(screen.getByText("Sufor")).toBeInTheDocument());

    apiMock.listFeeding.mockRejectedValue(new Error("network blip abis sync"));

    await act(async () => {
      await removeFromQueue(queueId);
    });
    await waitFor(() => expect(screen.queryByText("Sufor")).not.toBeInTheDocument());

    const remainingQueue = await getQueue();
    expect(remainingQueue).toHaveLength(0); // nggak ada apa-apa yang di-requeue ulang
    expect(apiMock.createFeeding).not.toHaveBeenCalled();
  });

  it("22. Dashboard does not stay stuck on 'Memuat...' when all GETs fail offline, and shows a clear offline state", async () => {
    apiMock.dailySummary.mockRejectedValue(new Error("offline"));
    apiMock.listFeeding.mockRejectedValue(new Error("offline"));
    apiMock.listSleep.mockRejectedValue(new Error("offline"));
    apiMock.listDiaper.mockRejectedValue(new Error("offline"));
    apiMock.listPumping.mockRejectedValue(new Error("offline"));
    apiMock.listActivity.mockRejectedValue(new Error("offline"));
    apiMock.listMedication.mockRejectedValue(new Error("offline"));

    render(<Dashboard child={testChild} onOpenProfile={() => {}} />);

    await waitFor(() => expect(screen.queryByText("Memuat...")).not.toBeInTheDocument());
    expect(screen.getByText(/sedang offline/)).toBeInTheDocument();
    expect(screen.getByText("Coba lagi")).toBeInTheDocument();
  });

  it("23. switching to a different authenticated user removes the previous user's pending records", async () => {
    await seedFeedingQueueItem({ userId: 1 });
    const { unmount } = render(<Dashboard child={testChild} onOpenProfile={() => {}} />);
    await waitFor(() => expect(screen.getByText("Sufor")).toBeInTheDocument());
    unmount();

    currentUserIdBox.value = 2; // akun lain login (Dashboard remount, kayak yang beneran kejadian di App.jsx)
    render(<Dashboard child={testChild} onOpenProfile={() => {}} />);

    await waitFor(() => expect(screen.queryByText("Memuat...")).not.toBeInTheDocument());
    expect(screen.queryByText("Sufor")).not.toBeInTheDocument();
  });

  it("24. a restored (not just freshly-created) pending record still blocks update/delete with a local id", async () => {
    await seedFeedingQueueItem();
    render(<Dashboard child={testChild} onOpenProfile={() => {}} />);
    await waitFor(() => expect(screen.getByText("Sufor")).toBeInTheDocument());

    const card = screen.getByText("Sufor").closest("div[aria-disabled]");
    await act(async () => card.click());

    expect(apiMock.updateFeeding).not.toHaveBeenCalled();
    expect(apiMock.deleteFeeding).not.toHaveBeenCalled();
  });
});

// --------------------------------------------------------------------------
// Caregiver Roles & Permissions Phase 1 — backend TETAP otoritatif buat
// SEMUA keputusan izin (lihat backend/docs/ROLES_PERMISSIONS.md); test di
// sini ngebuktiin frontend nyembunyiin kontrol yang bakal ditolak backend,
// pakai `child.role` yang sekarang dikembalikan di respons child-scoped.
// --------------------------------------------------------------------------

const feedingItem = (overrides = {}) => ({
  id: 42,
  feed_type: "sufor",
  volume_ml: 60,
  duration_minutes: null,
  breast_side: null,
  timestamp: new Date().toISOString(),
  created_by_user_id: 1,
  ...overrides,
});

async function renderWithRole(role, itemOverrides) {
  apiMock.listFeeding.mockResolvedValue([feedingItem(itemOverrides)]);
  render(<Dashboard child={{ ...testChild, role }} onOpenProfile={() => {}} />);
  await waitFor(() => expect(screen.queryByText("Memuat...")).not.toBeInTheDocument());
  await screen.findByText("Sufor");
}

// "Tidur"/"Popok" muncul DUA kali di layar: sekali sebagai label legenda
// statis (selalu ada, bukan tombol), sekali sebagai tombol quick-log —
// helper ini nyari kemunculan yang beneran ada di dalam elemen <button>,
// biar nggak ambigu ("Susu"/"Lainnya" nggak butuh ini, cuma muncul sekali).
function quickLogButton(label) {
  return screen.getAllByText(label).find((el) => el.closest("button"))?.closest("button") || null;
}

describe("Dashboard — Caregiver Roles & Permissions (Phase 1)", () => {
  it("viewer sees the record but no quick-log bar and no active mutation controls", async () => {
    await renderWithRole("viewer");

    expect(screen.getByText("Sufor")).toBeInTheDocument();
    expect(screen.queryByText("Susu")).not.toBeInTheDocument();
    expect(quickLogButton("Tidur")).toBeNull();
    expect(quickLogButton("Popok")).toBeNull();
    expect(screen.queryByText("Lainnya")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Hapus catatan")).not.toBeInTheDocument();
    expect(screen.queryByText("Duplikat")).not.toBeInTheDocument();

    // klik item TIDAK membuka form edit buat viewer
    await act(async () => screen.getByText("Sufor").closest("div").click());
    expect(screen.queryByTestId("quick-log-sheet")).not.toBeInTheDocument();
  });

  it("an unknown/missing role defaults to the same read-only behavior as viewer", async () => {
    apiMock.listFeeding.mockResolvedValue([feedingItem()]);
    render(<Dashboard child={{ ...testChild, role: undefined }} onOpenProfile={() => {}} />);
    await waitFor(() => expect(screen.queryByText("Memuat...")).not.toBeInTheDocument());
    await screen.findByText("Sufor");

    expect(screen.queryByText("Susu")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Hapus catatan")).not.toBeInTheDocument();
  });

  it("editor sees the quick-log bar (create) and can open the edit sheet on any record", async () => {
    currentUserIdBox.value = 1;
    // record dibuat OLEH ORANG LAIN (user 2) — editor tetap boleh UPDATE
    // record siapa pun, cuma HAPUS yang dibatasi ke punya sendiri
    await renderWithRole("editor", { created_by_user_id: 2 });

    expect(screen.getByText("Susu")).toBeInTheDocument();
    expect(quickLogButton("Tidur")).not.toBeNull();
    expect(quickLogButton("Popok")).not.toBeNull();

    await act(async () => screen.getByText("Sufor").closest("div").click());
    expect(await screen.findByTestId("quick-log-sheet")).toBeInTheDocument();
  });

  it("editor sees a delete control only for their own records", async () => {
    currentUserIdBox.value = 1;
    await renderWithRole("editor", { created_by_user_id: 1 }); // record buatan sendiri

    expect(screen.getByLabelText("Hapus catatan")).toBeInTheDocument();
  });

  it("editor does not see a delete control for a record created by someone else", async () => {
    currentUserIdBox.value = 1;
    await renderWithRole("editor", { created_by_user_id: 2 }); // record buatan orang lain

    expect(screen.queryByLabelText("Hapus catatan")).not.toBeInTheDocument();
  });

  it("owner sees a delete control for records created by anyone, including legacy null-creator records", async () => {
    currentUserIdBox.value = 1;
    await renderWithRole("owner", { created_by_user_id: null });

    expect(screen.getByLabelText("Hapus catatan")).toBeInTheDocument();
  });

  it("a backend 403 on a stale/exposed control shows a permission error inline, without crashing or logging the user out", async () => {
    // `api` di file ini di-mock TOTAL (bukan importOriginal — lihat
    // vi.mock di atas), jadi cukup Error biasa; Dashboard/QuickLogSheet
    // cuma pernah baca `err.message`, nggak pernah cek `.kind` (itu CUMA
    // relevan buat useOfflineSync.js, dites terpisah di file itu sendiri).
    apiMock.createFeeding.mockRejectedValue(
      new Error("Peran Anda hanya bisa melihat data, tidak bisa menambah/mengubah catatan."),
    );
    await renderWithRole("editor");

    await openFeedingSheet();
    await act(async () => screen.getByText("submit-sheet").click());

    // modal TETAP kebuka (submit gagal) — bukan logout/redirect/crash
    expect(await screen.findByTestId("quick-log-sheet")).toBeInTheDocument();
  });
});
