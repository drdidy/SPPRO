import type { Play } from "@/lib/types";
import { formatPrice, toneFor } from "@/lib/format";

export function ExecutionCard({ play, emphasis = false }: { play: Play; emphasis?: boolean }) {
  const tone = toneFor(play.status);

  return (
    <article className={`execution-card ${emphasis ? "primary" : ""}`}>
      <div className="card-shine" />
      <div className="execution-header">
        <div>
          <p className="eyebrow">{play.title}</p>
          <h3>{play.direction} | {play.contract}</h3>
        </div>
        <span className={`pill tone-${tone}`}>{play.status}</span>
      </div>

      <div className="price-triplet">
        <Value label="Current" value={formatPrice(play.current_mark)} />
        <Value label="At Entry" value={formatPrice(play.at_entry)} />
        <Value label="Expected Fill" value={formatPrice(play.expected_fill)} />
      </div>

      <div className="mini-grid">
        <Value label="RR" value={play.rr == null ? "-" : play.rr.toFixed(2)} />
        <Value label="Zone" value={play.zone} />
        <Value label="Budget" value={play.budget} />
        <Value label="Quality" value={play.quality} />
      </div>

      <p className="operator-line">{play.reason}</p>
    </article>
  );
}

function Value({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}
