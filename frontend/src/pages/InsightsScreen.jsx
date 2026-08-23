import { useCallback, useEffect, useRef, useState } from "react";
import {
  BarChart, Bar, LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
} from "recharts";
import { api, ApiError } from "../api/client";
import {
  cacheInsightSnapshot, getCachedInsightSnapshot,
} from "../utils/insightCache";
import { describeInsightCard } from "../utils/insightCodes";

const PERIOD_OPTIONS = [
  { key: "7d", label: "7 Hari" },
  { key: "30d", label: "30 Hari" },
];

const DISCLAIMER_TEXT =
  "Insight ini berdasarkan catatan yang dimasukkan dan bukan diagnosis medis. " +
  "Hubungi tenaga kesehatan jika Anda memiliki kekhawatiran tentang kondisi anak.";

function useOnlineStatus() {
  const [isOnline, setIsOnline] = useState(navigator.onLine);
  useEffect(() => {
    const goOnline = () => setIsOnline(true);
    const goOffline = () => setIsOnline(false);
    window.addEventListener("online", goOnline);
    window.addEventListener("offline", goOffline);
    return () => {
      window.removeEventListener("online", goOnline);
      window.removeEventListener("offline", goOffline);
    };
  }, []);
  return isOnline;
}

function fmtDay(iso) {
  try {
    return new Date(iso).toLocaleDateString("id-ID", { day: "2-digit", month: "short" });
  } catch (_) {
    return iso;
  }
}

function fmtDateTime(iso) {
  if (!iso) return "";
  try {
    return new Date(iso).toLocaleString("id-ID", { dateStyle: "medium", timeStyle: "short" });
  } catch (_) {
    return iso;
  }
}

function fmtDate(iso) {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleDateString("id-ID", { day: "2-digit", month: "long", year: "numeric" });
  } catch (_) {
    return iso;
  }
}

function fmtMinutesAsHours(minutes) {
  if (minutes == null) return "—";
  const h = Math.floor(minutes / 60);
  const m = Math.round(minutes % 60);
  if (h === 0) return `${m} menit`;
  if (m === 0) return `${h} jam`;
  return `${h} jam ${m} menit`;
}

function fmtSigned(value, unit) {
  if (value == null) return "—";
  const sign = value > 0 ? "+" : "";
  return `${sign}${value}${unit}`;
}

function fmtPercent(pct) {
  if (pct == null) return "Data pembanding belum cukup";
  const sign = pct > 0 ? "+" : "";
  return `${sign}${pct}%`;
}

/** Card kecil "angka + label", dipakai buat ringkasan tiap domain. */
function StatCard({ value, label, sub }) {
  return (
    <div className="bg-void-card border border-void-hairline rounded-xl2 p-4">
      <p className="text-2xl font-display text-ink">{value}</p>
      <p className="text-xs text-ink-faint">{label}</p>
      {sub && <p className="text-[11px] text-ink-faint mt-0.5">{sub}</p>}
    </div>
  );
}

function SectionCard({ title, children }) {
  return (
    <div className="bg-void-card border border-void-hairline rounded-xl2 p-4 mb-4 shadow-soft">
      <p className="text-xs text-ink-faint font-mono uppercase tracking-wider mb-3">{title}</p>
      {children}
    </div>
  );
}

function ComparisonRow({ label, comparison, unit, formatValue }) {
  if (!comparison) return null;
  const fmt = formatValue || ((v) => `${v}${unit || ""}`);
  return (
    <div className="flex items-center justify-between py-2 border-b border-void-hairline last:border-b-0">
      <div>
        <p className="text-sm text-ink">{label}</p>
        <p className="text-[11px] text-ink-faint">
          {fmt(comparison.current)} (sebelumnya {fmt(comparison.previous)})
        </p>
      </div>
      <p className={`text-sm font-semibold ${comparison.change > 0 ? "text-feed" : comparison.change < 0 ? "text-warn" : "text-ink-muted"}`}>
        {fmtPercent(comparison.percent_change)}
      </p>
    </div>
  );
}

