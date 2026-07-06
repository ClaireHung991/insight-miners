"""Orchestrator node — Tier 1/Tier 2 validation, clarification loop, routing.

This module provides:
- validate_tier1: structural check (deterministic, no LLM)
- tier2_agent: LlmAgent for semantic sufficiency checking
- handle_tier2_result: processes Tier 2 output, manages clarification rounds
- route_pipelines: fans out to Research/Interview pipelines with data-minimization
- deliver_results: collects finished outputs and packages for frontend

Contract refs:
  Agent-Contracts-Reference.md §1-§5
  Orchestrator-Frontend-Contract.md §1-§4
"""

import json
import uuid
from pathlib import Path
from typing import Any

from google.adk.agents.context import Context
from google.adk.events.event import Event
from google.adk.workflow import node
from pydantic import BaseModel

from app import db
from app.envelope import Envelope


# ── Pydantic models for workflow I/O ──────────────────────────────────────────

class SubmissionRequest(BaseModel):
    """Matches Orchestrator-Frontend-Contract §1."""
    want_report: bool = False
    topic: str | None = None
    want_transcript: bool = False
    transcript_file: str | None = None  # file path or base64 reference
    interview_purpose: str | None = None
    interview_background: str | None = None
    participant_count: int | None = None

    want_mindmap: bool = False
    want_recommendation: bool = False


class ArtifactStatus(BaseModel):
    """Per-artifact status for the status response."""
    report: str | None = None       # "generating" | "ready" | "failed" | None
    transcript: str | None = None
    mindmap: str | None = None
    recommendation: str | None = None


# ── Prompt loading ────────────────────────────────────────────────────────────

def _load_prompt(name: str) -> str:
    """Load a prompt file from app/prompts/, stripping YAML frontmatter."""
    prompt_path = Path(__file__).parent.parent / "prompts" / f"{name}.md"
    text = prompt_path.read_text()
    # Strip YAML frontmatter (--- ... ---)
    if text.startswith("---"):
        end = text.index("---", 3)
        text = text[end + 3:].strip()
    return text


# ── Tier 1 — Structural Validation ───────────────────────────────────────────

@node(rerun_on_resume=True)
async def validate_tier1(ctx: Context, node_input: Any):
    """Deterministic structural check — no LLM call.

    Checks:
    1. At least one of want_report / want_transcript is true
    2. want_recommendation only if rule 1 satisfied
    3. want_mindmap only if want_transcript is true
    4. If want_report: topic is non-empty
    5. If want_transcript: transcript_file present, interview_purpose + business_context non-empty
    6. Input-type routing: detect audio vs text by file extension
    """
    # Purge expired incomplete requests (check-on-access, contract §5)
    db.purge_expired()

    # Parse submission — node_input is types.Content from START
    # We store the parsed request in state for reuse
    if ctx.resume_inputs:
        # Resuming from a clarification round — merge answers into existing request
        request_dict = ctx.state.get("request", {})
        for key, value in ctx.resume_inputs.items():
            if key.startswith("clarify_"):
                field_name = key.replace("clarify_", "")
                request_dict[field_name] = value
        ctx.state["request"] = request_dict
    elif ctx.state.get("request"):
        # State was pre-seeded by the API (fast-path — no parse needed)
        request_dict = ctx.state["request"]
    else:
        # First submission — parse from user message JSON
        text = ""
        if hasattr(node_input, "parts"):
            for part in node_input.parts:
                if hasattr(part, "text") and part.text:
                    text = part.text
                    break

        try:
            request_dict = json.loads(text)
        except (json.JSONDecodeError, TypeError):
            yield Event(
                output={"status": "error", "message": "Invalid request format. Expected JSON."},
                route="rejected",
            )
            return

        ctx.state["request"] = request_dict

    req = SubmissionRequest(**request_dict)

    # Generate request_id if not present
    if "request_id" not in ctx.state:
        ctx.state["request_id"] = f"req_{uuid.uuid4().hex[:12]}"

    errors = []

    # Rule 1: at least one capability selected
    if not req.want_report and not req.want_transcript:
        errors.append("Select Report or Transcript to continue.")

    # Rule 2: C requires A or B
    if req.want_recommendation and not req.want_report and not req.want_transcript:
        errors.append("Recommendation requires at least one of Report or Transcript.")

    # Rule 3: mindmap requires transcript
    if req.want_mindmap and not req.want_transcript:
        errors.append("Mind map requires Transcript to be selected.")

    # Rule 4: if report selected, topic required
    if req.want_report and not (req.topic and req.topic.strip()):
        errors.append("Add a topic to research.")

    # Rule 5: if transcript selected, file + purpose + context required
    if req.want_transcript:
        if not req.transcript_file:
            errors.append("Upload an audio or text file.")
        if not (req.interview_purpose and req.interview_purpose.strip()):
            errors.append("Tell us the interview's purpose — this helps format it well.")
        if not (req.interview_background and req.interview_background.strip()):
            errors.append("Add some background context (company, product, etc.).")

    if errors:
        yield Event(
            output={"status": "error", "errors": errors},
            route="rejected",
        )
        return

    # Determine input type for transcript routing
    if req.want_transcript and req.transcript_file:
        ext = Path(req.transcript_file).suffix.lower()
        audio_exts = {".mp3", ".wav", ".m4a"}
        ctx.state["input_is_audio"] = ext in audio_exts

    # Store parsed request fields in state for downstream nodes
    ctx.state["want_report"] = req.want_report
    ctx.state["want_transcript"] = req.want_transcript
    ctx.state["want_recommendation"] = req.want_recommendation
    ctx.state["want_mindmap"] = req.want_mindmap

    yield Event(output=request_dict, route="route")



