# Med Spa Cold Email: Three-Touch Playbook

**Version:** Signal-led and relevance-led sequence. Final as of October 10, 2026.
**Project language:** US English.

This document records the approved sequence logic. The live Notion page and the two master prompts control execution.

---

## 1. Sequence logic

| Touch | Timing | Job |
|---|---|---|
| Touch 1 | Day 0 | Use a verified current signal and handoff, or the approved relevance-led handoff fallback. Connect KodoAI's relevance and ask one priority question. No modeled treatments, appointments, memberships, hours or dollars. |
| Touch 2 | Day 3 | Send a short same-thread bump that resurfaces the original objective and asks whether it is active. |
| Touch 3 | Day 7 | State honest partner-fit criteria and ask one question about the original objective. No new prospect claim, number or offer. |

The three active Touch 1 vectors are:

1. Conversion recovery
2. Capacity, including after-hours call handling
3. Rebooking and retention

After-hours call coverage and Cancellation recovery are retired as standalone vectors. Historical rows keep those labels as history.

Membership is not an active standalone Touch 1 vector. Historical membership records remain valid history but do not define the current sequence.

---

## 2. Touch 1 research spine

Every prospect is evaluated through five fields:

1. **Current Signal:** What changed recently?
2. **Likely Objective:** What are they probably trying to accomplish?
3. **Relevant Handoff:** What observable workflow could obstruct that objective?
4. **Reason to Respond:** Why would this founder care about hearing from KodoAI now?
5. **Evidence Strength:** Observed fact, reasonable inference or unknown.

Minimum send gate, signal-led:

- Current Signal and Relevant Handoff are observed and sourced.
- The objective is observed or a reasonable inference tied to that signal.
- Reason to Respond is coherent and business-specific.
- Native-platform screening reveals no material contradiction.
- Evidence is labeled at field level.

Minimum send gate, relevance-led:

- Use when Current Signal cannot reach Observed fact; record it as Unknown.
- Relevant Handoff must still be observed and sourced.
- Likely Objective is a reasonable inference tested directly in the final question.
- Reason to Respond is specific to this business.
- Native-platform screening reveals no material contradiction.

Hold only if neither gate survives or another qualification or stop rule fails. Missing online signals do not prove an absence of internal activity. A static website gap alone does not qualify unless it meets the complete relevance-led gate.

An existing KodoAI client or case study is not required. Soban is testing a market opportunity informed by what other providers are already doing. Keep category evidence in internal notes when useful; it does not establish this prospect's priority or replace the observed-handoff gate.

---

## 3. Signal to vector routing

| Signal-led situation supported by the evidence | Active vector |
|---|---|
| Growth signal plus a visible inquiry-to-booking handoff | Conversion recovery |
| Hiring, expansion, rising volume, a current evening/weekend demand signal or operational change plus a visible manual front-desk handoff, including a verified after-hours call-route failure | Capacity |
| A current retention, service-line or membership-base signal plus an observable recall/rebooking handoff | Rebooking and retention |

For relevance-led outreach, select from the observed handoff: inquiry-to-booking; repetitive booking/follow-up/call-handling/channel-reconciliation work (including a verified after-hours route failure); or manual or fragmented recall. Apply the same vector-specific evidence and native-platform screens as the Touch 1 prompt.

A cancellation or waitlist gap is not a vector on its own. It may be the handoff under Capacity or Rebooking and retention only after native-platform screening shows the refill mechanism absent, disabled or failing.

The situation or observed handoff chooses the vector. Company size does not choose the Touch 1 message.

### Platform screens

- Do not sell a native waitlist feature to a Zenoti, Boulevard, Vagaro or Aesthetic Record clinic unless research shows the feature is absent, disabled or failing in the relevant workflow.
- PatientNow has high native-overlap risk. Proceed only where an external channel, exception path or operating handoff remains visibly blocked.
- For an after-hours call handoff under Capacity, posted office hours are not enough. Verify what happens outside the coverage window and rule out a 24/7 human, voice agent or equivalent self-service route.

---

## 4. Competitor analysis is conditional

Competitor research is not a default research stage and a competitor sentence is not a default email component.

Use competitor analysis only when a **recent, verified competitor action is part of the prospect's present situation**, such as:

- a nearby competitor opening or entering the market;
- a competitor launching the same service line;
- a visible shift in booking access, hours or location coverage that plausibly changes local demand;
- the prospect explicitly naming competitive pressure.

When it qualifies, use it as evidence of the current signal or likely objective. Do not treat it as proof that the prospect is losing patients. Do not add a competitor merely to demonstrate that research was done.

Skip competitor analysis when the live signal already explains why the founder may care now, or when the comparison is static, weakly matched or unverifiable.

---

## 5. Touch 1 copy shape

Use the master template in the Touch 1 prompt and the live Notion page. Build the body around the five cold-email rules: 45 to 70 words and 5 to 8 sentences; an introduction with one named-client credibility sentence first (no Bluegile mention); the observed signal and handoff; one or two sentences on how we think we can help; one question. Use US English and no em dashes, in a founder's voice rather than an AE's. Client names come only from the approved list in the Touch 1 prompt (section 8b).

Touch 1 must not use modeled treatments, appointments, slots, memberships, hours or dollars. These have been retired because they asked a stranger to accept too many assumptions before KodoAI had earned trust.

---

## 6. Touch 2: simple bump

Touch 2 does not widen, prove or sell. It replies in the existing thread and resurfaces the likely objective already tested in Touch 1.

Rules:

- Use the exact objective from Touch 1. Do not invent a broader one.
- Do not re-research unless the thread shows a material change.
- Add no new diagnosis, observation, competitor, number or proof point.
- Add no planning model, trial, asset, urgency, call or meeting ask.
- Do not repeat the credibility line or re-introduce KodoAI.
- Use 10 to 35 words, US English, no em dash and one question at the end.

---

## 7. Touch 2 and Touch 3 templates

### Touch 2 template

> [Name],
>
> Is [objective tested in Touch 1] something you're working on right now, or is it not a priority?
>
> Soban

Use the existing thread and subject. Do not add context merely to make the bump look more personalized.

### Touch 3 template

```text
[Name],

We're choosing med-spa partners who are ready to make [objective tested in Touch 1] a priority this quarter.

Is that where [Company] is right now?

Soban
```

Use the existing thread and subject, 15 to 40 words excluding greeting and signature, US English, no em dash and exactly one question at the end. The partner-fit line is the only added framing. Carry the same objective; add no new prospect finding, research, proof, number, argument or offer.

Do not imply an existing med-spa client base or limited availability. A quarterly capacity claim requires Soban's confirmation of a real operating policy. The default template creates tension through readiness and fit.

---

## 8. Current approval state

Approved sequence: signal-led Touch 1 with a relevance-led fallback, simple-bump Touch 2 and partner-fit Touch 3, with exactly one question in every email. Touch 1 follows the five cold-email rules (45 to 70 words, 5 to 8 sentences, a named-client credibility line and no Bluegile mention) and uses three active vectors: Conversion recovery, Capacity and Rebooking and retention. The former close-off, planning models and trial language are retired and must not be restored from older files. Templates, cadence and word counts are KodoAI decisions informed by Rob's principles.
