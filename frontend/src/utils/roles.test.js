import { describe, expect, it } from "vitest";
import { describeRole, canWrite, isOwner, canDeleteRecord, ROLE_OWNER, ROLE_EDITOR, ROLE_VIEWER } from "./roles";

describe("describeRole", () => {
  it("translates each known backend role to a safe Indonesian label", () => {
    expect(describeRole(ROLE_OWNER)).toBe("Pemilik");
    expect(describeRole(ROLE_EDITOR)).toBe("Editor");
    expect(describeRole(ROLE_VIEWER)).toBe("Hanya melihat");
  });

  it("falls back to a generic label for unknown/missing roles, never echoing the raw value", () => {
    expect(describeRole("admin")).toBe("Tidak diketahui");
    expect(describeRole(undefined)).toBe("Tidak diketahui");
    expect(describeRole(null)).toBe("Tidak diketahui");
    expect(describeRole("")).toBe("Tidak diketahui");
  });
});

describe("canWrite", () => {
  it("allows owner and editor", () => {
    expect(canWrite(ROLE_OWNER)).toBe(true);
    expect(canWrite(ROLE_EDITOR)).toBe(true);
  });

  it("denies viewer", () => {
    expect(canWrite(ROLE_VIEWER)).toBe(false);
  });

  it("defaults an unknown/missing role to read-only (false), never granting write access", () => {
    expect(canWrite(undefined)).toBe(false);
    expect(canWrite(null)).toBe(false);
    expect(canWrite("")).toBe(false);
    expect(canWrite("admin")).toBe(false);
  });
});

describe("isOwner", () => {
  it("is true only for the owner role", () => {
    expect(isOwner(ROLE_OWNER)).toBe(true);
    expect(isOwner(ROLE_EDITOR)).toBe(false);
    expect(isOwner(ROLE_VIEWER)).toBe(false);
    expect(isOwner(undefined)).toBe(false);
  });
});

describe("canDeleteRecord", () => {
  it("owner can delete any record, including legacy records with no creator", () => {
    expect(canDeleteRecord(ROLE_OWNER, 5, 1)).toBe(true);
    expect(canDeleteRecord(ROLE_OWNER, null, 1)).toBe(true);
  });

  it("editor can delete only their own records", () => {
    expect(canDeleteRecord(ROLE_EDITOR, 1, 1)).toBe(true);
    expect(canDeleteRecord(ROLE_EDITOR, 2, 1)).toBe(false);
  });

  it("editor cannot delete a legacy record with a null creator", () => {
    expect(canDeleteRecord(ROLE_EDITOR, null, 1)).toBe(false);
  });

  it("viewer can never delete", () => {
    expect(canDeleteRecord(ROLE_VIEWER, 1, 1)).toBe(false);
    expect(canDeleteRecord(ROLE_VIEWER, null, 1)).toBe(false);
  });

  it("an unknown/missing role can never delete", () => {
    expect(canDeleteRecord(undefined, 1, 1)).toBe(false);
    expect(canDeleteRecord(null, 1, 1)).toBe(false);
  });
});
