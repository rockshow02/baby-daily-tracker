import { afterEach } from "vitest";
import { cleanup } from "@testing-library/react";
import "fake-indexeddb/auto";
import "@testing-library/jest-dom/vitest";

// RTL nggak auto-cleanup DOM antar test kecuali dites lewat setup ini —
// tanpa ini, komponen dari test sebelumnya nyangkut di document.body dan
// bikin query (getByText dkk) di test berikutnya nemuin elemen dobel.
afterEach(cleanup);
