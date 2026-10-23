"use client";

import { useId, useMemo, useRef, useState, type KeyboardEvent, type PointerEvent } from "react";

import type { MonthRow, ScenarioName, ScenarioResult } from "@/lib/api/types";
import {
  SCENARIOS,
  SCENARIO_STROKE,
  chartGeometry,
  money,
  moneyCompact,
  nearestIndex,
  type ChartFrame,
} from "@/lib/plan";
import { cn } from "@/lib/utils";

const FRAME: ChartFrame = { width: 360, height: 190, left: 46, right: 40, top: 12, bottom: 22 };
const MONTH_TICKS = [1, 3, 6, 9, 12];
const LABEL_GAP = 11;

/** Pushes end labels apart vertically so they never overlap. */
function spreadLabels(ys: { key: ScenarioName; y: number }[]): Map<ScenarioName, number> {
  const sorted = [...ys].sort((a, b) => a.y - b.y);
  for (let i = 1; i < sorted.length; i++) {
    const prev = sorted[i - 1]!;
    const cur = sorted[i]!;
    if (cur.y - prev.y < LABEL_GAP) cur.y = prev.y + LABEL_GAP;
  }
  return new Map(sorted.map((s) => [s.key, s.y]));
}

/**
 * One metric for the three scenarios over 12 months: a line per scenario (colour fixed by
 * scenario), legend + direct end labels, and a crosshair tooltip on hover or keyboard
 * focus. The 12-month table below is the non-hover route to every value.
 */
