"""Custom FastAPI application for the Product Discovery Team.

Exposes three endpoints matching the Orchestrator-Frontend Contract:
  POST /submit    — Submit a new request (§1 → §2)
  GET  /status/{request_id}  — Poll artifact status (§3)
  POST /retry     — Retry a single failed artifact (§4)

Also serves the frontend static files from /frontend/.
"""

import asyncio
import json
import logging
import uuid
from pathlib import Path
from typing import Any

from fastapi import FastAPI, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from google.adk.runners import Runner
from google.adk.sessions.in_memory_session_service import InMemorySessionService
from google.genai import types

logger = logging.getLogger(__name__)

# Try to import RequestInput for HITL detection
try:
    from google.adk.events import RequestInput
    _HAS_REQUEST_INPUT = True
except ImportError:
    RequestInput = None
    _HAS_REQUEST_INPUT = False

# ── In-memory run store ───────────────────────────────────────────────────────
# Active runs are in-memory only (contract: no persistent storage for live runs).
_active_runs: dict[str, dict] = {}

# One shared session service for all runs
_session_service = InMemorySessionService()


# ── Pydantic models matching Orchestrator-Frontend Contract ───────────────────

class SubmitRequest(BaseModel):
    """Orchestrator-Frontend-Contract §1."""
    want_report: bool = False
    topic: str | None = None
    want_transcript: bool = False
    interview_purpose: str | None = None
    interview_background: str | None = None
    participant_count: int | None = None
    want_mindmap: bool = False
    want_recommendation: bool = False


class RetryRequest(BaseModel):
    """Orchestrator-Frontend-Contract §4."""
    request_id: str
    artifact: str  # "report" | "transcript" | "mindmap" | "recommendation"


# ── FastAPI setup ─────────────────────────────────────────────────────────────

