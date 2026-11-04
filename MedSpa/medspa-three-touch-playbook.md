# Med Spa Cold Email: Three-Touch Playbook

**Version:** Signal-led draft, 24 September 2026. Pending Soban's review.
**Project language:** US English.

This document records the sequence logic and the optional Touch 2 planning models. The live Notion page and the two master prompts control execution.

---

## 1. Sequence logic

| Touch | Timing | Job |
|---|---|---|
| Touch 1 | Day 0 | Use a current signal to connect a likely objective with an observable handoff. Ask one question. No modeled treatments, appointments, memberships, hours or dollars. |
| Touch 2 | Day 3 | Refer back to the situation, optionally test a clearly labeled full-system planning model, and offer a one-week free trial. |
| Touch 3 | Day 7 | Close the loop briefly. No new claim, number or offer. |

The five active Touch 1 vectors are:

1. Conversion recovery
2. After-hours call coverage
3. Cancellation recovery
4. Rebooking and retention
5. Capacity

Membership is not an active standalone Touch 1 vector. Historical membership records remain valid history but do not define the current sequence.

---

## 2. Touch 1 research spine

Every prospect is evaluated through five fields:

1. **Current Signal:** What changed recently?
2. **Likely Objective:** What are they probably trying to accomplish?
3. **Relevant Handoff:** What observable workflow could obstruct that objective?
4. **Reason to Respond:** Why would this founder care about hearing from KodoAI now?
5. **Evidence Strength:** Observed fact, reasonable inference or unknown.

Minimum send gate:

- A current, time-bound signal is observed.
- The signal supports a reasonable objective.
- A relevant handoff is observable and connected to that objective.
- The message gives the founder a credible reason to respond now.
- The evidence can be labeled honestly.

A static website gap on its own does not qualify. If the signal, objective or connection to the handoff is too weak, hold the lead instead of forcing a vector.

---

## 3. Signal to vector routing

| Situation supported by the evidence | Active vector |
|---|---|
| Growth signal plus a visible inquiry-to-booking handoff | Conversion recovery |
| A current campaign, launch or expansion increases demand outside verified coverage windows | After-hours call coverage |
| A current capacity or demand signal makes dropped appointments more consequential, with a visible cancellation/waitlist handoff | Cancellation recovery |
| A current retention, service-line or membership-base signal plus an observable recall/rebooking handoff | Rebooking and retention |
| Hiring, expansion, rising volume or operational change plus a visible manual front-desk handoff | Capacity |

The situation chooses the vector. Company size does not choose the Touch 1 message.

### Platform screens

- Do not sell a native waitlist feature to a Zenoti, Boulevard or Aesthetic Record clinic unless research shows the feature is absent, disabled or failing in the relevant workflow.
- PatientNow has high native-overlap risk. Proceed only where an external channel, exception path or operating handoff remains visibly blocked.
- For after-hours coverage, posted office hours are not enough. Verify what happens outside the coverage window and rule out a 24/7 human, voice agent or equivalent self-service route.

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

Use the master template in the Touch 1 prompt and the live Notion page. Target 45 to 70 words, US English, no em dashes and one question.

Touch 1 must not use modeled treatments, appointments, slots, memberships, hours or dollars. These have been retired because they asked a stranger to accept too many assumptions before KodoAI had earned trust.

---

## 6. Optional Touch 2 planning models

These are retained as a separate experiment and are **not yet approved as the final Touch 2 design**. If Soban approves their use, label each figure as a full-system planning model for a clinic in the stated size tier, not a measurement of the prospect and not the value of the Touch 1 handoff alone.

| Vector | Small | Established | High-volume 75th | High-volume 90th | Multi-location, per site |
|---|---:|---:|---:|---:|---:|
| Conversion recovery | $45,556 | $60,744 | $122,448 | $311,016 | $84,396 |
| Capacity | $21,503 | $28,668 | $36,077 | $65,512 | $32,370 |

Additional cases:

- **Cancellation recovery:** the retained full-system Case A planning model is 916 additional completed visits per year on the same provider hours, modeled at $118,657. It is not a clinic measurement.
- **After-hours call coverage:** if tested, use the conversion-recovery row only as a whole-path inquiry-to-completed-treatment model. It is not the value of after-hours calls and must never be added to conversion recovery.
- **Rebooking and retention:** no approved annual dollar model exists. Do not use the old modeled-hours substitute.
- **Membership:** legacy model only. Do not use it to revive membership as an active Touch 1 vector.

### Size-tier reference for the optional experiment

The existing tiers use `Employees` as a rough proxy for clinic size because provider count is not reliably stored:

| Tier | Employees |
|---|---:|
| Small | 16 or fewer |
| Established | 17 to 26 |
| High-volume | 27 or more |

For multi-location prospects, use employees per verified location. Above roughly seven locations, quote a per-location figure rather than a large aggregate. These rules support the optional Touch 2 model only; they do not control Touch 1.

### Model limitations

- Contribution margin and operational lift are assumptions, not observed clinic facts.
- Native platform overlap can eliminate or reduce the modeled opportunity.
- Do not compute clinic-specific value without clinic-specific volume, conversion, completion and collection data.
- If the figure cannot be explained briefly and honestly, omit it and let the free trial carry Touch 2.

---

## 7. Touch 2 and Touch 3 templates

### Touch 2 working template

> [Name],
>
> Following up on [current signal or relevant handoff].
>
> For a [size tier] clinic, the full [path] has a modeled annual opportunity of [figure]. That's a planning model, not a measurement of [Company].
>
> Easier to test than assume. For one week, I'll run [slice] through [platform], free, capped at [limit].
>
> Want me to set that up for [day]?
>
> Soban | Founder, KodoAI

Use 45 to 85 words. If the optional planning model is not approved or does not apply, omit it and make the trial the reason for the follow-up.

### Touch 3 working template

> [Name], last one from me. If [the thing] isn't what you're working on this quarter, no problem and I'll leave it there. If it is, the week's still open.
>
> Soban

Use 15 to 40 words. Do not add a new argument, number or offer.

---

## 8. Approval boundary

This draft finalizes the new Touch 1 design but leaves one substantive decision open for Soban: whether Touch 2 should retain the annual planning-model experiment at all. Until he approves it, do not treat the model as production copy.
