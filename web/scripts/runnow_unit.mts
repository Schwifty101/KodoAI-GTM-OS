// Pure-logic checks for web/lib/runnow.ts. No database, no network.
// Run: cd web && npx tsx scripts/runnow_unit.mts
import assert from "node:assert/strict";
import { CONFIRM_KINDS, alreadyApplied, baseKind, enrichEstimate, findPreview, isApplyOf, isConfirmFlag, jobPayload, lastRun, newestApply, sameArgv, stepState, type JobRow } from "../lib/runnow";

const NOW = new Date("2026-11-25T12:00:00Z");
const hoursAgo = (h: number) => new Date(NOW.getTime() - h * 3600_000).toISOString();
let n = 0;
const job = (kind: string, status: string, argv: string[], created_at: string): JobRow => ({
  id: `j${++n}`, kind, status, payload: { argv }, result: null, error: null, created_at, finished_at: null,
});

// findPreview
const ARGV = ["--batch", "B1"];
assert.equal(findPreview([job("verify-sheet", "failed", ARGV, hoursAgo(1))], "verify-sheet", ARGV, NOW), undefined, "failed job is not a preview");
assert.equal(findPreview([job("verify-sheet", "cancelled", ARGV, hoursAgo(1))], "verify-sheet", ARGV, NOW), undefined, "cancelled job is not a preview");
assert.equal(findPreview([job("verify-sheet", "queued", ARGV, hoursAgo(1))], "verify-sheet", ARGV, NOW), undefined, "queued job is not a preview yet");
assert.equal(findPreview([job("verify-sheet", "done", ["--batch", "B2"], hoursAgo(1))], "verify-sheet", ARGV, NOW), undefined, "different batch id");
assert.equal(findPreview([job("verify-sheet", "done", [...ARGV, "--limit", "5"], hoursAgo(1))], "verify-sheet", ARGV, NOW), undefined, "extra flag");
assert.equal(findPreview([job("sheet-queue", "done", ARGV, hoursAgo(1))], "verify-sheet", ARGV, NOW), undefined, "different kind");
assert.equal(findPreview([job("verify-sheet", "done", ARGV, hoursAgo(25))], "verify-sheet", ARGV, NOW), undefined, "25 h old");
assert.equal(findPreview([job("verify-sheet", "done", [...ARGV, "--confirm"], hoursAgo(1))], "verify-sheet", [...ARGV, "--confirm"], NOW), undefined, "an apply job is never a preview");
assert.equal(findPreview([job("verify-sheet", "done", [...ARGV, "--conf"], hoursAgo(1))], "verify-sheet", [...ARGV, "--conf"], NOW), undefined, "an abbreviated --conf is an apply too");
const older = job("verify-sheet", "done", ARGV, hoursAgo(5));
const newer = job("verify-sheet", "done", ARGV, hoursAgo(2));
assert.equal(findPreview([older, newer, job("verify-sheet", "failed", ARGV, hoursAgo(1))], "verify-sheet", ARGV, NOW), newer, "newest done one");
assert.equal(findPreview([newer, older], "verify-sheet", ARGV, NOW), newer, "order of input does not matter");
assert.equal(findPreview([job("import-sheet", "done", [], hoursAgo(23))], "import-sheet", [], NOW)?.kind, "import-sheet", "empty argv, 23 h old is fine");

// alreadyApplied: one preview unlocks one Apply
const CONF = [...ARGV, "--confirm"];
const prev = job("verify-sheet", "done", ARGV, hoursAgo(5));
assert.equal(alreadyApplied([prev], "verify-sheet", ARGV, prev), false, "no apply yet");
for (const st of ["queued", "running", "done", "failed", "cancelled", "paused_budget"])
  assert.equal(alreadyApplied([prev, job("verify-sheet", st, CONF, hoursAgo(4))], "verify-sheet", ARGV, prev), true, `an apply that is ${st} spends the preview`);
assert.equal(alreadyApplied([prev, job("verify-sheet", "done", CONF, hoursAgo(6))], "verify-sheet", ARGV, prev), false, "an apply from before the preview does not");
const again = [prev, job("verify-sheet", "done", CONF, hoursAgo(4)), job("verify-sheet", "done", ARGV, hoursAgo(2))];
assert.equal(alreadyApplied(again, "verify-sheet", ARGV, findPreview(again, "verify-sheet", ARGV, NOW)!), false, "a newer done preview unlocks Apply again");
assert.equal(alreadyApplied([prev, job("verify-sheet", "queued", ["--confirm", "--batch", "B1"], hoursAgo(4))], "verify-sheet", ARGV, prev), true, "--confirm in any position counts");
assert.equal(alreadyApplied([prev, job("verify-sheet", "queued", [...ARGV, "--conf"], hoursAgo(4))], "verify-sheet", ARGV, prev), true, "an abbreviated --conf counts");
assert.equal(alreadyApplied([prev, job("verify-sheet", "done", ["--batch", "B2", "--confirm"], hoursAgo(4))], "verify-sheet", ARGV, prev), false, "another batch's apply");
assert.equal(alreadyApplied([prev, job("verify-sheet", "done", [...ARGV, "--limit", "5", "--confirm"], hoursAgo(4))], "verify-sheet", ARGV, prev), false, "an apply with an extra flag is a different run");
assert.equal(alreadyApplied([prev, job("sheet-queue", "done", CONF, hoursAgo(4))], "verify-sheet", ARGV, prev), false, "another kind's apply");
assert.equal(alreadyApplied([prev, job("verify-sheet", "done", ARGV, hoursAgo(4))], "verify-sheet", ARGV, prev), false, "another preview is not an apply");
// isApplyOf / newestApply
assert.ok(isApplyOf(job("verify-sheet", "done", CONF, hoursAgo(1)), "verify-sheet", ARGV));
assert.ok(!isApplyOf(job("verify-sheet", "done", ARGV, hoursAgo(1)), "verify-sheet", ARGV), "a preview is not an apply");
assert.ok(isApplyOf(job("import-sheet", "done", ["--confirm"], hoursAgo(1)), "import-sheet", []), "empty argv + --confirm");
const ap1 = job("verify-sheet", "failed", CONF, hoursAgo(4)), ap2 = job("verify-sheet", "queued", CONF, hoursAgo(1));
assert.equal(newestApply([ap1, ap2, prev], "verify-sheet", ARGV), ap2, "newest apply, previews skipped");
assert.equal(newestApply([prev], "verify-sheet", ARGV), undefined);

