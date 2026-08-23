import SummaryGrid from "./SummaryGrid";
import DetailList, { DetailListItem } from "./DetailList";
import EmptySectionState from "./EmptySectionState";
import PartialDataNotice from "./PartialDataNotice";
import TruncationNotice from "./TruncationNotice";
import {
  MISSING_VALUE, formatDateTimeWIB, formatDateWIB, formatDurationMinutes,
  formatInt, formatRatePerDay, formatRecordCount, formatTemperatureC, formatTimes,
  formatVolumeMl, formatWeightKg, formatLengthCm, orDash,
} from "../../utils/consultationFormat";
import {
  describeFeedType, describeGender, describeMilestoneType, describeMood, describeVaccinationStatus,
} from "../../utils/consultationLabels";

/** Tanggal murni ("YYYY-MM-DD") ATAU datetime ISO ("...T...+07:00") berada di dalam [start, end] ("YYYY-MM-DD") -- perbandingan STRING langsung, sah buat format tanggal ISO zero-padded. */
function isWithinPeriod(dateOrDateTime, period) {
  if (!dateOrDateTime || !period) return true;
  const datePart = dateOrDateTime.slice(0, 10);
  return datePart >= period.start_date && datePart <= period.end_date;
}

function ChildSummarySection({ section }) {
  const genderLabel = describeGender(section?.gender);
  return (
    <SummaryGrid
      rows={[
        { label: "Nama", value: orDash(section?.display_name) },
        { label: "Usia (per akhir periode)", value: orDash(section?.age_as_of_report_end) },
        { label: "Tanggal lahir", value: formatDateWIB(section?.birth_date) },
        genderLabel ? { label: "Jenis kelamin", value: genderLabel } : null,
        { label: "Jumlah catatan obat pada periode ini", value: formatRecordCount(section?.medication_event_count_in_period) },
        { label: "Jumlah kunjungan dokter pada periode ini", value: formatRecordCount(section?.doctor_visit_count_in_period) },
        { label: "Jumlah catatan sakit pada periode ini", value: formatRecordCount(section?.illness_record_count_in_period) },
        { label: "Jumlah catatan suhu pada periode ini", value: formatRecordCount(section?.temperature_record_count_in_period) },
      ]}
    />
  );
}

function FeedingSection({ section }) {
  const total = section?.total_events ?? 0;
  if (total === 0) return <EmptySectionState message="Tidak ada catatan menyusui/makan pada periode ini." />;
  const byType = section?.by_type || {};
  const eventsWithVolume = section?.events_with_volume ?? 0;
  return (
    <>
      <SummaryGrid
        rows={[
          { label: "Total sesi", value: formatTimes(total) },
          { label: "Rata-rata per hari", value: formatRatePerDay(section?.avg_events_per_day) },
          { label: describeFeedType("asi_langsung"), value: formatTimes(byType.asi_langsung ?? 0) },
          { label: describeFeedType("asi_perah"), value: formatTimes(byType.asi_perah ?? 0) },
          { label: describeFeedType("sufor"), value: formatTimes(byType.sufor ?? 0) },
          { label: describeFeedType("mpasi"), value: formatTimes(byType.mpasi ?? 0) },
          { label: "Total volume yang tercatat", value: formatVolumeMl(section?.total_volume_ml) },
          { label: "Rata-rata volume per sesi", value: formatVolumeMl(section?.avg_volume_ml_per_event) },
        ]}
      />
      <PartialDataNotice covered={eventsWithVolume} total={total} label="data volume" />
    </>
  );
}

function SleepSection({ section }) {
  const completed = section?.completed_session_count ?? 0;
  const unfinished = section?.unfinished_session_count ?? 0;
  if (completed === 0 && unfinished === 0) return <EmptySectionState message="Tidak ada catatan tidur pada periode ini." />;
  return (
    <>
      <SummaryGrid
        rows={[
          { label: "Sesi selesai", value: formatTimes(completed) },
          { label: "Sesi masih berjalan", value: formatTimes(unfinished) },
          { label: "Total durasi tidur (selesai)", value: formatDurationMinutes(section?.total_completed_minutes) },
          { label: "Rata-rata durasi per sesi", value: formatDurationMinutes(section?.avg_duration_minutes_per_session) },
        ]}
      />
      {unfinished > 0 && (
        <p className="text-xs text-ink-faint italic mt-1">
          Sesi yang masih berjalan tidak dihitung dalam total durasi.
        </p>
      )}
    </>
  );
}

