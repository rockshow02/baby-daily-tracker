import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import BottomNavigation from "./BottomNavigation";

describe("BottomNavigation", () => {
  it("marks the current destination and exposes an accessible nav label", () => {
    render(<BottomNavigation activeView="daily" onNavigate={() => {}} />);

    expect(screen.getByRole("navigation", { name: "Navigasi utama" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Beranda" })).toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("button", { name: "Statistik" })).not.toHaveAttribute("aria-current");
  });

  it("navigates to the selected destination", () => {
    const onNavigate = vi.fn();
    render(<BottomNavigation activeView="daily" onNavigate={onNavigate} />);

    fireEvent.click(screen.getByRole("button", { name: "Momen" }));

    expect(onNavigate).toHaveBeenCalledOnce();
    expect(onNavigate).toHaveBeenCalledWith("moments");
  });
});