// jobPayload: only `_test` kinds carry the marker claim_job skips; findPreview/stepState read argv only
assert.deepEqual(jobPayload("enrich_test", ["--batch", "B1"]), { argv: ["--batch", "B1"], test: true });
assert.deepEqual(jobPayload("verify-sheet_test", []), { argv: [], test: true });
assert.deepEqual(jobPayload("enrich", ["--batch", "B1"]), { argv: ["--batch", "B1"] });
assert.ok(!("test" in jobPayload("sheet-paint", [])), "a real kind never carries test");
assert.ok(!("test" in jobPayload("test_enrich", [])), "only the suffix counts");
const marked: JobRow = { ...job("verify-sheet_test", "done", ARGV, hoursAgo(1)), payload: jobPayload("verify-sheet_test", ARGV) };
assert.equal(findPreview([marked], "verify-sheet_test", ARGV, NOW), marked, "a test marker does not break the preview match");
assert.ok(sameArgv(marked.payload.argv ?? [], ARGV));

// stepState
const ORDER = ["import", "clean", "verify-sheet", "enrich", "signals", "select"];
const none: JobRow[] = [];
assert.deepEqual(stepState(ORDER, "clean", none, "B1"), { enabled: false, why: "import not done" });
assert.deepEqual(stepState(ORDER, "clean", none, "B1", true), { enabled: true }, "sheet import counts as import done");
assert.deepEqual(stepState(ORDER, "clean", [job("import-sheet", "done", ["--batch", "B1"], hoursAgo(1))], "B1"), { enabled: true }, "done import job");
assert.equal(stepState(ORDER, "clean", [job("import-sheet", "done", ["--batch", "B2"], hoursAgo(1))], "B1").enabled, false, "other batch's job");
assert.equal(stepState(ORDER, "clean", [job("import-sheet", "failed", ["--batch", "B1"], hoursAgo(1))], "B1").enabled, false, "failed job does not unlock");
assert.deepEqual(stepState(ORDER, "enrich", [job("clean", "done", ["--batch", "B1"], hoursAgo(1))], "B1"), { enabled: false, why: "verify-sheet not done" });
assert.equal(stepState(ORDER, "enrich", [job("verify-sheet", "done", ["--batch", "B1", "--confirm"], hoursAgo(1))], "B1").enabled, true, "previous step done");
assert.equal(stepState(ORDER, "select", [job("signals_test", "done", ["--batch", "B1"], hoursAgo(1))], "B1").enabled, true, "_test kinds count (browser check drives it)");
assert.equal(stepState(ORDER, "import", none, "B1").enabled, true, "first step has no gate");

// baseKind, sameArgv, CONFIRM_KINDS
assert.equal(baseKind("verify-sheet_test"), "verify-sheet");
assert.equal(baseKind("verify-sheet"), "verify-sheet");
assert.equal(baseKind("a_test_test"), "a_test", "strips one suffix only");
assert.ok(sameArgv(["--batch", "x"], ["--batch", "x"]));
assert.ok(!sameArgv(["--batch", "x"], ["--batch", "y"]));
assert.ok(!sameArgv(["a", "b"], ["b", "a"]), "order matters");
assert.deepEqual(CONFIRM_KINDS, ["import-sheet", "verify-sheet", "sheet-queue", "sheet-paint"]);

// isConfirmFlag: argparse accepts any unambiguous prefix, so --conf must count as --confirm
for (const a of ["--confirm", "--confirm=1", "--conf", "--con", "--c"]) assert.ok(isConfirmFlag(a), a);
for (const a of ["--", "-c", "--batch", "--limit", "--tab", "B1", "--confirmed", "--cx", ""]) assert.ok(!isConfirmFlag(a), a);

// lastRun
const a = job("sheet-queue", "done", [], hoursAgo(9));
const b = job("sheet-queue", "failed", [], hoursAgo(3));
assert.equal(lastRun([a, b, job("sheet-paint", "done", [], hoursAgo(1))], "sheet-queue"), b, "newest by created_at, own kind only");
assert.equal(lastRun([b, a], "sheet-queue"), b);
assert.equal(lastRun([], "sheet-queue"), undefined);

// enrichEstimate
assert.deepEqual(enrichEstimate(40, 0.5), { leads: 40, credits: 20 });
assert.deepEqual(enrichEstimate(0, 1), { leads: 0, credits: 0 });
assert.deepEqual(enrichEstimate(3, 0.1), { leads: 3, credits: 0.3 }, "no float noise");

console.log("runnow_unit: all asserts passed");
