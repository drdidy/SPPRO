# SPX PROPHET Streamlit App Handoff Specification

Last updated: 2026-04-27  
Primary file: `app.py`  
Core strategy modules: `core/`  
Tests: `tests/`  
Current product type: Streamlit production trading decision-support app for SPX/SPXW option execution using ES structure.

This document is written for another AI or engineering team that needs to understand, audit, improve, or rebuild the current Streamlit application without losing the strategy logic. The goal is to make the app cleaner, safer, and more valuable while preserving the core trading model unless a proven bug exists.

Important note: SPX PROPHET is not a generic trading dashboard. It is a deterministic operator system built around a specific ES structure strategy, SPX option execution, Asian-session anchor logic, polarity confirmation, 9:00 AM CT forward pricing, and a live operator workflow.

---

## 1. Executive Summary

SPX PROPHET is a Streamlit app that converts overnight ES structure into a live SPX options execution plan.

The app is intended to answer these questions:

1. What are the structurally relevant ES anchor pivots for the current NY session?
2. What projected ES/SPX lines matter at 9:00 AM CT?
3. Which cone or structure region is price currently inside?
4. What are the valid call and put entry lines?
5. Has price confirmed polarity, or is it only touching/extending?
6. Is the trade enterable now, should it wait for retest, or should it be skipped?
7. Which SPXW option contract should be used if the line confirms?
8. What should that option cost at the planned entry, not merely right now?
9. Is event risk, news risk, VWAP, budget, quote quality, or crowding telling the trader to reduce confidence?
10. What should be logged so the learning loop improves over time?

The current app is best understood as several engines layered together:

- Data/session engine
- Anchor selection engine
- Projection engine
- Cone scenario engine
- Polarity and trigger engine
- Execution state engine
- Options pricing and contract selection engine
- Event/news intelligence layer
- Trade log and learning layer
- Production/Edge Lab rendering layer

The most important product principle is:

```text
Structure Into Execution.
```

The app should not merely describe a chart. It should tell the operator what must happen before a trade is allowed.

---

## 2. Non-Negotiable Strategy Rules

These are core rules and should not be casually changed.

### 2.1 All Lines Are Polarity Lines

A projected line is not support or resistance by default.

It becomes:

- Support only if price touches the line and closes above it.
- Resistance only if price touches the line and closes below it.

The app must not activate a trade on a wick touch alone.

### 2.2 No Entry After Extended Rejection

If price touches a line and closes too far away from the line, that is an extended reaction, not a clean confirmation.

Current rule:

```text
If abs(close - line_price) <= 3 points:
    Valid confirmation

If abs(close - line_price) > 3 points:
    Extended reaction
    No entry
    Wait for retest
```

This is one of the most important execution safeguards.

### 2.3 Confirmed Trade Conditions

The system may allow a trade only when:

- Price touches or revisits a relevant polarity line.
- The candle closes on the correct side of the line.
- The close is within the allowed confirmation threshold.
- The structure still supports the trade.
- Stop and target authority are available.
- RR and budget are acceptable or clearly flagged.
- Event/news overlays do not require standing down.

### 2.4 Calls and Puts Are Both Available Inside Cones

Each cone has two possible plays:

- Buy/call at the cone floor after support confirmation.
- Sell/put at the cone ceiling after rejection confirmation.

This applies inside both the high cone and the low cone.

### 2.5 Above and Below Cone Extremes Are Single-Direction States

If price is completely above the high cone:

- The only structural trade is a buy/call on a retest/hold of the high cone ceiling.

If price is completely below the low cone:

- The only structural trade is a sell/put on a retest/reject of the low cone floor.

### 2.6 Asian Session Is Primary

The Asian session is the most important anchor source for the current strategy.

Current Asian window:

```text
5:00 PM CT to 2:00 AM CT
```

Reason:

- Early Globex and Asian session pivots often define the line NY respects.
- The app should not blindly wait for the prior NY 12 PM to 4 PM anchor if Asian pivots have already created the active line.

### 2.7 News Candle Override Rule

London is not normally the primary anchor unless a news event changes the structure.

Special news rule:

- If a high-impact 7:30 AM CT event causes price to shoot above an Asian anchor and close back below it, the highest point of the 7:00 AM CT news candle may become the anchor for that session.
- If price shoots below an Asian anchor and closes back above it, the lowest point of the 7:00 AM CT news candle may become the anchor for that session.
- If the news candle does not touch/break/reclaim the Asian anchor, Asian remains the main anchor.

