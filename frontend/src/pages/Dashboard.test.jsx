import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, render, screen, waitFor } from "@testing-library/react";
import Dashboard from "./Dashboard";

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
const { apiMock } = vi.hoisted(() => ({
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
    photoUrl: (f) => f,
    exportPdfUrl: () => "",
    exportJsonUrl: () => "",
    downloadAuthenticated: vi.fn(),
  },
}));

vi.mock("../api/client", () => ({ api: apiMock }));

const testChild = {
  id: 1,
  name: "Test Baby",
  nickname: "Dedek",
  birth_date: "2025-01-01",
  gender: "L",
  photo_filename: null,
  birth_weight_kg: 3.2,
  birth_height_cm: 50,
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

beforeEach(() => {
  resetApiMock();
});

afterEach(() => {
  vi.clearAllMocks();
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
    expect(screen.queryByTestId("quick-log-sheet")).not.toBeInTheDocument(); // sukses -> modal tetap ketutup
  });

  it("8. a failed refresh after a successful online create does not report the save as failed", async () => {
    apiMock.createFeeding.mockResolvedValue({ id: 42, ...payloadFor("feeding") });
    await renderDashboardReady();
    await openFeedingSheet();
    // loadAll() berikutnya (dipicu abis create) gagal — simulasiin koneksi
    // putus PAS SETELAH create-nya sendiri sukses
    apiMock.listFeeding.mockRejectedValueOnce(new Error("network blip"));

    await submitSheet();

    // modal tetap ketutup (submit dianggap SUKSES) walau refresh-nya gagal
    expect(screen.queryByTestId("quick-log-sheet")).not.toBeInTheDocument();
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
