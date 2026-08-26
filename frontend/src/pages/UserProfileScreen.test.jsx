import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import UserProfileScreen from "./UserProfileScreen";

const { apiMock } = vi.hoisted(() => ({
  apiMock: {
    listChildren: vi.fn(),
    listCaregivers: vi.fn(),
    updateProfile: vi.fn(),
    changePassword: vi.fn(),
    testTelegram: vi.fn(),
  },
}));

vi.mock("../api/client", () => ({ api: apiMock }));

const testUser = { id: 1, name: "Bunda", email: "bunda@test.com", telegram_chat_id: null };

beforeEach(() => {
  Object.values(apiMock).forEach((fn) => fn.mockReset());
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("UserProfileScreen — 'Anak yang Kamu Akses' (Caregiver Roles & Permissions Phase 1)", () => {
  it("uses the role already returned by listChildren() directly, without any per-child listCaregivers lookup", async () => {
    // Caregiver Roles & Permissions Phase 1 — api.listChildren() sudah
    // menyertakan `role` langsung di tiap objek anak; layar ini SEBELUMNYA
    // masih manggil api.listCaregivers(c.id) per anak buat nge-derive
    // ulang perannya (asumsi basi dari sebelum owner selalu punya `role`
    // di respons listChildren) — sekarang HARUS TIDAK PERNAH memanggilnya
    // sama sekali.
    apiMock.listChildren.mockResolvedValue([
      { id: 1, name: "Anak Satu", nickname: "Dedek", role: "owner" },
      { id: 2, name: "Anak Dua", nickname: "Kaka", role: "editor" },
    ]);

    render(<UserProfileScreen user={testUser} onUserUpdated={vi.fn()} />);

    await waitFor(() => expect(screen.getByText("Dedek")).toBeInTheDocument());
    expect(screen.getByText("Kaka")).toBeInTheDocument();
    expect(apiMock.listCaregivers).not.toHaveBeenCalled();
  });

  it("translates role labels through the shared allowlist, never showing a raw backend role string", async () => {
    apiMock.listChildren.mockResolvedValue([
      { id: 1, name: "Anak Satu", nickname: "Dedek", role: "owner" },
      { id: 2, name: "Anak Dua", nickname: "Kaka", role: "editor" },
      { id: 3, name: "Anak Tiga", nickname: "Bayi", role: "viewer" },
    ]);

    render(<UserProfileScreen user={testUser} onUserUpdated={vi.fn()} />);
    await waitFor(() => expect(screen.getByText("Dedek")).toBeInTheDocument());

    expect(screen.getByText("Pemilik")).toBeInTheDocument();
    expect(screen.getByText("Editor")).toBeInTheDocument();
    expect(screen.getByText("Hanya melihat")).toBeInTheDocument();
    expect(screen.queryByText("owner")).not.toBeInTheDocument();
    expect(screen.queryByText("editor")).not.toBeInTheDocument();
    expect(screen.queryByText("viewer")).not.toBeInTheDocument();
  });

  it("shows an empty state when the user has no accessible children", async () => {
    apiMock.listChildren.mockResolvedValue([]);
    render(<UserProfileScreen user={testUser} onUserUpdated={vi.fn()} />);
    expect(await screen.findByText("Belum ada anak.")).toBeInTheDocument();
  });
});
