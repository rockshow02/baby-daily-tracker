import { useCallback, useEffect, useState } from "react";
import { AuthProvider, useAuth } from "./context/AuthContext";
import { api, ApiError, getCurrentUserId } from "./api/client";
import { isOwner } from "./utils/roles";
import { getQueueForUser, QUEUE_STATUS } from "./utils/offlineQueue";
import { useOfflineSync } from "./hooks/useOfflineSync";
import {
  cacheChildren,
  getCachedChildren,
  getCachedActiveChildId,
  setCachedActiveChildId,
} from "./utils/sessionCache";
import { pruneInsightCacheToAccessibleChildren } from "./utils/insightCache";
import { pruneReminderCacheToAccessibleChildren } from "./utils/reminderCache";
import { pruneMedicationScheduleCacheToAccessibleChildren } from "./utils/medicationScheduleCache";
import { useReminderMonitor } from "./hooks/useReminderMonitor";
import AuthScreen from "./pages/AuthScreen";
import OnboardingWizard from "./pages/OnboardingWizard";
import Dashboard from "./pages/Dashboard";
import GrowthScreen from "./pages/GrowthScreen";
import HealthScreen from "./pages/HealthScreen";
import MomentsScreen from "./pages/MomentsScreen";
import StatsScreen from "./pages/StatsScreen";
import InsightsScreen from "./pages/InsightsScreen";
import ReminderScreen from "./pages/ReminderScreen";
import ChildProfileScreen from "./pages/ChildProfileScreen";
import UserProfileScreen from "./pages/UserProfileScreen";
import PrivacyDataScreen from "./pages/PrivacyDataScreen";
import CaregiverModal from "./components/CaregiverModal";
import OfflineStatusBanner from "./components/OfflineStatusBanner";
import SyncCenter from "./components/SyncCenter";
import AuditTrailScreen from "./components/AuditTrailScreen";
import BottomNavigation from "./components/BottomNavigation";

const NAV_ITEMS = [
  { key: "daily", label: "Harian", icon: "🍼" },
  { key: "growth", label: "Tumbuh Kembang", icon: "📈" },
  { key: "health", label: "Kesehatan", icon: "🩺" },
  { key: "moments", label: "Momen", icon: "✨" },
  { key: "stats", label: "Statistik", icon: "📊" },
  { key: "insights", label: "Insight", icon: "✨" },
  { key: "reminders", label: "Pengingat", icon: "🔔" },
];

const EXTRA_LABELS = {
  childProfile: "Profil Anak",
  userProfile: "Profil Saya",
  privacy: "Privasi & Data",
};

