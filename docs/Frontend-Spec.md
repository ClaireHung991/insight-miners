# Frontend Spec — Product Discovery Request Form

**Companion to:** Multi-Agent-Design (system architecture doc)
**Scope:** Form structure, field-level validation, clarification UX, runtime error handling, and the results view. This doc does not cover agent architecture, orchestration logic, or backend contracts — see Multi-Agent-Design for those.

---

## 0. Relationship to the Claude Design Prototype

An HTML prototype and screenshots (produced in Claude Design) are provided alongside this doc. Treat them as follows:

- **This spec and Agent-Contracts-Reference are binding.** Field names, required/optional status, validation rules, composition logic, and the states/behaviors described here (Sections 1–8) are the contract. Build against these.
- **The prototype is a non-binding reference for intent** — visual direction, layout feel, interaction tone. It illustrates *one way* the spec below could look, not the only acceptable way to build it.
- **If the prototype and this spec ever conflict, this spec wins.** The prototype may be visually out of date or simplified in ways that don't reflect later decisions (e.g., it may not show every validation state or the Results view).
- Antigravity is free to deviate from the prototype's exact layout, styling, copy, and component choices, as long as the resulting UI still satisfies every rule in Sections 1–8 below.

---

## 1. Form Structure and Composition Logic

The form presents three sections as cards, each with a top-level checkbox:

- **Request A — Online Research** (`want_report`)
- **Request B — Interview Transcription** (`want_transcript`)
- **Request C — Recommendation** (`want_recommendation`) — labeled "opt-in"

### Composition rules (must be enforced in the UI, not just on submit)

- At least one of `want_report` or `want_transcript` must be checked.
- `want_recommendation`'s checkbox is **disabled** (grayed out, not clickable) unless at least one of `want_report` or `want_transcript` is checked. No error message is needed for this — the disabled state plus a helper line ("Requires Report or Transcript") communicates it directly. This matches the validated visual design (see reference screenshot): unclickable, not error-flagged.
- `want_mindmap` (the Miro add-on) only appears/is enabled when `want_transcript` is checked. It is a sub-option nested under the Transcript section, not a top-level choice.
- Each section expands to reveal its fields only when its checkbox is checked; unchecked sections stay collapsed to a single line.

Valid combinations: A, B, A+B, A+C, B+C, A+B+C (B optionally carrying `want_mindmap`).

---

## 2. Fields Per Section

### Report (A) — visible when `want_report` is checked

| Field | Type | Required |
|---|---|---|
| `topic` | Text input | Yes (hard) |

Placeholder: *"What do you want researched? Be specific — e.g. 'AI code review tools for enterprise dev teams' rather than 'AI tools'."*

### Transcript (B) — visible when `want_transcript` is checked

| Field | Type | Required |
|---|---|---|
| Input file | File upload (audio: .mp3/.wav/.m4a, or text: .txt) | Yes (hard) |
| `interview_purpose` | Text input | Yes (hard) |
| `business_context` | Textarea | Yes (hard) |
| `participant_count` | Number input | No (soft) |
| `project_goals` | Text input | No (soft) |
| `want_mindmap` | Checkbox, "Also generate a Miro mind map" | No — independent add-on |

**Important:** text transcripts are uploaded as a file (.txt), never pasted into a textarea. Both audio and text inputs use the same upload widget; the accepted file types differ, and the system determines audio vs. text by file type.

### Recommendation (C)

| Field | Type | Required |
|---|---|---|
| `want_recommendation` | Checkbox, disabled unless A or B is checked | No — opt-in |

No additional fields — it's a single toggle.

---

## 3. Client-Side Validation (Tier 1 — blocks submit)

These are caught live as the user fills the form; the submit button should reflect an invalid state rather than letting the user click into a dead end where possible.

