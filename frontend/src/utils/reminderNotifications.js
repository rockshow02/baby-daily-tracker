/**
 * Notifikasi browser BEST-EFFORT buat Care Reminders & Schedules Phase 1
 * — CUMA jalan selagi tab aplikasi ini terbuka di device itu, TIDAK ADA
 * jaminan latar belakang (batasan PythonAnywhere Free — nggak ada push
 * service server-side — DAN batasan browser umum, lihat
 * backend/docs/REMINDERS.md). Modul ini SENGAJA nggak pernah "berpura-
 * pura" dukungan latar belakang (mis. Service Worker push) — kalau
 * `Notification` API nggak didukung/izin ditolak, fitur ini cuma nggak
 * nyala, TANPA fallback palsu.
 */

const NOTIFIED_OCCURRENCES_PREFIX = "babytracker_notified_occurrences_v1:";
const OPT_IN_PREFIX = "babytracker_notifications_enabled_v1:";
// Batas jumlah occurrence_key yang disimpan per (user, anak) — cegah
// entry localStorage ini numpuk nggak terbatas buat reminder harian
// yang udah aktif lama; entry TERLAMA yang dibuang duluan begitu
// kepenuhan (FIFO), bukan hal yang perlu diingat selamanya.
const MAX_TRACKED_OCCURRENCES = 200;

const REMINDER_TYPE_LABELS = {
  medication: "obat",
  doctor_visit: "kunjungan dokter",
  vaccination: "vaksinasi",
  pumping: "perah ASI",
  general: "perawatan",
};

export function isNotificationSupported() {
  return typeof window !== "undefined" && typeof window.Notification !== "undefined";
}

/** "unsupported" | "default" | "granted" | "denied" */
export function getNotificationPermission() {
  if (!isNotificationSupported()) return "unsupported";
  return window.Notification.permission;
}

/**
 * WAJIB cuma dipanggil dari handler klik tombol EKSPLISIT (lihat
 * ReminderScreen.jsx) — TIDAK PERNAH otomatis saat halaman dimuat,
 * browser modern bakal nolak/nge-log warning kalau dipanggil di luar
 * gesture pengguna, dan requirement produk juga eksplisit melarangnya.
 */
export async function requestNotificationPermission() {
  if (!isNotificationSupported()) return "unsupported";
  try {
    return await window.Notification.requestPermission();
  } catch (_) {
    return "denied";
  }
}

function optInKey(userId) {
  return `${OPT_IN_PREFIX}${userId}`;
}

export function isNotificationOptedIn(userId) {
  if (userId == null) return false;
  try {
    return localStorage.getItem(optInKey(userId)) === "1";
  } catch (_) {
    return false;
  }
}

export function setNotificationOptedIn(userId, enabled) {
  if (userId == null) return;
  try {
    if (enabled) localStorage.setItem(optInKey(userId), "1");
    else localStorage.removeItem(optInKey(userId));
  } catch (_) {
    // storage nggak kebuka — preferensi nggak ke-simpen, nggak fatal
  }
}

function notifiedKey(userId, childId) {
  return `${NOTIFIED_OCCURRENCES_PREFIX}${userId}:${childId}`;
}

function occurrenceNotifyId(reminderId, occurrenceKey) {
  return `${reminderId}:${occurrenceKey}`;
}

function readNotifiedList(userId, childId) {
  try {
    const raw = localStorage.getItem(notifiedKey(userId, childId));
    const arr = raw ? JSON.parse(raw) : [];
    return Array.isArray(arr) ? arr : [];
  } catch (_) {
    return [];
  }
}

/** True kalau occurrence ini SUDAH pernah memicu notifikasi di browser ini sebelumnya — cegah notifikasi dobel. */
export function hasNotifiedOccurrence(userId, childId, reminderId, occurrenceKey) {
  if (userId == null || childId == null) return false;
  return readNotifiedList(userId, childId).includes(occurrenceNotifyId(reminderId, occurrenceKey));
}