function AppContent() {
  const { user, loading, logout, setUser } = useAuth();
  const [children, setChildren] = useState([]);
  const [activeChild, setActiveChild] = useState(null);
  const [loadingChildren, setLoadingChildren] = useState(true);
  // null (berhasil dimuat online, termasuk kalau beneran kosong) |
  // "offline_cached" (gagal muat, tapi ada cache offline yang dipakai) |
  // "offline_no_cache" (gagal muat, DAN nggak ada cache sama sekali)
  const [childLoadError, setChildLoadError] = useState(null);
  const [showEmptyPrivacy, setShowEmptyPrivacy] = useState(false);

  /**
   * Muat daftar anak. Bedain 4 kemungkinan hasil secara eksplisit:
   * - sukses, ada isinya -> normal
   * - sukses, beneran kosong -> onboarding (ini SATU-SATUNYA jalur yang
   *   boleh nampilin OnboardingWizard, lihat requirement #4/#5)
   * - gagal karena 401 kekonfirmasi -> lewat alur logout() yang udah ada
   *   (bukan nebak-nebak nutup sesi manual di sini)
   * - gagal karena jaringan/error server lain (BUKAN 401) -> ini masalah
   *   MEMUAT data, bukan sesi invalid; jangan pernah nge-treat kayak 401
   *   (requirement #13) — coba restorasi dari cache offline user ini
   */
  const loadChildren = useCallback(async () => {
    if (!user) {
      setChildren([]);
      setActiveChild(null);
      setChildLoadError(null);
      setLoadingChildren(false);
      return;
    }
    setLoadingChildren(true);
    try {
      const list = await api.listChildren();
      setChildren(list);
      cacheChildren(user.id, list);
      // Revalidasi ONLINE yang berhasil = kesempatan buat mbuang snapshot
      // insight anak mana pun yang aksesnya udah dicabut (caregiver lain
      // ngeluarin kita, atau anaknya dihapus) — snapshot lama nggak boleh
      // nyangkut jadi "hantu" yang masih keliatan pas offline nanti.
      pruneInsightCacheToAccessibleChildren(user.id, list.map((c) => c.id));
      pruneReminderCacheToAccessibleChildren(user.id, list.map((c) => c.id));
      pruneMedicationScheduleCacheToAccessibleChildren(user.id, list.map((c) => c.id));
      const cachedActiveId = getCachedActiveChildId(user.id);
      const next = list.find((c) => c.id === cachedActiveId) || list[0] || null;
      setActiveChild(next);
      if (next) setCachedActiveChildId(user.id, next.id);
      setChildLoadError(null);
    } catch (err) {
      if (err instanceof ApiError && err.kind === "unauthorized") {
        await logout();
        return;
      }
      const cached = getCachedChildren(user.id);
      if (cached.length > 0) {
        setChildren(cached);
        const cachedActiveId = getCachedActiveChildId(user.id);
        setActiveChild(cached.find((c) => c.id === cachedActiveId) || cached[0]);
        setChildLoadError("offline_cached");
      } else {
        setChildren([]);
        setActiveChild(null);
        setChildLoadError("offline_no_cache");
      }
    } finally {
      setLoadingChildren(false);
    }
  }, [user, logout]);

  useEffect(() => {
    // tunggu AuthContext beres mutusin siapa user-nya duluan (baik itu
    // sukses/gagal/direstorasi dari cache) SEBELUM mulai muat daftar anak.
    // Tanpa guard ini, ada jendela render sesaat di mana `loading` (Auth)
    // masih true tapi effect ini SUDAH sempat jalan sekali dengan user
    // masih null (nge-set loadingChildren=false SEBELUM user yang
    // sebenarnya kesimpen) — begitu user beneran ke-set, ada 1 render
    // transisi dengan loading=false, loadingChildren=false (stale), TAPI
    // activeChild masih null (efek loadChildren belum sempat jalan ULANG),
    // yang keliru nampilin OnboardingWizard sekilas.
    if (loading) return;
    loadChildren();
  }, [loading, loadChildren]);

  // begitu koneksi balik, otomatis coba muat ulang daftar anak dari server
  // — jalur retry buat kasus "sempat gagal loadChildren() pas offline"
  useEffect(() => {
    const handleOnline = () => loadChildren();
    window.addEventListener("online", handleOnline);
    return () => window.removeEventListener("online", handleOnline);
  }, [loadChildren]);

  if (loading || loadingChildren) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <p className="text-ink-faint font-mono text-sm">Memuat...</p>
      </div>
    );
  }

  if (!user) return <AuthScreen />;

  if (!activeChild) {
    if (childLoadError === "offline_no_cache") {
      // gagal muat (offline/error server), DAN nggak ada cache anak sama
      // sekali buat direstorasi — belum pernah berhasil online sebelumnya
      // di perangkat ini. JANGAN nampilin OnboardingWizard (itu bakal
      // ngebiarin user "bikin anak baru" padahal mungkin udah punya di
      // server) — kasih fallback offline yang jelas + jalur retry.
      return (
        <div className="min-h-screen flex items-center justify-center px-6">
          <div className="text-center max-w-xs">
            <p className="text-3xl mb-3">📡</p>
            <p className="text-ink text-sm font-medium mb-1">Belum bisa dibuka offline</p>
            <p className="text-ink-faint text-xs mb-4">
              Perangkat ini belum pernah tersambung online buat memuat data anak. Sambungkan ke internet minimal
              sekali dulu supaya bisa dipakai offline setelahnya.
            </p>
            <button
              type="button"
              onClick={() => loadChildren()}
              className="text-xs font-semibold text-feed underline underline-offset-2"
            >
              Coba lagi
            </button>
          </div>
        </div>
      );
    }

    // sampai sini, activeChild null cuma mungkin kalau server BENERAN
    // ngonfirmasi daftar anaknya kosong (childLoadError === null) — bukan
    // gara-gara request gagal (requirement #4: jangan nampilin onboarding
    // cuma gara-gara request anak gagal)
    if (showEmptyPrivacy) {
      return (
        <PrivacyDataScreen
          onClose={() => setShowEmptyPrivacy(false)}
          onAccessChanged={async () => {
            await loadChildren();
          }}
          onAccountDeleted={logout}
        />
      );
    }

    return (
      <OnboardingWizard
        onOpenPrivacy={() => setShowEmptyPrivacy(true)}
        onComplete={(child) => {
          setChildren([child]);
          setActiveChild(child);
          cacheChildren(user.id, [child]);
          setCachedActiveChildId(user.id, child.id);
        }}
      />
    );
  }

  return (
    <AuthenticatedAppShell
      user={user}
      childrenList={children}
      setChildren={setChildren}
      activeChild={activeChild}
      setActiveChild={setActiveChild}
      setUser={setUser}
      logout={logout}
      reloadChildren={async () => {
        // Kalau aksi Privasi menghapus/mencabut akses anak terakhir,
        // pertahankan jalur ke layar Privasi agar user masih bisa
        // menghapus akun—jangan menjebaknya langsung di onboarding.
        setShowEmptyPrivacy(true);
        await loadChildren();
      }}
    />
  );
}