The app has a news reclaim anchor candidate system for this purpose.

---

## 3. Current App Files and Responsibilities

### 3.1 `app.py`

`app.py` is the main Streamlit app and currently contains many layers:

- Streamlit page layout and CSS.
- App state initialization.
- User input sidebar.
- Anchor selection wrappers.
- Scenario context generation.
- Execution state logic.
- Options chain rendering.
- Trade log and intelligence tabs.
- Market intelligence/news rendering.
- Snapshot export for the Next.js frontend.

This file is large and should be refactored eventually, but do not split it recklessly without tests.

### 3.2 `core/scenarios.py`

This module contains the current cone-based scenario engine.

The app should use five scenario regions:

1. `SCENARIO 1: BETWEEN CONES`
2. `SCENARIO 2: INSIDE HIGH CONE`
3. `SCENARIO 3: INSIDE LOW CONE`
4. `SCENARIO 4: ABOVE HIGH CONE`
5. `SCENARIO 5: BELOW LOW CONE`

Cone overlap is folded into Scenario 1 as neutral/compression, not as a sixth scenario.

### 3.3 `core/pivots.py`

This module contains pivot context and anchor derivation logic.

Important distinction:

- `true_extreme_time`: the candle where the actual high/low extreme printed.
- `pivot_time` or `projection_start_time`: the confirmation or projection-start timestamp used by line projection math.

The UI should display true pivot extreme time when telling the user where the anchor came from.

The projection engine may still use projection-start time internally. This distinction is intentional.

### 3.4 `core/projections.py`

This module handles projection of six structural lines.

Do not change projection math without a proven bug.

### 3.5 `options_provider.py`

This module handles options data provider abstractions and Tastytrade lookup plumbing.

Do not rewrite provider plumbing casually. The app depends on:

- Option symbol lookup.
- Chain retrieval.
- Bid/ask/last/mark.
- Greeks if available.
- Expiration and strike matching.

### 3.6 `tests/`

The test suite is important. It contains coverage for:

- Scenario rules.
- Cone output.
- Anchor selection.
- News reclaim behavior.
- Polarity confirmation.
- Options pricing.
- Contract binding.
- Trade prefill.
- UI helper behavior.

Any meaningful change should run:

```bash
python -m py_compile app.py core\pivots.py core\scenarios.py
python -m unittest discover -s tests -v
```

---

## 4. App Modes and Main User Workflow

### 4.1 Production Mode

Production Mode should be calm, minimal, and decision-first.

It should show:

- Decision state.
- Market bias.
- Live scenario.
- Planned entry.
- Selected strike.
- Current mark.
- At-entry estimate.
- Expected fill.
- Confidence.
- Risk.
- Budget fit.
- Event risk.
- One concise reason.

Production Mode should hide:

- Raw debug details.
- Duplicate warnings.
- Repeated scenario strings.
- Raw calibration internals.
- Excessive chain metrics.
- Developer-like phrasing.
- Repeated "insufficient" messages.

### 4.2 Edge Lab

Edge Lab is the dense research/debug/diagnostic area.

It may expose:

- Raw candidate anchor tables.
- Calibration details.
- Scenario transition details.
- Ranking reasons.
- Quote provider diagnostics.
- Full chain view.
- Replay/research analysis.

Edge Lab can be detailed, but it must still be clean and must not leak raw Streamlit objects or `DeltaGenerator` output.

### 4.3 Pre-Market Prep

Pre-Market Prep is the session structure preparation surface.

It should show:

- Evening/Asian/London/Pre-Open phase state.
- Whether each session is upcoming, active, or done.
- Current selected anchors.
- Projected 9:00 AM CT levels.
- Pre-open structure context.

Important:

- On Saturday before Sunday Globex opens, Asian and London must not show as done for the upcoming session.
- Asian is 5 PM to 2 AM CT.

### 4.4 Historical Projection Mode

Historical mode allows the user to select prior dates and see what the engine would have produced for a target projection time, usually 9:00 AM CT.

It must use the same anchor/scenario logic as live mode.

If historical mode shows different anchors than live mode for the same inputs, that is a bug.

### 4.5 Trade Log

Trade Log is the journal of reviewed real outcomes.

It should stay journal-focused:

