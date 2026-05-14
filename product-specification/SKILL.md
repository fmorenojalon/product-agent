---
name: product-specification
description: Interviews the user (typically a product lead) to capture all context about a proposed product or feature, then generates a structured PRD document. Use whenever the user wants to write, draft, or create a PRD, product spec, feature spec, product requirements document, or product brief. Also trigger on "spec out this feature", "document this product idea", "write up requirements for X", "I need a PRD for Y", or any request to formally capture what a product or feature is, who it's for, what it solves, and how it should be delivered. Covers problem definition, business case, solution scope, and release planning. Produces a downloadable .docx report with tables.
---

# Product Specification & PRD Generator

This skill interviews the user to capture comprehensive product or feature context, then produces a structured Product Requirements Document (PRD). It is designed to be used by product leads, PMs, or anyone responsible for specifying what gets built and why.

**Important:** This skill is an interview-driven workflow. Do not attempt to generate the PRD until all required information has been gathered or explicitly skipped by the user.

## Differentiation from other skills

- **product-analysis** researches an *external* product or competitor. This skill captures the specification of an *internal* product or feature your team is building.
- **product-roadmap-fit** evaluates whether a feature *should* be on the roadmap. This skill assumes the decision to explore is already made and focuses on *what* the feature is and *how* it should be delivered.

## Step 1 — Establish product/feature context

Start by understanding what is being specified. Ask the user:

1. **Feature type**: Is this a brand-new product, a modification of an existing feature, or an addition on top of an existing product?
2. **Feature name and one-line summary**: What is this called, and what does it do in one sentence?
3. **Problem statement**: What problem or pain point does this solve? What are the scenarios where users feel this pain most acutely? How are users currently working around it (if at all)?

These three items frame everything that follows. Get them before moving on.

## Step 2 — Interview: gather the full specification

Work through the following areas. For each area, check what the user has already provided (in this conversation or in attached documents) and only ask about gaps. **Group your questions** — ask about 3–5 related items per message rather than drip-feeding one at a time.

Before each batch, remind the user: *"If any of these don't apply or you'd rather skip them, just say so and we'll move on."*

### 2.1 Target & personas

- Who is this feature for? New personas, existing personas, or a specific segment/region within existing personas?
- If targeting existing personas: does this apply broadly or to a subset (e.g., specific geography, tier, vertical)?

### 2.2 User flows & stories

- What are the main user flows or stories this feature introduces?
- Walk through the primary "happy path" — what does the user do, step by step?
- Are there secondary or edge-case flows worth capturing?

### 2.3 Value & product impact

How does this feature improve the product? Ask the user to address whichever of these apply:

- **UX / engagement**: Does it make the product easier, faster, or more enjoyable to use?
- **Stickiness / retention**: Does it make the product harder to leave (switching costs, habit formation, data lock-in)?
- **Functionality**: Does it add capabilities users currently lack?
- **Integrations**: Does it connect with new external systems or platforms?
- **Reach**: Does it open the product to new user segments, geographies, or channels?
- **Revenue**: Does it impact any existing revenue streams, or create new ones?

### 2.4 Expected impact & success metrics

- What is the expected impact? Frame it in terms of: new user acquisition (same segment or new), retention/engagement improvement, new business line, new region expansion, or other.
- What metrics will be used to verify the problem is resolved and adoption is happening? Ask the user to be specific (metric name, target, timeframe if possible).
- What is the TAM (total addressable market) or feature-addressable market? Can the user quantify it for the current customer base and/or overall?

### 2.5 Business case & priority

- What is the quantifiable value to the customer?
- How does this feature align with the current strategy? (If the user has run a roadmap-fit evaluation, reference that.)
- What is the priority relative to other initiatives? (Ask for their framing — P0/P1/P2, MoSCoW, or narrative.)

### 2.6 Risks & mitigations

- What are the known risks (technical, market, regulatory, operational)?
- For each risk: is there a planned mitigation, or is it an accepted risk?
- Are there compliance or regulatory considerations given the regions of operation?

### 2.7 Dependencies

- What are the technical dependencies (APIs, infrastructure, platform changes, third-party services)?
- What are the non-technical dependencies (legal review, partnership agreements, content, design, training)?
- Are any dependencies blocking, and what is their current status?

### 2.8 Partnership impact

- How does this feature affect existing partnerships (positively, negatively, or neutrally)?
- Does it improve positioning for new partnerships?
- If it creates new partnership opportunities, capture: partner name, nature of the partnership, expected value exchange, and any agreements needed.

### 2.9 Solution scope

