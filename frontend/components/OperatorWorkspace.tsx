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
  const decision = snapshot.decision;
  const context = snapshot.market_context;
  const structure = snapshot.structure;
  const primaryRows = snapshot.strike_ladders.primary;
  const [activeRail, setActiveRail] = useState("OP");
  const [selectedStrike, setSelectedStrike] = useState(primaryRows.find((row) => row.tag === "Selected")?.strike ?? primaryRows[0]?.strike ?? "");
  const [projectionMode, setProjectionMode] = useState<ProjectionMode>("retest");
  const [quoteAge, setQuoteAge] = useState(4);
  const [commandOpen, setCommandOpen] = useState(false);
  const [armed, setArmed] = useState(false);
  const [visualTheme, setVisualTheme] = useState<"daylight" | "obsidian">("daylight");
  const [pointer, setPointer] = useState({ x: 50, y: 50 });
  const reduceMotion = useReducedMotion();

  const selectedRow = primaryRows.find((row) => row.strike === selectedStrike) ?? primaryRows[0];
  const ticketMark = selectedRow?.mark ?? primary.current_mark;
  const ticketAtEntry = selectedRow?.at_entry ?? primary.at_entry;
  const ticketFill = selectedRow?.fill ?? primary.expected_fill;
  const ticketRR = selectedRow?.rr ?? primary.rr;
  const activeContract = selectedRow?.strike ?? primary.contract;
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
  const nextThemeLabel = visualTheme === "daylight" ? "Obsidian" : "Daylight";
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

  const stageLevels = useMemo(() => structure.levels.slice(0, 4), [structure.levels]);

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
            <button
              className="masthead-button ghost"
              onClick={() => setVisualTheme((value) => (value === "daylight" ? "obsidian" : "daylight"))}
              type="button"
            >
              Switch to {nextThemeLabel}
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

          <ExecutionTicket
            activeContract={activeContract}
            armed={armed}
            currentMark={ticketMark}
            expectedFill={ticketFill}
            onArm={() => setArmed((value) => !value)}
            onCommands={() => setCommandOpen(true)}
            primary={primary}
            rr={ticketRR}
            atEntry={ticketAtEntry}
          />
        </motion.section>

        <motion.section className="operator-strip" variants={panelVariants} aria-label="Operator summary">
          <Metric label="Planned Entry" value={`${formatPrice(decision.planned_entry)} SPX`} />
          <Metric label="Selected Strike" value={activeContract} tone="warning" />
          <Metric label="Expected Fill" value={formatPrice(ticketFill)} tone="warning" />
          <Metric label="Current ES" value={formatPrice(structure.current_es)} />
          <Metric label="Anchor Source" value={`${structure.anchor_source} | ${structure.anchor_confidence}`} />
          <Metric label="Confidence" value={`${decision.confidence}%`} tone={toneFor(String(decision.confidence))} />
        </motion.section>

        <div className="workspace studio-workspace">
          <div className="left-stack">
            <motion.section className="panel" variants={panelVariants}>
              <div className="panel-header">
                <div>
                  <p className="kicker">Strike Selection</p>
                  <h3>Plan-locked nearby strikes</h3>
                </div>
                <span className="pill">Primary</span>
              </div>
              <StrikeRows rows={primaryRows} selectedStrike={selectedStrike} onSelect={setSelectedStrike} />
            </motion.section>

            <motion.section className="panel narrative-panel" variants={panelVariants}>
              <div className="panel-header">
                <div>
                  <p className="kicker">Execution Sequence</p>
                  <h3>From structure to action</h3>
                </div>
                <span className="pill">Live Ritual</span>
              </div>
              <div className="sequence-grid">
                <SequenceStep index="01" title="Anchor" value={`${structure.anchor_source} polarity`} active />
                <SequenceStep index="02" title="Retest" value="Wait for clean line return" active={projectionMode === "retest"} />
                <SequenceStep index="03" title="Contract" value={`${activeContract} selected`} active />
                <SequenceStep index="04" title="Authority" value={armed ? "Retest armed" : "Review required"} active={armed} />
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
            <button onClick={() => { setArmed(true); setCommandOpen(false); }} type="button">Arm selected strike</button>
            <button onClick={() => { setActiveRail("RK"); setCommandOpen(false); }} type="button">Open risk view</button>
            <span>Press Esc to close | Ctrl+K / Cmd+K opens this panel</span>
          </motion.section>
        </motion.div>
        ) : null}
      </AnimatePresence>
    </motion.main>
  );
}

function ExecutionTicket({
  activeContract,
  armed,
  atEntry,
  currentMark,
  expectedFill,
  onArm,
  onCommands,
  primary,
  rr
}: {
  activeContract: string;
  armed: boolean;
  atEntry: number | null;
  currentMark: number | null;
  expectedFill: number | null;
  onArm: () => void;
  onCommands: () => void;
  primary: OperatorSnapshot["primary_play"];
  rr: number | null;
}) {
  return (
    <motion.section className={`panel execution-ticket hero-ticket ${armed ? "armed-ticket" : ""}`} variants={panelVariants}>
      <div className="contract">
        <div>
          <p className="kicker">Execution Ticket</p>
          <h2>{activeContract}</h2>
          <p>{primary.direction} | {armed ? "Retest Armed" : primary.status} | {primary.quality} estimate</p>
        </div>
        <span className={`pill tone-${armed ? "warning" : toneFor(primary.status)}`}>{armed ? "Armed" : primary.status}</span>
      </div>
      <div className="kv-grid">
        <KV label="Current Mark" value={formatPrice(currentMark)} />
        <KV label="At Entry" value={formatPrice(atEntry)} />
        <KV label="Expected Fill" value={formatPrice(expectedFill)} />
      </div>
      <p className="ticket-copy">
        If price returns to planned entry, {activeContract} is estimated near {formatPrice(atEntry)} with likely fill near {formatPrice(expectedFill)}.
      </p>
      <div className="risk-block">
        <Risk label="Max Loss If Filled" value={expectedFill == null ? "Unavailable" : `$${Math.round(expectedFill * 100)} est.`} tone="warning" />
        <Risk label="RR at Entry" value={rr == null ? "-" : rr.toFixed(2)} />
        <Risk label="Liquidity" value="Normal" tone="positive" />
        <Risk label="Settlement" value="PM Cash | European" />
      </div>
      <div className="button-row">
        <button className="button primary" onClick={onArm} type="button">
          {armed ? "Retest Armed" : "Arm Retest"}
        </button>
        <button className="button" onClick={onCommands} type="button">Open Commands</button>
      </div>
    </motion.section>
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
  const pad = Math.max((rawMax - rawMin) * 0.16, 10);
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
  const routeD = `M ${currentNodeX} ${currentY} C ${chartLeft + 126} ${(currentY + entryY) / 2 - 34}, ${chartRight - 116} ${(currentY + entryY) / 2 + 34}, ${futureNodeX} ${entryY}`;
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
  const gateLevels = [aboveLine, belowLine].filter((level): level is { label: string; value: number; tone: string } => level != null);
  const distanceLabel = distanceToRetest == null
    ? "Distance unavailable"
    : `${Math.abs(distanceToRetest).toFixed(2)} pts ${distanceToRetest >= 0 ? "above" : "below"} retest`;
  const distanceTop = Math.max(15, Math.min(78, (((currentY + entryY) / 2) / 420) * 100));
  const entryTop = Math.max(16, Math.min(80, (entryY / 420) * 100));
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
        <path className="retest-route" d={routeD} markerEnd="url(#routeArrow)" />
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
      <div className="entry-ticket-badge" style={{ top: `${entryTop}%` }}>
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
