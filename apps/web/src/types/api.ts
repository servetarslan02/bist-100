// ALPHA BIST — Shared API Response Types

// === Portfolio ===
export interface OrderData {
  id?: number | string;
  order_id?: string;
  ticker: string;
  side: "BUY" | "SELL";
  quantity: number;
  price: number;
  status: string;
  created_at?: string;
  date?: string;
  executed_at?: string;
  [key: string]: any;
}

export interface PortfolioMetrics {
  sharpe_ratio: number;
  max_drawdown: number;
  win_rate: number;
  avg_holding_days: number;
  total_trades: number;
  profit_factor: number;
  calmar_ratio: number;
  timestamp: string;
}

// === Learning ===
export interface LearningModelPerformance {
  model_name: string;
  accuracy: number;
  brier_score: number;
  directional_accuracy: number;
  weight: number;
  last_updated: string;
}

export interface LearningMatrix {
  models: LearningModelPerformance[];
  overall_accuracy: number;
  total_predictions: number;
  timestamp: string;
}

export interface LearningReport {
  summary: string;
  recent_lessons: string[];
  model_improvements: Array<{
    model: string;
    metric: string;
    before: number;
    after: number;
  }>;
  timestamp: string;
}

// === System ===
export interface DatabaseInfo {
  name: string;
  type: string;
  status: string;
  size_mb: number;
  connections: number;
  latency_ms: number;
}

export interface SystemDetailItem {
  label: string;
  value: string;
}

export interface PipelineStatItem {
  label: string;
  value: string;
}

// === Scanner ===
export interface SignalResponse {
  signals: SignalItem[];
  timestamp: string;
}

export interface SignalItem {
  ticker: string;
  name: string;
  score: number;
  direction: string;
  risk_level: string;
  horizon: string;
  expected_return_pct: number;
  spec_category: string;
  catalyst?: string;
  confidence?: number;
}

// === Chart ===
export interface CandleData {
  time: number;
  open: number;
  high: number;
  low: number;
  close: number;
}

export interface VolumeData {
  time: number;
  value: number;
  color: string;
}

export interface ChartTickData {
  candles: CandleData[];
  volumes: VolumeData[];
  ticker: string;
}

// === Stress Test ===
export interface StressTestResult {
  scenario: string;
  portfolio_impact_pct: number;
  worst_position: string;
  var_95: number;
  cvar_95: number;
  timestamp: string;
}

// === Monte Carlo ===
export interface MonteCarloResult {
  paths: number[][];
  percentiles: {
    p5: number[];
    p50: number[];
    p95: number[];
  };
  terminal_distribution: number[];
  timestamp: string;
}
