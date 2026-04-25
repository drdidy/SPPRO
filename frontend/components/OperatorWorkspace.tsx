import type { OperatorSnapshot, StrikeRow } from "@/lib/types";
import { formatPrice, toneFor } from "@/lib/format";

export function OperatorWorkspace({ snapshot }: { snapshot: OperatorSnapshot }) {
  const primary = snapshot.primary_play;
  const decision = snapshot.decision;
  const context = snapshot.market_context;
  const structure = snapshot.structure;

  return (
    <main className="terminal-shell">
      <aside className="rail" aria-label="Operator navigation">
        <div className="rail-logo">SP</div>
        <div className="rail-item active">OP</div>
        <div className="rail-item">ST</div>
        <div className="rail-item">RK</div>
        <div className="rail-item">LG</div>
      </aside>

      <section className="main">
        <header className="topbar">
          <div className="brand-block">
            <h1>SPX PROPHET</h1>
            <p>Structure Into Execution</p>
          </div>
          <div className="status-strip">
            <span className="chip live">Preview Feed</span>
            <span className="chip">Quote Age 04s</span>
            <span className="chip">Order Not Sent</span>
            <span className="chip">0DTE | PM Cash</span>
          </div>
        </header>

        <div className="workspace">
          <div className="left-stack">
            <section className="panel authority">
              <div className="authority-grid">
                <div>
                  <p className="kicker">Order Authority</p>
                  <h2 className="decision-word">{decision.state}</h2>
                  <p className="decision-reason">{decision.reason}</p>
                  <div className="state-row">
                    <span className={`pill tone-${toneFor(decision.bias)}`}>{decision.bias}</span>
                    <span className="pill">{decision.scenario}</span>
                    <span className={`pill tone-${toneFor(decision.event_risk)}`}>Event {decision.event_risk}</span>
                    <span className={`pill tone-${toneFor(decision.budget)}`}>{decision.budget}</span>
                  </div>
                </div>
                <div className="metric-grid">
                  <Metric label="Planned Entry" value={`${formatPrice(decision.planned_entry)} SPX`} />
                  <Metric label="Selected Strike" value={decision.selected_strike} />
                  <Metric label="Expected Fill" value={formatPrice(decision.expected_fill)} />
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
                {structure.levels.map((level, index) => (
                  <div
                    className={`price-line ${level.label.includes("Entry") ? "active" : ""}`}
                    data-label={`${level.label} ${formatPrice(level.value)}`}
                    key={level.label}
                    style={{ top: `${18 + index * 22}%` }}
                  />
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
              <StrikeRows rows={snapshot.strike_ladders.primary} />
            </section>
          </div>

          <aside className="right-stack">
            <section className="panel execution-ticket">
              <div className="contract">
                <div>
                  <p className="kicker">Execution Ticket</p>
                  <h2>{primary.contract}</h2>
                  <p>{primary.direction} | {primary.status} | {primary.quality} estimate</p>
                </div>
                <span className={`pill tone-${toneFor(primary.status)}`}>{primary.status}</span>
              </div>
              <div className="kv-grid">
                <KV label="Current Mark" value={formatPrice(primary.current_mark)} />
                <KV label="At Entry" value={formatPrice(primary.at_entry)} />
                <KV label="Expected Fill" value={formatPrice(primary.expected_fill)} />
              </div>
              <div className="risk-block">
                <Risk label="Max Loss If Filled" value="$771 est." tone="warning" />
                <Risk label="Spread Width" value="0.22 est." />
                <Risk label="Liquidity" value="Normal" tone="positive" />
                <Risk label="Settlement" value="PM Cash | European" />
              </div>
              <div className="button-row">
                <div className="button primary">Review Required</div>
                <div className="button">Order Not Sent</div>
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
                  <div className="headline" key={headline.title}>
                    <strong>{headline.title}</strong>
                    <span>{headline.source} | {headline.time}</span>
                  </div>
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
    </main>
  );
}

function Metric({ label, value, tone = "neutral" }: { label: string; value: string; tone?: string }) {
  return (
    <div className="metric">
      <span>{label}</span>
      <strong className={`text-${tone}`}>{value}</strong>
    </div>
  );
}

function KV({ label, value }: { label: string; value: string }) {
  return (
    <div className="kv">
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

function StrikeRows({ rows }: { rows: StrikeRow[] }) {
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
        <div className={`ladder-row ${row.tag === "Selected" ? "selected" : ""}`} key={row.strike}>
          <strong>{row.strike}</strong>
          <span>{formatPrice(row.mark)}</span>
          <span>{formatPrice(row.at_entry)}</span>
          <span>{formatPrice(row.fill)}</span>
          <span>{row.rr == null ? "-" : row.rr.toFixed(2)}</span>
          <span className={`text-${toneFor(row.budget)}`}>{row.budget}</span>
          <span>{row.tag}</span>
        </div>
      ))}
    </div>
  );
}
