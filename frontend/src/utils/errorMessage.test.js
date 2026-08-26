import { describe, expect, it } from "vitest";
import { toUserFacingErrorMessage } from "./errorMessage";

describe("toUserFacingErrorMessage", () => {
  it("keeps a readable string", () => {
    expect(toUserFacingErrorMessage("Email atau password salah")).toBe("Email atau password salah");
  });

  it("extracts nested messages instead of rendering [object Object]", () => {
    expect(toUserFacingErrorMessage({ message: "Data belum lengkap" })).toBe("Data belum lengkap");
  });

  it("uses a safe fallback for unknown shapes", () => {
    expect(toUserFacingErrorMessage({ code: "INTERNAL" }, "Silakan coba lagi.")).toBe("Silakan coba lagi.");
  });
});
