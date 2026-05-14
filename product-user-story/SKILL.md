---
name: product-user-story
description: Takes a PRD or product specification and breaks it down into epics and fully defined user stories ready for engineering execution. Each story follows a strict format with scope ("As a [persona], I want to..., So that..."), background, designs, out-of-scope, and acceptance criteria in "Given, When, Then" format grouped by functional area. Use whenever the user wants to "break down a feature into stories", "write user stories for X", "create epics and stories from this PRD", "turn this spec into Jira tickets", "define acceptance criteria", or any request to decompose a product specification into engineering-ready work items. Also trigger on "write stories", "epic breakdown", "story writing", "AC for this feature", or "prepare tickets for engineering".
---

# Product User Story Generator

This skill takes a product specification (PRD, feature spec, or equivalent) and produces a complete set of epics and user stories ready for engineering execution. Every story follows the team's Jira guidelines, with properly structured scope, acceptance criteria, and dependencies.

## When to use

Use this whenever someone has a product specification and needs it translated into engineering-ready epics and stories. Typical signals: "break this down into stories", "write user stories for this feature", "create the epic/story structure", "turn this PRD into tickets", "define the AC", or any request to go from product spec to engineering work items.

## Differentiation from other skills

- **product-specification** captures *what* a feature is (the PRD). This skill takes that PRD and produces *how* it gets delivered — the epics, stories, and acceptance criteria that engineering executes against.
- **product-roadmap-fit** evaluates *whether* to build something. This skill assumes the decision is made and focuses on structuring the work.

## Step 1 — Ingest the product specification

Read the specification provided by the user. It may be a PRD document, a feature brief, a conversation summary, or even a rough description. Extract:

1. **Feature overview**: What is being built, and what problem does it solve?
2. **Target personas**: Who are the users?
3. **User flows**: What are the main functional flows?
4. **Scope boundaries**: What's explicitly in and out of scope?
5. **Dependencies**: Technical and non-technical prerequisites.
6. **Delivery phases**: If the spec defines phases, each phase typically maps to one epic.
7. **Designs**: Are there designs available, referenced, or needed?
8. **Metrics/tracking**: Are there analytics or tracking requirements?

## Step 2 — Clarify before writing (mandatory)

Before generating any epics or stories, ask the user about anything ambiguous or missing. This is a mandatory gate — do not generate stories based on assumptions about decisions that belong to the product lead.

**Always ask about these if not already covered in the spec:**

- **Designs**: Does the user want design placeholders included in stories (for a later Design refinement), or should designs be skipped for now? If designs exist, ask the user to provide or reference them.
- **API specifications**: If the feature involves APIs, should the skill propose an API structure, or does the user want to confirm API details before stories are written?
- **Analytics/tracking**: Should tracking requirements (e.g., PostHog events) be included as sections within stories, or as separate linked tasks?
- **Technical stories**: Does the user want engineering-only tasks (infrastructure, migrations, refactoring) called out separately, or left for engineering to define post-refinement?
- **Views/platforms**: Which views or platforms are in scope (e.g., Full view, Pop-up, Mobile, Extension, Web)?

**General rule**: When the specification doesn't explicitly address a decision that affects how stories are written, ask. Do not invent scope — the user is the product authority. Group questions in a single message (3–6 questions max). The user may say "skip" or "your call" for any item; accept that and note the assumption in the story.

## Step 3 — Structure epics

Map the specification into epics following these rules:

### Epic structure

Each epic represents a coherent delivery phase or functional area. An epic must contain:

1. **Title**: Clear, descriptive — the scope should be identifiable from the titles of the stories it contains.
2. **Summary**: 2–3 sentences describing the epic's scope and the value it delivers.
3. **Problem being solved**: What user or business problem this epic addresses.
4. **High-level scope**: What's included in this epic, stated as a list of functional areas or flows.
5. **Expected outcomes**: Measurable business or user outcomes.
6. **Dependencies**: Cross-epic or external dependencies.
7. **Stories list**: The user stories contained in this epic (generated in Step 4).

