import { NextResponse } from "next/server";
import { readFile } from "node:fs/promises";
import path from "node:path";
import { mockSnapshot } from "@/lib/mockData";

export const runtime = "nodejs";

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

  const snapshotPath = process.env.SPX_PROPHET_SNAPSHOT_PATH ?? path.join(process.cwd(), "..", "data", "operator_snapshot.json");
  try {
    const raw = await readFile(snapshotPath, "utf8");
    return NextResponse.json(JSON.parse(raw));
  } catch {
    // Fall back to the bundled mock when Streamlit has not exported a real
    // snapshot yet. This keeps the product shell usable during design work.
  }

  return NextResponse.json(mockSnapshot);
}
