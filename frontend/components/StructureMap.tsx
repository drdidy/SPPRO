import type { OperatorSnapshot } from "@/lib/types";
import { formatPrice } from "@/lib/format";

export function StructureMap({ snapshot }: { snapshot: OperatorSnapshot }) {
  const levels = snapshot.structure.levels;

  return (
    <section className="glass-card structure-card">
      <div className="section-heading">
        <div>
          <p className="eyebrow">ES Structure</p>
          <h2>Polarity map</h2>
        </div>
        <span className="pill">{snapshot.structure.anchor_source} anchor</span>
      </div>

      <div className="structure-scale">
        {levels.map((level, index) => (
          <div className={`level-line tone-${level.tone}`} key={level.label}>
            <div className="level-dot" style={{ animationDelay: `${index * 120}ms` }} />
            <div>
              <span>{level.label}</span>
              <strong>{formatPrice(level.value)}</strong>
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}
