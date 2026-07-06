# Product Discovery Support Team (Multi-Agent System)

**Track:** Concierge Agents
**Status:** Design finalized, technical design decisions finalized, ready for implementation

---

---

## Goal

A multi-agent support team for solo product managers, consultants, and entrepreneurs. The system accelerates product discovery by helping them identify the user problems, needs, or opportunities that will create the greatest impact for their target customers.

The system supports three capabilities the user selects independently:

- **Report (A)** — online research on a topic.
- **Transcript (B)** — interview transcription and organization, with an optional Miro mind map add-on.
- **Recommendation (C)** — an Advisor synthesis that builds a recommendation brief from the finished A and/or B outputs.

**Selection rules:**

- The user must choose at least one of Report (A) or Transcript (B).
- Recommendation (C) is an independent opt-in, available whenever at least one of A or B is selected. It is never automatic and never selectable on its own — C alone is invalid.
- When both A and B are selected and C is chosen, the recommendation synthesizes both outputs. When only one is selected and C is chosen, it builds from that one. When C is not chosen, each selected workflow's output goes straight to delivery, bypassing the Advisor.

This yields the valid combinations: A, B, A+B, A+C, B+C, and A+B+C.

---

## Key Concepts Demonstrated (Capstone Requirement: 3+ of 6)

| Concept | How it's shown | Where |
|---|---|---|
| Agent / Multi-agent system (ADK) | Orchestrator + specialized agents coordinating across 3 workflows | Code |
| MCP Server | Miro MCP integration, invoked as a skill from Editor B | Code |
| Agent skills (e.g. Agents CLI) | Miro mind map generation implemented as a callable skill, not a full agent | Code / Video |
| Security features | No persistent storage (bounded exception), data minimization, prompt injection hygiene, lightweight hardening | Code |
| Antigravity | To be demonstrated during build | Video |
| Deployability | To be addressed in video walkthrough | Video |

---

# User Requests

## Request A: Online Research

The user asks the system to research a topic, industry, market, problem space, or issue.

**Goal:** Help the user understand the problem space, trends, key players, challenges, and expert opinions — enough to make confident, informed judgments.

## Request B: Interview Transcription and Organization

The user provides either an audio file or a text transcript file — both are file uploads; text is not pasted into a text box. The system transforms it into a structured, readable format, and can optionally generate a Miro mind map as an add-on.

**Goal:** Help the user quickly understand the interview, organize insights, identify key findings, and determine next steps.

## Request C: Recommendations

An independent, opt-in addition — never automatic, and never selectable on its own. It requires at least one of Request A or Request B to also be selected.

Using knowledge from Request A and/or Request B (whichever were selected), the system synthesizes available information and recommends what to address first.

**Output:** A recommendation brief with top 3–5 priorities, reasoning per recommendation, and an Impact vs. Effort Matrix.

---

# Multi-Agent System Design

## Full Orchestration Flow

```
User submits request
        |
        v
   Orchestrator (validate + clarify, max 2 rounds)
   Confirms: want_report / want_transcript / want_recommendation
        |
   +----+----+
   v         v
Research   Interview
pipeline   pipeline
(runs if   (runs if
 want_      want_
 report)    transcript)
   |         |
   |  (if want_recommendation, selected pipeline(s) converge)
   +----+----+
        v
  Advisor agent (runs only if want_recommendation = true)
        |
        v
    Delivery

Note: want_report and want_transcript are independent — either or both
may run. want_recommendation is an independent opt-in that requires at
least one of the other two; it can never run alone. When
want_recommendation is false, each pipeline's output goes directly to
Delivery, bypassing the Advisor agent.
```

## Orchestrator: Request Validation and Clarification

Two-tier check before any agent is assigned:

1. **Tier 1 — Structural check** (deterministic, no LLM call): are required fields present at all? (topic filled in, file/text uploaded, etc.)
2. **Tier 2 — Semantic check** (LLM call): is the content actually sufficient in quality/specificity to produce a good result?

Tier 2 returns a structured result distinguishing **hard** (blocking) vs **soft** (quality-improving) gaps:

```json
{
  "status": "incomplete",
  "missing": [
    { "field": "interview_purpose", "required": true, "question": "What was the goal of this interview?" }
  ]
}
```

**Composition validation (also Tier 1):** the user selects independent booleans — `want_report` (A), `want_transcript` (B, with `want_mindmap` as a conditional add-on valid only when `want_transcript` is true), and `want_recommendation` (C). Rules:

- At least one of `want_report` or `want_transcript` must be true.
- `want_mindmap` is only valid when `want_transcript` is true.
- `want_recommendation` may only be true if at least one of `want_report` or `want_transcript` is true — C alone is rejected at Tier 1.
- Valid combinations: A, B, A+B, A+C, B+C, A+B+C (with B optionally carrying `want_mindmap`).

**Hard vs. soft requirements per request type:**

| Request | Hard requirements | Soft (quality-improving only) |
|---|---|---|
| A | Topic specific enough to research | — |
| B | Transcript file (text) or audio file (uploaded, not pasted), interview purpose, business context | Exact participant count, granular project goals |

