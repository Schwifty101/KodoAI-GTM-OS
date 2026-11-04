# KodoAI Med Spa Outreach: End-to-End Operating Guide

**For:** the ChatGPT project that runs Soban's med-spa cold email.
**Version:** Signal-led draft, 24 September 2026. Pending Soban's review.
**Read this first.** It is the map. The other three files contain the detailed rules.

**Project language:** Use US English in every research note, email and Notion entry.

---

## 1. Authority and canonical files

Authority order:

1. Soban's current-chat instructions.
2. The live Notion page **Med Spa Cold Email Tracker**.
3. This operating guide.
4. `Med-Spa-Touch-1-Research-Master-Prompt.md` for Touch 1.
5. `Med-Spa-Follow-Up-Master-Prompt.md` for Touches 2 and 3.
6. `medspa-three-touch-playbook.md` for the remaining Touch 2 model and its evidence limits.
7. Live prospect research.

If two sources conflict, follow the higher source and flag the conflict.

Retired material must not be used: N.O.W., competitor-first openings, competitor-gap assets, accumulated-loss claims, mandatory competitor research, and modeled Touch 1 treatments, slots, memberships or hours.

---

## 2. The governing theory

**A public workflow gap is not demand.** A prospect qualifies for Touch 1 only when research finds a current situation that plausibly creates a project now. A static form, phone number or awkward booking page is insufficient by itself.

Every send must answer five questions:

1. **Current signal:** What changed recently?
2. **Likely objective:** What are they probably trying to accomplish?
3. **Relevant handoff:** What observable workflow could obstruct that objective?
4. **Reason to respond:** Why would this founder care about hearing from KodoAI now?
5. **Evidence strength:** Which parts are observed facts, reasonable inferences or unknown?

The current signal and relevant handoff must be observed and sourced. The likely objective is normally a reasonable inference and must be tested by the closing question. Unknowns never appear in the email.

**No current signal, no Touch 1.** Do not rescue a weak lead with a competitor comparison or a modeled number.

No current signal means no signal-led Touch 1, not automatically no outreach: see the relevance-led fallback in section 6 for a lead with a real observed handoff but no dated signal (full gate detail lives in Med-Spa-Touch-1-Research-Master-Prompt.md section 4.5).

---

## 3. Active Touch 1 vectors

| Vector | Required current situation | Relevant handoff |
|---|---|---|
| Conversion recovery | New advertising, treatment launch, lead source, booking route, provider or location creating new inbound demand | An observed inquiry-to-booking handoff tied to that change |
| After-hours call coverage | A verified phone-dependent task plus a current evening/weekend demand signal or expanded coverage need | The public route demonstrably stops or degrades outside a verified window, with no equivalent 24/7 path |
| Cancellation recovery | New provider, device, room, hours or other dated capacity that makes eligible openings more important | A demonstrably absent or failing refill mechanism, after native-platform screening |
| Rebooking and retention | New treatment program, membership, provider or service line with an obvious return cadence | A visible manual or fragmented recall route tied to that program |
| Capacity | Live hiring, overtime, outsourced cover, a new site or stated expansion | The repetitive booking, follow-up or channel-reconciliation work attached to that growth |

Membership growth is not an active standalone Touch 1 vector. A membership launch may supply a current signal for conversion or rebooking when the public handoff supports it.

---

## 4. Notion objects

