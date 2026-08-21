/**
 * Antrian offline pakai IndexedDB — nyimpen request POST yang gagal
 * dikirim karena nggak ada koneksi, buat dicoba lagi otomatis begitu
 * online. Beda dari localStorage, IndexedDB tetap ada walau app ditutup
 * total (bukan cuma di-refresh), dan bisa nyimpen data lebih banyak/lebih
 * terstruktur.
 *
 * Tiap item nyimpen `userId` (bukan token!) biar syncQueue di
 * useOfflineSync bisa mastiin dia cuma nge-sync antrian punya user yang
 * LAGI aktif sekarang, dan `clientRequestId` (idempotency key) biar retry
 * nggak pernah bikin record dobel di server.
 */

const DB_NAME = "babytracker_offline";
const DB_VERSION = 1;
const STORE_NAME = "pending_requests";

/**
 * Nama event window yang di-dispatch SETIAP KALI antrian IndexedDB
 * berhasil berubah (item ditambah/dihapus/diupdate) — SATU nama konstan,
 * dipakai bareng oleh useOfflineSync dan Dashboard biar keduanya bisa
 * bereaksi tanpa perlu polling atau state global baru. Event ini SENGAJA
 * nggak bawa detail/payload — listener yang mau tau perubahannya, baca
 * ulang dari IndexedDB sendiri (satu-satunya sumber kebenaran), bukan
 * percaya isi event-nya. Aman di-dispatch berkali-kali beruntun; listener
 * (mis. reconciliation di Dashboard) idempotent terhadap itu.
 */
export const QUEUE_CHANGE_EVENT = "babytracker:offline-queue-changed";

function dispatchQueueChangeEvent() {
  if (typeof window !== "undefined" && typeof window.dispatchEvent === "function") {
    window.dispatchEvent(new CustomEvent(QUEUE_CHANGE_EVENT));
  }
}

export const QUEUE_STATUS = {
  PENDING: "pending",
  NEEDS_REVIEW: "needs_review",
};

/** Kenapa 1 item lagi nunggu ditinjau manual — dipakai buat nentuin pesan & aksi yang ditawarin di UI. */
export const REVIEW_REASON = {
  VALIDATION: "validation", // server nolak datanya (400/422)
  ACCESS_REVOKED: "access_revoked", // 403 — kemungkinan udah nggak punya akses ke anak ini
  CONFLICT: "conflict", // 409 — idempotency key ini udah kepake buat data yang BEDA
  LEGACY_UNKNOWN_OWNER: "legacy_unknown_owner", // dari sebelum fitur kepemilikan antrian ada
};

// Label tipe catatan yang manusiawi, dicocokin dari pola URL-nya — dipakai
// buat nampilin "Menyusui" dkk di panel review, bukan endpoint mentah.
const TYPE_LABELS = [
  { match: /\/feeding-logs$/, label: "Menyusui" },
  { match: /\/sleep-logs$/, label: "Tidur" },
  { match: /\/diaper-logs$/, label: "Popok" },
  { match: /\/pumping-logs$/, label: "Perah ASI" },
  { match: /\/activity-logs$/, label: "Aktivitas" },
  { match: /\/medication-logs$/, label: "Obat" },
];

// Field body yang ditampilin di ringkasan per tipe — SENGAJA nggak
// nyertain `notes` (teks bebas) biar ringkasan tetap "non-sensitive":
// cukup buat user ngenalin record-nya, tanpa nampilin catatan bebas apa
// adanya di panel review.
const SUMMARY_FIELDS = {
  "Menyusui": ["feed_type", "duration_minutes", "volume_ml", "breast_side"],
  "Tidur": ["start_time", "end_time", "sleep_type"],
  "Popok": ["diaper_type", "consistency", "color"],
  "Perah ASI": ["duration_minutes", "volume_ml", "breast_side"],
  "Aktivitas": ["activity_type", "duration_minutes"],
  "Obat": ["medication_name", "dosage"],
};

function describeType(url) {
  const found = TYPE_LABELS.find((t) => t.match.test(url || ""));
  return found ? found.label : "Catatan";
}