### Epic decomposition principles

- Each epic should deliver standalone value — it should be releasable on its own, even if subsequent epics enhance it.
- If the spec has delivery phases, map one epic per phase.
- If there are no explicit phases, group by functional area (e.g., "Onboarding flow", "Transaction display", "Settings & configuration").
- Technical-only work (migrations, infrastructure) gets its own epic with a summary, problem being solved, scope, and expected outcomes from a developer/infrastructure POV.
- Minor adjustments (copy changes, style tweaks) are filed as tasks, not stories.

## Step 4 — Write user stories

For each epic, produce the full set of user stories. Each story captures a single user-facing functionality.

### Story format

Every story must follow this exact structure. Use a table for the top section:

```
| User Story | Files and Documentation |
|------------|------------------------|
| [Scope statement — see below] | Designs: [link or "Pending design refinement" or "N/A"] |
|            | Other: [links to related docs, specs, APIs] |
```

Then the following sections in order:

#### Background (optional)
Provides context for the story. **Omit if the reasoning is clearly inherited from the epic.** When included, explain *why* this story exists — what current behavior is lacking, what changed, what technical context is relevant. Include screenshots, links, or references to current behavior when helpful.

See examples of good backgrounds:
- "Current DApp dialogue doesn't represent all native assets, causing that in some scenarios it is not possible to understand what you're actually signing."
- "Collateral Output is an upgrade to the existing collateral feature that allows to specify the collateral required when calling a smart contract..."

#### Scope
One or more scope statements in this exact format:

```
As a [persona],
I want to [action],
So that [outcome].
```

A story may have multiple scope statements when it serves more than one persona or addresses closely related needs within the same functionality. Each scope statement is a separate block.

See examples:
- Simple: "As a user onboarding in Lace-beta and choosing to create a new wallet, I want that a Midnight wallet is created... So I can operate in the Midnight testnet network"
- Multi-scope: A story with one scope for "user reviewing a DApp Tx request" and another for "user reading Tx details", when both are addressed by the same implementation.

#### Notes (optional)
Constraints, decisions, or implementation guidance that don't belong in AC but that engineering needs to know. Use bullet points. Examples:
- "Develop it behind a feature flag"
- "Only 24 words seed scheme is supported"
- "If the collateral is provided by a foreign address there is no need to add that information to the user"

#### Out of Scope (optional)
Clearly state what is **not** included. This prevents scope creep during refinement. Examples:
- "Mempool status"
- "Show UTXO information"

#### Views (when applicable)
List the views or contexts where this story applies:
- Full view
- Pop-up
- Mobile
- etc.

#### Designs (when applicable)
If designs are available, include inline screenshots or reference links (Figma, etc.) with a note: "More details in [Figma link]".

If designs are pending, write: "Pending design refinement session between Product and Design."

If not applicable, omit this section.

Show both states when relevant (e.g., collapsed and extended views, success and failure states, light and dark mode).

#### Acceptance Criteria (AC)

The AC is the contract between Product and Engineering. It serves as the QA checklist. **This is the most critical section of each story.**

**Format rules:**

1. **Use "Given, When, Then" format.** The first statement in each group uses the full form. Subsequent statements in the same group may abbreviate to "When..., Then..." carrying context from the first.

2. **Group AC by functional area or scenario.** Each group gets a named header (e.g., "Signed status", "From/to show only asset diffs", "Deposit", "Group by addresses"). This makes it scannable for QA.

3. **Bold the differentiating parts** when multiple statements share similar structure. This is critical for QA readability. Examples:
   - "Given the user has signed a Tx..., When the dapp has not called the submission endpoint... And the Tx **has not expired**, Then **in the activity detail** of the Tx there is a 'signed' status..."
   - "When the dapp has not called the submission endpoint... And the Tx **has expired**, Then Lace **removes the existing record** from the activity feed"

