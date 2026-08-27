import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import MonthlyStory from "./MonthlyStory";
import { api } from "../api/client";

vi.mock("../api/client", () => ({ api: {
  listMemoryJournal: vi.fn(), loadMemoryJournalPhoto: vi.fn(), previewMonthlyStory: vi.fn(),
  downloadAuthenticatedPost: vi.fn(), monthlyStoryPdfUrl: vi.fn(() => "pdf-url"),
} }));

const child = { id: 1, name: "Nara", role: "owner" };
const report = { month: "2026-08", child: { display_name: "Nara" },
  counts: { photos: 2, milestones: 1, vaccinations: 0 },
  previous_counts: { photos: 1, milestones: 0, vaccinations: 0 }, milestones: [], growth: [],
  selected_photos: [], parent_note: "Bulan ceria", disclaimer: "Bukan penilaian medis.",
  snapshot_token: "signed", capabilities: { can_export: true } };

describe("MonthlyStory", () => {
  beforeEach(() => { vi.clearAllMocks(); api.listMemoryJournal.mockResolvedValue({ items: [] }); });
  it("renders readable preview and comparison", async () => {
    api.previewMonthlyStory.mockResolvedValue(report);
    render(<MonthlyStory child={child} onClose={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "Buat Pratinjau" }));
    expect(await screen.findByText("Cerita Nara")).toBeInTheDocument();
    expect(screen.getByText(/Bulan sebelumnya: 1 foto/)).toBeInTheDocument();
    expect(screen.queryByText("snapshot_token")).not.toBeInTheDocument();
  });
  it("exports exactly the preview snapshot", async () => {
    api.previewMonthlyStory.mockResolvedValue(report);
    render(<MonthlyStory child={child} onClose={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "Buat Pratinjau" }));
    fireEvent.click(await screen.findByRole("button", { name: "Unduh PDF" }));
    await waitFor(() => expect(api.downloadAuthenticatedPost).toHaveBeenCalled());
    expect(api.downloadAuthenticatedPost.mock.calls[0][1].snapshot_token).toBe("signed");
  });
  it("hides private note and export for a viewer", async () => {
    api.previewMonthlyStory.mockResolvedValue({ ...report, capabilities: { can_export: false } });
    render(<MonthlyStory child={{ ...child, role: "viewer" }} onClose={vi.fn()} />);
    expect(screen.queryByLabelText(/Catatan orang tua/)).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Buat Pratinjau" }));
    await screen.findByText("Cerita Nara");
    expect(screen.queryByRole("button", { name: "Unduh PDF" })).not.toBeInTheDocument();
  });
});
