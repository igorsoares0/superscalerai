# SuperScaler AI — Landing Page Copy

Version 1.0 · Draft for review

---

## Positioning (the thinking behind every line below)

**The category problem:** every AI upscaler on the market promises "more detail." They all deliver it. What they don't tell you is the trade: the model invents detail it has no evidence for. Your subject comes back looking like their cousin. The logo on the product becomes a smear that resembles letters. The street sign says something that isn't a word.

So "more detail" is not a wedge — everyone claims it. **Fidelity is the wedge.** The anxiety a real user feels before clicking Enhance is not *will this get sharper*, it's *will this still be my photo*.

Every headline, section and CTA below is built on that single insight: **we sell detail you can trust, not detail you have to check.**

**Secondary wedge:** no sliders. Competitors expose creativity/resemblance/HDR/steps and quietly hand the user the job of calibrating a diffusion model. We did the calibration. The product is opinionated on purpose, and that's a feature we should say out loud, not apologize for.

**Voice:** plain, specific, quietly technical. Short sentences. Concrete nouns — face, logo, serial number, storefront — never "assets" or "visuals." No exclamation marks. Confidence comes from precision, not from adjectives.

**Audience, in priority order:** e-commerce sellers with bad product photos · portrait & wedding photographers · real-estate agents · designers restoring old client files · AI artists finishing generations.

---

## 1. Hero

### Recommended

> # Upscale that doesn't rewrite your photo.
>
> Most AI enhancers invent a new face, a new logo, new text. SuperScaler adds real detail and keeps the picture yours.
>
> **[ Enhance an image free ]**
> 8 credits when you sign up. No card.

**Why this one:** it leads with the objection instead of the promise. Anyone who has been burned by an AI upscaler recognizes their own experience in the first line and keeps reading. "Keeps the picture yours" is the whole product in four words.

### Alternates

**B — the outcome cut**
> # 4x the resolution. Same person.
>
> Real detail, added where the evidence supports it. Faces, text and logos come back the way they went in.

*Sharper, more quotable, works better as an ad. Slightly narrower — reads portrait-only when the product also serves product and architecture shots.*

**C — the craft cut**
> # Your photo, at a resolution it never had.
>
> Not a sharpening filter and not a hallucination. A pipeline that measures your image first, then enhances it on its own terms.

*Best for a design-led audience. Weakest CTA pull of the three — the objection stays implicit.*

**D — the anti-slider cut**
> # No prompts. No sliders. No second guessing.
>
> Pick what the photo is. We handle the twenty parameters underneath.

*Strong for users who have already tried the competition and bounced off the control panel. Use as a paid-search variant against branded competitor terms.*

### Hero visual direction

Before/after slider, live and draggable, loaded with a portrait at ~800px upscaled to 3200px. Default the handle to 40% so the enhanced side is what the eye lands on first. Under it, a small caption in muted text:

> Drag. That's the same photo — no retouching, no prompt.

---

## 2. Trust bar

Immediately under the hero. Four items, no logos until we have real ones.

> Formats: JPG · PNG · WEBP  ·  Up to 25 MB  ·  Up to 4x  ·  Your credits are refunded if a job fails

> ⚠️ **Needs your input:** do not add customer logos, "trusted by 10,000 creators," star ratings, or press badges until they're real. A fabricated trust bar is the fastest way to lose a technical audience, and it's the first thing they check.

---

## 3. The problem

> ## Every AI upscaler adds detail. The question is where it gets it.
>
> When a diffusion model enlarges your image, it doesn't magnify what's there — it generates what it thinks should be there. Turn that up and you get spectacular texture on a face that is no longer your client's face.
>
> That's why most upscaled photos look impressive in the thumbnail and unusable at full size. The eyes drifted. The wedding ring grew a stone. The label on the bottle says something close to your brand name.
>
> **You shouldn't have to inspect every result to find out whether you can ship it.**

---

## 4. How it works

> ## Three steps. No parameters.
>
> **1. Upload**
> JPG, PNG or WEBP, up to 25 MB.
>
> **2. Pick what it is**
> Portrait, Product, Architecture, or AI Generated. That's the only choice you make — and it's a choice about your photo, not about a model.
>
> **3. Download**
> Compare before and after, zoom to 100%, and take the full-resolution file.

Closing line under the three steps:

> Behind those three clicks: eight processing stages, a caption model, protection masks, and a set of parameters we spent weeks calibrating so you never have to see them.

---

## 5. Differentiators

Four blocks. Each one names a failure mode of the competition, then our answer. Order matters — identity first, because it carries the most fear.

