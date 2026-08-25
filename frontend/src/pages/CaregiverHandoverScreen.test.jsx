import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import CaregiverHandoverScreen from "./CaregiverHandoverScreen";

const { apiMock } = vi.hoisted(() => ({
  apiMock: {
    getCaregiverHandover: vi.fn(),
    createCaregiverHandover: vi.fn(),
    updateCaregiverHandover: vi.fn(),
    acknowledgeCaregiverHandover: vi.fn(),
    closeCaregiverHandover: vi.fn(),
  },
}));

vi.mock("../api/client", async (importOriginal) => {
  const actual = await importOriginal();
  return { ...actual, api: apiMock };
});

const { ApiError } = await import("../api/client");

const testChild = { id: 10, name: "Anak Satu", nickname: "Dedek", role: "owner" };
const CURRENT_USER_ID = 1;

function setOnline(value) {
  Object.defineProperty(window.navigator, "onLine", { value, configurable: true });
}

function setVisibility(state) {
  Object.defineProperty(document, "visibilityState", { value: state, configurable: true });
}

function fireVisibilityChange() {
  document.dispatchEvent(new Event("visibilitychange"));
}

const OFFLINE_MESSAGE = "Butuh koneksi internet untuk membuka atau memperbarui Serah Terima Pengasuh.";

function makeSummary(overrides = {}) {
  return {
    window_start: "2026-08-22T14:30:00+07:00",
    as_of_at: "2026-08-23T14:30:00+07:00",
    timezone: "Asia/Jakarta",
    generated_at: "2026-08-23T14:30:00+07:00",
    child_display_name: "Dedek",
    creator_display_name: "Ibu",
    status: "open",
    disclaimer: "Serah terima ini merangkum catatan yang dimasukkan sendiri oleh caregiver dan bukan diagnosis, saran pengobatan, atau rekomendasi penanganan darurat.",
    privacy_note: "Ringkasan ini berisi data perawatan anak yang cukup pribadi.",
    feeding: { total_events: 0, latest_timestamp: null, latest_feed_type: null, latest_volume_ml: null, measured_total_volume_ml: 0 },
    sleep: { total_events: 0, latest_start_time: null, latest_end_time: null, latest_is_ongoing: false, total_completed_minutes: 0 },
    diaper: { total_events: 0, latest_timestamp: null, latest_diaper_type: null, wet_count: 0, dirty_count: 0, mixed_count: 0 },
    pumping: { total_events: 0, latest_timestamp: null, measured_total_volume_ml: 0 },
    activity_mood: { activity_total_events: 0, latest_activity_type: null, latest_activity_timestamp: null, mood_total_events: 0, latest_mood: null, latest_mood_timestamp: null },
    health: { latest_temperature_celsius: null, latest_temperature_at: null, illnesses_overlapping_window: [], latest_doctor_visit_date: null, latest_doctor_visit_reason: null },
    medication: { administered_in_window: [], skipped_in_window: [], overdue_as_of_as_of_at: [], next_occurrence: null },
    reminders: { resolved_in_window: [], overdue_as_of_as_of_at: [], next_occurrence: null },
    ...overrides,
  };
}

function makeHandover(overrides = {}) {
  return {
    id: 5, child_id: 10, created_by_user_id: 1, created_by_name: "Ibu",
    window_start: "2026-08-22T14:30:00+07:00", as_of_at: "2026-08-23T14:30:00+07:00",
    note: null, status: "open",
    created_at: "2026-08-23T14:30:00Z", updated_at: "2026-08-23T14:30:00Z",
    closed_at: null, closed_by_name: null,
    ...overrides,
  };
}

function makeCapabilities(overrides = {}) {
  return { can_view: true, can_create: true, can_edit: true, can_close: true, can_acknowledge: true, ...overrides };
}

