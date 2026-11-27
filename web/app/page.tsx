"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { useRequireSession } from "@/lib/useRequireSession";
import { useSettings } from "@/lib/useSettings";
import { BATCH_SIZE } from "@/lib/batches";
import { budgetMeter, creditStatus, nextAction } from "@/lib/home";
import { loadHome, type HomeData } from "@/lib/homeData";
import { hint0017 } from "@/lib/metrics";

const usd = (n: number) => `$${n.toFixed(2)}`;
const num = (v: unknown) => Number(v) || 0;
const english = (d: Date, o: Intl.DateTimeFormatOptions) => d.toLocaleDateString("en-GB", o);
const dayLabel = (d: Date) => `${english(d, { weekday: "short" })} ${d.getDate()} ${english(d, { month: "short" })} ${d.getFullYear()}`;

export default function Home() {
  const ready = useRequireSession();
  const { vals, err: settingsErr } = useSettings(ready);
  const defaults = useRef(vals); // useSettings starts on the built-in defaults and swaps in a new object once the stored settings arrive
  const [data, setData] = useState<(HomeData & { now: Date }) | null>(null);
  const [err, setErr] = useState("");
  useEffect(() => {
    if (!ready) return;
    const now = new Date();
    loadHome(now).then((d) => { setErr(""); setData({ ...d, now }); }, (e) => setErr(hint0017((e as Error).message)));
  }, [ready]);
  if (!ready) return null;

  const loaded = data !== null && vals !== defaults.current; // budget and credit need the owner's settings, not the built-in ones
  const prices = { hunter: num(vals.price_hunter_usd_per_credit), prospeo: num(vals.price_prospeo_usd_per_credit), serper: num(vals.price_serper_usd_per_credit) };
  const credit = data && creditStatus({ credit_end_date: String(vals.credit_end_date), credit_balance_usd: num(vals.credit_balance_usd), credit_balance_as_of: String(vals.credit_balance_as_of) }, data.geminiSince, data.now);
  const meter = data && credit && budgetMeter(data.monthSpend, credit.ended, { monthly_budget_pkr: num(vals.monthly_budget_pkr), pkr_per_usd: num(vals.pkr_per_usd) }, prices);
  const warns = [credit?.warn, meter?.pct != null && meter.pct >= 100 ? `Over the monthly budget (${meter.pct.toFixed(0)}%)` : null].filter((w): w is string => !!w);
  const next = data && nextAction(data.counts);
  const y = data?.yesterday;
  const batch = data?.counts.batch;

  return (
    <>
      <h1>Home</h1>
      {(err || settingsErr) && <p className="err">{err || settingsErr}</p>}
      {!data ? !err && <p className="muted">Loading…</p> : (
        <>
          <div className="card">
            <strong>Next:</strong> <Link href={next!.href}>{next!.text}</Link>
          </div>
          <div className="grid">
            <div className="card">
              <h2>Yesterday</h2>
              <p className="muted">{dayLabel(new Date(data.now.getFullYear(), data.now.getMonth(), data.now.getDate() - 1))} (local time)</p>
              <p><strong>{y!.scraped}</strong> scraped, of which <strong>{y!.owners}</strong> verified owners</p>
              <p><strong>{y!.numbered}</strong> numbered into a batch</p>
              <p><strong>{y!.touch1}</strong> Touch 1 sent, <strong>{y!.followups}</strong> follow-ups sent</p>
            </div>
            <div className="card">
              <h2>Open batch</h2>
              <p>{batch ? `Batch ${String(batch.no).padStart(2, "0")}: ${batch.fill} of ${BATCH_SIZE}` : "No batch open"}</p>
              <p>Autopilot: {data.autopilot} <span className={`pill ${vals.autopilot_on === true ? "ok" : ""}`}>{vals.autopilot_on === true ? "on" : "off"}</span></p>
            </div>
            <div className="card">
              <h2>Budget and credit</h2>
              {!loaded ? <p className="muted">Loading…</p> : (
                <>
                  <p>{usd(meter!.spentUsd)} of {usd(meter!.budgetUsd)} this month ({meter!.pct === null ? "n/a" : `${meter!.pct.toFixed(0)}%`})</p>
                  <p className="muted">PKR {Math.round(meter!.spentUsd * num(vals.pkr_per_usd)).toLocaleString("en-US")} of {num(vals.monthly_budget_pkr).toLocaleString("en-US")}</p>
                  {Object.entries(meter!.creditsUnpriced).map(([p, n]) => <p className="muted" key={p}>{p}: {n} credits unpriced</p>)}
                  <p>
                    {usd(credit!.remaining)} of {usd(num(vals.credit_balance_usd))} Google credit left, {credit!.daysLeft} days to the end date{" "}
                    <span className={`pill ${warns.length ? "bad" : "ok"}`}>{warns.length ? warns.join("; ") : "no warnings"}</span>
                  </p>
                </>
              )}
            </div>
          </div>
          <p><Link href="/metrics">Metrics</Link> · <Link href="/replies">Replies</Link></p>
        </>
      )}
    </>
  );
}
