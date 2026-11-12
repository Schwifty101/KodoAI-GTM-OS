// Dev check: a signed-in user who is NOT the operator must see and change nothing. Creates and deletes a throwaway user.
// Run: node --env-file=.env.local --env-file=../.env --import tsx scripts/rls_intruder.mts
import { createClient } from "@supabase/supabase-js";

const url = process.env.NEXT_PUBLIC_SUPABASE_URL!;
const admin = createClient(url, process.env.SUPABASE_SECRET_KEY!);
const intruder = createClient(url, process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY!);
const email = "rls-intruder-test@example.com";
const fails: string[] = [];
const check = (name: string, cond: boolean) => { console.log(cond ? "ok  " : "FAIL", name); if (!cond) fails.push(name); };

const { data: batch } = await admin.from("batches").insert({ name: "TEST rls" }).select("id").single();
await admin.from("leads").insert({ place_id: "TEST_rls1", name: "Spa", status: "selected", batch_id: batch!.id });
await admin.from("suppression").insert({ domain: "rls-test.example", reason: "pytest-rls" });
const { data: made } = await admin.auth.admin.createUser({ email, email_confirm: true });
const g = await admin.auth.admin.generateLink({ type: "magiclink", email });
const v = await intruder.auth.verifyOtp({ token_hash: g.data.properties!.hashed_token, type: "magiclink" });
check("intruder is genuinely signed in", v.data.user?.email === email);

const leads = await intruder.from("leads").select("id");
check("signed-in non-operator reads 0 leads", (leads.data ?? []).length === 0);
const sup = await intruder.from("suppression").select("id");
check("signed-in non-operator reads 0 suppression rows", (sup.data ?? []).length === 0);
const view = await intruder.from("batch_metrics").select("batch_id");
check("signed-in non-operator reads 0 rows from the metrics view", (view.data ?? []).length === 0);
await admin.from("settings").upsert({ key: "weekly_target", value: 200 });
await admin.from("jobs").insert({ kind: "clean", payload: { test: true } });
for (const t of ["settings", "jobs", "spend_summary"]) check(`non-operator reads 0 rows from ${t}`, ((await intruder.from(t).select("*")).data ?? []).length === 0);
check("non-operator cannot insert into settings", !!(await intruder.from("settings").insert({ key: "zz_intruder", value: 1 })).error);
check("non-operator cannot insert into jobs", !!(await intruder.from("jobs").insert({ kind: "clean", payload: { test: true } })).error);
const ins = await intruder.from("suppression").insert({ domain: "evil.example", reason: "pytest-rls" });
check("non-operator cannot insert into suppression", !!ins.error);
await intruder.from("leads").update({ status: "booked" }).eq("place_id", "TEST_rls1");
await intruder.from("suppression").delete().eq("domain", "rls-test.example");
const still = await admin.from("leads").select("status").eq("place_id", "TEST_rls1").single();
const supStill = await admin.from("suppression").select("id").eq("domain", "rls-test.example");
check("non-operator update changed nothing", still.data?.status === "selected");
check("non-operator delete removed nothing", (supStill.data ?? []).length === 1);

await admin.from("jobs").delete().eq("payload->>test", "true");
await admin.from("leads").delete().like("place_id", "TEST_rls%");
await admin.from("suppression").delete().eq("reason", "pytest-rls");
await admin.from("batches").delete().eq("id", batch!.id);
if (made.user) await admin.auth.admin.deleteUser(made.user.id);
console.log(fails.length ? `${fails.length} FAILED` : "all ok");
process.exit(fails.length ? 1 : 0);
