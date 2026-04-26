"use client";

import type { CSSProperties } from "react";
import { useEffect, useMemo, useState } from "react";
import { AnimatePresence, motion, useReducedMotion } from "framer-motion";
import type { OperatorSnapshot, StrikeRow } from "@/lib/types";
import { formatPrice, toneFor } from "@/lib/format";
import { commandBackdropVariants, commandPanelVariants, panelVariants, shellVariants } from "@/lib/motion";

export function OperatorWorkspace({ snapshot }: { snapshot: OperatorSnapshot }) {
  const primary = snapshot.primary_play;
  const alternate = snapshot.alternate_play;
  const decision = snapshot.decision;
  const context = snapshot.market_context;
  const structure = snapshot.structure;
  const primaryRows = snapshot.strike_ladders.primary;
  const alternateRows = snapshot.strike_ladders.alternate;
  const [selectedStrike, setSelectedStrike] = useState(primaryRows.find((row) => row.tag === "Selected")?.strike ?? primaryRows[0]?.strike ?? "");
  const [selectedAlternateStrike, setSelectedAlternateStrike] = useState(
    alternateRows.find((row) => row.tag === "Selected")?.strike ?? alternateRows[0]?.strike ?? ""
  );
  const [clockNow, setClockNow] = useState(() => Date.now());
  const [commandOpen, setCommandOpen] = useState(false);
  const [armed, setArmed] = useState(false);
  const visualTheme = "obsidian";
  const [pointer, setPointer] = useState({ x: 50, y: 50 });
  const reduceMotion = useReducedMotion();

  const selectedRow = primaryRows.find((row) => row.strike === selectedStrike) ?? primaryRows[0];
  const selectedAlternateRow = alternateRows.find((row) => row.strike === selectedAlternateStrike) ?? alternateRows[0];
  const ticketMark = selectedRow?.mark ?? primary.current_mark;
  const ticketAtEntry = selectedRow?.at_entry ?? primary.at_entry;
  const ticketFill = selectedRow?.fill ?? primary.expected_fill;
  const ticketRR = selectedRow?.rr ?? primary.rr;
  const activeContract = selectedRow?.strike ?? primary.contract;
  const alternateMark = selectedAlternateRow?.mark ?? alternate.current_mark;
  const alternateAtEntry = selectedAlternateRow?.at_entry ?? alternate.at_entry;
  const alternateFill = selectedAlternateRow?.fill ?? alternate.expected_fill;
  const alternateRR = selectedAlternateRow?.rr ?? alternate.rr;
  const alternateContract = selectedAlternateRow?.strike ?? alternate.contract;
  const plannedEntrySpX = decision.planned_entry_spx ?? decision.planned_entry;
  const plannedEntryEs = decision.planned_entry_es ?? null;
  const mapEntry = plannedEntryEs ?? plannedEntrySpX;
  const distanceToEntry =
    structure.current_es != null && plannedEntryEs != null
      ? structure.current_es - plannedEntryEs
      : null;
  const distanceLabel =
    distanceToEntry == null
      ? "ES trigger distance unavailable"
      : `${Math.abs(distanceToEntry).toFixed(2)} pts ${distanceToEntry >= 0 ? "above" : "below"} ES trigger`;
  const shortDistanceLabel =
    distanceToEntry == null
      ? "Unavailable"
      : `${Math.abs(distanceToEntry).toFixed(1)} pts ${distanceToEntry >= 0 ? "above" : "below"}`;
  const mastheadReason =
    mapEntry != null
      ? `${decision.bias} plan needs ${formatPrice(mapEntry)} ${plannedEntryEs != null ? "ES" : "SPX"} retest confirmation.`
      : decision.reason;
  const scenarioLabel = `${decision.bias} / ${decision.scenario}`;
  const controlModeLabel = "Retest Plan";
  const orderStatus = armed ? "Retest Watch On" : "Retest Watch Off";
  const orderStatusDetail = armed
    ? `${activeContract} tracks confirmation at the planned line.`
    : "No trade authority before polarity confirmation.";
  const authorityTone = toneFor(decision.state);
  const retestAuthorityText = decision.reason;
  const authorityReason = retestAuthorityText || "Structure must confirm at the planned line before execution.";
  const triggerCondition =
    mapEntry == null
      ? "Trigger line unavailable until planned entry loads."
      : `Retest ${formatPrice(mapEntry)} ${plannedEntryEs != null ? "ES" : "SPX"} and confirm the ${structure.anchor_source} polarity line.`;
  const constraintLabels = [
    `Event ${decision.event_risk}`,
    `${decision.risk} Risk`,
    "Retest Required"
  ];
  const constraintSummary = constraintLabels.join(" | ");
  const authoritySubtitle = armed
    ? "Retest watch on. Confirmation still required."
    : decision.state.toUpperCase().includes("WAIT")
      ? "Stand down until the retest confirms."
      : "Execution authority follows confirmed structure.";
  const atmosphereStyle = { "--mx": `${pointer.x}%`, "--my": `${pointer.y}%` } as CSSProperties;
  const snapshotAgeSeconds = useMemo(() => {
    const parsed = Date.parse(snapshot.generated_at);
    if (!Number.isFinite(parsed)) return null;
    return Math.max(0, Math.round((clockNow - parsed) / 1000));
  }, [clockNow, snapshot.generated_at]);
  const snapshotAgeLabel =
    snapshotAgeSeconds == null
      ? "Unavailable"
      : snapshotAgeSeconds < 60
        ? `${snapshotAgeSeconds}s`
        : `${Math.floor(snapshotAgeSeconds / 60)}m ${snapshotAgeSeconds % 60}s`;

  const stageLevels = useMemo(() => structure.levels, [structure.levels]);

  useEffect(() => {
    const interval = window.setInterval(() => {
      setClockNow(Date.now());
    }, 10000);
    return () => window.clearInterval(interval);
  }, []);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if ((event.key === "/" && !event.metaKey && !event.ctrlKey) || ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k")) {
        event.preventDefault();
        setCommandOpen((value) => !value);
      }
      if (event.key === "Escape") {
        setCommandOpen(false);
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);

  return (
    <motion.main
      className={`terminal-shell cinematic-shell theme-${visualTheme}`}
      initial={reduceMotion ? false : "hidden"}
      onMouseMove={(event) => {
        const rect = event.currentTarget.getBoundingClientRect();
        setPointer({
          x: Math.round(((event.clientX - rect.left) / rect.width) * 100),
          y: Math.round(((event.clientY - rect.top) / rect.height) * 100)
        });
      }}
      style={atmosphereStyle}
      variants={shellVariants}
      animate="show"
    >
      <div className="aurora-field" aria-hidden="true" />
      <section className="main">
        <motion.header className="topbar cinematic-topbar masthead" variants={panelVariants}>
          <div className="masthead-sheen" aria-hidden="true" />
          <div className="masthead-brand">
            <div className="prophet-mark" aria-hidden="true">
              <svg viewBox="0 0 112 112" role="img">
                <defs>
                  <linearGradient id="prophetMarkLine" x1="16" x2="96" y1="92" y2="16">
                    <stop stopColor="#7ad7df" />
                    <stop offset="1" stopColor="#d8aa57" />
                  </linearGradient>
                </defs>
                <path className="mark-frame" d="M56 7 96 30v52L56 105 16 82V30L56 7Z" />
                <path className="mark-cone" d="M24 78 56 27l32 51" />
                <path className="mark-line mark-line-a" d="M24 78 88 34" />
                <path className="mark-line mark-line-b" d="M24 34 88 78" />
                <circle className="mark-node node-a" cx="56" cy="27" r="4" />
                <circle className="mark-node node-b" cx="24" cy="78" r="4" />
                <circle className="mark-node node-c" cx="88" cy="78" r="4" />
                <circle className="mark-core" cx="56" cy="56" r="7" />
              </svg>
            </div>
            <div className="brand-lockup">
              <span className="brand-kicker">Execution Intelligence</span>
              <h1 className="wordmark"><span>SPX</span><span>PROPHET</span></h1>
              <p>Structure Into Execution</p>
            </div>
          </div>

          <div className="market-pulse" aria-live="polite">
            <div className="pulse-head">
              <span className="live-dot-label">Live Plan Snapshot</span>
              <span className={`pulse-risk tone-${toneFor(decision.event_risk)}`}>{decision.event_risk} Event Risk</span>
            </div>
            <div className="pulse-decision">
              <span>Trigger Focus</span>
              <strong>{mapEntry == null ? "Entry Pending" : `${formatPrice(mapEntry)} ${plannedEntryEs != null ? "ES" : "SPX"}`}</strong>
              <p>
                <b>{mastheadReason}</b>
                <small>{scenarioLabel}</small>
              </p>
            </div>
            <div className="pulse-values">
              <span>Setup <strong>{`${primary.zone} | ${structure.anchor_source}`}</strong></span>
              <span>Strike <strong>{activeContract}</strong></span>
              <span>Distance <strong>{shortDistanceLabel}</strong></span>
              <span>Likely Fill <strong>{formatPrice(ticketFill)}</strong></span>
              <span>Confidence <strong>{decision.confidence}% | {decision.risk}</strong></span>
              <span>Snapshot Age <strong>{snapshotAgeLabel}</strong></span>
            </div>
          </div>

          <div className={`masthead-actions ${armed ? "is-armed" : ""}`}>
            <div className="action-eyebrow">
              <span>Execution Controls</span>
              <em>{controlModeLabel}</em>
            </div>
            <div className="order-state">
              <span>Alert Preview</span>
              <strong>{orderStatus}</strong>
              <small>{orderStatusDetail}</small>
            </div>
            <button className="masthead-button primary" onClick={() => setCommandOpen(true)} type="button">
              <span>Plan Controls</span>
              <strong>/</strong>
            </button>
            <button
              aria-pressed={armed}
              className="masthead-button arm"
              onClick={() => setArmed((value) => !value)}
              type="button"
            >
              {armed ? "Disable Watch" : "Enable Watch"}
            </button>
          </div>
        </motion.header>

        <motion.section className="cinematic-hero" variants={panelVariants}>
          <div className={`hero-copy authority-card tone-${authorityTone}`}>
            <div className="authority-topline">
              <p className="kicker">Trade Authority</p>
              <span className="decision-index">Retest Gate</span>
            </div>
            <div className="decision-lockup">
              <h2 className="decision-word">{decision.state}</h2>
              <span className="authority-subtitle">{authoritySubtitle}</span>
            </div>
            <p className="decision-reason">{authorityReason}</p>
            <div className="authority-trigger">
              <span>Trigger</span>
              <strong>{triggerCondition}</strong>
            </div>
            <div className="authority-ticket-row" aria-label="Execution ticket facts">
              <div>
                <span>{plannedEntryEs != null ? "Trigger ES" : "Trigger"}</span>
                <strong>{formatPrice(mapEntry)}</strong>
              </div>
              <div>
                <span>Contract</span>
                <strong>{activeContract}</strong>
              </div>
              <div>
                <span>Fill</span>
                <strong>{formatPrice(ticketFill)}</strong>
              </div>
              <div>
                <span>RR</span>
                <strong>{ticketRR == null ? "-" : ticketRR.toFixed(2)}</strong>
              </div>
            </div>
            <div className="authority-condition-grid" aria-label="Trade authority conditions">
              <div>
                <span>Bias</span>
                <strong>{decision.bias}</strong>
              </div>
              <div>
                <span>Location</span>
                <strong>{decision.scenario}</strong>
              </div>
              <div>
                <span>Guardrails</span>
                <strong>{constraintSummary}</strong>
              </div>
            </div>
            <div className="authority-market-card" aria-label="Market context">
              <div className="authority-market-head">
                <span>Market Context</span>
                <strong>{context.risk_mode}</strong>
              </div>
              <div className="authority-market-event">
                <span>Next Event</span>
                <strong>{context.next_event}</strong>
              </div>
              <p>{context.interpretation}</p>
              <div className="authority-headlines">
                {context.headlines.slice(0, 2).map((headline) => (
                  <a href={headline.url ?? "#"} key={headline.title}>
                    <strong>{headline.title}</strong>
                    <span>{headline.source} | {headline.time}</span>
                  </a>
                ))}
              </div>
            </div>
          </div>

          <PlayStack
            alternate={{
              atEntry: alternateAtEntry,
              contract: alternateContract,
              currentMark: alternateMark,
              expectedFill: alternateFill,
              play: alternate,
              rr: alternateRR
            }}
            armed={armed}
            onArm={() => setArmed((value) => !value)}
            onCommands={() => setCommandOpen(true)}
            primary={{
              atEntry: ticketAtEntry,
              contract: activeContract,
              currentMark: ticketMark,
              expectedFill: ticketFill,
              play: primary,
              rr: ticketRR
            }}
          />
        </motion.section>

        <motion.div className="structure-focus-row" variants={panelVariants}>
          <SignalTheater
            activeContract={activeContract}
            currentEs={structure.current_es}
            expectedFill={ticketFill}
            levels={stageLevels}
            plannedEntry={mapEntry}
            vwap={structure.vwap}
          />
        </motion.div>

        <motion.section className="operator-strip" variants={panelVariants} aria-label="Operator summary">
          <Metric label={plannedEntryEs != null ? "Trigger ES" : "Planned Entry"} value={`${formatPrice(mapEntry)} ${plannedEntryEs != null ? "ES" : "SPX"}`} />
          <Metric label="Primary Strike" value={activeContract} tone="warning" />
          <Metric label="Alternate Strike" value={alternateContract} />
          <Metric label="Expected Fill" value={formatPrice(ticketFill)} tone="warning" />
          <Metric label="Current ES" value={formatPrice(structure.current_es)} />
          <Metric label="Anchor Source" value={`${structure.anchor_source} | ${structure.anchor_confidence}`} />
        </motion.section>

        <div className="workspace studio-workspace">
          <div className="left-stack">
            <motion.section className="panel" variants={panelVariants}>
              <div className="panel-header">
                <div>
                  <p className="kicker">Strike Selection</p>
                  <h3>Plan-locked strikes</h3>
                </div>
                <span className="pill">Compact</span>
              </div>
              <div className="strike-summary-grid">
                <StrikeSummaryCard label="Primary Selected" row={selectedRow} fallbackContract={activeContract} />
                <StrikeSummaryCard label="Alternate Selected" row={selectedAlternateRow} fallbackContract={alternateContract} />
              </div>
              <details className="full-ladder-disclosure">
                <summary>
                  <span>Show nearby strike ladders</span>
                  <strong>Primary + Alternate</strong>
                </summary>
                <div className="ladder-split">
                  <div className="ladder-pane">
                    <div className="ladder-pane-head">
                      <span>Primary Ladder</span>
                      <strong>{activeContract}</strong>
                    </div>
                    <StrikeRows rows={primaryRows} selectedStrike={selectedStrike} onSelect={setSelectedStrike} />
                  </div>
                  <div className="ladder-pane">
                    <div className="ladder-pane-head">
                      <span>Alternate Ladder</span>
                      <strong>{alternateContract}</strong>
                    </div>
                    <StrikeRows rows={alternateRows} selectedStrike={selectedAlternateStrike} onSelect={setSelectedAlternateStrike} />
                  </div>
                </div>
              </details>
            </motion.section>

            <motion.section className="panel narrative-panel" variants={panelVariants}>
              <div className="panel-header">
                <div>
                  <p className="kicker">Retest Protocol</p>
                  <h3>What must happen next</h3>
                </div>
                <span className="pill">Polarity Gate</span>
              </div>
              <div className="sequence-grid">
                <SequenceStep index="01" title="Anchor" value={`${structure.anchor_source} polarity line selected`} active />
                <SequenceStep index="02" title="Return" value={`Price must revisit ${formatPrice(mapEntry)}`} active />
                <SequenceStep index="03" title="Confirm" value="Touch and close within 3 pts" active />
                <SequenceStep index="04" title="VWAP" value={structure.vwap?.label ?? "VWAP pending"} active={Boolean(structure.vwap?.value)} />
                <SequenceStep index="05" title="Alert" value={armed ? "Watch armed for retest" : "Arm only when ready"} active={armed} />
              </div>
            </motion.section>
          </div>
        </div>
      </section>

      <AnimatePresence>
        {commandOpen ? (
        <motion.div
          animate="show"
          className="command-backdrop"
          exit="exit"
          initial="hidden"
          onClick={() => setCommandOpen(false)}
          variants={commandBackdropVariants}
        >
          <motion.section className="command-panel" onClick={(event) => event.stopPropagation()} variants={commandPanelVariants}>
            <p className="kicker">Plan Controls</p>
            <h3>Operator actions</h3>
            <button onClick={() => { setSelectedStrike(primaryRows.find((row) => row.tag === "Selected")?.strike ?? primary.contract); setCommandOpen(false); }} type="button">Focus primary play</button>
            <button onClick={() => { setSelectedAlternateStrike(alternateRows.find((row) => row.tag === "Selected")?.strike ?? alternate.contract); setCommandOpen(false); }} type="button">Focus alternate play</button>
            <button onClick={() => { setArmed(true); setCommandOpen(false); }} type="button">Enable retest watch</button>
            <button onClick={() => { setCommandOpen(false); }} type="button">Review risk and context</button>
            <span>Press Esc to close | Ctrl+K / Cmd+K opens this panel</span>
          </motion.section>
        </motion.div>
        ) : null}
      </AnimatePresence>
    </motion.main>
  );
}

