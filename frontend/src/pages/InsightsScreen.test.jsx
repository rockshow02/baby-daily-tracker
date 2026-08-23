import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import InsightsScreen from "./InsightsScreen";
import { cacheInsightSnapshot } from "../utils/insightCache";

const { apiMock } = vi.hoisted(() => ({
  apiMock: { getInsights: vi.fn() },
}));

vi.mock("../api/client", async (importOriginal) => {
  const actual = await importOriginal();
  return { ...actual, api: apiMock };
});

const { ApiError } = await import("../api/client");

const testChild = { id: 10, name: "Anak Satu", nickname: "Dedek" };
const CURRENT_USER_ID = 1;

function setOnline(value) {
  Object.defineProperty(window.navigator, "onLine", { value, configurable: true });
}

function makeInsightResponse(overrides = {}) {
  return {
    child_id: 10,
    period: { key: "7d", start_date: "2026-08-17", end_date: "2026-08-23", timezone: "Asia/Jakarta", days: 7 },
    previous_period: { start_date: "2026-08-10", end_date: "2026-08-16" },
    metrics: {
      feeding: {
        total_events: 10, avg_events_per_day: 1.4,
        by_type: { asi_langsung: 5, asi_perah: 0, sufor: 5, mpasi: 0 },
        total_volume_ml: 500, events_with_volume: 5, avg_volume_ml_per_event: 100,
        daily_trend: [{ date: "2026-08-17", count: 1 }, { date: "2026-08-18", count: 2 }],
      },
      sleep: {
        completed_session_count: 7, unfinished_session_count: 1, total_completed_minutes: 420,
        avg_duration_minutes_per_session: 60, avg_minutes_per_day: 60,
        daily_trend: [{ date: "2026-08-17", total_minutes: 60 }],
      },
      diaper: { total_events: 14, pipis_count: 10, bab_count: 6, combined_count: 2, avg_events_per_day: 2, daily_trend: [] },
      pumping: { session_count: 3, total_volume_ml: 300, events_with_volume: 3, avg_volume_ml_per_event: 100, total_duration_minutes: 45, events_with_duration: 3, daily_trend: [] },
      growth: {
        latest: { measured_date: "2026-08-01", weight_kg: 5, height_cm: 60, head_circumference_cm: 38 },
        previous: { measured_date: "2026-07-01", weight_kg: 4.5, height_cm: 58, head_circumference_cm: 37 },
        weight_change_kg: 0.5, height_change_cm: 2, head_circumference_change_cm: 1,
        days_since_latest_measurement: 22,
      },
      health: {
        temperature_record_count: 1, latest_temperature_celsius: 37.2, latest_temperature_at: "2026-08-20T10:00:00+07:00",
        medication_event_count: 0, doctor_visit_count: 0, illness_record_count: 0,
      },
      activity: { session_count: 2, total_duration_minutes: 40, events_with_duration: 2, daily_trend: [] },
      mood: { counts: { ceria: 3, baik: 2, sedih: 1, menangis: 0 }, total_events: 6 },
      milestones: { count_in_period: 1, latest_milestone_type: "bisa_duduk", latest_milestone_date: "2026-08-18" },
    },
    comparisons: {
      feeding_count: { current: 10, previous: 8, change: 2, percent_change: 25.0 },
      feeding_volume_ml: { current: 500, previous: 400, change: 100, percent_change: 25.0 },
      sleep_duration_minutes: { current: 420, previous: 0, change: 420, percent_change: null },
      diaper_count: { current: 14, previous: 14, change: 0, percent_change: 0 },
      pumping_volume_ml: { current: 300, previous: 200, change: 100, percent_change: 50.0 },
      activity_duration_minutes: { current: 40, previous: 60, change: -20, percent_change: -33.3 },
    },
    insights: [
      { code: "sleep_duration_increased", severity: "info", metric: "sleep_duration_minutes", direction: "up", value: 420 },
    ],
    data_quality: { has_any_data: true, days_with_records: 6, missing_volume_count: 5, unfinished_sleep_count: 1 },
    generated_at: "2026-08-23T01:00:00Z",
    request_id: "req-1",
    ...overrides,
  };
}

