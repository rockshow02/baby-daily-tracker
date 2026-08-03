/**
 * Antrian offline pakai IndexedDB — nyimpen request POST/PUT/DELETE yang
 * gagal dikirim karena nggak ada koneksi, buat dicoba lagi otomatis begitu
 * online. Beda dari localStorage, IndexedDB tetap ada walau app ditutup
 * total (bukan cuma di-refresh), dan bisa nyimpen data lebih banyak/lebih
 * terstruktur.
 */

const DB_NAME = "babytracker_offline";
const DB_VERSION = 1;
const STORE_NAME = "pending_requests";

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
 * (string JSON atau null), headers (object biasa), dan opsional
 * `localId` (buat ngerelasiin ke item optimistic di UI).
 */
export async function enqueueRequest(entry) {
  const db = await openDB();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(STORE_NAME, "readwrite");
    const store = tx.objectStore(STORE_NAME);
    const req = store.add({ ...entry, queuedAt: new Date().toISOString() });
    req.onsuccess = () => resolve(req.result); // return id antrian
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

export async function removeFromQueue(id) {
  const db = await openDB();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(STORE_NAME, "readwrite");
    const store = tx.objectStore(STORE_NAME);
    const req = store.delete(id);
    req.onsuccess = () => resolve();
    req.onerror = () => reject(req.error);
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
