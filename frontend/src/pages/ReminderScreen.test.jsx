import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import ReminderScreen from "./ReminderScreen";
import { cacheReminderSnapshot } from "../utils/reminderCache";

const { apiMock } = vi.hoisted(() => ({
  apiMock: {
    listReminders: vi.fn(),
    createReminder: vi.fn(),
    updateReminder: vi.fn(),
    deleteReminder: vi.fn(),
    completeReminderOccurrence: vi.fn(),
    skipReminderOccurrence: vi.fn(),
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

function makeReminder(overrides = {}) {
  return {
    id: 1, child_id: 10, created_by_user_id: 1, reminder_type: "medication",
    title: "Obat pagi", scheduled_at: "2026-08-23T08:00:00+07:00", recurrence: "none",
    is_active: true, created_at: "2026-08-01T00:00:00Z", updated_at: "2026-08-01T00:00:00Z",
    can_edit: true, can_delete: true, can_act: true,
    next_occurrence_at: null,
    occurrences: [
      {
        occurrence_key: "2026-08-23", occurrence_at: "2026-08-23T08:00:00+07:00",
        state: "due", status: null, acted_at: null, acted_by_user_id: null, acted_by_name: null,
        linked_log_type: null, linked_log_id: null,
      },
    ],
    ...overrides,
  };
}

function makeReminderResponse(overrides = {}) {
  return {
    child_id: 10,
    timezone: "Asia/Jakarta",
    server_time: "2026-08-23T10:00:00+07:00",
    reminders: [makeReminder()],
    summary: { due_count: 1, overdue_count: 0, next_upcoming_at: null },
    ...overrides,
  };
}

beforeEach(() => {
  setOnline(true);
  localStorage.clear();
  Object.values(apiMock).forEach((fn) => fn.mockReset());
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("ReminderScreen — loading/success/empty/error states", () => {
  it("shows a loading state while the request is in flight", async () => {
    let resolvePromise;
    apiMock.listReminders.mockReturnValue(new Promise((resolve) => { resolvePromise = resolve; }));
    render(<ReminderScreen child={testChild} currentUserId={CURRENT_USER_ID} />);
    expect(screen.getByText("Memuat pengingat...")).toBeInTheDocument();
    resolvePromise(makeReminderResponse());
    await waitFor(() => expect(screen.queryByText("Memuat pengingat...")).not.toBeInTheDocument());
  });

  it("renders reminder occurrences on success", async () => {
    apiMock.listReminders.mockResolvedValue(makeReminderResponse());
    render(<ReminderScreen child={testChild} currentUserId={CURRENT_USER_ID} />);
    expect(await screen.findAllByText(/Obat pagi/)).not.toHaveLength(0);
    expect(screen.getByText("Jatuh Tempo")).toBeInTheDocument();
  });

  it("shows an empty state when there are no reminders at all", async () => {
    apiMock.listReminders.mockResolvedValue(makeReminderResponse({ reminders: [], summary: { due_count: 0, overdue_count: 0, next_upcoming_at: null } }));
    render(<ReminderScreen child={testChild} currentUserId={CURRENT_USER_ID} />);
    expect(await screen.findByText(/Belum ada pengingat/)).toBeInTheDocument();
  });

  it("shows a retryable error state on a non-network failure", async () => {
    apiMock.listReminders.mockRejectedValue(new ApiError({ kind: "server_error", status: 500, message: "Gagal memuat." }));
    render(<ReminderScreen child={testChild} currentUserId={CURRENT_USER_ID} />);
    expect(await screen.findByText("Gagal memuat.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Coba lagi" })).toBeInTheDocument();
  });

  it("shows a readable empty offline state with no cache", async () => {
    setOnline(false);
    render(<ReminderScreen child={testChild} currentUserId={CURRENT_USER_ID} />);
    expect(await screen.findByText("Belum ada pengingat tersimpan")).toBeInTheDocument();
    expect(apiMock.listReminders).not.toHaveBeenCalled();
  });
});

describe("ReminderScreen — offline cache", () => {
  it("restores cached reminders for the correct user/child when offline", async () => {
    cacheReminderSnapshot(CURRENT_USER_ID, testChild.id, makeReminderResponse());
    setOnline(false);
    render(<ReminderScreen child={testChild} currentUserId={CURRENT_USER_ID} />);
    expect(await screen.findAllByText(/Obat pagi/)).not.toHaveLength(0);
    expect(screen.getByText(/Menampilkan pengingat terakhir saat offline/)).toBeInTheDocument();
  });

  it("never shows another child's or user's cached reminders", async () => {
    cacheReminderSnapshot(999, testChild.id, makeReminderResponse());
    setOnline(false);
    render(<ReminderScreen child={testChild} currentUserId={CURRENT_USER_ID} />);
    expect(await screen.findByText("Belum ada pengingat tersimpan")).toBeInTheDocument();
  });

  it("hides create/edit/delete controls while offline even if cached data allows them", async () => {
    cacheReminderSnapshot(CURRENT_USER_ID, testChild.id, makeReminderResponse());
    setOnline(false);
    render(<ReminderScreen child={testChild} currentUserId={CURRENT_USER_ID} />);
    await screen.findAllByText(/Obat pagi/);
    expect(screen.queryByText("+ Pengingat Baru")).not.toBeInTheDocument();
    expect(screen.getByText(/Menyelesaikan atau/)).toBeInTheDocument();
  });
});

describe("ReminderScreen — role-based controls", () => {
  it("shows the create button to an owner", async () => {
    apiMock.listReminders.mockResolvedValue(makeReminderResponse());
    render(<ReminderScreen child={{ ...testChild, role: "owner" }} currentUserId={CURRENT_USER_ID} />);
    expect(await screen.findByText("+ Pengingat Baru")).toBeInTheDocument();
  });

  it("shows the create button to an editor", async () => {
    apiMock.listReminders.mockResolvedValue(makeReminderResponse());
    render(<ReminderScreen child={{ ...testChild, role: "editor" }} currentUserId={CURRENT_USER_ID} />);
    expect(await screen.findByText("+ Pengingat Baru")).toBeInTheDocument();
  });

  it("never shows the create button to a viewer, even with zero existing reminders", async () => {
    // Regresi: heuristik lama nyimpulkan "boleh buat" dari ada/nggaknya
    // reminder yang bisa diaksi -- keliru buat viewer TANPA reminder sama
    // sekali (nggak ada apa pun buat disimpulkan dari situ). `child.role`
    // WAJIB jadi sumber kebenarannya, bukan bentuk daftar reminder.
    apiMock.listReminders.mockResolvedValue(
      makeReminderResponse({ reminders: [], summary: { due_count: 0, overdue_count: 0, next_upcoming_at: null } }),
    );
    render(<ReminderScreen child={{ ...testChild, role: "viewer" }} currentUserId={CURRENT_USER_ID} />);
    await screen.findByText(/Belum ada pengingat/);
    expect(screen.queryByText("+ Pengingat Baru")).not.toBeInTheDocument();
  });

  it("never shows the create button to a viewer who has existing (view-only) reminders", async () => {
    apiMock.listReminders.mockResolvedValue(
      makeReminderResponse({ reminders: [makeReminder({ can_edit: false, can_delete: false, can_act: false })] }),
    );
    render(<ReminderScreen child={{ ...testChild, role: "viewer" }} currentUserId={CURRENT_USER_ID} />);
    await screen.findAllByText(/Obat pagi/);
    expect(screen.queryByText("+ Pengingat Baru")).not.toBeInTheDocument();
  });

  it("does not render complete/skip buttons for a reminder the viewer cannot act on", async () => {
    apiMock.listReminders.mockResolvedValue(
      makeReminderResponse({ reminders: [makeReminder({ can_edit: false, can_delete: false, can_act: false })] }),
    );
    render(<ReminderScreen child={testChild} currentUserId={CURRENT_USER_ID} />);
    await screen.findAllByText(/Obat pagi/);
    expect(screen.queryByRole("button", { name: "Selesai" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Lewati" })).not.toBeInTheDocument();
  });

  it("does not render edit/delete controls for a reminder the editor did not create", async () => {
    apiMock.listReminders.mockResolvedValue(
      makeReminderResponse({ reminders: [makeReminder({ can_edit: false, can_delete: false, can_act: true })] }),
    );
    render(<ReminderScreen child={testChild} currentUserId={CURRENT_USER_ID} />);
    await screen.findAllByText(/Obat pagi/);
    expect(screen.queryByRole("button", { name: "Ubah" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Hapus" })).not.toBeInTheDocument();
    // TAPI tetap boleh selesaikan/lewati (can_act nggak dibatasi kepemilikan)
    expect(screen.getByRole("button", { name: "Selesai" })).toBeInTheDocument();
  });
});

describe("ReminderScreen — complete/skip flow", () => {
  it("completing an occurrence calls the API with the correct reminder/occurrence and reloads", async () => {
    apiMock.listReminders.mockResolvedValue(makeReminderResponse());
    apiMock.completeReminderOccurrence.mockResolvedValue({ id: 5, status: "completed" });
    render(<ReminderScreen child={testChild} currentUserId={CURRENT_USER_ID} />);
    await screen.findAllByText(/Obat pagi/);

    fireEvent.click(screen.getByRole("button", { name: "Selesai" }));

    await waitFor(() =>
      expect(apiMock.completeReminderOccurrence).toHaveBeenCalledWith(testChild.id, 1, "2026-08-23"),
    );
    await waitFor(() => expect(apiMock.listReminders).toHaveBeenCalledTimes(2));
  });

  it("skipping an occurrence calls the skip API", async () => {
    apiMock.listReminders.mockResolvedValue(makeReminderResponse());
    apiMock.skipReminderOccurrence.mockResolvedValue({ id: 5, status: "skipped" });
    render(<ReminderScreen child={testChild} currentUserId={CURRENT_USER_ID} />);
    await screen.findAllByText(/Obat pagi/);

    fireEvent.click(screen.getByRole("button", { name: "Lewati" }));

    await waitFor(() =>
      expect(apiMock.skipReminderOccurrence).toHaveBeenCalledWith(testChild.id, 1, "2026-08-23"),
    );
  });

  it("shows a pending-sync state when completion is queued offline", async () => {
    apiMock.listReminders.mockResolvedValue(makeReminderResponse());
    apiMock.completeReminderOccurrence.mockResolvedValue({ id: "local-1", _offlineQueued: true });
    render(<ReminderScreen child={testChild} currentUserId={CURRENT_USER_ID} />);
    await screen.findAllByText(/Obat pagi/);

    fireEvent.click(screen.getByRole("button", { name: "Selesai" }));

    expect(await screen.findByText("Menunggu sinkron")).toBeInTheDocument();
  });
});

describe("ReminderScreen — create form validation & role gating", () => {
  it("opens the create form and submits a new reminder", async () => {
    apiMock.listReminders.mockResolvedValue(makeReminderResponse({ reminders: [] , summary: {due_count:0, overdue_count:0, next_upcoming_at:null}}));
    apiMock.createReminder.mockResolvedValue({ id: 2 });
    render(<ReminderScreen child={testChild} currentUserId={CURRENT_USER_ID} />);
    // reminders kosong -> tombol buat TETAP tampil (default canCreate true saat belum ada reminder apa pun)
    fireEvent.click(await screen.findByText("+ Pengingat Baru"));

    fireEvent.change(screen.getByLabelText("Judul"), { target: { value: "Vitamin D" } });
    fireEvent.change(screen.getByLabelText("Waktu"), { target: { value: "2026-08-24T08:00" } });
    fireEvent.click(screen.getByRole("button", { name: "Simpan" }));

    await waitFor(() => expect(apiMock.createReminder).toHaveBeenCalled());
    const payload = apiMock.createReminder.mock.calls[0][1];
    expect(payload.title).toBe("Vitamin D");
    expect(payload.reminder_type).toBe("medication");
  });
});

describe("ReminderScreen — notification settings", () => {
  it("shows an unsupported message when the browser has no Notification API", async () => {
    const original = window.Notification;
    delete window.Notification;
    apiMock.listReminders.mockResolvedValue(makeReminderResponse());
    render(<ReminderScreen child={testChild} currentUserId={CURRENT_USER_ID} />);
    expect(await screen.findByText("Browser ini tidak mendukung notifikasi.")).toBeInTheDocument();
    if (original) window.Notification = original;
  });

  it("shows an enable button when permission is still default", async () => {
    window.Notification = class { static permission = "default"; };
    apiMock.listReminders.mockResolvedValue(makeReminderResponse());
    render(<ReminderScreen child={testChild} currentUserId={CURRENT_USER_ID} />);
    expect(await screen.findByText("Aktifkan notifikasi saat aplikasi terbuka")).toBeInTheDocument();
    delete window.Notification;
  });

  it("shows a denied message without offering to re-prompt when permission is denied", async () => {
    window.Notification = class { static permission = "denied"; };
    apiMock.listReminders.mockResolvedValue(makeReminderResponse());
    render(<ReminderScreen child={testChild} currentUserId={CURRENT_USER_ID} />);
    expect(await screen.findByText(/Izin notifikasi ditolak/)).toBeInTheDocument();
    expect(screen.queryByText("Aktifkan notifikasi saat aplikasi terbuka")).not.toBeInTheDocument();
    delete window.Notification;
  });

  it("always shows the non-guaranteed-background disclosure", async () => {
    apiMock.listReminders.mockResolvedValue(makeReminderResponse());
    render(<ReminderScreen child={testChild} currentUserId={CURRENT_USER_ID} />);
    expect(await screen.findByText(/tidak ada jaminan/)).toBeInTheDocument();
  });
});
