# Agent Contracts Reference

**Companion to:** Multi-Agent-Design

**Purpose:** Single authoritative source for every inter-agent interface. All parallel build tracks (frontend + Workflows 1/2/3) code against *this* sheet. If something isn't here, it isn't a contract — it's an implementation detail free to change.

**Rule of the build:** The **fields and their required/optional status are frozen**. UI layout, wording, ordering, interaction, styling, and internal agent logic are all free to change without touching this sheet. A change to anything on *this* sheet is a contract change — it requires updating this file and Multi-Agent-Design, and may ripple into agent inputs.

---

## 1. Shared Envelope Schema

Every inter-agent handoff uses this envelope. Only `content` changes shape per agent; `request_id`, `quality_flags`, and `metadata` behave identically everywhere.

```json
{
  "request_id": "string — stable ID for the whole request lifecycle",
  "content": { "...": "agent-specific payload — see Section 4" },
  "quality_flags": [
    {
      "field": "string — which field is uncertain/inferred",
      "note": "string — what to caveat in output",
      "origin_agent": "string — who raised it"
    }
  ],
  "metadata": {
    "timestamp": "ISO-8601 string",
    "source_agent": "string — who produced this envelope"
  }
}
```

**Invariants:**
- `quality_flags` is append-only as the envelope travels. No agent deletes another agent's flags.
- `quality_flags` must survive the full chain: Orchestrator → (Editor B | Writer/Editor A) → Advisor. Any agent that produces user-facing output must reflect unresolved flags as caveats, not silent guesses.
- `metadata.source_agent` is overwritten by each producing agent; `request_id` never changes.

**Example** *(illustrative — a real envelope carrying one soft-gap flag, Orchestrator → Editor B. Values shown are examples, not required constants.)*

```json
{
  "request_id": "req_b7d1e004",
  "content": {
    "raw_transcript": "<transcript>Interviewer: Tell me about your first week...</transcript>",
    "interview_purpose": "Understand why trial users churn before day 7",
    "business_context": "B2B scheduling SaaS, 15-person startup"
  },
  "quality_flags": [
    { "field": "participant_count", "note": "Not provided; treat speaker labels as approximate", "origin_agent": "orchestrator" }
  ],
  "metadata": { "timestamp": "2026-07-04T09:20:00Z", "source_agent": "orchestrator" }
}
```

---

## 2. Tier 2 Sufficiency-Check Result

Returned by the Orchestrator's semantic (LLM) check. Drives the clarification loop.

```json
{
  "status": "complete | incomplete",
  "missing": [
    {
      "field": "string — machine field name",
      "required": true,
      "question": "string — the follow-up shown inline to the user"
    }
  ]
}
```

**Semantics:**
- `required: true` → **hard** gap (blocking). `required: false` → **soft** gap (quality-improving only).
- `status: "complete"` → `missing` is empty (or contains only already-accepted soft gaps).
- The loop is capped at **2 rounds**. After round 2:
  - any remaining **hard** gap → Orchestrator stops, explains the gap, request goes to **no** agent (held per Section 5).
  - only **soft** gaps remain → Orchestrator proceeds, converting each remaining soft gap into a `quality_flags` entry on the outgoing envelope (Section 1).

---

## 3. Field Requirements by Request Type

The frozen field set. The frontend form must be able to collect all **hard** fields; Tier 1 (structural) and Tier 2 (semantic) validate against this table.

| Request | Field | Hard / Soft | Notes |
|---|---|---|---|
| **A — Research** | `topic` | Hard | Must be specific enough to research |
| **B — Interview** | `transcript_or_audio` | Hard | One of: audio file **or** text transcript |
| **B — Interview** | `interview_purpose` | Hard | Goal of the interview |
| **B — Interview** | `business_context` | Hard | Context Editor B needs to segment meaningfully |
| **B — Interview** | `participant_count` | Soft | Quality-improving only |
| **B — Interview** | `want_mindmap` | Conditional | Shown only when `want_transcript` is true. User's explicit choice: generate a Miro mind map? If true, Editor B additionally emits the topic tree (Section 4) |
| **C — Recommendations** | *(none of its own)* | — | Consumes finished A and/or B outputs; requires no new user fields |

### Request composition (explicit, not inferred)

