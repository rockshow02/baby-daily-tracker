import { beforeEach, describe, expect, it } from "vitest";
import {
  enqueueRequest,
  getQueue,
  getQueueForUser,
  getLegacyItems,
  getQueueCount,
  removeFromQueue,
  updateQueueItem,
  sanitizeLegacyQueue,
  describeQueueItem,
  QUEUE_STATUS,
  REVIEW_REASON,
} from "./offlineQueue";

async function drainQueue() {
  const all = await getQueue();
  for (const item of all) {
    await removeFromQueue(item.id);
  }
}

beforeEach(async () => {
  await drainQueue();
});

describe("offlineQueue", () => {
  it("enqueues a request with owner, idempotency key, and pending status — never a token", async () => {
    const id = await enqueueRequest({
      method: "POST",
      url: "/children/1/feeding-logs",
      body: JSON.stringify({ feed_type: "asi_langsung" }),
      userId: 42,
      clientRequestId: "req-1",
    });

    const [item] = await getQueue();
    expect(item.id).toBe(id);
    expect(item.userId).toBe(42);
    expect(item.clientRequestId).toBe("req-1");
    expect(item.status).toBe(QUEUE_STATUS.PENDING);
    expect(item.attempts).toBe(0);
    expect(item.headers).toBeUndefined();
  });

  it("counts and lists queued items", async () => {
    await enqueueRequest({ method: "POST", url: "/a", userId: 1, clientRequestId: "k1" });
    await enqueueRequest({ method: "POST", url: "/b", userId: 1, clientRequestId: "k2" });

    expect(await getQueueCount()).toBe(2);
  });

  it("filters items by owner", async () => {
    await enqueueRequest({ method: "POST", url: "/a", userId: 1, clientRequestId: "k1" });
    await enqueueRequest({ method: "POST", url: "/b", userId: 2, clientRequestId: "k2" });

    const forUser1 = await getQueueForUser(1);
    expect(forUser1).toHaveLength(1);
    expect(forUser1[0].url).toBe("/a");
  });

  it("removes an item without touching others", async () => {
    const idA = await enqueueRequest({ method: "POST", url: "/a", userId: 1, clientRequestId: "k1" });
    const idB = await enqueueRequest({ method: "POST", url: "/b", userId: 1, clientRequestId: "k2" });

    await removeFromQueue(idA);

    const remaining = await getQueue();
    expect(remaining.map((i) => i.id)).toEqual([idB]);
  });

  it("updates fields on an item in place (patch, not replace)", async () => {
    const id = await enqueueRequest({ method: "POST", url: "/a", userId: 1, clientRequestId: "k1" });

    await updateQueueItem(id, { status: QUEUE_STATUS.NEEDS_REVIEW, lastError: "invalid" });

    const [item] = await getQueue();
    expect(item.status).toBe(QUEUE_STATUS.NEEDS_REVIEW);
    expect(item.lastError).toBe("invalid");
    expect(item.url).toBe("/a"); // field lain tetap ada
  });

  it("strips a legacy stored token without deleting the record, and keeps it visible for recovery", async () => {
    const id = await enqueueRequest({
      method: "POST",
      url: "/children/7/feeding-logs",
      body: JSON.stringify({ feed_type: "asi_langsung" }),
      userId: null,
      clientRequestId: "k1",
    });
    // simulasikan entri lama (sebelum fix) yang masih nyimpen token
    await updateQueueItem(id, { headers: { Authorization: "Bearer leaked-token" } });

    const strippedCount = await sanitizeLegacyQueue();
    expect(strippedCount).toBe(1);

    const [item] = await getQueue();
    expect(item.id).toBe(id); // record TETAP ADA, cuma token-nya dibersihin
    expect(item.headers?.Authorization).toBeUndefined();
    expect(item.status).toBe(QUEUE_STATUS.NEEDS_REVIEW);
    expect(item.ownerUnknown).toBe(true);
    expect(item.reviewReason).toBe(REVIEW_REASON.LEGACY_UNKNOWN_OWNER);

    // getQueueForUser TIDAK bisa nemuin ini lagi (userId-nya nggak jelas),
    // tapi getLegacyItems() HARUS tetap nemuin — ini yang bikin record ini
    // "recoverable" alih-alih ilang selamanya dari UI
    expect(await getQueueForUser(1)).toHaveLength(0);
    const legacy = await getLegacyItems();
    expect(legacy.map((i) => i.id)).toEqual([id]);
  });

  it("is a no-op when there is nothing legacy to sanitize", async () => {
    await enqueueRequest({ method: "POST", url: "/a", userId: 1, clientRequestId: "k1" });
    const strippedCount = await sanitizeLegacyQueue();
    expect(strippedCount).toBe(0);
    expect(await getLegacyItems()).toHaveLength(0);
  });

  it("describeQueueItem builds a human label, child reference, and a summary without free-text notes", () => {
    const item = {
      url: "/children/7/feeding-logs",
      queuedAt: "2026-01-01T10:00:00.000Z",
      body: JSON.stringify({
        feed_type: "asi_langsung",
        duration_minutes: 12,
        notes: "catatan pribadi yang sensitif",
      }),
    };

    const described = describeQueueItem(item);

    expect(described.typeLabel).toBe("Menyusui");
    expect(described.childId).toBe(7);
    expect(described.summary).toEqual({ feed_type: "asi_langsung", duration_minutes: 12 });
    expect(described.summary.notes).toBeUndefined();
  });
});