type PlayTicketData = {
  atEntry: number | null;
  contract: string;
  currentMark: number | null;
  expectedFill: number | null;
  play: OperatorSnapshot["primary_play"];
  rr: number | null;
};

function operatorStatusLabel(status: string) {
  const normalized = status.trim().toLowerCase();
  if (normalized === "armed") return "Candidate";
  if (normalized === "watch") return "Watching";
  if (normalized === "invalidated") return "Blocked";
  return status;
}

function triggerSummary(trigger?: string) {
  const normalized = (trigger ?? "").toLowerCase();
  if (normalized.includes("upper")) return "Reject upper line within 3 pts";
  if (normalized.includes("lower")) return "Hold lower line within 3 pts";
  if (trigger) return trigger;
  return "Confirm polarity line";
}

function PlayStack({
  alternate,
  armed,
  onArm,
  onCommands,
  primary
}: {
  alternate: PlayTicketData;
  armed: boolean;
  onArm: () => void;
  onCommands: () => void;
  primary: PlayTicketData;
}) {
  return (
    <motion.section className={`panel execution-ticket hero-ticket play-stack ${armed ? "armed-ticket" : ""}`} variants={panelVariants}>
      <div className="play-stack-head">
        <div>
          <p className="kicker">Execution Tickets</p>
          <h3>Primary + Alternate</h3>
        </div>
        <span className={`pill ${armed ? "tone-warning" : ""}`}>{armed ? "Alert Armed" : "Guarded"}</span>
      </div>
      <div className="play-ticket-list">
        <PlayTicketCard data={primary} label="Primary Play" active armed={armed} />
        <PlayTicketCard data={alternate} label="Alternate Play" armed={false} compact />
      </div>
      <div className="button-row">
        <button className="button primary" onClick={onArm} type="button">
          {armed ? "Disable Retest Watch" : "Enable Retest Watch"}
        </button>
        <button className="button" onClick={onCommands} type="button">Plan Controls</button>
      </div>
    </motion.section>
  );
}

