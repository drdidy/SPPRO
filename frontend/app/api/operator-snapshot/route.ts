import { NextResponse } from "next/server";
import { mockSnapshot } from "@/lib/mockData";

export async function GET() {
  const upstream = process.env.SPX_PROPHET_API_URL;

  if (upstream) {
    try {
      const response = await fetch(`${upstream.replace(/\/$/, "")}/api/operator-snapshot`, {
        next: { revalidate: 2 }
      });
      if (response.ok) {
        return NextResponse.json(await response.json());
      }
    } catch {
      // Fall back to the local mock snapshot. The UI should stay alive even if
      // the Python bridge is not running.
    }
  }

  return NextResponse.json(mockSnapshot);
}
