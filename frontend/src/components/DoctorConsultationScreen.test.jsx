import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import DoctorConsultationScreen from "./DoctorConsultationScreen";

function deferred() {
  let resolve, reject;
  const promise = new Promise((res, rej) => { resolve = res; reject = rej; });
  return { promise, resolve, reject };
}

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
    snapshot_token: "signed-token-1",
    ...overrides,
  };
}

function apiError(status, message) {
  const err = new Error(message);
  err.status = status;
  return err;
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
    expect(await screen.findByText(/23 Agu 2026/)).toBeInTheDocument();
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

describe("DoctorConsultationScreen — medical profile section gating (Owner/Editor only)", () => {
  it("allows selecting the medical profile section before any preview has confirmed capabilities", () => {
    render(<DoctorConsultationScreen child={testChild} onClose={vi.fn()} onRecordVisit={vi.fn()} />);
    const checkbox = screen.getByLabelText("Profil Medis & Kartu Darurat");
    expect(checkbox).not.toBeDisabled();
    fireEvent.click(checkbox);
    expect(checkbox).toBeChecked();
  });

  it("disables and unchecks the medical profile section once a preview confirms the role cannot include it (Viewer)", async () => {
    apiMock.previewDoctorConsultation.mockResolvedValue(makeReport({
      capabilities: { can_preview: true, can_export: false, can_add_private_notes: false, can_record_visit: false, can_include_medical_profile: false },
    }));
    render(<DoctorConsultationScreen child={testChild} onClose={vi.fn()} onRecordVisit={vi.fn()} />);
    fireEvent.click(screen.getByLabelText("Profil Medis & Kartu Darurat"));
    fireEvent.click(screen.getByRole("button", { name: "Buat Pratinjau" }));

    await waitFor(() => expect(screen.getByLabelText("Profil Medis & Kartu Darurat")).toBeDisabled());
    expect(screen.getByLabelText("Profil Medis & Kartu Darurat")).not.toBeChecked();
    expect(screen.getByText("Peran Anda tidak bisa mengakses ini")).toBeInTheDocument();
  });

  it("keeps the medical profile section available when a preview confirms Owner/Editor capability", async () => {
    apiMock.previewDoctorConsultation.mockResolvedValue(makeReport({
      capabilities: { can_preview: true, can_export: true, can_add_private_notes: true, can_record_visit: true, can_include_medical_profile: true },
    }));
    render(<DoctorConsultationScreen child={testChild} onClose={vi.fn()} onRecordVisit={vi.fn()} />);
    fireEvent.click(screen.getByLabelText("Profil Medis & Kartu Darurat"));
    fireEvent.click(screen.getByRole("button", { name: "Buat Pratinjau" }));

    await waitFor(() => expect(apiMock.previewDoctorConsultation).toHaveBeenCalled());
    expect(screen.getByLabelText("Profil Medis & Kartu Darurat")).not.toBeDisabled();
    expect(screen.getByLabelText("Profil Medis & Kartu Darurat")).toBeChecked();
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
    await screen.findByText(/23 Agu 2026/);

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

// --------------------------------------------------------------------------
// Regression: PDF payload can drift from the reviewed preview (bug review
// Agustus 2026) -- Download PDF must ALWAYS use the exact immutable
// snapshot tied to the currently displayed, non-stale preview, never a
// freshly rebuilt payload from the live form.
// --------------------------------------------------------------------------
describe("DoctorConsultationScreen — preview/PDF snapshot consistency", () => {
  it("previews only default non-sensitive sections", async () => {
    apiMock.previewDoctorConsultation.mockResolvedValue(makeReport());
    render(<DoctorConsultationScreen child={testChild} onClose={vi.fn()} onRecordVisit={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "Buat Pratinjau" }));

    await waitFor(() => expect(apiMock.previewDoctorConsultation).toHaveBeenCalled());
    const [, payload] = apiMock.previewDoctorConsultation.mock.calls[0];
    expect(payload.sections).not.toContain("medication");
    expect(payload.sections).not.toContain("illness");
    expect(payload.sections).not.toContain("doctor_visits");
  });

  it("hides Download PDF after selecting a sensitive section post-preview, until re-previewed", async () => {
    apiMock.previewDoctorConsultation.mockResolvedValue(makeReport());
    render(<DoctorConsultationScreen child={testChild} onClose={vi.fn()} onRecordVisit={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "Buat Pratinjau" }));
    await screen.findByRole("button", { name: "Unduh PDF" });

    fireEvent.click(screen.getByLabelText("Riwayat Obat"));

    expect(screen.queryByRole("button", { name: "Unduh PDF" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Catat Hasil Kunjungan" })).not.toBeInTheDocument();
    expect(screen.getByText("Pilihan laporan berubah. Buat pratinjau ulang sebelum mengunduh PDF.")).toBeInTheDocument();
  });

  it("never sends a PDF request built from the changed (unpreviewed) state", async () => {
    apiMock.previewDoctorConsultation.mockResolvedValue(makeReport());
    render(<DoctorConsultationScreen child={testChild} onClose={vi.fn()} onRecordVisit={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "Buat Pratinjau" }));
    await screen.findByRole("button", { name: "Unduh PDF" });

    fireEvent.click(screen.getByLabelText("Riwayat Obat"));
    // Tombol Unduh PDF sudah nggak ada lagi (lihat test di atas) -- ini
    // regresi TAMBAHAN buat mastiin handleDownload sendiri juga menolak
    // kalau kepanggil (mis. lewat race event lain), bukan cuma tombolnya
    // nggak dirender.
    expect(apiMock.downloadAuthenticatedPost).not.toHaveBeenCalled();
  });

  it("shows privacy confirmation naming the sensitive sections after a fresh sensitive preview, then sends exactly that snapshot's payload", async () => {
    const sensitiveReport = makeReport({
      sensitive_sections_included: ["medication", "questions"],
      sections: { child_summary: {}, feeding: {}, medication: { entries: [] }, questions: { text: "Kenapa rewel?" } },
    });
    apiMock.previewDoctorConsultation.mockResolvedValue(sensitiveReport);
    apiMock.downloadAuthenticatedPost.mockResolvedValue();
    render(<DoctorConsultationScreen child={testChild} onClose={vi.fn()} onRecordVisit={vi.fn()} />);

    fireEvent.click(screen.getByLabelText("Riwayat Obat"));
    fireEvent.click(screen.getByRole("button", { name: "Buat Pratinjau" }));
    await waitFor(() => expect(apiMock.previewDoctorConsultation).toHaveBeenCalled());
    const [, sentPayload] = apiMock.previewDoctorConsultation.mock.calls[0];

    fireEvent.click(await screen.findByRole("button", { name: "Unduh PDF" }));
    const dialog = await screen.findByRole("alertdialog");
    expect(dialog).toHaveTextContent("Riwayat Obat");
    expect(dialog).toHaveTextContent("Pertanyaan untuk Dokter");
    expect(apiMock.downloadAuthenticatedPost).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "Ya, unduh" }));
    await waitFor(() => expect(apiMock.downloadAuthenticatedPost).toHaveBeenCalledTimes(1));
    const [, downloadedPayload] = apiMock.downloadAuthenticatedPost.mock.calls[0];
    // Body PDF sekarang WAJIB menyertakan snapshot_token ALONGSIDE field
    // payload yang sama persis dikirim ke preview (bentuk flat, bukan
    // nesting -- lihat backend/docs/DOCTOR_CONSULTATION.md).
    expect(downloadedPayload).toEqual({ ...sentPayload, snapshot_token: sensitiveReport.snapshot_token });
  });

  it("cannot export a stale preview as though it still represented the current (later cleared) sensitive selection", async () => {
    apiMock.previewDoctorConsultation.mockResolvedValue(
      makeReport({ sensitive_sections_included: ["medication"] }),
    );
    render(<DoctorConsultationScreen child={testChild} onClose={vi.fn()} onRecordVisit={vi.fn()} />);
    fireEvent.click(screen.getByLabelText("Riwayat Obat"));
    fireEvent.click(screen.getByRole("button", { name: "Buat Pratinjau" }));
    await screen.findByRole("button", { name: "Unduh PDF" });

    // User berubah pikiran, HAPUS lagi section sensitif itu TANPA
    // preview ulang -- laporan lama (yang masih mengandung section itu)
    // TIDAK BOLEH bisa diunduh seolah-olah merepresentasikan pilihan baru.
    fireEvent.click(screen.getByLabelText("Riwayat Obat"));
    expect(screen.queryByRole("button", { name: "Unduh PDF" })).not.toBeInTheDocument();
  });

  it("blocks export after switching from 7-day to 30-day preset post-preview", async () => {
    apiMock.previewDoctorConsultation.mockResolvedValue(makeReport());
    render(<DoctorConsultationScreen child={testChild} onClose={vi.fn()} onRecordVisit={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "Buat Pratinjau" }));
    await screen.findByRole("button", { name: "Unduh PDF" });

    fireEvent.click(screen.getByRole("button", { name: "30 Hari Terakhir" }));
    expect(screen.queryByRole("button", { name: "Unduh PDF" })).not.toBeInTheDocument();
  });

  it("blocks export after changing custom start/end dates post-preview", async () => {
    apiMock.previewDoctorConsultation.mockResolvedValue(makeReport());
    render(<DoctorConsultationScreen child={testChild} onClose={vi.fn()} onRecordVisit={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "Rentang Kustom" }));
    fireEvent.change(screen.getByLabelText("Mulai"), { target: { value: "2026-08-01" } });
    fireEvent.change(screen.getByLabelText("Akhir"), { target: { value: "2026-08-10" } });
    fireEvent.click(screen.getByRole("button", { name: "Buat Pratinjau" }));
    await screen.findByRole("button", { name: "Unduh PDF" });

    fireEvent.change(screen.getByLabelText("Akhir"), { target: { value: "2026-08-12" } });
    expect(screen.queryByRole("button", { name: "Unduh PDF" })).not.toBeInTheDocument();
  });

  it("blocks export after editing questions post-preview", async () => {
    apiMock.previewDoctorConsultation.mockResolvedValue(makeReport());
    render(<DoctorConsultationScreen child={testChild} onClose={vi.fn()} onRecordVisit={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "Buat Pratinjau" }));
    await screen.findByRole("button", { name: "Unduh PDF" });

    fireEvent.change(screen.getByLabelText(/Pertanyaan untuk dokter/), { target: { value: "Pertanyaan baru" } });
    expect(screen.queryByRole("button", { name: "Unduh PDF" })).not.toBeInTheDocument();
  });

  it("blocks export after editing the additional note post-preview", async () => {
    apiMock.previewDoctorConsultation.mockResolvedValue(makeReport());
    render(<DoctorConsultationScreen child={testChild} onClose={vi.fn()} onRecordVisit={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "Buat Pratinjau" }));
    await screen.findByRole("button", { name: "Unduh PDF" });

    fireEvent.change(screen.getByLabelText(/Catatan tambahan/), { target: { value: "Catatan baru" } });
    expect(screen.queryByRole("button", { name: "Unduh PDF" })).not.toBeInTheDocument();
  });

  it("toggling a section checkbox after preview cannot mutate the already-stored snapshot payload", async () => {
    apiMock.previewDoctorConsultation.mockResolvedValue(makeReport());
    apiMock.downloadAuthenticatedPost.mockResolvedValue();
    render(<DoctorConsultationScreen child={testChild} onClose={vi.fn()} onRecordVisit={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "Buat Pratinjau" }));
    await waitFor(() => expect(apiMock.previewDoctorConsultation).toHaveBeenCalled());
    const [, firstPayload] = apiMock.previewDoctorConsultation.mock.calls[0];
    const firstSections = [...firstPayload.sections];

    fireEvent.click(screen.getByLabelText("Riwayat Obat"));
    fireEvent.click(screen.getByLabelText("Riwayat Sakit"));

    // Set/array pilihan section BOLEH terus berubah di form, tapi
    // payload yang SUDAH dikirim/tersimpan buat preview sebelumnya
    // TIDAK PERNAH ikut berubah (bukan referensi yang sama).
    expect(firstPayload.sections).toEqual(firstSections);
    expect(firstPayload.sections).not.toContain("medication");
    expect(firstPayload.sections).not.toContain("illness");
  });

  it("clears transient questions/notes and the snapshot when the screen is closed and reopened", async () => {
    apiMock.previewDoctorConsultation.mockResolvedValue(makeReport());
    const { unmount } = render(<DoctorConsultationScreen child={testChild} onClose={vi.fn()} onRecordVisit={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "Buat Pratinjau" }));
    await screen.findByLabelText(/Pertanyaan untuk dokter/);
    fireEvent.change(screen.getByLabelText(/Pertanyaan untuk dokter/), { target: { value: "Rahasia caregiver" } });
    unmount();

    apiMock.previewDoctorConsultation.mockClear();
    render(<DoctorConsultationScreen child={testChild} onClose={vi.fn()} onRecordVisit={vi.fn()} />);
    // Layar baru TIDAK punya field pertanyaan sama sekali sampai preview
    // baru berhasil (least-privilege default) -- otomatis membuktikan
    // teks lama nggak nyangkut di mana pun (bukan cuma "kosong lagi").
    expect(screen.queryByLabelText(/Pertanyaan untuk dokter/)).not.toBeInTheDocument();
    apiMock.previewDoctorConsultation.mockResolvedValue(makeReport());
    fireEvent.click(screen.getByRole("button", { name: "Buat Pratinjau" }));
    await screen.findByLabelText(/Pertanyaan untuk dokter/);
    expect(screen.getByLabelText(/Pertanyaan untuk dokter/)).toHaveValue("");
  });

  it("clears the snapshot immediately when the active child changes", async () => {
    apiMock.previewDoctorConsultation.mockResolvedValue(makeReport());
    const { rerender } = render(<DoctorConsultationScreen child={testChild} onClose={vi.fn()} onRecordVisit={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "Buat Pratinjau" }));
    await screen.findByRole("button", { name: "Unduh PDF" });

    rerender(<DoctorConsultationScreen child={{ ...testChild, id: 99 }} onClose={vi.fn()} onRecordVisit={vi.fn()} />);

    expect(screen.queryByRole("button", { name: "Unduh PDF" })).not.toBeInTheDocument();
    expect(screen.queryByText(/23 Agu 2026/)).not.toBeInTheDocument();
  });

  it("marks an arriving preview stale immediately if the form was edited while that request was still in flight", async () => {
    // Tombol "Buat Pratinjau" sendiri disabled selagi loading (proteksi
    // double-click, lihat test terpisah) jadi TIDAK PERNAH ada 2
    // permintaan preview yang benar-benar bersamaan lewat tombol itu --
    // TAPI checkbox section TETAP bisa diklik selagi request pertama
    // masih terbang. Kasus ini yang harus ditangkap: respons yang
    // akhirnya tiba TIDAK BOLEH kelihatan "up to date" walau sedetik
    // kalau form-nya sempat berubah selagi menunggu.
    const inFlight = deferred();
    apiMock.previewDoctorConsultation.mockReturnValueOnce(inFlight.promise);
    render(<DoctorConsultationScreen child={testChild} onClose={vi.fn()} onRecordVisit={vi.fn()} />);

    fireEvent.click(screen.getByRole("button", { name: "Buat Pratinjau" }));
    expect(screen.getByRole("button", { name: "Membuat pratinjau..." })).toBeDisabled();
    fireEvent.click(screen.getByLabelText("Riwayat Obat")); // edit SELAGI request pertama masih terbang

    inFlight.resolve(makeReport({ sensitive_sections_included: [] })); // laporan ini TIDAK mencerminkan "Riwayat Obat" yang baru dicentang
    await waitFor(() => expect(screen.getByText(/23 Agu 2026/)).toBeInTheDocument());

    expect(screen.queryByRole("button", { name: "Unduh PDF" })).not.toBeInTheDocument();
    expect(screen.getByText("Pilihan laporan berubah. Buat pratinjau ulang sebelum mengunduh PDF.")).toBeInTheDocument();
  });
});

