// Pure-logic checks for web/lib/home.ts and web/lib/replies.ts. No database, no network.
// Run: cd web && npx tsx scripts/home_unit.mts (also under TZ=Asia/Karachi and TZ=America/Los_Angeles)
import { budgetMeter, creditStatus, dayRange, nextAction, type HomeCounts } from "../lib/home";
import { gmailThreadUrl, replyBucket } from "../lib/replies";
import type { Prices } from "../lib/metrics";

let failed = 0;
function check(name: string, cond: boolean) {
  if (cond) console.log(`ok ${name}`);
  else { failed++; console.log(`FAIL ${name}`); }
}

// dayRange: local calendar days
const noon = new Date(2026, 10, 26, 12, 0, 0); // 2026-11-26 12:00 local
const y = dayRange(noon, 1);
check("dayRange: yesterday is the previous local calendar day",
  y.from === new Date(2026, 10, 25).toISOString() && y.to === new Date(2026, 10, 26).toISOString()
  && dayRange(noon, 0).from === y.to && dayRange(noon, 0).to === new Date(2026, 10, 27).toISOString());
if (process.env.TZ === "America/Los_Angeles") {
  const d = dayRange(new Date(2026, 10, 2, 12, 0, 0), 1); // Sunday 2026-11-01: clocks go back
  check("dayRange: 25 hours on the US fall-back day", (Date.parse(d.to) - Date.parse(d.from)) / 3_600_000 === 25);
} else console.log("skip dayRange: 25 hours on the US fall-back day (needs TZ=America/Los_Angeles)");

// creditStatus: UTC dates
const now = new Date("2026-11-26T15:00:00Z");
const day = (n: number) => new Date(now.getTime() + n * 86_400_000).toISOString().slice(0, 10);
const cv = (end: string, balance = 300) => ({ credit_end_date: end, credit_balance_usd: balance, credit_balance_as_of: "2026-11-01" });
const ok = creditStatus(cv(day(90)), 2, now);
check("creditStatus: 298 left with 90 days is not a warning", ok.remaining === 298 && ok.daysLeft === 90 && !ok.ended && ok.warn === null);
const low = creditStatus(cv(day(90)), 241, now); // 59 left = 19.7 percent
check("creditStatus: warns under 20 percent", low.remaining === 59 && !low.ended && !!low.warn && /20 percent/.test(low.warn)
  && creditStatus(cv(day(90)), 240, now).warn === null); // exactly 20 percent is not under
const soon = creditStatus(cv(day(13)), 2, now);
check("creditStatus: warns under 14 days", soon.daysLeft === 13 && !!soon.warn && /14 days/.test(soon.warn) && creditStatus(cv(day(14)), 2, now).warn === null);
const end = creditStatus(cv(day(0)), 2, now);
const used = creditStatus(cv(day(90)), 400, now);
check("creditStatus: ended on the end date", end.ended && end.daysLeft === 0 && !!end.warn && /ended/.test(end.warn)
  && creditStatus(cv(day(-3)), 2, now).daysLeft === 0 && !creditStatus(cv(day(1)), 2, now).ended
  && used.ended && used.remaining === 0 && !!used.warn);

// budgetMeter
const p0: Prices = { hunter: 0, prospeo: 0, serper: 0 };
const bv = { monthly_budget_pkr: 25000, pkr_per_usd: 276 };
const m0 = budgetMeter({}, false, bv, p0);
check("budgetMeter: 25000 PKR at 276 is a budget of 90.58 USD", m0.budgetUsd.toFixed(2) === "90.58" && m0.spentUsd === 0 && m0.pct === 0);
const spend = { apify: { units: 0, usd: 10 }, gemini: { units: 5000, usd: 4 } };
const before = budgetMeter(spend, false, bv, p0);
const after = budgetMeter(spend, true, bv, p0);
check("budgetMeter: Gemini counts only after the credit ended", before.spentUsd === 10 && after.spentUsd === 14
  && Math.abs(after.pct! - (14 / (25000 / 276)) * 100) < 1e-9);
const cr = { hunter: { units: 40, usd: 0 }, hunter_import: { units: 6, usd: 0 }, prospeo: { units: 0, usd: 0 }, serper: { units: 100, usd: 0 }, serper_maps: { units: 3, usd: 0 }, groq: { units: 9000, usd: 0 } };
const un = budgetMeter(cr, false, bv, { hunter: 0.1, prospeo: 0, serper: 0 });
check("budgetMeter: unpriced credits are listed, not guessed",
  JSON.stringify(un.creditsUnpriced) === JSON.stringify({ serper: 100, serper_maps: 3 }) && Math.abs(un.spentUsd - 4.6) < 1e-9
  && Object.keys(budgetMeter(cr, false, bv, { hunter: 1, prospeo: 1, serper: 1 }).creditsUnpriced).length === 0);
