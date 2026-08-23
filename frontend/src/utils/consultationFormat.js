/**
 * Formatter Bahasa Indonesia buat pratinjau Laporan Konsultasi
 * (`ConsultationPreview` dkk) — SATU sumber dipakai semua renderer
 * section, biar penulisan angka/tanggal/durasi konsisten di seluruh
 * laporan (dan konsisten sama PDF server-side, walaupun CSS-nya beda).
 *
 * Tanggal/waktu di sini SELALU eksplisit `timeZone: "Asia/Jakarta"` ke
 * `Intl.DateTimeFormat` — TIDAK PERNAH mengandalkan timezone lokal
 * browser yang bisa beda-beda per device, yang bisa menggeser tanggal
 * WIB yang sudah benar dari backend jadi hari yang salah.
 */

export const MISSING_VALUE = "—";

const MONTHS_SHORT_ID = [
  "Jan", "Feb", "Mar", "Apr", "Mei", "Jun",
  "Jul", "Agu", "Sep", "Okt", "Nov", "Des",
];

/**
 * "YYYY-MM-DD" (tanggal MURNI, tanpa jam/offset -- persis apa yang
 * dikirim backend buat measured_date/visit_date/achieved_date/dst,
 * lihat backend/utils/consultation_report.py) -> "23 Agu 2026".
 *
 * SENGAJA parsing string manual (bukan `new Date("YYYY-MM-DD")`,
 * yang ditafsirkan JS sebagai TENGAH MALAM UTC lalu bisa mundur/maju
 * 1 hari kalau di-render ulang pakai timezone lokal browser) -- tanggal
 * murni nggak butuh konversi timezone SAMA SEKALI, cuma butuh
 * diformat ulang apa adanya.
 */
export function formatDateWIB(dateStr) {
  if (!dateStr || typeof dateStr !== "string") return MISSING_VALUE;
  const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(dateStr);
  if (!match) return MISSING_VALUE;
  const [, year, month, day] = match;
  const monthIndex = Number(month) - 1;
  if (monthIndex < 0 || monthIndex > 11) return MISSING_VALUE;
  return `${Number(day)} ${MONTHS_SHORT_ID[monthIndex]} ${year}`;
}

/**
 * ISO datetime LENGKAP dengan offset (mis. "2026-08-23T08:30:00+07:00",
 * format standar seluruh timestamp di response ini) ->
 * "23 Agu 2026, 08.30 WIB". `Intl.DateTimeFormat` dengan
 * `timeZone: "Asia/Jakarta"` EKSPLISIT -- hasilnya SELALU jam dinding
 * WIB yang benar, terlepas timezone device pembacanya.
 */
export function formatDateTimeWIB(iso) {
  if (!iso || typeof iso !== "string") return MISSING_VALUE;
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return MISSING_VALUE;
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Jakarta",
    day: "numeric",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).formatToParts(date);
  const map = {};
  parts.forEach((p) => { map[p.type] = p.value; });
  // `month: "2-digit"` (numerik) dipetakan lewat tabel 3-huruf yang
  // SAMA PERSIS dipakai `formatDateWIB` di atas, biar tanggal murni dan
  // tanggal+jam SELALU konsisten gayanya di seluruh laporan ini.
  const monthShort = MONTHS_SHORT_ID[Number(map.month) - 1] || map.month;
  return `${Number(map.day)} ${monthShort} ${map.year}, ${map.hour}.${map.minute} WIB`;
}

/** Bilangan bulat Indonesia (pemisah ribuan titik) -- "1.234". */
export function formatInt(value) {
  if (value === null || value === undefined || Number.isNaN(value)) return MISSING_VALUE;
  return new Intl.NumberFormat("id-ID", { maximumFractionDigits: 0 }).format(value);
}

/** Desimal Indonesia (koma) dibulatkan `decimals` angka -- formatDecimal(5.2, 1) -> "5,2". */
export function formatDecimal(value, decimals = 1) {
  if (value === null || value === undefined || Number.isNaN(value)) return MISSING_VALUE;
  return new Intl.NumberFormat("id-ID", {
    minimumFractionDigits: decimals, maximumFractionDigits: decimals,
  }).format(value);
}

export function formatVolumeMl(value) {
  if (value === null || value === undefined) return MISSING_VALUE;
  return `${formatInt(value)} ml`;
}

export function formatWeightKg(value) {
  if (value === null || value === undefined) return MISSING_VALUE;
  return `${formatDecimal(value, 1)} kg`;
}

export function formatLengthCm(value) {
  if (value === null || value === undefined) return MISSING_VALUE;
  return `${formatDecimal(value, 1)} cm`;
}

export function formatTemperatureC(value) {
  if (value === null || value === undefined) return MISSING_VALUE;
  return `${formatDecimal(value, 1)}°C`;
}

/** "8 kali" -- invariant, nggak perlu logika pluralisasi (Bahasa Indonesia nggak butuh). */
export function formatTimes(value) {
  if (value === null || value === undefined) return MISSING_VALUE;
  return `${formatInt(value)} kali`;
}

/** "1,4 kali/hari". */
export function formatRatePerDay(value) {
  if (value === null || value === undefined) return MISSING_VALUE;
  return `${formatDecimal(value, 1)} kali/hari`;
}

/** "0 catatan" / "3 catatan" -- invariant, dipakai count generik (bukan "kali" per-kejadian). */
export function formatRecordCount(value) {
  if (value === null || value === undefined) return MISSING_VALUE;
  return `${formatInt(value)} catatan`;
}

/**
 * Menit -> "45 menit" / "1 jam 30 menit" / "8 jam" / "0 menit" (kalau
 * beneran nol, BUKAN kosong) / "—" kalau nilainya nggak ada sama sekali
 * (null/undefined, beda dari nol).
 */
export function formatDurationMinutes(totalMinutes) {
  if (totalMinutes === null || totalMinutes === undefined || Number.isNaN(totalMinutes)) return MISSING_VALUE;
  const rounded = Math.round(totalMinutes);
  if (rounded <= 0) return "0 menit";
  const hours = Math.floor(rounded / 60);
  const minutes = rounded % 60;
  if (hours === 0) return `${minutes} menit`;
  if (minutes === 0) return `${hours} jam`;
  return `${hours} jam ${minutes} menit`;
}

/** Fallback seragam buat nilai apa pun yang nggak ada -- dipakai renderer buat teks bebas/label. */
export function orDash(value) {
  if (value === null || value === undefined || value === "") return MISSING_VALUE;
  return value;
}