| Scenario | Message |
|---|---|
| Neither Report nor Transcript selected | Submit button disabled. Tooltip: "Select Report or Transcript to continue." |
| Report selected, topic empty | Inline under field: "Add a topic to research." |
| Transcript selected, no file uploaded | Inline under upload widget: "Upload an audio or text file." |
| Transcript selected, interview purpose empty | Inline: "Tell us the interview's purpose — this helps format it well." |
| Transcript selected, business context empty | Inline: "Add some background context (company, product, etc.)." |
| Recommendation checked without A/B | Not reachable — checkbox is disabled, no error message needed. |

---

## 4. File Constraints

- **Max file size: 40 MB**, for both audio and text uploads.
- Error message: **"File is too large (max 40 MB)."**
- Wrong file type: "Unsupported file type. Upload an audio file (.mp3, .wav, .m4a) or a text file (.txt)."
- Empty/corrupted file: "This file appears to be empty or unreadable — try uploading again."

---

## 5. Clarification Loop (Tier 2 — post-submit, not an error)

After submit, if the Orchestrator's Tier 2 semantic check flags gaps, the response distinguishes hard vs. soft. The UI reflects this as follows:

- **Soft gap only:** request proceeds automatically. Non-blocking banner shown during processing: "Proceeding with what you provided — some details were inferred and will be flagged in the output."
- **Hard gap, round 1 or 2:** the form does **not** reset or navigate away. Instead, the missing field(s) are rendered as new inline inputs **appended directly under the relevant section** (Report or Transcript) that the user already filled in — not in a separate modal, chatbot, or new page. Framed as a helpful ask, not an error: "A couple more details will help: [specific question]."
- **Hard gap still unresolved after round 2 (capped):** blocking message, calm and specific: "We still need [X] to continue. Your request has been saved — come back within 48 hours to add it, or start over."
  - This is the one case where state *does* persist across a page reload (see Section 7 — Session Behavior), since it's backed by the 48-hour TTL store.

---

## 6. Runtime Failure Handling (during agent processing)

| Scenario | Message |
|---|---|
| Speech-to-text failure | "We couldn't transcribe this audio. Try again, or upload a text transcript instead." |
| Agent/LLM failure (any pipeline stage) | "Something went wrong while generating your [report/transcript/recommendation]. Please try again." |
| Miro board creation failure | Degrades gracefully — does not block or fail the rest of the request. Handled via the Results View (Section 7): the Mind Map artifact shows its own "Failed" state with a "Retry mind map" button, independent of the other artifacts. |
| Generic timeout | "This is taking longer than expected. Please try again." — this requires a full resubmit; there is no persisted state to resume from (active runs are in-memory only), so there is no passive "check back later" option for this case. |
| Unclassified/unexpected error | "Something unexpected happened. Please try again or start a new request." |

---

## 7. Results View

**Placement:** appears **below the form** after submit. The form itself remains visible and usable — the user is not blocked from starting another request.

**Structure:** one card/row per artifact the user actually requested (not per agent — the user doesn't need to know about Writer/Editor/Advisor internals). Each artifact has its own independent status:

| Artifact | Shown when | States |
|---|---|---|
| Report | `want_report` true | Generating → Ready (download) / Failed (retry) |
| Transcript | `want_transcript` true | Generating → Ready (download) / Failed (retry) |
| Mind Map | `want_mindmap` true | Generating → Ready (Miro board link) / Failed (retry just this artifact) |
| Recommendation | `want_recommendation` true | Generating → Ready (download) / Failed (retry) |

Each artifact's state is independent — e.g., a Mind Map failure never blocks or hides the Report/Transcript/Recommendation cards; they can each be in different states simultaneously.

The Miro board link (once ready) is surfaced here, not embedded in the downloaded Markdown file.

---

## 8. Session and Persistence Behavior

- **Results view and any in-progress/completed state:** resets entirely on page refresh, tab close/reopen, or navigation away. This is intentional — active runs are pure in-memory per the system's no-persistent-storage design, so nothing survives a reload here, including "Retry" states.
- **Incomplete requests stuck on a hard-requirement gap (Section 5):** the one exception. These persist for **48 hours** (backed by the SQLite TTL store) and should still be present if the user returns within that window. After 48 hours, the request is auto-purged; if the user returns after expiry: "This request has expired and was removed. Please start a new one."
