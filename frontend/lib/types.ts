export type DecisionState = "ENTER CALL" | "ENTER PUT" | "WAIT" | "NO TRADE" | string;

export type Headline = {
  title: string;
  source: string;
  time: string;
  url?: string | null;
};

export type StrikeRow = {
  strike: string;
  mark: number | null;
  at_entry: number | null;
  fill: number | null;
  rr: number | null;
  budget: string;
  tag: string;
};

export type PlayAuthority = {
  execution_action?: string;
  trigger_state?: string;
  alert_state?: string;
  checklist_status?: string;
  invalidation_code?: string;
  invalidation_message?: string;
  expiry_status?: string;
  expiry_reason?: string;
  plan_validity?: string;
  timing_bucket?: string;
  budget_execution_status?: string;
  structure_valid?: boolean | null;
  move_completion_pct?: number | null;
  line_polarity_state?: string;
  line_polarity_reason?: string;
  vwap_alignment?: string;
  top_reasons?: string[];
};

export type Play = {
  title: string;
  direction: string;
  status: string;
  contract: string;
  planned_entry?: number | null;
  stop?: number | null;
  target_1?: number | null;
  target_2?: number | null;
  contracts?: number | null;
  trigger?: string;
  alert_state?: string;
  current_mark: number | null;
  at_entry: number | null;
  expected_fill: number | null;
  rr: number | null;
  zone: string;
  budget: string;
  quality: string;
  reason: string;
  authority?: PlayAuthority;
};

export type OperatorSnapshot = {
  generated_at: string;
  data_health?: {
    source: string;
    quote_quality: string;
    snapshot_age: string;
    provider: string;
    mode: string;
  };
  confirmation?: {
    status: string;
    tested_line: string;
    reason: string;
    candle_time?: string;
    engine?: string;
  };
  sit_out?: {
    active: boolean;
    reason: string;
    gap_distance?: number | null;
    narrowest_channel_width?: number | null;
  };
  decision: {
    state: DecisionState;
    modifier: string;
    bias: string;
    scenario: string;
    confidence: number;
    risk: string;
    event_risk: string;
    planned_entry: number | null;
    planned_entry_spx?: number | null;
    planned_entry_es?: number | null;
    selected_strike: string;
    expected_fill: number | null;
    budget: string;
    reason: string;
  };
  market_context: {
    risk_mode: string;
    event_risk: string;
    next_event: string;
    interpretation: string;
    headlines: Headline[];
  };
  primary_play: Play;
  alternate_play: Play;
  strike_ladders: {
    primary: StrikeRow[];
    alternate: StrikeRow[];
  };
  structure: {
    current_es: number | null;
    current_spx?: number | null;
    anchor_source: string;
    anchor_confidence: string;
    vwap?: {
      value: number | null;
      label?: string | null;
      detail?: string | null;
      alignment?: string | null;
    };
    levels: Array<{
      key?: string;
      label: string;
      value: number | null;
      tone: string;
      distance?: number | null;
      side?: string;
    }>;
  };
};
