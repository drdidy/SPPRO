"use client";

import type { CSSProperties } from "react";
import { useEffect, useMemo, useState } from "react";
import { AnimatePresence, motion, useReducedMotion } from "framer-motion";
import type { OperatorSnapshot, StrikeRow } from "@/lib/types";
import { formatPrice, toneFor } from "@/lib/format";
import { commandBackdropVariants, commandPanelVariants, panelVariants, shellVariants } from "@/lib/motion";

type ProjectionMode = "current" | "retest";

export function OperatorWorkspace({ snapshot }: { snapshot: OperatorSnapshot }) {
  const primary = snapshot.primary_play;
  const alternate = snapshot.alternate_play;
  const decision = snapshot.decision;
  const context = snapshot.market_context;
  const structure = snapshot.structure;
  const primaryRows = snapshot.strike_ladders.primary;
  const alternateRows = snapshot.strike_ladders.alternate;
  const [activeRail, setActiveRail] = useState("OP");
  const [selectedStrike, setSelectedStrike] = useState(primaryRows.find((row) => row.tag === "Selected")?.strike ?? primaryRows[0]?.strike ?? "");
  const [selectedAlternateStrike, setSelectedAlternateStrike] = useState(
    alternateRows.find((row) => row.tag === "Selected")?.strike ?? alternateRows[0]?.strike ?? ""
  );
  const [projectionMode, setProjectionMode] = useState<ProjectionMode>("retest");
  const [quoteAge, setQuoteAge] = useState(4);
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
  const distanceToEntry =
    structure.current_es != null && decision.planned_entry != null
      ? structure.current_es - decision.planned_entry
      : null;
  const distanceLabel =
    distanceToEntry == null
      ? "Entry distance unavailable"
      : `${Math.abs(distanceToEntry).toFixed(2)} pts ${distanceToEntry >= 0 ? "above" : "below"} entry`;
  const triggerLabel =
    decision.state.toUpperCase().includes("WAIT") && decision.planned_entry != null
      ? `Wait for ${formatPrice(decision.planned_entry)} retest`
      : decision.reason;
  const scenarioLabel = `${decision.bias} / ${decision.scenario}`;
  const executionLine = `${primary.status} | ${primary.zone} | ${structure.anchor_source} anchor`;
  const controlModeLabel = projectionMode === "retest" ? "Retest Mode" : "Current Mode";
  const orderStatus = armed ? "Retest Armed" : "Order Not Sent";
  const orderStatusDetail = armed
    ? `${activeContract} waits for confirmation at the planned line.`
    : `${decision.state} | ${triggerLabel}`;
  const authorityTone = toneFor(decision.state);
  const currentAuthorityText = "No fill authority at current price. Await structure return.";
  const retestAuthorityText = decision.reason;
  const authorityReason = projectionMode === "retest" ? retestAuthorityText : currentAuthorityText;
  const triggerCondition =
    decision.planned_entry == null
      ? "Trigger line unavailable until planned entry loads."
      : `Retest ${formatPrice(decision.planned_entry)} and confirm the Asian polarity line.`;
  const constraintLabels = [
    `Event ${decision.event_risk}`,
    decision.budget,
    `${decision.risk} Risk`
  ];
  const constraintSummary = constraintLabels.join(" | ");
  const authoritySubtitle = armed
    ? "Retest armed. Still wait for confirmation."
    : decision.state.toUpperCase().includes("WAIT")
      ? "Stand down until the retest confirms."
      : "Execution authority follows confirmed structure.";
  const atmosphereStyle = { "--mx": `${pointer.x}%`, "--my": `${pointer.y}%` } as CSSProperties;

  const stageLevels = useMemo(() => structure.levels, [structure.levels]);

  useEffect(() => {
    const interval = window.setInterval(() => {
      setQuoteAge((value) => (value >= 9 ? 3 : value + 1));
    }, 1400);
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
      <motion.aside className="rail" aria-label="Operator navigation" variants={panelVariants}>
        <div className="rail-logo">SP</div>
        {["OP", "ST", "RK", "LG"].map((item) => (
          <button
            aria-pressed={activeRail === item}
            className={`rail-item ${activeRail === item ? "active" : ""}`}
            key={item}
            onClick={() => setActiveRail(item)}
            type="button"
          >
            {item}
          </button>
        ))}
      </motion.aside>

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
              <span className="live-dot-label">Execution Tape</span>
              <span className={`pulse-risk tone-${toneFor(decision.event_risk)}`}>{decision.event_risk} Event Risk</span>
            </div>
            <div className="pulse-decision">
              <span>Trade State</span>
              <strong>{decision.state}</strong>
              <p>
                <b>{triggerLabel}</b>
                <small>{scenarioLabel}</small>
              </p>
            </div>
            <div className="pulse-values">
              <span>Setup <strong>{executionLine}</strong></span>
              <span>Strike <strong>{activeContract}</strong></span>
              <span>Entry <strong>{formatPrice(decision.planned_entry)}</strong></span>
              <span>ES Distance <strong>{distanceLabel}</strong></span>
              <span>Fill / Budget <strong>{formatPrice(ticketFill)} | {decision.budget}</strong></span>
              <span>Confidence <strong>{decision.confidence}% | {decision.risk} Risk</strong></span>
              <span>Context <strong>{context.risk_mode}</strong></span>
              <span>Quote Age <strong>{quoteAge.toString().padStart(2, "0")}s</strong></span>
            </div>
          </div>

          <div className={`masthead-actions ${armed ? "is-armed" : ""}`}>
            <div className="action-eyebrow">
              <span>Execution Controls</span>
              <em>{controlModeLabel}</em>
            </div>
            <div className="order-state">
              <span>{armed ? "Armed State" : "Safe State"}</span>
              <strong>{orderStatus}</strong>
              <small>{orderStatusDetail}</small>
            </div>
            <button className="masthead-button primary" onClick={() => setCommandOpen(true)} type="button">
              <span>Command Center</span>
              <strong>/</strong>
            </button>
            <button
              aria-pressed={armed}
              className="masthead-button arm"
              onClick={() => setArmed((value) => !value)}
              type="button"
            >
              {armed ? "Disarm Retest" : "Arm Retest"}
            </button>
          </div>
        </motion.header>

        <motion.section className="cinematic-hero" variants={panelVariants}>
          <div className={`hero-copy authority-card tone-${authorityTone}`}>
            <div className="authority-topline">
              <p className="kicker">Order Authority</p>
              <span className="decision-index">Gate 01</span>
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
                <span>Entry</span>
                <strong>{formatPrice(decision.planned_entry)}</strong>
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
            <div className="authority-condition-grid" aria-label="Order authority conditions">
              <div>
                <span>Bias</span>
                <strong>{decision.bias}</strong>
              </div>
              <div>
                <span>Location</span>
                <strong>{decision.scenario}</strong>
              </div>
              <div>
                <span>Constraints</span>
                <strong>{constraintSummary}</strong>
              </div>
            </div>
            <div className="mode-switch authority-mode-switch" aria-label="Projection mode">
              <button className={projectionMode === "current" ? "active" : ""} onClick={() => setProjectionMode("current")} type="button">Current Price</button>
              <button className={projectionMode === "retest" ? "active" : ""} onClick={() => setProjectionMode("retest")} type="button">If Retest</button>
            </div>
            <div className="state-row authority-state-row">
              <span className={`pill tone-${toneFor(decision.bias)}`}>{decision.bias}</span>
              <span className={`pill tone-${toneFor(decision.event_risk)}`}>Event {decision.event_risk}</span>
              <span className={`pill tone-${toneFor(decision.budget)}`}>{decision.budget}</span>
            </div>
          </div>

          <SignalTheater
            activeContract={activeContract}
            currentEs={structure.current_es}
            expectedFill={ticketFill}
            levels={stageLevels}
            plannedEntry={decision.planned_entry}
          />

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

        <motion.section className="operator-strip" variants={panelVariants} aria-label="Operator summary">
          <Metric label="Planned Entry" value={`${formatPrice(decision.planned_entry)} SPX`} />
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
                  <p className="kicker">Execution Sequence</p>
                  <h3>Execution checklist</h3>
                </div>
                <span className="pill">Operator Flow</span>
              </div>
              <div className="sequence-grid">
                <SequenceStep index="01" title="Anchor" value={`${structure.anchor_source} polarity`} active />
                <SequenceStep index="02" title="Retest" value="Wait for clean line return" active={projectionMode === "retest"} />
                <SequenceStep index="03" title="Primary" value={`${activeContract} | ${primary.status}`} active />
                <SequenceStep index="04" title="Alternate" value={`${alternateContract} | ${alternate.status}`} active={alternate.status !== "Blocked"} />
                <SequenceStep index="05" title="Alert" value={armed ? "Retest alert armed" : "No alert armed"} active={armed} />
              </div>
            </motion.section>
          </div>

          <aside className="right-stack">
            <motion.section className="panel market-card" variants={panelVariants}>
              <div className="panel-header">
                <div>
                  <p className="kicker">Market Context</p>
                  <h3>Event risk</h3>
                </div>
                <span className={`pill tone-${toneFor(context.event_risk)}`}>{context.risk_mode}</span>
              </div>
              <div className="next-event-row">
                <span>Next Event</span>
                <strong>{context.next_event}</strong>
              </div>
              <p className="panel-copy muted">{context.interpretation}</p>
              <div className="headlines">
                {context.headlines.slice(0, 3).map((headline) => (
                  <a className="headline" href={headline.url ?? "#"} key={headline.title}>
                    <strong>{headline.title}</strong>
                    <span>{headline.source} | {headline.time}</span>
                  </a>
                ))}
              </div>
            </motion.section>
          </aside>
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
            <p className="kicker">Command Center</p>
            <h3>Operator actions</h3>
            <button onClick={() => { setProjectionMode("retest"); setCommandOpen(false); }} type="button">Focus retest plan</button>
            <button onClick={() => { setSelectedStrike(primaryRows.find((row) => row.tag === "Selected")?.strike ?? primary.contract); setActiveRail("OP"); setCommandOpen(false); }} type="button">Focus primary play</button>
            <button onClick={() => { setSelectedAlternateStrike(alternateRows.find((row) => row.tag === "Selected")?.strike ?? alternate.contract); setActiveRail("OP"); setCommandOpen(false); }} type="button">Focus alternate play</button>
            <button onClick={() => { setArmed(true); setCommandOpen(false); }} type="button">Arm retest alert</button>
            <button onClick={() => { setActiveRail("RK"); setCommandOpen(false); }} type="button">Review risk and context</button>
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
        <span className={`pill ${armed ? "tone-warning" : ""}`}>{armed ? "Retest Alert Armed" : "No Order Submitted"}</span>
      </div>
      <div className="play-ticket-list">
        <PlayTicketCard data={primary} label="Primary Play" active armed={armed} />
        <PlayTicketCard data={alternate} label="Alternate Play" armed={false} />
      </div>
      <div className="button-row">
        <button className="button primary" onClick={onArm} type="button">
          {armed ? "Disarm Retest Alert" : "Arm Retest Alert"}
        </button>
        <button className="button" onClick={onCommands} type="button">Open Commands</button>
      </div>
    </motion.section>
  );
}

function PlayTicketCard({
  active = false,
  armed,
  data,
  label
}: {
  active?: boolean;
  armed: boolean;
  data: PlayTicketData;
  label: string;
}) {
  const isPut = data.contract.toUpperCase().endsWith("P");
  const isCall = data.contract.toUpperCase().endsWith("C");
  const contractSide = isPut ? "Put" : isCall ? "Call" : data.play.direction;
  const ticketState = armed ? "Retest Alert Armed" : data.play.status;
  const gateLabel = isPut ? "upper rejection line" : isCall ? "lower hold line" : "planned trigger";
  const fillCost = data.expectedFill == null ? "Unavailable" : `$${Math.round(data.expectedFill * 100)} est.`;

  return (
    <article className={`play-ticket-card ${active ? "active" : ""}`}>
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
        <Risk label="Budget" value={data.play.budget} tone={toneFor(data.play.budget)} />
        <Risk label="Trigger" value={data.play.trigger ?? data.play.zone} />
      </div>
    </article>
  );
}

function SignalTheater({
  activeContract,
  currentEs,
  expectedFill,
  levels,
  plannedEntry
}: {
  activeContract: string;
  currentEs: number | null;
  expectedFill: number | null;
  levels: Array<{ label: string; value: number | null; tone: string }>;
  plannedEntry: number | null;
}) {
  const chartTop = 46;
  const chartHeight = 308;
  const chartLeft = 72;
  const chartRight = 444;
  const currentNodeX = chartLeft + 42;
  const futureNodeX = chartRight - 42;
  const pricedLevels = levels.filter((level) => level.value != null) as Array<{ label: string; value: number; tone: string }>;
  const priceValues = [currentEs, plannedEntry, ...pricedLevels.map((level) => level.value)].filter((value): value is number => value != null);
  const rawMin = priceValues.length > 0 ? Math.min(...priceValues) : 0;
  const rawMax = priceValues.length > 0 ? Math.max(...priceValues) : 1;
  const pad = Math.max((rawMax - rawMin) * 0.04, 3);
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
  const routeTo = (targetPrice: number) => {
    const targetY = yFor(targetPrice);
    const midpointY = (currentY + targetY) / 2;
    return `M ${currentNodeX} ${currentY} C ${chartLeft + 128} ${midpointY - 28}, ${chartRight - 128} ${midpointY + 28}, ${futureNodeX} ${targetY}`;
  };
  const gateLevels = [aboveLine, belowLine].filter((level): level is { label: string; value: number; tone: string } => level != null);
  const distanceLabel = distanceToRetest == null
    ? "Distance unavailable"
    : `${Math.abs(distanceToRetest).toFixed(2)} pts ${distanceToRetest >= 0 ? "above" : "below"} retest`;
  const distanceTop = Math.max(15, Math.min(78, (((currentY + entryY) / 2) / 420) * 100));
  const entryTop = Math.max(16, Math.min(80, (entryY / 420) * 100));
  const putGateTop = aboveLine ? Math.max(16, Math.min(80, (yFor(aboveLine.value) / 420) * 100)) : null;
  const callGateTop = belowLine ? Math.max(16, Math.min(80, (yFor(belowLine.value) / 420) * 100)) : null;
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
  const confirmationLabel = isPutSetup
    ? "Touch line, close below within 3 pts"
    : isCallSetup
      ? "Touch line, close above within 3 pts"
      : "Touch line, close near it";
  const universalNoEntryLabel = "No puts until upper rejection. No calls until lower hold.";
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
    : "Waiting for structure data";

  return (
    <section className="signal-theater execution-map" aria-label="Animated execution structure map">
      <div className="stage-orbit orbit-one" />
      <div className="stage-orbit orbit-two" />
      <div className="map-titlebar">
        <div>
          <span>Structure Map</span>
          <strong>{mapStatus}</strong>
        </div>
        <em>{universalNoEntryLabel}</em>
      </div>
      <div className="polarity-rule-strip" aria-label="Polarity confirmation rules">
        <span>All lines start neutral</span>
        <span>Put gate: upper rejection</span>
        <span>Call gate: lower hold</span>
        <span>Extended reaction = wait</span>
      </div>
      <svg className="execution-map-svg" viewBox="0 0 520 420" role="img" aria-label="Current ES, planned entry, and structure levels">
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
        <rect className="entry-zone-fill" x={chartLeft} y={entryY - 13} width={chartRight - chartLeft} height="26" rx="13" />
        <line className="entry-zone-line" x1={chartLeft} x2={chartRight} y1={entryY} y2={entryY} />
        <text className="map-entry-label" x={chartLeft + 12} y={entryY - 18}>{entrySideLabel} {formatPrice(plannedEntry)}</text>
        {gateLevels.map((level) => {
          const y = yFor(level.value);
          const isUpperGate = aboveLine != null && level.value === aboveLine.value;
          const gateLabel = isUpperGate ? "Put rejection line" : "Call hold line";
          return (
            <g key={`${gateLabel}-${level.value}`}>
              <rect className={`gate-zone-fill ${isUpperGate ? "put-gate-zone" : "call-gate-zone"}`} x={chartLeft} y={y - 13} width={chartRight - chartLeft} height="26" rx="13" />
              <line className={`polarity-gate-line ${isUpperGate ? "put-gate-line" : "call-gate-line"}`} x1={chartLeft} x2={chartRight} y1={y} y2={y} />
              <circle className={`level-dot ${isUpperGate ? "put-gate-dot" : "call-gate-dot"}`} cx={chartLeft} cy={y} r="4" />
              <text className="structure-level-label" x={chartLeft + 12} y={y - 7}>{gateLabel} {formatPrice(level.value)}</text>
            </g>
          );
        })}
        {aboveLine ? (
          <text className="polarity-gate-label put-gate-label" x={chartRight - 156} y={yFor(aboveLine.value) - 10}>Put rejection candidate</text>
        ) : null}
        {belowLine ? (
          <text className="polarity-gate-label call-gate-label" x={chartRight - 138} y={yFor(belowLine.value) + 18}>Call hold candidate</text>
        ) : null}
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
        <text className="current-price-label" x={currentNodeX + 12} y={currentY - 12}>Current ES {formatPrice(currentEs)}</text>
      </svg>
      <div className="distance-badge" style={{ top: `${distanceTop}%` }}>
        <span>Distance to wait</span>
        <strong>{distanceLabel}</strong>
      </div>
      {putGateTop != null && aboveLine ? (
        <div className="gate-ticket-badge put-ticket-badge" style={{ top: `${putGateTop}%` }}>
          <span>Put Rejection Zone</span>
          <strong>{formatPrice(aboveLine.value)}</strong>
          {isPutSetup ? <small>{activeContract} selected</small> : <small>wait for close below</small>}
        </div>
      ) : null}
      {callGateTop != null && belowLine ? (
        <div className="gate-ticket-badge call-ticket-badge" style={{ top: `${callGateTop}%` }}>
          <span>Call Hold Zone</span>
          <strong>{formatPrice(belowLine.value)}</strong>
          {isCallSetup ? <small>{activeContract} selected</small> : <small>wait for close above</small>}
        </div>
      ) : null}
      <div className="entry-ticket-badge selected-ticket-badge" style={{ top: `${entryTop}%` }}>
        <span>{contractSide}</span>
        <strong>{activeContract}</strong>
        <small>Est. fill {formatPrice(expectedFill)}</small>
      </div>
      <div className="stage-readout top-left">
        <span>Current ES Price</span>
        <strong>{formatPrice(currentEs)}</strong>
        <small>{mapStatus}</small>
      </div>
      <div className="stage-readout bottom-left">
        <span>{entrySideLabel}</span>
        <strong>{formatPrice(plannedEntry)}</strong>
        <small>{confirmationLabel}</small>
      </div>
      <div className="stage-levels structure-legend">
        {aboveLine ? (
          <span className="tone-neutral">
            <em>Put rejection line</em>
            <strong>{formatPrice(aboveLine.value)}</strong>
          </span>
        ) : null}
        <span className="tone-accent">
          <em>Current ES</em>
          <strong>{formatPrice(currentEs)}</strong>
        </span>
        {belowLine ? (
          <span className="tone-neutral">
            <em>Call hold line</em>
            <strong>{formatPrice(belowLine.value)}</strong>
          </span>
        ) : null}
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
        <span className={`text-${toneFor(row?.budget ?? "")}`}>{row?.budget ?? "Budget unknown"}</span>
        <strong>{row?.tag ?? "Selected"}</strong>
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