The user's choice of what to produce is captured as three explicit boolean fields on the form, **not** inferred from which other fields are populated. The Orchestrator routes on these directly at Tier 1.

| Field | Type | Meaning |
|---|---|---|
| `want_report` | boolean | Run Research workflow (Request A) — always produces a report |
| `want_transcript` | boolean | Run Interview workflow (Request B) — always produces a text transcript; `want_mindmap` is an optional add-on under this |
| `want_recommendation` | boolean | Run Advisor synthesis (Request C) on whatever finished A/B outputs exist |

**C is an independent opt-in, not derived.** The user separately decides whether they also want a recommendation, regardless of whether they picked A, B, or both:
- A only + C → recommendation built from the report.
- B only + C → recommendation built from the transcript.
- A + B + C → recommendation synthesizes **both** finished outputs.
- A and/or B **without** C → each selected workflow's output goes straight to delivery, no Advisor.

C never runs automatically from having both A and B selected — it runs only when `want_recommendation` is true.

**Structural validity (Tier 1), two rules:**
1. At least one of `want_report` / `want_transcript` must be true.
2. `want_recommendation` may be true **only if** rule 1 is satisfied — C has no sources of its own, so **C-only is invalid** and is rejected before any semantic check.

**Input-type routing (Tier 1, deterministic, no LLM):**
- `transcript_or_audio` is audio → routed to Transcriber Agent.
- `transcript_or_audio` is text → routed straight to Editor B, Transcriber skipped.

---

## 4. Per-Agent `content` Payloads + Data-Minimization Boundaries

Each agent receives **only** the inputs listed. Inputs not listed must not be passed — this table *is* the data-minimization contract, not just a hint.

| Agent | Receives (`content` in) | Produces (`content` out) | Must NOT receive |
|---|---|---|---|
| **Orchestrator** | Full session state (it is the router) | Scoped envelopes to downstream agents | — (holds all, passes slices) |
| **Research Agent** | `topic` only | Structured research materials | Interview content — even on A+B requests |
| **Writer Agent** | Research materials | Draft report | Raw sources beyond what Research passed |
| **Editor A** (`report_editor`) | Draft report | Revision message (see pinned shape below) → Approved report | Interview content |
| **Transcriber Agent** | Audio file only | Raw transcript (chunked → merged chronologically) | Business context, unrelated session data |
| **Editor B** (`transcript_editor`) | Raw transcript **+** `interview_purpose`, `business_context`, speaker info | Formatted narrative document **+** (if requested) topic tree | User's full original request, unrelated session metadata |
| **Miro skill** | Structured **topic tree only** | Miro mind map board (via the `miro-diagram` skill, Mermaid mindmap syntax) | Raw transcript, narrative document, business context |
| **Advisor Agent** | *Finished* research report and/or *finished* formatted transcript | Recommendation brief + Impact/Effort matrix | Raw audio, raw transcript, any intermediate draft |

**Editor A / Editor B note:** one shared Editor implementation, parameterized by role (`report_editor` vs `transcript_editor`). Two instances, two prompt sets, one codebase — but treated as two distinct nodes in the architecture.

### Topic Tree (Editor B → Miro skill)

Emitted by Editor B **only when** `want_mindmap` is true, as a byproduct of segmentation it already performs. This is the *entire* payload the Miro skill receives — no raw transcript, no context.

```json
{
  "topics": [
    {
      "topic": "string",
      "subtopics": [
        { "subtopic": "string", "key_insights": ["string", "..."] }
      ]
    }
  ]
}
```

**Example** *(illustrative)*

```json
{
  "topics": [
    {
      "topic": "Onboarding friction",
      "subtopics": [
        { "subtopic": "Calendar sync setup", "key_insights": ["Users abandon at the OAuth step", "Unclear which calendar becomes the default"] },
        { "subtopic": "First-week value", "key_insights": ["No prompt to invite a teammate"] }
      ]
    }
  ]
}
```

### `content` examples for the nested payloads

These are the `content` blocks that sit inside the standard envelope (Section 1) at each handoff. Shown here without the surrounding envelope for brevity. Values are illustrative, not required constants.

**Research materials** *(Research Agent → Writer Agent)*