// Diekspor — dipakai ulang di utils/offlineHistoryMapping.js biar pola
// ekstraksi child id dari URL antrian nggak duplikat di dua tempat.
export function extractChildId(url) {
  const m = (url || "").match(/\/children\/(\d+)\//);
  return m ? Number(m[1]) : null;
}

/**
 * Ringkasan "aman ditampilkan" dari 1 item antrian — tipe catatan yang
 * manusiawi, anak yang dituju, kapan dicatat (lokal), dan field-field
 * struktural utamanya (bukan `notes` bebas). Dipakai bareng buat panel
 * legacy (item nggak jelas pemiliknya) dan panel needs-review.
 */
export function describeQueueItem(item) {
  const typeLabel = describeType(item.url);
  const childId = extractChildId(item.url);
  const summary = {};
  try {
    const parsed = item.body ? JSON.parse(item.body) : {};
    const fields = SUMMARY_FIELDS[typeLabel] || [];
    for (const key of fields) {
      if (parsed[key] !== undefined && parsed[key] !== null && parsed[key] !== "") {
        summary[key] = parsed[key];
      }
    }
  } catch (_) {
    // body bukan JSON valid — ringkasan kosong aja, jangan sampai gagal total
  }
  return { typeLabel, childId, queuedAt: item.queuedAt, summary };
}

function openDB() {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open(DB_NAME, DB_VERSION);
    req.onupgradeneeded = () => {
      const db = req.result;
      if (!db.objectStoreNames.contains(STORE_NAME)) {
        db.createObjectStore(STORE_NAME, {
          keyPath: "id",
          autoIncrement: true,
        });
      }
    };
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}

/**
 * Tambah 1 request ke antrian. `entry` harus punya: method, url, body
 * (string JSON atau null), userId (pemilik request ini), dan
 * clientRequestId (idempotency key yang dibuat client.js).
 */
export async function enqueueRequest(entry) {
  const db = await openDB();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(STORE_NAME, "readwrite");
    const store = tx.objectStore(STORE_NAME);
    const req = store.add({
      method: entry.method,
      url: entry.url,
      body: entry.body ?? null,
      userId: entry.userId ?? null,
      clientRequestId: entry.clientRequestId,
      status: QUEUE_STATUS.PENDING,
      attempts: 0,
      nextRetryAt: null,
      lastError: null,
      queuedAt: new Date().toISOString(),
    });
    req.onsuccess = () => {
      dispatchQueueChangeEvent(); // SETELAH commit — bukan sebelum, biar listener yang baca ulang selalu liat data terbaru
      resolve(req.result); // return id antrian
    };
    req.onerror = () => reject(req.error);
  });
}

export async function getQueue() {
  const db = await openDB();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(STORE_NAME, "readonly");
    const store = tx.objectStore(STORE_NAME);
    const req = store.getAll();
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}

/** Semua item punya user tertentu — antrian kecil, filter di JS udah cukup cepat. */
export async function getQueueForUser(userId) {
  const all = await getQueue();
  return all.filter((item) => item.userId === userId);
}

/**
 * Item "legacy" — kepemilikannya belum/nggak bisa dipastikan (biasanya
 * dari sebelum fitur penandaan pemilik antrian ada). SENGAJA independen
 * dari userId (bukan cuma nggak match user manapun) biar tetap kelihatan
 * di UI dan bisa di-klaim atau dibuang manual, bukan ilang gitu aja dari
 * getQueueForUser().
 */
export async function getLegacyItems() {
  const all = await getQueue();
  return all.filter((item) => item.ownerUnknown === true);
}

export async function removeFromQueue(id) {
  const db = await openDB();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(STORE_NAME, "readwrite");
    const store = tx.objectStore(STORE_NAME);
    const req = store.delete(id);
    req.onsuccess = () => {
      dispatchQueueChangeEvent();
      resolve();
    };
    req.onerror = () => reject(req.error);
  });
}

/** Update sebagian field 1 item (status, attempts, nextRetryAt, lastError, dst) tanpa hapus datanya. */
export async function updateQueueItem(id, patch) {
  const db = await openDB();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(STORE_NAME, "readwrite");
    const store = tx.objectStore(STORE_NAME);
    const getReq = store.get(id);
    getReq.onsuccess = () => {
      const existing = getReq.result;
      if (!existing) {
        resolve(null);
        return;
      }
      const updated = { ...existing, ...patch };
      const putReq = store.put(updated);
      putReq.onsuccess = () => {
        dispatchQueueChangeEvent();
        resolve(updated);
      };
      putReq.onerror = () => reject(putReq.error);
    };
    getReq.onerror = () => reject(getReq.error);
  });
}

export async function getQueueCount() {
  const db = await openDB();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(STORE_NAME, "readonly");
    const store = tx.objectStore(STORE_NAME);
    const req = store.count();
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}

/**
 * Bersihin item antrian lama (dari sebelum fitur ini ada) yang masih
 * nyimpen token Authorization mentah di dalamnya — itu bug privasi yang
 * lagi diperbaiki. Kita LEPAS token-nya (bukan hapus itemnya, data
 * catatan bayinya tetap disimpan) dan tandai "needs_review" karena kita
 * nggak bisa mastiin lagi ini punya user yang mana. Aman dipanggil
 * berkali-kali — item yang udah bersih dilewatin.
 */
export async function sanitizeLegacyQueue() {
  const all = await getQueue();
  const legacy = all.filter((item) => item.headers?.Authorization);
  for (const item of legacy) {
    // `headers: undefined` di-set EKSPLISIT (bukan cuma dihilangkan dari
    // patch) — updateQueueItem nge-merge patch di atas record yang ada,
    // jadi kalau cuma dihilangkan, token lama di `headers` bakal tetep
    // nyangkut.
    await updateQueueItem(item.id, {
      headers: undefined,
      status: QUEUE_STATUS.NEEDS_REVIEW,
      ownerUnknown: true,
      reviewReason: REVIEW_REASON.LEGACY_UNKNOWN_OWNER,
      lastError: "Catatan lama dari sebelum pembaruan — kepemilikan akun belum bisa dipastikan.",
    });
  }
  return legacy.length;
}
