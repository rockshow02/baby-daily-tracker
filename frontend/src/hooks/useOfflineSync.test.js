import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, renderHook, waitFor } from "@testing-library/react";
import { useOfflineSync } from "./useOfflineSync";
import { enqueueRequest, getQueue, removeFromQueue, updateQueueItem } from "../utils/offlineQueue";

let mockUserId = 1;
let mockToken = "token-user-1";
let mockGeneratedId = "generated-id";
const listChildrenMock = vi.fn();

vi.mock("../api/client", () => ({
  getToken: () => mockToken,
  getCurrentUserId: () => mockUserId,
  generateRequestId: () => mockGeneratedId,
  api: {
    listChildren: (...args) => listChildrenMock(...args),
  },
}));

async function drainQueue() {
  const all = await getQueue();
  for (const item of all) await removeFromQueue(item.id);
}

async function seed(overrides = {}) {
  return enqueueRequest({
    method: "POST",
    url: "/children/1/feeding-logs",
    body: JSON.stringify({ feed_type: "asi_langsung" }),
    userId: 1,
    clientRequestId: "req-1",
    ...overrides,
  });
}

function setOnline(value) {
  Object.defineProperty(window.navigator, "onLine", { value, configurable: true });
}

/**
 * Nunggu sesaat abis mount — dipakai cuma buat test yang sengaja mount
 * dengan navigator OFFLINE (biar mount effect nggak ikut nyoba sync
 * sendiri), jadi aman nunggu durasi pendek doang.
 */
async function settleMount() {
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 20));
  });
}

