// Verifies the Preview/Apply guard (enqueuePreview, enqueueApply, enqueueGuarded) against the real database under RLS.
// TEST rows only: kinds verify-sheet_test, import-sheet_test, enrich_test and argv naming TEST_runnow. A live worker may claim a queued
// *_test row but fails it at once (the kind is not in ALLOWED), so no pass ever runs. Rows are removed in `finally`.
// Run: node --env-file=.env.local --env-file=../.env --import tsx scripts/verify_runnow.mts
import { createClient } from "@supabase/supabase-js";
import { supabase } from "../lib/supabase";
import { enqueueApply, enqueueGuarded, enqueuePreview } from "../lib/actions";

const admin = createClient(process.env.NEXT_PUBLIC_SUPABASE_URL!, process.env.SUPABASE_SECRET_KEY!);
const fails: string[] = [];
const check = (name: string, cond: boolean) => { console.log(cond ? "ok  " : "FAIL", name); if (!cond) fails.push(name); };
const throws = async (p: Promise<unknown>) => { try { await p; return ""; } catch (e) { return (e as Error).message; } };

const KIND = "verify-sheet_test";
const TAG = `TEST_runnow_${Date.now()}`;
const ARGV = ["--batch", TAG];
const rows = async (kind: string, argv: string[]) => (await admin.from("jobs").select("id,status,payload,created_at").eq("kind", kind).contains("payload", { argv })).data ?? [];
const exact = async (kind: string, argv: string[]) => (await rows(kind, argv)).filter((r) => JSON.stringify(r.payload.argv) === JSON.stringify(argv));
const clear = async () => {
  await admin.from("jobs").delete().like("payload->>argv", `%TEST_runnow%`);
  await admin.from("jobs").delete().eq("kind", "import-sheet_test");
};
const doneJob = (kind: string, argv: string[], hoursOld = 0) => admin.from("jobs").insert({
  kind, status: "done", payload: { argv }, result: { output: "dry run" }, finished_at: new Date().toISOString(),
  created_at: new Date(Date.now() - hoursOld * 3600_000).toISOString(),
});