- Entry details.
- Exit details.
- Outcome.
- Tags.
- Notes.
- Confirmation status.
- Strategy metadata captured at prefill.

Do not pollute real trade log learning with synthetic historical bootstrap records.

### 4.6 Intelligence Tab

Intelligence should be dashboard/research-focused:

- Aggregated performance.
- Bias by scenario.
- Anchor performance.
- Regime behavior.
- Calibration/research summaries.
- YTD bootstrap/research data.

It should not duplicate Trade Log tables unnecessarily.

---

## 5. Data and State Stores

### 5.1 Trade Log

File:

```text
trade_log.json
```

Purpose:

- Stores reviewed or manually logged trades.
- Used for live learning/calibration only when records are real or reviewed.

### 5.2 Daily Snapshots

File:

```text
daily_snapshots.json
```

Purpose:

- Stores session snapshots, structure state, and related plan metadata.

### 5.3 Research Calibration

File:

```text
research_calibration.json
```

Purpose:

- Stores synthetic or historical research bootstrap output separately from real trade outcomes.
- Should not be mixed with the live trade log as if all records were reviewed trades.

### 5.4 Settings

File:

```text
settings.json
```

Purpose:

- Stores user settings and preferences such as budget, provider, controls, anchor overrides, etc.

### 5.5 Frontend Operator Snapshot

File:

```text
data/operator_snapshot.json
```

Purpose:

- Exports a structured operator snapshot for the Next.js/frontend prototype.
- The Streamlit app remains the source of strategy intelligence unless/until a backend API is built.

---

## 6. Session and Time Model

The app uses Central Time as the primary trading-session clock.

### 6.1 Important Sessions

Recommended current session windows:

```text
Prior NY / PM window: 12:00 PM to 4:00 PM CT
Asian session: 5:00 PM to 2:00 AM CT
London / Pre-NY: 2:00 AM to 7:00 AM CT
News candle window: 7:00 AM to 8:00 AM CT
Pre-open refinement: 7:00 AM to 8:25 AM CT
NY regular open: 8:30 AM CT
Primary projection target: 9:00 AM CT
```

### 6.2 9:00 AM CT Is the Main Projection Target

The options pricing engine and structure projections are designed around estimating values at 9:00 AM CT.

This is important because:

- SPX options pricing changes after open.
- IV and spreads behave differently before/after open.
- The user's strategy is centered around the structure that matters into NY execution.

### 6.3 ES/SPX Offset

The app converts ES structure to SPX execution levels using an effective offset.

Offset can be:

- Manual.
- Live inferred.
- Historical/default.

Do not allow offset errors to silently produce nonsense entries.

---

## 7. Anchor Selection Engine

### 7.1 Why Anchor Selection Exists

The old system used a fixed prior-day PM anchor window too rigidly.

The current strategy requires a session-aware anchor engine because:

- Asian pivots often matter more than the prior NY 12 PM to 4 PM pivots.
- NY may respect the Asian line before reaching the old PM line.
- A news candle can occasionally override Asian if it breaks and reclaims an Asian anchor.

### 7.2 Candidate Anchor Sources

The engine evaluates:

1. PM Window
2. Asian
3. London
4. Pre-NY
5. News reclaim candidate

### 7.3 Candidate Fields

Each candidate should store:

- `pivot_price`
- `pivot_time`
- `pivot_type`
- `session_source`
- `session_label`
- `candle_context`
- `true_extreme_price`
- `true_extreme_time`
- `touch_count_if_available`
- `distance_to_current_price`
- `line_projection_to_NY_open`
- `projected_level_at_8_30`
- `projected_level_at_9_00`
- `projected_level_at_current`
- `candidate_rank_score`
- `selection_reason`

### 7.4 Scoring Rules

Candidate scoring considers:

- Session weight.
- Extremeness.
- Projection proximity.
- Reaction evidence.
- Time relevance.
- Line respect.

Asian should generally win unless:

- News reclaim override is triggered.
- Manual override is active.
- A different source is provably more structurally active.

### 7.5 Locking Rule

Before session lock:

- Anchor selection may update as new overnight data arrives.

At session lock:

- Freeze selected anchors for the session.

After lock:

- Do not silently overwrite selected anchors.
- If price later respects a different line, show "Alternative anchor line being respected" or similar.

### 7.6 Display Rule

Production labels should show true pivot extreme time:

