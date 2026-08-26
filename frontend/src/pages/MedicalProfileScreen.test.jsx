import { StrictMode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor, fireEvent, within } from "@testing-library/react";
import MedicalProfileScreen from "./MedicalProfileScreen";

function deferred() {
  let resolve, reject;
  const promise = new Promise((res, rej) => { resolve = res; reject = rej; });
  return { promise, resolve, reject };
}

const { apiMock } = vi.hoisted(() => ({
  apiMock: {
    getMedicalProfile: vi.fn(),
    updateMedicalProfile: vi.fn(),
    reviewMedicalProfile: vi.fn(),
    previewEmergencyCard: vi.fn(),
    emergencyCardPdfUrl: vi.fn((childId) => `http://x/api/children/${childId}/emergency-card/pdf`),
    downloadAuthenticatedPost: vi.fn(),
  },
}));

vi.mock("../api/client", async (importOriginal) => {
  const actual = await importOriginal();
  return { ...actual, api: apiMock };
});

const { ApiError } = await import("../api/client");

const ownerChild = { id: 10, name: "Anak Satu", nickname: "Dedek", role: "owner" };
const editorChild = { id: 10, name: "Anak Satu", nickname: "Dedek", role: "editor" };
const viewerChild = { id: 11, name: "Anak Dua", nickname: "Kaka", role: "viewer" };
const CURRENT_USER_ID = 1;

function setOnline(value) {
  Object.defineProperty(window.navigator, "onLine", { value, configurable: true });
}

const FULL_CAPS = {
  can_view_medical_profile: true, can_edit_medical_profile: true,
  can_preview_emergency_card: true, can_export_emergency_card: true,
};

function makeProfile(overrides = {}) {
  return {
    id: 1, child_id: 10, blood_type: null, allergies: [], conditions: [],
    primary_doctor_name: null, primary_clinic_name: null, primary_clinic_phone: null,
    emergency_contact_name: null, emergency_contact_relationship: null, emergency_contact_phone: null,
    emergency_instructions: null, last_reviewed_at: null, last_reviewed_by_user_id: null,
    last_reviewed_by_name: null, created_at: "2026-08-01T00:00:00Z", updated_at: "2026-08-01T00:00:00Z",
    ...overrides,
  };
}

