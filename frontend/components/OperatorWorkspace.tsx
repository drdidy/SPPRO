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
  const [pointer, setPointer] = useState({ x: 50, y: 50 });
  const reduceMotion = useReducedMotion();

  const selectedRow = primaryRows.find((row) => row.strike === selectedStrike) ?? primaryRows[0];
  const ticketMark = selectedRow?.mark ?? primary.current_mark;
  const ticketAtEntry = selectedRow?.at_entry ?? primary.at_entry;
  const ticketFill = selectedRow?.fill ?? primary.expected_fill;
  const ticketRR = selectedRow?.rr ?? primary.rr;
  const activeContract = selectedRow?.strike ?? primary.contract;
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
      className="terminal-shell cinematic-shell"
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
        <motion.header className="topbar cinematic-topbar" variants={panelVariants}>
          <div className="brand-block">
            <span className="brand-kicker">Execution Intelligence</span>
            <h1>SPX PROPHET</h1>
            <p>Structure Into Execution</p>
          </div>
          <div className="status-strip">
            <span className="chip live">Preview Feed</span>
            <div className="quote-tape" aria-live="polite">
              <span>SPX <strong>7,194.75</strong></span>
              <span>ES <strong>{formatPrice(structure.current_es)}</strong></span>
              <span>VIX <strong>17.42</strong></span>
              <span>0DTE IV <strong>Elevated</strong></span>
              <span>Age <strong>{quoteAge.toString().padStart(2, "0")}s</strong></span>
            </div>
            <button className="chip action-chip" onClick={() => setCommandOpen(true)} type="button">Command /</button>
            <span className="chip">Order Not Sent</span>
          </div>
        </motion.header>

        <motion.section className="cinematic-hero" variants={panelVariants}>
          <div className="hero-copy">
            <p className="kicker">Order Authority</p>
            <div className="decision-lockup">
              <span className="decision-index">01</span>
              <h2 className="decision-word">{decision.state}</h2>
            </div>
            <p className="decision-reason">
              {projectionMode === "retest"
                ? decision.reason
                : "Current price is still away from the validated execution line."}
            </p>
            <div className="mode-switch" aria-label="Projection mode">
              <button className={projectionMode === "current" ? "active" : ""} onClick={() => setProjectionMode("current")} type="button">Current</button>
              <button className={projectionMode === "retest" ? "active" : ""} onClick={() => setProjectionMode("retest")} type="button">If Retest</button>
            </div>
            <div className="state-row">
              <span className={`pill tone-${toneFor(decision.bias)}`}>{decision.bias}</span>
              <span className="pill">{decision.scenario}</span>
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

          <div className="hero-metrics">
            <Metric label="Planned Entry" value={`${formatPrice(decision.planned_entry)} SPX`} />
            <Metric label="Selected Strike" value={activeContract} tone="warning" />
            <Metric label="Expected Fill" value={formatPrice(ticketFill)} tone="warning" />
            <Metric label="Current ES" value={formatPrice(structure.current_es)} />
            <Metric label="Anchor Source" value={`${structure.anchor_source} | ${structure.anchor_confidence}`} />
            <Metric label="Confidence" value={`${decision.confidence}%`} tone={toneFor(String(decision.confidence))} />
          </div>
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
            <motion.section className={`panel execution-ticket ${armed ? "armed-ticket" : ""}`} variants={panelVariants}>
              <div className="contract">
                <div>
                  <p className="kicker">Execution Ticket</p>
                  <h2>{activeContract}</h2>
                  <p>{primary.direction} | {armed ? "Retest Armed" : primary.status} | {primary.quality} estimate</p>
                </div>
                <span className={`pill tone-${armed ? "warning" : toneFor(primary.status)}`}>{armed ? "Armed" : primary.status}</span>
              </div>
              <div className="kv-grid">
                <KV label="Current Mark" value={formatPrice(ticketMark)} />
                <KV label="At Entry" value={formatPrice(ticketAtEntry)} />
                <KV label="Expected Fill" value={formatPrice(ticketFill)} />
              </div>
              <p className="ticket-copy">
                If price returns to planned entry, {activeContract} is estimated near {formatPrice(ticketAtEntry)} with likely fill near {formatPrice(ticketFill)}.
              </p>
              <div className="risk-block">
                <Risk label="Max Loss If Filled" value={ticketFill == null ? "Unavailable" : `$${Math.round(ticketFill * 100)} est.`} tone="warning" />
                <Risk label="RR at Entry" value={ticketRR == null ? "-" : ticketRR.toFixed(2)} />
                <Risk label="Liquidity" value="Normal" tone="positive" />
                <Risk label="Settlement" value="PM Cash | European" />
              </div>
              <div className="button-row">
                <button className="button primary" onClick={() => setArmed((value) => !value)} type="button">
                  {armed ? "Retest Armed" : "Arm Retest"}
                </button>
                <button className="button" onClick={() => setCommandOpen(true)} type="button">Open Commands</button>
              </div>
            </motion.section>

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
  return (
    <section className="signal-theater" aria-label="Animated structure map">
      <div className="stage-orbit orbit-one" />
      <div className="stage-orbit orbit-two" />
      <svg className="cone-svg" viewBox="0 0 520 420" role="img" aria-label="Asian polarity lines and retest zone">
        <defs>
          <linearGradient id="coneLine" x1="0" x2="1" y1="0" y2="1">
            <stop stopColor="#71c7df" stopOpacity="0.12" />
            <stop offset="0.48" stopColor="#71c7df" stopOpacity="0.86" />
            <stop offset="1" stopColor="#d8aa57" stopOpacity="0.26" />
          </linearGradient>
          <radialGradient id="coreGlow">
            <stop stopColor="#71c7df" stopOpacity="0.9" />
            <stop offset="1" stopColor="#71c7df" stopOpacity="0" />
          </radialGradient>
        </defs>
        <path className="cone-fill" d="M80 335 C185 235 280 170 445 70 L445 340 C285 276 180 278 80 335Z" />
        <path className="cone-line line-a" d="M74 336 C175 240 286 164 448 70" />
        <path className="cone-line line-b" d="M84 335 C195 292 300 296 448 340" />
        <path className="entry-band" d="M95 230 C210 224 332 214 455 198" />
        <circle className="pulse-core" cx="282" cy="218" r="64" fill="url(#coreGlow)" />
        <circle className="stage-node node-a" cx="282" cy="218" r="5" />
        <circle className="stage-node node-b" cx="448" cy="70" r="4" />
        <circle className="stage-node node-c" cx="448" cy="340" r="4" />
      </svg>
      <div className="stage-readout top-left">
        <span>Current ES</span>
        <strong>{formatPrice(currentEs)}</strong>
      </div>
      <div className="stage-readout bottom-left">
        <span>Planned Entry</span>
        <strong>{formatPrice(plannedEntry)}</strong>
      </div>
      <div className="stage-readout right">
        <span>{activeContract}</span>
        <strong>{formatPrice(expectedFill)} fill</strong>
      </div>
      <div className="stage-levels">
        {levels.map((level) => (
          <span key={level.label}>{level.label}: {formatPrice(level.value)}</span>
        ))}
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
