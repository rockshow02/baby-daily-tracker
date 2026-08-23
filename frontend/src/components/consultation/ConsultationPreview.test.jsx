import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import ConsultationPreview from "./ConsultationPreview";

const PERIOD = { preset: "7d", start_date: "2026-08-17", end_date: "2026-08-23", timezone: "Asia/Jakarta", days: 7 };

function makeReport(sections, overrides = {}) {
  return {
    child_display_name: "Dedek",
    period: PERIOD,
    included_sections: Object.keys(sections),
    sensitive_sections_included: [],
    sections,
    ...overrides,
  };
}

const RAW_TECHNICAL_KEYS = [
  "total_events", "avg_events_per_day", "events_with_volume", "unfinished_session_count",
  "total_count_in_period", "latest_temperature_celsius", '"truncated":',
];

function expectNoRawJsonLeak(container) {
  const text = container.textContent;
  for (const key of RAW_TECHNICAL_KEYS) {
    expect(text).not.toContain(key);
  }
  expect(container.querySelector("pre")).toBeNull();
}

describe("ConsultationPreview — no raw JSON / no technical field names", () => {
  it("never renders a <pre> tag or raw technical keys for a fully populated report", () => {
    const { container } = render(<ConsultationPreview report={makeReport({
      child_summary: {
        display_name: "Dedek", birth_date: "2026-01-01", gender: "L", age_as_of_report_end: "7 bulan",
        medication_event_count_in_period: 2, doctor_visit_count_in_period: 1,
        illness_record_count_in_period: 0, temperature_record_count_in_period: 3,
      },
      feeding: {
        total_events: 8, avg_events_per_day: 1.1, by_type: { asi_langsung: 5, asi_perah: 2, sufor: 1, mpasi: 0 },
        total_volume_ml: 300, events_with_volume: 6, avg_volume_ml_per_event: 50,
      },
    })} />);
    expectNoRawJsonLeak(container);
  });

  it("does not leak technical keys even for an empty section object", () => {
    const { container } = render(<ConsultationPreview report={makeReport({ feeding: {} })} />);
    expectNoRawJsonLeak(container);
  });
});

describe("ConsultationPreview — child summary", () => {
  it("shows readable labels and values", () => {
    render(<ConsultationPreview report={makeReport({
      child_summary: {
        display_name: "Dedek", birth_date: "2026-01-01", gender: "L", age_as_of_report_end: "7 bulan",
        medication_event_count_in_period: 2, doctor_visit_count_in_period: 1,
        illness_record_count_in_period: 0, temperature_record_count_in_period: 3,
      },
    })} />);
    expect(screen.getByText("Dedek")).toBeInTheDocument();
    expect(screen.getByText("7 bulan")).toBeInTheDocument();
    expect(screen.getByText("1 Jan 2026")).toBeInTheDocument();
    expect(screen.getByText("Laki-laki")).toBeInTheDocument();
    expect(screen.getByText("2 catatan")).toBeInTheDocument();
  });

  it("omits the gender row when gender is not available", () => {
    render(<ConsultationPreview report={makeReport({
      child_summary: { display_name: "Dedek", birth_date: "2026-01-01", gender: null, age_as_of_report_end: "7 bulan" },
    })} />);
    expect(screen.queryByText("Jenis kelamin")).not.toBeInTheDocument();
  });
});

