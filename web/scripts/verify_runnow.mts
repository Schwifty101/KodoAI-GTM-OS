// Verifies the Preview/Apply guard (enqueuePreview, enqueueApply, enqueueGuarded) against the real database under RLS.
// TEST rows only: kinds verify-sheet_test, import-sheet_test, enrich_test, draft_test, followups_test and argv naming TEST_runnow. enqueueJob marks every *_test job
// with payload.test = true, which claim_job skips, so the live worker never takes one (the admin-inserted rows carry it too). Rows are removed in `finally`.
// Run: node --env-file=.env.local --env-file=../.env --import tsx scripts/verify_runnow.mts
import { createClient } from "@supabase/supabase-js";
import { supabase } from "../lib/supabase";
import { enqueueApply, enqueueGuarded, enqueueJobOnce, enqueuePreview } from "../lib/actions";

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
  await admin.from("jobs").delete().in("kind", ["import-sheet_test", "draft_test", "followups_test"]);
};
// hoursOld 0 leaves created_at to the database clock, so a later apply (also database time) is ordered after it whatever this machine's clock says.
const doneJob = (kind: string, argv: string[], hoursOld = 0) => admin.from("jobs").insert({
  kind, status: "done", payload: { argv, test: true }, result: { output: "dry run" }, finished_at: new Date().toISOString(),
  ...(hoursOld ? { created_at: new Date(Date.now() - hoursOld * 3600_000).toISOString() } : {}),
});

try {
  await clear();
  const g = await admin.auth.admin.generateLink({ type: "magiclink", email: "soban@kodoai.xyz" });
  await supabase.auth.verifyOtp({ token_hash: g.data.properties!.hashed_token, type: "magiclink" });

  // Apply needs a done preview: none yet.
  check("enqueueApply with no preview throws 'no done preview for this argv'", (await throws(enqueueApply(KIND, ARGV))) === "no done preview for this argv");
  check("  ...and inserted nothing", (await rows(KIND, ARGV)).length === 0);

  // A failed preview does not unlock Apply.
  await admin.from("jobs").insert({ kind: KIND, status: "failed", payload: { argv: ARGV, test: true }, error: "boom", finished_at: new Date().toISOString() });
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
  check("  ...and the _test job carries payload.test = true (the live worker's claim skips it)", applied[0].payload.test === true);
  check("enqueueApply twice: the second is refused, one preview unlocks one Apply", (await throws(enqueueApply(KIND, ARGV))) === "preview already applied: run a new preview" && (await exact(KIND, [...ARGV, "--confirm"])).length === 1);
  await admin.from("jobs").update({ status: "done" }).eq("id", applied[0].id);
  check("  ...still refused once that apply is done", (await throws(enqueueApply(KIND, ARGV))) === "preview already applied: run a new preview");
  await admin.from("jobs").update({ status: "failed", error: "boom" }).eq("id", applied[0].id);
  check("  ...and once it failed (retry it from the Jobs table instead)", (await throws(enqueueApply(KIND, ARGV))) === "preview already applied: run a new preview" && (await exact(KIND, [...ARGV, "--confirm"])).length === 1);
  await doneJob(KIND, ARGV); // a new done preview, created after the apply
  check("  ...a new done preview unlocks Apply again", (await throws(enqueueApply(KIND, ARGV))) === "" && (await exact(KIND, [...ARGV, "--confirm"])).length === 2);
  check("enqueueApply refuses argv that already has --confirm or an abbreviation", (await throws(enqueueApply(KIND, [...ARGV, "--conf"]))) !== "");
  check("enqueueApply refuses a kind without a dry run", (await throws(enqueueApply("clean_test", ARGV))) !== "");

  // Preview never carries --confirm; a second identical preview is refused while the first is open.
  await admin.from("jobs").delete().like("payload->>argv", `%TEST_runnow%`).contains("payload", { argv: ["--confirm"] }); // drop every apply row (queued and failed)
  check("enqueuePreview with --confirm throws", (await throws(enqueuePreview(KIND, [...ARGV, "--confirm"]))) !== "");
  check("enqueuePreview with --conf throws", (await throws(enqueuePreview(KIND, [...ARGV, "--conf"]))) !== "");
  check("  ...and inserted nothing", (await rows(KIND, [...ARGV, "--confirm"])).length === 0 && (await rows(KIND, [...ARGV, "--conf"])).length === 0);
  check("enqueuePreview inserts one queued job", (await throws(enqueuePreview(KIND, ARGV))) === "" && (await exact(KIND, ARGV)).filter((r) => r.status === "queued").length === 1);
  check("  ...carrying payload.test = true", (await exact(KIND, ARGV)).filter((r) => r.status === "queued").every((r) => r.payload.test === true));
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

  // Two tabs, or the UI and the autopilot, are two processes: only the unique index on open jobs (migration 0016) can admit one of two inserts racing to the database.
  await clear();
  const XP = ["--batch", `${TAG}_xp`];
  const race = await Promise.all([1, 2].map(() => admin.from("jobs").insert({ kind: KIND, payload: { argv: XP, test: true } })));
  check("two racing inserts of an identical open job: the database keeps exactly one row", (await exact(KIND, XP)).length === 1);
  check("  ...and refuses the other with 23505", race.filter((r) => r.error?.code === "23505").length === 1);
  await admin.from("jobs").update({ status: "paused_budget" }).eq("kind", KIND).contains("payload", { argv: XP });
  check("a paused_budget twin does not block a new job (autopilot retries a capped pass)", !(await admin.from("jobs").insert({ kind: KIND, payload: { argv: XP, test: true } })).error);

  // Draft buttons (drafts/send pages): draftBatch and draftFollowups are enqueueJobOnce("draft", ["--batch-no", N]) and
  // enqueueJobOnce("followups", []). Real kinds are paid passes, so the same call shape is run on the *_test kinds.
  const DRAFT = ["--batch-no", `${TAG}_n`];
  check("draft_test --batch-no: first enqueue inserts one queued job", (await throws(enqueueJobOnce("draft_test", DRAFT))) === "" && (await exact("draft_test", DRAFT)).filter((r) => r.status === "queued").length === 1);
  check("draft_test --batch-no: an identical open job is refused ('already open')", (await throws(enqueueJobOnce("draft_test", DRAFT))).includes("already open") && (await exact("draft_test", DRAFT)).length === 1);
  check("followups_test []: first enqueue inserts one queued job", (await throws(enqueueJobOnce("followups_test", []))) === "" && (await admin.from("jobs").select("id").eq("kind", "followups_test").eq("status", "queued")).data!.length === 1);
  check("followups_test []: an identical open job is refused ('already open')", (await throws(enqueueJobOnce("followups_test", []))).includes("already open") && (await admin.from("jobs").select("id").eq("kind", "followups_test")).data!.length === 1);
} finally {
  await clear();
}
console.log(fails.length ? `${fails.length} FAILED` : "all ok");
process.exit(fails.length ? 1 : 0);