function DiaperSection({ section }) {
  const total = section?.total_events ?? 0;
  if (total === 0) return <EmptySectionState message="Tidak ada catatan popok pada periode ini." />;
  return (
    <SummaryGrid
      rows={[
        { label: "Total ganti popok", value: formatTimes(total) },
        { label: "Pipis", value: formatTimes(section?.pipis_count ?? 0) },
        { label: "BAB", value: formatTimes(section?.bab_count ?? 0) },
        { label: "Pipis + BAB", value: formatTimes(section?.combined_count ?? 0) },
        { label: "Rata-rata per hari", value: formatRatePerDay(section?.avg_events_per_day) },
      ]}
    />
  );
}

function PumpingSection({ section }) {
  const sessions = section?.session_count ?? 0;
  if (sessions === 0) return <EmptySectionState message="Tidak ada catatan memerah ASI pada periode ini." />;
  const eventsWithVolume = section?.events_with_volume ?? 0;
  const eventsWithDuration = section?.events_with_duration ?? 0;
  return (
    <>
      <SummaryGrid
        rows={[
          { label: "Jumlah sesi", value: formatTimes(sessions) },
          { label: "Total volume yang tercatat", value: formatVolumeMl(section?.total_volume_ml) },
          { label: "Rata-rata volume per sesi", value: formatVolumeMl(section?.avg_volume_ml_per_event) },
          { label: "Total durasi yang tercatat", value: formatDurationMinutes(section?.total_duration_minutes) },
        ]}
      />
      <PartialDataNotice covered={eventsWithVolume} total={sessions} label="data volume" />
      <PartialDataNotice covered={eventsWithDuration} total={sessions} label="data durasi" />
    </>
  );
}

function ActivityMoodSection({ section }) {
  const activity = section?.activity || {};
  const mood = section?.mood || {};
  const moodCounts = mood.counts || {};
  const activitySessions = activity.session_count ?? 0;
  const moodTotal = mood.total_events ?? 0;
  if (activitySessions === 0 && moodTotal === 0) {
    return <EmptySectionState message="Tidak ada catatan aktivitas atau suasana hati pada periode ini." />;
  }
  const eventsWithDuration = activity.events_with_duration ?? 0;
  return (
    <div className="space-y-3">
      <div>
        <h4 className="text-xs font-semibold text-ink-faint uppercase tracking-wider mb-1.5">Aktivitas</h4>
        {activitySessions === 0 ? (
          <EmptySectionState message="Tidak ada catatan aktivitas pada periode ini." />
        ) : (
          <>
            <SummaryGrid
              rows={[
                { label: "Jumlah sesi", value: formatTimes(activitySessions) },
                { label: "Total durasi", value: formatDurationMinutes(activity.total_duration_minutes) },
              ]}
            />
            <PartialDataNotice covered={eventsWithDuration} total={activitySessions} label="data durasi" />
          </>
        )}
      </div>
      <div>
        <h4 className="text-xs font-semibold text-ink-faint uppercase tracking-wider mb-1.5">Suasana hati</h4>
        {moodTotal === 0 ? (
          <EmptySectionState message="Tidak ada catatan suasana hati pada periode ini." />
        ) : (
          <SummaryGrid
            rows={[
              { label: describeMood("ceria"), value: formatTimes(moodCounts.ceria ?? 0) },
              { label: describeMood("baik"), value: formatTimes(moodCounts.baik ?? 0) },
              { label: describeMood("sedih"), value: formatTimes(moodCounts.sedih ?? 0) },
              { label: describeMood("menangis"), value: formatTimes(moodCounts.menangis ?? 0) },
              { label: "Total catatan", value: formatRecordCount(moodTotal) },
            ]}
          />
        )}
      </div>
    </div>
  );
}

/**
 * `formatWeightKg`/`formatLengthCm` SUDAH null-safe sendiri (balikin
 * MISSING_VALUE kalau `null`/`undefined`) -- helper ini CUMA nge-pastiin
 * pemanggil eksplisit soal itu di titik-titik yang butuh (previous/
 * changes, field OPSIONAL yang backend boleh nggak isi walau
 * measurement-nya sendiri ADA), TIDAK PERNAH nganggep nilai yang hilang
 * sebagai nol -- lihat requirement review: delta/nilai individual yang
 * `null` WAJIB tetap `—`, literal 0 WAJIB tetap tampil sebagai "0,0".
 */
