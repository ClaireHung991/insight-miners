"""Writer Agent — LlmAgent that drafts reports from research materials.

Receives: research_materials (from Research Agent output).
Produces: draft Markdown report.

Contract ref: Agent-Contracts-Reference.md §4 (Writer Agent row)
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


_prompt = _load_prompt("writer")

writer_agent = LlmAgent(
    name="writer_agent",
    model=credentials.writer_model,
    instruction=_prompt,
    output_key="draft_report",
    rerun_on_resume=True,
)
