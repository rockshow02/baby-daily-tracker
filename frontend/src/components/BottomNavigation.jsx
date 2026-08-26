const ITEMS = [
  {
    key: "daily",
    label: "Beranda",
    icon: (
      <path d="M3.5 10.8 12 3.9l8.5 6.9v9.1a1.6 1.6 0 0 1-1.6 1.6H5.1a1.6 1.6 0 0 1-1.6-1.6v-9.1ZM9 21.5v-7h6v7" />
    ),
  },
  {
    key: "stats",
    label: "Statistik",
    icon: <path d="M5 20V10m7 10V4m7 16v-7" />,
  },
  {
    key: "moments",
    label: "Momen",
    icon: (
      <>
        <rect x="3" y="4" width="18" height="16" rx="3" />
        <path d="m6.5 17 4.1-4.2 2.8 2.7 2.4-2.5 2.7 4M8.5 9h.01" />
      </>
    ),
  },
  {
    key: "userProfile",
    label: "Profil",
    icon: (
      <>
        <circle cx="12" cy="8" r="3.5" />
        <path d="M4.8 21c.5-4 3.2-6.2 7.2-6.2s6.7 2.2 7.2 6.2" />
      </>
    ),
  },
];

export default function BottomNavigation({ activeView, onNavigate }) {
  return (
    <nav
      aria-label="Navigasi utama"
      className="fixed inset-x-0 bottom-0 z-40 mx-auto w-full max-w-[42rem] border-t border-void-hairline bg-white/95 px-5 pt-2 shadow-nav backdrop-blur safe-bottom"
    >
      <div className="grid grid-cols-4 gap-1">
        {ITEMS.map((item) => {
          const active = activeView === item.key;
          return (
            <button
              key={item.key}
              type="button"
              aria-current={active ? "page" : undefined}
              onClick={() => onNavigate(item.key)}
              className={`flex min-h-14 flex-col items-center justify-center gap-1 rounded-2xl text-[11px] font-semibold transition-colors ${
                active ? "text-feed" : "text-ink-muted hover:text-ink"
              }`}
            >
              <svg
                viewBox="0 0 24 24"
                aria-hidden="true"
                className="h-5 w-5"
                fill={active && item.key === "daily" ? "currentColor" : "none"}
                stroke="currentColor"
                strokeWidth="1.8"
                strokeLinecap="round"
                strokeLinejoin="round"
              >
                {item.icon}
              </svg>
              <span>{item.label}</span>
            </button>
          );
        })}
      </div>
    </nav>
  );
}