describe("ConsultationPreview — feeding", () => {
  it("shows totals and the type breakdown with readable labels", () => {
    render(<ConsultationPreview report={makeReport({
      feeding: {
        total_events: 8, avg_events_per_day: 1.1, by_type: { asi_langsung: 5, asi_perah: 2, sufor: 1, mpasi: 0 },
        total_volume_ml: 300, events_with_volume: 6, avg_volume_ml_per_event: 50,
      },
    })} />);
    expect(screen.getByText("8 kali")).toBeInTheDocument();
    expect(screen.getByText("ASI langsung")).toBeInTheDocument();
    expect(screen.getByText("300 ml")).toBeInTheDocument();
  });

  it("shows a partial-volume coverage notice and never implies a complete total", () => {
    render(<ConsultationPreview report={makeReport({
      feeding: {
        total_events: 8, avg_events_per_day: 1.1, by_type: { asi_langsung: 8, asi_perah: 0, sufor: 0, mpasi: 0 },
        total_volume_ml: 300, events_with_volume: 6, avg_volume_ml_per_event: 50,
      },
    })} />);
    expect(screen.getByText("6 dari 8 sesi memiliki data volume.")).toBeInTheDocument();
    expect(screen.getByText("Total volume yang tercatat")).toBeInTheDocument();
  });

  it("hides the coverage notice when every event has volume data", () => {
    render(<ConsultationPreview report={makeReport({
      feeding: {
        total_events: 4, avg_events_per_day: 0.6, by_type: { asi_langsung: 4, asi_perah: 0, sufor: 0, mpasi: 0 },
        total_volume_ml: 200, events_with_volume: 4, avg_volume_ml_per_event: 50,
      },
    })} />);
    expect(screen.queryByText(/sesi memiliki data volume/)).not.toBeInTheDocument();
  });

  it("shows the empty state when there are no feeding events", () => {
    render(<ConsultationPreview report={makeReport({ feeding: { total_events: 0 } })} />);
    expect(screen.getByText("Tidak ada catatan menyusui/makan pada periode ini.")).toBeInTheDocument();
  });
});

describe("ConsultationPreview — sleep", () => {
  it("shows human-readable duration formatting", () => {
    render(<ConsultationPreview report={makeReport({
      sleep: {
        completed_session_count: 3, unfinished_session_count: 0,
        total_completed_minutes: 480, avg_duration_minutes_per_session: 160,
      },
    })} />);
    expect(screen.getByText("8 jam")).toBeInTheDocument();
  });

  it("shows a notice that unfinished sessions are excluded from duration totals", () => {
    render(<ConsultationPreview report={makeReport({
      sleep: {
        completed_session_count: 2, unfinished_session_count: 1,
        total_completed_minutes: 120, avg_duration_minutes_per_session: 60,
      },
    })} />);
    expect(screen.getByText("Sesi yang masih berjalan tidak dihitung dalam total durasi.")).toBeInTheDocument();
  });

  it("does not show the unfinished notice when there are no unfinished sessions", () => {
    render(<ConsultationPreview report={makeReport({
      sleep: { completed_session_count: 2, unfinished_session_count: 0, total_completed_minutes: 120 },
    })} />);
    expect(screen.queryByText(/masih berjalan tidak dihitung/)).not.toBeInTheDocument();
  });
});

describe("ConsultationPreview — diaper", () => {
  it("shows the caregiver-friendly breakdown", () => {
    render(<ConsultationPreview report={makeReport({
      diaper: { total_events: 6, pipis_count: 4, bab_count: 2, combined_count: 0, avg_events_per_day: 0.9 },
    })} />);
    expect(screen.getByText("Pipis")).toBeInTheDocument();
    expect(screen.getByText("BAB")).toBeInTheDocument();
    expect(screen.getByText("Pipis + BAB")).toBeInTheDocument();
  });
});

describe("ConsultationPreview — pumping", () => {
  it("shows a partial-data notice when not all sessions include values", () => {
    render(<ConsultationPreview report={makeReport({
      pumping: {
        session_count: 5, total_volume_ml: 200, events_with_volume: 3, avg_volume_ml_per_event: 66.7,
        total_duration_minutes: 40, events_with_duration: 5,
      },
    })} />);
    expect(screen.getByText("3 dari 5 sesi memiliki data volume.")).toBeInTheDocument();
    expect(screen.queryByText(/sesi memiliki data durasi/)).not.toBeInTheDocument();
  });
});

describe("ConsultationPreview — activity & mood", () => {
  it("shows two clear subsections", () => {
    render(<ConsultationPreview report={makeReport({
      activity_mood: {
        activity: { session_count: 2, total_duration_minutes: 60, events_with_duration: 2 },
        mood: { counts: { ceria: 3, baik: 2, sedih: 1, menangis: 0 }, total_events: 6 },
      },
    })} />);
    expect(screen.getByText("Aktivitas")).toBeInTheDocument();
    expect(screen.getByText("Suasana hati")).toBeInTheDocument();
    expect(screen.getByText("Ceria")).toBeInTheDocument();
    expect(screen.getByText("Menangis")).toBeInTheDocument();
  });
});