function makeEmergencyCard(overrides = {}) {
  return {
    child_display_name: "Dedek", birth_date: "1 Jan 2026", age_now: "7 bulan",
    blood_type_label: "Belum dicatat", allergies: [], conditions: [], regular_medications: [],
    primary_doctor_name: null, primary_clinic_name: null, primary_clinic_phone: null,
    emergency_contact_name: null, emergency_contact_relationship: null, emergency_contact_phone: null,
    emergency_instructions: null, last_reviewed_at: null, last_reviewed_by_name: null,
    disclaimer: "Kartu ini dibuat dari data yang dimasukkan caregiver, bukan diagnosis medis.",
    privacy_note: "Data ini sangat pribadi — jangan sebarkan tanpa alasan yang jelas.",
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
  apiMock.emergencyCardPdfUrl.mockImplementation((childId) => `http://x/api/children/${childId}/emergency-card/pdf`);
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("MedicalProfileScreen — least-privilege initial state", () => {
  it("starts in a loading state with no action buttons rendered before the server confirms capabilities", () => {
    apiMock.getMedicalProfile.mockReturnValue(deferred().promise);
    render(<MedicalProfileScreen child={ownerChild} currentUserId={CURRENT_USER_ID} onClose={vi.fn()} />);

    expect(screen.getByText("Memuat profil medis...")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Ubah Profil" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "🚑 Lihat Kartu Darurat" })).not.toBeInTheDocument();
  });

  it("shows the sensitive-data notice regardless of load outcome", () => {
    apiMock.getMedicalProfile.mockReturnValue(deferred().promise);
    render(<MedicalProfileScreen child={ownerChild} currentUserId={CURRENT_USER_ID} onClose={vi.fn()} />);
    expect(screen.getByText(/berisi data medis dan kontak yang sangat pribadi/)).toBeInTheDocument();
  });
});

describe("MedicalProfileScreen — Owner/Editor workflow", () => {
  it("loads and shows the profile summary with human-readable missing-data states", async () => {
    apiMock.getMedicalProfile.mockResolvedValue({ profile: makeProfile(), capabilities: FULL_CAPS });
    render(<MedicalProfileScreen child={ownerChild} currentUserId={CURRENT_USER_ID} onClose={vi.fn()} />);

    expect(await screen.findByText("Belum dicatat")).toBeInTheDocument();
    expect(screen.getByText("Belum ada alergi tercatat.")).toBeInTheDocument();
    expect(screen.getByText("Belum ada kondisi medis tercatat.")).toBeInTheDocument();
    expect(screen.getByText("Dokter: Belum diisi")).toBeInTheDocument();
    expect(screen.getByText("Belum pernah ditandai diperiksa ulang.")).toBeInTheDocument();
  });

  it("renders allergies and conditions from the loaded profile", async () => {
    apiMock.getMedicalProfile.mockResolvedValue({
      profile: makeProfile({
        allergies: [{ type: "drug", allergen: "Amoxicillin", reaction: "Ruam", severity: "severe", confirmed_by_professional: true }],
        conditions: [{ condition_name: "Asma", diagnosed_year: 2024, status: "active", note: null }],
      }),
      capabilities: FULL_CAPS,
    });
    render(<MedicalProfileScreen child={ownerChild} currentUserId={CURRENT_USER_ID} onClose={vi.fn()} />);

    expect(await screen.findByText(/Amoxicillin/)).toBeInTheDocument();
    expect(screen.getByText(/Berat/)).toBeInTheDocument();
    expect(screen.getByText("Asma (Aktif)")).toBeInTheDocument();
  });

  it("lets an Editor open edit mode, change fields, and save via PUT", async () => {
    apiMock.getMedicalProfile.mockResolvedValue({ profile: makeProfile(), capabilities: FULL_CAPS });
    apiMock.updateMedicalProfile.mockResolvedValue({
      profile: makeProfile({ blood_type: "O+", primary_doctor_name: "dr. Sari" }),
      capabilities: FULL_CAPS,
    });
    render(<MedicalProfileScreen child={editorChild} currentUserId={CURRENT_USER_ID} onClose={vi.fn()} />);

    fireEvent.click(await screen.findByRole("button", { name: "Ubah Profil" }));
    fireEvent.change(screen.getByLabelText("Golongan Darah"), { target: { value: "O+" } });
    fireEvent.change(screen.getByPlaceholderText("Nama dokter (opsional)"), { target: { value: "dr. Sari" } });
    fireEvent.click(screen.getByRole("button", { name: "Simpan Profil" }));

    await waitFor(() => expect(apiMock.updateMedicalProfile).toHaveBeenCalledWith(
      10, expect.objectContaining({ blood_type: "O+", primary_doctor_name: "dr. Sari" }),
    ));
    expect(await screen.findByText("O+")).toBeInTheDocument();
    expect(screen.getByText("Dokter: dr. Sari")).toBeInTheDocument();
  });

  it("marks the profile as reviewed via the dedicated review action", async () => {
    apiMock.getMedicalProfile.mockResolvedValue({ profile: makeProfile(), capabilities: FULL_CAPS });
    apiMock.reviewMedicalProfile.mockResolvedValue({
      profile: makeProfile({ last_reviewed_at: "2026-08-24T09:00:00+07:00", last_reviewed_by_name: "Ibu Dedek" }),
    });
    render(<MedicalProfileScreen child={ownerChild} currentUserId={CURRENT_USER_ID} onClose={vi.fn()} />);

    fireEvent.click(await screen.findByRole("button", { name: "Tandai sudah diperiksa ulang" }));

    await waitFor(() => expect(apiMock.reviewMedicalProfile).toHaveBeenCalledWith(10));
    expect(await screen.findByText(/Terakhir diperiksa ulang.*oleh Ibu Dedek/)).toBeInTheDocument();
  });

  it("shows a save error without a raw stack trace and keeps the form open", async () => {
    apiMock.getMedicalProfile.mockResolvedValue({ profile: makeProfile(), capabilities: FULL_CAPS });
    apiMock.updateMedicalProfile.mockRejectedValue(new Error("Data tidak valid."));
    render(<MedicalProfileScreen child={ownerChild} currentUserId={CURRENT_USER_ID} onClose={vi.fn()} />);

    fireEvent.click(await screen.findByRole("button", { name: "Ubah Profil" }));
    fireEvent.click(screen.getByRole("button", { name: "Simpan Profil" }));

    expect(await screen.findByText("Data tidak valid.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Simpan Profil" })).toBeInTheDocument();
  });
});

describe("MedicalProfileScreen — structured allergy & condition editors", () => {
  async function openEditMode() {
    apiMock.getMedicalProfile.mockResolvedValue({ profile: makeProfile(), capabilities: FULL_CAPS });
    render(<MedicalProfileScreen child={ownerChild} currentUserId={CURRENT_USER_ID} onClose={vi.fn()} />);
    fireEvent.click(await screen.findByRole("button", { name: "Ubah Profil" }));
  }

  it("adds and removes an allergy row", async () => {
    await openEditMode();
    expect(screen.getByText("Belum ada alergi ditambahkan.")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "+ Tambah alergi" }));
    expect(screen.getByLabelText("Nama alergen ke-1")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Nama alergen ke-1"), { target: { value: "Kacang" } });
    expect(screen.getByLabelText("Nama alergen ke-1")).toHaveValue("Kacang");

    fireEvent.click(screen.getByRole("button", { name: "Hapus alergi ini" }));
    expect(screen.getByText("Belum ada alergi ditambahkan.")).toBeInTheDocument();
  });

  it("adds and removes a condition row", async () => {
    await openEditMode();
    expect(screen.getByText("Belum ada kondisi medis ditambahkan.")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "+ Tambah kondisi medis" }));
    fireEvent.change(screen.getByLabelText("Nama kondisi medis ke-1"), { target: { value: "Asma" } });
    expect(screen.getByLabelText("Nama kondisi medis ke-1")).toHaveValue("Asma");

    fireEvent.click(screen.getByRole("button", { name: "Hapus kondisi ini" }));
    expect(screen.getByText("Belum ada kondisi medis ditambahkan.")).toBeInTheDocument();
  });

  it("submits structured allergy/condition entries as part of the PUT payload", async () => {
    apiMock.updateMedicalProfile.mockResolvedValue({ profile: makeProfile(), capabilities: FULL_CAPS });
    await openEditMode();

    fireEvent.click(screen.getByRole("button", { name: "+ Tambah alergi" }));
    fireEvent.change(screen.getByLabelText("Nama alergen ke-1"), { target: { value: "Kacang" } });
    fireEvent.click(screen.getByRole("button", { name: "+ Tambah kondisi medis" }));
    fireEvent.change(screen.getByLabelText("Nama kondisi medis ke-1"), { target: { value: "Asma" } });
    fireEvent.click(screen.getByRole("button", { name: "Simpan Profil" }));

    await waitFor(() => expect(apiMock.updateMedicalProfile).toHaveBeenCalledWith(
      10,
      expect.objectContaining({
        allergies: [expect.objectContaining({ allergen: "Kacang", type: "drug" })],
        conditions: [expect.objectContaining({ condition_name: "Asma" })],
      }),
    ));
  });
});

