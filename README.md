# Product Agent 

## Intro

'Product Agent' helps product leads, product managers and senior management working on strategy to take decisions or get in depth insights about adding new products or features into their existing portfolio.

## Concept

We want to build a working multi-agent system where Claude agents orchestrate existing product management workflows. There are already 5 Claude skills defined in their folders (product-analysis, product-user-feedback, product-roadmap-fit, product-specification, product-user-story) you've been using in the Claude.ai chat application. The goal is to turn this into a more ambitious PoC:

* A coordinated agent system that handles end-to-end product workflows: research → user feedback synthesis → opportunity sizing → roadmap input → spec drafting → user story generation
* Instread of using an MCP server for tool integration, use skills with scripts instead. The integrations requried for now are: Notion for task creation and monitorig, Discord to read most recent user feedback (more 'connectors' will be added at a later phase)
* Including agent observability: latency tracking, cost attribution per task, agent-to-agent handoff quality metrics

