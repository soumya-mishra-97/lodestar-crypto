import { ColorType, createChart, CrosshairMode, LineSeries, LineStyle, type Time } from "lightweight-charts";
import { useEffect, useMemo, useRef, useState } from "react";

export interface CompareSeries {
  label: string;
  /** Categorical slot, e.g. "--series-1"; assigned by identity, never by rank. */
  color: string;
  points: { date: string; value: number }[];
  dashed?: boolean;
}

const css = (name: string) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();

/**
 * Two or three lines on one shared axis and unit (e.g. strategy vs buy-and-hold, both indexed to 100).
 * Legend always present; a crosshair readout replaces per-point labels. Never a second y-axis.
 */
export function CompareChart({
  series,
  format,
  theme,
  height = 260,
  baseline,
  label,
}: {
  series: CompareSeries[];
  format: (v: number) => string;
  theme: string;
  height?: number;
  baseline?: number;
  label: string;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const [hover, setHover] = useState<{ date: string; values: (number | undefined)[] } | null>(null);
  const lookups = useMemo(() => series.map((s) => new Map(s.points.map((p) => [p.date, p.value]))), [series]);
  const latest = useMemo(() => {
    const date = series[0]?.points.at(-1)?.date;
    return date ? { date, values: lookups.map((m) => m.get(date)) } : null;
  }, [series, lookups]);

  useEffect(() => {
    if (!ref.current) return;
    const chart = createChart(ref.current, {
      layout: { background: { type: ColorType.Solid, color: "transparent" }, textColor: css("--muted"), fontFamily: "system-ui" },
      grid: { vertLines: { visible: false }, horzLines: { color: css("--grid") } },
      rightPriceScale: { borderColor: css("--axis") },
      timeScale: { borderColor: css("--axis") },
      crosshair: { mode: CrosshairMode.Magnet },
      localization: { priceFormatter: format },
      autoSize: true,
      handleScroll: false,
      handleScale: false,
    });
    series.forEach((s, i) => {
      const line = chart.addSeries(LineSeries, {
        color: css(s.color),
        lineWidth: 2,
        lineStyle: s.dashed ? LineStyle.Dashed : LineStyle.Solid,
        priceLineVisible: false,
        lastValueVisible: false,
      });
      line.setData(s.points.map((p) => ({ time: p.date as Time, value: p.value })));
      if (i === 0 && baseline !== undefined) {
        line.createPriceLine({ price: baseline, color: css("--axis"), lineWidth: 1, lineStyle: LineStyle.Dotted, axisLabelVisible: false });
      }
    });
    chart.timeScale().fitContent();
    chart.subscribeCrosshairMove((param) => {
      if (!param.time) return setHover(null);
      const date = String(param.time);
      setHover({ date, values: lookups.map((m) => m.get(date)) });
    });
    return () => chart.remove();
  }, [series, lookups, format, baseline, theme]);

  const shown = hover ?? latest;
  return (
    <figure aria-label={label}>
      <figcaption className="mb-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs">
        {series.map((s, i) => (
          <span key={s.label} className="flex items-center gap-1.5 text-ink-2">
            <span
              aria-hidden
              className="inline-block h-0.5 w-4 rounded"
              style={{ background: s.dashed ? `repeating-linear-gradient(90deg, var(${s.color}) 0 4px, transparent 4px 7px)` : `var(${s.color})` }}
            />
            {s.label}
            <span className="tabular text-ink">{shown?.values[i] !== undefined ? format(shown.values[i]) : "—"}</span>
          </span>
        ))}
        {shown && <span className="ml-auto tabular text-muted">{shown.date}</span>}
      </figcaption>
      <div ref={ref} style={{ height }} />
    </figure>
  );
}
