import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent, cleanup, act } from "@testing-library/react";
import RequestIdDetail from "./RequestIdDetail";

beforeEach(() => {
  // clipboard nggak ada secara default di jsdom — kasih implementasi
  // sukses standar, test yang butuh kegagalan meng-override sendiri.
  Object.assign(navigator, { clipboard: { writeText: vi.fn().mockResolvedValue(undefined) } });
});

afterEach(() => {
  vi.restoreAllMocks();
  vi.useRealTimers();
  cleanup();
});

describe("RequestIdDetail — display validation (defense in depth)", () => {
  it("renders nothing when requestId is null/absent", () => {
    const { container } = render(<RequestIdDetail requestId={null} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("does not render an invalid stored value, even though it came from IndexedDB (not just the hook's own guard)", () => {
    const { container } = render(<RequestIdDetail requestId={"not valid! <script>alert(1)</script>"} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("does not render an overlong stored value", () => {
    const { container } = render(<RequestIdDetail requestId={"a".repeat(200)} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("renders a valid request id", () => {
    render(<RequestIdDetail requestId="abc123-def_456" />);
    expect(screen.getByText("Info teknis")).toBeInTheDocument();
  });
});

describe("RequestIdDetail — collapsed by default, expandable", () => {
  it("keeps the request id hidden until the 'Info teknis' toggle is clicked", () => {
    render(<RequestIdDetail requestId="abc123-def_456" />);
    expect(screen.queryByText("abc123-def_456")).not.toBeInTheDocument();

    fireEvent.click(screen.getByText("Info teknis"));
    expect(screen.getByText("abc123-def_456")).toBeInTheDocument();
  });

  it("can be collapsed again after expanding", () => {
    render(<RequestIdDetail requestId="abc123-def_456" />);
    fireEvent.click(screen.getByText("Info teknis"));
    expect(screen.getByText("abc123-def_456")).toBeInTheDocument();

    fireEvent.click(screen.getByText("Sembunyikan info teknis"));
    expect(screen.queryByText("abc123-def_456")).not.toBeInTheDocument();
  });
});

describe("RequestIdDetail — copy action", () => {
  it("copies exactly the safe request id, never a raw/unsanitized value", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.assign(navigator, { clipboard: { writeText } });

    render(<RequestIdDetail requestId="abc123-def_456" />);
    fireEvent.click(screen.getByText("Info teknis"));
    await fireEvent.click(screen.getByText("Salin"));

    expect(writeText).toHaveBeenCalledTimes(1);
    expect(writeText).toHaveBeenCalledWith("abc123-def_456");
  });

  it("shows 'Tersalin' feedback after a successful copy", async () => {
    render(<RequestIdDetail requestId="abc123-def_456" />);
    fireEvent.click(screen.getByText("Info teknis"));
    await fireEvent.click(screen.getByText("Salin"));

    expect(await screen.findByText("Tersalin")).toBeInTheDocument();
  });

  it("does not crash when the clipboard API rejects, and the id stays manually readable", async () => {
    Object.assign(navigator, { clipboard: { writeText: vi.fn().mockRejectedValue(new Error("denied")) } });

    render(<RequestIdDetail requestId="abc123-def_456" />);
    fireEvent.click(screen.getByText("Info teknis"));

    await expect(fireEvent.click(screen.getByText("Salin"))).not.toBeNull();
    // nggak crash (render masih ada) DAN ID-nya tetap kebaca manual
    expect(screen.getByText("abc123-def_456")).toBeInTheDocument();
    expect(screen.queryByText("Tersalin")).not.toBeInTheDocument();
  });

  it("does not crash when the clipboard API is entirely unavailable", async () => {
    Object.assign(navigator, { clipboard: undefined });

    render(<RequestIdDetail requestId="abc123-def_456" />);
    fireEvent.click(screen.getByText("Info teknis"));
    fireEvent.click(screen.getByText("Salin"));

    expect(screen.getByText("abc123-def_456")).toBeInTheDocument();
  });
});

describe("RequestIdDetail — copy feedback timer cleanup (Issue 3)", () => {
  it("clears the 'Tersalin' timer on unmount without throwing or updating state after unmount", async () => {
    vi.useFakeTimers();
    const errorSpy = vi.spyOn(console, "error").mockImplementation(() => {});

    const { unmount } = render(<RequestIdDetail requestId="abc123-def_456" />);
    fireEvent.click(screen.getByText("Info teknis"));
    await act(async () => {
      fireEvent.click(screen.getByText("Salin"));
      await Promise.resolve();
    });

    unmount();
    // Kalau timer-nya nggak dibersihin, callback ini bakal nyoba
    // setState di komponen yang udah unmount dan React ngeluarin warning
    // ke console.error — ADVANCE waktunya lewat batas 2 detik DI SINI.
    act(() => {
      vi.advanceTimersByTime(3000);
    });

    expect(errorSpy).not.toHaveBeenCalled();
  });

  it("repeated copy clicks reset the timer instead of accumulating multiple independent timers", async () => {
    vi.useFakeTimers();
    const clearSpy = vi.spyOn(global, "clearTimeout");

    render(<RequestIdDetail requestId="abc123-def_456" />);
    fireEvent.click(screen.getByText("Info teknis"));

    const copyBtn = () => screen.getByText(/Salin|Tersalin/);
    await act(async () => {
      fireEvent.click(copyBtn());
      await Promise.resolve(); // biar await navigator.clipboard.writeText() di dalam handleCopy sempat resolve
    });
    const callsAfterFirstClick = clearSpy.mock.calls.length;

    // majuin waktu SEDIKIT (bukan 2000 penuh) sebelum klik ke-2 — biar
    // timer dari klik ke-1 KEBUKTIAN belum sempat nyala sendiri, murni
    // di-clear sama klik ke-2, bukan kebetulan udah abis duluan.
    act(() => {
      vi.advanceTimersByTime(500);
    });
    await act(async () => {
      fireEvent.click(copyBtn());
      await Promise.resolve();
    });
    // klik ke-2 HARUS motor clearTimeout lagi (buat timer dari klik
    // pertama) SEBELUM bikin timer baru — bukan numpuk 2 timer independen
    expect(clearSpy.mock.calls.length).toBeGreaterThan(callsAfterFirstClick);

    act(() => {
      vi.advanceTimersByTime(2000);
    });
    expect(screen.queryByText("Tersalin")).not.toBeInTheDocument();
  });
});