/**
 * Shell aplikasi buat user yang UDAH login DAN udah punya activeChild —
 * satu-satunya tempat `useOfflineSync()` dipanggil (lihat App.jsx
 * requirement observability: 1 controller sinkron otoritatif, bukan 1
 * instance per komponen yang butuh status sinkron). Mount/unmount-nya
 * ngikutin AppContent nampilin komponen ini atau nggak (login -> mount,
 * logout -> unmount balik ke AuthScreen) — PERSIS pola mount/unmount
 * OfflineStatusBanner yang lama, cuma sekarang hook-nya dipanggil DI
 * SINI (1 kali), lalu state/fungsinya diteruskan sebagai props ke
 * OfflineStatusBanner DAN SyncCenter — bukan dipanggil ulang sendiri-
 * sendiri sama masing-masing (yang bisa bikin 2 loop auto-sync balapan).
 */
function AuthenticatedAppShell({ user, childrenList, setChildren, activeChild, setActiveChild, setUser, logout, reloadChildren }) {
  const [activeView, setActiveView] = useState("daily");
  const [showCaregivers, setShowCaregivers] = useState(false);
  const [showMenu, setShowMenu] = useState(false);
  const [showSyncCenter, setShowSyncCenter] = useState(false);
  const [showAuditTrail, setShowAuditTrail] = useState(false);

  const sync = useOfflineSync();

  // Care Reminders & Schedules Phase 1 — SATU instance dipasang di sini
  // (persis pola useOfflineSync di atas), dipakai bareng buat ringkasan
  // Dashboard DAN notifikasi browser best-effort (lihat
  // hooks/useReminderMonitor.js) — bukan 2 polling terpisah yang bisa
  // balapan.
  const reminderMonitor = useReminderMonitor({
    child: activeChild,
    currentUserId: user.id,
    isOnline: sync.isOnline,
    onNavigateToReminders: () => setActiveView("reminders"),
  });

  const activeLabel = NAV_ITEMS.find((n) => n.key === activeView)?.label || EXTRA_LABELS[activeView] || "";

  const handleChildUpdated = (updatedChild) => {
    setActiveChild(updatedChild);
    setChildren((prev) => {
      const next = prev.map((c) => (c.id === updatedChild.id ? updatedChild : c));
      cacheChildren(user.id, next);
      return next;
    });
  };

  const handleLogout = async () => {
    try {
      const userId = getCurrentUserId();
      const pending = userId != null ? await getQueueForUser(userId) : [];
      const stillWaiting = pending.filter((i) => i.status !== QUEUE_STATUS.NEEDS_REVIEW).length;
      if (stillWaiting > 0) {
        const ok = window.confirm(
          `Masih ada ${stillWaiting} catatan yang belum tersinkron ke server. Catatan itu tetap tersimpan di HP ini dan akan otomatis disinkron kalau kamu login lagi sebagai akun ini. Tetap keluar?`,
        );
        if (!ok) return;
      }
    } catch (_) {
      // IndexedDB nggak kebuka — lanjut logout seperti biasa
    }
    logout();
  };

  return (
    <div className="min-h-screen pb-20">
      <OfflineStatusBanner sync={sync} onOpenDetail={() => setShowSyncCenter(true)} />
      {(activeView !== "daily" || childrenList.length > 1) && (
      <div className="app-page px-5 pt-4 flex items-center justify-between gap-2">
        {childrenList.length > 1 ? (
          <div className="flex gap-2 overflow-x-auto">
            {childrenList.map((c) => (
              <button
                key={c.id}
                onClick={() => {
                  setActiveChild(c);
                  setCachedActiveChildId(user.id, c.id);
                }}
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
          <p className="text-sm text-ink font-medium truncate">{activeChild.nickname || activeChild.name}</p>
        )}

        {activeView !== "daily" && <button
          onClick={() => setShowMenu(true)}
          className="flex items-center gap-1.5 bg-void-card border border-void-hairline rounded-full pl-3 pr-2 py-1.5 flex-shrink-0"
        >
          <span className="text-xs text-ink-muted whitespace-nowrap">{activeLabel}</span>
          <span className="text-ink-muted text-sm">☰</span>
        </button>
        }
      </div>
      )}

      <main className="app-page">
      {activeView === "daily" && (
        <Dashboard
          child={activeChild}
          onOpenProfile={() => setActiveView("childProfile")}
          reminderMonitor={reminderMonitor}
          onOpenReminders={() => setActiveView("reminders")}
          onOpenMenu={() => setShowMenu(true)}
        />
      )}
      {activeView === "growth" && <GrowthScreen child={activeChild} />}
      {activeView === "health" && <HealthScreen child={activeChild} currentUserId={user.id} />}
      {activeView === "moments" && <MomentsScreen child={activeChild} />}
      {activeView === "stats" && <StatsScreen child={activeChild} />}
      {activeView === "insights" && <InsightsScreen child={activeChild} currentUserId={user.id} />}
      {activeView === "reminders" && (
        <ReminderScreen
          child={activeChild}
          currentUserId={user.id}
          onRecordNow={(reminder) => {
            // Phase 1: navigasi ke layar catatan yang SUDAH ADA (bukan
            // auto-isi form/auto-taut catatan — lihat backend/docs/REMINDERS.md
            // bagian "Catat sekarang" buat batasan Phase 1 ini secara eksplisit).
            setActiveView(reminder.reminder_type === "doctor_visit" ? "health" : "daily");
          }}
        />
      )}
      {activeView === "childProfile" && (
        <ChildProfileScreen child={activeChild} currentUserId={user.id} onUpdated={handleChildUpdated} />
      )}
      {activeView === "userProfile" && <UserProfileScreen user={user} onUserUpdated={setUser} />}
      {activeView === "privacy" && (
        <PrivacyDataScreen onAccessChanged={reloadChildren} onAccountDeleted={logout} />
      )}
      </main>

      <BottomNavigation activeView={activeView} onNavigate={setActiveView} />

      {showMenu && (
        <div className="fixed inset-0 z-50 flex items-start justify-end sm:items-center sm:justify-center">
          <div className="absolute inset-0 bg-black/50" onClick={() => setShowMenu(false)} />
          <div className="relative w-full sm:max-w-xs bg-void-card border-b sm:border border-void-hairline rounded-b-xl2 sm:rounded-xl2 p-4 pb-6">
            <p className="text-[11px] text-ink-faint uppercase tracking-wider font-mono px-2 pt-1 pb-2">
              Menu
            </p>
            <div className="space-y-1 mb-3">
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
            <div className="border-t border-void-hairline pt-3 space-y-1">
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
              {isOwner(activeChild.role) && (
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
              )}
              <button
                onClick={() => {
                  setShowMenu(false);
                  setShowSyncCenter(true);
                }}
                className="w-full flex items-center gap-3 px-3 py-2.5 rounded-xl2 text-sm text-ink text-left"
              >
                <span className="text-base">🔄</span>
                Status Sinkronisasi
              </button>
              <button
                onClick={() => {
                  setShowMenu(false);
                  setShowAuditTrail(true);
                }}
                className="w-full flex items-center gap-3 px-3 py-2.5 rounded-xl2 text-sm text-ink text-left"
              >
                <span className="text-base">🕘</span>
                Aktivitas Pengasuh
              </button>
              <button
                onClick={() => {
                  setActiveView("privacy");
                  setShowMenu(false);
                }}
                className={`w-full flex items-center gap-3 px-3 py-2.5 rounded-xl2 text-sm text-left ${
                  activeView === "privacy" ? "bg-feed/15 text-feed font-medium" : "text-ink"
                }`}
              >
                <span className="text-base">🔐</span>
                Privasi & Data
              </button>
              <button
                onClick={handleLogout}
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

      {showSyncCenter && <SyncCenter sync={sync} onClose={() => setShowSyncCenter(false)} />}

      {showAuditTrail && (
        <AuditTrailScreen
          child={activeChild}
          currentUserId={user.id}
          onClose={() => setShowAuditTrail(false)}
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
