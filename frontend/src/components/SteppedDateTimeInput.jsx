const MINUTE_OPTIONS = Array.from({ length: 12 }, (_, i) => String(i * 5).padStart(2, "0"));
const HOUR_OPTIONS = Array.from({ length: 24 }, (_, i) => String(i).padStart(2, "0"));

/**
 * Pengganti <input type="datetime-local"> biasa — dipisah jadi 3 kontrol
 * (tanggal, jam, menit) biar menitnya DIJAMIN kelipatan 5 di semua browser.
 * Atribut `step` di datetime-local bawaan browser ternyata nggak konsisten
 * (di beberapa browser tetap nampilin semua menit 00-59 walau step diisi).
 *
 * value & onChange formatnya sama kayak input datetime-local biasa:
 * string "YYYY-MM-DDTHH:MM", biar gampang gantiinnya di tempat lain.
 */
export default function SteppedDateTimeInput({ value, onChange, max, className }) {
  const [datePart, timePart] = (value || "").split("T");
  const [hourPart, minutePart] = (timePart || "00:00").split(":");

  // kalau menit yang lagi kesimpen bukan kelipatan 5 (data lama/import),
  // bulatkan ke kelipatan 5 terdekat biar dropdown-nya tetap valid milih sesuatu
  const roundedMinute = String(Math.round(Number(minutePart || 0) / 5) * 5).padStart(2, "0");
  const safeMinute = roundedMinute === "60" ? "55" : roundedMinute;

  const [maxDatePart, maxTimePart] = (max || "").split("T");
  const [maxHourPart, maxMinutePart] = (maxTimePart || "23:55").split(":");
  const isMaxDate = !!max && datePart === maxDatePart;
  // menit maksimum juga dibulatin ke bawah ke kelipatan 5, biar pilihan
  // yang di atas "sekarang" nggak muncul di dropdown sama sekali
  const maxMinuteRounded = Math.floor(Number(maxMinutePart || 0) / 5) * 5;

  const emit = (d, h, m) => {
    if (!d) {
      onChange("");
      return;
    }
    // kalau tanggal yang dipilih = tanggal max (hari ini) dan jam/menit
    // hasil pilihan itu udah lewat batas max, "tarik mundur" otomatis ke
    // batas max-nya — biar nggak mungkin kesimpen waktu di masa depan
    if (max && d === maxDatePart) {
      if (h > maxHourPart) h = maxHourPart;
      if (h === maxHourPart && Number(m) > maxMinuteRounded) {
        m = String(maxMinuteRounded).padStart(2, "0");
      }
    }
    onChange(`${d}T${h}:${m}`);
  };

  const maxDate = max ? max.split("T")[0] : undefined;
  const availableHours = isMaxDate ? HOUR_OPTIONS.filter((h) => h <= maxHourPart) : HOUR_OPTIONS;
  const availableMinutes =
    isMaxDate && hourPart === maxHourPart
      ? MINUTE_OPTIONS.filter((m) => Number(m) <= maxMinuteRounded)
      : MINUTE_OPTIONS;

  return (
    <div className={`flex gap-2 ${className || ""}`}>
      <input
        type="date"
        value={datePart || ""}
        max={maxDate}
        onChange={(e) => emit(e.target.value, hourPart || "00", safeMinute)}
        className="flex-1 bg-void border border-void-hairline rounded-lg px-3 py-2.5 text-ink font-mono text-sm"
      />
      <select
        value={hourPart || "00"}
        onChange={(e) => emit(datePart, e.target.value, safeMinute)}
        className="bg-void border border-void-hairline rounded-lg px-2 py-2.5 text-ink font-mono text-sm"
      >
        {availableHours.map((h) => (
          <option key={h} value={h}>
            {h}
          </option>
        ))}
      </select>
      <span className="self-center text-ink-faint">:</span>
      <select
        value={safeMinute}
        onChange={(e) => emit(datePart, hourPart || "00", e.target.value)}
        className="bg-void border border-void-hairline rounded-lg px-2 py-2.5 text-ink font-mono text-sm"
      >
        {availableMinutes.map((m) => (
          <option key={m} value={m}>
            {m}
          </option>
        ))}
      </select>
    </div>
  );
}