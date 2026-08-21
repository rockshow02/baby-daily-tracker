import { createContext, useContext, useEffect, useState } from "react";
import {
  api,
  setToken,
  clearToken,
  getToken,
  setCurrentUser,
  clearCurrentUser,
} from "../api/client";

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    // kalau nggak ada token tersimpan sama sekali, nggak usah nembak /me
    // (biar langsung ke layar login, nggak nunggu network round-trip percuma)
    if (!getToken()) {
      setLoading(false);
      return;
    }
    api
      .me()
      .then((u) => {
        // backfill user id buat sesi yang udah login dari sebelum fitur
        // penandaan pemilik antrian offline ini ada
        setCurrentUser(u.id);
        setUser(u);
      })
      .catch(() => {
        setUser(null);
        clearToken();
        clearCurrentUser();
      })
      .finally(() => setLoading(false));
  }, []);

  const login = async (email, password) => {
    const u = await api.login({ email, password });
    setToken(u.token);
    setCurrentUser(u.id);
    setUser(u);
    return u;
  };

  const register = async (name, email, password) => {
    const u = await api.register({ name, email, password });
    setToken(u.token);
    setCurrentUser(u.id);
    setUser(u);
    return u;
  };

  const logout = async () => {
    try {
      await api.logout();
    } catch (_) {
      // logout di server gagal (jaringan mati, token udah invalid, dll) —
      // nggak masalah, state lokal (token, currentUser, user) TETAP wajib
      // dibersihin di bawah. Penting jangan sampai reject di sini nembus
      // ke pemanggil yang nggak nunggu/nangkep promise-nya (mis. tombol
      // "Masuk lagi" di OfflineStatusBanner motor logout() tanpa await),
      // soalnya itu bisa jadi unhandled promise rejection padahal
      // sesi-nya sendiri udah kebersih sesuai rencana.
    } finally {
      clearToken();
      clearCurrentUser();
      setUser(null);
    }
  };

  return (
    <AuthContext.Provider value={{ user, loading, login, register, logout, setUser }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  return useContext(AuthContext);
}