function PlayTicketCard({
  active = false,
  armed,
  compact = false,
  data,
  label
}: {
  active?: boolean;
  armed: boolean;
  compact?: boolean;
  data: PlayTicketData;
  label: string;
}) {
  const isPut = data.contract.toUpperCase().endsWith("P");
  const isCall = data.contract.toUpperCase().endsWith("C");
  const contractSide = isPut ? "Put" : isCall ? "Call" : data.play.direction;
  const ticketState = armed ? "Alert Watching" : operatorStatusLabel(data.play.status);
  const gateLabel = isPut ? "upper rejection line" : isCall ? "lower hold line" : "planned trigger";
  const fillCost = data.expectedFill == null ? "Unavailable" : `$${Math.round(data.expectedFill * 100)} est.`;
  const planSize = data.play.contracts == null ? "Plan size pending" : `${data.play.contracts} contract${data.play.contracts === 1 ? "" : "s"}`;
  const confirmationText = triggerSummary(data.play.trigger);

  return (
    <article className={`play-ticket-card ${active ? "active" : ""} ${compact ? "compact" : ""}`}>
      <div className="play-ticket-top">
        <div>
          <span className="play-label">{label}</span>
          <div className="ticket-contract-line">
            <h2>{data.contract}</h2>
            <span>{contractSide}</span>
          </div>
        </div>
        <div className="ticket-state">
          <span>Status</span>
          <strong>{ticketState}</strong>
          <small>{data.play.quality} estimate</small>
        </div>
      </div>
      <div className="kv-grid ticket-premium-grid">
        <KV label="Current" value={formatPrice(data.currentMark)} />
        <KV label="At Trigger" value={formatPrice(data.atEntry)} />
        <KV label="Expected Fill" value={formatPrice(data.expectedFill)} />
      </div>
      {compact ? (
        <div className="compact-ticket-strip">
          <span><em>Confirm</em><strong>{confirmationText}</strong></span>
          <span><em>Plan Size</em><strong>{planSize}</strong></span>
          <span><em>RR</em><strong>{data.rr == null ? "-" : data.rr.toFixed(2)}</strong></span>
        </div>
      ) : (
        <>
          <div className="play-level-strip" aria-label={`${label} execution levels`}>
            <span><em>Entry</em><strong>{formatPrice(data.play.planned_entry)}</strong></span>
            <span><em>Stop</em><strong>{formatPrice(data.play.stop)}</strong></span>
            <span><em>T1</em><strong>{formatPrice(data.play.target_1)}</strong></span>
            <span><em>T2</em><strong>{formatPrice(data.play.target_2)}</strong></span>
          </div>
          <p className="ticket-copy">
            {data.play.reason} If ES reaches the {gateLabel}, estimated premium is {formatPrice(data.atEntry)} and likely fill is {formatPrice(data.expectedFill)}.
          </p>
          <div className="ticket-risk-grid">
            <Risk label="Cost If Filled" value={fillCost} tone="warning" />
            <Risk label="RR" value={data.rr == null ? "-" : data.rr.toFixed(2)} />
            <Risk label="Plan Size" value={planSize} />
            <Risk label="Confirmation" value={confirmationText} />
          </div>
        </>
      )}
    </article>
  );
}

