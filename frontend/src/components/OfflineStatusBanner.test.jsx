import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import OfflineStatusBanner from "./OfflineStatusBanner";

const logoutMock = vi.fn();

vi.mock("../context/AuthContext", () => ({
  useAuth: () => ({ logout: logoutMock }),
}));

// `sync` diteruskan lewat PROP sekarang (bukan dipanggil sendiri lewat
// useOfflineSync() di dalam komponen) — App.jsx (AuthenticatedAppShell)
// yang megang SATU-SATUNYA instance hook itu. Lihat App.jsx dan
// hooks/useOfflineSync.test.js buat test hook-nya sendiri.
function baseSync(overrides = {}) {
  return {
    status: "idle",
    isOnline: true,
    syncing: false,
    pendingCount: 0,
    pendingItems: [],
    needsReviewCount: 0,
    needsReviewItems: [],
    legacyItems: [],
    lastSyncedAt: null,
    syncNow: vi.fn(),
    discardItem: vi.fn(),
    claimLegacyItem: vi.fn(),
    retryWithEdits: vi.fn(),
    ...overrides,
  };
}

beforeEach(() => {
  logoutMock.mockReset();
});

describe("OfflineStatusBanner — 401 re-authentication", () => {
  it("shows a 'Masuk lagi' action when status is auth_required", () => {
    render(<OfflineStatusBanner sync={baseSync({ status: "auth_required" })} />);

    expect(screen.getByText("Masuk lagi")).toBeInTheDocument();
  });

  it("clicking 'Masuk lagi' calls AuthContext's logout — not a local token manipulation", () => {
    render(<OfflineStatusBanner sync={baseSync({ status: "auth_required" })} />);

    fireEvent.click(screen.getByText("Masuk lagi"));
    expect(logoutMock).toHaveBeenCalledTimes(1);
  });

  it("does not show the 'Masuk lagi' action for other statuses", () => {
    render(<OfflineStatusBanner sync={baseSync({ status: "waiting", pendingCount: 2 })} />);

    expect(screen.queryByText("Masuk lagi")).not.toBeInTheDocument();
  });

  it("renders nothing when idle", () => {
    const { container } = render(<OfflineStatusBanner sync={baseSync({ status: "idle" })} />);
    expect(container).toBeEmptyDOMElement();
  });
});

describe("OfflineStatusBanner — Sync Center entry point", () => {
  it("shows a 'Detail' action and calls onOpenDetail when clicked, while the banner is visible", () => {
    const onOpenDetail = vi.fn();
    render(<OfflineStatusBanner sync={baseSync({ status: "waiting", pendingCount: 1 })} onOpenDetail={onOpenDetail} />);

    const detailBtn = screen.getByText("Detail");
    fireEvent.click(detailBtn);
    expect(onOpenDetail).toHaveBeenCalledTimes(1);
  });

  it("does not render a 'Detail' action when onOpenDetail is not provided", () => {
    render(<OfflineStatusBanner sync={baseSync({ status: "waiting", pendingCount: 1 })} />);
    expect(screen.queryByText("Detail")).not.toBeInTheDocument();
  });

  it("renders no 'Detail' action at all when idle (banner itself is not visible)", () => {
    const onOpenDetail = vi.fn();
    const { container } = render(<OfflineStatusBanner sync={baseSync({ status: "idle" })} onOpenDetail={onOpenDetail} />);
    expect(container).toBeEmptyDOMElement();
  });
});