**Clarification loop:**
- Missing fields render as inline follow-up form inputs (not a chatbot) — user fills in and resubmits.
- Capped at **2 rounds**.
- After round 2:
  - If a **hard** requirement is still missing -> Orchestrator stops and clearly explains the gap to the user. Request is not passed to any agent.
  - If only **soft** gaps remain -> Orchestrator proceeds, passing structured `quality_flags` to the relevant sub-agent so it can note inferred/uncertain content in its output rather than presenting guesses as fact.

**Incomplete request handling:** if a request is stopped due to a hard-requirement gap, it's held in ephemeral session state with a 48-hour TTL so the user can return and complete it. After 48 hours, it's auto-purged. (See Security Design and Technical Design Decisions below.)

## Model Assignment Per Agent

Not every agent uses the same LLM. Models are tiered by reasoning demand and are **configurable per agent role via environment variables**, not hardcoded — this keeps cost down and makes the model choice easy to swap later.

| Agent | Reasoning need | Model type |
|---|---|---|
| Orchestrator (Tier 2 sufficiency check) | Moderate — judging sufficiency, not generating content | Lighter/cheaper LLM |
| Research Agent | High — synthesizing and evaluating sources | Stronger LLM |
| Writer Agent | High — quality prose generation | Stronger LLM |
| Editor Agent (shared, both roles) | High — critique quality matters | Stronger LLM |
| Advisor Agent | High — synthesis and reasoning across sources | Stronger LLM |
| Transcriber Agent | N/A — not a reasoning task | Speech-to-text model (e.g. Whisper), separate credential from the LLMs above |
| Miro skill (see Workflow 2) | None — deterministic tool logic | No model needed |

---

## Workflow 1: Online Research (Request A)

1. Orchestrator validates Request A (see clarification flow above).
2. Orchestrator sends the task to the **Research Agent**, which performs research, synthesizes findings, and produces structured research materials.
3. Research Agent passes materials to the **Writer Agent**, which drafts the report.
4. Writer sends the draft to **Editor A**, which reviews it. Revision cycles repeat between Writer and Editor A until approved.
5. On approval:
   - If `want_recommendation` is false -> returned to Orchestrator for delivery.
   - If `want_recommendation` is true -> passed to the **Advisor Agent**.

---

## Workflow 2: Interview Transcription (Request B)

1. Orchestrator validates Request B (transcript/audio + hard-required background context).
2. **Input routing:** the Orchestrator checks input type directly during Tier 1 — no pass-through logic needed in any agent.
   - Audio -> routed to the **Transcriber Agent**.
   - Text -> routed straight to **Editor B**, skipping the Transcriber Agent entirely.
3. **Transcriber Agent** (audio only): checks whether the file fits a single speech-to-text request; if not, splits into chunks, transcribes each via a speech-to-text model, and merges them chronologically into a raw transcript.
4. **Editor B** formats the transcript into a structured, readable document, divided into logical topic sections. It requires the raw transcript **and** the interview background context (purpose, business context, speaker info) before starting — both are hard requirements.
5. **Editor A / Editor B:** implemented as **one shared Editor Agent**, parameterized by role (`report_editor` vs. `transcript_editor`) with different prompts/context per instantiation. They still appear as two distinct agents in the architecture.
6. **Miro integration (skill, not a separate agent):**
   - Editor B **always** produces the formatted narrative document — this never changes.
   - **If `want_mindmap` was requested**, Editor B additionally emits a structured topic tree (topic -> subtopics -> key insights) as a byproduct of the segmentation work it already does — no duplicated reasoning.
   - Generating the board is mechanical, not a judgment call — so it is implemented as a **skill Editor B invokes directly**, rather than a separate agent with its own reasoning loop. No LLM is involved in this step. Concretely, this uses Miro's official `miro-diagram` skill (via the Miro MCP server): the topic tree is converted to **Mermaid mindmap syntax** (chosen over the skill's plain-text option, since Mermaid's indentation-based hierarchy is a deterministic, code-only conversion from the tree — plain text would require the skill to re-interpret structure, duplicating reasoning Editor B already did).
   - A **new Miro board is created for each request** (via `board_create`) rather than reusing an existing board, consistent with the system's ephemeral, no-persistent-state design elsewhere.
   - The skill call is parameterized only with the structured topic tree — never the raw transcript or business context — preserving data minimization regardless of which component makes the call.
7. On completion:
   - If `want_recommendation` is false -> returned to Orchestrator for delivery.
   - If `want_recommendation` is true -> passed to the **Advisor Agent**.

---

## Workflow 3: Advisor Agent (Request C)

Runs only when the user opts into `want_recommendation`; it is never automatic and requires at least one of Request A or Request B to have been selected. Receives the research report and/or formatted transcript (whichever were selected) and synthesizes them into a recommendation brief:

- Top 3–5 recommended priorities, each with reasoning
- Impact vs. Effort Matrix

---

# Security Design

**Priorities chosen:** No persistent storage, data minimization, and lightweight hardening informed by Google's *Vibe Coding Agent Security and Evaluation* (May 2026) whitepaper, right-sized for a solo-use capstone project rather than enterprise scale.