function SignalTheater({
  activeContract,
  currentEs,
  expectedFill,
  levels,
  plannedEntry,
  vwap
}: {
  activeContract: string;
  currentEs: number | null;
  expectedFill: number | null;
  levels: Array<{ label: string; value: number | null; tone: string }>;
  plannedEntry: number | null;
  vwap?: OperatorSnapshot["structure"]["vwap"];
}) {
  const chartTop = 70;
  const chartHeight = 640;
  const chartLeft = 34;
  const chartRight = 842;
  const currentNodeX = chartLeft + 42;
  const futureNodeX = chartRight - 42;
  const pricedLevels = levels.filter((level) => level.value != null) as Array<{ label: string; value: number; tone: string }>;
  const aboveLine = currentEs == null
    ? null
    : pricedLevels
        .filter((level) => level.value > currentEs)
        .sort((a, b) => a.value - b.value)[0] ?? null;
  const belowLine = currentEs == null
    ? null
    : pricedLevels
        .filter((level) => level.value < currentEs)
        .sort((a, b) => b.value - a.value)[0] ?? null;
  const priceValues = [currentEs, plannedEntry, aboveLine?.value, belowLine?.value].filter((value): value is number => value != null);
  const rawMin = priceValues.length > 0 ? Math.min(...priceValues) : 0;
  const rawMax = priceValues.length > 0 ? Math.max(...priceValues) : 1;
  const pad = Math.max((rawMax - rawMin) * 0.12, 4);
  const minPrice = rawMin - pad;
  const maxPrice = rawMax + pad;
  const yFor = (price: number | null) => {
    if (price == null || maxPrice === minPrice) {
      return chartTop + chartHeight / 2;
    }
    return chartTop + ((maxPrice - price) / (maxPrice - minPrice)) * chartHeight;
  };
  const currentY = yFor(currentEs);
  const entryY = yFor(plannedEntry);
  const distanceToRetest = currentEs != null && plannedEntry != null ? currentEs - plannedEntry : null;
  const isPutSetup = activeContract.toUpperCase().endsWith("P");
  const isCallSetup = activeContract.toUpperCase().endsWith("C");
  const routeTo = (targetPrice: number) => {
    const targetY = yFor(targetPrice);
    const midpointY = (currentY + targetY) / 2;
    return `M ${currentNodeX} ${currentY} C ${chartLeft + 128} ${midpointY - 28}, ${chartRight - 128} ${midpointY + 28}, ${futureNodeX} ${targetY}`;
  };
  const gateLevels = [aboveLine, belowLine].filter((level): level is { label: string; value: number; tone: string } => level != null);
  const distanceLabel = distanceToRetest == null
    ? "Distance unavailable"
    : `${Math.abs(distanceToRetest).toFixed(2)} pts ${distanceToRetest >= 0 ? "above" : "below"} retest`;
  const entryMatchesGate =
    plannedEntry != null &&
    ((aboveLine != null && Math.abs(plannedEntry - aboveLine.value) < 0.01) ||
      (belowLine != null && Math.abs(plannedEntry - belowLine.value) < 0.01));
  const contractSide = isPutSetup
    ? "Selected Put"
    : isCallSetup
      ? "Selected Call"
      : "Selected Contract";
  const entrySideLabel = isPutSetup
    ? "Put Rejection Zone"
    : isCallSetup
      ? "Call Hold Zone"
      : "Retest Entry Zone";
  const universalNoEntryLabel = "Upper line gates puts. Lower line gates calls.";
  const vwapLabel = vwap?.label || "VWAP unavailable";
  const vwapDetail = vwap?.detail || "5m ES VWAP will appear here when available.";
  const mapStatus = currentEs != null && plannedEntry != null
    ? isPutSetup
      ? currentEs < plannedEntry
        ? "Current ES is below put rejection zone"
        : currentEs > plannedEntry
          ? "Current ES is above put rejection zone"
          : "Current ES is at put rejection zone"
      : isCallSetup
        ? currentEs > plannedEntry
          ? "Current ES is above call hold zone"
          : currentEs < plannedEntry
            ? "Current ES is below call hold zone"
            : "Current ES is at call hold zone"
        : currentEs > plannedEntry
          ? "Current ES is above retest zone"
          : currentEs < plannedEntry
            ? "Current ES is below retest zone"
            : "Current ES is at retest entry"
    : "Structure data unavailable";

  return (
    <section className="signal-theater execution-map" aria-label="Animated execution structure map">
      <div className="map-titlebar">
        <div>
          <span>Structure Map</span>
          <strong>{mapStatus}</strong>
        </div>
        <em>{universalNoEntryLabel}</em>
      </div>
      <div className="polarity-rule-strip" aria-label="Polarity confirmation rules">
        <span>Neutral until confirmed</span>
        <span>Put rejection above</span>
        <span>Call hold below</span>
        <span>Close within 3 pts</span>
      </div>
      <div className="map-body">
      <svg className="execution-map-svg" viewBox="0 0 880 780" role="img" aria-label="Current ES, planned entry, and structure levels">
        <defs>
          <linearGradient id="entryGlow" x1="0" x2="1" y1="0" y2="0">
            <stop stopColor="#d8aa57" stopOpacity="0" />
            <stop offset="0.5" stopColor="#d8aa57" stopOpacity="0.34" />
            <stop offset="1" stopColor="#d8aa57" stopOpacity="0" />
          </linearGradient>
          <radialGradient id="currentGlow">
            <stop stopColor="#71c7df" stopOpacity="0.72" />
            <stop offset="1" stopColor="#71c7df" stopOpacity="0" />
          </radialGradient>
          <marker id="routeArrow" markerHeight="8" markerWidth="8" orient="auto" refX="5" refY="3">
            <path d="M0,0 L0,6 L6,3 z" fill="#d8aa57" opacity="0.84" />
          </marker>
        </defs>
        {[0, 1, 2, 3, 4].map((tick) => {
          const y = chartTop + (chartHeight / 4) * tick;
          const price = maxPrice - ((maxPrice - minPrice) / 4) * tick;
          return (
            <g key={tick}>
              <line className="map-grid-line" x1={chartLeft} x2={chartRight} y1={y} y2={y} />
              <text className="map-axis-label" x={chartRight + 12} y={y + 4}>{formatPrice(price)}</text>
            </g>
          );
        })}
        {!entryMatchesGate ? (
          <>
            <rect className="entry-zone-fill" x={chartLeft} y={entryY - 13} width={chartRight - chartLeft} height="26" rx="13" />
            <line className="entry-zone-line" x1={chartLeft} x2={chartRight} y1={entryY} y2={entryY} />
          </>
        ) : null}
        {gateLevels.map((level) => {
          const y = yFor(level.value);
          const isUpperGate = aboveLine != null && level.value === aboveLine.value;
          const gateLabel = isUpperGate ? "Put rejection line" : "Call hold line";
          return (
            <g key={`${gateLabel}-${level.value}`}>
              <rect className={`gate-zone-fill ${isUpperGate ? "put-gate-zone" : "call-gate-zone"}`} x={chartLeft} y={y - 13} width={chartRight - chartLeft} height="26" rx="13" />
              <line className={`polarity-gate-line ${isUpperGate ? "put-gate-line" : "call-gate-line"}`} x1={chartLeft} x2={chartRight} y1={y} y2={y} />
              <circle className={`level-dot ${isUpperGate ? "put-gate-dot" : "call-gate-dot"}`} cx={chartLeft} cy={y} r="4" />
            </g>
          );
        })}
        {distanceToRetest != null && Math.abs(currentY - entryY) > 8 ? (
          <g className="distance-ruler">
            <line x1={chartRight - 84} x2={chartRight - 84} y1={Math.min(currentY, entryY)} y2={Math.max(currentY, entryY)} />
            <line x1={chartRight - 92} x2={chartRight - 76} y1={currentY} y2={currentY} />
            <line x1={chartRight - 92} x2={chartRight - 76} y1={entryY} y2={entryY} />
          </g>
        ) : null}
        {aboveLine ? <path className="gate-route put-route" d={routeTo(aboveLine.value)} markerEnd="url(#routeArrow)" /> : null}
        {belowLine ? <path className="gate-route call-route" d={routeTo(belowLine.value)} markerEnd="url(#routeArrow)" /> : null}
        <line className="current-price-line" x1={chartLeft} x2={chartRight} y1={currentY} y2={currentY} />
        <circle className="current-price-glow" cx={currentNodeX} cy={currentY} r="42" fill="url(#currentGlow)" />
        <circle className="current-price-ring" cx={currentNodeX} cy={currentY} r="13" />
        <circle className="current-price-node" cx={currentNodeX} cy={currentY} r="6" />
      </svg>
        <aside className="map-side-panel" aria-label="Structure map readout">
          <div className="map-side-card">
            <span>Execution Rule</span>
            <strong>No entry on touch alone</strong>
            <small>Price must touch the polarity line and close within 3 points. Extended reactions wait for retest.</small>
          </div>
          <div className="map-callout-grid">
            <div className="map-callout current">
              <span>Current ES</span>
              <strong>{formatPrice(currentEs)}</strong>
              <small>{distanceLabel}</small>
            </div>
            {aboveLine ? (
              <div className="map-callout put">
                <span>Put Gate</span>
                <strong>{formatPrice(aboveLine.value)}</strong>
                <small>{isPutSetup ? `${activeContract} selected` : "Close below required"}</small>
              </div>
            ) : null}
            {belowLine ? (
              <div className="map-callout call">
                <span>Call Gate</span>
                <strong>{formatPrice(belowLine.value)}</strong>
                <small>{isCallSetup ? `${activeContract} selected` : "Close above required"}</small>
              </div>
            ) : null}
            <div className="map-callout selected">
              <span>{contractSide}</span>
              <strong>{activeContract}</strong>
              <small>{entrySideLabel} {formatPrice(plannedEntry)} | fill {formatPrice(expectedFill)}</small>
            </div>
            <div className="map-callout vwap">
              <span>5m VWAP</span>
              <strong>{vwap?.value == null ? vwapLabel : formatPrice(vwap.value)}</strong>
              <small>{vwapDetail}</small>
            </div>
          </div>
        </aside>
        </div>
    </section>
  );
}

