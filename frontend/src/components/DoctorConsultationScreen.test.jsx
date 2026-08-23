import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import DoctorConsultationScreen from "./DoctorConsultationScreen";

const { apiMock } = vi.hoisted(() => ({
  apiMock: {
    previewDoctorConsultation: vi.fn(),
    doctorConsultationPdfUrl: vi.fn((childId) => `http://x/api/children/${childId}/doctor-consultation/pdf`),
    downloadAuthenticatedPost: vi.fn(),
  },
}));

vi.mock("../api/client", async (importOriginal) => {
  const actual = await importOriginal();
  return { ...actual, api: apiMock };
});

const testChild = { id: 10, name: "Anak Satu", nickname: "Dedek", birth_date: "2026-01-01" };

function setOnline(value) {
  Object.defineProperty(window.navigator, "onLine", { value, configurable: true });
}

function makeReport(overrides = {}) {
  return {
    child_id: 10,
    child_display_name: "Dedek",
    period: { preset: "7d", start_date: "2026-08-17", end_date: "2026-08-23", timezone: "Asia/Jakarta", days: 7 },
    generated_at: "2026-08-23T10:00:00+07:00",
    disclaimer: "Laporan ini dibuat dari catatan yang dimasukkan oleh caregiver dan bukan diagnosis atau pengganti konsultasi medis profesional.",
    privacy_note: "privasi",
    generated_statement: "Dibuat dari catatan yang dimasukkan oleh caregiver.",
    included_sections: ["child_summary", "feeding"],
    sensitive_sections_included: [],
    sections: {
      child_summary: { display_name: "Dedek", birth_date: "2026-01-01" },
      feeding: { total_events: 3 },
    },
    capabilities: { can_preview: true, can_export: true, can_add_private_notes: true, can_record_visit: true },
    request_id: "req-1",
    sensitive_section_codes: ["illness", "medication", "doctor_visits", "questions", "note"],
    ...overrides,
  };
}

beforeEach(() => {
  setOnline(true);
  Object.values(apiMock).forEach((fn) => fn.mockReset());
  apiMock.doctorConsultationPdfUrl.mockImplementation((childId) => `http://x/api/children/${childId}/doctor-consultation/pdf`);
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("DoctorConsultationScreen — period presets & preview", () => {
  it("requests a preview with the 7-day preset by default", async () => {
    apiMock.previewDoctorConsultation.mockResolvedValue(makeReport());
    render(<DoctorConsultationScreen child={testChild} onClose={vi.fn()} onRecordVisit={vi.fn()} />);

    fireEvent.click(screen.getByRole("button", { name: "Buat Pratinjau" }));

    await waitFor(() =>
      expect(apiMock.previewDoctorConsultation).toHaveBeenCalledWith(
        10, expect.objectContaining({ period: { preset: "7d" } }),
      ),
    );
    expect(await screen.findByText(/s\/d 2026-08-23/)).toBeInTheDocument();
  });

  it("switches preset to 14 days and 30 days", async () => {
    apiMock.previewDoctorConsultation.mockResolvedValue(makeReport());
    render(<DoctorConsultationScreen child={testChild} onClose={vi.fn()} onRecordVisit={vi.fn()} />);

    fireEvent.click(screen.getByRole("button", { name: "14 Hari Terakhir" }));
    fireEvent.click(screen.getByRole("button", { name: "Buat Pratinjau" }));
    await waitFor(() =>
      expect(apiMock.previewDoctorConsultation).toHaveBeenCalledWith(10, expect.objectContaining({ period: { preset: "14d" } })),
    );

    fireEvent.click(screen.getByRole("button", { name: "30 Hari Terakhir" }));
    fireEvent.click(screen.getByRole("button", { name: "Buat Pratinjau" }));
    await waitFor(() =>
      expect(apiMock.previewDoctorConsultation).toHaveBeenLastCalledWith(10, expect.objectContaining({ period: { preset: "30d" } })),
    );
  });

  it("shows a client-side validation message for a reversed custom range without calling the API", async () => {
    render(<DoctorConsultationScreen child={testChild} onClose={vi.fn()} onRecordVisit={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "Rentang Kustom" }));
    fireEvent.change(screen.getByLabelText("Mulai"), { target: { value: "2026-08-20" } });
    fireEvent.change(screen.getByLabelText("Akhir"), { target: { value: "2026-08-10" } });

    expect(await screen.findByText("Tanggal akhir tidak boleh sebelum tanggal mulai.")).toBeInTheDocument();
    expect(apiMock.previewDoctorConsultation).not.toHaveBeenCalled();
  });

  it("sends a valid custom range to the backend", async () => {
    apiMock.previewDoctorConsultation.mockResolvedValue(makeReport());
    render(<DoctorConsultationScreen child={testChild} onClose={vi.fn()} onRecordVisit={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "Rentang Kustom" }));
    fireEvent.change(screen.getByLabelText("Mulai"), { target: { value: "2026-08-01" } });
    fireEvent.change(screen.getByLabelText("Akhir"), { target: { value: "2026-08-10" } });
    fireEvent.click(screen.getByRole("button", { name: "Buat Pratinjau" }));

    await waitFor(() =>
      expect(apiMock.previewDoctorConsultation).toHaveBeenCalledWith(
        10, expect.objectContaining({ period: { preset: "custom", start_date: "2026-08-01", end_date: "2026-08-10" } }),
      ),
    );
  });

  it("shows a retryable error state when preview fails", async () => {
    apiMock.previewDoctorConsultation.mockRejectedValue(new Error("Gagal memuat"));
    render(<DoctorConsultationScreen child={testChild} onClose={vi.fn()} onRecordVisit={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "Buat Pratinjau" }));

    expect(await screen.findByText("Gagal memuat")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Coba lagi" })).toBeInTheDocument();
  });
});