describe("MedicalProfileScreen — Viewer forbidden state", () => {
  it("shows a uniform forbidden state and never exposes edit/preview controls", async () => {
    apiMock.getMedicalProfile.mockRejectedValue(
      new ApiError({ kind: "forbidden", status: 403, message: "Anda tidak punya akses ke profil medis anak ini." }),
    );
    render(<MedicalProfileScreen child={viewerChild} currentUserId={CURRENT_USER_ID} onClose={vi.fn()} />);

    expect(await screen.findByText("Tidak punya akses")).toBeInTheDocument();
    expect(screen.getByText("Anda tidak punya akses ke profil medis anak ini.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Ubah Profil" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "🚑 Lihat Kartu Darurat" })).not.toBeInTheDocument();
    expect(apiMock.getMedicalProfile).toHaveBeenCalledTimes(1);
  });
});

describe("MedicalProfileScreen — online-only behavior", () => {
  it("shows an offline message and never calls the API while offline", () => {
    setOnline(false);
    render(<MedicalProfileScreen child={ownerChild} currentUserId={CURRENT_USER_ID} onClose={vi.fn()} />);

    expect(screen.getByText("Butuh koneksi internet")).toBeInTheDocument();
    expect(apiMock.getMedicalProfile).not.toHaveBeenCalled();
  });

  it("never writes anything to localStorage during load, edit, save, or review", async () => {
    const setItemSpy = vi.spyOn(Storage.prototype, "setItem");
    apiMock.getMedicalProfile.mockResolvedValue({ profile: makeProfile(), capabilities: FULL_CAPS });
    apiMock.updateMedicalProfile.mockResolvedValue({ profile: makeProfile(), capabilities: FULL_CAPS });
    render(<MedicalProfileScreen child={ownerChild} currentUserId={CURRENT_USER_ID} onClose={vi.fn()} />);

    fireEvent.click(await screen.findByRole("button", { name: "Ubah Profil" }));
    fireEvent.click(screen.getByRole("button", { name: "Simpan Profil" }));
    await waitFor(() => expect(apiMock.updateMedicalProfile).toHaveBeenCalled());

    expect(setItemSpy).not.toHaveBeenCalled();
  });
});