try {
  await clear();
  const g = await admin.auth.admin.generateLink({ type: "magiclink", email: "soban@kodoai.xyz" });
  await supabase.auth.verifyOtp({ token_hash: g.data.properties!.hashed_token, type: "magiclink" });

  // Apply needs a done preview: none yet.
  check("enqueueApply with no preview throws 'no done preview for this argv'", (await throws(enqueueApply(KIND, ARGV))) === "no done preview for this argv");
  check("  ...and inserted nothing", (await rows(KIND, ARGV)).length === 0);

  // A failed preview does not unlock Apply.
  await admin.from("jobs").insert({ kind: KIND, status: "failed", payload: { argv: ARGV }, error: "boom", finished_at: new Date().toISOString() });
  check("enqueueApply after a failed preview throws", (await throws(enqueueApply(KIND, ARGV))) === "no done preview for this argv");

  // A stale preview (25 h) does not unlock Apply.
  await doneJob(KIND, ARGV, 25);
  check("enqueueApply after a 25 h old done preview throws", (await throws(enqueueApply(KIND, ARGV))) === "no done preview for this argv");

  // A fresh done preview unlocks exactly this argv.
  await doneJob(KIND, ARGV);
  check("enqueueApply with a different argv throws", (await throws(enqueueApply(KIND, ["--batch", `${TAG}_other`]))) === "no done preview for this argv");
  check("enqueueApply with an extra flag throws", (await throws(enqueueApply(KIND, [...ARGV, "--limit", "5"]))) === "no done preview for this argv");
  check("enqueueApply with a done preview does not throw", (await throws(enqueueApply(KIND, ARGV))) === "");
  const applied = await exact(KIND, [...ARGV, "--confirm"]);
  check("  ...inserted one queued job with --confirm last", applied.length === 1 && applied[0].status === "queued" && applied[0].payload.argv.at(-1) === "--confirm");
  check("enqueueApply twice: the second is refused while the first is open", (await throws(enqueueApply(KIND, ARGV))).includes("already open") && (await exact(KIND, [...ARGV, "--confirm"])).length === 1);
  check("enqueueApply refuses argv that already has --confirm or an abbreviation", (await throws(enqueueApply(KIND, [...ARGV, "--conf"]))) !== "");
  check("enqueueApply refuses a kind without a dry run", (await throws(enqueueApply("clean_test", ARGV))) !== "");

  // Preview never carries --confirm; a second identical preview is refused while the first is open.
  await admin.from("jobs").delete().like("payload->>argv", `%TEST_runnow%`).eq("status", "queued"); // free the apply job
  check("enqueuePreview with --confirm throws", (await throws(enqueuePreview(KIND, [...ARGV, "--confirm"]))) !== "");
  check("enqueuePreview with --conf throws", (await throws(enqueuePreview(KIND, [...ARGV, "--conf"]))) !== "");
  check("  ...and inserted nothing", (await rows(KIND, [...ARGV, "--confirm"])).length === 0 && (await rows(KIND, [...ARGV, "--conf"])).length === 0);
  check("enqueuePreview inserts one queued job", (await throws(enqueuePreview(KIND, ARGV))) === "" && (await exact(KIND, ARGV)).filter((r) => r.status === "queued").length === 1);
  check("enqueuePreview twice: the second throws (identical job open)", (await throws(enqueuePreview(KIND, ARGV))).includes("already open") && (await exact(KIND, ARGV)).filter((r) => r.status === "queued").length === 1);

  // The Jobs dropdown path.
  check("enqueueGuarded import-sheet_test --confirm throws (no preview)", (await throws(enqueueGuarded("import-sheet_test", ["--confirm"]))) === "no done preview for this argv");
  check("enqueueGuarded import-sheet_test --conf throws (abbreviation)", (await throws(enqueueGuarded("import-sheet_test", ["--conf"]))) === "no done preview for this argv");
  check("  ...and inserted nothing", (await admin.from("jobs").select("id").eq("kind", "import-sheet_test")).data!.length === 0);
  await admin.from("jobs").delete().like("payload->>argv", `%TEST_runnow%`).eq("status", "queued");
  check("enqueueGuarded verify-sheet_test --confirm with a done preview routes to apply", (await throws(enqueueGuarded(KIND, [...ARGV, "--confirm"]))) === "" && (await exact(KIND, [...ARGV, "--confirm"])).length === 1);
  await admin.from("jobs").delete().like("payload->>argv", `%TEST_runnow%`).eq("status", "queued");
  check("enqueueGuarded without --confirm is a plain preview enqueue", (await throws(enqueueGuarded(KIND, ARGV))) === "" && (await exact(KIND, ARGV)).filter((r) => r.status === "queued").length === 1);
  const ENRICH = ["--batch", TAG, "--confirm"]; // a kind with no dry run: --confirm is not special to the guard
  check("enqueueGuarded on a non-confirm kind goes straight to enqueueJobOnce", (await throws(enqueueGuarded("enrich_test", ENRICH))) === "" && (await exact("enrich_test", ENRICH)).length === 1);

  // Review focus: a real double click is two calls in flight at once, not one after the other.
  await clear();
  const RACE = ["--batch", `${TAG}_race`];
  await Promise.allSettled([enqueuePreview(KIND, RACE), enqueuePreview(KIND, RACE)]);
  const n = (await exact(KIND, RACE)).length;
  check("two overlapping Previews in one process insert exactly one job", n === 1);
  await admin.from("jobs").update({ status: "done" }).eq("kind", KIND).contains("payload", { argv: RACE });
  check("a new Preview is allowed once the old one is done (in-flight lock released)", (await throws(enqueuePreview(KIND, RACE))) === "" && (await exact(KIND, RACE)).length === 2);
} finally {
  await clear();
}
console.log(fails.length ? `${fails.length} FAILED` : "all ok");
process.exit(fails.length ? 1 : 0);
