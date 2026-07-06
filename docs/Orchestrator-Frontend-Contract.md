# Orchestrator–Frontend Contract

**Purpose:** this is the single source of truth for the boundary between the Orchestrator and the frontend. If the Orchestrator and frontend are built by separate agents/sessions, **both must be given this file verbatim** — not a paraphrased description of it from another doc. Multi-Agent-Design and Frontend-Spec should each reference this file rather than restate its contents.

**Scope:** exact data shapes only. Transport mechanism (polling vs. WebSocket/SSE), exact route/endpoint names, and framework choice are intentionally left to the builder — this file defines *what* is exchanged, not *how* it's transmitted.

**Status:** frozen once implementation begins. Changes require a deliberate edit here (with a version bump), not silent reinterpretation by either builder.

---

## Canonical Artifact Names

Every part of this contract refers to artifacts using exactly these four keys — nowhere else, nowhere different:

- `report`
- `transcript`
- `mindmap`
- `recommendation`

---

## 1. Submission Request (Frontend → Orchestrator)

Sent when the user clicks "Submit request."

```json
{
  "want_report": true,
  "topic": "AI code review tools for enterprise dev teams",
  "want_transcript": false,
  "transcript_file": null,
  "interview_purpose": null,
  "business_context": null,
  "participant_count": null,
  "project_goals": null,
  "want_mindmap": false,
  "want_recommendation": true
}
```

Field notes:
- `transcript_file` is a file reference (audio or text upload), not pasted text — required only if `want_transcript` is true.
- `participant_count` and `project_goals` are optional (soft fields).
- `want_mindmap` is only meaningful if `want_transcript` is true.
- `want_recommendation` is only valid if at least one of `want_report` / `want_transcript` is true (enforced by the frontend disabling the checkbox — see Composition validation in Multi-Agent-Design).

---

## 2. Submission Response (Orchestrator → Frontend)

### 2a. Accepted

```json
{
  "request_id": "req_abc123",
  "status": "accepted"
}
```

### 2b. Incomplete (Tier 2 clarification needed)

Same shape as the Tier 2 semantic-check response defined in Multi-Agent-Design.md's Orchestrator section — reused here verbatim, not redefined:

```json
{
  "request_id": "req_abc123",
  "status": "incomplete",
  "missing": [
    { "field": "interview_purpose", "required": true, "question": "What was the goal of this interview?" }
  ]
}
```

The frontend renders each entry in `missing` as an inline field appended under the relevant section (see Frontend-Spec, Section 5). The user resubmits with the same `request_id`, carrying the answered fields.

### 2c. Rejected (hard requirement still missing after 2 rounds)

```json
{
  "request_id": "req_abc123",
  "status": "rejected",
  "reason": "Interview purpose is required and was not provided after 2 clarification attempts.",
  "expires_at": "2026-07-07T14:00:00Z"
}
```

`expires_at` reflects the 48-hour TTL — the frontend uses this to know the request is still recoverable until that timestamp.

---

## 3. Status Response (Orchestrator → Frontend)

Used to populate the Results view (Frontend-Spec, Section 7). One entry per canonical artifact name; `null` means that artifact was never requested (distinct from `"failed"`).

```json
{
  "request_id": "req_abc123",
  "artifacts": {
    "report": "ready",
    "transcript": null,
    "mindmap": null,
    "recommendation": "generating"
  },
  "outputs": {
    "report": "https://.../report.md",
    "transcript": null,
    "mindmap": null,
    "recommendation": null
  }
}
```

Allowed values for each artifact in `artifacts`: `"generating"`, `"ready"`, `"failed"`, or `null` (not requested).

`outputs` holds the download URL (for `report`/`transcript`/`recommendation`) or the Miro board URL (for `mindmap`) once that artifact's status is `"ready"`. Otherwise `null`.

---

## 4. Retry Request (Frontend → Orchestrator)

Scoped to a single artifact — never re-runs the whole request.

```json
{
  "request_id": "req_abc123",
  "artifact": "mindmap"
}
```

Response: the same shape as Section 3 (Status Response), reflecting the retried artifact back to `"generating"`.

---

## Notes

- This contract does not define how status updates reach the frontend (poll vs. push) — that's an implementation choice for whoever builds the Orchestrator/frontend boundary.
- This contract does not define authentication/session handling for the HTTP layer itself — that's covered separately by the API Key Management section of Multi-Agent-Design.md, which governs server-side credentials, not frontend-to-backend auth.
- If either builder needs a field this contract doesn't cover, that's a sign this file needs updating — not a sign to improvise a local workaround.
