import { beforeEach, describe, expect, it, vi } from "vitest";
import { act, renderHook, waitFor } from "@testing-library/react";
import { AuthProvider, useAuth } from "./AuthContext";
import { getToken, getCurrentUserId, setToken, setCurrentUser, clearToken, clearCurrentUser, ApiError } from "../api/client";
import { cacheUserProfile, getCachedUserProfile } from "../utils/sessionCache";

// vi.mock's factory is hoisted above regular top-level const/let, jadi
// apiMock (yang dipakai di dalam factory) harus dibikin lewat vi.hoisted
// biar nggak kena "Cannot access before initialization".
const { apiMock } = vi.hoisted(() => ({
  apiMock: {
    me: vi.fn(),
    login: vi.fn(),
    register: vi.fn(),
    logout: vi.fn(),
  },
}));

vi.mock("../api/client", async (importOriginal) => {
  // dipakai FUNGSI ASLI buat token/currentUser (localStorage biasa) — cuma
  // `api` (network call) yang di-mock, biar test ini bener-bener ngebuktiin
  // AuthContext nge-clear localStorage yang sebenarnya, bukan cuma mock call
  const actual = await importOriginal();
  return { ...actual, api: apiMock };
});

function wrapper({ children }) {
  return <AuthProvider>{children}</AuthProvider>;
}

function setOnline(value) {
  Object.defineProperty(window.navigator, "onLine", { value, configurable: true });
}

beforeEach(() => {
  localStorage.clear();
  apiMock.me.mockReset();
  apiMock.login.mockReset();
  apiMock.register.mockReset();
  apiMock.logout.mockReset();
  setOnline(true);
});

describe("AuthContext", () => {
  it("login stores the token and current-user id, and exposes the user", async () => {
    apiMock.login.mockResolvedValue({ id: 5, name: "Ibu Test", email: "ibu@test.com", token: "tok-5" });
    const { result } = renderHook(() => useAuth(), { wrapper });
    await waitFor(() => expect(result.current.loading).toBe(false));

    await act(async () => {
      await result.current.login("ibu@test.com", "password123");
    });

    expect(result.current.user).toMatchObject({ id: 5, name: "Ibu Test" });
    expect(getToken()).toBe("tok-5");
    expect(getCurrentUserId()).toBe(5);
  });

  it("3. logout clears the invalid session — token, current-user id, and user state", async () => {
    apiMock.login.mockResolvedValue({ id: 5, name: "Ibu Test", email: "ibu@test.com", token: "tok-5" });
    apiMock.logout.mockResolvedValue({ success: true });
    const { result } = renderHook(() => useAuth(), { wrapper });
    await waitFor(() => expect(result.current.loading).toBe(false));
    await act(async () => {
      await result.current.login("ibu@test.com", "password123");
    });

    await act(async () => {
      await result.current.logout();
    });

    expect(result.current.user).toBeNull();
    expect(getToken()).toBeNull();
    expect(getCurrentUserId()).toBeNull();
  });

  it("logout still clears local session state even if the server logout call fails", async () => {
    apiMock.login.mockResolvedValue({ id: 5, name: "Ibu Test", email: "ibu@test.com", token: "tok-5" });
    apiMock.logout.mockRejectedValue(new Error("network error"));
    const { result } = renderHook(() => useAuth(), { wrapper });
    await waitFor(() => expect(result.current.loading).toBe(false));
    await act(async () => {
      await result.current.login("ibu@test.com", "password123");
    });

    await act(async () => {
      await result.current.logout();
    });

    expect(result.current.user).toBeNull();
    expect(getToken()).toBeNull();
  });
});