describe("MedicalProfileScreen — Emergency Card preview & PDF snapshot consistency", () => {
  it("sends exactly the snapshot_token returned with the active preview (no empty-body request)", async () => {
    apiMock.getMedicalProfile.mockResolvedValue({ profile: makeProfile(), capabilities: FULL_CAPS });
    apiMock.previewEmergencyCard.mockResolvedValue(makeEmergencyCard({ snapshot_token: "tok-abc-123" }));
    apiMock.downloadAuthenticatedPost.mockResolvedValue();
    vi.spyOn(window, "confirm").mockReturnValue(true);

    render(<MedicalProfileScreen child={ownerChild} currentUserId={CURRENT_USER_ID} onClose={vi.fn()} />);
    fireEvent.click(await screen.findByRole("button", { name: "🚑 Lihat Kartu Darurat" }));

    expect(await screen.findByText("Dedek")).toBeInTheDocument();
    const downloadButton = await screen.findByRole("button", { name: "Unduh PDF" });
    expect(downloadButton).not.toBeDisabled();
    fireEvent.click(downloadButton);

    await waitFor(() => expect(apiMock.downloadAuthenticatedPost).toHaveBeenCalledTimes(1));
    // Body sekarang WAJIB berisi snapshot_token yang PERSIS sama dari preview
    // -- body kosong `{}` yang dipakai SEBELUM perbaikan defect ini TIDAK PERNAH dikirim lagi.
    expect(apiMock.downloadAuthenticatedPost).toHaveBeenCalledWith(
      "http://x/api/children/10/emergency-card/pdf",
      { snapshot_token: "tok-abc-123" },
      expect.stringContaining("kartu-darurat"),
    );
    const [, sentBody] = apiMock.downloadAuthenticatedPost.mock.calls[0];
    expect(sentBody).not.toEqual({});
    expect(window.confirm).toHaveBeenCalled();
  });

  it("disables download when the preview response is missing a snapshot token", async () => {
    apiMock.getMedicalProfile.mockResolvedValue({ profile: makeProfile(), capabilities: FULL_CAPS });
    const { snapshot_token, ...cardWithoutToken } = makeEmergencyCard();
    apiMock.previewEmergencyCard.mockResolvedValue(cardWithoutToken);

    render(<MedicalProfileScreen child={ownerChild} currentUserId={CURRENT_USER_ID} onClose={vi.fn()} />);
    fireEvent.click(await screen.findByRole("button", { name: "🚑 Lihat Kartu Darurat" }));

    expect(await screen.findByRole("button", { name: "Unduh PDF" })).toBeDisabled();
  });

  it("cancelling the privacy confirmation never triggers a download", async () => {
    apiMock.getMedicalProfile.mockResolvedValue({ profile: makeProfile(), capabilities: FULL_CAPS });
    apiMock.previewEmergencyCard.mockResolvedValue(makeEmergencyCard());
    vi.spyOn(window, "confirm").mockReturnValue(false);

    render(<MedicalProfileScreen child={ownerChild} currentUserId={CURRENT_USER_ID} onClose={vi.fn()} />);
    fireEvent.click(await screen.findByRole("button", { name: "🚑 Lihat Kartu Darurat" }));
    fireEvent.click(await screen.findByRole("button", { name: "Unduh PDF" }));

    expect(apiMock.downloadAuthenticatedPost).not.toHaveBeenCalled();
  });

  it("prevents a double-submit while a PDF download is already in flight", async () => {
    apiMock.getMedicalProfile.mockResolvedValue({ profile: makeProfile(), capabilities: FULL_CAPS });
    apiMock.previewEmergencyCard.mockResolvedValue(makeEmergencyCard());
    vi.spyOn(window, "confirm").mockReturnValue(true);
    const { promise, resolve } = deferred();
    apiMock.downloadAuthenticatedPost.mockReturnValue(promise);

    render(<MedicalProfileScreen child={ownerChild} currentUserId={CURRENT_USER_ID} onClose={vi.fn()} />);
    fireEvent.click(await screen.findByRole("button", { name: "🚑 Lihat Kartu Darurat" }));
    const downloadButton = await screen.findByRole("button", { name: "Unduh PDF" });
    fireEvent.click(downloadButton);
    await waitFor(() => expect(downloadButton).toBeDisabled());
    fireEvent.click(downloadButton);

    expect(apiMock.downloadAuthenticatedPost).toHaveBeenCalledTimes(1);
    resolve();
  });

  it("disables the PDF button and shows local-edit guidance once the profile is edited after the preview was taken", async () => {
    apiMock.getMedicalProfile.mockResolvedValue({ profile: makeProfile(), capabilities: FULL_CAPS });
    apiMock.previewEmergencyCard.mockResolvedValue(makeEmergencyCard());
    apiMock.updateMedicalProfile.mockResolvedValue({ profile: makeProfile({ blood_type: "O+" }), capabilities: FULL_CAPS });

    render(<MedicalProfileScreen child={ownerChild} currentUserId={CURRENT_USER_ID} onClose={vi.fn()} />);
    fireEvent.click(await screen.findByRole("button", { name: "🚑 Lihat Kartu Darurat" }));
    expect(await screen.findByRole("button", { name: "Unduh PDF" })).not.toBeDisabled();

    fireEvent.click(screen.getByRole("button", { name: "Ubah Profil" }));
    fireEvent.click(screen.getByRole("button", { name: "Simpan Profil" }));
    await waitFor(() => expect(apiMock.updateMedicalProfile).toHaveBeenCalled());

    expect(await screen.findByText(/Profil medis sudah diubah sejak pratinjau ini dibuat/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Unduh PDF" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Muat ulang pratinjau" })).toBeInTheDocument();
  });

  it("on a 409 stale response: keeps the preview visible, disables download, and shows the safe refresh guidance", async () => {
    apiMock.getMedicalProfile.mockResolvedValue({ profile: makeProfile(), capabilities: FULL_CAPS });
    apiMock.previewEmergencyCard.mockResolvedValue(makeEmergencyCard());
    apiMock.downloadAuthenticatedPost.mockRejectedValue(
      apiError(409, "Data Kartu Darurat berubah sejak pratinjau dibuat. Muat ulang pratinjau sebelum mengunduh PDF."),
    );
    vi.spyOn(window, "confirm").mockReturnValue(true);

    render(<MedicalProfileScreen child={ownerChild} currentUserId={CURRENT_USER_ID} onClose={vi.fn()} />);
    fireEvent.click(await screen.findByRole("button", { name: "🚑 Lihat Kartu Darurat" }));
    fireEvent.click(await screen.findByRole("button", { name: "Unduh PDF" }));

    expect(await screen.findByText(
      "Data Kartu Darurat berubah sejak pratinjau dibuat. Muat ulang pratinjau sebelum mengunduh PDF.",
    )).toBeInTheDocument();
    // Preview yang SUDAH ditampilkan TETAP kelihatan (buat perbandingan) -- TIDAK dibuang.
    const dialog = screen.getByRole("dialog");
    expect(within(dialog).getByText("Dedek")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Unduh PDF" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Muat ulang pratinjau" })).toBeInTheDocument();
  });

  it("reloading the preview after a 409 replaces both the report and the token atomically, clearing the stale state", async () => {
    apiMock.getMedicalProfile.mockResolvedValue({ profile: makeProfile(), capabilities: FULL_CAPS });
    apiMock.previewEmergencyCard.mockResolvedValueOnce(makeEmergencyCard({ snapshot_token: "tok-old" }));
    apiMock.downloadAuthenticatedPost.mockRejectedValueOnce(apiError(409, "basi"));
    vi.spyOn(window, "confirm").mockReturnValue(true);

    render(<MedicalProfileScreen child={ownerChild} currentUserId={CURRENT_USER_ID} onClose={vi.fn()} />);
    fireEvent.click(await screen.findByRole("button", { name: "🚑 Lihat Kartu Darurat" }));
    fireEvent.click(await screen.findByRole("button", { name: "Unduh PDF" }));
    expect(await screen.findByText("basi")).toBeInTheDocument();

    apiMock.previewEmergencyCard.mockResolvedValueOnce(
      makeEmergencyCard({ snapshot_token: "tok-new", primary_doctor_name: "dr. Baru" }),
    );
    fireEvent.click(screen.getByRole("button", { name: "Muat ulang pratinjau" }));

    expect(await screen.findByText("Dokter: dr. Baru")).toBeInTheDocument();
    expect(screen.queryByText("basi")).not.toBeInTheDocument();
    const downloadButton = screen.getByRole("button", { name: "Unduh PDF" });
    expect(downloadButton).not.toBeDisabled();

    apiMock.downloadAuthenticatedPost.mockResolvedValueOnce();
    fireEvent.click(downloadButton);
    await waitFor(() => expect(apiMock.downloadAuthenticatedPost).toHaveBeenCalledTimes(2));
    expect(apiMock.downloadAuthenticatedPost).toHaveBeenLastCalledWith(
      expect.any(String), { snapshot_token: "tok-new" }, expect.any(String),
    );
  });

  it("an expired or invalid-token error (400) also requires a fresh preview, same as a 409", async () => {
    apiMock.getMedicalProfile.mockResolvedValue({ profile: makeProfile(), capabilities: FULL_CAPS });
    apiMock.previewEmergencyCard.mockResolvedValue(makeEmergencyCard());
    apiMock.downloadAuthenticatedPost.mockRejectedValue(
      apiError(400, "Token pratinjau tidak valid atau sudah kedaluwarsa. Muat ulang pratinjau Kartu Darurat."),
    );
    vi.spyOn(window, "confirm").mockReturnValue(true);

    render(<MedicalProfileScreen child={ownerChild} currentUserId={CURRENT_USER_ID} onClose={vi.fn()} />);
    fireEvent.click(await screen.findByRole("button", { name: "🚑 Lihat Kartu Darurat" }));
    fireEvent.click(await screen.findByRole("button", { name: "Unduh PDF" }));

    expect(await screen.findByText(
      "Token pratinjau tidak valid atau sudah kedaluwarsa. Muat ulang pratinjau Kartu Darurat.",
    )).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Unduh PDF" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Muat ulang pratinjau" })).toBeInTheDocument();
  });

  it("out-of-order preview responses cannot replace the newest snapshot", async () => {
    // React StrictMode dengan sengaja meng-invoke effect mount 2x (mount
    // -> cleanup -> mount lagi) -- ini cara STANDAR & andal buat memicu
    // 2 panggilan runPreview() yang beneran overlap dari 1 instance
    // komponen yang sama (skenario NYATA di React 18, bukan cuma
    // rekayasa test), buat membuktikan requestSeqRef beneran menolak
    // hasil dari request yang lebih AWAL dimulai, TERLEPAS urutan
    // SELESAI-nya (di sini yang belakangan dimulai SENGAJA di-resolve
    // duluan, yang lebih awal dimulai di-resolve BELAKANGAN -- kasus
    // out-of-order yang paling ketat).
    apiMock.getMedicalProfile.mockResolvedValue({ profile: makeProfile(), capabilities: FULL_CAPS });
    const first = deferred();
    const second = deferred();
    apiMock.previewEmergencyCard.mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise);

    render(
      <StrictMode>
        <MedicalProfileScreen child={ownerChild} currentUserId={CURRENT_USER_ID} onClose={vi.fn()} />
      </StrictMode>,
    );
    fireEvent.click(await screen.findByRole("button", { name: "🚑 Lihat Kartu Darurat" }));
    await waitFor(() => expect(apiMock.previewEmergencyCard).toHaveBeenCalledTimes(2));

    // Yang DIMULAI belakangan (request ke-2) selesai LEBIH DULU.
    second.resolve(makeEmergencyCard({ snapshot_token: "tok-second", primary_doctor_name: "dr. Kedua (terbaru)" }));
    expect(await screen.findByText("Dokter: dr. Kedua (terbaru)")).toBeInTheDocument();

    // Yang DIMULAI lebih awal (request ke-1, basi) baru selesai BELAKANGAN -- HARUS diabaikan.
    first.resolve(makeEmergencyCard({ snapshot_token: "tok-first-stale", primary_doctor_name: "dr. Pertama (basi)" }));
    await new Promise((r) => setTimeout(r, 0));
    expect(screen.queryByText("Dokter: dr. Pertama (basi)")).not.toBeInTheDocument();
    expect(screen.getByText("Dokter: dr. Kedua (terbaru)")).toBeInTheDocument();
  });

  it("shows a retryable error state when the preview fails, without a raw stack trace", async () => {
    apiMock.getMedicalProfile.mockResolvedValue({ profile: makeProfile(), capabilities: FULL_CAPS });
    apiMock.previewEmergencyCard.mockRejectedValueOnce(new Error("Gagal memuat pratinjau."))
      .mockResolvedValueOnce(makeEmergencyCard());

    render(<MedicalProfileScreen child={ownerChild} currentUserId={CURRENT_USER_ID} onClose={vi.fn()} />);
    fireEvent.click(await screen.findByRole("button", { name: "🚑 Lihat Kartu Darurat" }));

    expect(await screen.findByText("Gagal memuat pratinjau.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Coba lagi" }));
    expect(await screen.findByText("Dedek")).toBeInTheDocument();
  });

  it("never writes the snapshot token or card data to any browser storage", async () => {
    const setItemSpy = vi.spyOn(Storage.prototype, "setItem");
    apiMock.getMedicalProfile.mockResolvedValue({ profile: makeProfile(), capabilities: FULL_CAPS });
    apiMock.previewEmergencyCard.mockResolvedValue(makeEmergencyCard({ snapshot_token: "tok-secret" }));
    apiMock.downloadAuthenticatedPost.mockResolvedValue();
    vi.spyOn(window, "confirm").mockReturnValue(true);

    render(<MedicalProfileScreen child={ownerChild} currentUserId={CURRENT_USER_ID} onClose={vi.fn()} />);
    fireEvent.click(await screen.findByRole("button", { name: "🚑 Lihat Kartu Darurat" }));
    fireEvent.click(await screen.findByRole("button", { name: "Unduh PDF" }));
    await waitFor(() => expect(apiMock.downloadAuthenticatedPost).toHaveBeenCalled());

    expect(setItemSpy).not.toHaveBeenCalled();
  });

  it("never renders the download button when export capability is false", async () => {
    apiMock.getMedicalProfile.mockResolvedValue({
      profile: makeProfile(),
      capabilities: { ...FULL_CAPS, can_export_emergency_card: false },
    });
    apiMock.previewEmergencyCard.mockResolvedValue(makeEmergencyCard());

    render(<MedicalProfileScreen child={ownerChild} currentUserId={CURRENT_USER_ID} onClose={vi.fn()} />);
    fireEvent.click(await screen.findByRole("button", { name: "🚑 Lihat Kartu Darurat" }));

    expect(await screen.findByText("Dedek")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Unduh PDF" })).not.toBeInTheDocument();
  });
});

