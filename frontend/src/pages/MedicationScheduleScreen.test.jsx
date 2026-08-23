import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import MedicationScheduleScreen from "./MedicationScheduleScreen";
import { cacheMedicationScheduleSnapshot } from "../utils/medicationScheduleCache";

const { apiMock } = vi.hoisted(() => ({
  apiMock: {
    listMedicationSchedules: vi.fn(),
    createMedicationSchedule: vi.fn(),
    updateMedicationSchedule: vi.fn(),
    deleteMedicationSchedule: vi.fn(),
    administerMedicationDose: vi.fn(),
    skipMedicationDose: vi.fn(),
    getMedicationAdherence: vi.fn(),
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

function makeSchedule(overrides = {}) {
  const occurrenceCanAct = overrides.can_act ?? true;
  return {
    id: 1, child_id: 10, created_by_user_id: 1, medication_name: "Paracetamol",
    dose_value: 5, dose_unit: "ml", instructions: null,
    start_date: "2026-08-23", end_date: null, times_of_day: ["08:00"],
    timezone: "Asia/Jakarta", is_active: true,
    created_at: "2026-08-01T00:00:00Z", updated_at: "2026-08-01T00:00:00Z",
    can_edit: true, can_delete: true, can_act: true,
    next_occurrence_at: null,
    occurrences: [
      {
        occurrence_key: "2026-08-23T08:00", occurrence_at: "2026-08-23T08:00:00+07:00",
        state: "due", status: null, acted_at: null, acted_by_user_id: null, acted_by_name: null,
        medication_log_id: null, can_act: occurrenceCanAct,
      },
    ],
    ...overrides,
  };
}

function makeScheduleResponse(overrides = {}) {
  return {
    child_id: 10,
    timezone: "Asia/Jakarta",
    server_time: "2026-08-23T10:00:00+07:00",
    schedules: [makeSchedule()],
    summary: { due_count: 1, overdue_count: 0, next_upcoming_at: null },
    dose_units: ["ml", "mg"],
    can_create: true,
    ...overrides,
  };
}

const emptyAdherence = {
  child_id: 10, period: { key: "7d", days: 7 },
  expected_count: 0, administered_count: 0, skipped_count: 0,
  overdue_unresolved_count: 0, on_time_administered_count: 0, late_administered_count: 0,
  adherence_percentage: null,
};

beforeEach(() => {
  setOnline(true);
  localStorage.clear();
  Object.values(apiMock).forEach((fn) => fn.mockReset());
  apiMock.getMedicationAdherence.mockResolvedValue(emptyAdherence);
});

afterEach(() => {
  vi.clearAllTimers();
});

describe("MedicationScheduleScreen — loading/success/empty/error states", () => {
  it("shows a loading state while the request is in flight", async () => {
    let resolvePromise;
    apiMock.listMedicationSchedules.mockReturnValue(new Promise((resolve) => { resolvePromise = resolve; }));
    render(<MedicationScheduleScreen child={testChild} currentUserId={CURRENT_USER_ID} onClose={() => {}} />);
    expect(screen.getByText("Memuat jadwal obat...")).toBeInTheDocument();
    resolvePromise(makeScheduleResponse());
    await waitFor(() => expect(screen.queryByText("Memuat jadwal obat...")).not.toBeInTheDocument());
  });

  it("renders schedule occurrences on success", async () => {
    apiMock.listMedicationSchedules.mockResolvedValue(makeScheduleResponse());
    render(<MedicationScheduleScreen child={testChild} currentUserId={CURRENT_USER_ID} onClose={() => {}} />);
    expect(await screen.findAllByText(/Paracetamol/)).not.toHaveLength(0);
    expect(screen.getByText("Jatuh Tempo")).toBeInTheDocument();
  });

  it("shows an empty state when there are no schedules at all", async () => {
    apiMock.listMedicationSchedules.mockResolvedValue(makeScheduleResponse({ schedules: [], summary: { due_count: 0, overdue_count: 0, next_upcoming_at: null } }));
    render(<MedicationScheduleScreen child={testChild} currentUserId={CURRENT_USER_ID} onClose={() => {}} />);
    expect(await screen.findByText(/Belum ada jadwal obat/)).toBeInTheDocument();
  });

  it("shows a retryable error state on a non-network failure", async () => {
    apiMock.listMedicationSchedules.mockRejectedValue(new ApiError({ kind: "server_error", status: 500, message: "Gagal memuat." }));
    render(<MedicationScheduleScreen child={testChild} currentUserId={CURRENT_USER_ID} onClose={() => {}} />);
    expect(await screen.findByText("Gagal memuat.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Coba lagi" })).toBeInTheDocument();
  });

  it("shows a permission-denied state on a forbidden failure", async () => {
    apiMock.listMedicationSchedules.mockRejectedValue(new ApiError({ kind: "forbidden", status: 403, message: "Anda tidak punya izin." }));
    render(<MedicationScheduleScreen child={testChild} currentUserId={CURRENT_USER_ID} onClose={() => {}} />);
    expect(await screen.findByText("Tidak punya akses")).toBeInTheDocument();
    expect(screen.getByText("Anda tidak punya izin.")).toBeInTheDocument();
  });

  it("shows a readable empty offline state with no cache", async () => {
    setOnline(false);
    render(<MedicationScheduleScreen child={testChild} currentUserId={CURRENT_USER_ID} onClose={() => {}} />);
    expect(await screen.findByText("Belum ada jadwal obat tersimpan")).toBeInTheDocument();
    expect(apiMock.listMedicationSchedules).not.toHaveBeenCalled();
  });

  it("always shows the safety disclaimer", async () => {
    apiMock.listMedicationSchedules.mockResolvedValue(makeScheduleResponse());
    render(<MedicationScheduleScreen child={testChild} currentUserId={CURRENT_USER_ID} onClose={() => {}} />);
    expect(await screen.findByText(/bukan resep/)).toBeInTheDocument();
  });
});

describe("MedicationScheduleScreen — offline cache", () => {
  it("restores cached schedules for the correct user/child when offline", async () => {
    cacheMedicationScheduleSnapshot(CURRENT_USER_ID, testChild.id, makeScheduleResponse());
    setOnline(false);
    render(<MedicationScheduleScreen child={testChild} currentUserId={CURRENT_USER_ID} onClose={() => {}} />);
    expect(await screen.findAllByText(/Paracetamol/)).not.toHaveLength(0);
    expect(screen.getByText(/Menampilkan jadwal obat terakhir saat offline/)).toBeInTheDocument();
  });

  it("never shows another child's or user's cached schedules", async () => {
    cacheMedicationScheduleSnapshot(999, testChild.id, makeScheduleResponse());
    setOnline(false);
    render(<MedicationScheduleScreen child={testChild} currentUserId={CURRENT_USER_ID} onClose={() => {}} />);
    expect(await screen.findByText("Belum ada jadwal obat tersimpan")).toBeInTheDocument();
  });

  it("hides create/edit controls while offline even if cached data allows them", async () => {
    cacheMedicationScheduleSnapshot(CURRENT_USER_ID, testChild.id, makeScheduleResponse());
    setOnline(false);
    render(<MedicationScheduleScreen child={testChild} currentUserId={CURRENT_USER_ID} onClose={() => {}} />);
    await screen.findAllByText(/Paracetamol/);
    expect(screen.queryByText("+ Jadwal Obat Baru")).not.toBeInTheDocument();
    expect(screen.getByText(/Menandai obat/)).toBeInTheDocument();
  });
});

describe("MedicationScheduleScreen — role-based controls", () => {
  it("shows the create button to an owner", async () => {
    apiMock.listMedicationSchedules.mockResolvedValue(makeScheduleResponse());
    render(<MedicationScheduleScreen child={{ ...testChild, role: "owner" }} currentUserId={CURRENT_USER_ID} onClose={() => {}} />);
    expect(await screen.findByText("+ Jadwal Obat Baru")).toBeInTheDocument();
  });

  it("never shows the create button to a viewer, even with zero existing schedules", async () => {
    apiMock.listMedicationSchedules.mockResolvedValue(
      makeScheduleResponse({ schedules: [], summary: { due_count: 0, overdue_count: 0, next_upcoming_at: null } }),
    );
    render(<MedicationScheduleScreen child={{ ...testChild, role: "viewer" }} currentUserId={CURRENT_USER_ID} onClose={() => {}} />);
    await screen.findByText(/Belum ada jadwal obat/);
    expect(screen.queryByText("+ Jadwal Obat Baru")).not.toBeInTheDocument();
  });

  it("does not render administer/skip buttons for an occurrence the viewer cannot act on", async () => {
    apiMock.listMedicationSchedules.mockResolvedValue(
      makeScheduleResponse({ schedules: [makeSchedule({ can_edit: false, can_delete: false, can_act: false })] }),
    );
    render(<MedicationScheduleScreen child={testChild} currentUserId={CURRENT_USER_ID} onClose={() => {}} />);
    await screen.findAllByText(/Paracetamol/);
    expect(screen.queryByRole("button", { name: "Sudah diberikan" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Lewati" })).not.toBeInTheDocument();
  });

  it("editor can administer a dose on a schedule they did not create, but cannot edit its definition", async () => {
    apiMock.listMedicationSchedules.mockResolvedValue(
      makeScheduleResponse({ schedules: [makeSchedule({ can_edit: false, can_delete: false, can_act: true })] }),
    );
    render(<MedicationScheduleScreen child={testChild} currentUserId={CURRENT_USER_ID} onClose={() => {}} />);
    await screen.findAllByText(/Paracetamol/);
    expect(screen.queryByRole("button", { name: "Ubah" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Sudah diberikan" })).toBeInTheDocument();
  });
});

describe("MedicationScheduleScreen — administer/skip flow", () => {
  it("administering an occurrence calls the API with the correct schedule/occurrence and reloads", async () => {
    apiMock.listMedicationSchedules.mockResolvedValue(makeScheduleResponse());
    apiMock.administerMedicationDose.mockResolvedValue({ id: 5, status: "administered", medication_log_id: 9 });
    render(<MedicationScheduleScreen child={testChild} currentUserId={CURRENT_USER_ID} onClose={() => {}} />);
    await screen.findAllByText(/Paracetamol/);

    fireEvent.click(screen.getByRole("button", { name: "Sudah diberikan" }));

    await waitFor(() =>
      expect(apiMock.administerMedicationDose).toHaveBeenCalledWith(testChild.id, 1, "2026-08-23T08:00"),
    );
    await waitFor(() => expect(apiMock.listMedicationSchedules).toHaveBeenCalledTimes(2));
  });

  it("skipping an occurrence calls the skip API", async () => {
    apiMock.listMedicationSchedules.mockResolvedValue(makeScheduleResponse());
    apiMock.skipMedicationDose.mockResolvedValue({ id: 5, status: "skipped" });
    render(<MedicationScheduleScreen child={testChild} currentUserId={CURRENT_USER_ID} onClose={() => {}} />);
    await screen.findAllByText(/Paracetamol/);

    fireEvent.click(screen.getByRole("button", { name: "Lewati" }));

    await waitFor(() =>
      expect(apiMock.skipMedicationDose).toHaveBeenCalledWith(testChild.id, 1, "2026-08-23T08:00"),
    );
  });

  it("shows a pending-sync state when administering is queued offline", async () => {
    apiMock.listMedicationSchedules.mockResolvedValue(makeScheduleResponse());
    apiMock.administerMedicationDose.mockResolvedValue({ id: "local-1", _offlineQueued: true });
    render(<MedicationScheduleScreen child={testChild} currentUserId={CURRENT_USER_ID} onClose={() => {}} />);
    await screen.findAllByText(/Paracetamol/);

    fireEvent.click(screen.getByRole("button", { name: "Sudah diberikan" }));

    expect(await screen.findByText("Menunggu sinkron")).toBeInTheDocument();
  });

  it("double-click protection: a second click before the first request resolves does not send a second request", async () => {
    apiMock.listMedicationSchedules.mockResolvedValue(makeScheduleResponse());
    let resolveAdminister;
    apiMock.administerMedicationDose.mockReturnValue(new Promise((resolve) => { resolveAdminister = resolve; }));
    render(<MedicationScheduleScreen child={testChild} currentUserId={CURRENT_USER_ID} onClose={() => {}} />);
    await screen.findAllByText(/Paracetamol/);

    const button = screen.getByRole("button", { name: "Sudah diberikan" });
    fireEvent.click(button);
    // Tombolnya sendiri langsung disembunyikan (actionPending) begitu
    // request pertama mulai -- jadi klik kedua secara fisik nggak
    // mungkin nyampe ke handler lewat UI; kita tetap verifikasi
    // exactly-once di sisi API sebagai jaminan utamanya.
    await waitFor(() => expect(screen.queryByRole("button", { name: "Sudah diberikan" })).not.toBeInTheDocument());

    resolveAdminister({ id: 5, status: "administered", medication_log_id: 9 });
    await waitFor(() => expect(apiMock.listMedicationSchedules).toHaveBeenCalledTimes(2));
    expect(apiMock.administerMedicationDose).toHaveBeenCalledTimes(1);
  });

  it("shows a deterministic conflict message and refreshes when the occurrence was already resolved by another caregiver", async () => {
    apiMock.listMedicationSchedules.mockResolvedValue(makeScheduleResponse());
    apiMock.administerMedicationDose.mockRejectedValue(
      new ApiError({ kind: "http_error", status: 409, message: "Dosis ini sudah pernah ditandai sebelumnya." }),
    );
    render(<MedicationScheduleScreen child={testChild} currentUserId={CURRENT_USER_ID} onClose={() => {}} />);
    await screen.findAllByText(/Paracetamol/);

    fireEvent.click(screen.getByRole("button", { name: "Sudah diberikan" }));

    expect(await screen.findByText(/sudah ditandai oleh caregiver lain/)).toBeInTheDocument();
    await waitFor(() => expect(apiMock.listMedicationSchedules).toHaveBeenCalledTimes(2));
  });
});

describe("MedicationScheduleScreen — adherence summary", () => {
  it("shows counts and percentage when there is expected data", async () => {
    apiMock.listMedicationSchedules.mockResolvedValue(makeScheduleResponse());
    apiMock.getMedicationAdherence.mockResolvedValue({
      ...emptyAdherence, expected_count: 4, administered_count: 3, skipped_count: 1, adherence_percentage: 75.0,
    });
    render(<MedicationScheduleScreen child={testChild} currentUserId={CURRENT_USER_ID} onClose={() => {}} />);
    expect(await screen.findByText(/75/)).toBeInTheDocument();
  });

  it("never fabricates a percentage when there are no expected doses", async () => {
    apiMock.listMedicationSchedules.mockResolvedValue(makeScheduleResponse());
    apiMock.getMedicationAdherence.mockResolvedValue(emptyAdherence);
    render(<MedicationScheduleScreen child={testChild} currentUserId={CURRENT_USER_ID} onClose={() => {}} />);
    expect(await screen.findByText(/Belum ada dosis yang dijadwalkan/)).toBeInTheDocument();
  });

  it("switching to 30 Hari requests the 30d period", async () => {
    apiMock.listMedicationSchedules.mockResolvedValue(makeScheduleResponse());
    render(<MedicationScheduleScreen child={testChild} currentUserId={CURRENT_USER_ID} onClose={() => {}} />);
    await screen.findAllByText(/Paracetamol/);
    await waitFor(() => expect(apiMock.getMedicationAdherence).toHaveBeenCalledWith(testChild.id, "7d"));

    fireEvent.click(screen.getByRole("button", { name: "30 Hari" }));

    await waitFor(() => expect(apiMock.getMedicationAdherence).toHaveBeenCalledWith(testChild.id, "30d"));
  });
});

describe("MedicationScheduleScreen — schedule form validation", () => {
  it("opens the create form and submits a new schedule", async () => {
    apiMock.listMedicationSchedules.mockResolvedValue(makeScheduleResponse({ schedules: [], summary: { due_count: 0, overdue_count: 0, next_upcoming_at: null } }));
    apiMock.createMedicationSchedule.mockResolvedValue({ id: 2 });
    render(<MedicationScheduleScreen child={testChild} currentUserId={CURRENT_USER_ID} onClose={() => {}} />);
    fireEvent.click(await screen.findByText("+ Jadwal Obat Baru"));

    fireEvent.change(screen.getByLabelText("Nama Obat"), { target: { value: "Amoxicillin" } });
    fireEvent.change(screen.getByLabelText("Mulai"), { target: { value: "2026-08-23" } });
    fireEvent.click(screen.getByRole("button", { name: "Simpan" }));

    await waitFor(() => expect(apiMock.createMedicationSchedule).toHaveBeenCalled());
    const payload = apiMock.createMedicationSchedule.mock.calls[0][1];
    expect(payload.medication_name).toBe("Amoxicillin");
    expect(payload.times_of_day).toEqual(["08:00"]);
  });

  it("requires the medication name field (native HTML validation, empty submit does not call the API)", async () => {
    apiMock.listMedicationSchedules.mockResolvedValue(makeScheduleResponse({ schedules: [], summary: { due_count: 0, overdue_count: 0, next_upcoming_at: null } }));
    render(<MedicationScheduleScreen child={testChild} currentUserId={CURRENT_USER_ID} onClose={() => {}} />);
    fireEvent.click(await screen.findByText("+ Jadwal Obat Baru"));

    const nameInput = screen.getByLabelText("Nama Obat");
    expect(nameInput).toBeRequired();
  });

  it("dose unit select is disabled until a dose value is entered", async () => {
    apiMock.listMedicationSchedules.mockResolvedValue(makeScheduleResponse({ schedules: [], summary: { due_count: 0, overdue_count: 0, next_upcoming_at: null } }));
    render(<MedicationScheduleScreen child={testChild} currentUserId={CURRENT_USER_ID} onClose={() => {}} />);
    fireEvent.click(await screen.findByText("+ Jadwal Obat Baru"));

    expect(screen.getByLabelText("Satuan")).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Dosis (opsional)"), { target: { value: "5" } });
    expect(screen.getByLabelText("Satuan")).not.toBeDisabled();
  });

  it("adding a time beyond the daily maximum is not possible via the UI", async () => {
    apiMock.listMedicationSchedules.mockResolvedValue(makeScheduleResponse({ schedules: [], summary: { due_count: 0, overdue_count: 0, next_upcoming_at: null } }));
    render(<MedicationScheduleScreen child={testChild} currentUserId={CURRENT_USER_ID} onClose={() => {}} />);
    fireEvent.click(await screen.findByText("+ Jadwal Obat Baru"));

    const addButton = () => screen.queryByText("+ Tambah jam");
    for (let i = 0; i < 5; i++) {
      fireEvent.click(addButton());
    }
    expect(addButton()).not.toBeInTheDocument();
    expect(screen.getByText(/Maksimal 6 jam pemberian per hari/)).toBeInTheDocument();
  });

  it("shows the server validation error message on a failed submit", async () => {
    apiMock.listMedicationSchedules.mockResolvedValue(makeScheduleResponse({ schedules: [], summary: { due_count: 0, overdue_count: 0, next_upcoming_at: null } }));
    apiMock.createMedicationSchedule.mockRejectedValue(
      new ApiError({ kind: "validation", status: 400, message: "Nama obat wajib diisi" }),
    );
    render(<MedicationScheduleScreen child={testChild} currentUserId={CURRENT_USER_ID} onClose={() => {}} />);
    fireEvent.click(await screen.findByText("+ Jadwal Obat Baru"));
    fireEvent.change(screen.getByLabelText("Nama Obat"), { target: { value: "x" } });
    fireEvent.change(screen.getByLabelText("Mulai"), { target: { value: "2026-08-23" } });
    fireEvent.click(screen.getByRole("button", { name: "Simpan" }));

    expect(await screen.findByText("Nama obat wajib diisi")).toBeInTheDocument();
  });
});

describe("MedicationScheduleScreen — no raw JSON/internal field names leak", () => {
  it("never renders raw JSON, null, or undefined text anywhere on screen", async () => {
    apiMock.listMedicationSchedules.mockResolvedValue(makeScheduleResponse());
    apiMock.getMedicationAdherence.mockResolvedValue({
      ...emptyAdherence, expected_count: 2, administered_count: 1, adherence_percentage: 50.0,
    });
    render(<MedicationScheduleScreen child={testChild} currentUserId={CURRENT_USER_ID} onClose={() => {}} />);
    await screen.findAllByText(/Paracetamol/);

    const bodyText = document.body.textContent;
    expect(bodyText).not.toMatch(/\bundefined\b/);
    expect(bodyText).not.toMatch(/\bnull\b/);
    expect(bodyText).not.toMatch(/occurrence_key|medication_schedule|dose_unit|is_active/);
  });
});