// --------------------------------------------------------------------------
// Regression: Viewer initially receives optimistic write capabilities
// (bug review Agustus 2026) -- privileged controls (Questions/Note/
// Download PDF/Record Visit) must default to LEAST PRIVILEGE (hidden)
// until a successful, capability-bearing preview response says otherwise.
// --------------------------------------------------------------------------
describe("DoctorConsultationScreen — least-privilege capability defaults", () => {
  it("shows no privileged controls before any preview has been made", () => {
    render(<DoctorConsultationScreen child={testChild} onClose={vi.fn()} onRecordVisit={vi.fn()} />);
    expect(screen.queryByLabelText(/Pertanyaan untuk dokter/)).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/Catatan tambahan/)).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Unduh PDF" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Catat Hasil Kunjungan" })).not.toBeInTheDocument();
  });

  it("keeps privileged controls absent after a successful viewer (preview-only) response", async () => {
    apiMock.previewDoctorConsultation.mockResolvedValue(
      makeReport({ capabilities: { can_preview: true, can_export: false, can_add_private_notes: false, can_record_visit: false } }),
    );
    render(<DoctorConsultationScreen child={testChild} onClose={vi.fn()} onRecordVisit={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "Buat Pratinjau" }));
    await screen.findByText(/23 Agu 2026/);

    expect(screen.getByText(/Peran Anda hanya bisa melihat pratinjau/)).toBeInTheDocument();
    expect(screen.queryByLabelText(/Pertanyaan untuk dokter/)).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Unduh PDF" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Catat Hasil Kunjungan" })).not.toBeInTheDocument();
  });

  it("handles a backend 403 (crafted viewer attempt with private text) without granting or preserving privileges", async () => {
    // Simulasi: sesuatu (bug lain, devtools, dst) sempat memaksa
    // permintaan preview membawa teks privat padahal peran ini
    // sebenarnya Viewer -- backend WAJIB menolak (403), dan frontend
    // WAJIB tetap nggak pernah nampilin kontrol privileged apa pun
    // gara-gara percobaan ini.
    apiMock.previewDoctorConsultation.mockRejectedValue(
      Object.assign(new Error("Peran Anda tidak bisa menambahkan pertanyaan/catatan tambahan."), { status: 403 }),
    );
    render(<DoctorConsultationScreen child={testChild} onClose={vi.fn()} onRecordVisit={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "Buat Pratinjau" }));

    expect(await screen.findByText("Peran Anda tidak bisa menambahkan pertanyaan/catatan tambahan.")).toBeInTheDocument();
    expect(screen.queryByLabelText(/Pertanyaan untuk dokter/)).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Unduh PDF" })).not.toBeInTheDocument();
  });

  it("does not show privileged controls after any failed preview", async () => {
    apiMock.previewDoctorConsultation.mockRejectedValue(new Error("Gagal memuat"));
    render(<DoctorConsultationScreen child={testChild} onClose={vi.fn()} onRecordVisit={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "Buat Pratinjau" }));

    await screen.findByText("Gagal memuat");
    expect(screen.queryByLabelText(/Pertanyaan untuk dokter/)).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Unduh PDF" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Catat Hasil Kunjungan" })).not.toBeInTheDocument();
  });

  it("reveals questions/note/export/record-visit controls after an owner/editor capability-bearing preview", async () => {
    apiMock.previewDoctorConsultation.mockResolvedValue(makeReport());
    render(<DoctorConsultationScreen child={testChild} onClose={vi.fn()} onRecordVisit={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "Buat Pratinjau" }));

    expect(await screen.findByLabelText(/Pertanyaan untuk dokter/)).toBeInTheDocument();
    expect(screen.getByLabelText(/Catatan tambahan/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Unduh PDF" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Catat Hasil Kunjungan" })).toBeInTheDocument();
  });

  it("does not downgrade a previously-granted owner capability just because a later preview attempt failed", async () => {
    apiMock.previewDoctorConsultation.mockResolvedValueOnce(makeReport());
    render(<DoctorConsultationScreen child={testChild} onClose={vi.fn()} onRecordVisit={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "Buat Pratinjau" }));
    await screen.findByRole("button", { name: "Unduh PDF" });

    apiMock.previewDoctorConsultation.mockRejectedValueOnce(new Error("Server sibuk"));
    fireEvent.click(screen.getByLabelText("Riwayat Obat")); // invalidate -> requires re-preview
    fireEvent.click(screen.getByRole("button", { name: "Buat Pratinjau" }));
    await screen.findByText("Server sibuk");

    // Retry berhasil lagi -- kapabilitas Owner yang SEBELUMNYA sudah
    // diketahui TETAP `true` (activeSnapshot lama nggak pernah dihapus
    // gara-gara satu percobaan gagal), TIDAK "naik" jadi lebih longgar
    // ataupun "turun" jadi lebih ketat secara nggak konsisten.
    apiMock.previewDoctorConsultation.mockResolvedValueOnce(makeReport());
    fireEvent.click(screen.getByRole("button", { name: "Coba lagi" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Unduh PDF" })).toBeInTheDocument());
  });

  it("clears capabilities and snapshot immediately when switching from an owner child to a viewer child", async () => {
    apiMock.previewDoctorConsultation.mockResolvedValue(makeReport()); // owner: full capabilities
    const { rerender } = render(<DoctorConsultationScreen child={testChild} onClose={vi.fn()} onRecordVisit={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "Buat Pratinjau" }));
    await screen.findByRole("button", { name: "Unduh PDF" });

    const viewerChild = { id: 77, name: "Anak Dua", nickname: "Kakak" };
    rerender(<DoctorConsultationScreen child={viewerChild} onClose={vi.fn()} onRecordVisit={vi.fn()} />);

    // Snapshot/kapabilitas Owner anak SEBELUMNYA TIDAK PERNAH "bocor" ke
    // tampilan anak yang baru -- kembali ke least-privilege sampai anak
    // baru ini beneran di-preview.
    expect(screen.queryByRole("button", { name: "Unduh PDF" })).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/Pertanyaan untuk dokter/)).not.toBeInTheDocument();
    expect(screen.queryByText(/23 Agu 2026/)).not.toBeInTheDocument();
  });
});

