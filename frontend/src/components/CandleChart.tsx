import {
  CandlestickSeries,
  ColorType,
  createChart,
  CrosshairMode,
  type IChartApi,
  LineSeries,
  LineStyle,
  type UTCTimestamp,
} from "lightweight-charts";
import { useEffect, useMemo, useRef, useState } from "react";
import type { Chart, SeriesPoint } from "@/api/types";
import { usd } from "@/lib/format";

const css = (name: string) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();

/** Overlays take categorical slots 2-4 in fixed order (slot 1 is the up-candle hue); bands stay recessive. */
const OVERLAYS = [
  { key: "sma_20", label: "SMA 20", color: "--series-2" },
  { key: "sma_50", label: "SMA 50", color: "--series-3" },
  { key: "sma_200", label: "SMA 200", color: "--series-4" },
] as const;
type OverlayKey = (typeof OVERLAYS)[number]["key"];

interface Readout {
  t: number;
  o?: number;
  h?: number;
  l?: number;
  c: number;
  values: Partial<Record<OverlayKey | "rsi", number>>;
}

const toTime = (t: number) => t as UTCTimestamp;
const byTime = (points: SeriesPoint[]) => new Map(points.map((p) => [p.t, p.v]));

/**
 * Price: candles (exchange OHLC) or a close line when the exchange doesn't list the pair,
 * with SMA and Bollinger overlays on the same axis. RSI is its own chart below (never a second y-axis).
 * Up/down candles use the diverging blue/red pair, not the reserved status colors.
 */