4. **Every functional point must be covered.** AC defines the minimum requirements. If a scenario isn't in the AC, it's not required. Think through:
   - Happy path
   - Edge cases and error states
   - Boundary conditions (e.g., "When the Tx has more than the **securityParam value** (currently 2160) confirmations...")
   - Different contexts/views where behavior may differ (activity feed vs. activity detail, DApp request vs. Tx history)

5. **One AC statement per testable behavior.** Don't combine multiple verifiable outcomes in a single statement — split them so QA can pass/fail each independently.

**AC example (grouped, with bold differentiation):**

```
## Signed status

- Given the user has signed a Tx through the dapp bridge, When the dapp has not called the
  submission endpoint nor submitted the Tx through their own provider And the Tx **has not expired**,
  Then Lace adds a Tx record to the **activity feed**, showing a 'signed' status following figma design,
  And there is a tooltip with the text specified above

- When the dapp has not called the submission endpoint nor submitted the Tx through their own
  provider And the Tx **has not expired**, Then **in the activity detail** of the Tx there is a 'signed'
  status, And there is a tooltip with the text specified above

- When the dapp has not called the submission endpoint nor submitted the Tx through their own
  provider And the Tx **has expired**, Then Lace **removes the existing record** from the activity feed

## Submitted status

- Given the user has signed a Tx, When the Tx has been submitted to the Cardano provider but the
  Tx has not been validated yet, Then Lace shows a record of the Tx in the **activity feed** with the
  status 'Submitted', following figma design, And there is a tooltip with the text specified above

- When the Tx has been submitted to the Cardano provider but the Tx has not been validated yet,
  Then **in the activity detail** of the Tx there is a 'Submitted' status, And there is a tooltip with
  the text specified above
```

#### Tracking / Metrics (when applicable)
If the spec defines tracking requirements:
- Include them as a section in the story, OR
- Note: "Tracking: dedicated task to be linked — see [PostHog Event Dictionary / analytics spec]"

#### Linked stories / dependencies (when applicable)
Note which other stories this one depends on or relates to:
- "Blocked by: [Story title — e.g., 'Resolve totalCollateral and collateralReturn from db-sync']"
- "Implements: [Story title]"
- "Related: [Story title]"

### Story sizing guidance

- **One story = one user-facing functionality.** If a story covers two independent flows, split it.
- **Large stories** that span many AC groups may note: "This story is implemented by the completion of its linked tasks, no development happens for this story directly. AC is defined in linked tasks." — but this is the exception, not the norm. Prefer splitting into smaller stories.
- **Minor adjustments** (copy updates, style changes) should be tasks, not stories.

## Step 5 — Present the output

Present the complete epic/story structure as a **downloadable .docx document** using the docx skill, organized as:

1. **Overview**: Summary of the epic/story structure, total count of epics and stories.
2. **Per epic**: Epic details (summary, problem, scope, outcomes, dependencies), followed by each story in full format.
3. **Dependency map**: A summary of cross-story and cross-epic dependencies.
4. **Open questions**: Any items flagged during Step 2 that remain unresolved.

Also provide a brief summary in chat listing the epics and story titles for quick orientation.

## Style guidance

- **Write from the user's perspective.** Scope statements and AC should be understandable from a business standpoint, not an implementation standpoint. "Then the user sees a confirmation status" is correct; "Then the API returns a 200 with status=confirmed" belongs in an engineering task, not a story.
- **Be specific in AC.** Vague AC like "the feature works correctly" is useless. Every AC statement should be testable by QA without interpretation.
- **Don't invent functional requirements.** The stories must reflect the specification provided. If you think a flow is missing, ask the user — don't add it silently.
- **Bold is a tool, not decoration.** Only bold the parts of AC statements that differentiate them from sibling statements in the same group.
- **Flag uncertainty.** If a story rests on an assumption (e.g., "Assuming the API returns X format — confirm with user"), mark it visibly so it gets addressed in refinement.
