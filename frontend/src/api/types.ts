// Mirrors the backend response shapes (lodestar/interfaces/http and application/services).

export type Stance = "favorable" | "neutral" | "unfavorable";
export type RiskLevel = "low" | "moderate" | "high" | "very_high";
export type Horizon = "short_term" | "long_term";
export type RunStatus = "queued" | "running" | "awaiting_approval" | "approved" | "rejected" | "failed";
export type ReportStatus = "pending_approval" | "approved" | "rejected";
export type ReportKind = "on_demand" | "daily" | "trade_plan";
export type AnalysisKind = "on_demand" | "daily";
export type ClaimTag = "fact" | "calculation" | "interpretation" | "scenario" | "assumption";
export type EvidenceKind = "observation" | "calculation" | "text";
export type Unit = "usd" | "pct" | "ratio" | "index" | "count" | "days" | "text";

export interface Session {
  auth_mode: "local" | "password";
  authenticated: boolean;
  data_mode: "demo" | "live";
  demo: boolean;
  llm_mode: string;
}

export interface Asset {
  id: string;
  coingecko_id: string;
  symbol: string;
  name: string;
}

export interface AssetCandidate {
  coingecko_id: string;
  symbol: string;
  name: string;
  market_cap_rank: number | null;
  thumb_url: string | null;
}

export interface MarketSnapshot {
  coingecko_id: string;
  price_usd: number;
  market_cap_usd: number | null;
  fdv_usd: number | null;
  volume_24h_usd: number | null;
  change_24h_pct: number | null;
  change_7d_pct: number | null;
  change_30d_pct: number | null;
  change_1y_pct: number | null;
  ath_usd: number | null;
  ath_change_pct: number | null;
  market_cap_rank: number | null;
  as_of: string;
}

// ---------------------------------------------------------------- reports

export interface Claim {
  text: string;
  tag: ClaimTag;
  evidence_ids: string[];
}

export interface Evidence {
  id: string;
  key: string;
  label: string;
  value: number | string;
  unit: Unit;
  kind: EvidenceKind;
  source: string;
  as_of: string;
  inputs: string[];
}

export interface Signal {
  name: string;
  horizon: Horizon;
  contribution: number;
  detail: string;
  evidence_ids: string[];
}

export interface RiskFactor {
  name: string;
  points: number;
  detail: string;
  evidence_ids: string[];
}

export interface RiskAssessment {
  horizon: Horizon;
  level: RiskLevel;
  score: number;
  factors: RiskFactor[];
}

export interface Assessment {
  horizon: Horizon;
  score: number;
  stance: Stance;
  confidence: number;
  risk: RiskAssessment;
  signals: Signal[];
}

export interface HorizonNarrative {
  thesis: Claim[];
  opportunities: Claim[];
  risks: Claim[];
  watch: Claim[];
}

export interface Draft {
  headline: Claim;
  short_term: HorizonNarrative;
  long_term: HorizonNarrative;
  portfolio: Claim[];
  data_quality: Claim[];
  uncertainties: Claim[];
  disclaimer: string;
  writer: string;
}

export interface Reconciliation {
  field: string;
  reference_value: number;
  tolerance_pct: number;
  status: "consistent" | "mismatch" | "single_source";
  max_deviation_pct: number;
  comparisons: { source: string; value: number; deviation_pct: number; within_tolerance: boolean }[];
}

export interface AnalystSummary {
  claims_source: "llm" | "template";
  steps: number;
  tool_calls: number;
  stop_reason: "final" | "step_limit" | "policy_error";
  summary: string;
  dropped_claims: number;
}

export interface ReportContent {
  pipeline_version: string;
  generated_at: string;
  data_mode: "demo" | "live";
  asset: Asset;
  snapshot: MarketSnapshot;
  assessments: Record<Horizon, Assessment>;
  draft: Draft;
  portfolio: { held: boolean; available: boolean; weight_pct?: number; value_usd?: number } | null;
  reconciliation: Reconciliation | null;
  analysts: Record<string, AnalystSummary>;
  evidence: Evidence[];
  data_gaps: string[];
  verification: {
    passed: boolean;
    checked_claims: number;
    findings: { location: string; rule: string; message: string; claim_text: string }[];
    attempts: number;
    repairs: number;
  };
  disclaimer: string;
}