function makeNoHandoverResponse(capOverrides = {}) {
  return { handover: null, summary: null, acknowledgements: [], capabilities: makeCapabilities({ can_edit: false, can_close: false, can_acknowledge: false, ...capOverrides }) };
}

function makeWithHandoverResponse(overrides = {}) {
  return {
    handover: makeHandover(overrides.handover),
    summary: makeSummary(overrides.summary),
    acknowledgements: overrides.acknowledgements || [],
    capabilities: makeCapabilities(overrides.capabilities),
  };
}

beforeEach(() => {
  setOnline(true);
  setVisibility("visible");
  localStorage.clear();
  sessionStorage.clear();
  Object.values(apiMock).forEach((fn) => fn.mockReset());
});

afterEach(() => {
  vi.clearAllTimers();
  vi.useRealTimers();
});

describe("CaregiverHandoverScreen — loading/no-handover/error/forbidden states", () => {
  it("shows a loading state while the request is in flight", async () => {
    let resolvePromise;
    apiMock.getCaregiverHandover.mockReturnValue(new Promise((resolve) => { resolvePromise = resolve; }));
    render(<CaregiverHandoverScreen child={testChild} currentUserId={CURRENT_USER_ID} onClose={() => {}} />);
    expect(screen.getByText("Memuat...")).toBeInTheDocument();
    resolvePromise(makeNoHandoverResponse());
    await waitFor(() => expect(screen.queryByText("Memuat...")).not.toBeInTheDocument());
  });

  it("shows the no-open-handover empty state with a create control for a capable role", async () => {
    apiMock.getCaregiverHandover.mockResolvedValue(makeNoHandoverResponse({ can_create: true }));
    render(<CaregiverHandoverScreen child={testChild} currentUserId={CURRENT_USER_ID} onClose={() => {}} />);
    expect(await screen.findByText(/Belum ada Serah Terima/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Buat Serah Terima" })).toBeInTheDocument();
  });

  it("never shows the create control before capabilities are known (while loading)", async () => {
    let resolvePromise;
    apiMock.getCaregiverHandover.mockReturnValue(new Promise((resolve) => { resolvePromise = resolve; }));
    render(<CaregiverHandoverScreen child={testChild} currentUserId={CURRENT_USER_ID} onClose={() => {}} />);
    expect(screen.queryByRole("button", { name: "Buat Serah Terima" })).not.toBeInTheDocument();
    resolvePromise(makeNoHandoverResponse({ can_create: true }));
    await screen.findByRole("button", { name: "Buat Serah Terima" });
  });

  it("viewer never sees the create control, even with no open handover", async () => {
    apiMock.getCaregiverHandover.mockResolvedValue(makeNoHandoverResponse({ can_create: false }));
    render(<CaregiverHandoverScreen child={{ ...testChild, role: "viewer" }} currentUserId={2} onClose={() => {}} />);
    await screen.findByText(/Belum ada Serah Terima/);
    expect(screen.queryByRole("button", { name: "Buat Serah Terima" })).not.toBeInTheDocument();
  });

  it("shows a forbidden state for a 404/forbidden response", async () => {
    apiMock.getCaregiverHandover.mockRejectedValue(new ApiError({ kind: "forbidden", status: 403, message: "Anda tidak punya akses." }));
    render(<CaregiverHandoverScreen child={testChild} currentUserId={CURRENT_USER_ID} onClose={() => {}} />);
    expect(await screen.findByText("Tidak punya akses")).toBeInTheDocument();
    expect(screen.getByText("Anda tidak punya akses.")).toBeInTheDocument();
  });

  it("shows a retryable error state on a non-network failure", async () => {
    apiMock.getCaregiverHandover.mockRejectedValue(new ApiError({ kind: "server_error", status: 500, message: "Gagal memuat." }));
    render(<CaregiverHandoverScreen child={testChild} currentUserId={CURRENT_USER_ID} onClose={() => {}} />);
    expect(await screen.findByText("Gagal memuat.")).toBeInTheDocument();
    const retryBtn = screen.getByRole("button", { name: "Coba lagi" });
    apiMock.getCaregiverHandover.mockResolvedValue(makeNoHandoverResponse());
    fireEvent.click(retryBtn);
    await screen.findByText(/Belum ada Serah Terima/);
  });

  it("shows the exact offline message with no cached data at all while offline", async () => {
    setOnline(false);
    render(<CaregiverHandoverScreen child={testChild} currentUserId={CURRENT_USER_ID} onClose={() => {}} />);
    expect(await screen.findByText(OFFLINE_MESSAGE)).toBeInTheDocument();
    expect(apiMock.getCaregiverHandover).not.toHaveBeenCalled();
  });
});

describe("CaregiverHandoverScreen — create flow", () => {
  it("creates a handover with a note and shows the resulting summary", async () => {
    apiMock.getCaregiverHandover.mockResolvedValue(makeNoHandoverResponse({ can_create: true }));
    apiMock.createCaregiverHandover.mockResolvedValue(makeWithHandoverResponse({ handover: { note: "Cek suhu sore ini" } }));
    render(<CaregiverHandoverScreen child={testChild} currentUserId={CURRENT_USER_ID} onClose={() => {}} />);
    await screen.findByRole("button", { name: "Buat Serah Terima" });

    fireEvent.change(screen.getByPlaceholderText(/Catatan buat caregiver berikutnya/), { target: { value: "Cek suhu sore ini" } });
    fireEvent.click(screen.getByRole("button", { name: "Buat Serah Terima" }));

    await waitFor(() => expect(apiMock.createCaregiverHandover).toHaveBeenCalledWith(testChild.id, "Cek suhu sore ini"));
    expect(await screen.findByText("Cek suhu sore ini")).toBeInTheDocument();
  });

  it("double-submit protection: a second click before the first request resolves does not send a second request", async () => {
    apiMock.getCaregiverHandover.mockResolvedValue(makeNoHandoverResponse({ can_create: true }));
    let resolveCreate;
    apiMock.createCaregiverHandover.mockReturnValue(new Promise((resolve) => { resolveCreate = resolve; }));
    render(<CaregiverHandoverScreen child={testChild} currentUserId={CURRENT_USER_ID} onClose={() => {}} />);
    const btn = await screen.findByRole("button", { name: "Buat Serah Terima" });
    fireEvent.click(btn);
    fireEvent.click(btn);
    fireEvent.click(btn);
    await waitFor(() => expect(apiMock.createCaregiverHandover).toHaveBeenCalledTimes(1));
    resolveCreate(makeWithHandoverResponse());
  });

  it("shows a deterministic conflict message and reloads on a 409", async () => {
    apiMock.getCaregiverHandover
      .mockResolvedValueOnce(makeNoHandoverResponse({ can_create: true }))
      .mockResolvedValueOnce(makeWithHandoverResponse());
    apiMock.createCaregiverHandover.mockRejectedValue(new ApiError({ kind: "http_error", status: 409, message: "Sudah ada." }));
    render(<CaregiverHandoverScreen child={testChild} currentUserId={CURRENT_USER_ID} onClose={() => {}} />);
    fireEvent.click(await screen.findByRole("button", { name: "Buat Serah Terima" }));

    expect(await screen.findByText(/sudah diperbarui/)).toBeInTheDocument();
    expect(apiMock.getCaregiverHandover).toHaveBeenCalledTimes(2);
  });
});

describe("CaregiverHandoverScreen — role-aware controls", () => {
  it("owner sees edit and close controls on an open handover", async () => {
    apiMock.getCaregiverHandover.mockResolvedValue(makeWithHandoverResponse({ capabilities: { can_edit: true, can_close: true } }));
    render(<CaregiverHandoverScreen child={testChild} currentUserId={CURRENT_USER_ID} onClose={() => {}} />);
    await screen.findByText("ℹ️ Ringkasan");
    expect(screen.getByText("Ubah catatan")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Tutup Serah Terima" })).toBeInTheDocument();
  });

  it("viewer sees only the acknowledge control, never edit/close", async () => {
    apiMock.getCaregiverHandover.mockResolvedValue(
      makeWithHandoverResponse({ capabilities: { can_edit: false, can_close: false, can_acknowledge: true } }),
    );
    render(<CaregiverHandoverScreen child={{ ...testChild, role: "viewer" }} currentUserId={2} onClose={() => {}} />);
    await screen.findByText("ℹ️ Ringkasan");
    expect(screen.queryByText("Ubah catatan")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Tutup Serah Terima" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Tandai sudah dibaca" })).toBeInTheDocument();
  });

  it("editor who is not the creator sees neither edit nor close", async () => {
    apiMock.getCaregiverHandover.mockResolvedValue(
      makeWithHandoverResponse({ capabilities: { can_edit: false, can_close: false, can_acknowledge: true } }),
    );
    render(<CaregiverHandoverScreen child={{ ...testChild, role: "editor" }} currentUserId={3} onClose={() => {}} />);
    await screen.findByText("ℹ️ Ringkasan");
    expect(screen.queryByText("Ubah catatan")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Tutup Serah Terima" })).not.toBeInTheDocument();
  });
});

describe("CaregiverHandoverScreen — update note", () => {
  it("edits and saves a note", async () => {
    apiMock.getCaregiverHandover.mockResolvedValue(makeWithHandoverResponse({ handover: { note: "lama" } }));
    apiMock.updateCaregiverHandover.mockResolvedValue(makeWithHandoverResponse({ handover: { note: "baru" } }));
    render(<CaregiverHandoverScreen child={testChild} currentUserId={CURRENT_USER_ID} onClose={() => {}} />);
    await screen.findByText("lama");

    fireEvent.click(screen.getByText("Ubah catatan"));
    const textarea = screen.getByDisplayValue("lama");
    fireEvent.change(textarea, { target: { value: "baru" } });
    fireEvent.click(screen.getByRole("button", { name: "Simpan" }));

    await waitFor(() => expect(apiMock.updateCaregiverHandover).toHaveBeenCalledWith(5, "baru"));
    expect(await screen.findByText("baru")).toBeInTheDocument();
  });

  it("shows a deterministic message and reloads when the handover was already closed by someone else", async () => {
    apiMock.getCaregiverHandover
      .mockResolvedValueOnce(makeWithHandoverResponse({ handover: { note: "lama" } }))
      .mockResolvedValueOnce(makeWithHandoverResponse({ handover: { status: "closed" }, capabilities: { can_edit: false, can_close: false } }));
    apiMock.updateCaregiverHandover.mockRejectedValue(new ApiError({ kind: "validation", status: 400, message: "Sudah ditutup." }));
    render(<CaregiverHandoverScreen child={testChild} currentUserId={CURRENT_USER_ID} onClose={() => {}} />);
    await screen.findByText("lama");
    fireEvent.click(screen.getByText("Ubah catatan"));
    fireEvent.click(screen.getByRole("button", { name: "Simpan" }));

    expect(await screen.findByText(/sudah ditutup/)).toBeInTheDocument();
  });
});

describe("CaregiverHandoverScreen — acknowledge", () => {
  it("acknowledges and reflects the caregiver in the list", async () => {
    apiMock.getCaregiverHandover
      .mockResolvedValueOnce(makeWithHandoverResponse())
      .mockResolvedValueOnce(makeWithHandoverResponse({ acknowledgements: [{ id: 1, user_id: 1, display_name: "Ibu", acknowledged_at: "2026-08-23T15:00:00+07:00" }] }));
    apiMock.acknowledgeCaregiverHandover.mockResolvedValue({ acknowledgement: { id: 1 }, created: true });
    render(<CaregiverHandoverScreen child={testChild} currentUserId={CURRENT_USER_ID} onClose={() => {}} />);
    fireEvent.click(await screen.findByRole("button", { name: "Tandai sudah dibaca" }));

    await waitFor(() => expect(apiMock.acknowledgeCaregiverHandover).toHaveBeenCalledWith(5));
    expect(await screen.findByText(/Ibu \(Anda\)/)).toBeInTheDocument();
  });

  it("shows an already-acknowledged state and disables further clicks", async () => {
    apiMock.getCaregiverHandover.mockResolvedValue(
      makeWithHandoverResponse({ acknowledgements: [{ id: 1, user_id: CURRENT_USER_ID, display_name: "Ibu", acknowledged_at: "2026-08-23T15:00:00+07:00" }] }),
    );
    render(<CaregiverHandoverScreen child={testChild} currentUserId={CURRENT_USER_ID} onClose={() => {}} />);
    const btn = await screen.findByRole("button", { name: /Sudah ditandai dibaca/ });
    expect(btn).toBeDisabled();
  });

  it("double-submit protection on acknowledge", async () => {
    apiMock.getCaregiverHandover.mockResolvedValue(makeWithHandoverResponse());
    let resolveAck;
    apiMock.acknowledgeCaregiverHandover.mockReturnValue(new Promise((resolve) => { resolveAck = resolve; }));
    render(<CaregiverHandoverScreen child={testChild} currentUserId={CURRENT_USER_ID} onClose={() => {}} />);
    const btn = await screen.findByRole("button", { name: "Tandai sudah dibaca" });
    fireEvent.click(btn);
    fireEvent.click(btn);
    await waitFor(() => expect(apiMock.acknowledgeCaregiverHandover).toHaveBeenCalledTimes(1));
    resolveAck({ acknowledgement: { id: 1 }, created: true });
  });
});

describe("CaregiverHandoverScreen — close", () => {
  it("requires confirmation before closing", async () => {
    apiMock.getCaregiverHandover.mockResolvedValue(makeWithHandoverResponse());
    render(<CaregiverHandoverScreen child={testChild} currentUserId={CURRENT_USER_ID} onClose={() => {}} />);
    fireEvent.click(await screen.findByRole("button", { name: "Tutup Serah Terima" }));
    expect(apiMock.closeCaregiverHandover).not.toHaveBeenCalled();
    expect(await screen.findByText(/Yakin mau menutup/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Ya, tutup" }));
    await waitFor(() => expect(apiMock.closeCaregiverHandover).toHaveBeenCalledWith(5));
  });

  it("canceling the confirmation does not close", async () => {
    apiMock.getCaregiverHandover.mockResolvedValue(makeWithHandoverResponse());
    render(<CaregiverHandoverScreen child={testChild} currentUserId={CURRENT_USER_ID} onClose={() => {}} />);
    fireEvent.click(await screen.findByRole("button", { name: "Tutup Serah Terima" }));
    fireEvent.click(await screen.findByRole("button", { name: "Batal" }));
    expect(apiMock.closeCaregiverHandover).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Tutup Serah Terima" })).toBeInTheDocument();
  });
});

describe("CaregiverHandoverScreen — background polling & visibility", () => {
  it("polls every 60 seconds while the tab is visible and online", async () => {
    apiMock.getCaregiverHandover.mockResolvedValue(makeNoHandoverResponse());
    vi.useFakeTimers({ shouldAdvanceTime: true });
    render(<CaregiverHandoverScreen child={testChild} currentUserId={CURRENT_USER_ID} onClose={() => {}} />);
    await vi.waitFor(() => expect(apiMock.getCaregiverHandover).toHaveBeenCalledTimes(1));

    await vi.advanceTimersByTimeAsync(60000);
    expect(apiMock.getCaregiverHandover).toHaveBeenCalledTimes(2);

    await vi.advanceTimersByTimeAsync(60000);
    expect(apiMock.getCaregiverHandover).toHaveBeenCalledTimes(3);
  });

  it("never polls while offline", async () => {
    apiMock.getCaregiverHandover.mockResolvedValue(makeNoHandoverResponse());
    vi.useFakeTimers({ shouldAdvanceTime: true });
    setOnline(false);
    render(<CaregiverHandoverScreen child={testChild} currentUserId={CURRENT_USER_ID} onClose={() => {}} />);
    await vi.advanceTimersByTimeAsync(120000);
    expect(apiMock.getCaregiverHandover).not.toHaveBeenCalled();
  });

  it("never fetches while the document is hidden", async () => {
    apiMock.getCaregiverHandover.mockResolvedValue(makeNoHandoverResponse());
    vi.useFakeTimers({ shouldAdvanceTime: true });
    render(<CaregiverHandoverScreen child={testChild} currentUserId={CURRENT_USER_ID} onClose={() => {}} />);
    await vi.waitFor(() => expect(apiMock.getCaregiverHandover).toHaveBeenCalledTimes(1));

    setVisibility("hidden");
    await vi.advanceTimersByTimeAsync(120000);
    expect(apiMock.getCaregiverHandover).toHaveBeenCalledTimes(1);
  });

  it("changing from hidden to visible triggers an immediate refresh", async () => {
    apiMock.getCaregiverHandover.mockResolvedValue(makeNoHandoverResponse());
    render(<CaregiverHandoverScreen child={testChild} currentUserId={CURRENT_USER_ID} onClose={() => {}} />);
    await waitFor(() => expect(apiMock.getCaregiverHandover).toHaveBeenCalledTimes(1));

    setVisibility("hidden");
    fireVisibilityChange();
    await new Promise((r) => setTimeout(r, 0));
    expect(apiMock.getCaregiverHandover).toHaveBeenCalledTimes(1);

    setVisibility("visible");
    fireVisibilityChange();
    await waitFor(() => expect(apiMock.getCaregiverHandover).toHaveBeenCalledTimes(2));
  });

  it("removes the interval and visibilitychange listener on unmount", async () => {
    apiMock.getCaregiverHandover.mockResolvedValue(makeNoHandoverResponse());
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const { unmount } = render(<CaregiverHandoverScreen child={testChild} currentUserId={CURRENT_USER_ID} onClose={() => {}} />);
    await vi.waitFor(() => expect(apiMock.getCaregiverHandover).toHaveBeenCalledTimes(1));

    unmount();
    await vi.advanceTimersByTimeAsync(120000);
    expect(apiMock.getCaregiverHandover).toHaveBeenCalledTimes(1);
  });

  it("multiple timer ticks do not create overlapping requests", async () => {
    let resolveFirst;
    apiMock.getCaregiverHandover
      .mockImplementationOnce(() => new Promise((resolve) => { resolveFirst = resolve; }))
      .mockResolvedValue(makeNoHandoverResponse());
    vi.useFakeTimers({ shouldAdvanceTime: true });
    render(<CaregiverHandoverScreen child={testChild} currentUserId={CURRENT_USER_ID} onClose={() => {}} />);

    await vi.advanceTimersByTimeAsync(60000);
    expect(apiMock.getCaregiverHandover).toHaveBeenCalledTimes(1);

    resolveFirst(makeNoHandoverResponse());
    await vi.waitFor(() => expect(screen.queryByText("Memuat...")).not.toBeInTheDocument());
  });
});

describe("CaregiverHandoverScreen — silent refresh preserves trusted data", () => {
  it("a failed silent refresh shows a non-destructive warning and keeps displaying trusted data", async () => {
    apiMock.getCaregiverHandover
      .mockResolvedValueOnce(makeWithHandoverResponse())
      .mockRejectedValueOnce(new ApiError({ kind: "server_error", status: 500, message: "boom" }));
    render(<CaregiverHandoverScreen child={testChild} currentUserId={CURRENT_USER_ID} onClose={() => {}} />);
    await screen.findByText("ℹ️ Ringkasan");

    fireVisibilityChange();
    await waitFor(() => expect(screen.getByText("Pembaruan otomatis gagal. Data terakhir masih ditampilkan.")).toBeInTheDocument());
    expect(screen.getByText("ℹ️ Ringkasan")).toBeInTheDocument();
  });

  it("preserves a conflict message across a subsequent silent refresh failure", async () => {
    apiMock.getCaregiverHandover
      .mockResolvedValueOnce(makeNoHandoverResponse({ can_create: true }))
      .mockResolvedValueOnce(makeWithHandoverResponse())
      .mockRejectedValueOnce(new ApiError({ kind: "server_error", status: 500, message: "boom" }));
    apiMock.createCaregiverHandover.mockRejectedValue(new ApiError({ kind: "http_error", status: 409, message: "Sudah ada." }));
    render(<CaregiverHandoverScreen child={testChild} currentUserId={CURRENT_USER_ID} onClose={() => {}} />);
    fireEvent.click(await screen.findByRole("button", { name: "Buat Serah Terima" }));
    const conflictMsg = await screen.findByText(/sudah diperbarui/);

    fireVisibilityChange();
    await waitFor(() => expect(apiMock.getCaregiverHandover).toHaveBeenCalledTimes(3));
    expect(conflictMsg).toBeInTheDocument();
  });
});

describe("CaregiverHandoverScreen — obsolete child & unmount safety", () => {
  it("discards a late response for a child that is no longer active", async () => {
    const childB = { ...testChild, id: 20 };
    let resolveSlowA;
    apiMock.getCaregiverHandover
      .mockImplementationOnce(() => new Promise((resolve) => { resolveSlowA = resolve; }))
      .mockResolvedValueOnce(makeWithHandoverResponse({ handover: { id: 99, note: "CATATAN ANAK B" } }));

    const { rerender } = render(<CaregiverHandoverScreen child={testChild} currentUserId={CURRENT_USER_ID} onClose={() => {}} />);
    rerender(<CaregiverHandoverScreen child={childB} currentUserId={CURRENT_USER_ID} onClose={() => {}} />);
    expect(apiMock.getCaregiverHandover).toHaveBeenCalledTimes(1); // request buat childB dikoalesikan (nunggu request anak A lama selesai), belum benar-benar terkirim

    // Respons TELAT buat anak A (testChild) akhirnya datang -- HARUS
    // dibuang (anak aktifnya sudah childB), lalu request childB yang
    // sempat menunggu WAJIB benar-benar dijalankan.
    resolveSlowA(makeWithHandoverResponse({ handover: { id: 1, note: "CATATAN BASI ANAK A" } }));
    await waitFor(() => expect(apiMock.getCaregiverHandover).toHaveBeenCalledTimes(2));
    await screen.findByText("CATATAN ANAK B");
    expect(screen.queryByText("CATATAN BASI ANAK A")).not.toBeInTheDocument();
  });

  it("does not update state after unmount", async () => {
    let resolveSlow;
    apiMock.getCaregiverHandover.mockReturnValue(new Promise((resolve) => { resolveSlow = resolve; }));
    const consoleError = vi.spyOn(console, "error").mockImplementation(() => {});
    const { unmount } = render(<CaregiverHandoverScreen child={testChild} currentUserId={CURRENT_USER_ID} onClose={() => {}} />);
    unmount();

    resolveSlow(makeNoHandoverResponse());
    await new Promise((r) => setTimeout(r, 0));

    const stateUpdateWarning = consoleError.mock.calls.some(
      (call) => typeof call[0] === "string" && call[0].includes("state update"),
    );
    expect(stateUpdateWarning).toBe(false);
    consoleError.mockRestore();
  });
});

describe("CaregiverHandoverScreen — offline while trusted data is displayed", () => {
  it("marks trusted data as potentially outdated and disables mutations when connectivity drops", async () => {
    apiMock.getCaregiverHandover.mockResolvedValue(makeWithHandoverResponse());
    render(<CaregiverHandoverScreen child={testChild} currentUserId={CURRENT_USER_ID} onClose={() => {}} />);
    await screen.findByText("ℹ️ Ringkasan");

    setOnline(false);
    window.dispatchEvent(new Event("offline"));

    await waitFor(() => expect(screen.getAllByText((_, el) => el.textContent === OFFLINE_MESSAGE || el.textContent.startsWith(OFFLINE_MESSAGE)).length).toBeGreaterThan(0));
    expect(screen.getByText("ℹ️ Ringkasan")).toBeInTheDocument(); // data terpercaya TETAP kelihatan
    expect(screen.queryByText("Ubah catatan")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Tutup Serah Terima" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Tandai sudah dibaca" })).not.toBeInTheDocument();
  });
});

describe("CaregiverHandoverScreen — WIB rendering, human-readable output, no raw JSON", () => {
  it("renders timestamps in WIB, not raw ISO strings", async () => {
    apiMock.getCaregiverHandover.mockResolvedValue(makeWithHandoverResponse());
    render(<CaregiverHandoverScreen child={testChild} currentUserId={CURRENT_USER_ID} onClose={() => {}} />);
    await screen.findByText("ℹ️ Ringkasan");
    expect(screen.getAllByText(/WIB/).length).toBeGreaterThan(0);
    expect(screen.queryByText(/2026-08-23T14:30:00\+07:00/)).not.toBeInTheDocument();
  });

  it("never renders raw JSON, null, or undefined text anywhere on screen", async () => {
    apiMock.getCaregiverHandover.mockResolvedValue(makeWithHandoverResponse());
    const { container } = render(<CaregiverHandoverScreen child={testChild} currentUserId={CURRENT_USER_ID} onClose={() => {}} />);
    await screen.findByText("ℹ️ Ringkasan");
    const text = container.textContent;
    expect(text).not.toMatch(/\bnull\b/);
    expect(text).not.toMatch(/\bundefined\b/);
    expect(text).not.toMatch(/[{}[\]]"/);
  });

  it("shows human-readable empty states for every section with no data", async () => {
    apiMock.getCaregiverHandover.mockResolvedValue(makeWithHandoverResponse());
    render(<CaregiverHandoverScreen child={testChild} currentUserId={CURRENT_USER_ID} onClose={() => {}} />);
    await screen.findByText("ℹ️ Ringkasan");
    expect(screen.getByText(/Belum ada catatan menyusui/)).toBeInTheDocument();
    expect(screen.getByText(/Belum ada catatan tidur/)).toBeInTheDocument();
    expect(screen.getByText(/Belum ada catatan popok/)).toBeInTheDocument();
    expect(screen.getByText("Tidak ada catatan.")).toBeInTheDocument();
  });
});

describe("CaregiverHandoverScreen — never writes to browser storage", () => {
  it("does not write anything to localStorage or sessionStorage across load/create/acknowledge", async () => {
    apiMock.getCaregiverHandover.mockResolvedValue(makeNoHandoverResponse({ can_create: true }));
    apiMock.createCaregiverHandover.mockResolvedValue(makeWithHandoverResponse());
    apiMock.acknowledgeCaregiverHandover.mockResolvedValue({ acknowledgement: { id: 1 }, created: true });
    const localSetSpy = vi.spyOn(Storage.prototype, "setItem");

    render(<CaregiverHandoverScreen child={testChild} currentUserId={CURRENT_USER_ID} onClose={() => {}} />);
    fireEvent.click(await screen.findByRole("button", { name: "Buat Serah Terima" }));
    await waitFor(() => expect(apiMock.createCaregiverHandover).toHaveBeenCalled());

    expect(localSetSpy).not.toHaveBeenCalled();
    localSetSpy.mockRestore();
  });
});
