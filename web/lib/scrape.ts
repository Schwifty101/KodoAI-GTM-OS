import { supabase } from "./supabase";
import { fetchAll } from "./fetchAll";
import type { Coverage, Job } from "./types";

export const loadCoverage = () =>
  fetchAll<Coverage>((a, b) => supabase.from("coverage").select("*").order("seq").range(a, b));

export type MetroRow = {
  metro_rank: number; metro: string; state: string; total: number; pending: number; running: number; done: number; failed: number;
  places: number; newLeads: number; saturated: number; lastScraped: string | null;
};

export function summarizeMetros(rows: Coverage[]): MetroRow[] {
  const m = new Map<string, MetroRow>();
  for (const r of rows) {
    const k = `${r.metro_rank}|${r.metro}|${r.state}`;
    const x = m.get(k) ?? { metro_rank: r.metro_rank, metro: r.metro, state: r.state, total: 0, pending: 0, running: 0, done: 0, failed: 0, places: 0, newLeads: 0, saturated: 0, lastScraped: null };
    x.total++; x[r.status]++;
    x.places += r.places_found ?? 0; x.newLeads += r.new_leads ?? 0; if (r.saturated) x.saturated++;
    if (r.scraped_at && (!x.lastScraped || r.scraped_at > x.lastScraped)) x.lastScraped = r.scraped_at;
    m.set(k, x);
  }
  return [...m.values()].sort((a, b) => a.metro_rank - b.metro_rank);
}

export const walkJobOpen = (jobs: Job[]) => jobs.some((j) => j.kind === "walk" && ["queued", "running", "paused_budget"].includes(j.status));

export function runTilesArgv(n: number): string[] {
  if (!Number.isInteger(n) || n < 1 || n > 20) throw new Error("tiles must be a whole number from 1 to 20");
  return ["--tiles", String(n)];
}
