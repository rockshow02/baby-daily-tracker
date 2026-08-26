import { describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import QuickLogSheet from "./QuickLogSheet";

function renderSheet(overrides = {}) {
  const onClose = vi.fn();
  const onSubmit = vi.fn().mockResolvedValue({ id: 1 });
  render(
    <QuickLogSheet
      type="vitamin"
      onClose={onClose}
      onSubmit={onSubmit}
      onDelete={undefined}
      editingLog={null}
      lastFeedingLog={null}
      {...overrides}
    />,
  );
  return { onClose, onSubmit };
}

describe("QuickLogSheet — save/error handling", () => {
  it("successful submit calls onSubmit then onClose", async () => {
    const { onClose, onSubmit } = renderSheet();

    fireEvent.click(screen.getByText("Simpan"));

    await waitFor(() => expect(onClose).toHaveBeenCalledTimes(1));
    expect(onSubmit).toHaveBeenCalledTimes(1);
  });

  it("6. a genuine save/enqueue failure keeps the modal open and shows a readable error, without closing", async () => {
    const onSubmit = vi.fn().mockRejectedValue(new Error("Gagal menyimpan ke antrian offline."));
    const { onClose } = renderSheet({ onSubmit });

    fireEvent.click(screen.getByText("Simpan"));

    expect(await screen.findByText("Gagal menyimpan ke antrian offline.")).toBeInTheDocument();
    expect(onClose).not.toHaveBeenCalled(); // modal TETAP kebuka
  });

  it("does not expose a raw/undefined error shape — falls back to a generic readable message", async () => {
    // onSubmit reject dengan non-Error (mis. string mentah dari suatu tempat
    // yang nggak diharapkan) — pesan yang ditampilin tetap harus manusiawi
    const onSubmit = vi.fn().mockRejectedValue({});
    renderSheet({ onSubmit });

    fireEvent.click(screen.getByText("Simpan"));

    expect(await screen.findByText("Gagal menyimpan catatan. Coba lagi.")).toBeInTheDocument();
  });

  it("clears the previous error before a retry, rather than stacking messages", async () => {
    const onSubmit = vi.fn().mockRejectedValueOnce(new Error("Error pertama"));
    renderSheet({ onSubmit });

    fireEvent.click(screen.getByText("Simpan"));
    expect(await screen.findByText("Error pertama")).toBeInTheDocument();

    onSubmit.mockRejectedValueOnce(new Error("Error kedua"));
    fireEvent.click(screen.getByText("Simpan"));

    await waitFor(() => expect(screen.getByText("Error kedua")).toBeInTheDocument());
    expect(screen.queryByText("Error pertama")).not.toBeInTheDocument(); // yang lama nggak nyangkut
  });

  it("9. prevents double submission while a save is already in flight", async () => {
    let resolveSubmit;
    const onSubmit = vi.fn(
      () =>
        new Promise((resolve) => {
          resolveSubmit = resolve;
        }),
    );
    renderSheet({ onSubmit });

    const saveBtn = screen.getByText("Simpan");
    fireEvent.click(saveBtn);
    fireEvent.click(saveBtn); // klik kedua SEBELUM yang pertama selesai
    fireEvent.click(saveBtn); // dan ketiga

    expect(onSubmit).toHaveBeenCalledTimes(1); // cuma 1 kali kepanggil, bukan 3

    resolveSubmit({ id: 1 });
    await waitFor(() => expect(screen.getByText("Simpan")).not.toBeDisabled());
  });

  it("does not expose an error message before any submission is attempted", () => {
    renderSheet();
    // pastiin nggak ada sisa teks error yang ke-render tanpa pernah ada
    // kegagalan submit sama sekali (baseline sanity check)
    expect(screen.queryByText(/Gagal/)).not.toBeInTheDocument();
  });
});