```text
Asc Floor: Asian 5:00 PM CT
Desc Ceiling: Asian 5:00 PM CT
Anchor Confidence: Medium
```

If needed in Edge Lab, show both:

```text
True extreme: 5:00 PM CT
Projection start: 6:00 PM CT
```

---

## 8. Cone Structure Model

### 8.1 Core Principle

From the Asian high pivot and Asian low pivot:

- Each pivot produces an ascending line and a descending line.
- The high pivot creates the high cone.
- The low pivot creates the low cone.

### 8.2 High Cone

High pivot lines:

- High cone ceiling: high pivot ascending line.
- High cone floor: high pivot descending line.

If price is inside the high cone:

- Buy at the floor after support confirmation.
- Sell at the ceiling after rejection confirmation.

### 8.3 Low Cone

Low pivot lines:

- Low cone ceiling: low pivot ascending line.
- Low cone floor: low pivot descending line.

If price is inside the low cone:

- Buy at the floor after support confirmation.
- Sell at the ceiling after rejection confirmation.

### 8.4 Five Scenario Regions

The app should now think in five structural regions:

1. Above high cone
2. Inside high cone
3. Between cones
4. Inside low cone
5. Below low cone

The names in the app are currently:

```text
SCENARIO 1: BETWEEN CONES
SCENARIO 2: INSIDE HIGH CONE
SCENARIO 3: INSIDE LOW CONE
SCENARIO 4: ABOVE HIGH CONE
SCENARIO 5: BELOW LOW CONE
```

### 8.5 Directional Meaning

Inside high cone:

- Often structurally bullish at 9:00 AM because the floor can act as buy support.
- But it can still reject from the ceiling and close red later.
- Do not over-label it as permanently bullish.

Inside low cone:

- Often structurally bearish at 9:00 AM because the ceiling can act as sell resistance.
- But it can still support from the floor and rally later.
- Do not over-label it as permanently bearish.

This is why polarity confirmation matters more than simple scenario names.

---

## 9. Polarity and Trigger Engine

### 9.1 Inputs

The polarity engine uses:

- Current candle high/low/close.
- Projected line price.
- Direction.
- Touch tolerance.
- Close confirmation threshold.
- VWAP context if available.

### 9.2 Touch Rule

Current rule:

```text
touched = low <= line_price <= high, with approximately 1 point tolerance
```

### 9.3 Close Rule

For support:

```text
close > line_price
abs(close - line_price) <= 3 points
```

For resistance:

```text
close < line_price
abs(close - line_price) <= 3 points
```

### 9.4 Extended Reaction

If price touches and closes more than 3 points away:

```text
actionable = false
state = extended_reaction
wait_for_retest = true
```

### 9.5 Retest Logic

If extended reaction happens:

- Mark line as pending retest.
- Wait for price to return to same line.
- Allow trade only if close confirms within threshold.

### 9.6 Output Format

The polarity decision should be machine-usable:

```text
decision: TRADE / WAIT / NO TRADE
score: 0-100
line_used:
  name
  type
  source
polarity_state:
  support_hold
  resistance_rejection
  extended_rejection
  pending_retest
actionable: true/false
distance_to_line
close_distance
vwap_alignment
reason
```

---

## 10. Scenario and Execution State Engine

The app uses scenario state, plan validity, trigger state, timing, risk, budget, and event overlays to produce an operator action.

### 10.1 Plan Validity

Plan validity values:

- `valid`
- `valid_but_late`
- `caution`
- `stale`
- `invalid`

The app should invalidate or stale-lock old plans if live structure shifts too far from the locked premise.

### 10.2 Timing Buckets

Timing buckets:

- `early`
- `ideal`
- `good`
- `late`
- `exhausted`
- `chasing_premium`
- `unavailable`

### 10.3 Setup States

Allowed setup states:

- `LOCKED`
- `ARMED`
- `READY`
- `TRIGGERED`
- `ACTIVE`
- `INVALIDATED`
- `EXPIRED`
- `NO_TRADE`

The UI should not show conflicting states like:

```text
NO TRADE + UNTRADEABLE + INVALIDATED + SKIP TRADE
```

One primary decision should dominate.

### 10.4 Execution Actions

Allowed execution actions:

- `ENTER NOW`
- `WAIT`
- `WAIT FOR RETEST`
- `DOWNGRADE STRIKE`
- `REDUCE SIZE`
- `SKIP TRADE`

