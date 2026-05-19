"""Discord connector — Phase 1 returns fixture data. Phase 2 replaces with real API."""


def fetch_feedback(channels: list[str] | None = None) -> str:
    return """[MOCK — Phase 2 will replace this with live Discord data]

#product-feedback
- "Onboarding took 20 min to figure out, needs a guided tour"
- "Love the core idea but the UI feels dated vs competitors"
- "Would pay double if it integrated with Notion natively"

#feature-requests
- "Keyboard shortcuts please, I live in the terminal"
- "API access would be a game changer for our team"
- "Dark mode is the only thing stopping us from switching"
"""
