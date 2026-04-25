import type { OperatorSnapshot } from "@/lib/types";
import { toneFor } from "@/lib/format";

export function MarketContext({ snapshot }: { snapshot: OperatorSnapshot }) {
  const context = snapshot.market_context;
  const tone = toneFor(context.event_risk);

  return (
    <section className="glass-card market-card">
      <div className="section-heading">
        <div>
          <p className="eyebrow">Market Context</p>
          <h2>Event and headline risk</h2>
        </div>
        <span className={`pill tone-${tone}`}>{context.risk_mode}</span>
      </div>

      <div className="context-line">
        <span>Next event</span>
        <strong>{context.next_event}</strong>
      </div>
      <p className="muted-copy">{context.interpretation}</p>

      <div className="headline-list">
        {context.headlines.slice(0, 5).map((headline) => (
          <a
            className="headline-row"
            href={headline.url ?? "#"}
            aria-disabled={!headline.url}
            key={`${headline.title}-${headline.time}`}
          >
            <span>{headline.title}</span>
            <em>{headline.source} · {headline.time}</em>
          </a>
        ))}
      </div>
    </section>
  );
}
