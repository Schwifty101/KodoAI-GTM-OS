# KodoAI — Lahore Food Outreach: Message Variants

Five variants per batch, expanding [_MESSAGES.md](_MESSAGES.md). All rules from that file
still apply — send order, timing windows, daily cap, no links in message 1, stop on reply.

**What changed vs. the originals:** the CTA is no longer "want a clip?" but an open question
about what the business actually needs, with a light hint at the wider offer (website
refinement, workflow automation, AI content, marketing automation). The opt-out stays in,
reworded so it reads as an invitation rather than a dismissal.

**Variants differ by angle, not wording.** Each batch's five test genuinely different
persuasion approaches so the A/B measures something. Synonym-swapped variants teach you
nothing.

**Merge fields:** `{{business_name}}`, `{{area}}`, `{{review_count}}`, `{{website}}`.
Delete the field *and its sentence* if unavailable — never send the literal token.

---

## B01_DELIVERY_NOSITE — 51 leads
Delivery-capable, 200+ reviews, no website. Commission angle is valid here. Roman Urdu mix.

### V1 — commission numbers first
> Assalam o Alaikum! {{business_name}} ke delivery orders pe Foodpanda 25–35% le raha hai — un customers se bhi jo already aap ko jaante hain aur baar baar order karte hain.
>
> Aap ka apna ordering system ban sakta hai: WhatsApp + ek simple ordering page. Us pe commission zero.
>
> Waise hum sirf yeh nahi karte — workflow automation aur marketing bhi. Aap ko is waqt sab se zyada kis cheez ki zarurat hai?
>
> — Moiz, KodoAI
> (Kuch nahi chahiye to woh bhi bata dein 🙏)

### V2 — question-led
> Assalam o Alaikum! Ek sawal {{business_name}} ke baare mein — abhi delivery orders zyada tar Foodpanda se aate hain ya log direct call/WhatsApp karte hain?
>
> Poochh raha hun kyunki agar direct ka koi proper system ho to woh 25–35% commission bach jata hai.
>
> Hum ordering systems ke ilawa automation, content aur marketing pe bhi kaam karte hain. Aap batayein, abhi sab se bara masla kya hai?
>
> — Moiz, KodoAI

### V3 — customer-journey narrative
> Assalam o Alaikum! Ek scene sochiye: kisi ne {{business_name}} ka naam suna, Google pe dhoonda — kuch nahi mila. Phir Foodpanda khola aur wahan se order kar diya. Aap ka hi customer, magar 25–35% kam.
>
> Yeh gap band karna mushkil nahi: WhatsApp ordering + ek chhota sa page.
>
> Is ke ilawa automation aur marketing bhi dekhte hain. Aap ko kis cheez ki zarurat mehsoos hoti hai?
>
> — Moiz, KodoAI
> (Filhal kuch nahi to bhi bata dein 🙏)

### V4 — reviews as unused asset
> Assalam o Alaikum! {{business_name}} ke {{review_count}} reviews hain — {{area}} mein bohot kam jagahon ke itne hote hain. Log clearly aap ko pasand karte hain.
>
> Masla yeh hai ke woh saari demand Foodpanda ke through ja rahi hai, 25–35% commission ke saath, kyunki direct order ka koi rasta hi nahi.
>
> Hum yeh rasta banate hain — aur automation/marketing ka kaam bhi. Aap ki abhi sab se bari zarurat kya hai?
>
> — Moiz, KodoAI

### V5 — repeat-customer loss framing
> Assalam o Alaikum! Jo customer {{business_name}} se dus baar order kar chuka hai, us pe bhi Foodpanda har baar 25–35% le raha hai. Naye customer pe commission samajh aata hai — purane pe nahi.
>
> Un regulars ko direct laane ka system ban sakta hai, WhatsApp pe.
>
> Hum is ke saath automation, content aur marketing bhi karte hain. Aap ko abhi kis cheez ki zarurat hai?
>
> — Moiz, KodoAI
> (Zarurat na ho to bas bata dein 🙏)

---

## B02_DELIVERY_SITE — 78 leads
Delivery-capable, 200+ reviews, has a website. Biggest deals. English, peer tone.

### V1 — numbers first
> Assalam o Alaikum! Quick one about {{business_name}} — har delivery order pe Foodpanda 25–35% le raha hai, un customers se bhi jo already aap ko jaante hain.
>
> Site pe menu to hai, ordering nahi — woh add ho sakti hai, rebuild ke baghair.
>
> Waise hum sirf sites nahi banate; workflow automation aur marketing side bhi dekhte hain. Aap ko is waqt sab se zyada kis cheez ki zarurat hai?
>
> — Moiz, KodoAI
> (Kuch nahi chahiye to woh bhi bata dein, bura nahi manunga 🙏)

