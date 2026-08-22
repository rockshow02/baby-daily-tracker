import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import SyncCenter from "./SyncCenter";

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

function makePendingItem(overrides = {}) {
  return {
    id: 1,
    method: "POST",
    url: "/children/1/feeding-logs",
    body: JSON.stringify({ feed_type: "sufor", notes: "catatan rahasia sensitif" }),
    userId: 1,
    clientRequestId: "req-key-should-not-appear",
    status: "pending",
    attempts: 0,
    nextRetryAt: null,
    lastError: null,
    lastRequestId: null,
    queuedAt: "2026-01-15T09:00:00.000Z",
    ...overrides,
  };
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe("SyncCenter — accessibility", () => {
  it("exposes a dialog role, aria-modal, and a labelled title", () => {
    render(<SyncCenter sync={baseSync()} onClose={vi.fn()} />);
    const dialog = screen.getByRole("dialog", { name: "Status Sinkronisasi" });
    expect(dialog).toBeInTheDocument();
    expect(dialog).toHaveAttribute("aria-modal", "true");
  });

  it("has a visible close button", () => {
    render(<SyncCenter sync={baseSync()} onClose={vi.fn()} />);
    // ada 2 cara nutup (ikon ✕ di header, tombol teks "Tutup" di bawah) —
    // dua-duanya SAH sebagai "tombol tutup yang keliatan", jadi cek minimal 1 ada
    expect(screen.getAllByRole("button", { name: "Tutup" }).length).toBeGreaterThanOrEqual(1);
  });

  it("closes when the close button is clicked", () => {
    const onClose = vi.fn();
    render(<SyncCenter sync={baseSync()} onClose={onClose} />);
    fireEvent.click(screen.getAllByRole("button", { name: "Tutup" })[0]);
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("closes on Escape", () => {
    const onClose = vi.fn();
    render(<SyncCenter sync={baseSync()} onClose={onClose} />);
    fireEvent.keyDown(window, { key: "Escape" });
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("does not close on Escape while a discard confirmation is active", () => {
    const onClose = vi.fn();
    const item = { id: 9, url: "/children/1/feeding-logs", queuedAt: "2026-01-15T09:00:00.000Z", status: "needs_review", lastError: "Server menolak" };
    render(<SyncCenter sync={baseSync({ needsReviewCount: 1, needsReviewItems: [item] })} onClose={onClose} />);

    fireEvent.click(screen.getByText("Buang")); // buka konfirmasi 2-langkah
    expect(screen.getByText("Yakin?")).toBeInTheDocument();

    fireEvent.keyDown(window, { key: "Escape" });
    expect(onClose).not.toHaveBeenCalled();
  });

  it("cleans up the Escape listener on unmount", () => {
    const removeSpy = vi.spyOn(window, "removeEventListener");
    const { unmount } = render(<SyncCenter sync={baseSync()} onClose={vi.fn()} />);
    unmount();
    expect(removeSpy).toHaveBeenCalledWith("keydown", expect.any(Function));
  });
});

describe("SyncCenter — connectivity and state rendering", () => {
  it("shows Online when connected", () => {
    render(<SyncCenter sync={baseSync({ isOnline: true })} onClose={vi.fn()} />);
    expect(screen.getByText(/Online/)).toBeInTheDocument();
  });

  it("shows Offline when disconnected", () => {
    render(<SyncCenter sync={baseSync({ isOnline: false, status: "offline" })} onClose={vi.fn()} />);
    expect(screen.getAllByText(/Offline/).length).toBeGreaterThanOrEqual(1);
  });

  it.each([
    ["idle", "Semua catatan tersinkron"],
    ["synced", "Semua catatan tersinkron"],
    ["waiting", "Menunggu disinkronkan"],
    ["syncing", "Sedang menyinkronkan"],
    ["retry_scheduled", "Percobaan ulang dijadwalkan"],
    ["auth_required", "Perlu masuk ulang"],
    ["needs_review", "Ada catatan perlu ditinjau"],
  ])("renders a readable label for status=%s", (status, expectedLabel) => {
    render(<SyncCenter sync={baseSync({ status })} onClose={vi.fn()} />);
    expect(screen.getByText(new RegExp(expectedLabel))).toBeInTheDocument();
  });
});

describe("SyncCenter — counts and last sync", () => {
  it("shows pending, review, and legacy counts clearly separated", () => {
    render(
      <SyncCenter
        sync={baseSync({
          pendingCount: 3,
          needsReviewCount: 2,
          legacyItems: [{ id: 1 }, { id: 2 }],
        })}
        onClose={vi.fn()}
      />,
    );
    expect(screen.getByText("3")).toBeInTheDocument();
    expect(screen.getByText("2", { selector: "p.font-medium, span.font-medium" })).toBeInTheDocument();
    expect(screen.getByText("Catatan lama (kepemilikan belum jelas)")).toBeInTheDocument();
  });

  it("shows a safe fallback when no sync has ever completed", () => {
    render(<SyncCenter sync={baseSync({ lastSyncedAt: null })} onClose={vi.fn()} />);
    expect(screen.getByText("Belum pernah tersinkron")).toBeInTheDocument();
  });

  it("shows a formatted timestamp when a last sync exists", () => {
    render(<SyncCenter sync={baseSync({ lastSyncedAt: "2026-01-15T10:00:00.000Z" })} onClose={vi.fn()} />);
    expect(screen.queryByText("Belum pernah tersinkron")).not.toBeInTheDocument();
  });
});

describe("SyncCenter — manual sync button", () => {
  it("is disabled while offline", () => {
    render(<SyncCenter sync={baseSync({ isOnline: false, status: "offline" })} onClose={vi.fn()} />);
    expect(screen.getByText("Sinkronkan sekarang")).toBeDisabled();
  });

  it("is disabled while a sync is already running", () => {
    render(<SyncCenter sync={baseSync({ syncing: true, status: "syncing" })} onClose={vi.fn()} />);
    expect(screen.getByText("Menyinkronkan...")).toBeDisabled();
  });

  it("is enabled while online and idle, and calls syncNow on click", () => {
    const syncNow = vi.fn();
    render(<SyncCenter sync={baseSync({ syncNow })} onClose={vi.fn()} />);
    const btn = screen.getByText("Sinkronkan sekarang");
    expect(btn).not.toBeDisabled();
    fireEvent.click(btn);
    expect(syncNow).toHaveBeenCalledTimes(1);
  });

  it("rapid repeated clicks only ever call syncNow once per click — no extra dedupe needed at UI layer since the hook's own syncingRef guards it", () => {
    const syncNow = vi.fn();
    render(<SyncCenter sync={baseSync({ syncNow })} onClose={vi.fn()} />);
    const btn = screen.getByText("Sinkronkan sekarang");
    fireEvent.click(btn);
    fireEvent.click(btn);
    fireEvent.click(btn);
    expect(syncNow).toHaveBeenCalledTimes(3); // UI calls syncNow each click; syncQueue's syncingRef (tested in useOfflineSync.test.js) is what actually prevents double-send
  });

  it("shows clear feedback when there is nothing to sync", () => {
    render(<SyncCenter sync={baseSync({ pendingCount: 0, needsReviewCount: 0 })} onClose={vi.fn()} />);
    expect(screen.getByText("Tidak ada catatan yang perlu disinkronkan saat ini.")).toBeInTheDocument();
  });

  it("does not show the 'nothing to sync' hint when there are pending records", () => {
    render(<SyncCenter sync={baseSync({ pendingCount: 1 })} onClose={vi.fn()} />);
    expect(screen.queryByText("Tidak ada catatan yang perlu disinkronkan saat ini.")).not.toBeInTheDocument();
  });
});

describe("SyncCenter — pending item overview (privacy-safe)", () => {
  it("renders only safe fields: type label, queued time, attempts", () => {
    const item = makePendingItem({ attempts: 2 });
    render(<SyncCenter sync={baseSync({ pendingCount: 1, pendingItems: [item] })} onClose={vi.fn()} />);

    expect(screen.getByText("Menyusui")).toBeInTheDocument();
    expect(screen.getByText("2x dicoba")).toBeInTheDocument();
  });

  it("never renders the raw request body, notes, endpoint, or idempotency key", () => {
    const item = makePendingItem();
    render(<SyncCenter sync={baseSync({ pendingCount: 1, pendingItems: [item] })} onClose={vi.fn()} />);

    const text = document.body.textContent;
    expect(text).not.toContain("catatan rahasia sensitif");
    expect(text).not.toContain("/children/1/feeding-logs");
    expect(text).not.toContain("req-key-should-not-appear");
    expect(text).not.toContain("sufor");
  });

  it("does not offer a one-click destructive delete action for a normal pending record", () => {
    const item = makePendingItem();
    render(<SyncCenter sync={baseSync({ pendingCount: 1, pendingItems: [item] })} onClose={vi.fn()} />);
    expect(screen.queryByText("Buang")).not.toBeInTheDocument();
  });

  it("shows the next retry time when scheduled", () => {
    const item = makePendingItem({ nextRetryAt: "2026-01-15T09:05:00.000Z", attempts: 1 });
    render(<SyncCenter sync={baseSync({ pendingCount: 1, pendingItems: [item] })} onClose={vi.fn()} />);
    expect(screen.getByText(/Coba lagi:/)).toBeInTheDocument();
  });
});

describe("SyncCenter — X-Request-ID troubleshooting", () => {
  it("shows a request ID inside an expandable detail area, not by default", () => {
    const item = makePendingItem({ lastRequestId: "abc123-def456", nextRetryAt: "2026-01-15T09:05:00.000Z" });
    render(<SyncCenter sync={baseSync({ pendingCount: 1, pendingItems: [item] })} onClose={vi.fn()} />);

    expect(screen.queryByText("abc123-def456")).not.toBeInTheDocument();
    fireEvent.click(screen.getByText("Info teknis"));
    expect(screen.getByText("abc123-def456")).toBeInTheDocument();
  });

  it("offers a copy action for the request ID", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.assign(navigator, { clipboard: { writeText } });

    const item = makePendingItem({ lastRequestId: "abc123-def456", nextRetryAt: "2026-01-15T09:05:00.000Z" });
    render(<SyncCenter sync={baseSync({ pendingCount: 1, pendingItems: [item] })} onClose={vi.fn()} />);

    fireEvent.click(screen.getByText("Info teknis"));
    fireEvent.click(screen.getByText("Salin"));

    expect(writeText).toHaveBeenCalledWith("abc123-def456");
  });

  it("does not show an empty request-ID placeholder when there is none", () => {
    const item = makePendingItem({ lastRequestId: null });
    render(<SyncCenter sync={baseSync({ pendingCount: 1, pendingItems: [item] })} onClose={vi.fn()} />);
    expect(screen.queryByText("Info teknis")).not.toBeInTheDocument();
  });
});

describe("SyncCenter — review items (reuses QueueReviewPanel)", () => {
  it("renders needs-review items via the existing panel", () => {
    const item = {
      id: 5,
      url: "/children/1/feeding-logs",
      body: JSON.stringify({ feed_type: "sufor" }),
      queuedAt: "2026-01-15T09:00:00.000Z",
      status: "needs_review",
      lastError: "feed_type wajib diisi",
    };
    render(<SyncCenter sync={baseSync({ needsReviewCount: 1, needsReviewItems: [item] })} onClose={vi.fn()} />);
    expect(screen.getByText("Menyusui")).toBeInTheDocument();
    expect(screen.getByText("feed_type wajib diisi")).toBeInTheDocument();
  });
});