// --------------------------------------------------------------------------
// Regression: pratinjau JSON mentah (bug review Agustus 2026) --
// `JSON.stringify(section, ...)` DIHAPUS TOTAL, diganti
// components/consultation/ConsultationPreview.jsx.
// --------------------------------------------------------------------------
describe("DoctorConsultationScreen — human-readable preview (no raw JSON)", () => {
  it("never renders a <pre> element or raw technical field names through the full screen flow", async () => {
    apiMock.previewDoctorConsultation.mockResolvedValue(makeReport({
      sections: {
        child_summary: {
          display_name: "Dedek", birth_date: "2026-01-01", gender: "L", age_as_of_report_end: "7 bulan",
          medication_event_count_in_period: 2, doctor_visit_count_in_period: 1,
          illness_record_count_in_period: 0, temperature_record_count_in_period: 3,
        },
        feeding: {
          total_events: 8, avg_events_per_day: 1.1, by_type: { asi_langsung: 5, asi_perah: 2, sufor: 1, mpasi: 0 },
          total_volume_ml: 300, events_with_volume: 6, avg_volume_ml_per_event: 50,
        },
      },
    }));
    const { container } = render(<DoctorConsultationScreen child={testChild} onClose={vi.fn()} onRecordVisit={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "Buat Pratinjau" }));
    await screen.findByText(/23 Agu 2026/);

    expect(container.querySelector("pre")).toBeNull();
    const text = container.textContent;
    for (const technicalKey of [
      "total_events", "avg_events_per_day", "events_with_volume",
      "total_count_in_period", "latest_temperature_celsius", '"truncated":',
    ]) {
      expect(text).not.toContain(technicalKey);
    }
  });

  it("does not depend on a wide <table> element (mobile-friendly stacked cards instead)", async () => {
    apiMock.previewDoctorConsultation.mockResolvedValue(makeReport({
      included_sections: ["medication"],
      sensitive_sections_included: ["medication"],
      sections: {
        medication: {
          entries: [{ medication_name: "Paracetamol", dosage: "1 sdt", timestamp: "2026-08-20T08:00:00+07:00" }],
          total_count_in_period: 1, truncated: false,
        },
      },
    }));
    const { container } = render(<DoctorConsultationScreen child={testChild} onClose={vi.fn()} onRecordVisit={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "Buat Pratinjau" }));
    await screen.findByText("Paracetamol");

    expect(container.querySelector("table")).toBeNull();
  });
});