function GrowthSection({ section, period }) {
  const latest = section?.latest || null;
  const previous = section?.previous || null;
  const measurements = section?.measurements_in_period || [];
  if (!latest && measurements.length === 0) {
    return <EmptySectionState message="Belum ada pengukuran pertumbuhan." />;
  }
  const latestOutsidePeriod = latest && !isWithinPeriod(latest.measured_date, period);
  return (
    <div className="space-y-3">
      {latest && (
        <div>
          <h4 className="text-xs font-semibold text-ink-faint uppercase tracking-wider mb-1.5">Pengukuran terakhir</h4>
          <SummaryGrid
            rows={[
              { label: latestOutsidePeriod ? "Pengukuran terakhir yang tersedia" : "Tanggal", value: formatDateWIB(latest.measured_date) },
              { label: "Berat", value: formatWeightKg(latest.weight_kg) },
              { label: "Tinggi", value: formatLengthCm(latest.height_cm) },
              { label: "Lingkar kepala", value: formatLengthCm(latest.head_circumference_cm) },
              { label: "Hari sejak pengukuran", value: section?.days_since_latest_measurement != null ? `${section.days_since_latest_measurement} hari` : MISSING_VALUE },
            ]}
          />
        </div>
      )}
      {/* Pengukuran sebelumnya & perubahan CUMA ditampilkan kalau
          `previous` beneran ADA -- bukan cuma di-skip diam-diam kalau
          kosong (requirement: jangan sembunyikan section kosong tanpa
          penjelasan), tapi di sini emang TIDAK ADA apa pun buat
          dibandingkan sama sekali kalau nggak ada pengukuran sebelumnya,
          jadi menampilkan grup kosong justru menyesatkan. */}
      {previous && (
        <div>
          <h4 className="text-xs font-semibold text-ink-faint uppercase tracking-wider mb-1.5">Pengukuran sebelumnya</h4>
          <SummaryGrid
            rows={[
              { label: "Tanggal", value: formatDateWIB(previous.measured_date) },
              { label: "Berat", value: formatWeightKg(previous.weight_kg) },
              { label: "Tinggi", value: formatLengthCm(previous.height_cm) },
              { label: "Lingkar kepala", value: formatLengthCm(previous.head_circumference_cm) },
            ]}
          />
        </div>
      )}
      {previous && (
        <div>
          <h4 className="text-xs font-semibold text-ink-faint uppercase tracking-wider mb-1.5">Perubahan sejak pengukuran sebelumnya</h4>
          <SummaryGrid
            rows={[
              { label: "Perubahan berat", value: formatWeightKg(section?.weight_change_kg) },
              { label: "Perubahan tinggi", value: formatLengthCm(section?.height_change_cm) },
              { label: "Perubahan lingkar kepala", value: formatLengthCm(section?.head_circumference_change_cm) },
            ]}
          />
        </div>
      )}
      {measurements.length > 0 ? (
        <div>
          <h4 className="text-xs font-semibold text-ink-faint uppercase tracking-wider mb-1.5">Pengukuran pada periode ini</h4>
          <DetailList>
            {measurements.map((m) => (
              <DetailListItem key={m.measured_date}>
                <p className="font-medium">{formatDateWIB(m.measured_date)}</p>
                <p className="text-ink-muted text-xs mt-0.5">
                  {formatWeightKg(m.weight_kg)} · {formatLengthCm(m.height_cm)}
                  {m.head_circumference_cm != null ? ` · ${formatLengthCm(m.head_circumference_cm)}` : ""}
                </p>
              </DetailListItem>
            ))}
          </DetailList>
          <TruncationNotice visibleCount={measurements.length} totalCount={section?.total_count_in_period} />
        </div>
      ) : (
        <EmptySectionState message="Belum ada pengukuran pertumbuhan pada periode ini." />
      )}
    </div>
  );
}

function TemperatureSection({ section, period }) {
  const count = section?.record_count_in_period ?? 0;
  if (count === 0 && section?.latest_temperature_celsius == null) {
    return <EmptySectionState message="Tidak ada catatan suhu pada periode ini." />;
  }
  const latestOutsidePeriod = section?.latest_temperature_at && !isWithinPeriod(section.latest_temperature_at, period);
  return (
    <SummaryGrid
      rows={[
        { label: "Jumlah catatan pada periode ini", value: formatRecordCount(count) },
        count > 0 ? { label: "Rata-rata suhu pada periode ini", value: formatTemperatureC(section?.avg_celsius_in_period) } : null,
        count > 0 ? { label: "Suhu terendah pada periode ini", value: formatTemperatureC(section?.min_celsius_in_period) } : null,
        count > 0 ? { label: "Suhu tertinggi pada periode ini", value: formatTemperatureC(section?.max_celsius_in_period) } : null,
        { label: latestOutsidePeriod ? "Suhu terakhir yang tersedia" : "Suhu terakhir", value: formatTemperatureC(section?.latest_temperature_celsius) },
      ]}
    />
  );
}

