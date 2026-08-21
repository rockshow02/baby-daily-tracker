import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import OfflineStatusBanner from "./OfflineStatusBanner";

const useOfflineSyncMock = vi.fn();
const logoutMock = vi.fn();

vi.mock("../hooks/useOfflineSync", () => ({
  useOfflineSync: () => useOfflineSyncMock(),
}));

vi.mock("../context/AuthContext", () => ({
  useAuth: () => ({ logout: logoutMock }),
}));

function baseHookState(overrides = {}) {
  return {
    status: "idle",
    pendingCount: 0,
    needsReviewCount: 0,
    needsReviewItems: [],
    legacyItems: [],
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
    useOfflineSyncMock.mockReturnValue(baseHookState({ status: "auth_required" }));
    render(<OfflineStatusBanner />);

    expect(screen.getByText("Masuk lagi")).toBeInTheDocument();
  });

  it("clicking 'Masuk lagi' calls AuthContext's logout — not a local token manipulation", () => {
    useOfflineSyncMock.mockReturnValue(baseHookState({ status: "auth_required" }));
    render(<OfflineStatusBanner />);

    fireEvent.click(screen.getByText("Masuk lagi"));
    expect(logoutMock).toHaveBeenCalledTimes(1);
  });

  it("does not show the 'Masuk lagi' action for other statuses", () => {
    useOfflineSyncMock.mockReturnValue(baseHookState({ status: "waiting", pendingCount: 2 }));
    render(<OfflineStatusBanner />);

    expect(screen.queryByText("Masuk lagi")).not.toBeInTheDocument();
  });

  it("renders nothing when idle", () => {
    useOfflineSyncMock.mockReturnValue(baseHookState({ status: "idle" }));
    const { container } = render(<OfflineStatusBanner />);
    expect(container).toBeEmptyDOMElement();
  });
});