Production UI should translate these into cleaner operator language:

- `WAIT`
- `ENTER PUT`
- `ENTER CALL`
- `NO TRADE`
- `ENTER WITH CAUTION`

### 10.5 Alert States

Alert states:

- `QUIET`
- `WATCH`
- `PREPARE`
- `READY`
- `ACT_NOW`
- `INVALIDATED`
- `EXPIRED`

Alerts should be compact. Do not show a long alert log in Production Mode.

---

## 11. Stop and Target Authority

Each play should have:

- Authoritative stop.
- Target 1.
- Target 2.
- RR to target 1.
- RR to target 2.
- Risk from entry.
- Reward to target.

Do not invent levels if structure does not support them.

If stop/target authority is weak:

- Mark it clearly.
- Suppress actionability if needed.
- Avoid fake precision.

---

## 12. Options Pricing Engine

### 12.1 Purpose

The app must estimate what a selected SPXW contract should cost when the underlying reaches the planned entry line, especially at 9:00 AM CT.

This is not the same as showing the current mark.

### 12.2 Important Output Fields

For each selected/recommended contract:

- Current Mark
- At Entry Estimate
- Expected Fill
- Estimate Quality
- Budget Status
- RR
- Contract short label, such as `7155P`

### 12.3 Pricing Inputs

Use all available Tastytrade fields:

- Mark
- Bid
- Ask
- Last
- Delta
- Gamma
- Theta
- Vega
- Implied volatility
- Strike
- Option type
- Expiration
- Spread width
- Liquidity score
- Event risk level
- Calibration/slippage bias if available

### 12.4 Layered Pricing Model

Current desired model:

1. Underlying move:

```text
dS = target_underlying_price - current_underlying_price
```

2. Delta plus gamma:

```text
price_change = delta * dS + 0.5 * gamma * dS^2
```

3. Theta decay:

```text
dT = minutes_to_target / (60 * 24)
theta_impact = theta * dT
```

4. IV adjustment:

- Apply IV compression into the open if appropriate.
- Apply IV expansion for major event risk if appropriate.

5. Spread/fill penalty:

- Expected fill must be worse than theoretical mark.
- Wider spreads and event risk increase the fill penalty.

6. Clamp:

- No negative premiums.
- Minimum long option mark should be at least 0.01.

### 12.5 Estimate Quality

Estimate quality values:

- `Strong`
- `Moderate`
- `Weak`
- `Insufficient`

Quality should degrade if:

- Greeks are missing.
- Quotes are stale.
- Spread is wide.
- Event risk is high.
- Current underlying is far from entry.
- Calibration evidence is weak.

### 12.6 Contract Binding Rule

Every displayed premium field must come from the same selected contract:

- Symbol
- Strike
- Option type
- Mark
- Projected mark
- Expected fill
- RR
- Budget fit

If mismatch occurs:

- Fail safely.
- Do not render mixed contract data.

---

## 13. Contract Selection and Strike Ladder

### 13.1 Selected Contract Authority

After lock:

- Selected strike should not drift automatically on refresh.
- Manual user selection should persist.
- If contract disappears, fail gracefully.

### 13.2 Ranking Criteria

Nearby strikes should rank by:

1. Direction and structure validity.
2. Expected fill at planned entry.
3. RR quality.
4. Budget fit.
5. Liquidity/spread quality.
6. Estimate quality.
7. Not being too cheap/thin.

### 13.3 Minimum Viable Premium

Minimum recommended execution mark:

```text
MIN_EXECUTION_MARK = 0.20
```

Contracts below this may appear in ladder but should not become recommended execution strikes unless manually chosen.

### 13.4 Production Ladder Columns

Production Mode should show only:

- Strike
- Current mark
- At-entry estimate
- Expected fill
- RR
- Budget
- Tag

Full chain details belong in Edge Lab or an expander.

---

## 14. Event and News Intelligence

### 14.1 Purpose

Event/news risk is an execution overlay, not a scenario math override.

It can:

- Reduce confidence.
- Widen uncertainty.
- Penalize expected fill.
- Change guidance from enter to caution/wait.

It should not:

- Rewrite the structural lines.
- Fabricate news.
- Claim certainty where sources are unavailable.

### 14.2 Relevant News Categories

The feed should prioritize:

