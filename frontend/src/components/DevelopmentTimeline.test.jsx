import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import DevelopmentTimeline from "./DevelopmentTimeline";
import { api } from "../api/client";

vi.mock("../api/client", () => ({
  api: { developmentTimeline: vi.fn(), loadMemoryJournalPhoto: vi.fn() },
}));
vi.mock("./DevelopmentHub", () => ({ default: ({ onClose }) => <div>Development Hub terbuka<button onClick={onClose}>Tutup hub</button></div> }));

const child = { id: 7, name: "Nara", nickname: "Nara" };

describe("DevelopmentTimeline", () => {
  beforeEach(() => vi.clearAllMocks());

  it("renders a readable combined timeline and never raw JSON", async () => {
    api.developmentTimeline.mockResolvedValue({ items: [
      { id: "growth-1", type: "growth", date: "2026-08-21", title: "Pengukuran pertumbuhan", summary: "7.2 kg · 65 cm", icon: "📈", photo_entry_id: null },
    ], has_more: false });
    const { container } = render(<DevelopmentTimeline child={child} />);
    expect(await screen.findByText("Pengukuran pertumbuhan")).toBeInTheDocument();
    expect(screen.getByText("7.2 kg · 65 cm")).toBeInTheDocument();
    expect(container.querySelector("pre")).toBeNull();
    expect(api.developmentTimeline).toHaveBeenCalledWith(7, { limit: 100 });
  });

  it("requests a server-side category filter", async () => {
    api.developmentTimeline.mockResolvedValue({ items: [], has_more: false });
    render(<DevelopmentTimeline child={child} />);
    await screen.findByText("Belum ada cerita pada filter ini");
    fireEvent.click(screen.getByRole("button", { name: "Vaksin" }));
    await waitFor(() => expect(api.developmentTimeline).toHaveBeenLastCalledWith(7,
      { limit: 100, categories: ["vaccination"] }));
  });

  it("shows a safe error without replacing it with an empty state", async () => {
    api.developmentTimeline.mockRejectedValue(new Error("Linimasa belum dapat dimuat"));
    render(<DevelopmentTimeline child={child} />);
    expect(await screen.findByText("Linimasa belum dapat dimuat")).toBeInTheDocument();
    expect(screen.queryByText("Belum ada cerita pada filter ini")).not.toBeInTheDocument();
  });

  it("uses one consolidated hub entry point", async () => {
    api.developmentTimeline.mockResolvedValue({ items: [], has_more: false });
    render(<DevelopmentTimeline child={child} />);
    await screen.findByText("Belum ada cerita pada filter ini");
    expect(screen.queryByRole("button", { name: "Kalender" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Buka Hub" }));
    expect(screen.getByText("Development Hub terbuka")).toBeInTheDocument();
  });
});