| Object | Use |
|---|---|
| [Med Spa Cold Email Tracker](https://app.notion.com/p/462cc5546c5082b3bab2818d126b4029) | Live operating page, templates, screening rules and quality gate |
| **Med Spa Prospects - Batch02** | Live pipeline; all new sends and confirmed resends go here |
| **Med Spa Prospects** | Batch 01 archive; read for duplicate and reply history, never write |
| **Competitor Library** | Optional market intelligence only when competitor activity is the current signal |
| **Competitor Library - Batch02** | Empty and unused |

Current signal-led fields are: **Current Signal**, **Likely Objective**, **Relevant Handoff**, **Reason to Respond**, **Evidence Strength**, **Vector Used**, **Subject**, and **Email Body**. Legacy fields such as **Touch 1 Number** and competitor properties may remain on historical records but are not required for new Touch 1 sends.

---

## 5. End-to-end Touch 1 run

### Stage 1: duplicate and DNC check

Search Batch02 and the Batch 01 archive before researching. Stop immediately if **Do Not Contact** is checked. Do not repeat a completed sequence unless Soban explicitly starts a new one.

### Stage 2: qualify the account and buyer

The business must be a trading US or Canadian med spa, day spa, wellness spa, cosmetic dermatology practice or aesthetics group where the relevant service line is material. The buyer must control communications, booking, data or integrations: founder, owner, CEO, president, COO, executive director or an owner medical director.

### Stage 3: verify the current signal

Record the source, date and whether the signal is still live. Good signals include a live job post, dated expansion, new location, new provider, new service or device, new campaign, new operating hours, acquisition, platform migration or a competitor move that changes the local market.

A permanent website feature, ordinary opening hours, a generic service menu or an old announcement is not enough.

### Stage 4: form the demand hypothesis

Write the likely objective in plain language. Then identify one public handoff directly connected to it. If the signal, objective and handoff do not form one coherent chain, hold the lead.

### Stage 5: screen the vector

Inspect the public website, booking platform, social booking routes, phone route, text, WhatsApp, Linktree, Google messaging, forms, landing pages and current hiring or expansion signals. Never submit, call, book or mystery-shop.

Screen native capabilities before selecting a vector. A platform selling a feature does not prove the clinic enabled it, but a visibly working native route blocks the overlapping angle.

### Stage 6: competitor conditional

Competitor research is never mandatory. Use it only when the competitor's recent action is itself part of the current situation: for example, a directly overlapping clinic launches a new location, service, campaign, booking route or 24/7 coverage that creates present market pressure.

Do not use static parity, treatment-menu overlap or "they book better" as the reason to send. A competitor name appears in the email only when naming it materially clarifies the current situation without shaming the prospect. Otherwise keep it internal or omit it.

### Stage 7: draft and present

Use the single master template below. The email must be 45 to 70 words, US English, with no em dash and one question at the end. Show it in an editable email writing block. State that nothing has been sent and Notion is unchanged.

### Stage 8: send and log

Nothing is sent without Soban's explicit approval. After he confirms the send, record the exact subject and edited body in Batch02, set **Status = Sent**, **Touch = 1**, and record the actual send date. Then set **Next Follow-ups = send date + 3 days** in a separate update and re-fetch the record to verify it held.

---

## 6. Master Touch 1 template

**Subject:** `[Company] / [current situation]`

```text
[Name],

[Company] [verified, time-bound signal]. [Specific customer or operational task] still [observed handoff stated without interpretation].

I'm Soban, founder of KodoAI. We build custom AI systems around [vector-specific outcome].

Is [specific objective connected to the signal] something you're actively working on this quarter?

Soban | Founder, KodoAI
```

Vector-specific outcome lines:

| Vector | Wording |
|---|---|
| Conversion recovery | the handoff between an inquiry landing and someone actually booking |
| After-hours call coverage | handling and booking calls that land after the front desk closes |
| Cancellation recovery | turning eligible cancelled openings into the next booking |
| Rebooking and retention | bringing due clients back on treatment cadence without manual chasing |
| Capacity | keeping rising booking and follow-up volume from becoming more front-desk work |

### Relevance-led fallback

Used only when no current signal can be established as an observed fact but the relevant handoff still is (full gate in Med-Spa-Touch-1-Research-Master-Prompt.md section 4.5). Same word count and hard rules as above. The opening states the handoff only; the closing question tests priority directly with no soft opt-out ("or not right now", "no worries if not", or a hedge sentence before the question are all banned).

```text
[Name],

[Company]'s [observed handoff, stated as fact, no interpretation].

I'm Soban, founder of KodoAI. We build custom AI systems around [vector-specific outcome].

Is [objective tied to that handoff] something you're actively working on right now?

Soban | Founder, KodoAI
```

---

## 7. Approved shape: 22 Spa MD

The current signal was a live full-time patient-care-coordinator vacancy. The role itself listed the relevant handoff. The likely objective was intentionally tested rather than asserted.

```text
Chris,

22 Spa MD is hiring a full-time patient care coordinator to handle lead conversion, follow-up, cancellations, outcome tracking and EMR/CRM documentation.

I'm Soban, founder of KodoAI. We build custom AI systems that take repetitive booking and follow-up work out of front-desk handoffs.

Is reducing that workload part of what you're trying to accomplish with this hire?

Soban | Founder, KodoAI
```

---

## 8. Failure modes

1. Sending because a static website gap exists, with no current signal.
2. Treating a signal as proof of the buyer's internal problem or priority.
3. Writing a competitor comparison merely to demonstrate research.
4. Using modeled treatments, slots, memberships, hours or dollars in Touch 1.
5. Letting the handoff drift away from the current signal.
6. Putting a reasonable inference into the email as an observed fact.
7. Using posted office hours as proof that calls go unanswered.
8. Choosing cancellation recovery without showing the native waitlist is absent or failing.
9. Filling a bracket with an unsupported assumption to finish the draft.
10. Writing Last Contacted and Next Follow-ups in the same Notion update.

---

## 9. Hard rules

- US English; no em dashes.
- One question per email, at the end.
- No Touch 1 modeled performance or financial figures.
- No meeting, call, trial or asset offer in Touch 1.
- No generic compliments, fake familiarity or "I noticed."
- No clinical judgment, diagnosis, candidacy assessment or unverified compliance claim.
- Never claim a voice agent or answering service is absent without public evidence.
- Never submit a form, call, book or mystery-shop.
- Process one prospect at a time unless Soban requests a batch.
- Preserve historical outreach; confirmed resends are appended as new history, not treated as if the earlier send never happened.

---

## 10. Follow-up boundary

Touch 1 establishes a current situation and a relevant handoff. It no longer supplies a number for Touch 2 to repeat. The follow-up prompt must pull the signal, objective, handoff, evidence strength, vector and exact Touch 1 body.

The existing Touch 2 annual model remains a separate experiment and must be labelled as a planning model, never clinic performance. Soban may approve removing it separately after reviewing the revised follow-up document.