const DISCLAIMER_TEXT =
  "Insight ini berdasarkan catatan yang dimasukkan dan bukan diagnosis medis. " +
  "Hubungi tenaga kesehatan jika Anda memiliki kekhawatiran tentang kondisi anak.";

beforeEach(() => {
  setOnline(true);
  localStorage.clear();
  apiMock.getInsights.mockReset();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("InsightsScreen — loading/success/empty/error states", () => {
  it("shows a loading state while the request is in flight", async () => {
    let resolvePromise;
    apiMock.getInsights.mockReturnValue(new Promise((resolve) => { resolvePromise = resolve; }));
    render(<InsightsScreen child={testChild} currentUserId={CURRENT_USER_ID} />);
    expect(screen.getByText("Memuat insight...")).toBeInTheDocument();
    resolvePromise(makeInsightResponse());
    await waitFor(() => expect(screen.queryByText("Memuat insight...")).not.toBeInTheDocument());
  });

  it("renders overview cards on success", async () => {
    apiMock.getInsights.mockResolvedValue(makeInsightResponse());
    render(<InsightsScreen child={testChild} currentUserId={CURRENT_USER_ID} />);
    expect(await screen.findByText("Menyusui tercatat")).toBeInTheDocument();
    expect(screen.getByText("10")).toBeInTheDocument();
  });

  it("shows a dedicated insufficient-data state when has_any_data is false", async () => {
    apiMock.getInsights.mockResolvedValue(
      makeInsightResponse({
        data_quality: { has_any_data: false, days_with_records: 0, missing_volume_count: 0, unfinished_sleep_count: 0 },
        insights: [{ code: "insufficient_data", severity: "info", metric: null, direction: null, value: null }],
      }),
    );
    render(<InsightsScreen child={testChild} currentUserId={CURRENT_USER_ID} />);
    expect(await screen.findByText("Data belum cukup")).toBeInTheDocument();
    expect(screen.queryByText("Menyusui tercatat")).not.toBeInTheDocument();
  });

  it("shows a retryable error state on a non-network failure (e.g. server error)", async () => {
    apiMock.getInsights.mockRejectedValue(new ApiError({ kind: "server_error", status: 500, message: "Terjadi kesalahan pada server." }));
    render(<InsightsScreen child={testChild} currentUserId={CURRENT_USER_ID} />);
    expect(await screen.findByText("Terjadi kesalahan pada server.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Coba lagi" })).toBeInTheDocument();
  });

  it("shows a readable empty offline state when offline with no cache", async () => {
    setOnline(false);
    render(<InsightsScreen child={testChild} currentUserId={CURRENT_USER_ID} />);
    expect(await screen.findByText("Belum ada ringkasan tersimpan")).toBeInTheDocument();
    expect(apiMock.getInsights).not.toHaveBeenCalled();
  });
});

describe("InsightsScreen — offline cached snapshot", () => {
  it("restores the cached snapshot for the correct user and child when offline", async () => {
    cacheInsightSnapshot(CURRENT_USER_ID, testChild.id, makeInsightResponse());
    setOnline(false);
    render(<InsightsScreen child={testChild} currentUserId={CURRENT_USER_ID} />);
    expect(await screen.findByText("Menyusui tercatat")).toBeInTheDocument();
    expect(screen.getByText(/Menampilkan ringkasan terakhir saat offline/)).toBeInTheDocument();
  });

  it("never shows another child's cached snapshot", async () => {
    cacheInsightSnapshot(CURRENT_USER_ID, 999, makeInsightResponse());
    setOnline(false);
    render(<InsightsScreen child={testChild} currentUserId={CURRENT_USER_ID} />);
    expect(await screen.findByText("Belum ada ringkasan tersimpan")).toBeInTheDocument();
  });

  it("never shows another user's cached snapshot", async () => {
    cacheInsightSnapshot(999, testChild.id, makeInsightResponse());
    setOnline(false);
    render(<InsightsScreen child={testChild} currentUserId={CURRENT_USER_ID} />);
    expect(await screen.findByText("Belum ada ringkasan tersimpan")).toBeInTheDocument();
  });

  it("rejects a cache record with a missing/unknown schema version safely", async () => {
    localStorage.setItem(
      `babytracker_insight_cache_v1:${CURRENT_USER_ID}:${testChild.id}`,
      JSON.stringify({ userId: CURRENT_USER_ID, childId: testChild.id, data: makeInsightResponse(), cachedAt: new Date().toISOString() }),
    );
    setOnline(false);
    render(<InsightsScreen child={testChild} currentUserId={CURRENT_USER_ID} />);
    expect(await screen.findByText("Belum ada ringkasan tersimpan")).toBeInTheDocument();
  });

  it("falls back to the cached snapshot when the server is unreachable (network error) even while browser reports online", async () => {
    cacheInsightSnapshot(CURRENT_USER_ID, testChild.id, makeInsightResponse());
    apiMock.getInsights.mockRejectedValue(new ApiError({ kind: "network", status: null, message: "Nggak ada koneksi internet." }));
    render(<InsightsScreen child={testChild} currentUserId={CURRENT_USER_ID} />);
    expect(await screen.findByText(/Menampilkan ringkasan terakhir saat offline/)).toBeInTheDocument();
  });
});

describe("InsightsScreen — reconnect", () => {
  it("automatically refreshes when the browser comes back online", async () => {
    cacheInsightSnapshot(CURRENT_USER_ID, testChild.id, makeInsightResponse({ metrics: { ...makeInsightResponse().metrics, feeding: { ...makeInsightResponse().metrics.feeding, total_events: 999 } } }));
    setOnline(false);
    const { rerender } = render(<InsightsScreen child={testChild} currentUserId={CURRENT_USER_ID} />);
    expect(await screen.findByText(/Menampilkan ringkasan terakhir saat offline/)).toBeInTheDocument();

    apiMock.getInsights.mockResolvedValue(makeInsightResponse());
    setOnline(true);
    window.dispatchEvent(new Event("online"));
    rerender(<InsightsScreen child={testChild} currentUserId={CURRENT_USER_ID} />);

    await waitFor(() => expect(apiMock.getInsights).toHaveBeenCalled());
    await waitFor(() => expect(screen.queryByText(/Menampilkan ringkasan terakhir saat offline/)).not.toBeInTheDocument());
  });
});

describe("InsightsScreen — period selection", () => {
  it("sends the correct period when switching to 30 Hari", async () => {
    apiMock.getInsights.mockResolvedValue(makeInsightResponse());
    render(<InsightsScreen child={testChild} currentUserId={CURRENT_USER_ID} />);
    await screen.findByText("Menyusui tercatat");
    expect(apiMock.getInsights).toHaveBeenCalledWith(testChild.id, "7d");

    const { fireEvent } = await import("@testing-library/react");
    fireEvent.click(screen.getByRole("button", { name: "30 Hari" }));

    await waitFor(() => expect(apiMock.getInsights).toHaveBeenCalledWith(testChild.id, "30d"));
  });
});

describe("InsightsScreen — metric formatting & comparisons", () => {
  it("formats sleep duration as hours/minutes, not raw number of minutes", async () => {
    apiMock.getInsights.mockResolvedValue(makeInsightResponse());
    render(<InsightsScreen child={testChild} currentUserId={CURRENT_USER_ID} />);
    await screen.findByText("Menyusui tercatat");
    // 420 menit == 7 jam
    expect(screen.getAllByText("7 jam").length).toBeGreaterThan(0);
    expect(screen.queryByText("420")).not.toBeInTheDocument();
  });

  it("shows a clear message instead of a misleading percentage when percent_change is null", async () => {
    apiMock.getInsights.mockResolvedValue(makeInsightResponse());
    render(<InsightsScreen child={testChild} currentUserId={CURRENT_USER_ID} />);
    await screen.findByText("Menyusui tercatat");
    expect(screen.getByText("Data pembanding belum cukup")).toBeInTheDocument();
  });

  it("has a readable textual summary alongside the trend chart, not color-only meaning", async () => {
    apiMock.getInsights.mockResolvedValue(makeInsightResponse());
    render(<InsightsScreen child={testChild} currentUserId={CURRENT_USER_ID} />);
    expect(await screen.findByText(/Total 10 kali menyusui dalam 7 hari/)).toBeInTheDocument();
  });
});

describe("InsightsScreen — insight codes", () => {
  it("known insight codes render translated Indonesian text, never the raw code", async () => {
    apiMock.getInsights.mockResolvedValue(makeInsightResponse());
    render(<InsightsScreen child={testChild} currentUserId={CURRENT_USER_ID} />);
    expect(await screen.findByText(/Durasi tidur tercatat meningkat 420 menit/)).toBeInTheDocument();
    expect(screen.queryByText("sleep_duration_increased")).not.toBeInTheDocument();
  });

  it("an unknown insight code falls back to the safe generic text, never a raw code", async () => {
    apiMock.getInsights.mockResolvedValue(
      makeInsightResponse({ insights: [{ code: "brand_new_unreleased_code", severity: "info", metric: null, direction: null, value: null }] }),
    );
    render(<InsightsScreen child={testChild} currentUserId={CURRENT_USER_ID} />);
    expect(await screen.findByText("Ada observasi baru dari catatanmu.")).toBeInTheDocument();
    expect(screen.queryByText("brand_new_unreleased_code")).not.toBeInTheDocument();
  });
});

describe("InsightsScreen — privacy", () => {
  it("never renders a sensitive value even if it were present somewhere on the payload", async () => {
    const payload = makeInsightResponse();
    payload.metrics.health.doctor_name = "RAHASIA_DOKTER_XYZ"; // field yang backend TIDAK PERNAH kirim (lihat backend/docs/INSIGHTS.md), simulasi defense-in-depth
    apiMock.getInsights.mockResolvedValue(payload);
    render(<InsightsScreen child={testChild} currentUserId={CURRENT_USER_ID} />);
    await screen.findByText("Menyusui tercatat");
    expect(screen.queryByText(/RAHASIA/)).not.toBeInTheDocument();
  });
});

describe("InsightsScreen — role behavior", () => {
  it("never renders any mutation control (this screen is read-only for every role)", async () => {
    apiMock.getInsights.mockResolvedValue(makeInsightResponse());
    render(<InsightsScreen child={testChild} currentUserId={CURRENT_USER_ID} />);
    await screen.findByText("Menyusui tercatat");
    for (const forbidden of ["Hapus", "Edit", "Ubah", "Tambah", "Simpan"]) {
      expect(screen.queryByRole("button", { name: new RegExp(forbidden) })).not.toBeInTheDocument();
    }
  });
});

describe("InsightsScreen — disclaimer", () => {
  it("is visible on the success state", async () => {
    apiMock.getInsights.mockResolvedValue(makeInsightResponse());
    render(<InsightsScreen child={testChild} currentUserId={CURRENT_USER_ID} />);
    expect(screen.getByText(DISCLAIMER_TEXT)).toBeInTheDocument();
  });

  it("is visible on the loading state", () => {
    apiMock.getInsights.mockReturnValue(new Promise(() => {}));
    render(<InsightsScreen child={testChild} currentUserId={CURRENT_USER_ID} />);
    expect(screen.getByText(DISCLAIMER_TEXT)).toBeInTheDocument();
  });

  it("is visible on the error state", async () => {
    apiMock.getInsights.mockRejectedValue(new ApiError({ kind: "server_error", status: 500, message: "Gagal." }));
    render(<InsightsScreen child={testChild} currentUserId={CURRENT_USER_ID} />);
    await screen.findByRole("button", { name: "Coba lagi" });
    expect(screen.getByText(DISCLAIMER_TEXT)).toBeInTheDocument();
  });

  it("is visible on the offline-no-cache state", async () => {
    setOnline(false);
    render(<InsightsScreen child={testChild} currentUserId={CURRENT_USER_ID} />);
    await screen.findByText("Belum ada ringkasan tersimpan");
    expect(screen.getByText(DISCLAIMER_TEXT)).toBeInTheDocument();
  });
});
