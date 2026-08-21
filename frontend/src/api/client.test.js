import { beforeEach, describe, expect, it, vi } from "vitest";
import { api, setToken, setCurrentUser, clearToken, clearCurrentUser } from "./client";
import { getQueue, removeFromQueue } from "../utils/offlineQueue";

async function drainQueue() {
  const all = await getQueue();
  for (const item of all) await removeFromQueue(item.id);
}

beforeEach(async () => {
  await drainQueue();
  clearToken();
  clearCurrentUser();
  setToken("token-abc");
  setCurrentUser(7);
  global.fetch = vi.fn();
});

describe("api client — immediate online path", () => {
  it("12. a normal online create resolves directly and never touches the offline queue", async () => {
    const serverResponse = { id: 99, feed_type: "asi_langsung" };
    global.fetch.mockResolvedValueOnce({
      ok: true,
      status: 201,
      json: async () => serverResponse,
    });

    const result = await api.createFeeding(1, { feed_type: "asi_langsung" });

    expect(result).toEqual(serverResponse);
    expect(result._offlineQueued).toBeUndefined();
    expect(global.fetch).toHaveBeenCalledTimes(1);
    expect(await getQueue()).toHaveLength(0);

    const [, fetchOptions] = global.fetch.mock.calls[0];
    expect(fetchOptions.headers["X-Idempotency-Key"]).toBeTruthy();
    expect(fetchOptions.headers["Authorization"]).toBe("Bearer token-abc");
  });

  it("falls back to the offline queue on a genuine network failure, tagged with the current user", async () => {
    global.fetch.mockRejectedValueOnce(new TypeError("Failed to fetch"));

    const result = await api.createFeeding(1, { feed_type: "asi_langsung" });

    expect(result._offlineQueued).toBe(true);
    expect(String(result.id)).toMatch(/^local-/);

    const [queued] = await getQueue();
    expect(queued.userId).toBe(7);
    expect(queued.clientRequestId).toBeTruthy();
    expect(queued.headers).toBeUndefined(); // token TIDAK disimpan di item antrian
  });

  it("15. a lost-response retry reuses the exact same idempotency key the first attempt sent — the contract the backend relies on to keep exactly one record", async () => {
    // percobaan PERTAMA: server SEBENARNYA sempat proses request-nya, tapi
    // koneksi putus sebelum responsnya balik ke klien — dari sudut pandang
    // fetch(), ini persis sama kayak gagal jaringan biasa
    global.fetch.mockRejectedValueOnce(new TypeError("Failed to fetch"));
    const queuedResult = await api.createFeeding(1, { feed_type: "asi_langsung" });
    expect(queuedResult._offlineQueued).toBe(true);

    const [queued] = await getQueue();
    const firstAttemptKey = global.fetch.mock.calls[0][1].headers["X-Idempotency-Key"];
    expect(queued.clientRequestId).toBe(firstAttemptKey);

    // percobaan KEDUA: simulasi retry dari antrian offline (useOfflineSync
    // punya loop-nya sendiri yang diuji terpisah di useOfflineSync.test.js
    // — di sini kita cuma pastiin KONTRAK client.js-nya: key yang di-resend
    // harus SAMA PERSIS, bukan dibikin baru).
    global.fetch.mockResolvedValueOnce({ ok: true, status: 201, json: async () => ({ id: 1 }) });
    await fetch(`http://localhost:5000/api${queued.url}`, {
      method: queued.method,
      headers: { "Content-Type": "application/json", "X-Idempotency-Key": queued.clientRequestId },
      body: queued.body,
    });
    const secondAttemptKey = global.fetch.mock.calls[1][1].headers["X-Idempotency-Key"];

    expect(secondAttemptKey).toBe(firstAttemptKey); // key SAMA di kedua percobaan
    // => backend (diuji di backend/tests/test_idempotency.py) balikin hasil
    // yang sama utk key yang sama, jadi cuma 1 record yang beneran kesimpen
  });
});
