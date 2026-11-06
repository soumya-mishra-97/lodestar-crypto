import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect } from "react";
import { followStream } from "@/lib/sse";
import { mergeEvents } from "@/lib/pipeline";
import { api, authHeaders, BASE, json, setAccessToken } from "./client";
import type {
  AddressImportResult,
  AnalysisReport,
  Asset,
  AssetCandidate,
  Backtest,
  Chart,
  CsvImportResult,
  Overview,
  PaperPerformance,
  PaperPosition,
  Portfolio,
  Preferences,
  Report,
  ReportKind,
  ReportStatus,
  ReportSummary,
  Run,
  RunDetail,
  RunEvent,
  Scan,
  Session,
  SettingsView,
  SetupKind,
} from "./types";

export const keys = {
  session: ["session"] as const,
  overview: ["overview"] as const,
  assets: ["assets"] as const,
  asset: (id: string) => ["asset", id] as const,
  chart: (id: string, days: number) => ["chart", id, days] as const,
  assetReport: (id: string) => ["asset-report", id] as const,
  watchlist: ["watchlist"] as const,
  portfolio: ["portfolio"] as const,
  search: (q: string) => ["search", q] as const,
  runs: (assetId?: string) => ["runs", assetId ?? "all"] as const,
  run: (id: string) => ["run", id] as const,
  reports: (kind: string, status: string) => ["reports", kind, status] as const,
  report: (id: string) => ["report", id] as const,
  settings: ["settings"] as const,
  scans: ["scans"] as const,
  scan: (id: string) => ["scan", id] as const,
  latestScan: ["scan", "latest"] as const,
  backtests: (assetId?: string) => ["backtests", assetId ?? "all"] as const,
  backtest: (id: string) => ["backtest", id] as const,
  paper: ["paper"] as const,
};

// ---------------------------------------------------------------- session & auth

export const useSession = () => useQuery({ queryKey: keys.session, queryFn: () => api<Session>("/session"), staleTime: 60_000 });

export function useLogin() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (v: { email: string; password: string; register?: boolean }) => {
      if (v.register) await api("/auth/register", { method: "POST", ...json({ email: v.email, password: v.password }) });
      const t = await api<{ access_token: string }>("/auth/login", {
        method: "POST",
        ...json({ email: v.email, password: v.password }),
      });
      setAccessToken(t.access_token);
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.session }),
  });
}

export function useLogout() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api("/auth/logout", { method: "POST" }),
    onSettled: () => {
      setAccessToken(null);
      qc.clear();
    },
  });
}

// ---------------------------------------------------------------- assets

export const useSearch = (q: string) =>
  useQuery({
    queryKey: keys.search(q),
    queryFn: () => api<AssetCandidate[]>(`/assets/search?q=${encodeURIComponent(q)}`),
    enabled: q.trim().length >= 2,
    staleTime: 5 * 60_000,
  });

export const useAssets = () => useQuery({ queryKey: keys.assets, queryFn: () => api<Asset[]>("/assets") });
export const useAsset = (id: string) => useQuery({ queryKey: keys.asset(id), queryFn: () => api<Asset>(`/assets/${id}`) });

export const useChart = (id: string, days: number) =>
  useQuery({
    queryKey: keys.chart(id, days),
    queryFn: () => api<Chart>(`/assets/${id}/chart?days=${days}`),
    placeholderData: (prev) => prev, // keep the previous frame while a new range loads
    refetchInterval: 60_000,
  });

export const useAssetReport = (id: string) =>
  useQuery({ queryKey: keys.assetReport(id), queryFn: () => api<AnalysisReport>(`/assets/${id}/report`), retry: false });

/** Add a coin: track it, watch it and start a pipeline run (returns the run to follow). */
export function useAddCoin() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (coingecko_id: string) =>
      api<{ asset: Asset; run: Run | null }>("/assets", { method: "POST", ...json({ coingecko_id }) }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: keys.assets });
      void qc.invalidateQueries({ queryKey: keys.overview });
      void qc.invalidateQueries({ queryKey: ["runs"] });
    },
  });
}

export function useStartRun(assetId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (force: boolean) =>
      api<{ run: Run; created: boolean }>(`/assets/${assetId}/runs${force ? "?force=true" : ""}`, { method: "POST" }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["runs"] }),
  });
}

export const useWatchlist = () => useQuery({ queryKey: keys.watchlist, queryFn: () => api<Asset[]>("/watchlist") });

