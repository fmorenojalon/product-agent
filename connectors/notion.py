"""Notion connector — Phase 1 prints to stdout. Phase 2 replaces with real API."""


def push_stories(stories: str) -> None:
    print("[ Notion ] Mock — stories would be pushed to Notion in Phase 2.")
    print(f"           ({len(stories.splitlines())} lines of story content ready to sync)\n")
