import { OperatorWorkspace } from "@/components/OperatorWorkspace";
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

  return <OperatorWorkspace snapshot={snapshot} />;
}
