import { formatOccurrenceDateTime } from "../utils/reminders";

/**
 * Ringkasan pengingat RINGKAS di Dashboard — SENGAJA cuma angka +
 * 1 baris teks, TIDAK PERNAH daftar penuh (itu tugas ReminderScreen.jsx)
 * biar dashboard nggak penuh sesak. Data-nya dari useReminderMonitor
 * (dipasang sekali di App.jsx, di-polling berkala) — komponen ini
 * MURNI presentasional, TIDAK PERNAH fetch sendiri.
 */
export default function DashboardReminderSummary({ status, summary, onOpen }) {
  // Loading pertama kali / gagal total / offline tanpa cache -- jangan
  // taruh apa pun di dashboard, biar nggak "kedip"/ganggu alur utama.
  if (status === "loading" || status === "error" || status === "offline_no_cache") return null;
  if (!summary) return null;

  const dueCount = summary.due_count || 0;
  const overdueCount = summary.overdue_count || 0;
  const nextAt = summary.next_upcoming_at;

  if (dueCount === 0 && overdueCount === 0 && !nextAt) return null;

  return (
    <button
      type="button"
      onClick={onOpen}
      className="w-full text-left bg-void-card border border-void-hairline rounded-xl2 px-4 py-3 mb-4 flex items-center justify-between gap-2"
    >
      <div className="min-w-0">
        <p className="text-[11px] text-ink-faint font-mono uppercase tracking-wider mb-1">🔔 Pengingat</p>
        <div className="flex flex-wrap gap-x-3 gap-y-0.5 text-sm">
          {overdueCount > 0 && <span className="text-warn font-semibold">{overdueCount} terlambat</span>}
          {dueCount > 0 && <span className="text-feed font-semibold">{dueCount} jatuh tempo</span>}
          {overdueCount === 0 && dueCount === 0 && nextAt && (
            <span className="text-ink-muted">Berikutnya {formatOccurrenceDateTime(nextAt)}</span>
          )}
        </div>
      </div>
      <span className="text-ink-faint text-sm flex-shrink-0">→</span>
    </button>
  );
}
