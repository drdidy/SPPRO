import type { StrikeRow } from "@/lib/types";
import { formatPrice, toneFor } from "@/lib/format";

export function StrikeLadder({ title, rows }: { title: string; rows: StrikeRow[] }) {
  return (
    <section className="glass-card ladder-card">
      <div className="section-heading">
        <div>
          <p className="eyebrow">Strike Selection</p>
          <h2>{title}</h2>
        </div>
        <span className="pill">Plan-locked</span>
      </div>
      <div className="ladder-table">
        <div className="ladder-row ladder-head">
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
            <span>{row.rr == null ? "—" : row.rr.toFixed(2)}</span>
            <span className={`text-${toneFor(row.budget)}`}>{row.budget}</span>
            <span className="tag">{row.tag}</span>
          </div>
        ))}
      </div>
    </section>
  );
}