describe("MedicalProfileScreen — child switching & stale response protection", () => {
  it("clears the previous child's profile immediately on switch and ignores a late-arriving stale response", async () => {
    const first = deferred();
    apiMock.getMedicalProfile.mockReturnValueOnce(first.promise);
    const { rerender } = render(<MedicalProfileScreen child={ownerChild} currentUserId={CURRENT_USER_ID} onClose={vi.fn()} />);

    first.resolve({
      profile: makeProfile({ primary_doctor_name: "dr. Owner Punya Anak Satu" }),
      capabilities: FULL_CAPS,
    });
    expect(await screen.findByText("Dokter: dr. Owner Punya Anak Satu")).toBeInTheDocument();

    const second = deferred();
    apiMock.getMedicalProfile.mockReturnValueOnce(second.promise);
    rerender(<MedicalProfileScreen child={viewerChild} currentUserId={CURRENT_USER_ID} onClose={vi.fn()} />);

    // State is cleared synchronously on child switch, before the new fetch resolves.
    expect(screen.queryByText("Dokter: dr. Owner Punya Anak Satu")).not.toBeInTheDocument();
    expect(screen.getByText("Memuat profil medis...")).toBeInTheDocument();

    second.reject(new ApiError({ kind: "forbidden", status: 403, message: "Anda tidak punya akses ke profil medis anak ini." }));
    expect(await screen.findByText("Tidak punya akses")).toBeInTheDocument();
    expect(screen.queryByText("Dokter: dr. Owner Punya Anak Satu")).not.toBeInTheDocument();
  });

  it("discards a stale successful response that resolves after the child has already changed", async () => {
    const first = deferred();
    apiMock.getMedicalProfile.mockReturnValueOnce(first.promise);
    const { rerender } = render(<MedicalProfileScreen child={ownerChild} currentUserId={CURRENT_USER_ID} onClose={vi.fn()} />);

    apiMock.getMedicalProfile.mockResolvedValueOnce({
      profile: makeProfile({ child_id: 11, primary_doctor_name: "dr. Anak Dua" }),
      capabilities: FULL_CAPS,
    });
    rerender(<MedicalProfileScreen child={viewerChild} currentUserId={CURRENT_USER_ID} onClose={vi.fn()} />);
    expect(await screen.findByText("Dokter: dr. Anak Dua")).toBeInTheDocument();

    // The slow first request (for the old child) resolves after the switch — must not overwrite the new child's data.
    first.resolve({ profile: makeProfile({ primary_doctor_name: "dr. STALE Anak Satu" }), capabilities: FULL_CAPS });
    await new Promise((r) => setTimeout(r, 0));
    expect(screen.getByText("Dokter: dr. Anak Dua")).toBeInTheDocument();
    expect(screen.queryByText("Dokter: dr. STALE Anak Satu")).not.toBeInTheDocument();
  });
});

