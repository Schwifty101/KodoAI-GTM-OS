import type { Job } from "./types";

// Pure logic for the run-now buttons: no Supabase, no React. Used by lib/actions.ts (the guard) and the pages.

export type JobRow = Pick<Job, "id" | "kind" | "status" | "payload" | "result" | "error" | "created_at" | "finished_at">;

/** Kinds whose CLI pass has a dry run and takes --confirm to write; only these go through Preview/Apply. */
export const CONFIRM_KINDS = ["import-sheet", "verify-sheet", "sheet-queue", "sheet-paint"];

/** Test jobs use a `_test` kind suffix; the guard treats them like the real kind. */
export const baseKind = (kind: string) => kind.replace(/_test$/, "");

export const sameArgv = (a: string[], b: string[]) => JSON.stringify(a) === JSON.stringify(b);

/** argparse takes any unambiguous prefix, so `--conf` is `--confirm`; every prefix of at least `--c` (and `--conf=x`) counts as the flag. */
export const isConfirmFlag = (a: string) => { const f = a.split("=")[0]; return f.length >= 3 && "--confirm".startsWith(f); };

const argvOf = (j: JobRow): string[] => j.payload?.argv ?? [];
const at = (j: JobRow) => Date.parse(j.created_at);
const newest = (jobs: JobRow[]) => jobs.reduce<JobRow | undefined>((m, j) => (!m || at(j) > at(m) ? j : m), undefined);

export const PREVIEW_MAX_AGE_MS = 24 * 3600_000;

/** The newest `done` job of this kind with exactly this argv, created under 24 h ago. A job that already carries --confirm is an apply, never a preview. */
export function findPreview(jobs: JobRow[], kind: string, argv: string[], now: Date = new Date()): JobRow | undefined {
  return newest(jobs.filter((j) =>
    j.kind === kind && j.status === "done" && sameArgv(argvOf(j), argv) && !argvOf(j).some(isConfirmFlag) && now.getTime() - at(j) < PREVIEW_MAX_AGE_MS));
}

/**
 * A step is enabled when the previous step has a `done` job whose argv names this batch.
 * A sheet import has no batch id in its argv (import-sheet creates the batch), so `isSheetImport` counts as "import done".
 * The first step has no gate. Job kinds are compared by baseKind, so `_test` jobs drive it too.
 */
export function stepState(order: string[], step: string, jobs: JobRow[], batchId: string, isSheetImport = false): { enabled: boolean; why?: string } {
  const i = order.indexOf(step);
  if (i < 0) throw new Error(`unknown step ${step}`);
  if (i === 0) return { enabled: true };
  const prev = order[i - 1];
  if (prev === "import" && isSheetImport) return { enabled: true };
  const kind = prev === "import" ? "import-sheet" : prev;
  const done = jobs.some((j) => j.status === "done" && baseKind(j.kind) === kind && argvOf(j).includes(batchId));
  return done ? { enabled: true } : { enabled: false, why: `${prev} not done` };
}

/** The newest job of exactly this kind, by created_at. */
export const lastRun = (jobs: JobRow[], kind: string): JobRow | undefined => newest(jobs.filter((j) => j.kind === kind));

/** UI-only estimate for enrich (it has no dry run): leads times credits each, rounded so 3 x 0.1 shows 0.3. */
export const enrichEstimate = (cleaned: number, creditPerLead: number) => ({ leads: cleaned, credits: Math.round(cleaned * creditPerLead * 1e4) / 1e4 });
