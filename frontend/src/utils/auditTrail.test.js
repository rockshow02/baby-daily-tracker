import { describe, expect, it } from "vitest";
import {
  describeEntityType,
  describeChangedFields,
  describeAuditEvent,
  ENTITY_TYPE_LABELS,
  ENTITY_TYPE_FILTER_OPTIONS,
  ACTION_FILTER_OPTIONS,
} from "./auditTrail";

describe("describeEntityType", () => {
  it("maps every known entity_type to a non-empty Indonesian label", () => {
    for (const key of Object.keys(ENTITY_TYPE_LABELS)) {
      expect(describeEntityType(key)).toBeTruthy();
    }
  });

  it("falls back to a safe generic label for an unknown entity_type instead of echoing the raw key", () => {
    expect(describeEntityType("some_future_entity_backend_added")).toBe("catatan");
    expect(describeEntityType("some_future_entity_backend_added")).not.toContain("future");
  });
});

describe("describeChangedFields", () => {
  it("maps whitelisted field names to human labels for a known entity_type", () => {
    expect(describeChangedFields("feeding_log", ["duration_minutes", "volume_ml"])).toEqual([
      "durasi",
      "volume",
    ]);
  });

  it("falls back to a safe generic label for a field name outside the whitelist, never echoing the raw key", () => {
    const result = describeChangedFields("feeding_log", ["some_unexpected_raw_key"]);
    expect(result).toEqual(["detail"]);
    expect(result.join("")).not.toContain("unexpected");
  });

  it("returns an empty list for a nullish/missing changed_fields value", () => {
    expect(describeChangedFields("feeding_log", null)).toEqual([]);
    expect(describeChangedFields("feeding_log", undefined)).toEqual([]);
  });

  it("maps the backend's generic private-field marker to a safe Indonesian label, for any entity_type", () => {
    expect(describeChangedFields("medication_log", ["private_details"])).toEqual(["detail pribadi"]);
    expect(describeChangedFields("illness_log", ["private_details"])).toEqual(["detail pribadi"]);
    expect(describeChangedFields("feeding_log", ["private_details"])).toEqual(["detail pribadi"]);
  });

  it("mixes a safe field label and the private-details label together, without exposing which private field it was", () => {
    const result = describeChangedFields("doctor_visit", ["next_visit_date", "private_details"]);
    expect(result).toEqual(["jadwal kontrol", "detail pribadi"]);
    // marker generik itu sendiri TIDAK PERNAH nama field privat aslinya
    // (mis. "doctor_name", "diagnosis") — cuma label generik yang tetap
    expect(result).not.toContain("doctor_name");
    expect(result).not.toContain("diagnosis");
  });

  it("returns generic fallbacks for every field when entity_type itself is unknown", () => {
    expect(describeChangedFields("some_future_entity", ["x", "y"])).toEqual(["detail", "detail"]);
  });
});

describe("describeAuditEvent", () => {
  it("builds a create sentence", () => {
    const event = {
      action: "create",
      entity_type: "feeding_log",
      changed_fields: [],
      actor_name: "Weswew",
    };
    expect(describeAuditEvent(event)).toBe("Weswew menambahkan catatan menyusui");
  });

  it("builds a delete sentence", () => {
    const event = {
      action: "delete",
      entity_type: "diaper_log",
      changed_fields: [],
      actor_name: "Weswew",
    };
    expect(describeAuditEvent(event)).toBe("Weswew menghapus catatan popok");
  });

  it("builds an update sentence naming only the changed fields, joined with 'dan'", () => {
    const event = {
      action: "update",
      entity_type: "feeding_log",
      changed_fields: ["timestamp", "volume_ml"],
      actor_name: "Weswew",
    };
    expect(describeAuditEvent(event)).toBe("Weswew mengubah waktu dan volume catatan menyusui");
  });

  it("joins three or more changed fields with commas and a trailing 'dan'", () => {
    const event = {
      action: "update",
      entity_type: "feeding_log",
      changed_fields: ["timestamp", "volume_ml", "duration_minutes"],
      actor_name: "Weswew",
    };
    expect(describeAuditEvent(event)).toBe(
      "Weswew mengubah waktu, volume dan durasi catatan menyusui",
    );
  });

  it("falls back to a generic actor label when actor_name is null (e.g. actor account no longer exists)", () => {
    const event = { action: "create", entity_type: "sleep_log", changed_fields: [], actor_name: null };
    expect(describeAuditEvent(event)).toBe("Pengguna menambahkan catatan tidur");
  });

  it("builds a sentence for a notes-only (fully private) update using the generic marker's label", () => {
    const event = {
      action: "update",
      entity_type: "medication_log",
      changed_fields: ["private_details"],
      actor_name: "Weswew",
    };
    expect(describeAuditEvent(event)).toBe("Weswew mengubah detail pribadi catatan obat");
  });

  it("falls back to a generic phrase when an update event has no changed_fields at all", () => {
    const event = {
      action: "update",
      entity_type: "mood_log",
      changed_fields: [],
      actor_name: "Weswew",
    };
    expect(describeAuditEvent(event)).toBe("Weswew mengubah sebagian detail catatan mood");
  });

  it("never renders the raw entity_type/field key text for an unrecognized value", () => {
    const event = {
      action: "update",
      entity_type: "some_new_entity_v2",
      changed_fields: ["some_new_raw_field"],
      actor_name: "Weswew",
    };
    const sentence = describeAuditEvent(event);
    expect(sentence).not.toContain("some_new_entity_v2");
    expect(sentence).not.toContain("some_new_raw_field");
  });
});

describe("filter option lists", () => {
  it("ENTITY_TYPE_FILTER_OPTIONS starts with an 'all' option and covers all 12 Phase 1 entity types", () => {
    expect(ENTITY_TYPE_FILTER_OPTIONS[0]).toEqual({ value: "", label: "Semua jenis" });
    expect(ENTITY_TYPE_FILTER_OPTIONS.length).toBe(1 + Object.keys(ENTITY_TYPE_LABELS).length);
  });

  it("ACTION_FILTER_OPTIONS covers create/update/delete plus an 'all' option", () => {
    const values = ACTION_FILTER_OPTIONS.map((o) => o.value);
    expect(values).toEqual(["", "create", "update", "delete"]);
  });
});
