"""Shared Editor — parameterized by role (report_editor / transcript_editor).

Two instances, two prompt sets, one codebase.
- Editor A (report_editor): reviews draft reports, returns RevisionMessage.
- Editor B (transcript_editor): formats transcripts, emits topic tree.

Contract ref: Agent-Contracts-Reference.md §4 (Editor rows + pinned revision shape)
"""

from pathlib import Path

from google.adk.agents import LlmAgent

from app import credentials
from app.envelope import RevisionMessage


def _load_prompt(name: str) -> str:
    """Load a prompt file from app/prompts/, stripping YAML frontmatter."""
    prompt_path = Path(__file__).parent.parent / "prompts" / f"{name}.md"
    text = prompt_path.read_text()
    if text.startswith("---"):
        end = text.index("---", 3)
        text = text[end + 3:].strip()
    return text


def create_editor(role: str) -> LlmAgent:
    """Create an Editor agent for the given role.

    Args:
        role: "report_editor" or "transcript_editor"

    Returns:
        An LlmAgent configured with the appropriate prompt and output schema.
    """
    prompt = _load_prompt(role)

    if role == "report_editor":
        return LlmAgent(
            name="report_editor",
            model=credentials.editor_model,
            instruction=prompt,
            output_schema=RevisionMessage,
            output_key="editor_a_result",
            rerun_on_resume=True,
        )
    elif role == "transcript_editor":
        # Transcript editor does NOT use RevisionMessage — it produces
        # a formatted transcript + topic tree (see transcript_editor prompt).
        return LlmAgent(
            name="transcript_editor",
            model=credentials.editor_model,
            instruction=prompt,
            output_key="editor_b_result",
            rerun_on_resume=True,
        )
    else:
        raise ValueError(f"Unknown editor role: {role}")


# Pre-built instances for direct import
report_editor = create_editor("report_editor")
transcript_editor = create_editor("transcript_editor")
