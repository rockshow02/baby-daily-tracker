import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import PrivacyDataScreen from "./PrivacyDataScreen";

const { apiMock, queueMock } = vi.hoisted(() => ({
  apiMock: {
    privacyOverview: vi.fn(),
    downloadAuthenticated: vi.fn(),
    exportJsonUrl: vi.fn((id) => `/export/${id}`),
    deleteChildData: vi.fn(),
    leaveChildAccess: vi.fn(),
    deleteAccount: vi.fn(),
  },
  queueMock: vi.fn(),
}));

vi.mock("../api/client", () => ({ api: apiMock, getCurrentUserId: () => 7 }));
vi.mock("../utils/offlineQueue", () => ({
  getQueueForUser: queueMock,
  QUEUE_STATUS: { NEEDS_REVIEW: "needs_review" },
}));

const ownerOverview = {
  children: [{
    child: { id: 10, name: "Nara Putri", nickname: "Nara", role: "owner" },
    record_groups: [
      { key: "feeding_logs", label: "Menyusui", count: 4 },
      { key: "sleep_logs", label: "Tidur", count: 0 },
    ],
    total_records: 4,
    caregiver_count: 2,
    has_photo: true,
    capabilities: { can_export: true, can_delete_child: true, can_leave_child: false },
  }],
  account: { owned_children: 1, shared_children: 0, can_delete_account: false, confirmation_text: "HAPUS AKUN" },
};

describe("PrivacyDataScreen", () => {
  beforeEach(() => {
    Object.values(apiMock).forEach((fn) => fn.mockClear());
    queueMock.mockReset().mockResolvedValue([]);
    apiMock.privacyOverview.mockResolvedValue(ownerOverview);
    apiMock.downloadAuthenticated.mockResolvedValue(undefined);
    apiMock.deleteChildData.mockResolvedValue({ success: true, file_cleanup: "ok" });
    apiMock.leaveChildAccess.mockResolvedValue({ success: true });
    apiMock.deleteAccount.mockResolvedValue({ success: true });
  });

  it("shows privacy-minimal inventory and downloads the existing JSON backup", async () => {
    render(<PrivacyDataScreen onAccessChanged={vi.fn()} onAccountDeleted={vi.fn()} />);
    expect(await screen.findByText("Nara")).toBeInTheDocument();
    fireEvent.click(screen.getByText("Lihat inventaris data"));
    expect(screen.getByText("Menyusui")).toBeInTheDocument();
    expect(screen.queryByText("Tidur")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Unduh backup JSON" }));
    await waitFor(() => expect(apiMock.downloadAuthenticated).toHaveBeenCalledWith("/export/10", "backup-Nara.json"));
  });

  it("requires exact typed confirmation and password before deleting child data", async () => {
    const onAccessChanged = vi.fn().mockResolvedValue(undefined);
    render(<PrivacyDataScreen onAccessChanged={onAccessChanged} onAccountDeleted={vi.fn()} />);
    await screen.findByText("Nara");
    fireEvent.click(screen.getByRole("button", { name: "Hapus semua data anak" }));
    const submit = screen.getByRole("button", { name: "Hapus permanen" });
    expect(submit).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Teks konfirmasi"), { target: { value: "Nara Putri" } });
    fireEvent.change(screen.getByLabelText("Password saat ini"), { target: { value: "password123" } });
    expect(submit).toBeEnabled();
    fireEvent.click(submit);
    await waitFor(() => expect(apiMock.deleteChildData).toHaveBeenCalledWith(10, {
      password: "password123", confirmation: "Nara Putri",
    }));
    expect(onAccessChanged).toHaveBeenCalledTimes(1);
  });

  it("blocks destructive actions while this child still has pending offline mutations", async () => {
    queueMock.mockResolvedValue([{ status: "pending", url: "/children/10/feeding-logs" }]);
    render(<PrivacyDataScreen onAccessChanged={vi.fn()} onAccountDeleted={vi.fn()} />);
    await screen.findByText("Nara");
    fireEvent.click(screen.getByRole("button", { name: "Hapus semua data anak" }));
    expect(screen.getByText(/belum tersinkron/)).toBeInTheDocument();
    expect(screen.queryByLabelText("Password saat ini")).not.toBeInTheDocument();
  });

  it("shows leave action instead of delete for a viewer", async () => {
    apiMock.privacyOverview.mockResolvedValue({
      children: [{ ...ownerOverview.children[0], child: { ...ownerOverview.children[0].child, role: "viewer" }, capabilities: { can_export: true, can_delete_child: false, can_leave_child: true } }],
      account: { owned_children: 0, shared_children: 1, can_delete_account: true, confirmation_text: "HAPUS AKUN" },
    });
    render(<PrivacyDataScreen onAccessChanged={vi.fn()} onAccountDeleted={vi.fn()} />);
    await screen.findByText("Nara");
    expect(screen.getByRole("button", { name: "Keluar dari akses anak" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Hapus semua data anak" })).not.toBeInTheDocument();
  });
});
