import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent, cleanup } from "@testing-library/react";
import ErrorBoundary from "./ErrorBoundary";
import { setToken, setCurrentUser, getToken, getCurrentUserId } from "../api/client";
import { enqueueRequest, getQueue } from "../utils/offlineQueue";

// Komponen anak yang SENGAJA crash di render pertama (tapi TIDAK crash
// lagi setelah remount, biar bisa dites "Coba lagi" beneran memulihkan) —
// dikontrol lewat variabel modul di luar komponen, bukan prop, biar
// perilakunya bisa di-reset per-test tanpa harus lewat re-render manual.
let shouldThrow = true;
function Bomb() {
  if (shouldThrow) {
    throw new Error("simulated render crash — pesan ini TIDAK BOLEH muncul di UI");
  }
  return <div data-testid="bomb-recovered">pulih</div>;
}

function Safe() {
  return <div data-testid="safe-child">aman</div>;
}

beforeEach(() => {
  shouldThrow = true;
  localStorage.clear();
  // React 18 nyetak error boundary yang ketangkep ke console.error bawaan
  // (di LUAR kendali kita) — silence-in di sini biar output test bersih,
  // BUKAN buat nyembunyiin assertion apa pun (semua assertion tetap jalan).
  vi.spyOn(console, "error").mockImplementation(() => {});
});

afterEach(() => {
  vi.restoreAllMocks();
  cleanup();
});

describe("ErrorBoundary", () => {
  it("1. child render error displays the fallback (not the crashed child)", () => {
    render(
      <ErrorBoundary>
        <Bomb />
      </ErrorBoundary>
    );

    expect(screen.getByText("Ups, ada yang nggak beres.")).toBeInTheDocument();
    expect(screen.queryByTestId("bomb-recovered")).not.toBeInTheDocument();
  });

  it("2. a safe client error ID is displayed", () => {
    render(
      <ErrorBoundary>
        <Bomb />
      </ErrorBoundary>
    );

    const idEl = screen.getByTestId("error-boundary-id");
    expect(idEl.textContent).toMatch(/Kode error: .+/);
  });

  it("3. the crashed error's message/stack is never rendered into the fallback DOM", () => {
    render(
      <ErrorBoundary>
        <Bomb />
      </ErrorBoundary>
    );

    expect(document.body.textContent).not.toMatch(/simulated render crash/);
    expect(document.body.textContent).not.toMatch(/at Bomb/); // potongan khas stack trace
  });

  it("4. Retry remounts the child (recovers once the underlying condition is fixed)", () => {
    render(
      <ErrorBoundary>
        <Bomb />
      </ErrorBoundary>
    );
    expect(screen.getByText("Ups, ada yang nggak beres.")).toBeInTheDocument();

    // "perbaiki" kondisi yang bikin crash SEBELUM klik retry — persis
    // skenario nyata: reload data / state yang bikin bug ilang
    shouldThrow = false;
    fireEvent.click(screen.getByText("Coba lagi"));

    expect(screen.getByTestId("bomb-recovered")).toBeInTheDocument();
    expect(screen.queryByText("Ups, ada yang nggak beres.")).not.toBeInTheDocument();
  });

  it("5. Reload calls the expected browser reload behavior", () => {
    const reloadSpy = vi.fn();
    const originalLocation = window.location;
    Object.defineProperty(window, "location", {
      configurable: true,
      value: { ...originalLocation, reload: reloadSpy },
    });

    render(
      <ErrorBoundary>
        <Bomb />
      </ErrorBoundary>
    );
    fireEvent.click(screen.getByText("Muat ulang aplikasi"));

    expect(reloadSpy).toHaveBeenCalledTimes(1);

    Object.defineProperty(window, "location", { configurable: true, value: originalLocation });
  });

  it("6. offline queue (IndexedDB) storage is not cleared when a component crashes", async () => {
    const queueId = await enqueueRequest({
      method: "POST",
      url: "/children/1/feeding-logs",
      body: JSON.stringify({ feed_type: "sufor" }),
      userId: 1,
      clientRequestId: "error-boundary-test-key",
    });

    render(
      <ErrorBoundary>
        <Bomb />
      </ErrorBoundary>
    );
    fireEvent.click(screen.getByText("Coba lagi"));

    const queue = await getQueue();
    expect(queue.some((item) => item.id === queueId)).toBe(true);
  });

  it("7. authentication storage (token, current user id) is not cleared when a component crashes", () => {
    setToken("some-token-value");
    setCurrentUser(42);

    render(
      <ErrorBoundary>
        <Bomb />
      </ErrorBoundary>
    );
    fireEvent.click(screen.getByText("Coba lagi"));

    expect(getToken()).toBe("some-token-value");
    expect(getCurrentUserId()).toBe(42);
  });

  it("does not affect rendering of a child that never throws", () => {
    render(
      <ErrorBoundary>
        <Safe />
      </ErrorBoundary>
    );

    expect(screen.getByTestId("safe-child")).toBeInTheDocument();
    expect(screen.queryByText("Ups, ada yang nggak beres.")).not.toBeInTheDocument();
  });

  it("shows the friendly Indonesian fallback message with both required actions", () => {
    render(
      <ErrorBoundary>
        <Bomb />
      </ErrorBoundary>
    );

    expect(screen.getByText("Coba lagi")).toBeInTheDocument();
    expect(screen.getByText("Muat ulang aplikasi")).toBeInTheDocument();
  });
});