describe("ConsultationPreview — growth", () => {
  it("shows latest and previous measurements", () => {
    render(<ConsultationPreview report={makeReport({
      growth: {
        latest: { measured_date: "2026-08-20", weight_kg: 8.2, height_cm: 68, head_circumference_cm: 44 },
        previous: { measured_date: "2026-07-20", weight_kg: 7.8, height_cm: 66, head_circumference_cm: 43 },
        weight_change_kg: 0.4, height_change_cm: 2, head_circumference_change_cm: 1,
        days_since_latest_measurement: 3,
        measurements_in_period: [{ measured_date: "2026-08-20", weight_kg: 8.2, height_cm: 68, head_circumference_cm: 44 }],
        total_count_in_period: 1,
        truncated: false,
      },
    })} />);
    expect(screen.getByText("8,2 kg")).toBeInTheDocument();
    expect(screen.getByText("Tanggal pengukuran terakhir")).toBeInTheDocument();
  });

  it("labels a lifetime-latest measurement outside the period clearly", () => {
    render(<ConsultationPreview report={makeReport({
      growth: {
        latest: { measured_date: "2026-06-01", weight_kg: 7, height_cm: 60, head_circumference_cm: null },
        previous: null, weight_change_kg: null, height_change_cm: null, head_circumference_change_cm: null,
        days_since_latest_measurement: 80,
        measurements_in_period: [],
        total_count_in_period: 0,
        truncated: false,
      },
    })} />);
    expect(screen.getByText("Pengukuran terakhir yang tersedia")).toBeInTheDocument();
    expect(screen.queryByText("Tanggal pengukuran terakhir")).not.toBeInTheDocument();
  });

  it("shows the empty state when there is no measurement at all", () => {
    render(<ConsultationPreview report={makeReport({ growth: { latest: null, measurements_in_period: [] } })} />);
    expect(screen.getByText("Belum ada pengukuran pertumbuhan.")).toBeInTheDocument();
  });
});

describe("ConsultationPreview — temperature", () => {
  it("shows the in-period summary", () => {
    render(<ConsultationPreview report={makeReport({
      temperature: {
        record_count_in_period: 3, avg_celsius_in_period: 36.9, min_celsius_in_period: 36.5,
        max_celsius_in_period: 37.4, latest_temperature_celsius: 36.8,
        latest_temperature_at: "2026-08-22T08:00:00+07:00",
      },
    })} />);
    expect(screen.getByText("36,9°C")).toBeInTheDocument();
  });

  it("shows the empty state when there are no temperature records at all", () => {
    render(<ConsultationPreview report={makeReport({ temperature: { record_count_in_period: 0, latest_temperature_celsius: null } })} />);
    expect(screen.getByText("Tidak ada catatan suhu pada periode ini.")).toBeInTheDocument();
  });
});

describe("ConsultationPreview — illness (sensitive)", () => {
  it("shows entries without exposing generic notes", () => {
    render(<ConsultationPreview report={makeReport({
      illness: { entries: [{ illness_name: "Demam", start_date: "2026-08-18", end_date: "2026-08-20", is_ongoing: false, symptoms: "Demam ringan" }], total_count_in_period: 1, truncated: false },
    })} />);
    expect(screen.getByText("Demam")).toBeInTheDocument();
    expect(screen.getByText(/Demam ringan/)).toBeInTheDocument();
  });

  it("shows the ongoing label when there is no end date", () => {
    render(<ConsultationPreview report={makeReport({
      illness: { entries: [{ illness_name: "Batuk", start_date: "2026-08-18", end_date: null, is_ongoing: true, symptoms: null }], total_count_in_period: 1, truncated: false },
    })} />);
    expect(screen.getByText(/Masih berlangsung/)).toBeInTheDocument();
  });
});

describe("ConsultationPreview — medication (sensitive)", () => {
  it("shows medication entries", () => {
    render(<ConsultationPreview report={makeReport({
      medication: { entries: [{ medication_name: "Paracetamol", dosage: "1 sdt", timestamp: "2026-08-20T08:00:00+07:00" }], total_count_in_period: 1, truncated: false },
    })} />);
    expect(screen.getByText("Paracetamol")).toBeInTheDocument();
    expect(screen.getByText(/1 sdt/)).toBeInTheDocument();
  });
});