export function ScenarioChart({
  title,
  metric,
  scenarios,
  selected,
}: {
  title: string;
  metric: keyof Pick<MonthRow, "mrr" | "cash">;
  scenarios: readonly ScenarioResult[];
  selected: ScenarioName;
}) {
  const titleId = useId();
  const svgRef = useRef<SVGSVGElement>(null);
  const [active, setActive] = useState<number | null>(null);
  const series = useMemo(
    () => scenarios.map((s) => ({ key: s.scenario, values: s.months.map((m) => m[metric]) })),
    [scenarios, metric],
  );
  const geo = useMemo(() => chartGeometry(series, FRAME), [series]);
  const count = series[0]?.values.length ?? 0;
  const last = count - 1;
  const ends = spreadLabels(series.map((s) => ({ key: s.key, y: geo.y(s.values[last] ?? 0) })));

  const onPointerMove = (e: PointerEvent<SVGSVGElement>) => {
    const box = svgRef.current?.getBoundingClientRect();
    if (!box || box.width === 0) return;
    const px = ((e.clientX - box.left) / box.width) * FRAME.width;
    setActive(nearestIndex(px, count, FRAME));
  };
  const onKeyDown = (e: KeyboardEvent<SVGSVGElement>) => {
    if (e.key !== "ArrowLeft" && e.key !== "ArrowRight") return;
    e.preventDefault();
    setActive((i) => {
      const at = i ?? last;
      return Math.max(0, Math.min(last, at + (e.key === "ArrowRight" ? 1 : -1)));
    });
  };

  const label = (key: ScenarioName) => SCENARIOS.find((s) => s.value === key)?.label ?? key;

  return (
    <figure className="bg-card flex min-w-0 flex-col gap-2 rounded-lg border p-3">
      <figcaption className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
        <span id={titleId} className="text-sm font-medium">
          {title}
        </span>
        <span className="text-muted-foreground flex flex-wrap gap-3 text-xs" aria-hidden>
          {series.map((s) => (
            <span key={s.key} className="inline-flex items-center gap-1.5">
              <span
                className="inline-block h-0.5 w-3 rounded-full"
                style={{ background: SCENARIO_STROKE[s.key] }}
              />
              {label(s.key)}
            </span>
          ))}
        </span>
      </figcaption>
      <div className="relative">
        <svg
          ref={svgRef}
          viewBox={`0 0 ${FRAME.width} ${FRAME.height}`}
          className="block h-auto w-full touch-pan-y overflow-visible outline-none focus-visible:ring-3 focus-visible:ring-ring/50 rounded"
          role="img"
          aria-labelledby={titleId}
          aria-describedby={`${titleId}-desc`}
          tabIndex={0}
          onPointerMove={onPointerMove}
          onPointerLeave={() => setActive(null)}
          onFocus={() => setActive((i) => i ?? last)}
          onBlur={() => setActive(null)}
          onKeyDown={onKeyDown}
        >
          <desc id={`${titleId}-desc`}>
            {series
              .map((s) => `${label(s.key)}: ${money(s.values[last] ?? 0)} in month 12`)
              .join("; ")}
          </desc>
          {geo.ticks.map((t) => (
            <g key={t}>
              <line
                x1={FRAME.left}
                x2={FRAME.width - FRAME.right}
                y1={geo.y(t)}
                y2={geo.y(t)}
                stroke="var(--border)"
                strokeWidth={t === 0 ? 1 : 0.6}
              />
              <text
                x={FRAME.left - 6}
                y={geo.y(t)}
                dy="0.32em"
                textAnchor="end"
                className="fill-muted-foreground tabular text-[9px]"
              >
                {moneyCompact(t)}
              </text>
            </g>
          ))}
          {MONTH_TICKS.filter((m) => m <= count).map((m) => (
            <text
              key={m}
              x={geo.x(m - 1)}
              y={FRAME.height - 6}
              textAnchor="middle"
              className="fill-muted-foreground tabular text-[9px]"
            >
              M{m}
            </text>
          ))}
          {geo.paths.map((p) => (
            <path
              key={p.key}
              d={p.d}
              fill="none"
              stroke={SCENARIO_STROKE[p.key]}
              strokeWidth={p.key === selected ? 2.25 : 1.5}
              strokeOpacity={p.key === selected ? 1 : 0.7}
              strokeLinejoin="round"
              strokeLinecap="round"
              data-scenario={p.key}
            />
          ))}
          {series.map((s) => (
            <text
              key={s.key}
              x={geo.x(last) + 5}
              y={ends.get(s.key)}
              dy="0.32em"
              className={cn(
                "text-[9px]",
                s.key === selected ? "fill-foreground font-medium" : "fill-muted-foreground",
              )}
            >
              {label(s.key)}
            </text>
          ))}
          {active !== null && (
            <g pointerEvents="none">
              <line
                x1={geo.x(active)}
                x2={geo.x(active)}
                y1={FRAME.top}
                y2={FRAME.height - FRAME.bottom}
                stroke="var(--muted-foreground)"
                strokeWidth={0.75}
                strokeDasharray="2 2"
              />
              {series.map((s) => (
                <circle
                  key={s.key}
                  cx={geo.x(active)}
                  cy={geo.y(s.values[active] ?? 0)}
                  r={3.5}
                  fill={SCENARIO_STROKE[s.key]}
                  stroke="var(--card)"
                  strokeWidth={2}
                />
              ))}
            </g>
          )}
        </svg>
        {active !== null && (
          <div
            role="status"
            className={cn(
              "bg-popover pointer-events-none absolute top-1 z-10 flex min-w-32 flex-col gap-0.5 rounded-md border px-2.5 py-1.5 text-xs shadow-sm",
              active > last / 2 ? "left-[14%]" : "right-[12%]",
            )}
          >
            <span className="text-muted-foreground">Month {active + 1}</span>
            {series.map((s) => (
              <span key={s.key} className="flex items-center gap-2">
                <span
                  className="inline-block h-0.5 w-3 shrink-0 rounded-full"
                  style={{ background: SCENARIO_STROKE[s.key] }}
                />
                <span className="tabular font-mono font-medium">
                  {money(s.values[active] ?? 0)}
                </span>
                <span className="text-muted-foreground">{label(s.key)}</span>
              </span>
            ))}
          </div>
        )}
      </div>
    </figure>
  );
}
