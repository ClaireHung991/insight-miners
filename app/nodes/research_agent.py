"""Research Agent — LlmAgent with web search.

Receives: topic only (data minimization).
Produces: structured research materials (JSON).

Contract ref: Agent-Contracts-Reference.md §4 (Research Agent row)
"""

from pathlib import Path

from google.adk.agents import LlmAgent

from app import credentials


def _load_prompt(name: str) -> str:
    """Load a prompt file from app/prompts/, stripping YAML frontmatter."""
    prompt_path = Path(__file__).parent.parent / "prompts" / f"{name}.md"
    text = prompt_path.read_text()
    if text.startswith("---"):
        end = text.index("---", 3)
        text = text[end + 3:].strip()
    return text


def web_search(query: str) -> str:
    """Search the web using DuckDuckGo and return top results.

    Args:
        query: The search query string.

    Returns:
        Formatted string of top search results with title, URL, and snippet.
    """
    from duckduckgo_search import DDGS
    results = []
    with DDGS() as ddgs:
        for r in ddgs.text(query, max_results=8):
            results.append(f"Title: {r['title']}\nURL: {r['href']}\nSnippet: {r['body']}\n")
    return "\n---\n".join(results) if results else "No results found."


_prompt = _load_prompt("research_agent")

research_agent = LlmAgent(
    name="research_agent",
    model=credentials.research_model,
    instruction=_prompt,
    tools=[web_search],
    output_key="research_materials",
    rerun_on_resume=True,
)