function SequenceStep({ active, index, title, value }: { active?: boolean; index: string; title: string; value: string }) {
  return (
    <div className={`sequence-step ${active ? "active" : ""}`}>
      <span>{index}</span>
      <strong>{title}</strong>
      <p>{value}</p>
    </div>
  );
}

function Metric({ label, value, tone = "neutral" }: { label: string; value: string; tone?: string }) {
  return (
    <div className="metric interactive-card">
      <span>{label}</span>
      <strong className={`text-${tone}`}>{value}</strong>
    </div>
  );
}

function KV({ label, value }: { label: string; value: string }) {
  return (
    <div className="kv interactive-card">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function Risk({ label, value, tone = "neutral" }: { label: string; value: string; tone?: string }) {
  return (
    <div className="risk-row">
      <span>{label}</span>
      <strong className={`text-${tone}`}>{value}</strong>
    </div>
  );
}

function StrikeSummaryCard({
  fallbackContract,
  label,
  row
}: {
  fallbackContract: string;
  label: string;
  row?: StrikeRow;
}) {
  return (
    <article className="strike-summary-card">
      <div className="strike-summary-top">
        <span>{label}</span>
        <strong>{row?.strike ?? fallbackContract}</strong>
      </div>
      <div className="strike-summary-values">
        <span><em>Now</em><strong>{formatPrice(row?.mark ?? null)}</strong></span>
        <span><em>At Trigger</em><strong>{formatPrice(row?.at_entry ?? null)}</strong></span>
        <span><em>Fill</em><strong>{formatPrice(row?.fill ?? null)}</strong></span>
        <span><em>RR</em><strong>{row?.rr == null ? "-" : row.rr.toFixed(2)}</strong></span>
      </div>
      <div className="strike-summary-footer">
        <span>Plan locked</span>
        <strong>{row?.tag === "Selected" ? "Selected" : row?.tag ?? "Selected"}</strong>
      </div>
    </article>
  );
}

function StrikeRows({
  rows,
  selectedStrike,
  onSelect
}: {
  rows: StrikeRow[];
  selectedStrike: string;
  onSelect: (strike: string) => void;
}) {
  return (
    <div className="ladder-table">
      <div className="ladder-row table-head">
        <span>Strike</span>
        <span>Mark</span>
        <span>At Entry</span>
        <span>Fill</span>
        <span>RR</span>
        <span>Budget</span>
        <span>Tag</span>
      </div>
      {rows.map((row) => (
        <button
          className={`ladder-row ${row.strike === selectedStrike ? "selected" : ""}`}
          key={row.strike}
          onClick={() => onSelect(row.strike)}
          type="button"
        >
          <strong>{row.strike}</strong>
          <span>{formatPrice(row.mark)}</span>
          <span>{formatPrice(row.at_entry)}</span>
          <span>{formatPrice(row.fill)}</span>
          <span>{row.rr == null ? "-" : row.rr.toFixed(2)}</span>
          <span className={`text-${toneFor(row.budget)}`}>{row.budget}</span>
          <span>{row.strike === selectedStrike ? "Selected" : row.tag}</span>
        </button>
      ))}
    </div>
  );
}
