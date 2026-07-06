"""Transcriber — calls OpenAI Whisper API for audio, or reads text files.

Receives: file path (audio or text).
Produces: raw transcript string.

For audio files under 25 MB, calls Whisper API directly.
For audio files over 25 MB, splits into 10-minute chunks, transcribes
each chunk in parallel, then merges the results.
For text files, reads the file content directly.

Contract ref: Agent-Contracts-Reference.md §4 (Transcriber row)
"""

import concurrent.futures
import logging
import os
import tempfile
from pathlib import Path

from openai import OpenAI

from app import credentials

logger = logging.getLogger(__name__)

# Whisper API hard limit
_WHISPER_MAX_BYTES = 25 * 1024 * 1024  # 25 MB

# Chunking config
_CHUNK_MS = 10 * 60 * 1000   # 10 minutes per chunk
_MAX_WORKERS = 4              # parallel Whisper calls

_AUDIO_EXTENSIONS = {".mp3", ".wav", ".m4a", ".webm", ".mp4", ".mpeg", ".mpga", ".oga", ".ogg"}


def transcribe_file(file_path: str) -> str:
    """Transcribe an audio file or read a text file.

    Args:
        file_path: Absolute path to the input file.

    Returns:
        Raw transcript as a string.

    Raises:
        FileNotFoundError: If the file doesn't exist.
        ValueError: If the file type is unsupported.
    """
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")

    ext = path.suffix.lower()

    if ext in _AUDIO_EXTENSIONS:
        return _transcribe_audio(path)
    elif ext in {".txt", ".md", ".text"}:
        return path.read_text(encoding="utf-8")
    else:
        raise ValueError(
            f"Unsupported file type: {ext}. "
            f"Supported audio: {_AUDIO_EXTENSIONS}. Text: .txt, .md"
        )


def _transcribe_audio(path: Path) -> str:
    """Route to direct or chunked transcription based on file size."""
    file_size = path.stat().st_size

    if file_size <= _WHISPER_MAX_BYTES:
        logger.info(f"Transcribing directly ({file_size / (1024*1024):.1f} MB): {path.name}")
        return _whisper_direct(path)
    else:
        logger.info(
            f"File {file_size / (1024*1024):.1f} MB > 25 MB limit — "
            f"splitting into {_CHUNK_MS // 60000}-minute chunks"
        )
        return _transcribe_chunked(path)


def _whisper_direct(path: Path) -> str:
    """Call Whisper API on a single file."""
    client = OpenAI(api_key=credentials.openai_api_key)
    with open(path, "rb") as audio_file:
        response = client.audio.transcriptions.create(
            model="whisper-1",
            file=audio_file,
            response_format="text",
        )
    return response


def _transcribe_chunked(path: Path) -> str:
    """Split audio into chunks, transcribe in parallel, merge results.

    Strategy:
      1. Load audio with pydub (uses ffmpeg under the hood)
      2. Slice into non-overlapping 10-minute segments
      3. Export each segment as a temporary MP3
      4. Transcribe all chunks concurrently (up to 4 at a time)
      5. Concatenate transcripts in order
    """
    try:
        from pydub import AudioSegment
    except ImportError:
        raise RuntimeError(
            "pydub is required for files > 25 MB. Install it with: uv add pydub"
        )

    # Load full audio
    logger.info(f"Loading audio: {path.name}")
    audio = AudioSegment.from_file(str(path))
    duration_ms = len(audio)
    logger.info(f"Duration: {duration_ms / 60000:.1f} minutes")

    # Slice into chunks
    chunk_ranges = []
    start = 0
    while start < duration_ms:
        end = min(start + _CHUNK_MS, duration_ms)
        chunk_ranges.append((start, end))
        start = end

    logger.info(f"Splitting into {len(chunk_ranges)} chunks")

    client = OpenAI(api_key=credentials.openai_api_key)

    def transcribe_chunk(idx: int, start_ms: int, end_ms: int) -> tuple[int, str]:
        """Export one chunk to a temp file and call Whisper on it."""
        segment = audio[start_ms:end_ms]
        minutes = f"{start_ms // 60000:.0f}m–{end_ms // 60000:.0f}m"

        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
            tmp_path = tmp.name

        try:
            logger.info(f"Chunk {idx + 1}/{len(chunk_ranges)} ({minutes}): exporting…")
            segment.export(tmp_path, format="mp3")

            logger.info(f"Chunk {idx + 1}/{len(chunk_ranges)} ({minutes}): transcribing…")
            with open(tmp_path, "rb") as f:
                response = client.audio.transcriptions.create(
                    model="whisper-1",
                    file=f,
                    response_format="text",
                )
            logger.info(f"Chunk {idx + 1}/{len(chunk_ranges)} ({minutes}): done ✓")
            return idx, str(response)
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

    # Transcribe all chunks in parallel
    results: list[str] = [""] * len(chunk_ranges)
    with concurrent.futures.ThreadPoolExecutor(max_workers=_MAX_WORKERS) as executor:
        futures = {
            executor.submit(transcribe_chunk, i, start, end): i
            for i, (start, end) in enumerate(chunk_ranges)
        }
        for future in concurrent.futures.as_completed(futures):
            try:
                idx, text = future.result()
                results[idx] = text
            except Exception as e:
                idx = futures[future]
                logger.error(f"Chunk {idx + 1} failed: {e}")
                results[idx] = f"[Transcription error in chunk {idx + 1}: {e}]"

    # Merge: join with a single newline between chunks
    transcript = "\n".join(chunk.strip() for chunk in results if chunk.strip())
    logger.info(f"Chunked transcription complete — {len(transcript)} characters")
    return transcript