## No Persistent Storage (with one bounded exception)

- Nothing sensitive touches disk during processing — audio chunks, raw transcripts, draft reports, and intermediate agent outputs stay in memory / short-lived session state only.
- The only files written to disk are: (a) the final deliverable the user explicitly downloads, and (b) incomplete requests awaiting user follow-up.
- **Incomplete requests** (stopped on a hard-requirement gap) are held in ephemeral storage with a **48-hour TTL**, then automatically purged. This balances usability (user can come back and finish) against data retention (nothing lingers indefinitely).

## Data Minimization Between Agents

Each agent receives only what it needs to do its job:

- **Advisor Agent** receives only the *finished* research report and *finished* formatted transcript — never raw audio, never intermediate drafts.
- **Research Agent** receives only the topic/query — never interview content, even on combined requests.
- **Editor B** receives the raw transcript plus only the specific background context it needs — not the user's full original request or unrelated session metadata.
- **Miro skill** receives only the structured topic tree — no raw transcript, no narrative document.
- **Orchestrator** holds the full session state (it's the router) but passes scoped slices downstream, never the whole state.

## Prompt Injection Hygiene

External content ingested by the system — interview transcripts and web research results — is treated as untrusted data, not as instructions. Every agent prompt that includes ingested content wraps it in explicit delimiter tags (e.g. `<transcript>...</transcript>`, `<research_results>...</research_results>`), with an explicit system instruction that content inside these tags is data to analyze, never commands to follow. This mitigates the risk of injected text (e.g. "ignore previous instructions...") altering agent behavior — a real risk here since the system regularly ingests third-party content into LLM context.

## Additional Lightweight Hardening

- **MCP trust boundary:** the Miro MCP server endpoint is pinned/hardcoded rather than dynamically discovered; no arbitrary MCP servers are trusted at runtime.
- **Prompts as versioned artifacts:** system prompts live in dedicated files (e.g. `/prompts/editor_b.md`) rather than inline strings, version-controlled as part of the repo.
- **Least-privilege API scoping:** where a provider supports scoped tokens (e.g. Miro), tokens are limited to only the permissions needed (board/diagram creation), not full account access. *(Note: Miro's MCP docs don't spell out fine-grained scopes — verify actual granularity during OAuth setup rather than assuming it.)*

---

# Evaluation Approach

Security asks whether the agent stayed within bounds; evaluation asks whether it actually did a good job. This project does not build a separate evaluation framework, but its existing architecture already embodies one evaluation pattern worth documenting explicitly:

**Agent-as-Judge, built into the workflow itself.** The Writer -> Editor A review loop (Workflow 1) functions as an Agent-as-Judge pattern: one agent produces output, another agent evaluates and critiques it before it's considered final, with revision cycles repeating until approved. This is the same principle enterprise evaluation frameworks build as separate infrastructure — here it is native to the pipeline rather than bolted on afterward.

No additional evaluation tooling is planned given the project timeline. This section documents that the design already reflects sound evaluation principles, rather than introducing new scope.

---

# Delivery Design

- **Output format:** Markdown as the primary format (fast to generate, handles structured content and tables well — e.g. the Impact vs. Effort Matrix).
- **Delivery method:** Frontend download button.
- **Miro board delivery:** when `want_mindmap` is selected, the resulting board link is shown separately in the frontend once generation completes — not embedded inside the downloaded Markdown file.

---

---

# Technical Design Decisions

## Ephemeral Session State Mechanism

- **Active pipeline runs:** pure in-memory — state object passed directly between agent calls. No external store needed; if a run fails, the user simply resubmits.
- **Incomplete requests (48-hour TTL case):** lightweight local SQLite table with an `expires_at` column.

## Agent I/O Contracts

All agents communicate using a shared envelope schema rather than fully custom per-agent formats, so cross-cutting fields behave consistently everywhere:

```json
{
  "request_id": "...",
  "content": { "...": "agent-specific payload" },
  "quality_flags": [],
  "metadata": { "timestamp": "...", "source_agent": "..." }
}
```

Each agent's actual data lives in `content`, shaped however that agent needs. `quality_flags` and `metadata` stay consistent across every handoff — this matters because `quality_flags` needs to travel through multiple agents (Orchestrator -> Editor B -> Advisor Agent).

## API Key Management

- Centralized credentials module (`credentials.py` / `config.py`): all keys loaded once from `.env`; agents import from this module rather than reading `os.environ` directly.
- Enables scoping (e.g., only the code path that calls the Miro skill accesses the Miro token) and gives one auditable place to see every credential the system uses.

## 48-Hour TTL Enforcement

- Check-on-access: no background scheduler. The Orchestrator runs a cleanup query (`DELETE FROM incomplete_requests WHERE expires_at < now()`) at the start of each session, before handling anything else.

## GitHub Distribution: Credential Setup for Other Users

- Ship a `.env.example` file listing all required variable names (LLM key(s), speech-to-text API key, Miro API token/MCP credentials) with placeholder values — no real keys committed.
- README documents setup: copy `.env.example` to `.env`, fill in your own keys. Supports both the competition's "no keys in code" rule and the Documentation score.