describe("ConsultationPreview — vaccination", () => {
  it("shows text status labels, not color alone", () => {
    render(<ConsultationPreview report={makeReport({
      vaccination: {
        vaccinations: [
          { vaccine_schedule_id: 1, vaccine_name: "BCG", dose_label: null, given: true, given_date: "2026-02-01" },
          { vaccine_schedule_id: 2, vaccine_name: "Polio", dose_label: "Dosis 1", given: false, given_date: null },
        ],
      },
    })} />);
    expect(screen.getByText("Sudah diberikan")).toBeInTheDocument();
    expect(screen.getByText("Belum diberikan")).toBeInTheDocument();
  });
});

describe("ConsultationPreview — milestones", () => {
  it("shows a known milestone label", () => {
    render(<ConsultationPreview report={makeReport({
      milestones: { entries: [{ milestone_type: "bisa_duduk", achieved_date: "2026-08-10" }], total_count_in_period: 1, truncated: false },
    })} />);
    expect(screen.getByText("Bisa duduk")).toBeInTheDocument();
  });

  it("falls back to a safe generic label for an unknown milestone code", () => {
    render(<ConsultationPreview report={makeReport({
      milestones: { entries: [{ milestone_type: "some_future_code", achieved_date: "2026-08-10" }], total_count_in_period: 1, truncated: false },
    })} />);
    expect(screen.getByText("Milestone lainnya")).toBeInTheDocument();
    expect(screen.queryByText("some_future_code")).not.toBeInTheDocument();
  });
});

describe("ConsultationPreview — previous doctor visits (sensitive)", () => {
  it("shows visit entries with reason and diagnosis", () => {
    render(<ConsultationPreview report={makeReport({
      doctor_visits: { entries: [{ visit_date: "2026-08-15", doctor_name: "Dr. A", clinic_name: "Klinik A", reason: "Demam", diagnosis: "ISPA", next_visit_date: null }], total_count_in_period: 1, truncated: false },
    })} />);
    expect(screen.getByText("Dr. A")).toBeInTheDocument();
    expect(screen.getByText(/Demam/)).toBeInTheDocument();
    expect(screen.getByText(/ISPA/)).toBeInTheDocument();
  });
});

describe("ConsultationPreview — Smart Insights", () => {
  it("shows the backend-provided safe description", () => {
    render(<ConsultationPreview report={makeReport({
      insights: {
        insights: [{ code: "sleep_duration_increased", description: "Total durasi tidur tercatat meningkat sekitar 45 menit dibanding periode sebelumnya.", metric: "sleep_duration_minutes", direction: "up", value: 45 }],
        data_quality: { has_any_data: true, days_with_records: 5 },
      },
    })} />);
    expect(screen.getByText(/meningkat sekitar 45 menit/)).toBeInTheDocument();
    expect(screen.queryByText("sleep_duration_increased")).not.toBeInTheDocument();
  });

  it("shows the required insufficient-data message", () => {
    render(<ConsultationPreview report={makeReport({
      insights: {
        insights: [{ code: "insufficient_data", description: "irrelevant backend text", metric: null, direction: null, value: null }],
        data_quality: { has_any_data: false, days_with_records: 0 },
      },
    })} />);
    expect(screen.getByText("Data belum cukup untuk menyimpulkan pola.")).toBeInTheDocument();
  });
});

describe("ConsultationPreview — questions & note (sensitive, transient)", () => {
  it("preserves line breaks and renders as plain text", () => {
    const { container } = render(<ConsultationPreview report={makeReport({
      questions: { text: "Baris 1\nBaris 2\nBaris 3" },
    })} />);
    expect(container.textContent).toContain("Baris 1");
    expect(container.textContent).toContain("Baris 2");
    const p = screen.getByText(/Baris 1/);
    expect(p.className).toContain("whitespace-pre-wrap");
  });

  it("renders HTML/script strings as literal text, never interpreted markup", () => {
    const payload = "<script>alert(1)</script><b>bold</b>";
    const { container } = render(<ConsultationPreview report={makeReport({ note: { text: payload } })} />);
    expect(container.querySelector("script")).toBeNull();
    expect(container.querySelector("b")).toBeNull();
    expect(screen.getByText(payload)).toBeInTheDocument();
  });

  it("shows empty states with the correct headings when no text was provided", () => {
    render(<ConsultationPreview report={makeReport({ questions: { text: "" }, note: { text: "" } })} />);
    expect(screen.getByText("Pertanyaan untuk Dokter")).toBeInTheDocument();
    expect(screen.getByText("Catatan Tambahan Caregiver")).toBeInTheDocument();
    expect(screen.getByText("Tidak ada pertanyaan yang ditambahkan.")).toBeInTheDocument();
    expect(screen.getByText("Tidak ada catatan tambahan yang ditambahkan.")).toBeInTheDocument();
  });
});

