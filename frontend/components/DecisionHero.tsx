import type { OperatorSnapshot } from "@/lib/types";
import { formatPrice, toneFor } from "@/lib/format";

export function DecisionHero({ snapshot }: { snapshot: OperatorSnapshot }) {
  const { decision, structure } = snapshot;
  const tone = toneFor(decision.state);

  return (
    <section className={`hero-shell tone-${tone}`}>
      <div className="hero-ambient" />
      <div className="hero-topline">
        <div>
          <p className="eyebrow">SPX Prophet</p>
          <h1>{decision.state}</h1>
          <p className="hero-reason">{decision.reason}</p>
        </div>
        <div className={`decision-orb tone-${tone}`}>
          <span>{decision.modifier}</span>
        </div>
      </div>

      <div className="hero-badges">
        <span>{decision.bias}</span>
        <span>{decision.scenario}</span>
        <span>Risk {decision.risk}</span>
        <span>Event {decision.event_risk}</span>
      </div>

      <div className="hero-grid">
        <Metric label="Planned Entry" value={`${formatPrice(decision.planned_entry)} SPX`} />
        <Metric label="Selected Strike" value={decision.selected_strike} />
        <Metric label="Expected Fill" value={formatPrice(decision.expected_fill)} />
        <Metric label="Budget" value={decision.budget} />
        <Metric label="Current ES" value={formatPrice(structure.current_es)} />
        <Metric label="Anchor" value={`${structure.anchor_source} · ${structure.anchor_confidence}`} />
      </div>
    </section>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="metric-card">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}
