import type { OperatorSnapshot } from "./types";

export const mockSnapshot: OperatorSnapshot = {
  generated_at: new Date().toISOString(),
  decision: {
    state: "WAIT",
    modifier: "VALID",
    bias: "Bearish",
    scenario: "Between Channels",
    confidence: 74,
    risk: "Low",
    event_risk: "Major",
    planned_entry: 7211.25,
    selected_strike: "7210P",
    expected_fill: 6.88,
    budget: "Over Budget",
    reason: "Waiting for price to rally into the Asian polarity rejection line."
  },
  market_context: {
    risk_mode: "High Watch",
    event_risk: "Major",
    next_event: "No scheduled release loaded",
    interpretation: "Headline risk may widen fills and reduce estimate reliability.",
    headlines: [
      { title: "Macro calendar feed ready for high-impact events", source: "SPX Prophet", time: "Now" },
      { title: "Policy and headline shock watch is active", source: "SPX Prophet", time: "Now" },
      { title: "Live news feed can be connected after API credentials are added", source: "SPX Prophet", time: "Setup" }
    ]
  },
  primary_play: {
    title: "Primary Idea",
    direction: "Put",
    status: "Armed",
    contract: "7210P",
    planned_entry: 7211.25,
    stop: 7229.5,
    target_1: 7186.8,
    target_2: 7167.16,
    contracts: 1,
    trigger: "Upper-line rejection close within 3 points",
    alert_state: "Watch",
    current_mark: 10.8,
    at_entry: 6.63,
    expected_fill: 6.88,
    rr: 1.31,
    zone: "Near Zone",
    budget: "Over Budget",
    quality: "Moderate",
    reason: "Best bearish fit if SPX retests the upper Asian polarity line and rejects."
  },
  alternate_play: {
    title: "Alternate Idea",
    direction: "Call",
    status: "Watch",
    contract: "7180C",
    planned_entry: 7186.8,
    stop: 7167.16,
    target_1: 7211.25,
    target_2: 7228.5,
    contracts: 1,
    trigger: "Lower-line hold close within 3 points",
    alert_state: "Prepare",
    current_mark: 9.8,
    at_entry: 5.35,
    expected_fill: 5.54,
    rr: 1.05,
    zone: "Outside Zone",
    budget: "Within Budget",
    quality: "Weak",
    reason: "Informational only until bullish polarity confirms."
  },
  strike_ladders: {
    primary: [
      { strike: "7200P", mark: 8.1, at_entry: 5.22, fill: 5.39, rr: 1.18, budget: "Over", tag: "Balanced" },
      { strike: "7205P", mark: 9.4, at_entry: 5.91, fill: 6.09, rr: 1.24, budget: "Over", tag: "Best RR" },
      { strike: "7210P", mark: 10.8, at_entry: 6.63, fill: 6.88, rr: 1.31, budget: "Over", tag: "Selected" },
      { strike: "7215P", mark: 12.2, at_entry: 7.36, fill: 7.61, rr: 1.22, budget: "Over", tag: "System Pick" },
      { strike: "7220P", mark: 13.7, at_entry: 8.12, fill: 8.4, rr: 1.06, budget: "Over", tag: "Rich" }
    ],
    alternate: [
      { strike: "7170C", mark: 12.3, at_entry: 6.14, fill: 6.36, rr: 0.92, budget: "Over", tag: "Watch" },
      { strike: "7175C", mark: 10.9, at_entry: 5.71, fill: 5.92, rr: 0.98, budget: "Over", tag: "Balanced" },
      { strike: "7180C", mark: 9.8, at_entry: 5.35, fill: 5.54, rr: 1.05, budget: "Within", tag: "Selected" },
      { strike: "7185C", mark: 8.45, at_entry: 4.88, fill: 5.04, rr: 1.01, budget: "Within", tag: "Budget Fit" },
      { strike: "7190C", mark: 7.1, at_entry: 4.22, fill: 4.39, rr: 0.86, budget: "Within", tag: "Cheap" }
    ]
  },
  structure: {
    current_es: 7194.75,
    anchor_source: "Asian",
    anchor_confidence: "Medium",
    levels: [
      { label: "Upper Polarity", value: 7228.5, tone: "neutral" },
      { label: "Active Entry Line", value: 7211.25, tone: "accent" },
      { label: "Mid Structure", value: 7186.8, tone: "neutral" },
      { label: "Lower Polarity", value: 7167.16, tone: "neutral" }
    ]
  }
};
