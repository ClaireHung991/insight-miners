"""Shared envelope schema for all inter-agent handoffs.

Every message passed between agents uses this envelope.
Only `content` changes shape per agent; request_id, quality_flags,
and metadata behave identically everywhere.

Contract ref: Agent-Contracts-Reference.md §1
"""

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field


class QualityFlag(BaseModel):
    """A flag raised by an agent for uncertain or inferred content.

    quality_flags is append-only. No agent deletes another agent's flags.
    """

    field: str = Field(description="Which field is uncertain or inferred")
    note: str = Field(description="What to caveat in the output")
    origin_agent: str = Field(description="Which agent raised this flag")


class EnvelopeMetadata(BaseModel):
    """Metadata block on every envelope.

    source_agent is overwritten by each producing agent.
    timestamp reflects when this envelope was produced.
    """

    timestamp: str = Field(description="ISO-8601 production timestamp")
    source_agent: str = Field(description="Agent that produced this envelope")


class Envelope(BaseModel):
    """Standard inter-agent envelope.

    request_id: stable ID for the whole request lifecycle — never changes.
    content:    agent-specific payload (see Agent-Contracts-Reference.md §4).
    quality_flags: append-only list of uncertainty flags.
    metadata:   overwritten by each producing agent.
    """

    request_id: str
    content: dict[str, Any]
    quality_flags: list[QualityFlag] = Field(default_factory=list)
    metadata: EnvelopeMetadata

    def add_flag(self, field: str, note: str, origin_agent: str) -> "Envelope":
        """Return a new Envelope with an appended quality flag.

        Never mutates in place — quality_flags is append-only.
        """
        return self.model_copy(
            update={
                "quality_flags": self.quality_flags
                + [QualityFlag(field=field, note=note, origin_agent=origin_agent)]
            }
        )

    def with_source(self, agent_name: str) -> "Envelope":
        """Return a new Envelope stamped with the given agent as source."""
        return self.model_copy(
            update={
                "metadata": EnvelopeMetadata(
                    timestamp=datetime.now(timezone.utc).isoformat(),
                    source_agent=agent_name,
                )
            }
        )

    @classmethod
    def create(cls, request_id: str, content: dict[str, Any], source_agent: str) -> "Envelope":
        """Convenience factory for a fresh envelope."""
        return cls(
            request_id=request_id,
            content=content,
            quality_flags=[],
            metadata=EnvelopeMetadata(
                timestamp=datetime.now(timezone.utc).isoformat(),
                source_agent=source_agent,
            ),
        )



# ── Editor A / Editor B revision message ─────────────────────────────────────
# Pinned contract shape — Agent-Contracts-Reference.md §4 (Writer ↔ Editor A)

class RevisionNote(BaseModel):
    section: str = Field(description="Which part of the draft")
    issue: str = Field(description="What is wrong")
    suggestion: str = Field(description="How to fix it")


class RevisionMessage(BaseModel):
    """Returned by Editor A/B on each review cycle."""

    approved: bool
    notes: list[RevisionNote] = Field(default_factory=list)