function IllnessSection({ section }) {
  const entries = section?.entries || [];
  if (entries.length === 0) return <EmptySectionState message="Tidak ada catatan sakit pada periode ini." />;
  return (
    <>
      <DetailList>
        {entries.map((e, i) => (
          <DetailListItem key={`${e.illness_name}-${e.start_date}-${i}`}>
            <p className="font-medium">{orDash(e.illness_name)}</p>
            <p className="text-ink-muted text-xs mt-0.5">
              {formatDateWIB(e.start_date)} – {e.is_ongoing ? "Masih berlangsung" : formatDateWIB(e.end_date)}
            </p>
            {e.symptoms && <p className="text-ink-muted text-xs mt-1">Gejala: {e.symptoms}</p>}
          </DetailListItem>
        ))}
      </DetailList>
      <TruncationNotice visibleCount={entries.length} totalCount={section?.total_count_in_period} />
    </>
  );
}

/**
 * Ringkasan kepatuhan jadwal obat (Medication Schedule & Adherence Phase
 * 1) -- `section.adherence_summary` datang PERSIS apa adanya dari
 * utils/consultation_report.py:_medication_adherence_summary, murni
 * angka agregat (JAMU nama obat/instruksi per-jadwal). `null` berarti
 * child ini nggak punya jadwal obat yang overlap periode ini SAMA
 * SEKALI -- TIDAK dirender apa-apa (bukan tabel nol), beda dari
 * `entries` (riwayat MedicationLog) yang independen bisa tetap kosong
 * ATAU terisi terlepas dari ada/tidaknya jadwal.
 */
function MedicationAdherenceSummary({ adherence }) {
  if (!adherence) return null;
  return (
    <div className="mt-4">
      <p className="text-xs text-ink-faint font-mono uppercase tracking-wider mb-2">
        Ringkasan Kepatuhan Jadwal Obat
      </p>
      <SummaryGrid
        rows={[
          { label: "Jumlah jadwal obat aktif pada periode ini", value: formatInt(adherence.schedule_count) },
          { label: "Dosis yang dijadwalkan", value: formatInt(adherence.expected_count) },
          { label: "Dosis diberikan", value: formatInt(adherence.administered_count) },
          { label: "Dosis dilewati", value: formatInt(adherence.skipped_count) },
          { label: "Dosis terlambat diberikan", value: formatInt(adherence.late_administered_count) },
          { label: "Dosis belum diselesaikan (lewat jadwal)", value: formatInt(adherence.overdue_unresolved_count) },
          {
            label: "Persentase kepatuhan",
            value: adherence.adherence_percentage == null ? MISSING_VALUE : `${adherence.adherence_percentage}%`,
          },
        ]}
      />
    </div>
  );
}

function MedicationSection({ section }) {
  const entries = section?.entries || [];
  return (
    <>
      {entries.length === 0 ? (
        <EmptySectionState message="Tidak ada catatan obat pada periode ini." />
      ) : (
        <>
          <DetailList>
            {entries.map((e, i) => (
              <DetailListItem key={`${e.medication_name}-${e.timestamp}-${i}`}>
                <p className="font-medium">{orDash(e.medication_name)}</p>
                <p className="text-ink-muted text-xs mt-0.5">
                  {e.dosage ? `${e.dosage} · ` : ""}{formatDateTimeWIB(e.timestamp)}
                </p>
              </DetailListItem>
            ))}
          </DetailList>
          <TruncationNotice visibleCount={entries.length} totalCount={section?.total_count_in_period} />
        </>
      )}
      <MedicationAdherenceSummary adherence={section?.adherence_summary} />
    </>
  );
}

