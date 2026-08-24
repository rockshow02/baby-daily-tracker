import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import VaccinationScreen from "./VaccinationScreen";

const { apiMock } = vi.hoisted(() => ({
  apiMock: { listChildVaccinations: vi.fn(), updateChildVaccinations: vi.fn() },
}));

vi.mock("../api/client", () => ({ api: apiMock }));

const child = { id: 10, name: "Bayi", role: "owner" };

function response(overrides = {}) {
  return {
    age_months: 3,
    can_update: true,
    disclaimer: "Jadwal ini adalah referensi. Konfirmasikan kepada dokter.",
    summary: { total: 3, given: 1, upcoming: 1, due: 0, overdue: 1 },
    vaccinations: [
      { vaccine_schedule_id: 1, vaccine_name: "BCG", category: "wajib", state: "overdue", due: true, given: false, recommended_age_months: 1, recommended_date: "2026-02-01" },
      { vaccine_schedule_id: 2, vaccine_name: "Polio 1", category: "wajib", state: "given", due: true, given: true, given_date: "2026-02-02", recommended_age_months: 1, recommended_date: "2026-02-01" },
      { vaccine_schedule_id: 3, vaccine_name: "MR", category: "wajib", state: "upcoming", due: false, given: false, recommended_age_months: 9, recommended_date: "2026-10-01" },
    ],
    ...overrides,
  };
}

beforeEach(() => {
  Object.values(apiMock).forEach((fn) => fn.mockReset());
  apiMock.listChildVaccinations.mockResolvedValue(response());
  apiMock.updateChildVaccinations.mockResolvedValue(response());
});

describe("VaccinationScreen planner", () => {
  it("shows readable planner states, summary, dates, and disclaimer", async () => {
    render(<VaccinationScreen child={child} />);
    expect(await screen.findByText("BCG")).toBeInTheDocument();
    expect(screen.getAllByText("Terlambat").length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText("Akan datang")).toBeInTheDocument();
    expect(screen.getByText(/Keseluruhan: 1 diberikan/)).toBeInTheDocument();
    expect(screen.getByText(/Konfirmasikan kepada dokter/)).toBeInTheDocument();
  });

  it("defaults to pending and can filter completed records", async () => {
    render(<VaccinationScreen child={child} />);
    await screen.findByText("BCG");
    expect(screen.queryByText("Polio 1")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Sudah diberikan" }));
    expect(screen.getByText("Polio 1")).toBeInTheDocument();
    expect(screen.queryByText("BCG")).not.toBeInTheDocument();
  });

  it("is read-only when backend capability is false", async () => {
    apiMock.listChildVaccinations.mockResolvedValue(response({ can_update: false }));
    render(<VaccinationScreen child={{ ...child, role: "viewer" }} />);
    await screen.findByText("BCG");
    expect(screen.getByText("Peran Anda hanya dapat melihat riwayat vaksinasi.")).toBeInTheDocument();
    const rowButton = screen.getByText("BCG").closest("button");
    expect(rowButton).toBeDisabled();
    expect(screen.queryByText("Ubah")).not.toBeInTheDocument();
  });

  it("shows a safe load failure instead of staying blank", async () => {
    apiMock.listChildVaccinations.mockRejectedValue(new Error("Server sementara tidak tersedia"));
    render(<VaccinationScreen child={child} />);
    expect(await screen.findByText("Server sementara tidak tersedia")).toBeInTheDocument();
  });

  it("unmarking a completed vaccination sends an explicit boolean and reloads", async () => {
    render(<VaccinationScreen child={child} />);
    await screen.findByText("BCG");
    fireEvent.click(screen.getByRole("button", { name: "Sudah diberikan" }));
    fireEvent.click(screen.getByText("Polio 1").closest("button"));
    await waitFor(() => expect(apiMock.updateChildVaccinations).toHaveBeenCalledWith(10, [
      { vaccine_schedule_id: 2, given: false, given_date: null },
    ]));
  });
});
