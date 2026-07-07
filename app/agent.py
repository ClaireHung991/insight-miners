# ruff: noqa
# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Product Discovery Team — root Workflow agent.

Graph architecture:
  START → validate_tier1 →(route)→ route_pipelines
  validate_tier1 →(rejected)→ deliver_results

  route_pipelines →(research_only)→ research_pipeline → check_advisor
  route_pipelines →(interview_only)→ interview_pipeline → check_advisor
  route_pipelines →(both)→ run_both → check_advisor

  check_advisor →(advisor)→ advisor_stub → deliver_results
  check_advisor →(deliver)→ deliver_results

Routed edges require explicit Edge objects with FunctionNode-wrapped callables.
Unconditional edges can use the 2-tuple shorthand.
"""

from google.adk.apps import App
from google.adk.events.event import Event
from google.adk.workflow import Workflow, Edge, FunctionNode, node
from google.adk.agents.context import Context

from app.nodes.orchestrator import (
    validate_tier1,
    route_pipelines,
    deliver_results,
)

from app.nodes.research_agent import research_agent
from app.nodes.writer_agent import writer_agent
from app.nodes.editor import report_editor

# ── Research Pipeline (Phase 3a) ─────────────────────────────────────────────

MAX_REVISION_ROUNDS = 2


def _call_llm(system_prompt: str, user_message: str, model: str | None = None) -> str:
    """Call OpenAI directly. Returns the text response."""
    from openai import OpenAI
    from app import credentials
    import os

    api_key = os.environ.get("OPENAI_API_KEY", "")
    client = OpenAI(api_key=api_key)
    m = model or credentials.writer_model
    # Strip "openai/" prefix if present — OpenAI client doesn't want it
    if m.startswith("openai/"):
        m = m[len("openai/"):]

    resp = client.chat.completions.create(
        model=m,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ],
    )
    return resp.choices[0].message.content or ""


def _load_prompt(name: str) -> str:
    from pathlib import Path
    p = Path(__file__).parent / "prompts" / f"{name}.md"
    text = p.read_text()
    if text.startswith("---"):
        end = text.index("---", 3)
        text = text[end + 3:].strip()
    return text


async def _research_pipeline(ctx: Context, node_input):
    """Research → Writer → Editor A review loop.

    1. web_search researches the topic
    2. Writer drafts a report from the research materials
    3. Editor A reviews; if not approved, Writer revises (max 2 rounds)
    4. Final report stored in state['outputs']['report']
    """
    from app.nodes.research_agent import web_search
    from app import credentials

    # Step 1: Research the topic
    envelope = ctx.state.get("research_envelope", {})
    topic = envelope.get("content", {}).get("topic", "")

    search_results = web_search(topic)
    research_prompt = _load_prompt("research_agent")
    research_materials = _call_llm(research_prompt, f"Topic: {topic}\n\nSearch results:\n{search_results}", model=credentials.research_model)
    ctx.state["research_materials"] = research_materials

    # Step 2: Writer drafts report
    writer_prompt = _load_prompt("writer")
    draft = _call_llm(writer_prompt, research_materials, model=credentials.writer_model)
    ctx.state["draft_report"] = draft

    # Step 3: Editor A review loop
    editor_prompt = _load_prompt("report_editor")
    for revision_round in range(MAX_REVISION_ROUNDS):
        editor_feedback = _call_llm(editor_prompt, draft, model=credentials.editor_model)
        ctx.state["editor_a_result"] = editor_feedback

        # Simple approval check — if editor says APPROVED or similar, stop
        if any(word in editor_feedback.upper() for word in ["APPROVED", "APPROVE", "LGTM", "LOOKS GOOD"]):
            break

        if revision_round < MAX_REVISION_ROUNDS - 1:
            draft = _call_llm(writer_prompt, f"Revise based on feedback:\n\n{editor_feedback}\n\nOriginal draft:\n{draft}", model=credentials.writer_model)
            ctx.state["draft_report"] = draft

    # Step 4: Store final report
    artifacts = ctx.state.get("artifacts", {})
    outputs = ctx.state.get("outputs", {})
    artifacts["report"] = "ready"
    outputs["report"] = ctx.state.get("draft_report", "# Report generation failed")
    ctx.state["artifacts"] = artifacts
    ctx.state["outputs"] = outputs
    return Event(output={"report": "complete"})



# ── Interview Pipeline (Phase 3b) ────────────────────────────────────────────

async def _interview_pipeline(ctx: Context, node_input):
    """Transcriber → cleaned transcript + summary → optional Miro mind map."""
    import json as _json
    import logging
    import traceback

    from app.nodes.transcriber import transcribe_file
    from app import credentials as _creds

    logger = logging.getLogger(__name__)

    def _fail_all(reason: str):
        """Mark both transcript and summary as failed with a visible error message."""
        artifacts = ctx.state.get("artifacts", {})
        outputs = ctx.state.get("outputs", {})
        for key in ("transcript", "summary"):
            artifacts[key] = "failed"
            outputs[key] = reason
        ctx.state["artifacts"] = artifacts
        ctx.state["outputs"] = outputs

    envelope = ctx.state.get("transcript_envelope", {})
    content = envelope.get("content", {})
    file_path = content.get("raw_transcript", "")
    interview_purpose = content.get("interview_purpose", "") or ctx.state.get("interview_purpose", "")
    interview_background = content.get("interview_background", "") or ctx.state.get("interview_background", "")

    logger.info(f"[interview_pipeline] file_path={file_path!r}")

    if not file_path:
        _fail_all("No file path found in envelope — upload may not have been saved correctly.")
        return Event(output={"transcript": "failed"})

    # ── Step 1: Transcribe ────────────────────────────────────────────────────
    try:
        logger.info(f"[interview_pipeline] Transcribing {file_path}")
        raw_transcript = transcribe_file(file_path)
        logger.info(f"[interview_pipeline] Transcription done — {len(raw_transcript)} chars")
    except Exception as e:
        tb = traceback.format_exc()
        logger.error(f"[interview_pipeline] Transcription failed: {e}\n{tb}")
        _fail_all(f"Transcription error: {e}")
        return Event(output={"transcript": "failed", "error": str(e)})

    ctx.state["raw_transcript"] = raw_transcript

    # ── Step 2a: Cleaned speaker-labelled transcript ──────────────────────────
    try:
        logger.info("[interview_pipeline] Running transcript cleaner...")
        cleaner_prompt = _load_prompt("transcript_cleaner")

        # Build context block so the LLM can identify speakers by name
        context_block = "## Interview Context\n"
        if interview_purpose:
            context_block += f"Purpose: {interview_purpose}\n"
        if interview_background:
            context_block += f"Background: {interview_background}\n"
        context_block += "\n## Raw Transcript\n"

        cleaner_input = context_block + raw_transcript
        transcript_cleaned = _call_llm(cleaner_prompt, cleaner_input, model=_creds.editor_model)
        ctx.state["transcript_cleaned"] = transcript_cleaned
        logger.info(f"[interview_pipeline] Cleaner done — {len(transcript_cleaned)} chars")
    except Exception as e:
        tb = traceback.format_exc()
        logger.error(f"[interview_pipeline] Cleaner LLM failed: {e}\n{tb}")
        transcript_cleaned = f"[Transcript cleaning failed: {e}]"
        ctx.state["transcript_cleaned"] = transcript_cleaned

    # ── Step 2b: Interview summary ────────────────────────────────────────────
    try:
        logger.info("[interview_pipeline] Running transcript editor (summary)...")
        transcript_editor_prompt = _load_prompt("transcript_editor")
        editor_result_raw = _call_llm(transcript_editor_prompt, raw_transcript, model=_creds.editor_model)
        ctx.state["editor_b_result"] = editor_result_raw
        logger.info(f"[interview_pipeline] Editor done — {len(editor_result_raw)} chars")
    except Exception as e:
        tb = traceback.format_exc()
        logger.error(f"[interview_pipeline] Summary LLM failed: {e}\n{tb}")
        editor_result_raw = f"[Summary generation failed: {e}]"
        ctx.state["editor_b_result"] = editor_result_raw

    # Parse JSON if editor returned structured output
    topic_tree = []
    formatted_summary = editor_result_raw
    if isinstance(editor_result_raw, str):
        try:
            parsed = _json.loads(editor_result_raw)
            formatted_summary = parsed.get("formatted_transcript", editor_result_raw)
            topic_tree = parsed.get("topic_tree", [])
        except (_json.JSONDecodeError, TypeError):
            formatted_summary = editor_result_raw

    # ── Store results ─────────────────────────────────────────────────────────
    artifacts = ctx.state.get("artifacts", {})
    outputs = ctx.state.get("outputs", {})
    artifacts["transcript"] = "ready"
    outputs["transcript"] = transcript_cleaned
    artifacts["summary"] = "ready"
    outputs["summary"] = formatted_summary

    # ── Step 3: Optional Miro mind map ────────────────────────────────────────
    if ctx.state.get("want_mindmap") and topic_tree:
        try:
            from app.nodes.miro_skill import create_mindmap
            board_url = await create_mindmap(topic_tree)
            artifacts["mindmap"] = "ready"
            outputs["mindmap"] = board_url
        except Exception as e:
            logger.error(f"[interview_pipeline] Miro mind map failed: {e}")
            artifacts["mindmap"] = "failed"
            outputs["mindmap"] = f"Mind map error: {e}"
    elif ctx.state.get("want_mindmap"):
        artifacts["mindmap"] = "failed"
        outputs["mindmap"] = "No topic tree available for mind map"

    ctx.state["artifacts"] = artifacts
    ctx.state["outputs"] = outputs
    logger.info("[interview_pipeline] Complete.")
    return Event(output={"transcript": "complete", "summary": "complete"})





async def _run_both(ctx: Context, node_input):
    """When A+B selected, run both pipelines concurrently."""
    import asyncio
    await asyncio.gather(
        _research_pipeline(ctx, node_input),
        _interview_pipeline(ctx, node_input),
    )
    return Event(output={"research": "complete", "interview": "complete"})


def _check_advisor(ctx: Context, node_input):
    """After pipelines complete, route to Advisor if requested, else deliver."""
    if ctx.state.get("want_recommendation"):
        return Event(output=node_input, route="advisor")
    return Event(output=node_input, route="deliver")


async def _run_advisor(ctx: Context, node_input):
    """Advisor Agent — synthesize outputs into a recommendation brief (Phase 4)."""
    from app import credentials as _creds

    outputs = ctx.state.get("outputs", {})

    # Build advisor input with untrusted content delimiters
    sections = []
    if outputs.get("report"):
        sections.append(f"<research_report>\n{outputs['report']}\n</research_report>")
    if outputs.get("transcript"):
        sections.append(f"<formatted_transcript>\n{outputs['transcript']}\n</formatted_transcript>")

    advisor_input = "\n\n".join(sections) if sections else "No completed outputs available."
    advisor_prompt = _load_prompt("advisor")
    rec_result = _call_llm(advisor_prompt, advisor_input, model=_creds.recommendation_model)

    # Store recommendation
    artifacts = ctx.state.get("artifacts", {})
    artifacts["recommendation"] = "ready"
    outputs["recommendation"] = rec_result
    ctx.state["artifacts"] = artifacts
    ctx.state["outputs"] = outputs
    return Event(output={"recommendation": "complete"})


# ── Wrap as FunctionNodes (required for Edge objects) ─────────────────────────

research_node = FunctionNode(func=_research_pipeline, name="research_pipeline", rerun_on_resume=True)
interview_node = FunctionNode(func=_interview_pipeline, name="interview_pipeline", rerun_on_resume=True)
run_both_node = FunctionNode(func=_run_both, name="run_both_pipelines", rerun_on_resume=True)
check_advisor_node = FunctionNode(func=_check_advisor, name="check_advisor")
advisor_node = FunctionNode(func=_run_advisor, name="advisor", rerun_on_resume=True)

# Orchestrator nodes — wrap those that participate in routed edges
validate_tier1_node = validate_tier1  # already a @node-decorated FunctionNode
route_node = FunctionNode(func=route_pipelines, name="route_pipelines")
deliver_node = FunctionNode(func=deliver_results, name="deliver_results")


# ── Workflow Definition ───────────────────────────────────────────────────────

root_agent = Workflow(
    name="product_discovery_team",
    description=(
        "Multi-agent product discovery support tool. Validates requests, "
        "routes to Research and/or Interview pipelines, and optionally "
        "synthesizes an Advisor recommendation."
    ),
    edges=[
        # ── Orchestrator validation ──
        ("START", validate_tier1_node),
        Edge(from_node=validate_tier1_node, to_node=route_node, route="route"),
        Edge(from_node=validate_tier1_node, to_node=deliver_node, route="rejected"),

        # ── Pipeline dispatch ──
        Edge(from_node=route_node, to_node=research_node, route="research_only"),
        Edge(from_node=route_node, to_node=interview_node, route="interview_only"),
        Edge(from_node=route_node, to_node=run_both_node, route="both"),

        # ── All pipelines converge on check_advisor ──
        (research_node, check_advisor_node),
        (interview_node, check_advisor_node),
        (run_both_node, check_advisor_node),

        # ── Advisor decision ──
        Edge(from_node=check_advisor_node, to_node=advisor_node, route="advisor"),
        Edge(from_node=check_advisor_node, to_node=deliver_node, route="deliver"),
        (advisor_node, deliver_node),
    ],
)

app = App(
    root_agent=root_agent,
    name="product_discovery_team",
)
