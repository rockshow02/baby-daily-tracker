import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import DashboardReminderSummary from "./DashboardReminderSummary";

/**
 * Regresi khusus: reminder harian yang tanggal MULAI-nya sendiri masih di
 * masa depan tidak boleh membuat dashboard menunjukkan due/overdue count
 * palsu (okurensi yang sebenarnya belum pernah ada) -- lihat
 * backend/utils/reminder_engine.py:next_pending_occurrence_at() &
 * backend/docs/REMINDERS.md. Komponen ini murni presentasional, jadi test
 * ini cuma memverifikasi ia menampilkan `summary` apa adanya tanpa
 * menghitung ulang apa pun sendiri.
 */
describe("DashboardReminderSummary — future-start-date reminder", () => {
  it("shows the future next-reminder date, never a fabricated due/overdue count", () => {
    render(
      <DashboardReminderSummary
        status="ready"
        summary={{ due_count: 0, overdue_count: 0, next_upcoming_at: "2026-08-28T08:00:00+07:00" }}
        onOpen={vi.fn()}
      />,
    );
    expect(screen.getByText(/Berikutnya/)).toBeInTheDocument();
    expect(screen.queryByText(/jatuh tempo/)).not.toBeInTheDocument();
    expect(screen.queryByText(/terlambat/)).not.toBeInTheDocument();
  });

  it("renders nothing when there is nothing due, overdue, or upcoming at all", () => {
    const { container } = render(
      <DashboardReminderSummary
        status="ready"
        summary={{ due_count: 0, overdue_count: 0, next_upcoming_at: null }}
        onOpen={vi.fn()}
      />,
    );
    expect(container).toBeEmptyDOMElement();
  });
});
