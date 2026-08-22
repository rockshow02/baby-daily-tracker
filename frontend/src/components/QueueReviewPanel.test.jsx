import { describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import QueueReviewPanel from "./QueueReviewPanel";

function makeItem(overrides = {}) {
  return {
    id: 1,
    userId: 1,
    url: "/children/7/feeding-logs",
    body: JSON.stringify({ feed_type: "asi_langsung", duration_minutes: 10 }),
    status: "needs_review",
    reviewReason: "validation",
    lastError: "feed_type wajib diisi",
    queuedAt: "2026-01-01T10:00:00.000Z",
    ...overrides,
  };
}

function legacyMedicationItem(overrides = {}) {
  return makeItem({
    id: 2,
    url: "/children/42/medication-logs",
    body: JSON.stringify({ medication_name: "Paracetamol", dosage: "0.8 ml", notes: "demam tinggi" }),
    userId: undefined,
    ownerUnknown: true,
    reviewReason: "legacy_unknown_owner",
    lastError: null,
    ...overrides,
  });
}

const noop = () => {};

describe("QueueReviewPanel", () => {
  it("renders nothing when there is nothing to review", () => {
    const { container } = render(
      <QueueReviewPanel needsReviewItems={[]} legacyItems={[]} discardItem={noop} claimLegacyItem={noop} retryWithEdits={noop} />,
    );
    expect(container).toBeEmptyDOMElement();
  });

  // ---------- item 1: legacy record privacy before ownership verification ----------

  it("1. an unknown-owner legacy record does not reveal any payload field", () => {
    render(
      <QueueReviewPanel
        needsReviewItems={[]}
        legacyItems={[legacyMedicationItem()]}
        discardItem={noop}
        claimLegacyItem={vi.fn()}
        retryWithEdits={noop}
      />,
    );

    expect(screen.queryByText(/Paracetamol/)).not.toBeInTheDocument();
    expect(screen.queryByText(/0\.8 ml/)).not.toBeInTheDocument();
    expect(screen.queryByText(/demam tinggi/)).not.toBeInTheDocument();
  });

  it("2. medication name and dosage are absent before verification", () => {
    render(
      <QueueReviewPanel
        needsReviewItems={[]}
        legacyItems={[legacyMedicationItem()]}
        discardItem={noop}
        claimLegacyItem={vi.fn()}
        retryWithEdits={noop}
      />,
    );

    expect(screen.queryByText(/medication_name/)).not.toBeInTheDocument();
    expect(screen.queryByText(/dosage/)).not.toBeInTheDocument();
    expect(screen.queryByText(/Paracetamol/)).not.toBeInTheDocument();
  });

  it("3. the child id is absent before verification", () => {
    render(
      <QueueReviewPanel
        needsReviewItems={[]}
        legacyItems={[legacyMedicationItem()]}
        discardItem={noop}
        claimLegacyItem={vi.fn()}
        retryWithEdits={noop}
      />,
    );

    // childId (42) TIDAK boleh nongol di mana pun, termasuk pola "anak #42"
    // yang dulu ditampilin sebelum perbaikan privasi ini
    expect(screen.queryByText(/anak #42/)).not.toBeInTheDocument();
    expect(screen.queryByText("42")).not.toBeInTheDocument();
  });

  it("does not render the raw endpoint or request body anywhere", () => {
    render(
      <QueueReviewPanel
        needsReviewItems={[]}
        legacyItems={[legacyMedicationItem()]}
        discardItem={noop}
        claimLegacyItem={vi.fn()}
        retryWithEdits={noop}
      />,
    );

    expect(screen.queryByText(/medication-logs/)).not.toBeInTheDocument();
    expect(screen.queryByText(/\/children\/42/)).not.toBeInTheDocument();
  });

  it("4. a failed claim reveals no additional data — only a generic rejection reason", async () => {
    const claimLegacyItem = vi.fn().mockResolvedValue({ claimed: false, reason: "Kamu nggak punya akses ke anak ini." });
    render(
      <QueueReviewPanel
        needsReviewItems={[]}
        legacyItems={[legacyMedicationItem()]}
        discardItem={noop}
        claimLegacyItem={claimLegacyItem}
        retryWithEdits={noop}
      />,
    );

    fireEvent.click(screen.getByText("Klaim akun ini"));
    expect(await screen.findByText("Kamu nggak punya akses ke anak ini.")).toBeInTheDocument();

    expect(screen.queryByText(/Paracetamol/)).not.toBeInTheDocument();
    expect(screen.queryByText(/0\.8 ml/)).not.toBeInTheDocument();
    expect(screen.queryByText(/anak #42/)).not.toBeInTheDocument();
  });

  it("6. the summary becomes visible only once an item is no longer an unknown-owner legacy record", () => {
    // sebelum klaim: item ada di legacyItems -> nggak ada ringkasan sama sekali
    const { rerender } = render(
      <QueueReviewPanel
        needsReviewItems={[]}
        legacyItems={[legacyMedicationItem()]}
        discardItem={noop}
        claimLegacyItem={vi.fn()}
        retryWithEdits={noop}
      />,
    );
    expect(screen.queryByText(/Paracetamol/)).not.toBeInTheDocument();

    // sesudah klaim sukses: item pindah jadi needs-review biasa (kepemilikan
    // udah jelas) -> ringkasannya sekarang BOLEH kelihatan
    rerender(
      <QueueReviewPanel
        needsReviewItems={[
          makeItem({
            id: 2,
            url: "/children/42/medication-logs",
            body: JSON.stringify({ medication_name: "Paracetamol", dosage: "0.8 ml" }),
            reviewReason: "validation",
            lastError: "medication_name wajib diisi",
          }),
        ]}
        legacyItems={[]}
        discardItem={noop}
        claimLegacyItem={noop}
        retryWithEdits={noop}
      />,
    );
    expect(screen.getByText(/Paracetamol/)).toBeInTheDocument();
  });

  it("discarding a legacy record still requires explicit confirmation", () => {
    const discardItem = vi.fn();
    render(
      <QueueReviewPanel
        needsReviewItems={[]}
        legacyItems={[legacyMedicationItem()]}
        discardItem={discardItem}
        claimLegacyItem={vi.fn()}
        retryWithEdits={noop}
      />,
    );

    fireEvent.click(screen.getByText("Buang"));
    expect(discardItem).not.toHaveBeenCalled();
    fireEvent.click(screen.getByText("Yakin?").nextSibling);
    expect(discardItem).toHaveBeenCalledWith(2);
  });

  // ---------- item 3: proper per-type editable fields ----------

  it("feeding validation correction — select for feed_type, retry with corrected value", () => {
    const retryWithEdits = vi.fn();
    render(
      <QueueReviewPanel
        needsReviewItems={[makeItem({ body: JSON.stringify({ feed_type: "", duration_minutes: 10 }) })]}
        legacyItems={[]}
        discardItem={noop}
        claimLegacyItem={noop}
        retryWithEdits={retryWithEdits}
      />,
    );

    fireEvent.click(screen.getByText("Edit"));
    const feedTypeSelect = screen.getByLabelText(/Jenis/); // "Sisi" (breast_side) juga kosong, disambiguasi lewat label
    fireEvent.change(feedTypeSelect, { target: { value: "sufor" } });
    fireEvent.click(screen.getByText("Coba lagi"));

    expect(retryWithEdits).toHaveBeenCalledTimes(1);
    const [, body] = retryWithEdits.mock.calls[0];
    expect(JSON.parse(body)).toMatchObject({ feed_type: "sufor", duration_minutes: 10 });
  });

  it("blocks retry locally when a required field is left empty", () => {
    const retryWithEdits = vi.fn();
    render(
      <QueueReviewPanel
        needsReviewItems={[makeItem({ body: JSON.stringify({ feed_type: "", duration_minutes: 10 }) })]}
        legacyItems={[]}
        discardItem={noop}
        claimLegacyItem={noop}
        retryWithEdits={retryWithEdits}
      />,
    );

    fireEvent.click(screen.getByText("Edit"));
    fireEvent.click(screen.getByText("Coba lagi")); // feed_type masih kosong

    expect(retryWithEdits).not.toHaveBeenCalled();
    // pesan lokal spesifik ("Jenis wajib diisi.") — bukan cuma cocok
    // substring "wajib diisi" yang juga muncul di lastError bawaan item
    expect(screen.getByText("Jenis wajib diisi.")).toBeInTheDocument();
  });

  it("medication validation correction — text input for medication_name", () => {
    const retryWithEdits = vi.fn();
    render(
      <QueueReviewPanel
        needsReviewItems={[
          makeItem({
            url: "/children/7/medication-logs",
            body: JSON.stringify({ medication_name: "", dosage: "1 ml" }),
            lastError: "medication_name wajib diisi",
          }),
        ]}
        legacyItems={[]}
        discardItem={noop}
        claimLegacyItem={noop}
        retryWithEdits={retryWithEdits}
      />,
    );

    fireEvent.click(screen.getByText("Edit"));
    const nameInput = screen.getByLabelText(/Nama obat/); // "Waktu" (timestamp) juga kosong, disambiguasi lewat label
    fireEvent.change(nameInput, { target: { value: "Paracetamol" } });
    fireEvent.click(screen.getByText("Coba lagi"));

    const [, body] = retryWithEdits.mock.calls[0];
    expect(JSON.parse(body)).toMatchObject({ medication_name: "Paracetamol", dosage: "1 ml" });
  });

  it("timestamp correction — datetime-local input round-trips to a backend-parseable ISO string with seconds", () => {
    const retryWithEdits = vi.fn();
    render(
      <QueueReviewPanel
        needsReviewItems={[
          makeItem({
            url: "/children/7/sleep-logs",
            body: JSON.stringify({ start_time: "2026-01-01T08:00:00", sleep_type: "siang" }),
            lastError: "start_time wajib diisi",
          }),
        ]}
        legacyItems={[]}
        discardItem={noop}
        claimLegacyItem={noop}
        retryWithEdits={retryWithEdits}
      />,
    );

    fireEvent.click(screen.getByText("Edit"));
    const startInput = screen.getByLabelText(/Mulai/); // "Selesai" (end_time) juga datetime-local, disambiguasi lewat label
    fireEvent.change(startInput, { target: { value: "2026-01-01T09:30" } });
    fireEvent.click(screen.getByText("Coba lagi"));

    const [, body] = retryWithEdits.mock.calls[0];
    expect(JSON.parse(body).start_time).toBe("2026-01-01T09:30:00");
  });

  it("presents a 'recreate manually' message instead of an edit action when a field can't be safely edited", () => {
    const retryWithEdits = vi.fn();
    render(
      <QueueReviewPanel
        needsReviewItems={[
          makeItem({
            url: "/children/7/medication-logs",
            body: JSON.stringify({ medication_name: "Paracetamol", illness_id: 999 }),
            lastError: "illness_id tidak valid",
          }),
        ]}
        legacyItems={[]}
        discardItem={noop}
        claimLegacyItem={noop}
        retryWithEdits={retryWithEdits}
      />,
    );

    expect(screen.queryByText("Edit")).not.toBeInTheDocument();
    expect(screen.getByText(/catat ulang manual/)).toBeInTheDocument();
  });

  // ---------- item 4: 409 fingerprint conflict ----------

  it("a conflict (409) item offers no edit-and-retry, only discard, with a safe explanation", () => {
    render(
      <QueueReviewPanel
        needsReviewItems={[
          makeItem({
            reviewReason: "conflict",
            lastError: "Request ini sudah pernah diproses server dengan data yang berbeda — tidak disimpan otomatis lagi.",
          }),
        ]}
        legacyItems={[]}
        discardItem={noop}
        claimLegacyItem={noop}
        retryWithEdits={vi.fn()}
      />,
    );

    expect(screen.queryByText("Edit")).not.toBeInTheDocument();
    expect(screen.getByText(/sudah pernah diproses server dengan data yang berbeda/)).toBeInTheDocument();
    expect(screen.getByText("Buang")).toBeInTheDocument();
  });

  // ---------- pre-existing coverage kept ----------

  it("discard requires explicit confirmation before calling discardItem", () => {
    const discardItem = vi.fn();
    render(
      <QueueReviewPanel needsReviewItems={[makeItem()]} legacyItems={[]} discardItem={discardItem} claimLegacyItem={noop} retryWithEdits={noop} />,
    );

    fireEvent.click(screen.getByText("Buang"));
    expect(discardItem).not.toHaveBeenCalled();
    fireEvent.click(screen.getByText("Yakin?").nextSibling);
    expect(discardItem).toHaveBeenCalledWith(1);
  });

  it("shows a distinct message and no edit option for an access_revoked (403) item", () => {
    render(
      <QueueReviewPanel
        needsReviewItems={[makeItem({ reviewReason: "access_revoked", lastError: null })]}
        legacyItems={[]}
        discardItem={noop}
        claimLegacyItem={noop}
        retryWithEdits={noop}
      />,
    );

    expect(screen.getByText(/sudah tidak punya akses/i)).toBeInTheDocument();
    expect(screen.queryByText("Edit")).not.toBeInTheDocument();
  });

  it("never renders an item belonging to a different user", () => {
    render(<QueueReviewPanel needsReviewItems={[]} legacyItems={[]} discardItem={noop} claimLegacyItem={noop} retryWithEdits={noop} />);
    expect(screen.queryByText("Menyusui")).not.toBeInTheDocument();
  });

  // ---------- Issue 2: request ID visibility for owned vs. legacy items ----------

  it("shows a valid request ID for an OWNED needs-review item, collapsed by default", () => {
    render(
      <QueueReviewPanel
        needsReviewItems={[makeItem({ lastRequestId: "owned-req-id-abc" })]}
        legacyItems={[]}
        discardItem={noop}
        claimLegacyItem={noop}
        retryWithEdits={noop}
      />,
    );

    expect(screen.queryByText("owned-req-id-abc")).not.toBeInTheDocument();
    fireEvent.click(screen.getByText("Info teknis"));
    expect(screen.getByText("owned-req-id-abc")).toBeInTheDocument();
  });

  it("never shows a request ID for an unclaimed legacy item, even if one happens to be present on the record", () => {
    render(
      <QueueReviewPanel
        needsReviewItems={[]}
        legacyItems={[legacyMedicationItem({ lastRequestId: "should-never-appear-legacy" })]}
        discardItem={noop}
        claimLegacyItem={vi.fn()}
        retryWithEdits={noop}
      />,
    );

    expect(screen.queryByText("Info teknis")).not.toBeInTheDocument();
    expect(screen.queryByText("should-never-appear-legacy")).not.toBeInTheDocument();
  });

  it("does not render the request-ID detail toggle for a needs-review item without one", () => {
    render(
      <QueueReviewPanel
        needsReviewItems={[makeItem({ lastRequestId: null })]}
        legacyItems={[]}
        discardItem={noop}
        claimLegacyItem={noop}
        retryWithEdits={noop}
      />,
    );
    expect(screen.queryByText("Info teknis")).not.toBeInTheDocument();
  });
});