```json
{
  "research_materials": {
    "topic": "AI note-taking tools for solo consultants",
    "key_findings": [
      "Market splits into transcription-first vs synthesis-first tools",
      "Solo users cite team-oriented pricing tiers as top friction"
    ],
    "key_players": ["Otter", "Fathom", "Granola"],
    "expert_opinions": [
      { "claim": "Synthesis quality matters more than transcription accuracy above ~90%", "source": "industry analyst commentary" }
    ]
  }
}
```

**Transcript + context bundle** *(Orchestrator → Editor B)*

```json
{
  "raw_transcript": "<transcript>Interviewer: Walk me through...</transcript>",
  "interview_purpose": "Understand why trial users churn before day 7",
  "business_context": "B2B scheduling SaaS, 15-person startup",
  "speaker_info": "2 speakers: interviewer (PM) and participant (trial user)"
}
```

**Recommendation brief** *(Advisor Agent → Orchestrator → delivery)*

```json
{
  "recommendation_brief": {
    "priorities": [
      { "rank": 1, "recommendation": "Fix calendar OAuth abandonment", "reasoning": "Highest-frequency churn point in the transcript, low build cost" }
    ],
    "impact_effort_matrix": [
      { "item": "Fix OAuth flow", "impact": "high", "effort": "low" },
      { "item": "Rebuild default-calendar logic", "impact": "medium", "effort": "high" }
    ]
  }
}
```

### Writer ↔ Editor A revision message (pinned contract)

The revision loop between the Writer and Editor A crosses a build boundary (the Editor is shared code, potentially built on a separate track from the Writer), so its shape is pinned rather than left internal. Editor A returns this on each cycle; the loop repeats while `approved` is false.

```json
{
  "approved": false,
  "notes": [
    { "section": "string — which part of the draft", "issue": "string — what's wrong", "suggestion": "string — how to fix" }
  ]
}
```

When `approved` is true, `notes` is empty (or omitted) and the draft is considered final.

---

## 5. Incomplete-Request Persistence Contract

The one bounded exception to no-persistent-storage. Applies only to requests stopped on a **hard** gap after round 2.

| Property | Value |
|---|---|
| Store | Local SQLite table `incomplete_requests` |
| Key | `request_id` |
| Payload | The partial request as collected so far (enough for the user to resume) |
| Expiry column | `expires_at` = created + **48 hours** |
| Purge mechanism | **Check-on-access.** Orchestrator runs `DELETE FROM incomplete_requests WHERE expires_at < now()` at the start of each session, before handling anything. No background scheduler. |

Active (non-blocked) pipeline runs are **in-memory only** — never written here. If a live run fails, the user resubmits.

---

## 6. Cross-Cutting Constraints (bind every track)

These are contract-level because violating them in any single track breaks a system-wide guarantee.

- **Untrusted content is delimited.** Any prompt containing ingested content (transcripts, web results) wraps it in explicit tags (`<transcript>…</transcript>`, `<research_results>…</research_results>`) with a system instruction that tag contents are data to analyze, never commands.
- **MCP endpoint is pinned.** The Miro MCP server URL is hardcoded, not runtime-discovered. No other MCP servers are trusted.
- **Prompts are versioned artifacts.** System prompts live in `/prompts/<agent>.md` (stable filenames — no version in the name), not inline strings. Each prompt file carries an **in-file version header** (frontmatter, e.g. `version: 3` plus a short changelog line) so the active prompt's version is visible at a glance; git provides the full history. Do not fork versioned copies into the filename (`editor_b.v3.md`), which drift out of sync with imports.
- **Credentials are centralized.** All keys load once from `.env` via a single credentials module; agents import from it, never read `os.environ` directly. Miro token is scoped to board/diagram creation only.
- **Models are env-configurable per agent role**, not hardcoded — so the model choice can be swapped without code changes.

---

## 7. What is NOT a contract (free to change without touching this sheet)

- Form layout, styling, wording, field ordering, how many screens.
- The inline clarification interaction pattern (as long as the field set and hard/soft status in Section 3 are unchanged).
- Internal reasoning, prompts, and revision-loop tuning inside any agent.
- Number of Writer↔Editor A revision cycles before force-stop.
- Chunking strategy inside the Transcriber.
- Output styling of the final Markdown deliverable.

If a prototype or build change touches Sections 1–6, it is a **contract change**: update this sheet + Multi-Agent-Design first, then propagate.
