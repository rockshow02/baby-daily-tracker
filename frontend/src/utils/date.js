/**
 * "Hari ini" versi WIB (Asia/Jakarta), TIDAK bergantung timezone device/browser.
 *
 * Kenapa nggak boleh pakai `new Date().toISOString().split("T")[0]`:
 * toISOString() SELALU UTC. WIB itu UTC+7, jadi pas jam 00:00-06:59 WIB,
 * waktu UTC-nya masih tanggal KEMARIN — bikin app salah nunjuk "hari ini"
 * di jam-jam dini hari (baru bener lagi jam 07:00 WIB, pas UTC ganti tanggal).
 */
export function todayWIB() {
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Jakarta",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).formatToParts(new Date());
  const map = {};
  parts.forEach((p) => (map[p.type] = p.value));
  return `${map.year}-${map.month}-${map.day}`;
}

/** Versi todayWIB() tapi buat tanggal apapun (bukan cuma "sekarang"), dalam timezone WIB. */
export function toWIBDateStr(date) {
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Jakarta",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).formatToParts(date);
  const map = {};
  parts.forEach((p) => (map[p.type] = p.value));
  return `${map.year}-${map.month}-${map.day}`;
}

/** Ambil jam (0-23) dalam WIB dari sebuah timestamp, TIDAK bergantung timezone device. */
export function getWIBHour(dateStr) {
  const parts = new Intl.DateTimeFormat("en-GB", {
    timeZone: "Asia/Jakarta",
    hour: "2-digit",
    hour12: false,
  }).formatToParts(new Date(dateStr));
  return Number(parts.find((p) => p.type === "hour").value);
}

/** Label periode waktu (Pagi/Siang/Sore/Malam) buat pengelompokan riwayat. */
export function timePeriodLabel(dateStr) {
  const h = getWIBHour(dateStr);
  if (h >= 4 && h < 11) return "🌅 Pagi";
  if (h >= 11 && h < 15) return "☀️ Siang";
  if (h >= 15 && h < 18) return "🌇 Sore";
  return "🌙 Malam";
}
