/** Обёртки над recharts для графиков приложения (адаптивны к теме). */

import React from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

const TOOLTIP_STYLE = {
  background: "hsl(var(--popover))",
  border: "1px solid hsl(var(--border))",
  color: "hsl(var(--popover-foreground))",
  borderRadius: 8,
  fontSize: 12,
} as React.CSSProperties;

type Row = { name: string; [key: string]: unknown };

export interface BarDatum {
  name: string;
  [key: string]: unknown;
}

/** Столбчатая диаграмма (одна или несколько серий). */
export function ColumnChart<T extends Row>({
  data,
  keys,
  height = 270,
}: {
  data: T[];
  keys: Array<{ key: string; name: string }>;
  height?: number;
}) {
  return (
    <div className="overflow-x-auto">
      <ResponsiveContainer width="100%" height={height}>
        <BarChart data={data as unknown as Row[]}>
          <CartesianGrid stroke="hsl(var(--border))" vertical={false} />
          <XAxis dataKey="name" interval="preserveStart" />
          <YAxis />
          <Tooltip contentStyle={TOOLTIP_STYLE} />
          {keys.map((k) => (
            <Bar key={k.key} dataKey={k.key} name={k.name} radius={4} />
          ))}
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

export interface HistDatum {
  label: string;
  count: number;
}

/** Гистограмма распределения. */
export function HistogramChart({ data, height = 270, unit = "чанков" }: {
  data: HistDatum[];
  height?: number;
  unit?: string;
}) {
  return (
    <div className="overflow-x-auto">
      <ResponsiveContainer width="100%" height={height}>
        <BarChart data={data as unknown as Row[]}>
          <CartesianGrid stroke="hsl(var(--border))" vertical={false} />
          <XAxis dataKey="label" interval="preserveStart" />
          <YAxis />
          <Tooltip contentStyle={TOOLTIP_STYLE} />
          <Bar dataKey="count" name={unit} radius={3} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

export interface LineDatum {
  name: string;
  value: number;
}

/** Линейный график времени. */
export function TimingLineChart({ data, height = 250, unit = "мс" }: {
  data: LineDatum[];
  height?: number;
  unit?: string;
}) {
  return (
    <div className="overflow-x-auto">
      <ResponsiveContainer width="100%" height={height}>
        <LineChart data={data as unknown as Row[]}>
          <CartesianGrid stroke="hsl(var(--border))" />
          <XAxis dataKey="name" interval="preserveStart" />
          <YAxis />
          <Tooltip contentStyle={TOOLTIP_STYLE} />
          <Line type="monotone" dataKey="value" name={unit} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}

/** Квантили для box plot. */
export interface BoxStats {
  min: number;
  q1: number;
  median: number;
  q3: number;
  max: number;
}

export function boxStats(values: number[]): BoxStats | null {
  if (!values.length) return null;
  const s = [...values].sort((a, b) => a - b);
  const q = (p: number) => {
    const pos = (s.length - 1) * p;
    const lo = Math.floor(pos);
    const hi = Math.ceil(pos);
    return lo === hi ? s[lo] : (s[lo] + s[hi]) / 2;
  };
  return { min: s[0], q1: q(0.25), median: q(0.5), q3: q(0.75), max: s[s.length - 1] };
}

/** Box plot на чистом CSS по квантилям (адаптивен к теме). */
export function BoxPlotChart({ series }: { series: Array<{ name: string; stats: BoxStats }> }) {
  const globalMax = Math.max(...series.map((s) => s.stats.max), 1);
  const pct = (v: number) => Math.max(0.5, (v / globalMax) * 100);
  return (
    <div className="space-y-5">
      {series.map((s) => {
        const { min, q1, median, q3, max } = s.stats;
        const iqr = Math.max(0, q3 - q1);
        return (
          <div key={s.name} className="flex items-center gap-3">
            <span className="w-36 shrink-0 truncate text-xs text-muted-foreground" title={s.name}>
              {s.name}
            </span>
            <div className="relative h-9 flex-1">
              <div className="absolute top-[15px] h-px border-t border-dashed"
                style={{ left: `${pct(min)}%`, width: `${pct(q1) - pct(min)}%` }} />
              <div className="absolute top-[15px] h-px border-t border-dashed"
                style={{ left: `${pct(q3)}%`, width: `${pct(max) - pct(q3)}%` }} />
              <div className="absolute top-[6px] h-5 rounded-sm bg-primary DEFAULT/15"
                style={{ left: `${pct(q1)}%`, width: `${pct(iqr)}%` }} />
              <div className="absolute top-[6px] w-0.5 bg-primary DEFAULT"
                style={{ left: `${pct(median)}%`, height: 20 }} />
              <span className="absolute top-[1px] h-1.5 w-1.5 rounded-full bg-secondary-foreground"
                style={{ left: `${pct(min)}%` }} />
              <span className="absolute top-[1px] h-1.5 w-1.5 rounded-full bg-secondary-foreground"
                style={{ left: `${pct(max)}%` }} />
            </div>
            <span className="w-24 shrink-0 text-right font-mono text-[11px] text-muted-foreground">
              {Math.round(min)} … {Math.round(max)}
            </span>
          </div>
        );
      })}
    </div>
  );
}