export interface ReportSummary {
  id: string;
  run_id: string;
  asset: Asset | null;
  kind: ReportKind;
  status: ReportStatus;
  headline: string;
  short_term_stance: Stance;
  long_term_stance: Stance;
  short_term_risk: RiskLevel;
  long_term_risk: RiskLevel;
  created_at: string;
  decided_at: string | null;
  decision_note: string | null;
  setup_kind?: SetupKind | null;
  setup_status?: SetupStatus | null;
}

export interface AnalysisReport extends ReportSummary {
  kind: AnalysisKind;
  content: ReportContent;
}

export interface TradePlanReport extends ReportSummary {
  kind: "trade_plan";
  content: TradePlanContent;
}

export type Report = AnalysisReport | TradePlanReport;

export const isTradePlan = (r: Report): r is TradePlanReport => r.kind === "trade_plan";

// ---------------------------------------------------------------- pipeline

export interface Run {
  id: string;
  asset_id: string;
  requested_by: string | null;
  kind: ReportKind;
  status: RunStatus;
  current_step: string | null;
  repair_count: number;
  error: string | null;
  data_mode: string;
  llm_mode: string;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  is_terminal: boolean;
  asset?: Asset;
  report_id: string | null;
}

export interface RunEvent {
  run_id: string;
  seq: number;
  ts: string;
  step: string;
  type: "run" | "step" | "tool_call" | "note";
  status: string | null;
  payload: Record<string, unknown>;
}

export interface RunDetail extends Run {
  events: RunEvent[];
}

// ---------------------------------------------------------------- market & portfolio

export interface Candle {
  t: number;
  o: number;
  h: number;
  l: number;
  c: number;
  v: number;
}

export interface SeriesPoint {
  t: number;
  v: number;
}

export interface Chart {
  asset: Asset;
  snapshot: MarketSnapshot;
  candle_source: string | null;
  candles: Candle[];
  line: { t: number; v: number; volume: number }[];
  indicators: {
    source: string;
    sma_20: SeriesPoint[];
    sma_50: SeriesPoint[];
    sma_200: SeriesPoint[];
    bb_upper: SeriesPoint[];
    bb_lower: SeriesPoint[];
    rsi_14: SeriesPoint[];
  };
}

export interface HoldingLot {
  id: string;
  source: string;
  source_label: string;
  quantity: number;
  avg_cost_usd: number | null;
  notes: string | null;
}

export interface Position {
  asset: Asset;
  quantity: number;
  avg_cost_usd: number | null;
  cost_usd: number | null;
  price_usd: number | null;
  change_24h_pct: number | null;
  value_usd: number | null;
  pnl_usd: number | null;
  pnl_pct: number | null;
  price_stale: boolean;
  weight_pct: number | null;
  holdings: HoldingLot[];
}

export interface PortfolioTotals {
  total_value_usd: number;
  total_cost_usd: number;
  total_pnl_usd: number | null;
  total_pnl_pct: number | null;
  change_24h_pct: number | null;
  stale_prices: number;
}

export interface Portfolio extends PortfolioTotals {
  positions: Position[];
}

export interface PortfolioRisk {
  score: number;
  level: RiskLevel;
  weighted_asset_risk: number;
  concentration_hhi: number;
  concentration_points: number;
  largest_weight_pct: number;
  volatility_30d_pct: number | null;
  coverage_pct: number;
}

export interface AllocationSlice {
  asset: Pick<Asset, "id" | "symbol" | "name">;
  value_usd: number;
  weight_pct: number | null;
}

export interface Overview {
  data_mode: "demo" | "live";
  portfolio: PortfolioTotals & { positions: number };
  allocation: AllocationSlice[];
  risk: Record<Horizon, PortfolioRisk | null>;
  watchlist: { asset: Asset; snapshot: MarketSnapshot | null; sparkline: number[]; latest_report: ReportSummary | null }[];
  latest_report: ReportSummary | null;
  recent_runs: Run[];
  market_sentiment: { fear_greed_value: number; classification: string; as_of: string } | null;
}

export interface CsvImportResult {
  imported: { line: number; asset: Asset; quantity: number }[];
  errors: { line: number; message: string }[];
}

export interface AddressImportResult {
  chain: string;
  address: string;
  source_label: string;
  imported: { asset: Asset; quantity: number }[];
  demo: boolean;
}

