const STATUS_STYLE = {
  kurang: { dot: "bg-warn", label: "Kurang" },
  normal: { dot: "bg-diaper", label: "Normal" },
  lebih: { dot: "bg-feed", label: "Lebih" },
};

export default function StatusPill({ icon, title, actual, unit, range, status, note }) {
  const style = status ? STATUS_STYLE[status] : null;

  return (
    <div className="bg-void-card border border-void-hairline rounded-xl2 p-4 flex-1 min-w-[140px]">
      <div className="flex items-center justify-between mb-2">
        <span className="text-xl">{icon}</span>
        {style && (
          <span className="flex items-center gap-1.5 text-xs font-mono text-ink-muted">
            <span className={`w-1.5 h-1.5 rounded-full ${style.dot}`} />
            {style.label}
          </span>
        )}
      </div>
      <p className="font-display text-2xl text-ink leading-none">
        {actual}
        <span className="text-sm text-ink-muted ml-1">{unit}</span>
      </p>
      <p className="text-xs text-ink-faint mt-1">{title}</p>
      {range && <p className="text-[11px] text-ink-faint font-mono mt-2">acuan: {range}</p>}
      {note && <p className="text-[11px] text-ink-faint mt-1 leading-snug">{note}</p>}
    </div>
  );
}