export function CandleChart({ chart, theme }: { chart: Chart; theme: string }) {
  const priceRef = useRef<HTMLDivElement>(null);
  const rsiRef = useRef<HTMLDivElement>(null);
  const [visible, setVisible] = useState<Record<OverlayKey | "bands", boolean>>({
    sma_20: true,
    sma_50: true,
    sma_200: false,
    bands: false,
  });
  const [readout, setReadout] = useState<Readout | null>(null);

  const lookups = useMemo(() => {
    const ind = chart.indicators;
    return {
      sma_20: byTime(ind.sma_20),
      sma_50: byTime(ind.sma_50),
      sma_200: byTime(ind.sma_200),
      rsi: byTime(ind.rsi_14),
    };
  }, [chart]);

  const latest: Readout | null = useMemo(() => {
    const c = chart.candles.at(-1);
    const l = chart.line.at(-1);
    const t = c?.t ?? l?.t;
    if (t === undefined) return null;
    return {
      t,
      o: c?.o,
      h: c?.h,
      l: c?.l,
      c: c?.c ?? l?.v ?? 0,
      values: {
        sma_20: lookups.sma_20.get(t),
        sma_50: lookups.sma_50.get(t),
        sma_200: lookups.sma_200.get(t),
        rsi: lookups.rsi.get(t),
      },
    };
  }, [chart, lookups]);

  useEffect(() => {
    if (!priceRef.current || !rsiRef.current) return;
    const common = {
      layout: { background: { type: ColorType.Solid, color: "transparent" }, textColor: css("--muted"), fontFamily: "system-ui" },
      grid: { vertLines: { visible: false }, horzLines: { color: css("--grid") } },
      rightPriceScale: { borderColor: css("--axis") },
      timeScale: { borderColor: css("--axis"), timeVisible: false },
      crosshair: { mode: CrosshairMode.Magnet },
      autoSize: true,
      handleScroll: false,
      handleScale: false,
    };
    const price: IChartApi = createChart(priceRef.current, { ...common, localization: { priceFormatter: (v: number) => usd(v) } });
    const rsi: IChartApi = createChart(rsiRef.current, {
      ...common,
      layout: { ...common.layout, attributionLogo: false }, // one TradingView attribution is enough
      timeScale: { visible: false },
    });

    if (chart.candles.length) {
      const up = css("--series-1");
      const down = css("--series-8");
      const candles = price.addSeries(CandlestickSeries, {
        upColor: up,
        downColor: down,
        borderUpColor: up,
        borderDownColor: down,
        wickUpColor: up,
        wickDownColor: down,
        priceLineVisible: false,
      });
      candles.setData(chart.candles.map((c) => ({ time: toTime(c.t), open: c.o, high: c.h, low: c.l, close: c.c })));
    } else {
      const line = price.addSeries(LineSeries, { color: css("--series-1"), lineWidth: 2, priceLineVisible: false });
      line.setData(chart.line.map((p) => ({ time: toTime(p.t), value: p.v })));
    }

    if (visible.bands) {
      for (const key of ["bb_upper", "bb_lower"] as const) {
        const band = price.addSeries(LineSeries, {
          color: css("--muted"),
          lineWidth: 1,
          lineStyle: LineStyle.Dashed,
          priceLineVisible: false,
          lastValueVisible: false,
          crosshairMarkerVisible: false,
        });
        band.setData(chart.indicators[key].map((p) => ({ time: toTime(p.t), value: p.v })));
      }
    }
    for (const o of OVERLAYS) {
      if (!visible[o.key]) continue;
      const s = price.addSeries(LineSeries, {
        color: css(o.color),
        lineWidth: 2,
        priceLineVisible: false,
        lastValueVisible: false,
        crosshairMarkerVisible: false,
      });
      s.setData(chart.indicators[o.key].map((p) => ({ time: toTime(p.t), value: p.v })));
    }

    const rsiLine = rsi.addSeries(LineSeries, {
      color: css("--series-7"),
      lineWidth: 2,
      priceLineVisible: false,
      autoscaleInfoProvider: () => ({ priceRange: { minValue: 0, maxValue: 100 } }), // RSI is bounded: fixed scale
    });
    rsiLine.setData(chart.indicators.rsi_14.map((p) => ({ time: toTime(p.t), value: p.v })));
    for (const level of [30, 70]) {
      rsiLine.createPriceLine({ price: level, color: css("--axis"), lineWidth: 1, lineStyle: LineStyle.Dashed, axisLabelVisible: true, title: "" });
    }
    rsi.priceScale("right").applyOptions({ scaleMargins: { top: 0.08, bottom: 0.08 } });

    price.timeScale().fitContent();
    rsi.timeScale().fitContent();
    price.timeScale().subscribeVisibleLogicalRangeChange((range) => {
      if (range) rsi.timeScale().setVisibleLogicalRange(range);
    });

    const candleByTime = new Map(chart.candles.map((c) => [c.t, c]));
    const lineByTime = new Map(chart.line.map((p) => [p.t, p.v]));
    price.subscribeCrosshairMove((param) => {
      const t = typeof param.time === "number" ? param.time : undefined;
      if (t === undefined) return setReadout(null);
      const c = candleByTime.get(t);
      const close = c?.c ?? lineByTime.get(t);
      if (close === undefined) return setReadout(null);
      setReadout({
        t,
        o: c?.o,
        h: c?.h,
        l: c?.l,
        c: close,
        values: {
          sma_20: lookups.sma_20.get(t),
          sma_50: lookups.sma_50.get(t),
          sma_200: lookups.sma_200.get(t),
          rsi: lookups.rsi.get(t),
        },
      });
    });
    return () => {
      price.remove();
      rsi.remove();
    };
  }, [chart, theme, visible, lookups]);

  const shown = readout ?? latest;
  const date = shown ? new Date(shown.t * 1000).toISOString().slice(0, 10) : "";
  const toggle = (key: OverlayKey | "bands") => setVisible((v) => ({ ...v, [key]: !v[key] }));

  return (
    <figure>
      <div className="mb-3 flex flex-wrap items-center gap-x-4 gap-y-2 text-xs text-ink-2" aria-live="polite">
        {shown?.o !== undefined ? (
          <span className="tabular">
            O <strong className="text-ink">{usd(shown.o)}</strong> H <strong className="text-ink">{usd(shown.h)}</strong> L{" "}
            <strong className="text-ink">{usd(shown.l)}</strong> C <strong className="text-ink">{usd(shown.c)}</strong>
          </span>
        ) : (
          <span className="tabular">
            Close <strong className="text-ink">{usd(shown?.c)}</strong>
          </span>
        )}
        <span className="ml-auto tabular text-muted">{date}</span>
      </div>
      <div className="mb-2 flex flex-wrap gap-2" role="group" aria-label="Indicators">
        {OVERLAYS.map((o) => (
          <button
            key={o.key}
            type="button"
            aria-pressed={visible[o.key]}
            onClick={() => toggle(o.key)}
            className={`flex items-center gap-1.5 rounded-md border px-2 py-1 text-xs ${visible[o.key] ? "border-line bg-surface-2 text-ink" : "border-transparent text-muted"}`}
          >
            <span className="h-0.5 w-4 rounded" style={{ background: `var(${o.color})` }} aria-hidden />
            {o.label}
            <span className="tabular text-ink-2">{usd(shown?.values[o.key])}</span>
          </button>
        ))}
        <button
          type="button"
          aria-pressed={visible.bands}
          onClick={() => toggle("bands")}
          className={`flex items-center gap-1.5 rounded-md border px-2 py-1 text-xs ${visible.bands ? "border-line bg-surface-2 text-ink" : "border-transparent text-muted"}`}
        >
          <span className="h-0 w-4 border-t border-dashed" style={{ borderColor: "var(--muted)" }} aria-hidden />
          Bollinger (20, 2)
        </button>
      </div>
      <div ref={priceRef} className="h-80 w-full" role="img" aria-label={`Daily ${chart.candles.length ? "candles" : "closing price"} with moving averages`} />
      <div className="mt-3 flex items-center gap-2 text-xs text-ink-2">
        <span className="h-0.5 w-4 rounded" style={{ background: "var(--series-7)" }} aria-hidden />
        RSI (14) <strong className="tabular text-ink">{shown?.values.rsi?.toFixed(1) ?? "—"}</strong>
        <span className="text-muted">· 30 oversold / 70 overbought</span>
      </div>
      <div ref={rsiRef} className="h-28 w-full" role="img" aria-label="14-day relative strength index" />
      <figcaption className="mt-2 text-xs text-muted">
        {chart.candle_source ? `Daily candles from ${chart.candle_source}` : "No exchange candles for this pair; showing daily closes"} ·
        indicators computed by Lodestar from the plotted series.
      </figcaption>
    </figure>
  );
}
