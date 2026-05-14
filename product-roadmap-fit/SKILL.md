---
name: product-roadmap-fit
description: Evaluates whether a proposed product, feature, or strategic initiative fits a company's existing roadmap and strategy. Analyzes the proposal against the company's mission, product portfolio, target personas, OKRs, legal footprint, and partnerships, and produces an executive-style approve/reject/conditional recommendation. Use whenever the user wants to assess, vet, validate, pressure-test, or sanity-check a new product, feature, or initiative against company strategy — including phrases like "should we build X", "does X fit our roadmap", "evaluate this feature", "roadmap fit", "product strategy review", "strategic fit", "go/no-go", "is this on-strategy", or "would X make sense for us". Trigger even when the user doesn't say "roadmap" explicitly, as long as they're weighing a new product, feature, or initiative against company strategy. Works for product managers, strategy and leadership, or anyone proposing or vetting an initiative.
---

# Product Roadmap Fit Evaluation

This skill produces a structured strategic evaluation of a proposed product or feature, scoring its fit against the company's existing context, and ends with an executive recommendation.

## When to use

Use this whenever someone is deciding whether to add a new product, feature, or initiative to their roadmap and wants a rigorous cross-functional check before committing. The user may be a product manager, a strategy or leadership function, or anyone proposing or vetting an initiative. Typical signals: "should we build this", "does X fit our strategy", "evaluate this idea", "would Y make sense for our users", "go/no-go on Z", "is this on-strategy", or any pre-commitment vetting of a feature or initiative.

## Step 1 — Gather company context (mandatory gate)

The evaluation is only as good as the company context behind it. **Do not proceed to Step 3 until this step is complete.** This is a hard gate, not a suggestion — a roadmap-fit analysis run on assumed context is worse than no analysis, because it produces confident-sounding recommendations grounded in fiction.

You need information on each of the following:

1. **Mission statement** — the company's stated purpose
2. **Product portfolio** — current products and the use cases each one serves
3. **Target personas** — in priority order (primary, secondary, etc.)
4. **Revenue model** — how the company makes money
5. **OKRs** — at company and/or department level, current cycle
6. **Roadmap** — what's already planned and committed
7. **Legal & regional footprint** — regions of operation, applicable regulatory frameworks, and ideally % of users and/or revenue per region
8. **Partnerships** — list of active partners, what each one does, and the revenue/value model with each

**How to handle this step:**

1. First, scan the conversation history and any attached documents for context already provided. Summarize back in 1–2 lines what you understood for each item you found.
2. For every item that is missing, thin, or ambiguous, ask the user. Group the questions in a single message — don't drip-feed across multiple turns.
3. **Pause and wait for the user's response before continuing.** Do not start the analysis with placeholders, assumptions, or generic industry defaults.
4. The user may explicitly tell you to skip a specific item (e.g., "we have no formal partnerships, ignore that one" or "skip OKRs, just use the mission and roadmap"). Accept explicit skips and proceed — but only those that are explicitly waived. Silence on an item is not a waiver.
5. Never invent context to fill gaps. If after asking, the user can't provide an item and doesn't waive it, say so plainly and stop — do not run a partial analysis dressed up as a complete one.

## Step 2 — Gather the proposed product's details

Get a clear picture of what's being evaluated. At minimum you need:

- What the product/feature does
- Who it's intended for
- The core problem it solves or use case it serves
- Whether it's standalone or extends an existing product
- Any known constraints (timeline, budget, dependencies)

If the user's description is vague on these, ask before analyzing.

## Step 3 — Run the analysis

Work through these six dimensions in order. For each dimension, base conclusions on the company context from Step 1; do not rely on generic best practices alone.

### 3.1 Target fit

- Which personas does the proposed product target?
- How do those personas overlap with the company's existing prioritized personas? (full match, partial overlap, adjacent, or net-new audience?)
- Which use cases does it fulfill? Do they overlap with existing use cases, extend them, or open new flows entirely?

### 3.2 Portfolio fit

- Does this integrate into an existing product/feature, or is it a standalone addition?
- What are the realistic levers for **user acquisition** this opens up (e.g., new top-of-funnel, cross-sell, referral)?
- What are the realistic levers for **retention and engagement** (e.g., increased session frequency, deeper feature adoption, stickiness)?

### 3.3 Mission alignment

- How does the product align with the company's mission?
- If alignment is weak or absent: does it actively threaten the mission, or is it merely orthogonal? Can it be reframed to align? Be honest — don't force alignment that isn't there.

### 3.4 Roadmap & OKR impact

- Which existing OKRs does this help, hurt, or leave untouched?
- Provide a directional estimate of impact (qualitative is fine if numbers aren't available; flag what would be needed for a quantitative estimate).
- If you need additional input from the user to assess this — e.g., current metric baselines, capacity constraints — ask explicitly here rather than guessing.

### 3.5 Legal & compliance impact

- Does the product raise any compliance or regulatory concerns in the regions the company operates in? Consider data protection (GDPR, CCPA, etc.), sector-specific regulation, content/age requirements, accessibility, export controls — whichever apply to the company's footprint.
- If a region holds a meaningful share of users or revenue (per Step 1), weight its regulatory regime accordingly.

### 3.6 Partnership impact

- Which existing partnerships are affected — positively, negatively, or neutrally — by adding this product?
- Are there partnership conflicts (e.g., competing with a partner's offering, breaching exclusivity, changing the revenue split logic)?
- Are there partnership opportunities the product could unlock?

## Step 4 — Produce the executive summary

End with a tight executive summary that a busy decision-maker can read in under a minute. Use this exact structure:

```markdown
# Roadmap Fit Evaluation: [Product/Feature Name]

## Recommendation
**[APPROVE / APPROVE WITH CONDITIONS / REJECT]**

[1–3 sentences explaining the headline reasoning.]

## Key strengths
- [Bullet — strongest reasons in favor]

## Key risks & concerns
- [Bullet — strongest reasons against, including any compliance, partnership, or mission risks]

## Conditions / open questions
- [If recommendation is conditional: the specific parameters, thresholds, or decisions that would change the answer]
- [Any items the user explicitly waived in Step 1 that the decision-maker should know were not assessed]

## Detailed analysis
[Then the six-dimension breakdown from Step 3, kept concise — a few bullets per dimension, not essays.]
```

## Style guidance

- **Be direct.** This is a decision-support document, not a pitch deck. If the answer is "no", say so and explain why. If it's "yes, but…", make the "but" specific and actionable.
- **Distinguish evidence from inference.** When a conclusion rests on assumed context rather than confirmed information, mark it (e.g., "Assuming current EU revenue share remains ~30%…").
- **Avoid generic strategy-speak.** "Synergies" and "alignment with strategic priorities" mean nothing on their own. Tie every claim to a specific persona, OKR, partner, regulation, or product in the company's actual context.
- **Quantify where possible.** Even rough ranges ("could lift activation by a few percentage points" / "adds 2–4 weeks to Q3 capacity") are more useful than unqualified claims.
- **Surface trade-offs explicitly.** Almost every real decision involves trading one OKR or persona against another. Name those trades rather than papering over them.