- **MVP**: What is the minimum deliverable that addresses the core problem? Which use cases does the MVP cover, and which are deferred?
- **Effort**: Rough assessment of effort required (T-shirt size or time range is fine at this stage — note that more accurate estimation follows approval).
- **Adoption path**: How will the product be adopted? (Rollout strategy, migration from existing flows, dependencies on other teams or partners.)

### 2.10 Delivery phases

- What are the high-level phases of delivery from a product perspective? (Not engineering sprints — think: Phase 1 = MVP with core flow, Phase 2 = integrations, Phase 3 = scale/optimization, etc.)
- For each phase: what's included, rough timeline or sequencing, and key milestones.

### 2.11 Release & commercialization

- **Release message**: What is the feature's functional description and summary of cases covered, suitable for release notes or a changelog?
- **GTM (go-to-market)**: If the feature is large enough to warrant GTM, capture the plan or note that GTM planning is pending.

## Step 3 — Confidence & certainty check

Before generating the document, do a quick pass with the user:

- For each major section (Problem, Business Case, Solution, Release), ask the user to rate their certainty: **High / Medium / Low**. This maps to the "Certainty (roughly)" row in the evaluation framework and helps readers of the PRD know where the spec is solid vs. where assumptions remain.

Present this as a simple checklist the user can respond to quickly, not a lengthy re-interview.

## Step 4 — Generate the PRD document

Produce the PRD as a **.docx file** using the docx skill. The document should be professional, scannable, and use tables where they aid readability.

### Document structure

```
1. Executive Summary
   - Feature name, type (new / modification / addition), one-line summary
   - Recommendation or status (e.g., "Ready for engineering review", "Pending legal sign-off")
   - Certainty ratings table (Problem / Business Case / Solution / Release)

2. Problem Definition
   - Target personas and segments
   - Problem statement and pain scenarios
   - Current workarounds

3. Business Case
   - TAM / feature-addressable market
   - Customer value (quantified where possible)
   - Strategic alignment and priority
   - Certainty rating

4. Solution
   - MVP scope and use cases addressed
   - User flows (primary and secondary)
   - Product impact summary (table: dimension → impact description)
   - Effort estimate
   - Adoption path
   - Certainty rating

5. Expected Impact & Metrics
   - Impact framing (acquisition / retention / revenue / reach / etc.)
   - Success metrics table (metric | target | timeframe)

6. Risks & Mitigations
   - Risk register table (risk | severity | mitigation | status)

7. Dependencies
   - Technical dependencies table (dependency | owner | status | blocking?)
   - Non-technical dependencies table (same columns)

8. Partnership Impact
   - Existing partnership effects
   - New partnership opportunities (if any)

9. Delivery Phases
   - Phase table (phase | scope | timeline | milestones)

10. Release & Commercialization
    - Release message / changelog draft
    - GTM plan or GTM status

11. Evaluation Framework (Summary Table)
    [Reproduce the four-column framework table below]
```

### Evaluation framework table

Include this table in the PRD (Section 11) as a one-page summary. It maps to the user's provided framework:

| | **Problem** | **Business Case** | **Solution** | **Release & Commercialization** |
|---|---|---|---|---|
| **Core** | Target: personas, segments, verticals | TAM: feature-addressable market, quantified | MVP: minimum deliverable, use cases covered | Metrics: how we verify the problem is solved and adoption is happening |
| **Detail** | Problem: scenarios and pain level | Value: quantifiable customer value | Effort: rough build estimate | Release message: functional description and cases covered |
| **Context** | Current workarounds | Priority · Strategic alignment | Adoption: rollout path, dependencies, other work needed | GTM: if large enough |
| **Confidence** | Certainty (High/Med/Low) | Certainty (High/Med/Low) | Certainty (High/Med/Low) | Certainty (High/Med/Low) |

### Style guidance for the document

- **Executive summary first.** A busy stakeholder should get the full picture from page 1.
- **Tables over prose for structured data.** Risks, dependencies, metrics, and phases are easier to scan as tables.
- **Flag assumptions.** If the user skipped a section or gave a rough estimate, mark it clearly (e.g., "Estimate — pending engineering input").
- **Keep it actionable.** Every section should help someone make a decision or take a next step, not just describe the feature.

## Handling skipped sections

If the user skipped any section during the interview:

- Still include the section header in the PRD.
- Add a note: *"Not assessed — skipped by product lead during specification."*
- This ensures readers know the gap is intentional, not an oversight.

## After delivery

Once the .docx is generated, provide a brief chat summary covering:

- What was captured
- Which sections were skipped (if any)
- Suggested next steps (e.g., "Schedule engineering estimation for effort sizing", "Route to legal for compliance review on Section 6")