- CPI
- PPI
- NFP/jobs/unemployment
- GDP
- FOMC
- Fed speakers/Powell
- Rates/yields
- Major breaking market headlines
- Market-moving policy headlines
- Trump/Truth Social or political shock headlines only if market relevant

### 14.3 Market Context Card

Production should show:

- Event risk level.
- Next known high-impact event.
- 3 to 5 relevant headlines.
- One interpretation line.

If feed is unavailable:

```text
Live news unavailable
```

Do not fabricate headlines.

### 14.4 Event Risk Levels

Suggested levels:

- Quiet
- Low
- Medium
- High
- Extreme

### 14.5 Event Effects

Example:

If structure is valid but event risk is high:

- Do not invalidate structure.
- Downgrade execution confidence.
- Possibly show `Enter with caution` or `Wait for event pass`.

---

## 15. 5-Minute VWAP

The app uses 5-minute ES VWAP as a dynamic confirmation layer.

Purpose:

- If bullish and price is above VWAP, bullish alignment improves.
- If bearish and price is below VWAP, bearish alignment improves.
- If misaligned, downgrade confidence.

VWAP should not override structure by itself.

If VWAP data is unavailable:

- Show a compact unavailable label.
- Do not spam repeated warnings.

---

## 16. Crowding and Absorption Proxy

The user wants to know if a direction is too retail-heavy.

With current data, the app cannot truly identify dark pools.

It can provide proxies:

- Options crowding near strike.
- Put/call skew if data available.
- Bid/ask and quote pressure proxies.
- Price behavior around lines.
- Wick/close absorption around structural levels.
- VWAP alignment/misalignment.

Important UI wording:

- Do not say "dark pool detected."
- Use wording like "Absorption risk elevated" or "Crowding proxy elevated."

---

## 17. Trade Log and Learning Loop

### 17.1 Real Trade Learning

The app learns from reviewed trade log outcomes:

- Win/loss/breakeven.
- Entry quality.
- Scenario.
- Anchor source.
- Trigger state.
- Contract estimate accuracy.
- Event/news context.

### 17.2 Research Bootstrap

The app also supports historical research bootstrap.

This must stay separate from real trade log outcomes.

Research data can help:

- Identify scenario tendencies.
- Compare anchor source performance.
- Analyze YTD behavior.
- Improve calibration estimates.

But it should not be treated as reviewed live outcome data unless the user explicitly reviews it.

---

## 18. Production UI Principles

### 18.1 Decision First

The first visible surface must answer:

```text
What should I do right now?
```

Examples:

- Wait.
- Enter put.
- Enter call.
- No trade.
- Enter with caution.

### 18.2 Avoid Analysis Paralysis

Do not show the same idea in five places.

Rules:

- Final decision appears prominently once.
- Why no trade appears once.
- Structure change note appears once.
- Budget status appears once per play.
- Override state appears once.

### 18.3 Production Card Content

Primary and alternate cards should show:

- Direction/contract.
- Status.
- Current mark.
- At trigger.
- Expected fill.
- Entry.
- Stop.
- T1.
- T2.
- RR.
- Confirmation rule.
- Plan size or relevant risk.

Avoid clutter:

- Do not show repeated "Line confirmation unavailable."
- Do not show raw HTML.
- Do not show internal strings.
- Do not show `DeltaGenerator`.

### 18.4 Typography and Styling

The user prefers a premium operator product, not a debug dashboard.

Production UI should use:

- Larger readable text.
- Clear hierarchy.
- Dark premium aesthetic unless otherwise decided.
- Consistent card styling.
- Compact but legible sections.
- No overlapping expander icons/text.

---

## 19. Current Known Product Issues to Watch

These are recurring risks that future work should audit carefully:

1. Raw HTML leaking into Streamlit cards.
2. Streamlit `DeltaGenerator` objects being accidentally rendered with `st.write`.
3. Duplicate state labels such as no trade plus invalidated plus skip trade.
4. Anchor label showing projection-start time instead of true pivot time.
5. Historical mode accidentally using old PM-window anchors instead of session-aware anchors.
6. Contract display showing full Tastytrade symbol instead of readable short label.
7. Primary and alternate cards becoming visually inconsistent.
8. Market intelligence showing unavailable data too noisily.
9. Edge Lab duplicating Trade Log.
10. Streamlit Material icon text rendering if CSS overrides icon font.

---

## 20. Required Validation