export function useToggleWatch() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ assetId, watch }: { assetId: string; watch: boolean }) =>
      api(`/watchlist/${assetId}`, { method: watch ? "PUT" : "DELETE" }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: keys.watchlist });
      void qc.invalidateQueries({ queryKey: keys.overview });
    },
  });
}

// ---------------------------------------------------------------- pipeline

export const useRuns = (assetId?: string) =>
  useQuery({
    queryKey: keys.runs(assetId),
    queryFn: () => api<Run[]>(`/runs?limit=60${assetId ? `&asset_id=${assetId}` : ""}`),
    refetchInterval: 15_000,
  });

export const useRun = (id: string | undefined) =>
  useQuery({ queryKey: keys.run(id ?? "none"), queryFn: () => api<RunDetail>(`/runs/${id}`), enabled: Boolean(id) });

/** Follow a run live over SSE, merging events into the cached run detail. */
export function useRunStream(run: RunDetail | undefined) {
  const qc = useQueryClient();
  const id = run?.id;
  const resting = run ? ["awaiting_approval", "approved", "rejected", "failed"].includes(run.status) : true;
  const lastSeq = run?.events.at(-1)?.seq ?? 0;

  useEffect(() => {
    if (!id || resting) return;
    const controller = new AbortController();
    void followStream(`${BASE}/runs/${id}/events`, {
      headers: authHeaders,
      lastEventId: lastSeq,
      signal: controller.signal,
      onMessage: (message) => {
        const event = JSON.parse(message.data) as RunEvent;
        qc.setQueryData<RunDetail>(keys.run(id), (prev) => {
          if (!prev) return prev;
          const next = { ...prev, events: mergeEvents(prev.events, [event]) };
          if (event.type === "run" && event.status) next.status = event.status as RunDetail["status"];
          if (event.type === "step") next.current_step = event.step;
          return next;
        });
      },
      onEnd: () => {
        void qc.invalidateQueries({ queryKey: keys.run(id) });
        void qc.invalidateQueries({ queryKey: ["runs"] });
        void qc.invalidateQueries({ queryKey: keys.overview });
      },
    });
    return () => controller.abort();
    // lastSeq is only the resume point; changes to it must not restart the stream.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id, resting, qc]);
}

// ---------------------------------------------------------------- reports

export const useReports = (kind: ReportKind | "all", status: ReportStatus | "all") =>
  useQuery({
    queryKey: keys.reports(kind, status),
    queryFn: () => {
      const params = new URLSearchParams({ limit: "100" });
      if (kind !== "all") params.set("kind", kind);
      if (status !== "all") params.set("status", status);
      return api<ReportSummary[]>(`/reports?${params}`);
    },
  });

export const useReport = (id: string | undefined | null) =>
  useQuery({ queryKey: keys.report(id ?? "none"), queryFn: () => api<Report>(`/reports/${id}`), enabled: Boolean(id) });

export function useDecision() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ reportId, approve, note }: { reportId: string; approve: boolean; note?: string }) =>
      api<Report>(`/reports/${reportId}/${approve ? "approve" : "reject"}`, { method: "POST", ...json({ note: note || null }) }),
    onSuccess: (report) => {
      qc.setQueryData(keys.report(report.id), report);
      void qc.invalidateQueries({ queryKey: ["reports"] });
      void qc.invalidateQueries({ queryKey: ["asset-report"] });
      void qc.invalidateQueries({ queryKey: keys.run(report.run_id) });
      void qc.invalidateQueries({ queryKey: ["runs"] });
      void qc.invalidateQueries({ queryKey: keys.overview });
    },
  });
}

// ---------------------------------------------------------------- overview, portfolio, settings

export const useOverview = () =>
  useQuery({ queryKey: keys.overview, queryFn: () => api<Overview>("/overview"), refetchInterval: 60_000 });

export const usePortfolio = () => useQuery({ queryKey: keys.portfolio, queryFn: () => api<Portfolio>("/portfolio") });

function usePortfolioMutation<V, R>(fn: (v: V) => Promise<R>) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: fn,
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: keys.portfolio });
      void qc.invalidateQueries({ queryKey: keys.overview });
      void qc.invalidateQueries({ queryKey: keys.assets });
    },
  });
}

export const useUpsertHolding = () =>
  usePortfolioMutation((v: { asset_id: string; quantity: number; avg_cost_usd: number | null; notes: string | null }) =>
    api("/portfolio/holdings", { method: "PUT", ...json(v) }),
  );

