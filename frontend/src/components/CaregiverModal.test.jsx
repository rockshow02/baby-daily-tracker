import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent, waitFor, within } from "@testing-library/react";
import CaregiverModal from "./CaregiverModal";

const { apiMock } = vi.hoisted(() => ({
  apiMock: {
    listCaregivers: vi.fn(),
    createInvite: vi.fn(),
    updateCaregiverRole: vi.fn(),
    removeCaregiver: vi.fn(),
  },
}));

vi.mock("../api/client", () => ({ api: apiMock }));

const testChild = { id: 1, name: "Dedek" };

function ownerAsOwner() {
  // name SENGAJA bukan "Pemilik" — biar nggak bentrok sama teks badge
  // peran "Pemilik" pas dites (2 elemen beda yang kebetulan sama teksnya).
  return { user_id: 1, name: "Bunda", email: "owner@test.com", role: "owner" };
}
function editorEntry(overrides = {}) {
  return { user_id: 2, name: "Editor Test", email: "editor@test.com", role: "editor", ...overrides };
}

beforeEach(() => {
  apiMock.listCaregivers.mockReset();
  apiMock.createInvite.mockReset();
  apiMock.updateCaregiverRole.mockReset();
  apiMock.removeCaregiver.mockReset();
});

afterEach(() => {
  vi.restoreAllMocks();
});

async function renderAsOwner(extraCaregivers = [editorEntry()]) {
  apiMock.listCaregivers.mockResolvedValue([ownerAsOwner(), ...extraCaregivers]);
  render(<CaregiverModal child={testChild} currentUserId={1} onClose={vi.fn()} />);
  await screen.findByText("Editor Test");
}

describe("CaregiverModal — accessibility", () => {
  it("exposes a dialog role, aria-modal, and a labelled title", async () => {
    await renderAsOwner();
    const dialog = screen.getByRole("dialog", { name: `Pengasuh ${testChild.name}` });
    expect(dialog).toBeInTheDocument();
    expect(dialog).toHaveAttribute("aria-modal", "true");
  });

  it("closes on Escape", async () => {
    apiMock.listCaregivers.mockResolvedValue([ownerAsOwner()]);
    const onClose = vi.fn();
    render(<CaregiverModal child={testChild} currentUserId={1} onClose={onClose} />);
    fireEvent.keyDown(window, { key: "Escape" });
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});

describe("CaregiverModal — role labels", () => {
  it("shows translated role labels, never the raw backend role string", async () => {
    await renderAsOwner();
    expect(screen.getByText("Pemilik")).toBeInTheDocument();
    // "Editor" muncul beberapa kali (badge peran + tombol ubah-peran +
    // pilihan undangan) — cukup buktikan minimal 1 label terjemahan ada,
    // BUKAN string role mentah "editor" (huruf kecil) yang nggak pernah
    // dipakai di mana pun.
    expect(screen.getAllByText("Editor").length).toBeGreaterThan(0);
    expect(screen.queryByText("editor")).not.toBeInTheDocument();
    expect(screen.queryByText("owner")).not.toBeInTheDocument();
  });
});

describe("CaregiverModal — owner-only invitation UI", () => {
  it("lets the owner pick Editor or Viewer, defaulting to Editor, before creating an invite", async () => {
    apiMock.listCaregivers.mockResolvedValue([ownerAsOwner()]);
    apiMock.createInvite.mockResolvedValue({ code: "ABCD1234", role: "viewer" });
    render(<CaregiverModal child={testChild} currentUserId={1} onClose={vi.fn()} />);
    await screen.findByText("Undang pengasuh baru");

    const viewerOption = screen.getByRole("button", { name: "Hanya melihat" });
    fireEvent.click(viewerOption);

    fireEvent.click(screen.getByRole("button", { name: "Buat Kode Undangan" }));

    await waitFor(() => expect(apiMock.createInvite).toHaveBeenCalledWith(testChild.id, "viewer"));
    expect(await screen.findByText("ABCD1234")).toBeInTheDocument();
  });

  it("does not show the invitation section to a non-owner (defense in depth even if somehow opened)", async () => {
    apiMock.listCaregivers.mockResolvedValue([ownerAsOwner(), editorEntry({ user_id: 2 })]);
    render(<CaregiverModal child={testChild} currentUserId={2} onClose={vi.fn()} />);
    await screen.findByText("Editor Test");

    expect(screen.queryByText("Undang pengasuh baru")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Buat Kode Undangan" })).not.toBeInTheDocument();
  });
});

describe("CaregiverModal — role update flow", () => {
  it("owner can switch a caregiver from editor to viewer", async () => {
    apiMock.updateCaregiverRole.mockResolvedValue({ user_id: 2, role: "viewer" });
    await renderAsOwner([editorEntry()]);

    // grup ubah-peran baris caregiver ini SPESIFIK (aria-label-nya nyebut
    // nama caregivernya), jadi nggak ambigu sama pilihan peran undangan
    // di bagian bawah modal yang SAMA-SAMA punya tombol "Hanya melihat".
    const roleGroup = screen.getByRole("group", { name: "Ubah peran Editor Test" });
    apiMock.listCaregivers.mockResolvedValueOnce([ownerAsOwner(), editorEntry({ role: "viewer" })]);
    fireEvent.click(within(roleGroup).getByRole("button", { name: "Hanya melihat" }));

    await waitFor(() =>
      expect(apiMock.updateCaregiverRole).toHaveBeenCalledWith(testChild.id, 2, "viewer"),
    );
  });

  it("does not show role-change controls for the owner's own row", async () => {
    await renderAsOwner();
    // baris "Pemilik" nggak boleh punya grup ubah-peran sama sekali —
    // cuma baris caregiver non-pemilik yang dapet kontrol ini
    expect(screen.queryByRole("group", { name: "Ubah peran Pemilik" })).not.toBeInTheDocument();
    expect(screen.getByRole("group", { name: "Ubah peran Editor Test" })).toBeInTheDocument();
  });
});

describe("CaregiverModal — revoke confirmation flow", () => {
  it("requires a two-step confirmation before revoking access", async () => {
    apiMock.removeCaregiver.mockResolvedValue({ success: true });
    await renderAsOwner();

    fireEvent.click(screen.getByRole("button", { name: "Cabut" }));
    expect(apiMock.removeCaregiver).not.toHaveBeenCalled();

    const confirmButton = await screen.findByRole("button", { name: "Yakin, cabut" });
    apiMock.listCaregivers.mockResolvedValueOnce([ownerAsOwner()]);
    fireEvent.click(confirmButton);

    await waitFor(() => expect(apiMock.removeCaregiver).toHaveBeenCalledWith(testChild.id, 2));
  });

  it("cancelling the confirmation does not revoke access", async () => {
    await renderAsOwner();

    fireEvent.click(screen.getByRole("button", { name: "Cabut" }));
    fireEvent.click(await screen.findByRole("button", { name: "Batal" }));

    expect(apiMock.removeCaregiver).not.toHaveBeenCalled();
    expect(screen.getByText("Editor Test")).toBeInTheDocument();
  });
});
