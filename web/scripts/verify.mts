// Dev verification: seeds test rows, mints a one-off operator session, and runs the app's real write actions under RLS.
// Run: node --env-file=.env.local --env-file=../.env --import tsx scripts/verify.mts   (reads the secret key from ../.env; never bundled into the app)
import { createClient } from "@supabase/supabase-js";
import { supabase } from "../lib/supabase";
import { approveLeads, rejectLeads, unapproveLeads } from "../lib/actions";

const admin = createClient(process.env.NEXT_PUBLIC_SUPABASE_URL!, process.env.SUPABASE_SECRET_KEY!);
const fails: string[] = [];
const check = (name: string, cond: boolean) => { console.log(cond ? "ok  " : "FAIL", name); if (!cond) fails.push(name); };

const { data: batch } = await admin.from("batches").insert({ name: "TEST web verify" }).select("id").single();
const mk = (i: number, status: string) => ({ place_id: `TEST_v${i}`, name: `Spa ${i}`, status, batch_id: batch!.id, domain: `v${i}.com` });
await admin.from("leads").insert([mk(1, "selected"), mk(2, "selected"), mk(3, "selected"), mk(4, "sent")]);
const g = await admin.auth.admin.generateLink({ type: "magiclink", email: "soban@kodoai.xyz" });
await supabase.auth.verifyOtp({ token_hash: g.data.properties!.hashed_token, type: "magiclink" });

const row = async (n: number) => (await admin.from("leads").select("status,approved,reject_reason").eq("place_id", `TEST_v${n}`).single()).data!;
const id = async (n: number) => (await admin.from("leads").select("id").eq("place_id", `TEST_v${n}`).single()).data!.id as string;
const [a, b, c, d] = [await id(1), await id(2), await id(3), await id(4)];

await approveLeads([a, b, d]);
check("approve marks selected leads approved", (await row(1)).approved && (await row(2)).approved);
check("approve leaves a lead that is not `selected` alone", !(await row(4)).approved && (await row(4)).status === "sent");
await unapproveLeads([b]);
check("unapprove clears approval", !(await row(2)).approved);
await rejectLeads([c, d]);
const rc = await row(3);
check("reject sets status rejected, reason operator, not approved", rc.status === "rejected" && rc.reject_reason === "operator" && !rc.approved);
check("reject leaves a lead that is not `selected` alone", (await row(4)).status === "sent");

await admin.from("leads").delete().like("place_id", "TEST_v%");
await admin.from("batches").delete().eq("id", batch!.id);
console.log(fails.length ? `${fails.length} FAILED` : "all ok");
process.exit(fails.length ? 1 : 0);