export const useRemoveHolding = () =>
  usePortfolioMutation((holdingId: string) => api(`/portfolio/holdings/${holdingId}`, { method: "DELETE" }));

export const useImportCsv = () =>
  usePortfolioMutation((content: string) => api<CsvImportResult>("/portfolio/import/csv", { method: "POST", ...json({ content }) }));

export const useImportAddress = () =>
  usePortfolioMutation((v: { chain: string; address: string }) =>
    api<AddressImportResult>("/portfolio/import/address", { method: "POST", ...json(v) }),
  );

export const useSettings = () => useQuery({ queryKey: keys.settings, queryFn: () => api<SettingsView>("/settings") });

export function useUpdatePreferences() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (v: Partial<Preferences>) => api<SettingsView>("/settings", { method: "PUT", ...json(v) }),
    onSuccess: (data) => qc.setQueryData(keys.settings, data),
  });
}

// ---------------------------------------------------------------- trader skills (paper trading only)

const SCAN_POLL_MS = 1500;

export const useScans = () => useQuery({ queryKey: keys.scans, queryFn: () => api<Scan[]>("/scans") });

/** The latest scan, polled while it is still running. */
export const useLatestScan = () =>
  useQuery({
    queryKey: keys.latestScan,
    queryFn: () => api<Scan | null>("/scans/latest"),
    refetchInterval: (q) => (q.state.data?.status === "running" ? SCAN_POLL_MS : false),
  });

export const useScan = (id: string | undefined) =>
  useQuery({
    queryKey: keys.scan(id ?? "none"),
    queryFn: () => api<Scan>(`/scans/${id}`),
    enabled: Boolean(id),
    refetchInterval: (q) => (q.state.data?.status === "running" ? SCAN_POLL_MS : false),
  });

export function useStartScan() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (v: { universe: "top" | "watchlist"; top_n?: number }) => api<Scan>("/scans", { method: "POST", ...json(v) }),
    onSuccess: (scan) => {
      qc.setQueryData(keys.latestScan, scan);
      void qc.invalidateQueries({ queryKey: keys.scans });
    },
  });
}

/** Select a coin: start the per-coin trader-skills pipeline and return the run to follow. */
export function useStartTradePlan() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (v: { coingecko_id: string; force?: boolean }) =>
      api<{ asset: Asset; run: Run; created: boolean }>("/trade-plans", { method: "POST", ...json(v) }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["runs"] });
      void qc.invalidateQueries({ queryKey: keys.assets });
    },
  });
}

export const useBacktests = (assetId?: string) =>
  useQuery({
    queryKey: keys.backtests(assetId),
    queryFn: () => api<Backtest[]>(`/backtests${assetId ? `?asset_id=${assetId}` : ""}`),
  });

export const useBacktest = (id: string | undefined | null) =>
  useQuery({ queryKey: keys.backtest(id ?? "none"), queryFn: () => api<Backtest>(`/backtests/${id}`), enabled: Boolean(id) });

export function useRunBacktest() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (v: { coingecko_id: string; setup?: SetupKind }) =>
      api<{ id: string }>("/backtests", { method: "POST", ...json(v) }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["backtests"] }),
  });
}

export const usePaper = () => useQuery({ queryKey: keys.paper, queryFn: () => api<PaperPerformance>("/paper") });

function usePaperMutation<V>(fn: (v: V) => Promise<PaperPerformance | PaperPosition | undefined>) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: fn,
    onSuccess: (data) => {
      if (data && "positions" in data) qc.setQueryData(keys.paper, data);
      else void qc.invalidateQueries({ queryKey: keys.paper });
    },
  });
}

export const usePaperOpen = () =>
  usePaperMutation((reportId: string) => api<PaperPosition>("/paper/positions", { method: "POST", ...json({ report_id: reportId }) }));
export const usePaperCancel = () =>
  usePaperMutation((positionId: string) => api<undefined>(`/paper/positions/${positionId}/cancel`, { method: "POST" }));
export const usePaperTick = () => usePaperMutation(() => api<PaperPerformance>("/paper/tick", { method: "POST" }));
export const usePaperReset = () => usePaperMutation(() => api<PaperPerformance>("/paper/reset", { method: "POST" }));
export const usePaperDemoReplay = () =>
  usePaperMutation(() => api<PaperPerformance>("/paper/demo-replay", { method: "POST" }));