beforeEach(async () => {
  mockUserId = 1;
  mockToken = "token-user-1";
  mockGeneratedId = "generated-id";
  listChildrenMock.mockReset();
  await drainQueue();
  global.fetch = vi.fn();
  setOnline(true);
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("useOfflineSync", () => {
  it("1. successfully syncs a queued record (mount auto-sync)", async () => {
    await seed();
    global.fetch.mockResolvedValueOnce({ ok: true, status: 201, headers: { get: () => null } });

    renderHook(() => useOfflineSync());

    await waitFor(async () => {
      expect(await getQueue()).toHaveLength(0);
    });
  });

  it("2. retains item on network failure, then syncs on a later successful retry", async () => {
    setOnline(false); // biar mount effect nggak ikut nyoba sync sendiri, kita kendaliin manual
    const { result } = renderHook(() => useOfflineSync());
    await settleMount();

    const id = await seed();
    global.fetch.mockRejectedValueOnce(new TypeError("Failed to fetch"));

    await act(async () => {
      await result.current.syncNow();
    });

    const [item] = await getQueue();
    expect(item.id).toBe(id);
    expect(item.attempts).toBe(1);
    expect(item.nextRetryAt).toBeTruthy();

    // waktu retry beneran dijadwalin lewat backoff timer di production;
    // di sini kita simulasikan waktunya udah sampai biar retry langsung
    // dicoba tanpa nunggu real time
    await updateQueueItem(id, { nextRetryAt: null });
    global.fetch.mockResolvedValueOnce({ ok: true, status: 201, headers: { get: () => null } });

    await act(async () => {
      await result.current.syncNow();
    });

    expect(await getQueue()).toHaveLength(0);
  });

  it("3. retains item and schedules backoff on a 500 response", async () => {
    await seed();
    global.fetch.mockResolvedValueOnce({
      ok: false,
      status: 500,
      headers: { get: () => null },
      json: async () => ({}),
    });

    const { result } = renderHook(() => useOfflineSync());

    await waitFor(() => expect(result.current.status).toBe("retry_scheduled"));

    const [item] = await getQueue();
    expect(item.attempts).toBe(1);
    expect(item.nextRetryAt).toBeTruthy();
  });

  it("4. retains item and honors Retry-After on a 429 response", async () => {
    await seed();
    global.fetch.mockResolvedValueOnce({
      ok: false,
      status: 429,
      headers: { get: (name) => (name === "Retry-After" ? "2" : null) },
      json: async () => ({}),
    });

    const before = Date.now();
    renderHook(() => useOfflineSync());

    await waitFor(async () => {
      const [item] = await getQueue();
      expect(item.nextRetryAt).toBeTruthy();
    });

    const [item] = await getQueue();
    const delay = new Date(item.nextRetryAt).getTime() - before;
    expect(delay).toBeGreaterThanOrEqual(1900);
    expect(delay).toBeLessThanOrEqual(3000);
  });

  it("5a. 401 pauses the whole run without touching any item", async () => {
    await seed({ url: "/children/1/feeding-logs", clientRequestId: "req-1" });
    await seed({ url: "/children/1/sleep-logs", clientRequestId: "req-2" });
    global.fetch.mockResolvedValueOnce({
      ok: false,
      status: 401,
      headers: { get: () => null },
      json: async () => ({ error: "Belum login" }),
    });

    const { result } = renderHook(() => useOfflineSync());

    await waitFor(() => expect(result.current.status).toBe("auth_required"));

    expect(global.fetch).toHaveBeenCalledTimes(1); // item ke-2 nggak sempat dicoba
    const items = await getQueue();
    expect(items).toHaveLength(2);
    expect(items.every((i) => i.attempts === 0)).toBe(true);
  });

  it("5b. 403 parks the item as needs_review (access_revoked) and lets the next item still sync", async () => {
    await seed({ url: "/children/1/feeding-logs", clientRequestId: "req-1" });
    await seed({ url: "/children/1/sleep-logs", clientRequestId: "req-2" });
    global.fetch
      .mockResolvedValueOnce({
        ok: false,
        status: 403,
        headers: { get: () => null },
        json: async () => ({ error: "Tidak diizinkan" }),
      })
      .mockResolvedValueOnce({ ok: true, status: 201, headers: { get: () => null } });

    const { result } = renderHook(() => useOfflineSync());

    await waitFor(() => expect(result.current.needsReviewCount).toBe(1));

    expect(global.fetch).toHaveBeenCalledTimes(2); // BEDA dari 401 — item ke-2 tetap dicoba
    const items = await getQueue();
    expect(items).toHaveLength(1);
    expect(items[0].status).toBe("needs_review");
    expect(items[0].reviewReason).toBe("access_revoked");
    expect(result.current.status).not.toBe("auth_required");
  });

  it("6. parks a 400 validation error as needs_review and continues to the next item", async () => {
    await seed({ url: "/children/1/feeding-logs", clientRequestId: "req-1" });
    await seed({ url: "/children/1/sleep-logs", clientRequestId: "req-2" });
    global.fetch
      .mockResolvedValueOnce({
        ok: false,
        status: 400,
        headers: { get: () => null },
        json: async () => ({ error: "feed_type wajib diisi" }),
      })
      .mockResolvedValueOnce({ ok: true, status: 201, headers: { get: () => null } });

    const { result } = renderHook(() => useOfflineSync());

    await waitFor(() => expect(result.current.needsReviewCount).toBe(1));

    expect(global.fetch).toHaveBeenCalledTimes(2); // item rusak nggak mem-block item ke-2
    const items = await getQueue();
    expect(items).toHaveLength(1);
    expect(items[0].status).toBe("needs_review");
    expect(items[0].lastError).toBe("feed_type wajib diisi");
  });

  it("7. logout leaves queued items untouched and isolated", async () => {
    const id = await seed();
    mockUserId = null; // logout sebelum sempat sync

    const { result } = renderHook(() => useOfflineSync());
    await settleMount();

    expect(global.fetch).not.toHaveBeenCalled();
    const [item] = await getQueue();
    expect(item.id).toBe(id);
    expect(item.status).toBe("pending");
    expect(result.current.pendingCount).toBe(0); // nggak ada user aktif buat ditampilin
  });

  it("8. a second user's session never syncs the first user's queued items", async () => {
    const id = await seed({ userId: 1 });
    mockUserId = 2; // user lain login di device yang sama

    renderHook(() => useOfflineSync());
    await settleMount();

    expect(global.fetch).not.toHaveBeenCalled();
    const [item] = await getQueue();
    expect(item.id).toBe(id);
    expect(item.userId).toBe(1);
    expect(item.attempts).toBe(0);
  });

  it("9. overlapping sync attempts don't double-send the same item", async () => {
    setOnline(false);
    const { result } = renderHook(() => useOfflineSync());
    await settleMount();

    await seed();
    let resolveFetch;
    global.fetch.mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          resolveFetch = resolve;
        }),
    );

    await act(async () => {
      const firstRun = result.current.syncNow();
      const secondRun = result.current.syncNow(); // dipanggil sebelum yang pertama selesai — harus no-op
      // tunggu firstRun BENERAN nyampe ke fetch() (lewat beberapa round-trip
      // IndexedDB async) sebelum kita nge-resolve fetch-nya
      await vi.waitFor(() => expect(global.fetch).toHaveBeenCalledTimes(1));
      resolveFetch({ ok: true, status: 201, headers: { get: () => null } });
      await Promise.all([firstRun, secondRun]);
    });

    expect(global.fetch).toHaveBeenCalledTimes(1);
  });

  it("10. reuses the same idempotency key across a retry after a lost response", async () => {
    setOnline(false);
    const { result } = renderHook(() => useOfflineSync());
    await settleMount();

    await seed({ clientRequestId: "stable-key" });
    global.fetch.mockRejectedValueOnce(new TypeError("Failed to fetch"));

    await act(async () => {
      await result.current.syncNow();
    });

    const [afterFailure] = await getQueue();
    await updateQueueItem(afterFailure.id, { nextRetryAt: null });
    global.fetch.mockResolvedValueOnce({ ok: true, status: 201, headers: { get: () => null } });

    await act(async () => {
      await result.current.syncNow();
    });

    const secondCallHeaders = global.fetch.mock.calls[1][1].headers;
    expect(secondCallHeaders["X-Idempotency-Key"]).toBe("stable-key");
  });

  it("11. syncs multiple queued records in their original order", async () => {
    await seed({ url: "/a", clientRequestId: "k1" });
    await seed({ url: "/b", clientRequestId: "k2" });
    await seed({ url: "/c", clientRequestId: "k3" });
    global.fetch.mockResolvedValue({ ok: true, status: 201, headers: { get: () => null } });

    renderHook(() => useOfflineSync());

    await waitFor(async () => {
      expect(await getQueue()).toHaveLength(0);
    });

    const calledUrls = global.fetch.mock.calls.map((call) => call[0]);
    expect(calledUrls).toHaveLength(3);
    expect(calledUrls[0]).toContain("/a");
    expect(calledUrls[1]).toContain("/b");
    expect(calledUrls[2]).toContain("/c");
  });

  it("legacy record stays visible after sanitization and can be claimed once backend confirms child access", async () => {
    setOnline(false);
    const { result } = renderHook(() => useOfflineSync());
    await settleMount();

    const id = await seed({ url: "/children/7/feeding-logs", userId: undefined, clientRequestId: undefined });
    await updateQueueItem(id, {
      ownerUnknown: true,
      status: "needs_review",
      reviewReason: "legacy_unknown_owner",
      clientRequestId: undefined,
    });
    await act(async () => {
      await result.current.syncNow(); // refresh nggak wajib nyala sync, tapi state hook harus baca ulang
    });
    expect(result.current.legacyItems.map((i) => i.id)).toEqual([id]);

    listChildrenMock.mockResolvedValueOnce([{ id: 7, name: "Baby Test" }]);
    global.fetch.mockResolvedValueOnce({ ok: true, status: 201, headers: { get: () => null } });

    let outcome;
    await act(async () => {
      outcome = await result.current.claimLegacyItem(id);
    });

    expect(outcome).toEqual({ claimed: true });

    // claimLegacyItem nge-trigger syncQueue() TANPA nunggunya (biar UI
    // "klaim" nggak keblok nunggu network) — jadi di sini nunggu efeknya
    // beneran kelar (item sukses disync abis diklaim), bukan asumsi udah
    // langsung selesai pas claimLegacyItem() resolve.
    await waitFor(async () => {
      const remaining = await getQueue();
      expect(remaining.some((i) => i.id === id)).toBe(false);
    });
    expect(global.fetch).toHaveBeenCalled();
    const lastCallHeaders = global.fetch.mock.calls[global.fetch.mock.calls.length - 1][1].headers;
    expect(lastCallHeaders["X-Idempotency-Key"]).toBe(mockGeneratedId); // key baru dibikin, item lama nggak punya
  });

  it("legacy claim is rejected (and item stays quarantined) when the current user can't access the referenced child", async () => {
    setOnline(false);
    const { result } = renderHook(() => useOfflineSync());
    await settleMount();

    const id = await seed({ url: "/children/99/feeding-logs", userId: undefined, clientRequestId: "legacy-key" });
    await updateQueueItem(id, { ownerUnknown: true, status: "needs_review", reviewReason: "legacy_unknown_owner" });
    await act(async () => {
      await result.current.syncNow();
    });

    listChildrenMock.mockResolvedValueOnce([{ id: 7, name: "Anak lain" }]); // 99 BUKAN salah satunya

    let outcome;
    await act(async () => {
      outcome = await result.current.claimLegacyItem(id);
    });

    expect(outcome.claimed).toBe(false);
    expect(outcome.reason).toBeTruthy();
    expect(global.fetch).not.toHaveBeenCalled(); // nggak pernah nyoba sync record yang ditolak klaimnya

    const [item] = await getQueue();
    expect(item.id).toBe(id);
    expect(item.ownerUnknown).toBe(true); // tetap dikarantina, nggak disentuh
    expect(item.userId).not.toBe(1); // BUKAN diklaim jadi punya user yang lagi login
  });

  it("5. a successful claim assigns the record to the currently authenticated user's id", async () => {
    setOnline(false);
    const { result } = renderHook(() => useOfflineSync());
    await settleMount();

    const id = await seed({ url: "/children/7/feeding-logs", userId: undefined, clientRequestId: undefined });
    await updateQueueItem(id, { ownerUnknown: true, status: "needs_review", reviewReason: "legacy_unknown_owner" });
    await act(async () => {
      await result.current.syncNow();
    });

    listChildrenMock.mockResolvedValueOnce([{ id: 7, name: "Baby Test" }]);
    // fetch tetap gagal (network) abis diklaim — sengaja, biar item TETAP
    // ada di antrian dan kita bisa periksa field userId-nya langsung,
    // bukan cuma nyimpulkan dari "item udah kesync"
    global.fetch.mockRejectedValueOnce(new TypeError("Failed to fetch"));

    let outcome;
    await act(async () => {
      outcome = await result.current.claimLegacyItem(id);
    });
    expect(outcome).toEqual({ claimed: true });

    await waitFor(async () => {
      const [item] = await getQueue();
      expect(item.userId).toBe(1);
    });
    const [item] = await getQueue();
    expect(item.ownerUnknown).toBe(false);
    expect(item.reviewReason).toBeFalsy();
  });

  describe("401 re-authentication flow", () => {
    it("retains queued records after pausing on 401 (they are never touched)", async () => {
      const id = await seed();
      global.fetch.mockResolvedValueOnce({
        ok: false,
        status: 401,
        headers: { get: () => null },
        json: async () => ({ error: "Belum login" }),
      });

      const { result } = renderHook(() => useOfflineSync());
      await waitFor(() => expect(result.current.status).toBe("auth_required"));

      const [item] = await getQueue();
      expect(item.id).toBe(id);
      expect(item.status).toBe("pending"); // TIDAK diubah, TIDAK dihapus
    });

    it("cancels the scheduled retry timer on unmount (logout), not just a generic cleanup call", async () => {
      // Dites lewat spy setTimeout/clearTimeout ASLI (bukan fake timers) —
      // fake timers berisiko nyangkut kalau fake-indexeddb internalnya
      // pakai setTimeout juga buat jadwalin callback IDBRequest-nya. Yang
      // mau dibuktiin di sini spesifik: id timer YANG DIJADWALIN buat
      // retry (delay match BACKOFF_BASE_MS = 5000ms) itu SAH dikirim ke
      // clearTimeout pas hook-nya di-unmount, bukan cuma "clearTimeout
      // kepanggil doang" (yang bisa aja cuma dari cleanup timer lain yang
      // nggak nyala).
      const setTimeoutSpy = vi.spyOn(global, "setTimeout");
      const clearTimeoutSpy = vi.spyOn(global, "clearTimeout");

      await seed();
      global.fetch.mockResolvedValueOnce({
        ok: false,
        status: 500,
        headers: { get: () => null },
        json: async () => ({}),
      });

      const { unmount } = renderHook(() => useOfflineSync());
      await waitFor(() => expect(global.fetch).toHaveBeenCalledTimes(1));

      const retryCallIndex = setTimeoutSpy.mock.calls.findIndex(([, delay]) => delay === 5000);
      expect(retryCallIndex).toBeGreaterThanOrEqual(0); // retry beneran dijadwalin abis 500
      const scheduledTimerId = setTimeoutSpy.mock.results[retryCallIndex].value;

      unmount();

      const clearedIds = clearTimeoutSpy.mock.calls.map(([id]) => id);
      expect(clearedIds).toContain(scheduledTimerId);

      setTimeoutSpy.mockRestore();
      clearTimeoutSpy.mockRestore();
    });

    it("resuming sync after logging back in as the SAME user (fresh hook mount) succeeds", async () => {
      const id = await seed();
      global.fetch.mockResolvedValueOnce({
        ok: false,
        status: 401,
        headers: { get: () => null },
        json: async () => ({ error: "Belum login" }),
      });

      const first = renderHook(() => useOfflineSync());
      await waitFor(() => expect(first.result.current.status).toBe("auth_required"));
      first.unmount(); // "Masuk lagi" -> AuthContext.logout() -> komponen unmount

      // user login lagi SEBAGAI AKUN YANG SAMA -> App.jsx nge-mount ulang
      // OfflineStatusBanner/useOfflineSync dari nol
      global.fetch.mockResolvedValueOnce({ ok: true, status: 201, headers: { get: () => null } });
      renderHook(() => useOfflineSync());

      await waitFor(async () => {
        const remaining = await getQueue();
        expect(remaining.some((i) => i.id === id)).toBe(false);
      });
    });

    it("logging in as a DIFFERENT user after a 401 does not synchronize the previous user's queued records", async () => {
      const id = await seed({ userId: 1 });
      global.fetch.mockResolvedValueOnce({
        ok: false,
        status: 401,
        headers: { get: () => null },
        json: async () => ({ error: "Belum login" }),
      });

      const first = renderHook(() => useOfflineSync());
      await waitFor(() => expect(first.result.current.status).toBe("auth_required"));
      first.unmount();

      mockUserId = 2; // akun LAIN login di device yang sama
      global.fetch.mockClear();
      renderHook(() => useOfflineSync());
      await settleMount();

      expect(global.fetch).not.toHaveBeenCalled();
      const [item] = await getQueue();
      expect(item.id).toBe(id);
      expect(item.userId).toBe(1); // tetap punya user 1, TIDAK disync pakai sesi user 2
    });
  });
});
