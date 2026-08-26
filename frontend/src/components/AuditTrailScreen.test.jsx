import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import AuditTrailScreen from "./AuditTrailScreen";

const { apiMock } = vi.hoisted(() => ({
  apiMock: {
    listAuditEvents: vi.fn(),
    listCaregivers: vi.fn(),
  },
}));

// `api` di-mock, TAPI ApiError dipakai ASLI (persis pola App.test.jsx) —
// komponen ini membedakan ApiError.kind === "network" dari error lain,
// jadi butuh instance ApiError yang sungguhan, bukan objek biasa.
vi.mock("../api/client", async (importOriginal) => {
  const actual = await importOriginal();
  return { ...actual, api: apiMock };
});

const { ApiError } = await import("../api/client");

const testChild = { id: 1, name: "Anak Satu", nickname: "Dedek" };

function setOnline(value) {
  Object.defineProperty(window.navigator, "onLine", { value, configurable: true });
}

function makeEvent(overrides = {}) {
  return {
    id: 1,
    action: "create",
    entity_type: "feeding_log",
    entity_id: 5,
    changed_fields: [],
    recorded_at: "2026-01-10T08:00:00+07:00",
    created_at: "2026-01-10T08:00:05Z",
    actor_user_id: 2,
    actor_name: "Weswew",
    ...overrides,
  };
}

