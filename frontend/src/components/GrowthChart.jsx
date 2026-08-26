import {
  ComposedChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from "recharts";

const UNIT = {
  weight: "kg",
  height: "cm",
  head_circumference: "cm",
};

function CustomTooltip({ active, payload, label, measurementType }) {
  if (!active || !payload || payload.length === 0) return null;
  const point = payload.find((p) => p.dataKey === "childValue");

  return (
    <div className="bg-void-card border border-void-hairline rounded-lg px-3 py-2 shadow-soft">
      <p className="text-xs text-ink-faint font-medium mb-1">{label} bulan</p>
      {point?.value != null && (
        <p className="text-sm text-ink font-semibold">
          {point.value} {UNIT[measurementType]}
        </p>
      )}
    </div>
  );
}

export default function GrowthChart({ measurementType, referenceCurve, childPoints }) {
  // gabungkan kurva acuan dengan titik data anak berdasarkan usia (bulan)
  const merged = referenceCurve.map((ref) => {
    const childPoint = childPoints.find((p) => Math.round(p.age_months) === ref.age_months);
    return {
      ...ref,
      childValue: childPoint ? childPoint.value : null,
    };
  });

  return (
    <div className="h-56 w-full sm:h-64">
      <ResponsiveContainer width="100%" height="100%">
        <ComposedChart data={merged} margin={{ top: 10, right: 8, left: -25, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#F0E2CC" vertical={false} />
          <XAxis
            dataKey="age_months"
            tick={{ fontSize: 10, fill: "#9C8F82" }}
            tickLine={false}
            axisLine={{ stroke: "#F0E2CC" }}
            label={{ value: "usia (bulan)", position: "insideBottom", offset: -2, fontSize: 10, fill: "#9C8F82" }}
          />
          <YAxis
            tick={{ fontSize: 10, fill: "#9C8F82" }}
            tickLine={false}
            axisLine={false}
            width={40}
          />
          <Tooltip content={<CustomTooltip measurementType={measurementType} />} />

          {/* batas normal WHO: -2SD dan +2SD sebagai garis tipis */}
          <Line
            dataKey="sd_neg2"
            stroke="#4FC9A8"
            strokeWidth={1}
            strokeOpacity={0.5}
            dot={false}
            isAnimationActive={false}
          />
          <Line
            dataKey="sd_pos2"
            stroke="#4FC9A8"
            strokeWidth={1}
            strokeOpacity={0.5}
            dot={false}
            isAnimationActive={false}
          />

          {/* garis median WHO */}
          <Line
            dataKey="median"
            stroke="#C7BAA9"
            strokeWidth={1.5}
            strokeDasharray="4 3"
            dot={false}
            isAnimationActive={false}
          />

          {/* titik data anak */}
          <Line
            dataKey="childValue"
            stroke="#FFA733"
            strokeWidth={2.5}
            dot={{ r: 4, fill: "#FFA733", strokeWidth: 0 }}
            connectNulls
            isAnimationActive={false}
          />
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}