describe("AuthContext — offline session recovery (hard refresh / cold start while offline)", () => {
  it("1. a network failure during the /auth/me startup check does not clear the token", async () => {
    setToken("tok-5");
    setCurrentUser(5);
    apiMock.me.mockRejectedValue(
      new ApiError({ kind: "network", message: "Nggak ada koneksi internet. Coba lagi nanti." }),
    );

    const { result } = renderHook(() => useAuth(), { wrapper });
    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(getToken()).toBe("tok-5");
  });

  it("2. a network failure during the /auth/me startup check does not clear the current-user id", async () => {
    setToken("tok-5");
    setCurrentUser(5);
    apiMock.me.mockRejectedValue(new ApiError({ kind: "network", message: "offline" }));

    const { result } = renderHook(() => useAuth(), { wrapper });
    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(getCurrentUserId()).toBe(5);
  });

  it("3. a matching cached user is restored during offline startup", async () => {
    setToken("tok-5");
    setCurrentUser(5);
    cacheUserProfile({ id: 5, name: "Ibu Test", email: "ibu@test.com" });
    apiMock.me.mockRejectedValue(new ApiError({ kind: "network", message: "offline" }));

    const { result } = renderHook(() => useAuth(), { wrapper });
    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(result.current.user).toMatchObject({ id: 5, name: "Ibu Test" });
    expect(result.current.isOfflineSession).toBe(true);
  });

  it("4. a cached user with a different id is rejected (never used to silently restore the wrong account)", async () => {
    setToken("tok-5");
    setCurrentUser(5);
    // cache ini punya id BEDA dari currentUserId — simulasi sisa cache dari akun lain di perangkat yang sama
    cacheUserProfile({ id: 999, name: "Akun Lain", email: "lain@test.com" });
    apiMock.me.mockRejectedValue(new ApiError({ kind: "network", message: "offline" }));

    const { result } = renderHook(() => useAuth(), { wrapper });
    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(result.current.user).toBeNull();
  });

  it("5. a confirmed 401 clears the session and cache", async () => {
    setToken("tok-5");
    setCurrentUser(5);
    cacheUserProfile({ id: 5, name: "Ibu Test", email: "ibu@test.com" });
    apiMock.me.mockRejectedValue(new ApiError({ kind: "unauthorized", status: 401, message: "Sesi tidak valid" }));

    const { result } = renderHook(() => useAuth(), { wrapper });
    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(result.current.user).toBeNull();
    expect(getToken()).toBeNull();
    expect(getCurrentUserId()).toBeNull();
    expect(getCachedUserProfile(5)).toBeNull();
  });

  it("6. a non-401 server error does not masquerade as successful authentication", async () => {
    setToken("tok-5");
    setCurrentUser(5);
    apiMock.me.mockRejectedValue(new ApiError({ kind: "server_error", status: 500, message: "Server error" }));

    const { result } = renderHook(() => useAuth(), { wrapper });
    await waitFor(() => expect(result.current.loading).toBe(false));

    // nggak ada cache buat fallback di sini, jadi "sukses" yang keliru
    // akan kelihatan sebagai user ke-set entah dari mana — pastiin nggak
    expect(result.current.user).toBeNull();
    // dan sesi TETAP dipertahankan (bukan dianggap penolakan 401)
    expect(getToken()).toBe("tok-5");
    expect(getCurrentUserId()).toBe(5);
  });

  it("7. a successful /auth/me updates the user cache", async () => {
    setToken("tok-5");
    setCurrentUser(5);
    apiMock.me.mockResolvedValue({ id: 5, name: "Ibu Test Baru", email: "ibu@test.com" });

    const { result } = renderHook(() => useAuth(), { wrapper });
    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(result.current.user).toMatchObject({ id: 5, name: "Ibu Test Baru" });
    expect(getCachedUserProfile(5)).toMatchObject({ id: 5, name: "Ibu Test Baru" });
    expect(result.current.isOfflineSession).toBe(false);
  });

  it("8. returning online retries session validation and replaces the cached profile with the server response", async () => {
    setToken("tok-5");
    setCurrentUser(5);
    cacheUserProfile({ id: 5, name: "Ibu Test", email: "ibu@test.com" });
    apiMock.me.mockRejectedValueOnce(new ApiError({ kind: "network", message: "offline" }));

    const { result } = renderHook(() => useAuth(), { wrapper });
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.isOfflineSession).toBe(true);

    apiMock.me.mockResolvedValueOnce({ id: 5, name: "Ibu Test Update", email: "ibu@test.com" });
    setOnline(true);
    act(() => {
      window.dispatchEvent(new Event("online"));
    });

    await waitFor(() => expect(result.current.isOfflineSession).toBe(false));
    expect(result.current.user).toMatchObject({ name: "Ibu Test Update" });
    expect(apiMock.me).toHaveBeenCalledTimes(2);
  });

  it("9. returning online and receiving a 401 clears the offline session", async () => {
    setToken("tok-5");
    setCurrentUser(5);
    cacheUserProfile({ id: 5, name: "Ibu Test", email: "ibu@test.com" });
    apiMock.me.mockRejectedValueOnce(new ApiError({ kind: "network", message: "offline" }));

    const { result } = renderHook(() => useAuth(), { wrapper });
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.user).toMatchObject({ id: 5 });

    apiMock.me.mockRejectedValueOnce(new ApiError({ kind: "unauthorized", status: 401, message: "invalid" }));
    act(() => {
      window.dispatchEvent(new Event("online"));
    });

    await waitFor(() => expect(result.current.user).toBeNull());
    expect(getToken()).toBeNull();
  });

  it("a stale successful /auth/me response does not resurrect a session cleared by another process while it was in flight", async () => {
    setToken("tok-5");
    setCurrentUser(5);
    let resolveMe;
    apiMock.me.mockImplementation(
      () =>
        new Promise((resolve) => {
          resolveMe = resolve;
        }),
    );

    const { result } = renderHook(() => useAuth(), { wrapper });
    // startup effect udah nembak api.me(), tapi masih pending

    // simulasikan proses LAIN (mis. request lain — App.jsx muat daftar
    // anak — balik 401 lebih dulu dan motor logout()) nge-clear sesi
    // duluan SELAGI /auth/me di atas masih di-fly
    clearToken();
    clearCurrentUser();

    await act(async () => {
      resolveMe({ id: 5, name: "Ibu Test", email: "ibu@test.com" });
      await Promise.resolve();
    });

    await waitFor(() => expect(result.current.loading).toBe(false));

    // respons "sukses" yang basi ini TIDAK BOLEH nghidupin lagi sesi yang
    // emang udah sengaja ditutup oleh proses lain
    expect(result.current.user).toBeNull();
    expect(getToken()).toBeNull();
  });

  it("does not fire duplicate /auth/me requests when 'online' fires more than once in quick succession", async () => {
    setToken("tok-5");
    setCurrentUser(5);
    apiMock.me.mockResolvedValue({ id: 5, name: "Ibu Test", email: "ibu@test.com" });

    const { result } = renderHook(() => useAuth(), { wrapper });
    await waitFor(() => expect(result.current.loading).toBe(false));
    const callsAfterStartup = apiMock.me.mock.calls.length;

    act(() => {
      window.dispatchEvent(new Event("online"));
      window.dispatchEvent(new Event("online"));
      window.dispatchEvent(new Event("online"));
    });

    await waitFor(() => expect(apiMock.me.mock.calls.length).toBeGreaterThan(callsAfterStartup));
    // sinkron rapat berturut-turut TETAP nggak boleh numpuk lebih dari 1
    // request ekstra yang beneran nyampe network — checkingRef nolak yang
    // dobel selagi salah satu masih berjalan
    expect(apiMock.me.mock.calls.length).toBe(callsAfterStartup + 1);
  });
});