beforeEach(() => {
  setOnline(true);
  apiMock.listAuditEvents.mockReset();
  apiMock.listCaregivers.mockReset();
  apiMock.listCaregivers.mockResolvedValue([
    { user_id: 1, name: "Pemilik", email: "a@a.com", role: "owner" },
    { user_id: 2, name: "Weswew", email: "b@b.com", role: "caregiver" },
  ]);
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("AuditTrailScreen — loading/ready/empty/error states", () => {
  it("shows a loading state while the first page is in flight", async () => {
    let resolvePromise;
    apiMock.listAuditEvents.mockReturnValue(
      new Promise((resolve) => {
        resolvePromise = resolve;
      }),
    );
    render(<AuditTrailScreen child={testChild} currentUserId={1} onClose={vi.fn()} />);
    expect(screen.getByText("Memuat aktivitas...")).toBeInTheDocument();
    resolvePromise({ events: [], next_cursor: null });
    await waitFor(() => expect(screen.queryByText("Memuat aktivitas...")).not.toBeInTheDocument());
  });

  it("renders a human-readable sentence for each event using the allowlist mapping", async () => {
    apiMock.listAuditEvents.mockResolvedValue({ events: [makeEvent()], next_cursor: null });
    render(<AuditTrailScreen child={testChild} currentUserId={1} onClose={vi.fn()} />);
    expect(await screen.findByText("Weswew menambahkan catatan menyusui")).toBeInTheDocument();
  });

  it("shows an empty state when there are no events", async () => {
    apiMock.listAuditEvents.mockResolvedValue({ events: [], next_cursor: null });
    render(<AuditTrailScreen child={testChild} currentUserId={1} onClose={vi.fn()} />);
    expect(await screen.findByText(/Belum ada aktivitas/)).toBeInTheDocument();
  });

  it("shows a retry-able error state on failure, without treating it as an auth failure", async () => {
    apiMock.listAuditEvents.mockRejectedValue(
      new ApiError({ kind: "server_error", status: 500, message: "Server error" }),
    );
    render(<AuditTrailScreen child={testChild} currentUserId={1} onClose={vi.fn()} />);
    expect(await screen.findByText("Server error")).toBeInTheDocument();
    const retryButton = screen.getByRole("button", { name: "Coba lagi" });
    expect(retryButton).toBeInTheDocument();

    apiMock.listAuditEvents.mockResolvedValueOnce({ events: [makeEvent()], next_cursor: null });
    fireEvent.click(retryButton);
    expect(await screen.findByText("Weswew menambahkan catatan menyusui")).toBeInTheDocument();
  });

  it("shows a distinct, non-alarming message for a network error (not an auth error)", async () => {
    apiMock.listAuditEvents.mockRejectedValue(
      new ApiError({ kind: "network", status: null, message: "Nggak ada koneksi internet. Coba lagi nanti." }),
    );
    render(<AuditTrailScreen child={testChild} currentUserId={1} onClose={vi.fn()} />);
    expect(
      await screen.findByText("Nggak bisa terhubung ke server. Periksa koneksi internet kamu."),
    ).toBeInTheDocument();
  });
});

describe("AuditTrailScreen — offline behavior (Phase 1 is online-only)", () => {
  it("explains the feature is online-only instead of calling the API when offline", async () => {
    setOnline(false);
    render(<AuditTrailScreen child={testChild} currentUserId={1} onClose={vi.fn()} />);
    expect(await screen.findByText(/cuma bisa dilihat pas online/)).toBeInTheDocument();
    expect(apiMock.listAuditEvents).not.toHaveBeenCalled();
  });

  it("does not write the audit feed to localStorage", async () => {
    const setItemSpy = vi.spyOn(Storage.prototype, "setItem");
    apiMock.listAuditEvents.mockResolvedValue({ events: [makeEvent()], next_cursor: null });
    render(<AuditTrailScreen child={testChild} currentUserId={1} onClose={vi.fn()} />);
    await screen.findByText("Weswew menambahkan catatan menyusui");
    expect(setItemSpy).not.toHaveBeenCalled();
  });
});

describe("AuditTrailScreen — pagination", () => {
  it("shows 'Muat lagi' when a next_cursor is present and appends the next page on click", async () => {
    apiMock.listAuditEvents.mockResolvedValueOnce({
      events: [makeEvent({ id: 1 })],
      next_cursor: 1,
    });
    render(<AuditTrailScreen child={testChild} currentUserId={1} onClose={vi.fn()} />);
    await screen.findByText("Weswew menambahkan catatan menyusui");

    const loadMoreButton = screen.getByRole("button", { name: "Muat lagi" });
    apiMock.listAuditEvents.mockResolvedValueOnce({
      events: [makeEvent({ id: 2, entity_type: "diaper_log", action: "delete" })],
      next_cursor: null,
    });
    fireEvent.click(loadMoreButton);

    await screen.findByText("Weswew menghapus catatan popok");
    // Halaman pertama TETAP kelihatan (ditambah, bukan diganti)
    expect(screen.getByText("Weswew menambahkan catatan menyusui")).toBeInTheDocument();
    // next_cursor null di halaman ke-2 -> tombol "Muat lagi" ilang
    expect(screen.queryByRole("button", { name: "Muat lagi" })).not.toBeInTheDocument();

    expect(apiMock.listAuditEvents).toHaveBeenLastCalledWith(
      testChild.id,
      expect.objectContaining({ cursor: 1 }),
    );
  });

  it("does not show 'Muat lagi' when there is no next_cursor", async () => {
    apiMock.listAuditEvents.mockResolvedValue({ events: [makeEvent()], next_cursor: null });
    render(<AuditTrailScreen child={testChild} currentUserId={1} onClose={vi.fn()} />);
    await screen.findByText("Weswew menambahkan catatan menyusui");
    expect(screen.queryByRole("button", { name: "Muat lagi" })).not.toBeInTheDocument();
  });
});

describe("AuditTrailScreen — filters", () => {
  it("re-fetches with the selected action/entity_type/actor filters", async () => {
    apiMock.listAuditEvents.mockResolvedValue({ events: [], next_cursor: null });
    render(<AuditTrailScreen child={testChild} currentUserId={1} onClose={vi.fn()} />);
    await waitFor(() => expect(apiMock.listAuditEvents).toHaveBeenCalledTimes(1));

    fireEvent.change(screen.getByLabelText("Filter aksi"), { target: { value: "delete" } });
    await waitFor(() =>
      expect(apiMock.listAuditEvents).toHaveBeenLastCalledWith(
        testChild.id,
        expect.objectContaining({ action: "delete" }),
      ),
    );

    fireEvent.change(screen.getByLabelText("Filter jenis catatan"), {
      target: { value: "sleep_log" },
    });
    await waitFor(() =>
      expect(apiMock.listAuditEvents).toHaveBeenLastCalledWith(
        testChild.id,
        expect.objectContaining({ entity_type: "sleep_log" }),
      ),
    );

    fireEvent.change(screen.getByLabelText("Filter pengasuh"), { target: { value: "2" } });
    await waitFor(() =>
      expect(apiMock.listAuditEvents).toHaveBeenLastCalledWith(
        testChild.id,
        expect.objectContaining({ actor_user_id: "2" }),
      ),
    );
  });

  it("populates the actor filter from the child's current caregiver list", async () => {
    apiMock.listAuditEvents.mockResolvedValue({ events: [], next_cursor: null });
    render(<AuditTrailScreen child={testChild} currentUserId={1} onClose={vi.fn()} />);
    expect(await screen.findByRole("option", { name: "Pemilik (kamu)" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "Weswew" })).toBeInTheDocument();
  });
});

describe("AuditTrailScreen — closing", () => {
  it("calls onClose when the header close button is clicked", async () => {
    apiMock.listAuditEvents.mockResolvedValue({ events: [], next_cursor: null });
    const onClose = vi.fn();
    render(<AuditTrailScreen child={testChild} currentUserId={1} onClose={onClose} />);
    await screen.findByText(/Belum ada aktivitas/);
    // Ada 2 tombol dengan accessible name "Tutup" (ikon ✕ header + tombol
    // teks footer) — dua-duanya SAH, jadi klik yang pertama ketemu (pola
    // yang sama dipakai SyncCenter.test.jsx).
    fireEvent.click(screen.getAllByRole("button", { name: "Tutup" })[0]);
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});
