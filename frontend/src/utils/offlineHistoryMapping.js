/**
 * Helper murni (pure function, gampang dites terpisah) buat ubah 1 item
 * antrian offline (IndexedDB) jadi "record riwayat" yang bisa langsung
 * dirender Dashboard persis kayak record dari server — dipakai buat
 * merestorasi catatan yang masih nunggu sinkron setelah Dashboard di-mount
 * ulang (refresh halaman, buka lagi app-nya, dll), bukan cuma pas
 * baru-catat-langsung (itu udah diurus optimistic di Dashboard sendiri).
 *
 * SENGAJA nggak nyentuh IndexedDB sama sekali di file ini — biar gampang
 * dites tanpa perlu fake-indexeddb, dan biar jelas batasnya: fungsi di
 * sini murni transformasi data, pemanggilnya (Dashboard) yang urus baca
 * dari offlineQueue.js.
 */
import { extractChildId } from "./offlineQueue";
import { toWIBDateStr } from "./date";

// URL endpoint -> "type" internal yang dipakai Dashboard (feed_type dkk
// beda dari label manusiawi "Menyusui" dkk di offlineQueue.js — ini
// spesifik buat nentuin masuk state array yang mana).
const TYPE_BY_PATH = [
  { match: /\/feeding-logs$/, type: "feeding" },
  { match: /\/sleep-logs$/, type: "sleep" },
  { match: /\/diaper-logs$/, type: "diaper" },
  { match: /\/pumping-logs$/, type: "pumping" },
  { match: /\/activity-logs$/, type: "activity" }, // stroll/bathing dibedain dari body.activity_type
  { match: /\/medication-logs$/, type: "vitamin" },
];

/** Tentuin tipe log dari URL antrian. Return null kalau URL-nya nggak dikenali (endpoint yang nggak didukung recovery). */
export function determineLogType(url) {
  const found = TYPE_BY_PATH.find((t) => t.match.test(url || ""));
  return found ? found.type : null;
}

/** Re-export biar pemanggil cuma perlu import dari 1 modul ini buat semua kebutuhan parsing URL antrian. */
export function extractChildIdFromUrl(url) {
  return extractChildId(url);
}

/**
 * Ubah 1 item antrian jadi record riwayat siap-render, atau `null` kalau
 * item-nya nggak aman/nggak bisa direstorasi (endpoint nggak dikenal, body
 * rusak, field waktu kejadian nggak ada, dst) — JANGAN PERNAH throw, biar
 * 1 item antrian yang rusak nggak bisa nge-crash seluruh Dashboard.
 *
 * Item yang statusnya needs_review atau kepemilikannya belum jelas
 * (ownerUnknown) SENGAJA TIDAK ditangani di sini — itu tetap harus lewat
 * QueueReviewPanel, bukan direstorasi diam-diam jadi record riwayat biasa.
 * Pemanggil (Dashboard) yang wajib nyaring itu SEBELUM manggil fungsi ini.
 */
export function mapQueueItemToHistoryRecord(item) {
  if (!item || typeof item.id === "undefined" || typeof item.url !== "string") return null;

  const type = determineLogType(item.url);
  if (!type) return null;

  const childId = extractChildIdFromUrl(item.url);
  if (childId == null) return null;

  let body;
  try {
    body = item.body ? JSON.parse(item.body) : {};
  } catch (_) {
    return null; // body korup — jangan direstorasi, jangan crash
  }
  if (typeof body !== "object" || body === null || Array.isArray(body)) return null;

  // aktivitas generik (stroll/bathing) nentuin "kind"-nya dari isi body,
  // bukan dari endpoint (satu endpoint buat 2 jenis aktivitas)
  const kind = type === "activity" ? body.activity_type : type;
  if (!kind || (type === "activity" && kind !== "stroll" && kind !== "bathing")) return null;

  const at = kind === "sleep" ? body.start_time : body.timestamp;
  if (!at || Number.isNaN(new Date(at).getTime())) return null; // nggak ada/rusak waktu kejadian -> nggak aman direstorasi

  return {
    ...body,
    id: `local-${item.id}`,
    _offlineQueued: true,
    kind,
    at,
    childId,
  };
}

/**
 * True kalau record hasil mapQueueItemToHistoryRecord() "kejadian" di
 * tanggal yang lagi dipilih user (dalam WIB, samain sama gimana Dashboard
 * biasanya nentuin tanggal). Sesi tidur diperlakukan khusus (overlap
 * rentang hari, bukan exact match) — SAMA PERSIS kayak query backend buat
 * sleep-logs, biar sesi yang lintas tengah malam tetap konsisten muncul
 * di kedua hari terkait, sama kayak record yang udah sinkron.
 */
export function matchesSelectedDate(record, dateStr) {
  if (!record?.at || !dateStr) return false;

  if (record.kind === "sleep") {
    const dayStart = new Date(`${dateStr}T00:00:00`);
    const dayEnd = new Date(dayStart.getTime() + 24 * 60 * 60 * 1000);
    const start = new Date(record.at);
    if (Number.isNaN(start.getTime())) return false;
    const end = record.end_time ? new Date(record.end_time) : null;
    if (end && Number.isNaN(end.getTime())) return false;
    return start < dayEnd && (end === null || end > dayStart);
  }

  return toWIBDateStr(new Date(record.at)) === dateStr;
}

/**
 * Rekonsiliasi array 1 tipe log (mis. feedingLogs) — buang entri
 * optimistic (`_offlineQueued`) yang id-nya udah nggak ada lagi di daftar
 * "masih pending" yang baru dibaca (berarti udah kesync ATAU udah dibuang
 * manual), lalu tambahin entri pending baru yang belum ada di array
 * (dicocokin lewat `id`, yang formatnya SELALU "local-<queueId antrian>" —
 * identitas stabil dari IndexedDB, BUKAN dari timestamp/isi payload, biar
 * 2 record yang isinya kebetulan sama persis tetap kebedain).
 *
 * Fungsi murni — nggak nyentuh state React sama sekali, jadi gampang
 * dites, dan aman dipanggil berkali-kali beruntun (idempotent): manggil
 * ini 2x dengan input yang sama persis bakal ngasih hasil yang sama.
 */
export function reconcilePendingArray(prevArray, freshPendingRecords) {
  const freshIds = new Set(freshPendingRecords.map((r) => r.id));
  const withoutStalePending = prevArray.filter((item) => !item._offlineQueued || freshIds.has(item.id));
  const existingIds = new Set(withoutStalePending.map((item) => item.id));
  const toAdd = freshPendingRecords.filter((r) => !existingIds.has(r.id));
  return [...toAdd, ...withoutStalePending];
}

/** Buang record duplikat (id sama) dari 1 array hasil mapping — jaring pengaman, seharusnya jarang kepake karena id antrian IndexedDB unik. */
export function dedupeByQueueIdentity(records) {
  const seen = new Set();
  const result = [];
  for (const record of records) {
    if (!record || seen.has(record.id)) continue;
    seen.add(record.id);
    result.push(record);
  }
  return result;
}
