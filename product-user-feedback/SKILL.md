---
name: product-user-feedback
description: "Analyzes user feedback about a product or feature in online forums and product review platforms. Then runs a structured PRO vs. AGAINST agent debate grounded in real community data, and produces a ranked minimum feature list to convert skeptics. Trigger whenever the user asks “what is the user feedback about this product/feature?” \"Would [persona] be interested in [product/feature]?\", \"What would it take to convince [audience] to adopt [X]?\"."
---

# Step 0: Extract inputs
Identify the Persona we're analyzing (e.g., "backend engineer", "privacy-conscious user", "small business owner")
Identify the Product/Feature: "GitHub Copilot", "WhatsApp payment features", "Shopify AI tools")
If no Persona is specified, run the analysis without a specific persona in mind. If the request is not clear, ask for clarification


# Step 1: General Reddit intelligence gathering


Run these searches in parallel to get broad coverage (use web search with site:reddit.com ):
site:reddit.com [persona] [product] — general overlap
site:reddit.com [product] review OR experience OR thoughts — general sentiment
site:reddit.com [product] hate OR problem OR issue OR disappointed — objections and pain points
site:reddit.com [product] love OR great OR switched OR recommend — advocates and wins
site:reddit.com r/[persona-relevant-subreddit] [product] — persona's own community (infer the most relevant subreddit from the persona, e.g. r/webdev for developers, r/smallbusiness for business owners)
For each search result, extract:
The actual user statements (what people say, not just titles)
Recurring themes across multiple posts/comments
Specific features or missing features that are mentioned
The emotional tone (frustrated, enthusiastic, indifferent)
Aim for at least 10-15 distinct data points before moving on. If initial searches are sparse, try alternative search terms.

# Step 2: Specific forums intelligence gathering
Find out if there are specific forums outside reddit where users may express experiences about this product.

Look for the top 2 forums out of reddit, and run the same type of queries as with reddit, and summarize the feedback with the same structure as with reddit data:

The actual user statements (what people say, not just titles)
Recurring themes across multiple posts/comments
Specific features or missing features that are mentioned
The emotional tone (frustrated, enthusiastic, indifferent)


# Step 3: Reviews
Figure out if this product feature is applicable for platform reviews (like stores: Android, iOS, Chrome), trustpilot, etc

If it is applicable, dig through the review to summarize the product feedback, trying to get as close as possible as the format from previous points. If there is not much feedback, do a small summary.

# Step 4: Synthesize findings
Before the debate, organize what you've found from all the different sources into two clear camps. This is the raw material both agents will draw from.
PRO signals (reasons the persona would be interested):
List specific benefits mentioned 
Note which pain points the product solves that this persona actually has
Highlight any viral moments, success stories, or enthusiastic testimonials
AGAINST signals (reasons the persona would resist):
List specific objections, frustrations, dealbreakers
Note missing features that were requested
Highlight trust issues, pricing concerns, workflow friction, ethical objections
Present this synthesis to the user before the debate, formatted clearly. Label it "Intelligence Summary". This step is important — it shows the user where the debate data comes from and lets them spot anything missing.

Step 5: The debate
Now instantiate two agents and run them through a structured debate. Both agents are grounded entirely in the intelligence summarized from Step 4 — no speculation, no generic claims.
PRO agent: Advocates for the product from the perspective of what genuinely benefits the persona. They argue based on real use cases and documented wins. They also propose specific features or changes to address AGAINST's objections.
AGAINST agent: Represents the skeptical persona. They raise concrete objections grounded in evidence. They are not a strawman — they are a reasonable, thoughtful person who has seen the criticism and isn't convinced yet. They shift position only when a specific objection is genuinely addressed.
Debate format (up to 5 rounds):
Round N: PRO: [argument or response to AGAINST's last point, proposes feature/change if needed] AGAINST: [raises or maintains specific objection, or concedes a point if genuinely addressed] Status: [which objections remain unresolved]
Convergence rules:
AGAINST concedes a point only when PRO has proposed something that directly addresses it with enough specificity
The debate ends when either: (a) AGAINST is fully convinced, (b) 5 rounds pass, or (c) a clear stalemate is reached on specific points
Don't force artificial resolution — a stalemate is a valid and informative outcome
Render the debate as a readable dialogue, not as a list of bullet points. It should feel like a real exchange.


Step 6: Output — minimum feature list
After the debate, produce the final deliverable: what would it actually take to convert the AGAINST persona?
Structure the output as:
Minimum feature set to convert a skeptic. with a maximum of 6 features.
For each feature/change:
What: the specific thing needed
Why it matters: the exact objection it resolves (tied to evidence)
Priority: Must-have / Nice-to-have
Rank by impact — the top items are the ones AGAINST was most insistent about.
Also include a short Verdict paragraph: given the current state of the product (before any hypothetical changes), would most members of this persona adopt it? Be direct.


# Output format summary
Your final response should have four labeled sections:
Intelligence Summary — PRO and AGAINST signals from community data
Minimum Feature List — ranked table of what would convert a skeptic
Verdict — a direct, honest assessment of current product-market fit for this persona
Keep the tone analytical and honest. Don't oversell the product or the method. If data found is sparse for a niche product, say so — it's meaningful signal that the community hasn't formed strong opinions yet.