// --------------------------------------------------------------------------
// Doctor Consultation Snapshot-Safe PDF Export (bug review Agustus 2026)
// -- lapis KEDUA, server-side, di ATAS `activeSnapshot` lokal yang sudah
// ada. Lihat backend/docs/DOCTOR_CONSULTATION.md bagian "Konsistensi
// snapshot preview -> PDF (token bertanda tangan)". Sebagian besar
// requirement (edit periode/section/pertanyaan/catatan/ganti anak
// membatalkan snapshot, konfirmasi privasi pakai daftar section
// sensitif snapshot aktif, klik ganda cuma 1 request) SUDAH dibuktikan
// oleh describe block "preview/PDF snapshot consistency" &
// "least-privilege capability defaults" di atas -- TIDAK diulang di
// sini, cuma perilaku BARU (token) yang ditambahkan.
// --------------------------------------------------------------------------
describe("DoctorConsultationScreen — snapshot-safe PDF export (signed token)", () => {
  it("stores {payload, report, snapshotToken} atomically and sends the exact token + payload to the PDF endpoint", async () => {
    apiMock.previewDoctorConsultation.mockResolvedValue(makeReport({ snapshot_token: "tok-abc-123" }));
    apiMock.downloadAuthenticatedPost.mockResolvedValue();
    render(<DoctorConsultationScreen child={testChild} onClose={vi.fn()} onRecordVisit={vi.fn()} />);

    fireEvent.click(screen.getByRole("button", { name: "Buat Pratinjau" }));
    await waitFor(() => expect(apiMock.previewDoctorConsultation).toHaveBeenCalled());
    const [, sentPayload] = apiMock.previewDoctorConsultation.mock.calls[0];

    fireEvent.click(await screen.findByRole("button", { name: "Unduh PDF" }));
    await waitFor(() => expect(apiMock.downloadAuthenticatedPost).toHaveBeenCalledTimes(1));
    const [url, body] = apiMock.downloadAuthenticatedPost.mock.calls[0];
    expect(url).toBe("http://x/api/children/10/doctor-consultation/pdf");
    expect(body).toEqual({ ...sentPayload, snapshot_token: "tok-abc-123" });
  });

  it("disables the PDF button when the preview response is missing a snapshot token", async () => {
    const { snapshot_token, ...reportWithoutToken } = makeReport();
    apiMock.previewDoctorConsultation.mockResolvedValue(reportWithoutToken);
    render(<DoctorConsultationScreen child={testChild} onClose={vi.fn()} onRecordVisit={vi.fn()} />);

    fireEvent.click(screen.getByRole("button", { name: "Buat Pratinjau" }));
    expect(await screen.findByRole("button", { name: "Unduh PDF" })).toBeDisabled();
  });

  it("on a 409 stale response: keeps the old preview visible, disables download, and shows 'Buat pratinjau ulang'", async () => {
    apiMock.previewDoctorConsultation.mockResolvedValue(makeReport());
    apiMock.downloadAuthenticatedPost.mockRejectedValue(
      apiError(409, "Data laporan konsultasi berubah sejak pratinjau dibuat. Buat pratinjau ulang sebelum mengunduh PDF."),
    );
    render(<DoctorConsultationScreen child={testChild} onClose={vi.fn()} onRecordVisit={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "Buat Pratinjau" }));
    fireEvent.click(await screen.findByRole("button", { name: "Unduh PDF" }));

    expect(await screen.findByText(
      "Data laporan konsultasi berubah sejak pratinjau dibuat. Buat pratinjau ulang sebelum mengunduh PDF.",
    )).toBeInTheDocument();
    // Preview yang SUDAH ditampilkan TETAP kelihatan (buat perbandingan) -- TIDAK dibuang.
    expect(screen.getByText(/23 Agu 2026/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Unduh PDF" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Buat pratinjau ulang" })).toBeInTheDocument();
  });

  it("reloading the preview after a 409 replaces report, payload, and token atomically, clearing the stale state", async () => {
    apiMock.previewDoctorConsultation.mockResolvedValueOnce(makeReport({ snapshot_token: "tok-old" }));
    apiMock.downloadAuthenticatedPost.mockRejectedValueOnce(apiError(409, "basi"));
    render(<DoctorConsultationScreen child={testChild} onClose={vi.fn()} onRecordVisit={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "Buat Pratinjau" }));
    fireEvent.click(await screen.findByRole("button", { name: "Unduh PDF" }));
    expect(await screen.findByText("basi")).toBeInTheDocument();

    apiMock.previewDoctorConsultation.mockResolvedValueOnce(makeReport({ snapshot_token: "tok-new" }));
    fireEvent.click(screen.getByRole("button", { name: "Buat pratinjau ulang" }));
    await waitFor(() => expect(apiMock.previewDoctorConsultation).toHaveBeenCalledTimes(2));
    expect(screen.queryByText("basi")).not.toBeInTheDocument();
    const downloadButton = await screen.findByRole("button", { name: "Unduh PDF" });
    expect(downloadButton).not.toBeDisabled();

    apiMock.downloadAuthenticatedPost.mockResolvedValueOnce();
    fireEvent.click(downloadButton);
    await waitFor(() => expect(apiMock.downloadAuthenticatedPost).toHaveBeenCalledTimes(2));
    const [, secondBody] = apiMock.downloadAuthenticatedPost.mock.calls[1];
    expect(secondBody.snapshot_token).toBe("tok-new");
  });

  it("treats an expired/invalid-token (400) response the same way as a 409 -- requires a fresh preview", async () => {
    apiMock.previewDoctorConsultation.mockResolvedValue(makeReport());
    apiMock.downloadAuthenticatedPost.mockRejectedValue(
      apiError(400, "Token pratinjau tidak valid atau sudah kedaluwarsa. Buat pratinjau ulang sebelum mengunduh PDF."),
    );
    render(<DoctorConsultationScreen child={testChild} onClose={vi.fn()} onRecordVisit={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "Buat Pratinjau" }));
    fireEvent.click(await screen.findByRole("button", { name: "Unduh PDF" }));

    expect(await screen.findByText(
      "Token pratinjau tidak valid atau sudah kedaluwarsa. Buat pratinjau ulang sebelum mengunduh PDF.",
    )).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Unduh PDF" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Buat pratinjau ulang" })).toBeInTheDocument();
  });

  it("out-of-order preview responses cannot replace the latest snapshot (a slow response for a superseded child arrives late)", async () => {
    const first = deferred();
    apiMock.previewDoctorConsultation.mockReturnValueOnce(first.promise);
    const { rerender } = render(<DoctorConsultationScreen child={testChild} onClose={vi.fn()} onRecordVisit={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "Buat Pratinjau" }));
    expect(screen.getByRole("button", { name: "Membuat pratinjau..." })).toBeDisabled();

    // Anak berganti SELAGI request pertama masih terbang -- requestSeqRef
    // dinaikkan (lihat useEffect child.id komponen), request lama itu
    // otomatis "basi" begitu tiba.
    const otherChild = { ...testChild, id: 99 };
    apiMock.previewDoctorConsultation.mockResolvedValueOnce(makeReport({ snapshot_token: "tok-for-child-99" }));
    rerender(<DoctorConsultationScreen child={otherChild} onClose={vi.fn()} onRecordVisit={vi.fn()} />);

    // Request LAMA (anak 10) akhirnya selesai -- HARUS diabaikan total.
    first.resolve(makeReport({ snapshot_token: "tok-for-child-10-stale", child_display_name: "Dedek Lama Basi" }));
    await new Promise((r) => setTimeout(r, 0));

    expect(screen.queryByText("Dedek Lama Basi")).not.toBeInTheDocument();
  });

  it("does not update state or log an error after unmounting while a preview request is in flight", async () => {
    const errorSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    const { promise, resolve } = deferred();
    apiMock.previewDoctorConsultation.mockReturnValue(promise);
    const { unmount } = render(<DoctorConsultationScreen child={testChild} onClose={vi.fn()} onRecordVisit={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "Buat Pratinjau" }));

    unmount();
    resolve(makeReport());
    await new Promise((r) => setTimeout(r, 0));

    expect(errorSpy).not.toHaveBeenCalled();
  });

  it("never writes the snapshot token, payload, or report to any browser storage (also proves nothing is queued offline, since this app's offline queue itself lives in localStorage)", async () => {
    const setItemSpy = vi.spyOn(Storage.prototype, "setItem");
    apiMock.previewDoctorConsultation.mockResolvedValue(makeReport({ snapshot_token: "tok-secret" }));
    apiMock.downloadAuthenticatedPost.mockResolvedValue();
    render(<DoctorConsultationScreen child={testChild} onClose={vi.fn()} onRecordVisit={vi.fn()} />);

    fireEvent.click(screen.getByRole("button", { name: "Buat Pratinjau" }));
    fireEvent.click(await screen.findByRole("button", { name: "Unduh PDF" }));
    await waitFor(() => expect(apiMock.downloadAuthenticatedPost).toHaveBeenCalled());

    expect(setItemSpy).not.toHaveBeenCalled();
  });
});
