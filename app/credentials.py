# ruff: noqa: E402
"""Centralized credentials module.

This is the ONLY place in the codebase that reads os.environ / dotenv.
All other modules import from here — never read os.environ directly.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

# Load .env from the app/ directory (where this file lives)
_env_path = Path(__file__).parent / ".env"
load_dotenv(_env_path)


def _require(name: str) -> str:
    """Return env var value or raise a clear error at startup."""
    value = os.environ.get(name)
    if not value:
        raise EnvironmentError(
            f"Required environment variable '{name}' is not set. "
            f"Check {_env_path} or copy .env.example to .env."
        )
    return value


def _optional(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


# ── Google AI Studio ──────────────────────────────────────────────────────────
google_api_key: str = _require("GOOGLE_API_KEY")
google_genai_use_vertexai: bool = (
    _optional("GOOGLE_GENAI_USE_VERTEXAI", "False").lower() == "true"
)

# ── Model assignments (env-configurable per agent role) ───────────────────────
orchestrator_model: str = _optional("ORCHESTRATOR_MODEL", "gemini-2.5-flash")
research_model: str = _optional("RESEARCH_MODEL", "gemini-2.5-flash")
writer_model: str = _optional("WRITER_MODEL", "gemini-2.5-flash")
editor_model: str = _optional("EDITOR_MODEL", "gemini-2.5-flash")
recommendation_model: str = _optional("RECOMMENDATION_MODEL", "gemini-2.5-pro")

# ── OpenAI / Whisper ─────────────────────────────────────────────────────────
openai_api_key: str = _require("OPENAI_API_KEY")

# ── Miro ─────────────────────────────────────────────────────────────────────
miro_access_token: str = _require("MIRO_ACCESS_TOKEN")