function TrendChart({ title, data, dataKey, unit, color, summary }) {
  if (!data || data.length === 0) return null;
  return (
    <SectionCard title={title}>
      <div className="h-40">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={data} margin={{ top: 5, right: 5, left: -25, bottom: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#F0E2CC" vertical={false} />
            <XAxis dataKey="date" tickFormatter={fmtDay} tick={{ fontSize: 10, fill: "#9C8F82" }} tickLine={false} axisLine={{ stroke: "#F0E2CC" }} />
            <YAxis tick={{ fontSize: 10, fill: "#9C8F82" }} tickLine={false} axisLine={false} width={30} allowDecimals={false} />
            <Tooltip formatter={(v) => [`${v} ${unit}`, ""]} labelFormatter={fmtDay} />
            <Bar dataKey={dataKey} fill={color} radius={[4, 4, 0, 0]} />
          </BarChart>
        </ResponsiveContainer>
      </div>
      {/* Ringkasan TEKSTUAL — bukan cuma mengandalkan warna/bentuk grafik
          buat nyampein makna (requirement aksesibilitas). */}
      <p className="text-[11px] text-ink-faint mt-2">{summary}</p>
    </SectionCard>
  );
}

/**
 * "✨ Insight" — ringkasan 7/30 hari BACA-SAJA (Smart Insights & Weekly
 * Summary, Phase 1). Semua role (owner/editor/viewer) lihat tampilan
 * yang SAMA PERSIS — TIDAK ADA kontrol mutasi apa pun di layar ini,
 * jadi tidak ada yang perlu disembunyikan per-role (lihat
 * backend/docs/INSIGHTS.md bagian Otorisasi).
 */
export default function InsightsScreen({ child, currentUserId }) {
  const isOnline = useOnlineStatus();
  const [period, setPeriod] = useState("7d");
  // loading | ready | offline_cached | offline_no_cache | error
  const [status, setStatus] = useState("loading");
  const [data, setData] = useState(null);
  const [cachedAt, setCachedAt] = useState(null);
  const [errorMessage, setErrorMessage] = useState("");
  const firstLoadRef = useRef(true);

  const loadCachedFallback = useCallback(() => {
    const cached = getCachedInsightSnapshot(currentUserId, child.id);
    if (cached) {
      setData(cached.data);
      setCachedAt(cached.cachedAt);
      setStatus("offline_cached");
    } else {
      setData(null);
      setCachedAt(null);
      setStatus("offline_no_cache");
    }
  }, [currentUserId, child.id]);

  const load = useCallback(async () => {
    if (!isOnline) {
      loadCachedFallback();
      return;
    }
    setStatus((prev) => (prev === "ready" || prev === "offline_cached" ? prev : "loading"));
    setErrorMessage("");
    try {
      const res = await api.getInsights(child.id, period);
      setData(res);
      setCachedAt(null);
      setStatus("ready");
      cacheInsightSnapshot(currentUserId, child.id, res);
    } catch (err) {
      if (err instanceof ApiError && err.kind === "network") {
        // Server nggak kesentuh sama sekali (walau browser bilang
        // online) — perlakukan SAMA kayak offline: coba cache.
        loadCachedFallback();
        return;
      }
      setStatus("error");
      setErrorMessage(err?.message || "Gagal memuat insight.");
    }
  }, [child.id, period, isOnline, currentUserId, loadCachedFallback]);

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [child.id, period, isOnline]);

  useEffect(() => {
    firstLoadRef.current = false;
  }, []);

  const metrics = data?.metrics;
  const comparisons = data?.comparisons;
  const insights = data?.insights || [];
  const periodDays = data?.period?.days || (period === "30d" ? 30 : 7);
  const hasAnyData = data?.data_quality?.has_any_data;

  return (
    <div className="min-h-screen pb-16 px-6 pt-8">
      <h1 className="font-display text-3xl text-ink mb-1">✨ Insight</h1>
      <p className="text-sm text-ink-muted mb-4">
        Ringkasan pola {periodDays} hari terakhir {child.nickname || child.name}
      </p>

      <div
        role="note"
        aria-label="Peringatan bukan diagnosis medis"
        className="text-[11px] text-ink-muted bg-void border border-void-hairline rounded-xl2 px-3 py-2.5 mb-4"
      >
        {DISCLAIMER_TEXT}
      </div>

      <div className="flex gap-2 mb-4" role="group" aria-label="Pilih periode insight">
        {PERIOD_OPTIONS.map((opt) => (
          <button
            key={opt.key}
            type="button"
            onClick={() => setPeriod(opt.key)}
            aria-pressed={period === opt.key}
            className={`flex-1 py-2.5 rounded-xl2 border text-xs font-medium ${
              period === opt.key ? "bg-feed/15 border-feed text-feed" : "bg-void-card border-void-hairline text-ink-muted"
            }`}
          >
            {opt.label}
          </button>
        ))}
      </div>

      {status === "offline_cached" && (
        <p className="text-[11px] text-warn bg-warn/10 border border-warn/30 rounded-lg px-3 py-2 mb-4">
          Menampilkan ringkasan terakhir saat offline — dibuat {fmtDateTime(cachedAt)}.
        </p>
      )}

      {status === "loading" && (
        <div className="space-y-3" aria-live="polite" aria-busy="true">
          <p className="text-ink-faint text-sm text-center py-2">Memuat insight...</p>
          {[0, 1, 2].map((i) => (
            <div key={i} className="h-16 bg-void-card border border-void-hairline rounded-xl2 animate-pulse" />
          ))}
        </div>
      )}

      {status === "error" && (
        <div className="text-center py-6 space-y-3">
          <p className="text-warn text-sm">{errorMessage}</p>
          <button
            onClick={load}
            className="px-4 py-2 rounded-lg border border-void-hairline text-ink-muted text-sm font-medium"
          >
            Coba lagi
          </button>
        </div>
      )}

      {status === "offline_no_cache" && (
        <div className="text-center py-10 px-4">
          <p className="text-3xl mb-3">📡</p>
          <p className="text-ink text-sm font-medium mb-1">Belum ada ringkasan tersimpan</p>
          <p className="text-ink-faint text-xs">
            Sambungkan ke internet minimal sekali dulu supaya insight bisa dilihat offline setelahnya.
          </p>
        </div>
      )}

      {(status === "ready" || status === "offline_cached") && data && !hasAnyData && (
        <div className="text-center py-10 px-4 bg-void-card border border-void-hairline rounded-xl2">
          <p className="text-3xl mb-3">🌱</p>
          <p className="text-ink text-sm font-medium mb-1">Data belum cukup</p>
          <p className="text-ink-faint text-xs">
            Belum ada catatan di {periodDays} hari terakhir. Catat aktivitas harian dulu supaya insight bisa dihitung.
          </p>
        </div>
      )}

      {(status === "ready" || status === "offline_cached") && data && hasAnyData && (
        <>
          <div className="grid grid-cols-2 gap-3 mb-4">
            <StatCard
              value={metrics.feeding.total_events}
              label="Menyusui tercatat"
              sub={`rata-rata ${metrics.feeding.avg_events_per_day}x/hari`}
            />
            <StatCard
              value={fmtMinutesAsHours(metrics.sleep.total_completed_minutes)}
              label="Tidur (sesi selesai)"
              sub={metrics.sleep.unfinished_session_count > 0 ? `${metrics.sleep.unfinished_session_count} sesi masih berjalan` : undefined}
            />
            <StatCard
              value={metrics.diaper.total_events}
              label="Ganti popok"
              sub={`${metrics.diaper.pipis_count} pipis, ${metrics.diaper.bab_count} BAB`}
            />
            <StatCard
              value={metrics.pumping.session_count}
              label="Sesi pumping"
              sub={metrics.pumping.events_with_volume > 0 ? `total ${metrics.pumping.total_volume_ml} ml` : "belum ada data volume"}
            />
          </div>

          <TrendChart
            title="Tren Menyusui"
            data={metrics.feeding.daily_trend}
            dataKey="count"
            unit="kali"
            color="#FFA733"
            summary={`Total ${metrics.feeding.total_events} kali menyusui dalam ${periodDays} hari, rata-rata ${metrics.feeding.avg_events_per_day} kali per hari.`}
          />

          <TrendChart
            title="Tren Tidur"
            data={metrics.sleep.daily_trend}
            dataKey="total_minutes"
            unit="menit"
            color="#9B87E0"
            summary={`Total ${fmtMinutesAsHours(metrics.sleep.total_completed_minutes)} tidur tercatat (sesi selesai saja) dalam ${periodDays} hari.`}
          />

          <SectionCard title="Dibanding Periode Sebelumnya">
            <ComparisonRow label="Menyusui" comparison={comparisons.feeding_count} unit="x" />
            <ComparisonRow label="Volume menyusui" comparison={comparisons.feeding_volume_ml} unit=" ml" />
            <ComparisonRow
              label="Durasi tidur"
              comparison={comparisons.sleep_duration_minutes}
              formatValue={fmtMinutesAsHours}
            />
            <ComparisonRow label="Ganti popok" comparison={comparisons.diaper_count} unit="x" />
            <ComparisonRow label="Volume pumping" comparison={comparisons.pumping_volume_ml} unit=" ml" />
            <ComparisonRow
              label="Durasi aktivitas"
              comparison={comparisons.activity_duration_minutes}
              formatValue={fmtMinutesAsHours}
            />
          </SectionCard>

          <SectionCard title="Tumbuh Kembang">
            {metrics.growth.latest ? (
              <div className="space-y-1 text-sm text-ink">
                <p>Pengukuran terakhir: {fmtDate(metrics.growth.latest.measured_date)}</p>
                <div className="flex gap-4 text-xs text-ink-muted">
                  <span>Berat {fmtSigned(metrics.growth.weight_change_kg, " kg")}</span>
                  <span>Tinggi {fmtSigned(metrics.growth.height_change_cm, " cm")}</span>
                  <span>LK {fmtSigned(metrics.growth.head_circumference_change_cm, " cm")}</span>
                </div>
                {metrics.growth.days_since_latest_measurement > 30 && (
                  <p className="text-[11px] text-ink-faint">
                    {metrics.growth.days_since_latest_measurement} hari sejak pengukuran terakhir.
                  </p>
                )}
              </div>
            ) : (
              <p className="text-sm text-ink-faint">Belum ada pengukuran pertumbuhan tercatat.</p>
            )}
          </SectionCard>

          <SectionCard title="Ringkasan Kesehatan">
            <div className="grid grid-cols-2 gap-2 text-xs text-ink-muted">
              <p>Suhu tercatat: {metrics.health.temperature_record_count}x</p>
              <p>Kunjungan dokter: {metrics.health.doctor_visit_count}x</p>
              <p>Catatan obat: {metrics.health.medication_event_count}x</p>
              <p>Catatan sakit: {metrics.health.illness_record_count}x</p>
            </div>
            {metrics.health.latest_temperature_celsius != null && (
              <p className="text-[11px] text-ink-faint mt-2">
                Suhu terakhir tercatat: {metrics.health.latest_temperature_celsius}°C ({fmtDateTime(metrics.health.latest_temperature_at)})
              </p>
            )}
          </SectionCard>

          {insights.length > 0 && (
            <SectionCard title="Observasi">
              <ul className="space-y-2">
                {insights.map((card, i) => (
                  <li key={i} className="text-sm text-ink bg-void border border-void-hairline rounded-lg px-3 py-2.5">
                    {describeInsightCard(card, periodDays)}
                  </li>
                ))}
              </ul>
            </SectionCard>
          )}
        </>
      )}
    </div>
  );
}
