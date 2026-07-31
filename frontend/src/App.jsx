import { useEffect, useState } from "react";
import { AuthProvider, useAuth } from "./context/AuthContext";
import { api } from "./api/client";
import AuthScreen from "./pages/AuthScreen";
import OnboardingWizard from "./pages/OnboardingWizard";
import Dashboard from "./pages/Dashboard";
import GrowthScreen from "./pages/GrowthScreen";
import HealthScreen from "./pages/HealthScreen";
import MomentsScreen from "./pages/MomentsScreen";
import StatsScreen from "./pages/StatsScreen";
import ChildProfileScreen from "./pages/ChildProfileScreen";
import UserProfileScreen from "./pages/UserProfileScreen";
import CaregiverModal from "./components/CaregiverModal";

function AppContent() {
  const { user, loading, logout, setUser } = useAuth();
  const [children, setChildren] = useState([]);
  const [activeChild, setActiveChild] = useState(null);
  const [loadingChildren, setLoadingChildren] = useState(true);
  const [activeView, setActiveView] = useState("daily");
  const [showCaregivers, setShowCaregivers] = useState(false);
  const [showMenu, setShowMenu] = useState(false);

  const NAV_ITEMS = [
    { key: "daily", label: "Harian", icon: "🍼" },
    { key: "growth", label: "Tumbuh Kembang", icon: "📈" },
    { key: "health", label: "Kesehatan", icon: "🩺" },
    { key: "moments", label: "Momen", icon: "✨" },
    { key: "stats", label: "Statistik", icon: "📊" },
  ];

  const EXTRA_LABELS = {
    childProfile: "Profil Anak",
    userProfile: "Profil Saya",
  };

  useEffect(() => {
    if (!user) {
      setLoadingChildren(false);
      return;
    }
    api
      .listChildren()
      .then((list) => {
        setChildren(list);
        setActiveChild(list[0] || null);
      })
      .finally(() => setLoadingChildren(false));
  }, [user]);

  if (loading || loadingChildren) {
    return (
      <div className="flex items-center justify-center min-h-screen">
        <p className="font-mono text-sm text-ink-faint">Memuat...</p>
      </div>
    );
  }

  if (!user) return <AuthScreen />;

  if (!activeChild) {
    return (
      <OnboardingWizard
        onComplete={(child) => {
          setChildren([child]);
          setActiveChild(child);
        }}
      />
    );
  }

  const activeLabel = NAV_ITEMS.find((n) => n.key === activeView)?.label || EXTRA_LABELS[activeView] || "";

  const handleChildUpdated = (updatedChild) => {
    setActiveChild(updatedChild);
    setChildren((prev) => prev.map((c) => (c.id === updatedChild.id ? updatedChild : c)));
  };

  return (
    <div>
      <div className="flex items-center justify-between gap-2 px-6 pt-4">
        {children.length > 1 ? (
          <div className="flex gap-2 overflow-x-auto">
            {children.map((c) => (
              <button
                key={c.id}
                onClick={() => setActiveChild(c)}
                className={`px-3 py-1.5 rounded-full text-xs font-medium border whitespace-nowrap flex-shrink-0 ${
                  c.id === activeChild.id
                    ? "bg-feed/20 border-feed text-feed"
                    : "border-void-hairline text-ink-muted"
                }`}
              >
                {c.nickname || c.name}
              </button>
            ))}
          </div>
        ) : (
          <p className="text-sm font-medium truncate text-ink">{activeChild.nickname || activeChild.name}</p>
        )}

        <button
          onClick={() => setShowMenu(true)}
          className="flex items-center gap-1.5 bg-void-card border border-void-hairline rounded-full pl-3 pr-2 py-1.5 flex-shrink-0"
        >
          <span className="text-xs text-ink-muted whitespace-nowrap">{activeLabel}</span>
          <span className="text-sm text-ink-muted">☰</span>
        </button>
      </div>

      {activeView === "daily" && (
        <Dashboard child={activeChild} onOpenProfile={() => setActiveView("childProfile")} />
      )}
      {activeView === "growth" && <GrowthScreen child={activeChild} />}
      {activeView === "health" && <HealthScreen child={activeChild} />}
      {activeView === "moments" && <MomentsScreen child={activeChild} />}
      {activeView === "stats" && <StatsScreen child={activeChild} />}
      {activeView === "childProfile" && (
        <ChildProfileScreen child={activeChild} currentUserId={user.id} onUpdated={handleChildUpdated} />
      )}
      {activeView === "userProfile" && <UserProfileScreen user={user} onUserUpdated={setUser} />}

      {showMenu && (
        <div className="fixed inset-0 z-50 flex items-start justify-end sm:items-center sm:justify-center">
          <div className="absolute inset-0 bg-black/50" onClick={() => setShowMenu(false)} />
          <div className="relative w-full p-4 pb-6 border-b sm:max-w-xs bg-void-card sm:border border-void-hairline rounded-b-xl2 sm:rounded-xl2">
            <p className="text-[11px] text-ink-faint uppercase tracking-wider font-mono px-2 pt-1 pb-2">
              Menu
            </p>
            <div className="mb-3 space-y-1">
              {NAV_ITEMS.map((item) => (
                <button
                  key={item.key}
                  onClick={() => {
                    setActiveView(item.key);
                    setShowMenu(false);
                  }}
                  className={`w-full flex items-center gap-3 px-3 py-2.5 rounded-xl2 text-sm text-left ${
                    activeView === item.key ? "bg-feed/15 text-feed font-medium" : "text-ink"
                  }`}
                >
                  <span className="text-base">{item.icon}</span>
                  {item.label}
                </button>
              ))}
            </div>
            <div className="pt-3 space-y-1 border-t border-void-hairline">
              <button
                onClick={() => {
                  setActiveView("childProfile");
                  setShowMenu(false);
                }}
                className={`w-full flex items-center gap-3 px-3 py-2.5 rounded-xl2 text-sm text-left ${
                  activeView === "childProfile" ? "bg-feed/15 text-feed font-medium" : "text-ink"
                }`}
              >
                <span className="text-base">👶</span>
                Profil Anak
              </button>
              <button
                onClick={() => {
                  setActiveView("userProfile");
                  setShowMenu(false);
                }}
                className={`w-full flex items-center gap-3 px-3 py-2.5 rounded-xl2 text-sm text-left ${
                  activeView === "userProfile" ? "bg-feed/15 text-feed font-medium" : "text-ink"
                }`}
              >
                <span className="text-base">👤</span>
                Profil Saya
              </button>
              <button
                onClick={() => {
                  setShowMenu(false);
                  setShowCaregivers(true);
                }}
                className="w-full flex items-center gap-3 px-3 py-2.5 rounded-xl2 text-sm text-ink text-left"
              >
                <span className="text-base">👥</span>
                Pengasuh
              </button>
              <button
                onClick={logout}
                className="w-full flex items-center gap-3 px-3 py-2.5 rounded-xl2 text-sm text-warn text-left"
              >
                <span className="text-base">🚪</span>
                Keluar
              </button>
            </div>
          </div>
        </div>
      )}

      {showCaregivers && (
        <CaregiverModal
          child={activeChild}
          currentUserId={user.id}
          onClose={() => setShowCaregivers(false)}
        />
      )}
    </div>
  );
}

export default function App() {
  return (
    <AuthProvider>
      <AppContent />
    </AuthProvider>
  );
}