describe("MedicalProfileScreen — no raw technical data ever rendered", () => {
  it("never renders raw enum codes, null/undefined literals, or the internal profile id", async () => {
    apiMock.getMedicalProfile.mockResolvedValue({
      profile: makeProfile({
        id: 999,
        allergies: [{ type: "drug", allergen: "Amoxicillin", reaction: null, severity: null, confirmed_by_professional: false }],
      }),
      capabilities: FULL_CAPS,
    });
    const { container } = render(<MedicalProfileScreen child={ownerChild} currentUserId={CURRENT_USER_ID} onClose={vi.fn()} />);

    await screen.findByText(/Amoxicillin/);
    expect(container.textContent).not.toMatch(/\bundefined\b/);
    expect(container.textContent).not.toMatch(/\bnull\b/);
    expect(container.textContent).not.toMatch(/\b999\b/);
    expect(container.textContent).not.toContain("drug");
  });
});

describe("MedicalProfileScreen — error/retry & unmount safety", () => {
  it("shows a retryable error state on a generic load failure", async () => {
    apiMock.getMedicalProfile.mockRejectedValueOnce(new Error("Gagal memuat profil medis."))
      .mockResolvedValueOnce({ profile: makeProfile(), capabilities: FULL_CAPS });
    render(<MedicalProfileScreen child={ownerChild} currentUserId={CURRENT_USER_ID} onClose={vi.fn()} />);

    expect(await screen.findByText("Gagal memuat profil medis.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Coba lagi" }));
    expect(await screen.findByText("Belum dicatat")).toBeInTheDocument();
  });

  it("does not update state or log an error after unmounting while a request is in flight", async () => {
    const errorSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    const { promise, resolve } = deferred();
    apiMock.getMedicalProfile.mockReturnValue(promise);
    const { unmount } = render(<MedicalProfileScreen child={ownerChild} currentUserId={CURRENT_USER_ID} onClose={vi.fn()} />);

    unmount();
    resolve({ profile: makeProfile(), capabilities: FULL_CAPS });
    await new Promise((r) => setTimeout(r, 0));

    expect(errorSpy).not.toHaveBeenCalled();
  });
});