function VaccinationSection({ section }) {
  const vaccinations = section?.vaccinations || [];
  if (vaccinations.length === 0) return <EmptySectionState message="Belum ada jadwal vaksinasi yang tersedia." />;
  return (
    <DetailList>
      {vaccinations.map((v) => (
        <DetailListItem key={v.vaccine_schedule_id}>
          <div className="flex items-center justify-between gap-2">
            <p className="font-medium">
              {orDash(v.vaccine_name)}{v.dose_label ? ` (${v.dose_label})` : ""}
            </p>
            <span
              className={`flex-shrink-0 text-[11px] font-semibold px-2 py-0.5 rounded-full ${
                v.given ? "bg-feed/15 text-feed" : "bg-void-hairline text-ink-muted"
              }`}
            >
              {describeVaccinationStatus(v.given)}
            </span>
          </div>
          {v.given_date && <p className="text-ink-muted text-xs mt-0.5">Diberikan: {formatDateWIB(v.given_date)}</p>}
        </DetailListItem>
      ))}
    </DetailList>
  );
}

function MilestonesSection({ section }) {
  const entries = section?.entries || [];
  if (entries.length === 0) return <EmptySectionState message="Belum ada milestone yang tercatat." />;
  return (
    <>
      <DetailList>
        {entries.map((e, i) => (
          <DetailListItem key={`${e.milestone_type}-${e.achieved_date}-${i}`}>
            <p className="font-medium">{describeMilestoneType(e.milestone_type)}</p>
            <p className="text-ink-muted text-xs mt-0.5">{formatDateWIB(e.achieved_date)}</p>
          </DetailListItem>
        ))}
      </DetailList>
      <TruncationNotice visibleCount={entries.length} totalCount={section?.total_count_in_period} />
    </>
  );
}

function DoctorVisitsSection({ section }) {
  const entries = section?.entries || [];
  if (entries.length === 0) return <EmptySectionState message="Tidak ada kunjungan dokter pada periode ini." />;
  return (
    <>
      <DetailList>
        {entries.map((e, i) => (
          <DetailListItem key={`${e.visit_date}-${i}`}>
            <p className="font-medium">{formatDateWIB(e.visit_date)}</p>
            <p className="text-ink-muted text-xs mt-0.5">{orDash(e.doctor_name || e.clinic_name)}</p>
            {e.reason && <p className="text-ink-muted text-xs mt-1">Keluhan: {e.reason}</p>}
            {e.diagnosis && <p className="text-ink-muted text-xs mt-0.5">Diagnosis: {e.diagnosis}</p>}
          </DetailListItem>
        ))}
      </DetailList>
      <TruncationNotice visibleCount={entries.length} totalCount={section?.total_count_in_period} />
    </>
  );
}

function InsightsSection({ section }) {
  const cards = section?.insights || [];
  const hasAnyData = section?.data_quality?.has_any_data;
  if (!hasAnyData || cards.length === 0 || (cards.length === 1 && cards[0]?.code === "insufficient_data")) {
    return <EmptySectionState message="Data belum cukup untuk menyimpulkan pola." />;
  }
  return (
    <div className="space-y-2">
      {cards.map((card, i) => (
        <div key={card.code || i} role="note" className="flex gap-2 bg-void-card border border-void-hairline rounded-xl2 px-3 py-2.5">
          <span aria-hidden="true">ℹ️</span>
          <p className="text-sm text-ink">{orDash(card.description)}</p>
        </div>
      ))}
    </div>
  );
}

function QuestionsSection({ section }) {
  const text = section?.text || "";
  if (!text) return <EmptySectionState message="Tidak ada pertanyaan yang ditambahkan." />;
  return <p className="text-sm text-ink whitespace-pre-wrap break-words">{text}</p>;
}

function NoteSection({ section }) {
  const text = section?.text || "";
  if (!text) return <EmptySectionState message="Tidak ada catatan tambahan yang ditambahkan." />;
  return <p className="text-sm text-ink whitespace-pre-wrap break-words">{text}</p>;
}

function UnavailableSection() {
  return <EmptySectionState message="Bagian ini belum didukung pada versi aplikasi ini." />;
}

export const SECTION_RENDERERS = {
  child_summary: ChildSummarySection,
  feeding: FeedingSection,
  sleep: SleepSection,
  diaper: DiaperSection,
  pumping: PumpingSection,
  activity_mood: ActivityMoodSection,
  growth: GrowthSection,
  temperature: TemperatureSection,
  illness: IllnessSection,
  medication: MedicationSection,
  vaccination: VaccinationSection,
  milestones: MilestonesSection,
  doctor_visits: DoctorVisitsSection,
  insights: InsightsSection,
  questions: QuestionsSection,
  note: NoteSection,
};

export function renderSectionContent(code, section, period) {
  const Renderer = SECTION_RENDERERS[code];
  if (!Renderer) return <UnavailableSection />;
  return <Renderer section={section} period={period} />;
}
