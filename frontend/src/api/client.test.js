import { beforeEach, describe, expect, it, vi } from "vitest";
import { api, ApiError, setToken, setCurrentUser, clearToken, clearCurrentUser } from "./client";
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

describe("api client — Medication Schedule & Adherence occurrence actions are offline-queueable", () => {
  it("administerMedicationDose falls back to the offline queue on a network failure", async () => {
    global.fetch.mockRejectedValueOnce(new TypeError("Failed to fetch"));

    const result = await api.administerMedicationDose(1, 5, "2026-08-23T08:00");

    expect(result._offlineQueued).toBe(true);
    const [queued] = await getQueue();
    expect(queued.url).toBe("/children/1/medication-schedules/5/occurrences/2026-08-23T08:00/administer");
    expect(queued.userId).toBe(7);
    expect(queued.clientRequestId).toBeTruthy();
  });

  it("skipMedicationDose falls back to the offline queue on a network failure", async () => {
    global.fetch.mockRejectedValueOnce(new TypeError("Failed to fetch"));

    const result = await api.skipMedicationDose(1, 5, "2026-08-23T08:00");

    expect(result._offlineQueued).toBe(true);
    const [queued] = await getQueue();
    expect(queued.url).toBe("/children/1/medication-schedules/5/occurrences/2026-08-23T08:00/skip");
  });

  it("createMedicationSchedule (definition CRUD) is NOT offline-queueable — a network failure throws instead", async () => {
    global.fetch.mockRejectedValueOnce(new TypeError("Failed to fetch"));

    await expect(api.createMedicationSchedule(1, { medication_name: "Obat" })).rejects.toMatchObject({
      kind: "network",
    });
    expect(await getQueue()).toHaveLength(0);
  });

  it("a normal online administer resolves directly and never touches the offline queue", async () => {
    const serverResponse = { id: 1, status: "administered", medication_log_id: 10 };
    global.fetch.mockResolvedValueOnce({ ok: true, status: 201, json: async () => serverResponse });

    const result = await api.administerMedicationDose(1, 5, "2026-08-23T08:00");

    expect(result).toEqual(serverResponse);
    expect(result._offlineQueued).toBeUndefined();
    expect(await getQueue()).toHaveLength(0);
    const [, fetchOptions] = global.fetch.mock.calls[0];
    expect(fetchOptions.headers["X-Idempotency-Key"]).toBeTruthy();
  });
});

describe("api client — structured error classification (ApiError)", () => {
  // /auth/me (GET) dipakai sebagai endpoint contoh — BUKAN offline-
  // queueable, jadi kegagalan jaringan di sini beneran nge-throw
  // (bukan diam-diam masuk antrian kayak createFeeding).

  it("a genuine network failure throws an ApiError with kind 'network' (never treated as a rejected session)", async () => {
    global.fetch.mockRejectedValue(new TypeError("Failed to fetch"));

    await expect(api.me()).rejects.toMatchObject({
      kind: "network",
      status: null,
      message: "Nggak ada koneksi internet. Coba lagi nanti.",
    });
    await expect(api.me()).rejects.toBeInstanceOf(ApiError);
  });

  it("a 401 response throws an ApiError with kind 'unauthorized', preserving the server's message", async () => {
    global.fetch.mockResolvedValueOnce({
      ok: false,
      status: 401,
      json: async () => ({ error: "Sesi tidak valid" }),
    });

    await expect(api.me()).rejects.toMatchObject({
      kind: "unauthorized",
      status: 401,
      message: "Sesi tidak valid",
    });
  });

  it("a 403 response throws an ApiError with kind 'forbidden'", async () => {
    global.fetch.mockResolvedValueOnce({
      ok: false,
      status: 403,
      json: async () => ({ error: "Tidak punya akses" }),
    });

    await expect(api.listChildren()).rejects.toMatchObject({ kind: "forbidden", status: 403 });
  });

  it("a 422 response throws an ApiError with kind 'validation'", async () => {
    global.fetch.mockResolvedValueOnce({
      ok: false,
      status: 422,
      json: async () => ({ error: "Data tidak valid" }),
    });

    await expect(api.listChildren()).rejects.toMatchObject({ kind: "validation", status: 422 });
  });

  it("a 500 response throws an ApiError with kind 'server_error'", async () => {
    global.fetch.mockResolvedValueOnce({
      ok: false,
      status: 500,
      json: async () => ({}),
    });

    await expect(api.listChildren()).rejects.toMatchObject({ kind: "server_error", status: 500 });
  });

  it("an unrecognized error status still falls back to a readable message ('http_error')", async () => {
    global.fetch.mockResolvedValueOnce({
      ok: false,
      status: 404,
      json: async () => ({}),
    });

    await expect(api.listChildren()).rejects.toMatchObject({
      kind: "http_error",
      status: 404,
      message: "Request gagal (404)",
    });
  });

  it("ApiError never carries the raw response body — only status/kind/message", async () => {
    global.fetch.mockResolvedValueOnce({
      ok: false,
      status: 401,
      json: async () => ({ error: "Sesi tidak valid", stack_trace: "sensitive internals", token: "should-not-leak" }),
    });

    try {
      await api.me();
      expect.unreachable();
    } catch (err) {
      expect(err.message).toBe("Sesi tidak valid");
      expect(err.kind).toBe("unauthorized");
      expect(err.status).toBe(401);
      expect(err.stack_trace).toBeUndefined();
      expect(err.token).toBeUndefined();
    }
  });
});