describe("ConsultationPreview — missing values", () => {
  it("renders the dash for missing values, never null/undefined/NaN literal text", () => {
    const { container } = render(<ConsultationPreview report={makeReport({
      growth: {
        latest: { measured_date: "2026-08-20", weight_kg: null, height_cm: null, head_circumference_cm: null },
        previous: null, weight_change_kg: null, height_change_cm: null, head_circumference_change_cm: null,
        days_since_latest_measurement: null, measurements_in_period: [], total_count_in_period: 0, truncated: false,
      },
    })} />);
    expect(container.textContent).not.toContain("null");
    expect(container.textContent).not.toContain("undefined");
    expect(container.textContent).not.toContain("NaN");
    expect(screen.getAllByText("—").length).toBeGreaterThan(0);
  });
});

describe("ConsultationPreview — truncation", () => {
  it("shows visible vs total counts, never the raw truncated boolean", () => {
    const entries = Array.from({ length: 10 }, (_, i) => ({
      medication_name: `Obat ${i}`, dosage: "1x", timestamp: `2026-08-2${i % 3}T08:00:00+07:00`,
    }));
    const { container } = render(<ConsultationPreview report={makeReport({
      medication: { entries, total_count_in_period: 24, truncated: true },
    })} />);
    expect(screen.getByText("Menampilkan 10 dari 24 catatan terbaru pada periode ini.")).toBeInTheDocument();
    expect(container.textContent).not.toContain("truncated");
  });

  it("shows no truncation notice when the list is not truncated", () => {
    render(<ConsultationPreview report={makeReport({
      medication: { entries: [{ medication_name: "Obat A", dosage: null, timestamp: "2026-08-20T08:00:00+07:00" }], total_count_in_period: 1, truncated: false },
    })} />);
    expect(screen.queryByText(/Menampilkan/)).not.toBeInTheDocument();
  });
});

describe("ConsultationPreview — unknown section & error containment", () => {
  it("does not expose raw data for an unknown future section code", () => {
    const { container } = render(<ConsultationPreview report={makeReport({ some_future_section: { weird: "shape", nested: { a: 1 } } })} />);
    expect(screen.getByText("Bagian ini belum didukung pada versi aplikasi ini.")).toBeInTheDocument();
    expect(container.textContent).not.toContain("weird");
    expect(container.textContent).not.toContain("nested");
  });

  it("contains a malformed section's crash without breaking sibling sections", () => {
    const spy = vi.spyOn(console, "error").mockImplementation(() => {});
    render(<ConsultationPreview report={makeReport({
      // `entries` sengaja BUKAN array (bentuk yang nggak terduga) --
      // renderer illness manggil `.map` di atasnya, harus nge-throw.
      illness: { entries: "not-an-array", total_count_in_period: 1, truncated: false },
      feeding: { total_events: 3, avg_events_per_day: 0.4, by_type: { asi_langsung: 2, asi_perah: 1, sufor: 0, mpasi: 0 }, total_volume_ml: 0, events_with_volume: 0 },
    })} />);
    expect(screen.getByText("Bagian ini tidak dapat ditampilkan.")).toBeInTheDocument();
    expect(screen.getByText("3 kali")).toBeInTheDocument();
    expect(screen.getByText("2 kali")).toBeInTheDocument();
    spy.mockRestore();
  });
});

describe("ConsultationPreview — sensitive badges", () => {
  it("shows the Sensitif badge as text on sensitive sections, not on non-sensitive ones", () => {
    render(<ConsultationPreview report={makeReport({
      feeding: { total_events: 0 },
      medication: { entries: [], total_count_in_period: 0, truncated: false },
    })} />);
    const badges = screen.getAllByText("Sensitif");
    expect(badges.length).toBe(1);
    expect(badges[0].closest("section")).toHaveTextContent("Riwayat Obat");
  });
});