check("budgetMeter: budget 0 gives null pct", budgetMeter(spend, true, { monthly_budget_pkr: 0, pkr_per_usd: 276 }, p0).pct === null
  && budgetMeter(spend, true, { monthly_budget_pkr: 25000, pkr_per_usd: 0 }, p0).pct === null);

// nextAction
const none: HomeCounts = { replies: 0, mailboxPaused: null, approvedWhileOff: 0, followupsDrafted: 0, draftsWaiting: 0, selectedUnapproved: 0, batch: null };
const alone = (o: Partial<HomeCounts>) => nextAction({ ...none, ...o });
const a = [
  alone({ replies: 2 }), alone({ mailboxPaused: "bounce rate over 3%" }), alone({ approvedWhileOff: 5 }), alone({ followupsDrafted: 1 }),
  alone({ draftsWaiting: 8 }), alone({ selectedUnapproved: 12 }), alone({ batch: { no: 3, fill: 41 } }),
];
check("nextAction: each state alone",
  a.map((x) => x.href).join(" ") === "/replies /send /send /send /drafts /review /batches"
  && /^2 replies need/.test(a[0].text) && /bounce rate over 3%/.test(a[1].text) && /^5 approved emails/.test(a[2].text)
  && /^1 follow-up waiting/.test(a[3].text) && a[4].text === "8 drafts waiting for review" && /^12 selected leads/.test(a[5].text)
  && a[6].text === "Batch 03 is filling: 41 of 100" && /^1 reply needs/.test(alone({ replies: 1 }).text) && /^1 draft waiting/.test(alone({ draftsWaiting: 1 }).text));
const all: HomeCounts = { replies: 1, mailboxPaused: "x", approvedWhileOff: 1, followupsDrafted: 1, draftsWaiting: 1, selectedUnapproved: 1, batch: { no: 4, fill: 1 } };
const steps: Partial<HomeCounts>[] = [{ replies: 0 }, { mailboxPaused: null }, { approvedWhileOff: 0 }, { followupsDrafted: 0 }, { draftsWaiting: 0 }, { selectedUnapproved: 0 }];
const hrefs = ["/replies", "/send", "/send", "/send", "/drafts", "/review", "/batches"];
let cur = { ...all };
const seen = [nextAction(cur).href];
for (const s of steps) { cur = { ...cur, ...s }; seen.push(nextAction(cur).href); }
check("nextAction: replies beat everything and each later rule beats the next", seen.join(" ") === hrefs.join(" ")
  && nextAction(all).href === "/replies" && nextAction({ ...all, replies: 0 }).text.startsWith("Mailbox paused"));
const nw = nextAction(none);
check("nextAction: nothing waiting", nw.text === "Nothing waiting" && nw.href === "/leads");

// replyBucket
check("replyBucket: replied with no outcome or other needs a look", replyBucket("replied", null) === "look" && replyBucket("replied", "other") === "look");
check("replyBucket: replied positive is positive", replyBucket("replied", "positive") === "positive");
check("replyBucket: replied negative and unsubscribed are declined", replyBucket("replied", "negative") === "declined" && replyBucket("replied", "opt_out") === "declined"
  && replyBucket("unsubscribed", null) === "declined" && replyBucket("unsubscribed", "positive") === "declined" && replyBucket("sent", "negative") === "declined"
  && replyBucket("bounced", null) === "bounced" && replyBucket("sent", "bounce") === "bounced");
check("replyBucket: booked beats a positive outcome", replyBucket("booked", "positive") === "booked" && replyBucket("booked", null) === "booked" && replyBucket("booked", "negative") === "booked");
check("replyBucket: sent is null", replyBucket("sent", null) === null && replyBucket("drafted", null) === null && replyBucket("sent", "other") === null && replyBucket("selected", null) === null);

// gmailThreadUrl
check("gmailThreadUrl encodes the address", gmailThreadUrl("ann+kodo@x.com", "18c0ffee") === "https://mail.google.com/mail/?authuser=ann%2Bkodo%40x.com#all/18c0ffee");

if (failed) { console.log(`${failed} FAILED`); process.exit(1); }