Always run after meaningful changes:

```bash
python -m py_compile app.py
python -m py_compile core\pivots.py core\scenarios.py core\projections.py
python -m unittest discover -s tests -v
```

If working on frontend snapshot or Next.js prototype:

```bash
cd frontend
npm run lint
npm run build
```

Do not push changes without validation unless explicitly told to skip.

---

## 21. Phase-Based Build Plan for Another AI

The following phases are designed so another AI can rebuild or improve the app without losing the strategy.

### Phase 0: Full Audit and Guardrails

Goal:

- Understand current code paths.
- Identify data flow.
- Verify tests.
- Prevent accidental strategy drift.

Tasks:

- Read `app.py`, `core/scenarios.py`, `core/pivots.py`, `core/projections.py`, `options_provider.py`.
- Run full tests.
- List existing state stores.
- Identify all render functions.
- Identify all functions that affect scenario/entry/contract selection.

Output:

- Audit summary.
- Known risks.
- No code changes unless fixing a crash.

### Phase 1: Session and Data Foundation

Goal:

- Make sure time/session logic is correct.

Tasks:

- Confirm Central Time handling.
- Confirm Asian window is 5 PM to 2 AM CT.
- Confirm historical mode uses selected trading date correctly.
- Confirm weekend and Sunday Globex state logic.
- Confirm ES/SPX offset handling.

Tests:

- Saturday before Sunday Globex shows Asian upcoming.
- Sunday 6 PM CT shows Asian active.
- Monday 1:30 AM CT still shows Asian active.
- Monday 2:30 AM CT shows London active.

### Phase 2: Anchor Selection Engine

Goal:

- Ensure the app chooses correct session anchors.

Tasks:

- Build candidate anchors from PM, Asian, London, Pre-NY.
- Keep Asian primary.
- Allow news reclaim override only when rule is satisfied.
- Store true extreme time separately from projection start.
- Display true pivot time in Production.
- Display both times in Edge Lab.

Tests:

- Asian overrides PM when structurally relevant.
- News candle overrides Asian only when break/reclaim occurs.
- Manual override works.
- Locked anchor does not silently change.

### Phase 3: Cone Scenario Engine

Goal:

- Ensure five scenario regions are correct.

Tasks:

- Use high pivot lines to create high cone.
- Use low pivot lines to create low cone.
- Classify above high cone, inside high cone, between cones, inside low cone, below low cone.
- Fold overlap/compression into neutral Scenario 1.
- Ensure primary/alternate plays match cone logic.

Tests:

- All five scenarios.
- Above high cone only call continuation.
- Below low cone only put continuation.
- Inside high cone has floor buy and ceiling sell.
- Inside low cone has floor buy and ceiling sell.

### Phase 4: Polarity and Retest Engine

Goal:

- Prevent premature trades.

Tasks:

- Evaluate nearest lines.
- Require touch plus close.
- Require close within 3 points.
- Mark extended reaction as wait for retest.
- Keep pending retest memory.
- Include VWAP alignment.

Tests:

- Touch only does not trade.
- Extended rejection does not trade.
- Clean close near line allows trade.
- Retest confirmation allows trade.
- Opposite-side close invalidates the setup.

### Phase 5: Stop, Target, and Execution Authority

Goal:

- Turn structure into an executable operator plan.

Tasks:

- Compute stop and targets from structural lines.
- Compute RR.
- Build setup state.
- Build trigger state.
- Build action state.
- Build alert state.
- Suppress trade if stop/target unavailable.

Tests:

- Stop null-safe.
- RR too low blocks trade.
- Move spent expires trade.
- Trigger state transitions correctly.

### Phase 6: Options Pricing Engine

Goal:

- Estimate contract price at planned entry and at 9:00 AM CT.

Tasks:

- Use Tastytrade mark, bid, ask, Greeks, IV.
- Apply delta/gamma/theta/vega model.
- Apply spread and liquidity penalty.
- Apply event risk adjustment.
- Clamp negative values.
- Produce estimate quality.

Tests:

- Favorable move increases option value.
- Theta lowers value over time.
- IV crush lowers value into open.
- Expected fill is greater than or equal to projected mark.
- Missing Greeks degrade quality without crash.

### Phase 7: Contract Selection and Strike Ladder

Goal:

- Choose stable, executable contracts.

Tasks:

