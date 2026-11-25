// Pure-logic checks for web/lib/runnow.ts. No database, no network.
// Run: cd web && npx tsx scripts/runnow_unit.mts
import assert from "node:assert/strict";
import { CONFIRM_KINDS, baseKind, enrichEstimate, findPreview, lastRun, sameArgv, stepState, type JobRow } from "../lib/runnow";

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
const older = job("verify-sheet", "done", ARGV, hoursAgo(5));
const newer = job("verify-sheet", "done", ARGV, hoursAgo(2));
assert.equal(findPreview([older, newer, job("verify-sheet", "failed", ARGV, hoursAgo(1))], "verify-sheet", ARGV, NOW), newer, "newest done one");
assert.equal(findPreview([newer, older], "verify-sheet", ARGV, NOW), newer, "order of input does not matter");
assert.equal(findPreview([job("import-sheet", "done", [], hoursAgo(23))], "import-sheet", [], NOW)?.kind, "import-sheet", "empty argv, 23 h old is fine");

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