function markNotified(userId, childId, reminderId, occurrenceKey) {
  try {
    const list = readNotifiedList(userId, childId);
    const id = occurrenceNotifyId(reminderId, occurrenceKey);
    if (list.includes(id)) return;
    list.push(id);
    const bounded = list.slice(-MAX_TRACKED_OCCURRENCES);
    localStorage.setItem(notifiedKey(userId, childId), JSON.stringify(bounded));
  } catch (_) {
    // nggak kesimpen -- risiko PALING BURUK cuma notifikasi dobel sesekali, bukan crash
  }
}

/** Dipanggil pas logout — bersihin jejak deduplikasi + preferensi opt-in, konsisten sama cache lain per-user. */
export function clearNotificationStateForUser(userId) {
  if (userId == null) return;
  try {
    const prefix = `${NOTIFIED_OCCURRENCES_PREFIX}${userId}:`;
    const keysToRemove = [optInKey(userId)];
    for (let i = 0; i < localStorage.length; i++) {
      const key = localStorage.key(i);
      if (key && key.startsWith(prefix)) keysToRemove.push(key);
    }
    keysToRemove.forEach((k) => localStorage.removeItem(k));
  } catch (_) {
    // storage nggak kebuka — nggak ada yang perlu dibersihkan
  }
}

/**
 * Teks notifikasi GENERIK per `reminder_type` — TIDAK PERNAH `title`
 * reminder aslinya (bisa berisi nama obat/rincian medis yang caregiver
 * ketik sendiri, lihat models.py:Reminder docstring backend).
 */
function genericNotificationText(childName, reminderType) {
  const label = REMINDER_TYPE_LABELS[reminderType] || REMINDER_TYPE_LABELS.general;
  if (childName) return `Pengingat ${label} untuk ${childName} sudah waktunya diperiksa.`;
  return "Ada pengingat perawatan yang jatuh tempo.";
}

/**
 * Tampilkan 1 notifikasi browser buat 1 occurrence due/overdue — CUMA
 * kalau didukung + izin granted + user memang opt-in + occurrence ini
 * BELUM pernah dinotifikasi di browser ini. `tag` di opsi Notification
 * jadi lapis deduplikasi KEDUA di level browser (notifikasi baru dengan
 * tag yang sama menggantikan yang lama, bukan numpuk) — di ATAS
 * deduplikasi localStorage kita sendiri, bukan pengganti.
 *
 * Balikin `true` kalau notifikasi beneran ditampilkan, `false` kalau
 * tidak (alasan apa pun) — TIDAK PERNAH throw.
 */
export function notifyDueOccurrence({ userId, childId, childName, reminder, occurrence, onClickNavigate }) {
  if (!isNotificationSupported()) return false;
  if (window.Notification.permission !== "granted") return false;
  if (!isNotificationOptedIn(userId)) return false;
  if (!reminder || !occurrence) return false;
  if (hasNotifiedOccurrence(userId, childId, reminder.id, occurrence.occurrence_key)) return false;

  try {
    const notif = new window.Notification("Baby Daily Tracker", {
      body: genericNotificationText(childName, reminder.reminder_type),
      tag: `reminder-${reminder.id}-${occurrence.occurrence_key}`,
    });
    notif.onclick = () => {
      try {
        window.focus();
      } catch (_) {
        // beberapa browser/context nggak ngizinin window.focus() -- nggak fatal
      }
      if (typeof onClickNavigate === "function") onClickNavigate();
      notif.close();
    };
  } catch (_) {
    // konstruksi Notification() bisa gagal (mis. dipanggil di worker/context
    // yang nggak didukung) -- gagal diam-diam, TIDAK PERNAH ditandai "sudah dinotif"
    return false;
  }

  markNotified(userId, childId, reminder.id, occurrence.occurrence_key);
  return true;
}