# ── Pipeline Routing ──────────────────────────────────────────────────────────

def route_pipelines(ctx: Context, node_input: Any):
    """Fan out to the appropriate pipeline(s) based on user selections.

    Returns an Event with route indicating which pipelines to run.
    Also builds scoped envelopes per data-minimization contract (§4).
    """
    request = ctx.state.get("request", {})
    request_id = ctx.state.get("request_id", "unknown")
    quality_flags = ctx.state.get("quality_flags", [])

    want_report = ctx.state.get("want_report", False)
    want_transcript = ctx.state.get("want_transcript", False)

    # Build scoped envelopes — data minimization (contract §4)
    if want_report:
        research_envelope = Envelope.create(
            request_id=request_id,
            content={"topic": request.get("topic", "")},
            source_agent="orchestrator",
        )
        # Add any quality flags
        for qf in quality_flags:
            research_envelope = research_envelope.add_flag(**qf)
        ctx.state["research_envelope"] = research_envelope.model_dump()

    if want_transcript:
        transcript_content = {
            "raw_transcript": request.get("transcript_file", ""),
            "interview_purpose": request.get("interview_purpose", ""),
            "interview_background": request.get("interview_background", ""),
            "speaker_info": f"{request.get('participant_count', 'unknown')} speakers",
        }
        transcript_envelope = Envelope.create(
            request_id=request_id,
            content=transcript_content,
            source_agent="orchestrator",
        )
        for qf in quality_flags:
            transcript_envelope = transcript_envelope.add_flag(**qf)
        ctx.state["transcript_envelope"] = transcript_envelope.model_dump()

    # Initialize artifact status tracking
    artifacts = {
        "report": "generating" if want_report else None,
        "transcript": "generating" if want_transcript else None,
        "summary": "generating" if want_transcript else None,
        "mindmap": "generating" if ctx.state.get("want_mindmap") else None,
        "recommendation": "generating" if ctx.state.get("want_recommendation") else None,
    }
    ctx.state["artifacts"] = artifacts
    ctx.state["outputs"] = {
        "report": None,
        "transcript": None,
        "summary": None,
        "mindmap": None,
        "recommendation": None,
    }

    # Route to appropriate pipeline(s)
    if want_report and want_transcript:
        return Event(output=request, route="both")
    elif want_report:
        return Event(output=request, route="research_only")
    else:
        return Event(output=request, route="interview_only")


# ── Delivery / Results Collection ─────────────────────────────────────────────

def deliver_results(ctx: Context, node_input: Any):
    """Package final results for the frontend.

    Matches Orchestrator-Frontend-Contract §3 (Status Response).
    """
    request_id = ctx.state.get("request_id", "unknown")
    artifacts = ctx.state.get("artifacts", {})
    outputs = ctx.state.get("outputs", {})

    # Clean up any completed incomplete request
    db.delete_incomplete(request_id)

    return Event(
        output={
            "request_id": request_id,
            "artifacts": artifacts,
            "outputs": outputs,
        },
        content=_format_results_content(artifacts, outputs),
    )


def _format_results_content(artifacts: dict, outputs: dict):
    """Format results as types.Content for ADK web UI display."""
    from google.genai import types

    lines = ["## Results\n"]
    for name, status in artifacts.items():
        if status is None:
            continue
        icon = "✅" if status == "ready" else "⏳" if status == "generating" else "❌"
        line = f"- {icon} **{name.title()}**: {status}"
        if status == "ready" and outputs.get(name):
            line += f" — [Download]({outputs[name]})"
        lines.append(line)

    return types.Content(
        role="model",
        parts=[types.Part.from_text(text="\n".join(lines))],
    )