app = FastAPI(
    title="Product Discovery Team",
    description="Multi-agent product discovery support API",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Tighten in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Upload directory ──────────────────────────────────────────────────────────
UPLOAD_DIR = Path(__file__).parent / "_uploads"
UPLOAD_DIR.mkdir(exist_ok=True)


# ── Background runner ─────────────────────────────────────────────────────────

async def _run_workflow(request_id: str, initial_state: dict[str, Any]) -> None:
    """Execute the Workflow in the background and write results back to _active_runs.

    Retries up to 3 times on transient 503/429 errors from the Gemini API.
    """
    from app.agent import app as adk_app

    run = _active_runs.get(request_id)
    if not run:
        return

    max_attempts = 3
    for attempt in range(1, max_attempts + 1):
        try:
            await _run_workflow_once(request_id, initial_state, run, adk_app)
            return  # success
        except Exception as e:
            err_str = str(e)
            is_transient = "503" in err_str or "UNAVAILABLE" in err_str or "429" in err_str or "RESOURCE_EXHAUSTED" in err_str
            if is_transient and attempt < max_attempts:
                wait_s = 15 * attempt
                logger.warning(f"[{request_id}] Transient API error (attempt {attempt}/{max_attempts}), retrying in {wait_s}s: {e}")
                await asyncio.sleep(wait_s)
                # Reset generating statuses for retry
                for key, status in run["artifacts"].items():
                    if status == "failed":
                        run["artifacts"][key] = "generating"
                        run["outputs"][key] = None
            else:
                logger.error(f"[{request_id}] Workflow failed after {attempt} attempt(s): {e}", exc_info=True)
                for key, status in run["artifacts"].items():
                    if status == "generating":
                        run["artifacts"][key] = "failed"
                        run["outputs"][key] = f"Error: {e}"
                return


async def _run_workflow_once(request_id: str, initial_state: dict, run: dict, adk_app) -> None:
    """Single attempt at running the workflow."""

    user_id = "api_user"
    session_id = request_id

    # Create a session pre-seeded with the request state
    session = await _session_service.create_session(
        app_name=adk_app.name,
        user_id=user_id,
        session_id=session_id,
        state=initial_state,
    )

    runner = Runner(
        app=adk_app,
        session_service=_session_service,
    )

    # Build the user message — the orchestrator reads from session state,
    # so the message text is just a trigger signal.
    user_message = types.Content(
        role="user",
        parts=[types.Part(text=json.dumps({
            "request_id": request_id,
            "want_report": initial_state.get("want_report", False),
            "want_transcript": initial_state.get("want_transcript", False),
            "want_mindmap": initial_state.get("want_mindmap", False),
            "want_recommendation": initial_state.get("want_recommendation", False),
        }))],
    )

    try:
        async for event in runner.run_async(
            user_id=user_id,
            session_id=session_id,
            new_message=user_message,
        ):
            # Detect HITL clarification requests
            if _HAS_REQUEST_INPUT and RequestInput and isinstance(event, RequestInput):
                logger.info(f"[{request_id}] Clarification requested: {event.message}")
                # Store clarification questions so the frontend can surface them
                existing_questions = run.get("clarification_questions", [])
                existing_questions.append({
                    "field": getattr(event, "interrupt_id", "unknown").replace("clarify_", ""),
                    "question": event.message,
                })
                run["clarification_questions"] = existing_questions
                # Mark all generating artifacts as needs_clarification
                for key in run["artifacts"]:
                    if run["artifacts"][key] == "generating":
                        run["artifacts"][key] = "needs_clarification"
                        run["outputs"][key] = {
                            "status": "needs_clarification",
                            "questions": existing_questions,
                        }
                return  # Stop consuming events — workflow is paused

            # Sync results from session state back to _active_runs on each event
            try:
                updated_session = await _session_service.get_session(
                    app_name=adk_app.name,
                    user_id=user_id,
                    session_id=session_id,
                )
                if updated_session and updated_session.state:
                    state = updated_session.state
                    # Replace artifact statuses if they moved forward (generating → ready/failed)
                    state_artifacts = state.get("artifacts", {})
                    state_outputs = state.get("outputs", {})
                    for key in run["artifacts"]:
                        if state_artifacts.get(key) in ("ready", "failed"):
                            run["artifacts"][key] = state_artifacts[key]
                        if state_outputs.get(key) is not None:
                            run["outputs"][key] = state_outputs[key]
            except Exception as sync_err:
                logger.debug(f"State sync error (non-fatal): {sync_err}")

        # Final authoritative sync after workflow completes
        final_session = await _session_service.get_session(
            app_name=adk_app.name,
            user_id=user_id,
            session_id=session_id,
        )
        if final_session and final_session.state:
            state = final_session.state
            state_artifacts = state.get("artifacts", {})
            state_outputs = state.get("outputs", {})
            logger.info(f"[{request_id}] Final session state keys: {list(state.keys())}")
            logger.info(f"[{request_id}] Final session artifacts: {state_artifacts}")

            # Map of artifact key → raw state key written by each pipeline
            _raw_output_keys = {
                "report": "draft_report",
                "transcript": "transcript_cleaned",
                "summary": "editor_b_result",
                "mindmap": "mindmap_url",
                "recommendation": "recommendation_result",
            }

            for key in run["artifacts"]:
                if state_artifacts.get(key) in ("ready", "failed"):
                    # Authoritative: pipeline explicitly set the status
                    run["artifacts"][key] = state_artifacts[key]
                    run["outputs"][key] = state_outputs.get(key)
                elif state_outputs.get(key) is not None:
                    # outputs dict was written but artifacts dict wasn't updated
                    run["artifacts"][key] = "ready"
                    run["outputs"][key] = state_outputs.get(key)
                elif state.get(_raw_output_keys.get(key, "__missing__")) is not None:
                    # Fall back to raw pipeline output key in state
                    run["artifacts"][key] = "ready"
                    run["outputs"][key] = state[_raw_output_keys[key]]
                elif run["artifacts"][key] == "generating":
                    run["artifacts"][key] = "failed"
                    logger.warning(f"[{request_id}] Artifact '{key}' never completed")

    except Exception as e:
        logger.error(f"Workflow error for {request_id}: {e}", exc_info=True)
        # Mark all still-generating artifacts as failed
        for key, status in run["artifacts"].items():
            if status == "generating":
                run["artifacts"][key] = "failed"
                run["outputs"][key] = f"Error: {e}"


# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.post("/submit")
async def submit_request(
    want_report: bool = Form(False),
    topic: str = Form(None),
    want_transcript: bool = Form(False),
    transcript_file: UploadFile | None = File(None),
    interview_purpose: str = Form(None),
    interview_background: str = Form(None),
    participant_count: int = Form(None),
    want_mindmap: bool = Form(False),
    want_recommendation: bool = Form(False),
):
    """Handle form submission (Orchestrator-Frontend-Contract §1 → §2).

    Performs Tier 1 structural validation. If valid, creates a run entry
    and triggers the workflow asynchronously.
    """
    request_id = f"req_{uuid.uuid4().hex[:12]}"

    # Handle file upload
    file_path = None
    if transcript_file and transcript_file.filename:
        file_ext = Path(transcript_file.filename).suffix
        file_path = str(UPLOAD_DIR / f"{request_id}{file_ext}")
        content = await transcript_file.read()
        Path(file_path).write_bytes(content)

    # ── Tier 1 structural validation ──
    errors = []

    if not want_report and not want_transcript:
        errors.append("Select Report or Transcript to continue.")

    if want_recommendation and not want_report and not want_transcript:
        errors.append("Recommendation requires at least one of Report or Transcript.")

    if want_mindmap and not want_transcript:
        errors.append("Mind map requires Transcript to be selected.")

    if want_report and not (topic and topic.strip()):
        errors.append("Add a topic to research.")

    if want_transcript:
        if not file_path:
            errors.append("Upload an audio or text file.")
        if not (interview_purpose and interview_purpose.strip()):
            errors.append("Tell us the interview's purpose — this helps format it well.")
        if not (interview_background and interview_background.strip()):
            errors.append("Add some background context (company, product, etc.).")

    if errors:
        return JSONResponse(
            status_code=422,
            content={"status": "error", "errors": errors},
        )

    # ── Build initial artifacts map ──
    artifacts: dict[str, str | None] = {
        "report": "generating" if want_report else None,
        "transcript": "generating" if want_transcript else None,
        "summary": "generating" if want_transcript else None,
        "mindmap": "generating" if want_mindmap else None,
        "recommendation": "generating" if want_recommendation else None,
    }
    outputs: dict[str, Any] = {k: None for k in artifacts}

    _active_runs[request_id] = {
        "request_id": request_id,
        "artifacts": artifacts,
        "outputs": outputs,
        "clarification_round": 0,
    }

    # ── Build initial workflow state ──
    # Seed ctx.state so validate_tier1 can read request directly from state,
    # bypassing the JSON-parse path (which expects a SubmissionRequest-shaped dict).
    full_request = {
        "want_report": want_report,
        "topic": topic or "",
        "want_transcript": want_transcript,
        "transcript_file": file_path or "",   # Key orchestrator reads
        "interview_purpose": interview_purpose or "",
        "interview_background": interview_background or "",
        "participant_count": participant_count,
        "want_mindmap": want_mindmap,
        "want_recommendation": want_recommendation,
    }

    initial_state: dict[str, Any] = {
        # Pre-seed the request_id so orchestrator uses our ID, not a new one
        "request_id": request_id,

        # Pre-seed the request dict — validate_tier1 reads ctx.state["request"]
        # when resuming; we set it here so it's available from the first run too.
        "request": full_request,

        # ── Flattened fields for workflow state access ──
        "want_report": want_report,
        "want_transcript": want_transcript,
        "want_mindmap": want_mindmap,
        "want_recommendation": want_recommendation,
        "topic": topic or "",
        "interview_purpose": interview_purpose or "",
        "interview_background": interview_background or "",
        "participant_count": str(participant_count) if participant_count else "not provided",

        # Clarification round counter
        "clarification_round": 0,

        # Artifacts tracking (workflow will overwrite)
        "artifacts": {k: None for k in artifacts if artifacts[k] is not None},
        "outputs": {k: None for k in artifacts if artifacts[k] is not None},
    }

    # ── Fire and forget the workflow ──
    asyncio.create_task(_run_workflow(request_id, initial_state))

    return {
        "request_id": request_id,
        "status": "accepted",
        "artifacts": artifacts,
        "outputs": outputs,
    }


@app.get("/status/{request_id}")
async def get_status(request_id: str):
    """Poll artifact status (Orchestrator-Frontend-Contract §3)."""
    run = _active_runs.get(request_id)
    if not run:
        return JSONResponse(
            status_code=404,
            content={"error": f"No active run found for {request_id}"},
        )

    return {
        "request_id": request_id,
        "artifacts": run["artifacts"],
        "outputs": run["outputs"],
    }


@app.post("/retry")
async def retry_artifact(req: RetryRequest):
    """Retry a single failed artifact (Orchestrator-Frontend-Contract §4)."""
    run = _active_runs.get(req.request_id)
    if not run:
        return JSONResponse(
            status_code=404,
            content={"error": f"No active run found for {req.request_id}"},
        )

    valid_artifacts = {"report", "transcript", "mindmap", "recommendation"}
    if req.artifact not in valid_artifacts:
        return JSONResponse(
            status_code=400,
            content={"error": f"Invalid artifact: {req.artifact}"},
        )

    if run["artifacts"].get(req.artifact) != "failed":
        return JSONResponse(
            status_code=400,
            content={"error": f"Artifact '{req.artifact}' is not in 'failed' state"},
        )

    # Reset to generating and re-trigger
    run["artifacts"][req.artifact] = "generating"
    run["outputs"][req.artifact] = None

    # TODO: re-run just the specific pipeline for this artifact
    # For now, inform the client it's been reset to generating
    return {
        "request_id": req.request_id,
        "artifacts": run["artifacts"],
        "outputs": run["outputs"],
    }


# ── Static file serving for frontend ──────────────────────────────────────────

_frontend_dir = Path(__file__).parent.parent / "frontend"
if _frontend_dir.exists():
    @app.get("/")
    async def serve_index():
        return FileResponse(_frontend_dir / "index.html")

    app.mount("/static", StaticFiles(directory=str(_frontend_dir)), name="frontend")


# ── Main ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
