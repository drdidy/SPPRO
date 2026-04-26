import { mockSnapshot } from "./mockData";
import type { Headline, OperatorSnapshot, Play, StrikeRow } from "./types";

function asNumber(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function asString(value: unknown, fallback = ""): string {
  return typeof value === "string" && value.trim() ? value : fallback;
}

function normalizeStrikeRows(value: unknown): StrikeRow[] {
  if (!Array.isArray(value)) {
    return [];
  }
  return value.map((row) => {
    const source = row && typeof row === "object" ? row as Partial<StrikeRow> : {};
    return {
      strike: asString(source.strike, "-"),
      mark: asNumber(source.mark),
      at_entry: asNumber(source.at_entry),
      fill: asNumber(source.fill),
      rr: asNumber(source.rr),
      budget: asString(source.budget, "Unknown"),
      tag: asString(source.tag, "Candidate")
    };
  });
}

function normalizePlay(value: unknown, fallback: Play): Play {
  const source = value && typeof value === "object" ? value as Partial<Play> : {};
  return {
    ...fallback,
    ...source,
    title: asString(source.title, fallback.title),
    direction: asString(source.direction, fallback.direction),
    status: asString(source.status, fallback.status),
    contract: asString(source.contract, fallback.contract),
    planned_entry: asNumber(source.planned_entry ?? fallback.planned_entry),
    stop: asNumber(source.stop ?? fallback.stop),
    target_1: asNumber(source.target_1 ?? fallback.target_1),
    target_2: asNumber(source.target_2 ?? fallback.target_2),
    contracts: asNumber(source.contracts ?? fallback.contracts),
    trigger: asString(source.trigger, fallback.trigger ?? ""),
    alert_state: asString(source.alert_state, fallback.alert_state ?? ""),
    current_mark: asNumber(source.current_mark),
    at_entry: asNumber(source.at_entry),
    expected_fill: asNumber(source.expected_fill),
    rr: asNumber(source.rr),
    zone: asString(source.zone, fallback.zone),
    budget: asString(source.budget, fallback.budget),
    quality: asString(source.quality, fallback.quality),
    reason: asString(source.reason, fallback.reason)
  };
}

function normalizeHeadlines(value: unknown): Headline[] {
  if (!Array.isArray(value)) {
    return [];
  }
  return value.map((item) => {
    const source = item && typeof item === "object" ? item as Partial<Headline> : {};
    return {
      title: asString(source.title, "Market context unavailable"),
      source: asString(source.source, "SPX Prophet"),
      time: asString(source.time, ""),
      url: source.url ?? null
    };
  });
}

export function normalizeOperatorSnapshot(value: unknown): OperatorSnapshot {
  const source = value && typeof value === "object" ? value as Partial<OperatorSnapshot> : {};
  return {
    generated_at: asString(source.generated_at, mockSnapshot.generated_at),
    decision: {
      ...mockSnapshot.decision,
      ...(source.decision ?? {}),
      state: asString(source.decision?.state, mockSnapshot.decision.state),
      modifier: asString(source.decision?.modifier, mockSnapshot.decision.modifier),
      bias: asString(source.decision?.bias, mockSnapshot.decision.bias),
      scenario: asString(source.decision?.scenario, mockSnapshot.decision.scenario),
      confidence: asNumber(source.decision?.confidence) ?? mockSnapshot.decision.confidence,
      risk: asString(source.decision?.risk, mockSnapshot.decision.risk),
      event_risk: asString(source.decision?.event_risk, mockSnapshot.decision.event_risk),
      planned_entry: asNumber(source.decision?.planned_entry),
      selected_strike: asString(source.decision?.selected_strike, mockSnapshot.decision.selected_strike),
      expected_fill: asNumber(source.decision?.expected_fill),
      budget: asString(source.decision?.budget, mockSnapshot.decision.budget),
      reason: asString(source.decision?.reason, mockSnapshot.decision.reason)
    },
    market_context: {
      ...mockSnapshot.market_context,
      ...(source.market_context ?? {}),
      risk_mode: asString(source.market_context?.risk_mode, mockSnapshot.market_context.risk_mode),
      event_risk: asString(source.market_context?.event_risk, mockSnapshot.market_context.event_risk),
      next_event: asString(source.market_context?.next_event, mockSnapshot.market_context.next_event),
      interpretation: asString(source.market_context?.interpretation, mockSnapshot.market_context.interpretation),
      headlines: normalizeHeadlines(source.market_context?.headlines)
    },
    primary_play: normalizePlay(source.primary_play, mockSnapshot.primary_play),
    alternate_play: normalizePlay(source.alternate_play, mockSnapshot.alternate_play),
    strike_ladders: {
      primary: normalizeStrikeRows(source.strike_ladders?.primary),
      alternate: normalizeStrikeRows(source.strike_ladders?.alternate)
    },
    structure: {
      ...mockSnapshot.structure,
      ...(source.structure ?? {}),
      current_es: asNumber(source.structure?.current_es),
      anchor_source: asString(source.structure?.anchor_source, mockSnapshot.structure.anchor_source),
      anchor_confidence: asString(source.structure?.anchor_confidence, mockSnapshot.structure.anchor_confidence),
      levels: Array.isArray(source.structure?.levels) ? source.structure.levels.map((level) => ({
        label: asString(level?.label, "Structure Line"),
        value: asNumber(level?.value),
        tone: asString(level?.tone, "neutral")
      })) : []
    }
  };
}
