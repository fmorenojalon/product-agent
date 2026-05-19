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

**Pre-step:** A fast Claude call extracts competitor names and a target persona from the raw idea, so downstream skills receive precise inputs.  
**Phase A — Research (parallel):** Both research agents run simultaneously.  
**Human gate:** The orchestrator synthesizes the research into 2–3 product direction proposals; the user confirms one.  
**Phase B — Specification (sequential):** Spec drafting runs first, then user story generation uses its output.

```
User prompt (idea / hypothesis)
    │
    ├─► [Pre-step] Extract competitors + persona  (Claude API call, ~2s)
    │
    ├─► UC-1: Competitive research       (product-analysis)        ┐ run in
    └─► UC-2: User feedback synthesis    (product-user-feedback)   ┘ parallel
                    │
            [Orchestrator synthesizes both outputs]
                    │
            2–3 product direction proposals presented to user
                    │
              [Human confirms one]
                    │
            UC-3: Spec drafting          (product-specification)
                    │
            UC-4: User story generation  (product-user-story → Notion)
```

## In-Scope Use Cases (PoC)

### Pre-step: Competitor & Persona Extraction
A fast Claude API call interprets the user's raw idea and returns the 2–3 most relevant competitor products to research and the primary target persona. This bridges the gap between a vague idea and the specific inputs the skills expect.

- Input: free-text idea from the user
- Output: `{ competitors: [...], persona: "..." }` (JSON, used internally)
- No skill — single orchestrator Claude call, no tools

### UC-1: Competitive Research
The agent produces a structured research brief covering the competitive landscape, market positioning, and relevant technical and commercial signals for the identified competitors.

- Input: idea + extracted competitor names
- Output: research brief (markdown)
- Agent: `product-analysis` skill (SKILL.md as system prompt via Claude API)
- Tools: Brave Search (web search)
- Runs in parallel with UC-2

### UC-2: User Feedback Synthesis
The agent researches publicly available user feedback on comparable products and distills it into key themes, sentiment signals, and quoted evidence relevant to the idea.

- Input: idea + extracted competitors + persona
- Output: feedback synthesis report (markdown)
- Agent: `product-user-feedback` skill (SKILL.md as system prompt via Claude API)
- Tools: Brave Search (web search)
- Runs in parallel with UC-1
- **New work — Discord connector:** Implemented in Phase 2. Phase 1 uses a mock connector returning fixture data.

### Synthesis & Proposal Generation (Orchestrator step)
Once UC-1 and UC-2 complete, the orchestrator synthesizes both outputs and generates 2–3 distinct product direction proposals. Each proposal includes a short name and rationale grounded in the research.

- Input: UC-1 brief + UC-2 synthesis
- Output: 2–3 labelled proposals printed to CLI
- New orchestrator logic — single Claude API call, no tools, no skill

### UC-3: Spec Drafting
Given the confirmed direction and research context, the agent generates a product specification document.

- Input: confirmed proposal + UC-1 brief + UC-2 synthesis (injected as context)
- Output: product spec (markdown)
- Agent: `product-specification` skill (SKILL.md as system prompt)
- **Context-injection mode:** The skill's interactive interview is bypassed. The orchestrator prepends all upstream context as pre-filled answers and instructs the skill to generate the PRD directly.

### UC-4: User Story Generation
The agent breaks the product spec into structured epics and user stories.

- Input: product spec from UC-3
- Output: epics and user stories (markdown)
- Agent: `product-user-story` skill (SKILL.md as system prompt)
- **Context-injection mode:** The skill's mandatory clarification step is bypassed via the same API-mode instruction.
- **New work — Notion integration:** Implemented in Phase 2. Phase 1 uses a mock connector that prints to stdout.

## Out of Scope (PoC)

- Roadmap fit assessment (`product-roadmap-fit` skill deferred to a later phase)
- Additional feedback connectors beyond Discord (Intercom, etc.)
- Approval workflows or stakeholder routing beyond the proposal selection gate
- Custom UI — interaction is CLI-first

## New Development Required (beyond existing skills)

| Component | Type | Phase |
|---|---|---|
| Custom Python orchestrator | New | Phase 1 |
| Pre-step: competitor + persona extraction | New | Phase 1 |
| Brave Search tool integration | New | Phase 1 |
| Orchestrator synthesis + proposal generation | New | Phase 1 |
| Discord connector script | New | Phase 2 |
| Notion connector script | New | Phase 2 |
| Observability layer (latency, cost, handoff metrics) | New | Phase 3 |

## Success Criteria

| Metric | Target |
|---|---|
| UC-1 and UC-2 run in parallel from a single prompt | Phase 1 |
| Orchestrator presents 2–3 grounded proposals after research | Phase 1 |
| Spec and user stories generated after user confirms a direction | Phase 1 |
| All outputs saved as markdown files in a timestamped output/ folder | Phase 1 |
| User stories appear in Notion after a single end-to-end run | Phase 2 |
| Discord feedback included in UC-2 synthesis | Phase 2 |
| Per-task cost and latency tracked and attributable per agent | Phase 3 |