- Keep selected contract bound to plan.
- Rank contracts by expected fill, RR, budget, liquidity, quality.
- Prevent low-price garbage contracts from being recommended.
- Keep nearby ladder compact in Production.
- Put full chain in Edge Lab.

Tests:

- Selected contract does not drift on refresh.
- Contract binding mismatch fails safely.
- Within-budget viable contract is preferred.
- Full chain with missing fields does not crash.

### Phase 8: Event and Market Intelligence

Goal:

- Add relevant market context without clutter.

Tasks:

- Show high-impact economic events.
- Show relevant headlines.
- Include policy/Trump shock risk only if market relevant.
- Avoid fake news.
- Apply event risk as execution overlay.

Tests:

- Calendar unavailable fails gracefully.
- News unavailable fails gracefully.
- High event risk downgrades action.
- Irrelevant headlines are filtered out.

### Phase 9: Trade Log, Intelligence, and Research Learning

Goal:

- Keep live learning clean and useful.

Tasks:

- Trade Log remains reviewed journal.
- Intelligence becomes research dashboard.
- Historical bootstrap writes to research dataset only.
- Store anchor/source/execution fields in logs.
- Avoid duplicate tables.

Tests:

- Trade log schema backward-compatible.
- Research bootstrap does not pollute trade log.
- Intelligence summary handles low-data states.

### Phase 10: Production UI Cleanup

Goal:

- Make the app calm, premium, and easy to understand.

Tasks:

- One decision-first hero.
- Compact primary and alternate cards.
- Clean Market Context card.
- Polished Structure Map.
- No raw HTML leakage.
- No duplicate warnings.
- No debug strings in Production.

Tests:

- Production helpers do not output duplicate "why no trade."
- HTML sanitizer removes leaked tags.
- Missing optional fields do not crash.
- Icon CSS does not render Material icon names as text.

### Phase 11: API and Next.js Production Surface

Goal:

- Eventually move the production operator surface out of Streamlit.

Tasks:

- Keep Streamlit as strategy lab/admin initially.
- Expose a backend API or operator snapshot.
- Build Next.js as production UI.
- Preserve exact Streamlit operator output before redesigning deeply.
- Validate visual UI against actual strategy states.

Warning:

- Do not build a beautiful frontend that does not match the strategy.
- Strategy correctness comes before animation.

---

## 22. Suggested Refactor Roadmap

The current app works, but `app.py` is too large. A careful refactor could split it into:

```text
app.py
core/
  pivots.py
  projections.py
  scenarios.py
  polarity.py
  execution.py
  pricing.py
  events.py
  learning.py
ui/
  styles.py
  live.py
  premarket.py
  trade_log.py
  intelligence.py
  edge_lab.py
providers/
  tastytrade.py
storage/
  json_store.py
```

Do this only after tests are strong enough to protect behavior.

---

## 23. What Another AI Must Not Do

Do not:

- Revert to old 12 PM to 4 PM-only anchor logic.
- Treat lines as support/resistance before polarity confirmation.
- Enter after extended rejection.
- Use current option mark as planned entry price.
- Mix contract fields from different symbols.
- Claim dark pool detection from insufficient data.
- Show raw debug objects in Production.
- Remove intelligence just because UI is crowded.
- Pollute Trade Log with synthetic research outcomes.
- Change projection/channel math without proving a bug.

---

## 24. What Another AI Should Improve First

Best next improvements:

1. Create a small structured backend/service layer around the existing engines.
2. Refactor `app.py` into testable modules.
3. Add visual tests or snapshot tests for Production Mode helper output.
4. Strengthen anchor candidate diagnostics in Edge Lab.
5. Improve historical replay UX.
6. Make Market Intelligence more reliable and less noisy.
7. Build a true API for the Next.js frontend.
8. Keep Streamlit as research/admin until the web app fully matches strategy output.

---

## 25. Final Product North Star

SPX PROPHET should feel like an operator-grade execution system:

```text
Asian anchor selected.
Price is inside the low cone.
Upper line is the put rejection gate.
Lower line is the call support gate.
No trade on touch alone.
Wait for close within 3 points.
If confirmed, use the selected contract.
Expected fill at 9:00 AM CT is X.
Event risk is Y.
Action: wait, enter, or stand down.
```

The user should be able to understand the whole live state in under five seconds.

The system should be deterministic, truthful, compact, and safe for real-money decision support.