### V2 — question-led
> Assalam o Alaikum! Ek sawal {{business_name}} ke baare mein — regular customers ke orders bhi Foodpanda se aate hain ya direct?
>
> Poochh raha hun kyunki site pe menu hai, ordering ka option nahi.
>
> Lekin shayad aap ki asal problem yeh hai hi nahi. Hum ordering systems, site refinement, content aur marketing automation — sab pe kaam karte hain. Aap batayein, abhi sab se bara masla kya hai?
>
> — Moiz, KodoAI

### V3 — English, observation-led
> Assalam o Alaikum! I was looking at {{business_name}}'s site — the menu's there, but there's no way to order from it, so delivery keeps routing through Foodpanda at 25–35%.
>
> That's fixable without a rebuild. But it may not be your biggest problem.
>
> We work across websites, workflow automation, AI content and marketing systems. What would actually move the needle for you right now?
>
> — Moiz, KodoAI
> (And if nothing's needed, no problem — just say so.)

### V4 — priority framing
> Assalam o Alaikum! {{business_name}} ki site dekhi — menu to hai, magar wahin se order karne ka option nahi. Is liye delivery ka har order Foodpanda ke through, 25–35% ke saath.
>
> Yeh theek karna mushkil nahi. Par ho sakta hai aap ki priority kuch aur ho — site behtar karna, kaam automate karna, ya content aur marketing.
>
> Aap khud batayein, kis cheez ki zarurat mehsoos hoti hai?
>
> — Moiz, KodoAI

### V5 — customer-journey narrative
> Assalam o Alaikum! Ek scene sochiye: kisi ne {{business_name}} ka naam suna, Google pe search kiya, menu dekha — aur phir order karne ke liye Foodpanda khol liya. Wahi customer, wahi order, magar 25–35% kam.
>
> Yeh gap aap ki maujooda site pe band ho sakta hai, naya banaye baghair.
>
> Waise hum automation aur marketing ka kaam bhi karte hain. Aap ke hisaab se abhi sab se zyada kis cheez ki zarurat hai?
>
> — Moiz, KodoAI
> (Filhal kuch nahi to bhi bata dein 🙏)

---

## B03_CAFE_NOSITE — 22 leads
Cafés, dessert, bakery. 200+ reviews, no website. **No commission angle** — dine-in and
brand-led. Sell discovery.

### V1 — discovery gap
> Assalam o Alaikum! {{business_name}} clearly has something going — {{review_count}} reviews in {{area}}, and still nothing online beyond social media.
>
> The gap: when someone hears about you and searches Google, there's no menu, no photos, no way to book. They scroll to the next place.
>
> We build cafés a clean one-pager, and we also handle content and marketing systems. What would help you most right now?
>
> — Moiz, KodoAI
> (Not relevant? Just say so 🙏)

### V2 — Instagram dependency
> Assalam o Alaikum! Right now {{business_name}} lives entirely on Instagram — which works until someone searches for you on Google and finds nothing they can act on.
>
> A simple page with menu, photos, location and a WhatsApp button fixes that in about a week. Instagram stays your front door; this catches everyone who doesn't use it.
>
> We also do content and marketing automation. What's the most useful thing for you at the moment?
>
> — Moiz, KodoAI

### V3 — narrative
> Assalam o Alaikum! Ek scene: kisi ne dost se {{business_name}} ke baare mein suna, Google pe search kiya — menu nahi, photos nahi, timings nahi. Us ne agli jagah choose kar li.
>
> Yeh roz hota hai aur kisi ko pata nahi chalta. Ek saaf sa one-pager is ko rok deta hai.
>
> Hum content aur marketing ka kaam bhi karte hain. Aap ke liye abhi sab se zyada kaam ki cheez kya hogi?
>
> — Moiz, KodoAI
> (Filhal kuch nahi to bhi bata dein 🙏)

### V4 — reputation has nowhere to land
> Assalam o Alaikum! {{review_count}} reviews is a genuinely strong number for a café in {{area}} — most never get close.
>
> What's missing is somewhere for that reputation to land. Someone reads the reviews, wants the menu or timings, and there's no page to send them to.
>
> We build that, and we also work on content and marketing systems. What would actually help you most right now?
>
> — Moiz, KodoAI

### V5 — pre-visit decision
> Assalam o Alaikum! For a café, half the decision is made before anyone walks in — photos, menu, whether they can book a table for six on a Saturday.
>
> {{business_name}} has no page carrying any of that, so every one of those questions costs you a customer who didn't want to ask.
>
> We build that page; we also do content and marketing automation. What's your biggest gap at the moment?
>
> — Moiz, KodoAI
> (No need? Just tell me 🙏)

---

## B04_CAFE_SITE — 36 leads
Cafés with a site, 200+ reviews. Sell **content + conversion**, never a rebuild.

### V1 — skip the pitch, name the two levers
> Assalam o Alaikum! Your site's already up, so I'll skip the pitch.
>
> Two things move numbers for cafés at your level: a booking / WhatsApp-order button people can't miss, and fresh food photos and reels. Most café sites go stale within a year while Instagram takes all the attention.
>
> We handle both, plus marketing automation and AI content. What's the priority for {{business_name}} right now?
>
> — Moiz, KodoAI (not relevant? just say so)

### V2 — missing next step
> Assalam o Alaikum! Had a look at {{website}} — it does the job of telling people who you are.
>
> What it doesn't do is give them an obvious next step. No prominent booking or WhatsApp button means an interested visitor just… leaves.
>
> That's a small change, not a rebuild. We also do content and marketing automation. What would be most useful for {{business_name}} at the moment?
>
> — Moiz, KodoAI

### V3 — content decay
> Assalam o Alaikum! Quick observation about {{business_name}} — the site's fine, but café sites age fast. Menu shifts, prices change, the photos stay from launch day.
>
> Meanwhile all your fresh content goes to Instagram, where it disappears in 48 hours instead of working for you permanently.
>
> We keep sites current and handle content and marketing automation. What's the biggest gap for you right now?
>
> — Moiz, KodoAI
> (Not a priority? No problem, just tell me 🙏)

### V4 — photography
> Assalam o Alaikum! Food photography does more work than anything else on a café's website — and it's usually the oldest thing on there.
>
> For {{business_name}} the quickest win is probably fresh shots and short reels, plus making the booking option impossible to miss. Neither needs a rebuild.
>
> We also do marketing automation and AI content. What would help you most at the moment?
>
> — Moiz, KodoAI

### V5 — question-led
> Assalam o Alaikum! Genuine question about {{website}} — kya us se koi actual bookings ya orders aate hain, ya woh sirf ek online business card ban gaya hai?
>
> Zyada tar café sites doosri wali cheez hoti hain. Thodi si tabdeeli — visible booking button aur nayi photos — us ko badal deti hai.
>
> Hum content aur marketing automation bhi karte hain. {{business_name}} ke liye abhi sab se zaroori kya hai?
>
> — Moiz, KodoAI
> (Filhal kuch nahi to bata dein 🙏)

---

## B06_REPUTATION — 30 leads
200+ reviews, rating under 4.0. **Never mention their rating** — it insults them and kills
the thread. Every variant below sells the feedback-capture flow and treats their volume as
the asset it is.

### V1 — volume, and its one downside
> Assalam o Alaikum! {{business_name}} does real volume — {{review_count}} reviews is more than most places in {{area}} ever get.
>
> The tricky part about that volume: one bad night ends up on Google permanently, and you usually find out weeks later.
>
> We set up a WhatsApp flow that asks customers how it went right after their order, so issues reach you first. We also do automation and marketing. What's most useful for you right now?
>
> — Moiz, KodoAI

### V2 — the feedback asymmetry
> Assalam o Alaikum! Something most restaurant owners notice too late: the customer who had a great meal says nothing, and the one who had a bad experience writes it up that evening.
>
> With {{review_count}} reviews, {{business_name}} feels that imbalance more than most. A simple post-order WhatsApp check-in evens it out — unhappy ones reach you directly, happy ones get pointed to Google.
>
> We also handle automation and marketing. What would help most at the moment?
>
> — Moiz, KodoAI
> (Not relevant? Just say so 🙏)

### V3 — hearing it before Google does
> Assalam o Alaikum! {{business_name}} clearly has steady volume in {{area}}.
>
> At that scale the useful question isn't whether something occasionally goes wrong — it's whether you hear about it before Google does. Right now there's probably no channel for that.
>
> We set up an automatic WhatsApp check-in after each order. The same system takes direct orders, so regulars stop costing you Foodpanda commission. We also do marketing automation and content — what's your priority right now?
>
> — Moiz, KodoAI

### V4 — narrative
> Assalam o Alaikum! Ek scene: Friday raat, kitchen full, ek order 40 minute late gaya. Customer ne kuch kaha nahi — bas ghar ja kar Google pe likh diya. Aap ko pata Monday ko chala.
>
> {{business_name}} jaise volume pe yeh har mahine hota hai. Ek automatic WhatsApp check-in is ko rok deta hai — shikayat pehle aap tak aati hai.
>
> Hum automation aur marketing bhi karte hain. Aap ki abhi sab se bari zarurat kya hai?
>
> — Moiz, KodoAI
> (Zarurat na ho to bata dein 🙏)

### V5 — question-led
> Assalam o Alaikum! Ek sawal {{business_name}} ke baare mein — abhi customer ka feedback aap tak pohanchne ka koi tareeqa hai, ya sirf Google review se hi pata chalta hai?
>
> {{review_count}} reviews ka matlab hai volume acha hai, lekin us volume pe feedback ka koi direct channel na hona mehnga parta hai.
>
> Hum yeh flow set up karte hain, aur automation/marketing ka kaam bhi. Aap batayein kis cheez ki zarurat hai?
>
> — Moiz, KodoAI

---

## B05_EARLY_STAGE — 91 leads
Under 200 reviews. Thin budgets, lowest priority, smallest offer.

**Deliberate departure:** the offer-hint is much lighter here than in other batches. The
original spec says honesty converts better than upselling on this segment, and listing four
services at a new business with no budget reads as exactly the upsell it warns against. These
variants ask the open question without the service menu.

### V1 — honest, small
> Assalam o Alaikum! Saw {{business_name}} in {{area}} — looks fairly new?
>
> Honestly, at this stage a big website isn't what you need. What matters is being findable: Google listing set up properly, menu online, and a WhatsApp ordering link for your Instagram bio.
>
> We do that as a small starter setup. But you'd know better than me — what's actually slowing things down right now?
>
> — Moiz, KodoAI (reply anytime, or not at all 🙏)

### V2 — findability basics
> Assalam o Alaikum! {{business_name}} {{area}} mein naya lag raha hai?
>
> Is stage pe bara website banane ka koi faida nahi. Asal cheez yeh hai ke jab koi aap ko dhoonde to mil jayein — Google listing theek ho, menu online ho, aur WhatsApp order ka link ho.
>
> Hum yeh chhota sa setup karte hain. Lekin aap batayein — abhi sab se zyada dikkat kis cheez mein aa rahi hai?
>
> — Moiz, KodoAI

### V3 — the Instagram bio link
> Assalam o Alaikum! Agar {{business_name}} ke zyada tar customers Instagram se aate hain, to sab se bara masla aksar yeh hota hai ke bio mein click karne ko kuch theek sa nahi hota.
>
> Ek simple menu page aur WhatsApp ordering link — bas itna. Is stage pe is se zyada ki zarurat nahi hoti.
>
> Aap ke hisaab se abhi sab se bari rukawat kya hai?
>
> — Moiz, KodoAI
> (Jawab na dena ho to koi baat nahi 🙏)

### V4 — question-led, no pitch at all
> Assalam o Alaikum! {{business_name}} ko {{area}} mein dekha — kaafi naya hai?
>
> Poochhna yeh tha ke abhi customers zyada tar kahan se aa rahe hain — Instagram, walk-in, ya Foodpanda?
>
> Poochh raha hun kyunki jawab ke hisaab se agla step bilkul alag hota hai, aur naye setups ko aksar bari cheez ki zarurat hi nahi hoti. Aap batayein?
>
> — Moiz, KodoAI

### V5 — narrative
> Assalam o Alaikum! Naye restaurants ke saath aksar yeh hota hai: khana acha hota hai, log aate hain, magar jab koi dost ko naam batata hai to woh Google pe dhoondta hai aur kuch theek se milta nahi.
>
> {{business_name}} ke liye is stage pe sirf itna kaafi hai — listing, menu online, WhatsApp order link.
>
> Aap ko abhi sab se zyada kis cheez ki kami mehsoos hoti hai?
>
> — Moiz, KodoAI
> (Filhal kuch nahi to bhi theek hai 🙏)

---

## B00_NO_WHATSAPP — 120 leads (do not send on WhatsApp)
No WhatsApp-capable number. Highest median review count of any batch — do not discard.

Route as the original spec says: 68 with an email get the **B02 V3** variant reworded as
email with a subject line; the rest get Instagram DM or a walk-in with a printed one-pager.
The open-question CTA works better over email than the clip ask did, since there's no
one-tap reply either way.

---

## Notes on using these

**Rotation is not the point.** Content variation was never what protected a number — block
and report rate is. These convert better and generate fewer blocks because the opt-out is
present and the ask is lower-pressure, not because they defeat any classifier.

**Keep one clip-ask control.** Every variant here replaces "want a clip?" with an open
question. That trades raw reply rate for reply quality — open questions need composing, a
yes/no needs one tap. Keep one original-style message per batch running so you can measure
the tradeoff instead of guessing.

**The service hint scales with budget.** B02 and B04 name up to four services; B01 and B03
name two; B05 names none. Naming a full catalogue at a business that can't afford it reads
as spray-and-pray and costs credibility.

**Every promise still needs backing.** These commit to less than the originals — no clip, no
before/after — but if someone asks what you've built, have it ready.
