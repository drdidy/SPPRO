import { DecisionHero } from "@/components/DecisionHero";
import { ExecutionCard } from "@/components/ExecutionCard";
import { MarketContext } from "@/components/MarketContext";
import { StrikeLadder } from "@/components/StrikeLadder";
import { StructureMap } from "@/components/StructureMap";
import { mockSnapshot } from "@/lib/mockData";
import type { OperatorSnapshot } from "@/lib/types";

async function getSnapshot(): Promise<OperatorSnapshot> {
  const baseUrl = process.env.NEXT_PUBLIC_APP_URL ?? "http://localhost:3000";
  try {
    const response = await fetch(`${baseUrl}/api/operator-snapshot`, {
      cache: "no-store"
    });
    if (response.ok) {
      return response.json();
    }
  } catch {
    // Keep the production shell alive while the Python bridge is offline.
  }
  return mockSnapshot;
}

export default async function Home() {
  const snapshot = await getSnapshot();

  return (
    <main className="app-shell">
      <div className="background-grid" />
      <header className="topbar">
        <div>
          <span className="brand-mark">SPX</span>
          <span className="brand-name">PROPHET</span>
        </div>
        <p>Structure Into Execution</p>
      </header>

      <DecisionHero snapshot={snapshot} />

      <div className="two-column">
        <MarketContext snapshot={snapshot} />
        <StructureMap snapshot={snapshot} />
      </div>

      <section className="execution-grid">
        <ExecutionCard play={snapshot.primary_play} emphasis />
        <ExecutionCard play={snapshot.alternate_play} />
      </section>

      <section className="two-column ladders">
        <StrikeLadder title="Primary Nearby Strikes" rows={snapshot.strike_ladders.primary} />
        <StrikeLadder title="Alternate Nearby Strikes" rows={snapshot.strike_ladders.alternate} />
      </section>
    </main>
  );
}
