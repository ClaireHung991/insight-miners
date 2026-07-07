# Changelog

All notable changes to **Insight Miners** are documented here.

---

## [Unreleased]

### Added
- `.md` (Markdown) file support for interview transcript upload — frontend only change; backend already handled it via `transcriber.py`

---

## [2026-07-07]

### Changed
- **Parallel pipeline execution** — when both Research (A) and Interview (B) are selected, pipelines now run concurrently via `asyncio.gather` instead of sequentially. Roughly halves wall-clock time for combined requests.

---

## [2026-07-06]

### Added
- **Miro mind map integration** — switched from broken MCP-based approach to direct Miro REST API v2. Uses `sticky_notes` + `connectors` to build a radial hierarchy. One new board is created per submission.
- **Project renamed** to **Insight Miners** (was "Product Discovery Team") — updated frontend title, README, Kaggle write-up, Docker image name, and directory references.
- **CHANGELOG.md** — this file.
- **docs/kaggle-writeup.md** — Kaggle competition submission write-up (internal, not published to GitHub).
- **README.md** — comprehensive production-quality documentation including architecture diagrams, engineering decisions, and full environment variable reference.
- **Configuration section in README** — step-by-step credential setup guide with `[!CAUTION]` warning and links to each API key source.

### Changed
- **Speaker identification in transcripts** — `transcript_cleaner.md` prompt updated to extract real names from interview context (e.g. outputs `Jensen Huang:` instead of `Interviewee:` when the name is inferable).
- **Frontend font sizes** — updated across all element types: h1 (26px), section headings/submit button (17px, weight 600), inputs/textareas (15.5px), field labels/descriptions (14.5px), helper/error text (13px), payload pre block (13.5px).
- **Input field backgrounds** — changed from grey to white (`#ffffff`) to match design reference.
- **Research Topic field** — converted from single-line `<input>` to multi-line `<textarea rows="5">` for better writing experience.

### Removed
- **Preview button** — removed from all download/output cards across the UI.

### Security
- **`.gitignore` hardened** — added `app/_uploads/*` and `app/incomplete_requests.db` to prevent user-uploaded files and runtime SQLite database from being committed.
- **`app/_uploads/.gitkeep`** — added so the uploads directory structure is preserved in the repo without committing any contents.
- **`docs/` folder excluded from GitHub** — internal design documents, contracts, and writeup are gitignored and never published.

---

## [2026-07-05]

### Added
- **Chunked parallel audio transcription** — files over Whisper's 25 MB hard limit are split into 10-minute chunks via `pydub`, transcribed concurrently with up to 4 `ThreadPoolExecutor` workers, and merged in order.
- **Transient API error retry** — `_run_workflow` retries up to 3 times on 429/503 errors with linear backoff (15s, 30s, 45s).
- **Scoped data envelopes** — `Envelope` Pydantic model ensures each pipeline only receives the fields it needs (data minimization).
- **Prompt files as versioned Markdown** — all agent system prompts live in `app/prompts/*.md` with YAML frontmatter (`version`, `changelog`). Behavioral changes require no code edits.
- **48-hour TTL for incomplete requests** — persisted to SQLite; `purge_expired()` called on each Orchestrator session start.
- **File size display fix** — frontend now shows correct MB size (was showing incorrect value due to unit mismatch).

### Changed
- **Submit button** — fixed spinning state; button now correctly stops after submission completes or fails.

---

## Format

This changelog follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) conventions.
Sections per release: `Added`, `Changed`, `Removed`, `Fixed`, `Security`.
