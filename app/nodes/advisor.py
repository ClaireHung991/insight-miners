"""Advisor Agent — synthesizes finished outputs into a recommendation brief.

Receives: finished report and/or formatted transcript from state.
Produces: recommendation brief with prioritized recommendations + impact/effort matrix.

Contract ref: Agent-Contracts-Reference.md §4 (Advisor row)
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


_prompt = _load_prompt("advisor")

advisor_agent = LlmAgent(
    name="advisor_agent",
    model=credentials.recommendation_model,
    instruction=_prompt,
    output_key="recommendation_result",
    rerun_on_resume=True,
)
