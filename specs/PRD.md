# Product Requirements Document — Product Agent

## Overview

Product Agent is a multi-agent AI system that helps product leads, product managers, and senior strategists make informed decisions about adding new products or features to an existing portfolio. It orchestrates a set of specialized Claude agents that cover research, user feedback synthesis, and specification generation end-to-end.

## Target Users

- Product leads evaluating new feature or product opportunities
- Product managers preparing specs and user stories for engineering
- Senior management seeking strategic insight into portfolio decisions

## Problem Statement

Product decisions require synthesizing fragmented inputs — market research, user feedback, roadmap constraints, and engineering requirements — a process that today is slow, manual, and inconsistent across teams. Product Agent automates the heavy-lifting so PMs can focus on judgment rather than assembly.

## Pipeline Overview

The pipeline has two distinct phases separated by a human decision gate:

**Phase A — Research (parallel):** Both research agents run simultaneously from the user's initial idea.  
**Human gate:** The orchestrator synthesizes the research into 2–3 product direction proposals; the user confirms one.  
**Phase B — Specification (sequential):** Spec drafting and user story generation run in sequence using the confirmed direction as input.

```
User prompt (idea / hypothesis)
    ├─► UC-1: Competitive research       (product-analysis)        ┐ run in
    └─► UC-2: User feedback synthesis   (product-user-feedback)    ┘ parallel
                    │
            [Orchestrator synthesizes both outputs]
                    │
            2–3 product direction proposals presented to user
                    │
              [Human confirms one]
                    │
            ├─► UC-3: Spec drafting      (product-specification)
            └─► UC-4: User stories       (product-user-story → Notion)
```

## In-Scope Use Cases (PoC)

### UC-1: Competitive Research
The agent accepts a product idea or feature hypothesis and produces a structured research brief covering the competitive landscape, market positioning of comparable products, and relevant technical and commercial signals.

- Input: free-text idea or feature hypothesis from the user
- Output: structured research brief (markdown) — competitors, positioning, key signals
- Agent: `product-analysis` (existing skill)
- Runs in parallel with UC-2

### UC-2: User Feedback Synthesis
The agent researches publicly available user feedback on comparable products and distills it into key themes, sentiment signals, and quoted evidence relevant to the idea under evaluation.

- Input: idea or product area to investigate (same prompt as UC-1)
- Output: feedback synthesis report (markdown) covering Reddit, forums, and app store reviews
- Agent: `product-user-feedback` (existing skill — sources via web search)
- Runs in parallel with UC-1
- **New work — Discord connector:** Reading user feedback from Discord channels requires a new connector script that fetches recent messages from configured channels and injects them into the skill's synthesis step. Implemented in Phase 2.

### Synthesis & Proposal Generation (Orchestrator step)
Once UC-1 and UC-2 complete, the orchestrator synthesizes both outputs and generates 2–3 distinct product direction proposals for the user to choose from. Each proposal includes a one-paragraph rationale grounded in the research.

- Input: UC-1 research brief + UC-2 feedback synthesis
- Output: 2–3 labelled product direction proposals presented in the CLI
- **This is new orchestrator logic** — not covered by any existing skill. Implemented as a single Claude API call with both research artifacts as context.
- The user selects or refines one proposal before the pipeline continues.

### UC-3: Spec Drafting
Given the confirmed product direction and the research context, the agent generates a product specification document.

- Input: confirmed proposal + UC-1 brief + UC-2 synthesis (injected as context)
- Output: product spec document (.docx)
- Agent: `product-specification` (existing skill)
- **Note:** This skill is interview-driven by design. In the pipeline, the orchestrator runs it in context-injection mode: upstream outputs and the confirmed direction are provided as pre-filled answers, bypassing the interactive interview. This behavior needs to be validated.

### UC-4: User Story Generation
The agent breaks the confirmed product spec into structured epics and user stories.

- Input: product spec from UC-3
- Output: user stories as a structured document (.docx)
- Agent: `product-user-story` (existing skill)
- **New work — Notion integration:** The existing skill outputs a `.docx` file. Pushing user stories to Notion as database rows is net-new development, implemented as a separate connector script called after the skill completes. Implemented in Phase 2.

## Out of Scope (PoC)

- Roadmap fit assessment (`product-roadmap-fit` skill exists but is deferred to a later phase)
- Additional feedback connectors beyond Discord (e.g. Intercom — the existing skill already covers public app store reviews via web search)
- Approval workflows or stakeholder routing beyond the proposal selection gate
- Custom UI — interaction is CLI-first for the PoC

## New Development Required (beyond existing skills)

| Component | Type | Phase |
|---|---|---|
| Custom Python orchestrator | New | Phase 1 |
| Orchestrator synthesis + proposal generation step | New | Phase 1 |
| Discord connector script | New | Phase 2 |
| Notion connector script | New | Phase 2 |
| Observability layer (latency, cost, handoff metrics) | New | Phase 3 |

## Success Criteria

| Metric | Target |
|---|---|
| UC-1 and UC-2 run in parallel from a single prompt | Phase 1 |
| Orchestrator presents 2–3 grounded proposals after research | Phase 1 |
| Spec and user stories generated after user confirms a direction | Phase 1 |
| User stories appear in Notion after a single end-to-end run | Phase 2 |
| Discord feedback included in UC-2 synthesis | Phase 2 |
| Per-task cost and latency tracked and attributable per agent | Phase 3 |
