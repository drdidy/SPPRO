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
};

export type OperatorSnapshot = {
  generated_at: string;
  decision: {
    state: DecisionState;
    modifier: string;
    bias: string;
    scenario: string;
    confidence: number;
    risk: string;
    event_risk: string;
    planned_entry: number | null;
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
    anchor_source: string;
    anchor_confidence: string;
    levels: Array<{ label: string; value: number | null; tone: string }>;
  };
};