export interface SettingsView {
  data_mode: "demo" | "live";
  demo: boolean;
  auth_mode: "local" | "password";
  llm: { mode: string; configured: boolean; model: string; effort: string };
  providers: { name: string; role: string; active: boolean; keyed: boolean }[];
  pipeline: { steps: string[]; max_agent_steps: number; max_repairs: number; approval_required: boolean };
  schedule: { daily_report_hour_utc: number };
  preferences: Preferences;
}

export interface Preferences {
  polymarket_enabled: boolean;
  mismatch_tolerance_pct: number;
  max_loss_pct: number;
  max_position_pct: number;
  max_slippage_pct: number;
  fee_bps: number;
  slippage_bps: number;
  horizon_days: number;
  min_volume_usd: number;
  paper_starting_cash: number;
}

export interface Problem {
  title: string;
  status: number;
  detail: string;
  request_id?: string;
}

// ---------------------------------------------------------------- trader skills (paper trading only)

export type SetupKind = "breakout" | "pullback" | "trend_reclaim";
export type SetupStatus = "active" | "extended" | "waiting";
export type Reliability = "insufficient" | "small" | "adequate";

export interface TradeMetrics {
  trades: number;
  win_rate_pct: number | null;
  avg_return_pct: number | null;
  median_return_pct: number | null;
  total_return_pct: number;
  max_drawdown_pct: number;
  sharpe: number;
  profit_factor: number | null;
  exposure_pct: number;
  buy_hold_return_pct: number;
  days: number;
}

export interface SetupParams {
  lookback: number;
  atr_mult: number;
  volume_mult: number;
  reward_r: number;
  zone_atr: number;
}

export interface ScenarioRow {
  name: "bull" | "base" | "bear";
  definition: string;
  count: number;
  total: number;
  probability_pct: number | null;
  probability_ci: [number, number] | null;
  mean_pct: number | null;
  median_pct: number | null;
  worst_drawdown_pct: number | null;
}

export interface ScenarioSet {
  kind: SetupKind;
  horizon_days: number;
  band_pct: number;
  cost_pct: number;
  overall: {
    n: number;
    wins: number;
    win_rate_pct: number | null;
    win_rate_ci: [number, number] | null;
    mean_pct: number | null;
    mean_ci: [number, number] | null;
    median_pct: number | null;
    worst_drawdown_pct: number | null;
    reliability: Reliability;
  };
  scenarios: ScenarioRow[];
}

export interface Sizing {
  units: number;
  notional_usd: number;
  pct_of_equity: number;
  max_loss_usd: number;
  loss_at_stop_usd: number;
  stop_distance_pct: number;
  expected_slippage_pct: number | null;
  binding: "max_loss" | "concentration" | "liquidity" | "correlation" | "no_trade";
  warnings: string[];
  equity_usd: number;
  entry_reference: number;
  stop: number;
  correlation_btc: number | null;
  correlations_open: Record<string, number>;
}

export interface ScanMetrics {
  close: number;
  above_sma20: boolean;
  above_sma50: boolean;
  sma20_above_sma50: boolean;
  sma20_slope_pct: number;
  trend_points: number;
  breakout: boolean;
  breakout_distance_pct: number;
  volume_ratio: number;
  return_30d_pct: number;
  rs_vs_btc_pct: number;
  volume_24h_usd: number | null;
  passes_liquidity: boolean;
  setup_kind: SetupKind;
  score: number;
}

export interface TradePlanCard {
  asset: Pick<Asset, "symbol" | "name" | "coingecko_id">;
  setup: {
    kind: SetupKind;
    status: SetupStatus;
    trend_up: boolean;
    trigger_text: string;
    close: number;
    sma20: number | null;
    sma50: number | null;
    atr: number;
  };
  timing: { trigger_level: number; entry_zone: [number, number]; invalidation: number; profit_level: number };
  risk: RiskAssessment;
  size: Sizing;
  scenarios: ScenarioSet;
  backtest: {
    in_sample: TradeMetrics;
    out_of_sample: TradeMetrics;
    walk_forward: TradeMetrics | null;
    warnings: string[];
    chosen_params: SetupParams;
  };
  scanner: ScanMetrics;
}

export interface TradePlanDraft {
  headline: Claim;
  setup: Claim[];
  timing: Claim[];
  scenarios: Claim[];
  risk: Claim[];
  invalidation: Claim[];
  evidence: Claim[];
  assumptions: Claim[];
  disclaimer: string;
  writer: string;
}

