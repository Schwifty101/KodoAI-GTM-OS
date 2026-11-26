// A lost enqueue race (Postgres 23505 from the unique index on open jobs, migration 0016) reads as "an identical job is already open". Fake client: no database, no network.
// Run: cd web && npx tsx scripts/enqueue_dup_unit.mts
import assert from "node:assert/strict";

process.env.NEXT_PUBLIC_SUPABASE_URL ??= "http://localhost:1"; // the client is created on import and never called
process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY ??= "unused";
const { supabase } = await import("../lib/supabase");
const { enqueueJobOnce, retryJob } = await import("../lib/actions");

const DUP = { code: "23505", message: 'duplicate key value violates unique constraint "jobs_open_unique"' };
const NONE = { data: [], error: null };
// A query builder whose awaited result depends on the verb that started it; filters change nothing.
const fake = (results: Record<string, unknown>) => {
  (supabase as any).from = () => {
    let verb = "";
    const q: any = new Proxy({}, { get: (_t, k) => (k === "then" ? (res: (v: unknown) => void) => res(results[verb]) : (...a: unknown[]) => { if (k === "select" || k === "insert" || k === "update") verb = k as string; return q; }) });
    return q;
  };
};
const message = async (p: Promise<unknown>) => { try { await p; return ""; } catch (e) { return (e as Error).message; } };

fake({ select: NONE, insert: { error: DUP } });
assert.equal(await message(enqueueJobOnce("enrich_test", ["--batch", "B1"])), "an identical job is already open", "no open twin seen, but the insert lost the race");
fake({ select: NONE, insert: { error: { code: "42501", message: "permission denied" } } });
assert.equal(await message(enqueueJobOnce("enrich_test", ["--batch", "B1"])), "permission denied", "any other error keeps its own message (and the in-flight lock was released)");
fake({ update: { error: DUP } });
assert.equal(await message(retryJob("j1")), "an identical job is already open", "retry onto an open twin");
fake({ update: { error: null } });
assert.equal(await message(retryJob("j1")), "", "no error, no throw");

console.log("enqueue_dup_unit: all asserts passed");