### 5.1 Identity

> ### It knows a face when it sees one.
>
> Before anything is generated, SuperScaler analyzes your image and finds the faces. Large faces are handled by the main pass. Small ones — the ones every other tool destroys — get cropped out, enhanced as their own close-up where the model is reliable, and composited back.
>
> The result is a face with real skin texture that is still recognizably the same person. We tuned that trade deliberately, and we tuned it conservatively.

### 5.2 Text and logos

> ### Text stays text. Logos stay logos.
>
> Generative models cannot read. Ask one to enlarge a serial number, a price tag or a brand mark and it will produce something shaped like letters.
>
> So we don't ask. Text and logo regions are detected, enlarged deterministically — no generation at all — and blended back into the enhanced image with a feathered mask. No invented characters. No visible seam.
>
> If you sell products with writing on them, this is the difference between a usable photo and a fake one.

### 5.3 Presets

> ### A preset isn't a label. It's twenty decisions you don't have to make.
>
> Denoise strength, structural guidance, which local enhancers run, how many passes, the prompt fragment that steers the whole thing — every one of those is set per preset, calibrated against test sets, and locked.
>
> "Portrait" doesn't mean we tagged it portrait. It means the parameters are the ones that survive a face.

Optional supporting table — good for a technical audience, cut it for a mainstream one:

| Preset | Built for | Protects |
|---|---|---|
| **Portrait** | People, headshots, weddings | Identity, skin texture |
| **Product** | E-commerce, packaging, catalogs | Text, labels, logos |
| **Architecture** | Interiors, real estate, exteriors | Straight lines, signage |
| **AI Generated** | Midjourney, SDXL, FLUX output | Nothing — this one is free to invent |

### 5.4 Reproducibility

> ### The same photo, twice.
>
> Every job stores its seed and every resolved parameter. Run it again and you get the identical file. Hit Regenerate and you get a genuine second take, not a random reroll of the whole thing.
>
> If your work goes through client approval, this is the difference between a tool and a toy.

---

## 6. Under the hood

For the skeptic who scrolled this far. This is the credibility section — it should read like documentation, not marketing.

> ## Most upscalers are one API call. This is eight stages.
>
> A single model handed a whole image has to guess at everything at once. We break the problem apart, so each part can be solved by something that's actually good at it — and so any stage can be replaced when something better comes along.
>
> **Analyzer** — measures resolution, noise, blur, compression, faces, text regions. CPU, no guessing.
> **Captioner** — describes your image so the generative pass has something true to work from. You never write a prompt.
> **Planner** — merges the preset, the measurements and your scale into one explicit execution plan.
> **Preprocessor** — orientation, color, artifact removal. Snapshots the original's color so we can restore it later.
> **Generative Upscaler** — the main pass, max 2x at a time, guided by the structure of your original.
> **Local Enhancers** — repairs what the generative pass costs: small faces, text, logos.
> **Post Processor** — color-matched back to your original, sharpened, seams checked.
> **Exporter** — final image, thumbnail, and the full plan that produced it.
>
> Open models only. No proprietary black box in the critical path.

---

## 7. Pricing

> ## Pay for pixels, not for seats.
>
> Credits never expire. One credit is one enhancement at standard resolution; larger outputs cost more because they genuinely cost us more.
>
> | Output resolution | Credits |
> |---|---|
> | Up to 1024px | 1 |
> | Up to 2048px | 2 |
> | Up to 4096px | 4 |
> | Above 4096px | 8 |
>
> **Start with 8 free credits.** Enough for one full-resolution job on a photo straight off your phone — we sized it that way on purpose, so the trial works with the picture you actually have.
>
> **If a job fails, the credits go back.** Automatically.

### Credit packs

> ⚠️ **Blocked on you — I did not invent prices.** Pack sizes and amounts are your call, not mine. Tell me the numbers and I'll write the tier names, the value framing, and the anchor copy around them.
>
> Structural recommendation when you decide: three packs, middle one marked "Most popular," priced so the middle pack's per-credit rate looks obviously better than the small one. Name packs by use, not by size — "One shoot," "A season," "Studio."

> **Also needs a decision before this section ships:** subscription vs one-off packs vs both. The copy above assumes pure prepaid credits, which is the easier story to tell and the weaker recurring revenue. Worth a conversation.

---

## 8. Objection handling / FAQ

