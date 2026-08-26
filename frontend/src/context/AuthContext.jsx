import { createContext, useCallback, useContext, useEffect, useRef, useState } from "react";
import {
  api,
  ApiError,
  setToken,
  clearToken,
  getToken,
  setCurrentUser,
  clearCurrentUser,
  getCurrentUserId,
} from "../api/client";
import { cacheUserProfile, getCachedUserProfile, clearUserCache } from "../utils/sessionCache";
import { clearLastSyncedAt } from "../utils/syncMetadata";
import { clearAllInsightSnapshotsForUser } from "../utils/insightCache";
import { clearAllReminderSnapshotsForUser } from "../utils/reminderCache";
import { clearAllMedicationScheduleSnapshotsForUser } from "../utils/medicationScheduleCache";
import { clearNotificationStateForUser } from "../utils/reminderNotifications";

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);
  // true kalau `user` di atas direstorasi dari cache lokal TANPA konfirmasi
  // server terbaru (mis. hard refresh sambil offline) — BUKAN berarti
  // sesinya invalid, cuma belum divalidasi ulang. Server tetap otoritatif
  // begitu online lagi (lihat refreshSessionFromServer di bawah).
  const [isOfflineSession, setIsOfflineSession] = useState(false);

  // guard SATU pintu, dipakai bareng sama startup check DAN reconnect
  // check, biar nggak pernah ada 2 request /auth/me jalan bersamaan (mis.
  // event "online" nyala pas startup check masih berjalan).
  const checkingRef = useRef(false);

  // applyServerUser/clearSession/refreshSessionFromServer/login/register/
  // logout SEMUA di-useCallback dengan dependency yang stabil (cuma
  // setState + import modul, nggak pernah berubah identitasnya) — biar
  // referensinya STABIL selama AuthProvider hidup. Ini penting soalnya
  // App.jsx makein `logout` sebagai dependency useCallback-nya sendiri
  // (loadChildren); kalau `logout` ganti identitas tiap render, itu bakal
  // motor App.jsx re-fetch daftar anak berulang-ulang tanpa henti.
  const applyServerUser = useCallback((u) => {
    setCurrentUser(u.id);
    cacheUserProfile(u);
    setUser(u);
    setIsOfflineSession(false);
  }, []);

  const clearSession = useCallback(() => {
    // baca userId SEBELUM di-clear — perlu buat nentuin cache siapa yang
    // mesti dibersihin
    const uid = getCurrentUserId();
    setUser(null);
    clearToken();
    clearCurrentUser();
    if (uid != null) {
      clearUserCache(uid);
      // Konsisten sama kebijakan cache per-user lain di atas — lihat
      // utils/syncMetadata.js buat kenapa ini AMAN (nggak sensitif) tapi
      // tetap dibersihkan buat konsistensi. Antrian offline ITU SENDIRI
      // (utils/offlineQueue.js) TIDAK disentuh di sini — logout nggak
      // pernah menghapus catatan yang masih nunggu disinkron.
      clearLastSyncedAt(uid);
      // Snapshot insight (utils/insightCache.js) SAMA — nggak sensitif
      // (payload-nya sendiri sudah privacy-minimal, lihat
      // backend/docs/INSIGHTS.md), tapi tetap dibersihkan biar akun lain
      // yang login di device yang sama nggak pernah kebetulan lihat
      // snapshot akun sebelumnya.
      clearAllInsightSnapshotsForUser(uid);
      // Snapshot reminder (utils/reminderCache.js) + jejak deduplikasi
      // notifikasi/preferensi opt-in (utils/reminderNotifications.js) —
      // SAMA alasannya: akun lain yang login di device yang sama TIDAK
      // PERNAH boleh kebetulan lihat/dapet notifikasi dari data akun
      // sebelumnya.
      clearAllReminderSnapshotsForUser(uid);
      // Snapshot jadwal obat (utils/medicationScheduleCache.js) — SAMA
      // alasannya kayak snapshot reminder di atas.
      clearAllMedicationScheduleSnapshotsForUser(uid);
      clearNotificationStateForUser(uid);
    }
    setIsOfflineSession(false);
  }, []);

  /**
   * Coba validasi ulang sesi ke server (dipanggil pas startup DAN pas
   * reconnect). Balikin:
   * - { ok: true } kalau server BENERAN ngonfirmasi — baik sukses ATAU
   *   401 yang ke-konfirmasi invalid, dua-duanya "selesai", pemanggil
   *   nggak perlu fallback apa-apa lagi.
   * - { ok: false } kalau gagal karena JARINGAN atau error server lain
   *   yang BUKAN 401 (mis. 500) — sesi yang lagi aktif TIDAK disentuh sama
   *   sekali di sini. Kegagalan jaringan TIDAK PERNAH dianggap sebagai
   *   penolakan otentikasi yang ke-konfirmasi.
   */
  const refreshSessionFromServer = useCallback(async () => {
    try {
      const u = await api.me();
      if (!getToken()) {
        // sesi ini udah di-clear duluan sama proses LAIN (mis. request
        // lain — App.jsx muat daftar anak — balik 401 lebih dulu dan
        // motor logout()) SELAGI /auth/me ini masih di-fly. Jangan
        // resurrect sesi yang emang udah sengaja ditutup cuma gara-gara
        // respons basi ini kebetulan sukses.
        return { ok: true };
      }
      applyServerUser(u);
      return { ok: true };
    } catch (err) {
      if (err instanceof ApiError && err.kind === "unauthorized") {
        clearSession();
        return { ok: true };
      }
      return { ok: false };
    }
  }, [applyServerUser, clearSession]);

  useEffect(() => {
    // kalau nggak ada token tersimpan sama sekali, nggak usah nembak /me
    // (biar langsung ke layar login, nggak nunggu network round-trip percuma)
    if (!getToken()) {
      setLoading(false);
      return;
    }

    let cancelled = false;
    checkingRef.current = true;
    refreshSessionFromServer().then((result) => {
      if (cancelled) return;
      if (!result.ok) {
        // gagal jaringan (atau error server non-401) pas startup — JANGAN
        // nge-clear sesi (requirement #13). Restorasi shell offline dari
        // cache lokal, TAPI cuma kalau id-nya cocok sama currentUserId
        // yang lagi aktif — jangan pernah diam-diam pakai cache akun lain.
        const uid = getCurrentUserId();
        const cached = uid != null ? getCachedUserProfile(uid) : null;
        if (cached) {
          setUser(cached);
          setIsOfflineSession(true);
        }
        // kalau nggak ada cache yang cocok, token & currentUserId TETAP
        // dibiarin utuh (bisa aja koneksi balik sebentar lagi) — cuma
        // `user` state-nya tetap null, jadi UI nunjukin layar login
        // sampai validasi berhasil, bukan nge-clear sesi paksa.
      }
      setLoading(false);
      checkingRef.current = false;
    });

    return () => {
      cancelled = true;
    };
  }, [refreshSessionFromServer]);

  useEffect(() => {
    const handleOnline = () => {
      if (checkingRef.current || !getToken()) return;
      checkingRef.current = true;
      refreshSessionFromServer().finally(() => {
        checkingRef.current = false;
      });
    };
    window.addEventListener("online", handleOnline);
    return () => window.removeEventListener("online", handleOnline);
  }, [refreshSessionFromServer]);

  const login = useCallback(
    async (email, password) => {
      const u = await api.login({ email, password });
      setToken(u.token);
      applyServerUser(u);
      return u;
    },
    [applyServerUser],
  );

  const register = useCallback(
    async (name, email, password) => {
      const u = await api.register({ name, email, password });
      setToken(u.token);
      applyServerUser(u);
      return u;
    },
    [applyServerUser],
  );

  const logout = useCallback(async () => {
    try {
      await api.logout();
    } catch (_) {
      // logout di server gagal (jaringan mati, token udah invalid, dll) —
      // nggak masalah, state lokal (token, currentUser, user, cache) TETAP
      // wajib dibersihin di bawah. Penting jangan sampai reject di sini
      // nembus ke pemanggil yang nggak nunggu/nangkep promise-nya (mis.
      // tombol "Masuk lagi" di OfflineStatusBanner motor logout() tanpa
      // await), soalnya itu bisa jadi unhandled promise rejection padahal
      // sesi-nya sendiri udah kebersih sesuai rencana.
    } finally {
      clearSession();
    }
  }, [clearSession]);

  return (
    <AuthContext.Provider value={{ user, loading, isOfflineSession, login, register, logout, setUser }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  return useContext(AuthContext);
}
