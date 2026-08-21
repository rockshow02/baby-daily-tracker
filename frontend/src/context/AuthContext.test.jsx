import { beforeEach, describe, expect, it, vi } from "vitest";
import { act, renderHook, waitFor } from "@testing-library/react";
import { AuthProvider, useAuth } from "./AuthContext";
import { getToken, getCurrentUserId } from "../api/client";

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

beforeEach(() => {
  localStorage.clear();
  apiMock.me.mockReset();
  apiMock.login.mockReset();
  apiMock.register.mockReset();
  apiMock.logout.mockReset();
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