export interface TradePlanContent {
  kind: "trade_plan";
  pipeline_version: string;
  generated_at: string;
  data_mode: "demo" | "live";
  asset: Asset;
  snapshot: MarketSnapshot;
  card: TradePlanCard;
  outcomes: { date: string; return_pct: number; max_drawdown_pct: number }[];
  backtest_id: string | null;
  draft: TradePlanDraft;
  reconciliation: Reconciliation | null;
  analysts: Record<string, AnalystSummary>;
  evidence: Evidence[];
  data_gaps: string[];
  verification: ReportContent["verification"];
  disclaimer: string;
}

export interface ScanRow {
  rank: number;
  coingecko_id: string;
  symbol: string;
  name: string;
  market_cap_rank: number | null;
  asset_id: string | null;
  metrics: ScanMetrics | null;
  score: number | null;
  passes_liquidity: boolean;
  shortlisted: boolean;
  error: string | null;
}

export interface Scan {
  id: string;
  universe: "top" | "watchlist";
  top_n: number | null;
  status: "running" | "completed" | "failed";
  progress: number;
  total: number;
  results: ScanRow[] | null;
  error: string | null;
  data_mode: "demo" | "live";
  created_at: string;
  finished_at: string | null;
}

export interface BacktestSummary {
  symbol: string;
  kind: SetupKind;
  oos_trades: number;
  oos_total_return_pct: number;
  oos_buy_hold_pct: number;
  oos_sharpe: number;
  warnings: number;
  data_mode: "demo" | "live";
}

export interface BacktestConfig {
  kind: SetupKind;
  horizon: number;
  fee_bps: number;
  slippage_bps: number;
  reward_r: number;
  lookbacks: number[];
  atr_mults: number[];
  in_sample_fraction: number;
  wf_train: number;
  wf_test: number;
}

export interface BacktestResult {
  config: BacktestConfig;
  bars: number;
  first_date: string;
  last_date: string;
  approximate_bars: boolean;
  chosen_params: SetupParams;
  in_sample: TradeMetrics;
  out_of_sample: TradeMetrics;
  oos_range: [number, number];
  grid_median_sharpe: number;
  folds: { train: [number, number]; test: [number, number]; params: SetupParams; train_metrics: TradeMetrics; test_metrics: TradeMetrics }[];
  walk_forward: TradeMetrics | null;
  oos_trades: { entry_date: string; exit_date: string; entry: number; exit: number; return_pct: number; reason: string; bars_held: number }[];
  equity: { date: string; strategy: number; buy_hold: number }[];
  warnings: string[];
  assumptions: string[];
}

export interface Backtest {
  id: string;
  asset_id: string;
  run_id: string | null;
  kind: SetupKind;
  config: BacktestConfig;
  summary: BacktestSummary;
  created_at: string;
  result: BacktestResult | null;
  asset: Asset | null;
}

export type PaperStatus = "pending" | "triggered" | "open" | "closed" | "cancelled";

export interface PaperPosition {
  id: string;
  asset_id: string;
  report_id: string | null;
  origin: "plan" | "demo_replay";
  status: PaperStatus;
  setup_kind: SetupKind;
  trigger: number;
  entry_low: number;
  entry_high: number;
  stop: number;
  profit_level: number;
  horizon: number;
  expiry_bars: number;
  units: number;
  opened_on: string;
  created_at: string;
  bars_seen: number;
  bars_held: number;
  entry_price: number | null;
  entry_at: string | null;
  exit_price: number | null;
  exit_at: string | null;
  exit_reason: string | null;
  fees_usd: number;
  pnl_usd: number | null;
  asset: Asset | null;
  mark_price: number | null;
  unrealised_usd: number | null;
}

export interface PaperPerformance {
  account: { starting_cash: number; cash: number; started_on: string; last_processed: string | null };
  equity_usd: number;
  open_value_usd: number;
  return_pct: number;
  realised_pnl_usd: number;
  closed_trades: number;
  win_rate_pct: number | null;
  max_drawdown_pct: number;
  equity: { date: string; equity: number; cash: number }[];
  benchmark: { label: string; points: { date: string; value: number }[]; return_pct: number | null } | null;
  positions: PaperPosition[];
  data_mode: "demo" | "live";
}