> **Will it change my subject's face?**
> That's the failure we built the product around. Faces are detected, small ones are repaired as close-ups rather than guessed at, and the Portrait preset runs at a deliberately low creativity setting — we tested where identity starts to break and stayed well underneath it. On a well-lit photo you should not be able to tell it's the same person only because we told you.
>
> **Do I need to write a prompt?**
> No, and there's nowhere to. A caption model reads your image and writes the prompt for you.
>
> **What can I upload?**
> JPG, PNG and WEBP, up to 25 MB, up to 3072px on the longest edge. Bigger inputs get rejected rather than silently downscaled.
>
> **How much bigger does it get?**
> Up to 4x, in 2x passes. If your image is already at the target size, we run an enhance-only pass instead of upscaling for no reason.
>
> **How long does it take?**
> ⚠️ *Placeholder — fill in from real p50/p95 job times before this goes live. Do not guess; this is the number people screenshot.*
>
> **What happens if it fails?**
> Your credits are refunded automatically. That includes jobs interrupted on our side.
>
> **Can I use the results commercially?**
> Yes. The output is yours. Every model in our pipeline is licensed for commercial use — we checked the weights, not just the code.
>
> **Do you train on my images?**
> ⚠️ *Needs your policy decision — do not publish a placeholder here. This is the single most-read FAQ answer for a technical audience and the one they will hold you to. Answer it plainly and truthfully, or leave the question off entirely.*
>
> **Can I get the same result twice?**
> Yes. Every job stores its seed and full parameter set.

---

## 9. Final CTA

> ## Try it on the photo you're worried about.
>
> Not the easy one. The one with the small face, or the label you can't read, or the shot you already gave up on. That's the one that tells you whether this works.
>
> **[ Enhance an image free ]**
> 8 credits. No card. Takes about a minute.

**Why this framing:** every SaaS closes with "get started free," which asks for nothing and gets nothing. Naming the hard photo does two jobs — it's a confident quality claim, and it steers the trial toward the case where we beat the competition most visibly. Users who upload an easy photo see a small difference and churn.

---

## 10. Microcopy

Small surfaces, disproportionate effect on how finished the product feels.

**Buttons**
- Primary CTA: `Enhance an image free`
- In-app primary: `Enhance` (never "Submit," never "Process")
- Secondary: `See how it works`
- On the compare view: `Download full size`
- Retry: `Regenerate` — with tooltip *Same settings, new take.*

**Upload zone**
- Empty: `Drop an image here` / `JPG, PNG or WEBP · up to 25 MB`
- Dragging: `Let go.`
- Too large: `That's over 25 MB. Try exporting at a lower compression.`
- Too many pixels: `That's larger than 3072px on the long edge — bigger than we can enhance well. Downscale it and we'll take it from there.`
- Wrong format: `We take JPG, PNG and WEBP. That looked like something else.`

**Job states** — say what's happening, not "Loading."
- `Reading your image…`
- `Describing what's in it…`
- `Enhancing — this is the slow part…`
- `Repairing faces…`
- `Matching color to your original…`
- `Done.`

**Empty gallery**
> Nothing here yet. Upload something and it'll show up — original and enhanced, side by side.

**Out of credits**
> You're out of credits. Your images stay where they are.
> `[ Get more ]`

**Job failed**
> That one didn't finish, and your credits are back in your account. If it happens again with the same image, send it to us — we'll look at it.

**Password reset confirmation**
> If that email is registered, a reset link is on its way.

*(Deliberately non-committal — confirming whether an address exists is an account-enumeration leak.)*

---

## 11. Meta / SEO

**Title tag** (58 chars)
`SuperScaler AI — Upscale photos without changing them`

**Meta description** (152 chars)
`AI image upscaling that keeps faces recognizable and text readable. Pick a preset, get up to 4x resolution. 8 free credits, no card required.`

**OG image direction:** a single before/after pair, split down the middle, cropped tight on a face at roughly 300% so the detail gain is legible at thumbnail size. No UI chrome, no logo lockup, no text overlay beyond the product name — the split itself is the message.

**Primary keyword targets:** ai image upscaler · upscale image without losing face · magnific alternative · ai photo enhancer for product photos

---

## Open items before this ships

1. **Prices and pack structure** — yours to decide, I left it blank on purpose.
2. **Subscription vs one-off credits** — changes section 7 substantially.
3. **Real processing times** for the FAQ.
4. **Training-data policy** — needs a real answer, not copy.
5. **Before/after assets** — the hero slider carries more persuasive weight than every word above it combined. Pick examples where the *fidelity* win is visible, not just the sharpness win: a small face, a label with text on it. A generic landscape proves nothing our competitors can't also show.
