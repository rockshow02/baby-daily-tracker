import { createContext, useContext, useEffect, useState } from "react";
import { api, setToken, clearToken, getToken } from "../api/client";

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
      .then(setUser)
      .catch(() => {
        setUser(null);
        clearToken();
      })
      .finally(() => setLoading(false));
  }, []);

  const login = async (email, password) => {
    const u = await api.login({ email, password });
    setToken(u.token);
    setUser(u);
    return u;
  };

  const register = async (name, email, password) => {
    const u = await api.register({ name, email, password });
    setToken(u.token);
    setUser(u);
    return u;
  };

  const logout = async () => {
    try {
      await api.logout();
    } finally {
      clearToken();
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