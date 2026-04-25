"use client";

import { useEffect, useState } from "react";
import type { OperatorSnapshot, StrikeRow } from "@/lib/types";
import { formatPrice, toneFor } from "@/lib/format";

export function OperatorWorkspace({ snapshot }: { snapshot: OperatorSnapshot }) {
  const primary = snapshot.primary_play;
  const decision = snapshot.decision;
  const context = snapshot.market_context;
  const structure = snapshot.structure;
  const primaryRows = snapshot.strike_ladders.primary;
  const [activeRail, setActiveRail] = useState("OP");
  const [selectedStrike, setSelectedStrike] = useState(primaryRows.find((row) => row.tag === "Selected")?.strike ?? primaryRows[0]?.strike ?? "");
  const [projectionMode, setProjectionMode] = useState<"current" | "retest">("retest");
  const [quoteAge, setQuoteAge] = useState(4);
  const [commandOpen, setCommandOpen] = useState(false);
  const [armed, setArmed] = useState(false);

  const selectedRow = primaryRows.find((row) => row.strike === selectedStrike) ?? primaryRows[0];
  const ticketMark = selectedRow?.mark ?? primary.current_mark;
  const ticketAtEntry = selectedRow?.at_entry ?? primary.at_entry;
  const ticketFill = selectedRow?.fill ?? primary.expected_fill;
  const ticketRR = selectedRow?.rr ?? primary.rr;
  const activeContract = selectedRow?.strike ?? primary.contract;

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
    <main className="terminal-shell">
      <aside className="rail" aria-label="Operator navigation">
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
      </aside>

      <section className="main">
        <header className="topbar">
          <div className="brand-block">
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
            <span className="chip">0DTE | PM Cash</span>
          </div>
        </header>

        <div className="workspace">
          <div className="left-stack">
            <section className="panel authority panel-live">
              <div className="authority-grid">
                <div>
                  <p className="kicker">Order Authority</p>
                  <h2 className="decision-word">{decision.state}</h2>
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
                <div className="metric-grid">
                  <Metric label="Planned Entry" value={`${formatPrice(decision.planned_entry)} SPX`} />
                  <Metric label="Selected Strike" value={activeContract} tone="warning" />
                  <Metric label="Expected Fill" value={formatPrice(ticketFill)} tone="warning" />
                  <Metric label="Current ES" value={formatPrice(structure.current_es)} />
                  <Metric label="Anchor Source" value={`${structure.anchor_source} | ${structure.anchor_confidence}`} />
                  <Metric label="Confidence" value={`${decision.confidence}%`} tone={toneFor(String(decision.confidence))} />
                </div>
              </div>
            </section>

            <section className="panel chart-panel">
              <div className="panel-header">
                <div>
                  <p className="kicker">ES Structure</p>
                  <h3>Polarity map</h3>
                </div>
                <span className="pill">Asian Anchor Active</span>
              </div>
              <div className="structure-chart">
                <div className="price-sweep" />
                {structure.levels.map((level, index) => (
                  <div
                    className={`price-line ${level.label.includes("Entry") ? "active" : ""}`}
                    data-label={`${level.label} ${formatPrice(level.value)}`}
                    key={level.label}
                    style={{ top: `${18 + index * 22}%` }}
                  >
                    <span className="line-node" />
                  </div>
                ))}
              </div>
            </section>

            <section className="panel">
              <div className="panel-header">
                <div>
                  <p className="kicker">Strike Selection</p>
                  <h3>Plan-locked nearby strikes</h3>
                </div>
                <span className="pill">Primary</span>
              </div>
              <StrikeRows rows={primaryRows} selectedStrike={selectedStrike} onSelect={setSelectedStrike} />
            </section>
          </div>

          <aside className="right-stack">
            <section className={`panel execution-ticket ${armed ? "armed-ticket" : ""}`}>
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
            </section>

            <section className="panel market-card">
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
            </section>

            <section className="panel risk-card">
              <div className="panel-header">
                <div>
                  <p className="kicker">Live Risk</p>
                  <h3>Guardrails</h3>
                </div>
                <span className="pill">Paper Preview</span>
              </div>
              <div className="execution-ticket">
                <Risk label="Daily Loss Lockout" value="Not Triggered" tone="positive" />
                <Risk label="Open Position" value="None" />
                <Risk label="Buying Power Check" value="Needed" tone="warning" />
              </div>
            </section>
          </aside>
        </div>
      </section>

      {commandOpen ? (
        <div className="command-backdrop" onClick={() => setCommandOpen(false)}>
          <section className="command-panel" onClick={(event) => event.stopPropagation()}>
            <p className="kicker">Command Center</p>
            <h3>Operator actions</h3>
            <button onClick={() => { setProjectionMode("retest"); setCommandOpen(false); }} type="button">Focus retest plan</button>
            <button onClick={() => { setArmed(true); setCommandOpen(false); }} type="button">Arm selected strike</button>
            <button onClick={() => { setActiveRail("RK"); setCommandOpen(false); }} type="button">Open risk view</button>
            <span>Press Esc to close | Ctrl+K / Cmd+K opens this panel</span>
          </section>
        </div>
      ) : null}
    </main>
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