describe("DoctorConsultationScreen — section selection & sensitive indicators", () => {
  it("marks sensitive sections with a distinct indicator", () => {
    render(<DoctorConsultationScreen child={testChild} onClose={vi.fn()} onRecordVisit={vi.fn()} />);
    const illnessRow = screen.getByLabelText("Riwayat Sakit").closest("div");
    expect(illnessRow).toHaveTextContent("Sensitif");
    const feedingRow = screen.getByLabelText("Menyusui / Makan").closest("div");
    expect(feedingRow).not.toHaveTextContent("Sensitif");
  });

  it("select-all and base-only controls toggle optional sections", async () => {
    apiMock.previewDoctorConsultation.mockResolvedValue(makeReport());
    render(<DoctorConsultationScreen child={testChild} onClose={vi.fn()} onRecordVisit={vi.fn()} />);

    fireEvent.click(screen.getByRole("button", { name: "Pilih semua" }));
    expect(screen.getByLabelText("Riwayat Obat")).toBeChecked();

    fireEvent.click(screen.getByRole("button", { name: "Bagian dasar saja" }));
    expect(screen.getByLabelText("Riwayat Obat")).not.toBeChecked();
    expect(screen.getByLabelText("Ringkasan Anak")).toBeChecked();
  });
});

describe("DoctorConsultationScreen — PDF export & privacy confirmation", () => {
  it("downloads directly when no sensitive section is selected", async () => {
    apiMock.previewDoctorConsultation.mockResolvedValue(makeReport());
    apiMock.downloadAuthenticatedPost.mockResolvedValue();
    render(<DoctorConsultationScreen child={testChild} onClose={vi.fn()} onRecordVisit={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "Buat Pratinjau" }));
    await screen.findByRole("button", { name: "Unduh PDF" });

    fireEvent.click(screen.getByRole("button", { name: "Unduh PDF" }));
    await waitFor(() => expect(apiMock.downloadAuthenticatedPost).toHaveBeenCalledTimes(1));
  });

  it("asks for privacy confirmation before downloading a report with sensitive sections", async () => {
    apiMock.previewDoctorConsultation.mockResolvedValue(
      makeReport({ sensitive_sections_included: ["medication"] }),
    );
    apiMock.downloadAuthenticatedPost.mockResolvedValue();
    render(<DoctorConsultationScreen child={testChild} onClose={vi.fn()} onRecordVisit={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "Buat Pratinjau" }));
    await screen.findByRole("button", { name: "Unduh PDF" });

    fireEvent.click(screen.getByRole("button", { name: "Unduh PDF" }));
    expect(await screen.findByRole("alertdialog")).toBeInTheDocument();
    expect(apiMock.downloadAuthenticatedPost).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "Ya, unduh" }));
    await waitFor(() => expect(apiMock.downloadAuthenticatedPost).toHaveBeenCalledTimes(1));
  });

  it("prevents duplicate PDF submissions while a download is in flight", async () => {
    apiMock.previewDoctorConsultation.mockResolvedValue(makeReport());
    let resolveDownload;
    apiMock.downloadAuthenticatedPost.mockReturnValue(new Promise((resolve) => { resolveDownload = resolve; }));
    render(<DoctorConsultationScreen child={testChild} onClose={vi.fn()} onRecordVisit={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "Buat Pratinjau" }));
    await screen.findByRole("button", { name: "Unduh PDF" });

    fireEvent.click(screen.getByRole("button", { name: "Unduh PDF" }));
    const button = await screen.findByRole("button", { name: "Mengunduh PDF..." });
    expect(button).toBeDisabled();
    fireEvent.click(button);
    expect(apiMock.downloadAuthenticatedPost).toHaveBeenCalledTimes(1);
    resolveDownload();
  });

  it("does not offer a PDF download button to a viewer (can_export false)", async () => {
    apiMock.previewDoctorConsultation.mockResolvedValue(
      makeReport({ capabilities: { can_preview: true, can_export: false, can_add_private_notes: false, can_record_visit: false } }),
    );
    render(<DoctorConsultationScreen child={testChild} onClose={vi.fn()} onRecordVisit={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "Buat Pratinjau" }));
    await screen.findByText(/s\/d 2026-08-23/);

    expect(screen.queryByRole("button", { name: "Unduh PDF" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Catat Hasil Kunjungan" })).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/Pertanyaan untuk dokter/)).not.toBeInTheDocument();
  });
});

describe("DoctorConsultationScreen — offline behavior", () => {
  it("disables preview and shows an offline notice when offline", () => {
    setOnline(false);
    render(<DoctorConsultationScreen child={testChild} onClose={vi.fn()} onRecordVisit={vi.fn()} />);
    expect(screen.getByText(/Butuh koneksi internet/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Buat Pratinjau" })).toBeDisabled();
    expect(apiMock.previewDoctorConsultation).not.toHaveBeenCalled();
  });
});

describe("DoctorConsultationScreen — record visit reuses the existing form", () => {
  it("calls onRecordVisit (not a second form) when the button is clicked", async () => {
    apiMock.previewDoctorConsultation.mockResolvedValue(makeReport());
    const onRecordVisit = vi.fn();
    render(<DoctorConsultationScreen child={testChild} onClose={vi.fn()} onRecordVisit={onRecordVisit} />);
    fireEvent.click(screen.getByRole("button", { name: "Buat Pratinjau" }));
    await screen.findByRole("button", { name: "Catat Hasil Kunjungan" });

    fireEvent.click(screen.getByRole("button", { name: "Catat Hasil Kunjungan" }));
    expect(onRecordVisit).toHaveBeenCalledTimes(1);
  });
});
