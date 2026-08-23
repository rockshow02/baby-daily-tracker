import { afterEach } from "vitest";
import { cleanup } from "@testing-library/react";
import "fake-indexeddb/auto";
import "@testing-library/jest-dom/vitest";

// RTL nggak auto-cleanup DOM antar test kecuali dites lewat setup ini —
// tanpa ini, komponen dari test sebelumnya nyangkut di document.body dan
// bikin query (getByText dkk) di test berikutnya nemuin elemen dobel.
afterEach(cleanup);

// jsdom nggak punya ResizeObserver bawaan — recharts (dipakai
// StatsScreen.jsx/InsightsScreen.jsx) butuh ini buat ResponsiveContainer,
// dan tanpa polyfill ini render-nya throw "ResizeObserver is not defined"
// di lingkungan test. Stub no-op (bukan implementasi beneran) cukup,
// soalnya test di sini nggak pernah menguji ukuran/layout piksel asli.
if (typeof globalThis.ResizeObserver === "undefined") {
  globalThis.ResizeObserver = class ResizeObserver {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
}
