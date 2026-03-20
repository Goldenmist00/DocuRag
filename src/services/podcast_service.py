"""
podcast_service.py
==================
Orchestrates podcast generation from notebook sources.

Pipeline stages:
  1. retrieving  — fetch top-k chunks from the notebook
  2. scripting   — LLM generates a two-host conversational transcript
  3. synthesizing — TTS converts each speaker turn into audio via Deepgram Aura
  4. assembling  — concatenate audio segments into a single MP3
  5. ready       — podcast available for playback

Uses Deepgram Aura for high-quality neural TTS synthesis.
Requires DEEPGRAM_API_KEY in .env.
"""

import logging
import os
import re
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import requests as http_requests
from dotenv import load_dotenv

from src.db import podcast_db, source_db, notebook_db
from src.retriever import RetrievedChunk

load_dotenv()
logger = logging.getLogger(__name__)

PODCAST_DIR = Path("uploads/podcasts")
PODCAST_DIR.mkdir(parents=True, exist_ok=True)

DEEPGRAM_API_KEY = os.getenv("DEEPGRAM_API_KEY", "")
DEEPGRAM_TTS_URL = "https://api.deepgram.com/v1/speak"

VOICE_HOST_1 = "aura-orion-en"
VOICE_HOST_2 = "aura-asteria-en"

HOST_1_NAME = "Alex"
HOST_2_NAME = "Sarah"

_RETRIEVE_TOP_K = 20

PODCAST_SYSTEM_PROMPT = f"""You are a podcast script writer. Create an engaging, \
natural-sounding conversational podcast transcript between two hosts discussing \
the provided content.

Hosts:
- {HOST_1_NAME}: Curious and engaging host who asks insightful questions, \
summarises key points, and keeps the conversation flowing.
- {HOST_2_NAME}: Knowledgeable expert who provides detailed explanations, \
adds real-world examples, and offers deeper insights.

Rules:
- Cover ALL important points from the provided content.
- Make the conversation natural — use transitions like "That's a great point", \
"Building on that", "What I find interesting is".
- Each speaker turn should be 2-4 sentences. Never exceed 5 sentences per turn.
- Start with a brief, enthusiastic introduction of the topic.
- End with a concise summary and takeaway for listeners.
- Aim for 12-20 exchanges total (6-10 per host).
- Do NOT use any markdown, bullet points, or formatting.
- Do NOT include stage directions, sound effects, or actions in brackets.

Output format — use EXACTLY this format for every line:
{HOST_1_NAME}: [dialogue here]
{HOST_2_NAME}: [dialogue here]
{HOST_1_NAME}: [dialogue here]
..."""

PODCAST_USER_TEMPLATE = """Source material to discuss:

{content}

Generate the podcast transcript now:"""


def generate_podcast(
    notebook_id: str,
    retriever,
    generator,
) -> Dict:
    """
    Trigger podcast generation for a notebook.

    Creates a podcast record and returns it immediately. The actual
    generation runs synchronously (called from a thread pool by the
    API layer).

    Args:
        notebook_id: Notebook UUID whose sources feed the podcast.
        retriever: Configured Retriever instance.
        generator: Configured Generator instance.

    Returns:
        Podcast dict with initial status.

    Raises:
        ValueError: If notebook not found or has no ready sources.
    """
    nb = notebook_db.get_notebook(notebook_id)
    if not nb:
        raise ValueError(f"Notebook not found: {notebook_id}")

    sources = source_db.list_sources(notebook_id)
    ready = [s for s in sources if s.get("status") == "ready"]
    if not ready:
        raise ValueError("No ready sources in this notebook. Upload and process sources first.")

    existing = podcast_db.get_podcast_by_notebook(notebook_id)
    if existing and existing["status"] in ("pending", "retrieving", "scripting", "synthesizing", "assembling"):
        return existing

    podcast = podcast_db.create_podcast(notebook_id, status="pending")
    logger.info("Podcast %s created for notebook %s", podcast["id"], notebook_id)
    return podcast


def process_podcast(
    podcast_id: str,
    retriever,
    generator,
) -> None:
    """
    Run the full podcast generation pipeline.

    This is a long-running synchronous function meant to be called
    from a thread pool executor.

    Args:
        podcast_id: UUID of the podcast record to process.
        retriever: Configured Retriever instance.
        generator: Configured Generator instance.
    """
    podcast = podcast_db.get_podcast(podcast_id)
    if not podcast:
        logger.error("Podcast %s not found — skipping", podcast_id)
        return

    notebook_id = podcast["notebook_id"]

    try:
        _set_status(podcast_id, "retrieving")

        sources = source_db.list_sources(notebook_id)
        ready = [s for s in sources if s.get("status") == "ready"]
        ready_with_chunks = [s for s in ready if (s.get("chunk_count") or 0) > 0]

        logger.info(
            "Podcast %s: notebook %s has %d sources (%d ready, %d with chunks)",
            podcast_id, notebook_id, len(sources), len(ready), len(ready_with_chunks),
        )

        if not ready_with_chunks:
            podcast_db.update_podcast(
                podcast_id,
                status="error",
                error_message=(
                    f"No processable sources found. "
                    f"{len(sources)} sources total, {len(ready)} ready, "
                    f"{len(ready_with_chunks)} with chunks. "
                    f"Re-upload your sources and wait for processing to complete."
                ),
            )
            return

        actual_db_count = _count_chunks_in_db(notebook_id)
        logger.info(
            "Podcast %s: actual DB chunk count for notebook = %d",
            podcast_id, actual_db_count,
        )

        if actual_db_count == 0:
            podcast_db.update_podcast(
                podcast_id,
                status="error",
                error_message=(
                    f"Source metadata shows {sum(s.get('chunk_count', 0) for s in ready)} "
                    f"chunks but the vector store table has 0 rows for this notebook. "
                    f"Re-upload your sources to regenerate embeddings."
                ),
            )
            return

        chunks = retriever.retrieve(
            query="Summarise the key topics, concepts, and important details",
            top_k=_RETRIEVE_TOP_K,
            notebook_id=notebook_id,
        )

        if not chunks:
            logger.warning(
                "Podcast %s: retriever returned 0 but DB has %d rows — "
                "falling back to chunk_db.search()",
                podcast_id, actual_db_count,
            )
            chunks = _fallback_retrieve(notebook_id, retriever)

        if not chunks:
            podcast_db.update_podcast(
                podcast_id,
                status="error",
                error_message=(
                    f"Could not retrieve chunks. DB has {actual_db_count} rows "
                    f"for this notebook but both retriever and fallback returned 0."
                ),
            )
            return

        _set_status(podcast_id, "scripting")
        transcript = _generate_transcript(chunks, generator)

        if not transcript:
            podcast_db.update_podcast(
                podcast_id,
                status="error",
                error_message="Failed to generate transcript.",
            )
            return

        _set_status(podcast_id, "synthesizing")
        turns = _parse_transcript(transcript)

        if not turns:
            podcast_db.update_podcast(
                podcast_id,
                status="error",
                error_message="Could not parse transcript into speaker turns.",
            )
            return

        audio_segments = _synthesize_turns(turns, podcast_id)

        _set_status(podcast_id, "assembling")
        audio_path = _assemble_audio(audio_segments, notebook_id, podcast_id)

        podcast_db.update_podcast(
            podcast_id,
            status="ready",
            transcript=transcript,
            audio_path=str(audio_path),
        )
        logger.info("Podcast %s ready — %s", podcast_id, audio_path)

    except Exception as exc:
        logger.error("Podcast %s failed: %s", podcast_id, exc, exc_info=True)
        podcast_db.update_podcast(
            podcast_id,
            status="error",
            error_message=str(exc)[:500],
        )


def get_podcast_for_notebook(notebook_id: str) -> Optional[Dict]:
    """
    Get the latest podcast for a notebook.

    Args:
        notebook_id: Notebook UUID.

    Returns:
        Podcast dict or None.
    """
    return podcast_db.get_podcast_by_notebook(notebook_id)


def delete_podcast(podcast_id: str) -> None:
    """
    Delete a podcast and its audio file from disk.

    Args:
        podcast_id: UUID string.

    Raises:
        ValueError: If podcast not found.
    """
    podcast = podcast_db.get_podcast(podcast_id)
    if not podcast:
        raise ValueError(f"Podcast not found: {podcast_id}")

    if podcast.get("audio_path"):
        try:
            Path(podcast["audio_path"]).unlink(missing_ok=True)
        except Exception as exc:
            logger.warning("Could not remove audio file %s: %s", podcast["audio_path"], exc)

    deleted = podcast_db.delete_podcast(podcast_id)
    if not deleted:
        raise ValueError(f"Podcast not found: {podcast_id}")
    logger.info("Deleted podcast %s", podcast_id)


# ─── Internal helpers ───


def _count_chunks_in_db(notebook_id: str) -> int:
    """
    Direct SQL count of chunks for a notebook in the document_chunks table.

    Bypasses the retriever and vector_store to check actual DB state.

    Args:
        notebook_id: Notebook UUID.

    Returns:
        Number of rows in document_chunks for this notebook.
    """
    from src.db.connection import get_connection

    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT COUNT(*) FROM document_chunks WHERE notebook_id = %s",
                    (notebook_id,),
                )
                return cur.fetchone()[0]
    except Exception as exc:
        logger.error("Failed to count chunks for notebook %s: %s", notebook_id, exc)
        return -1


def _fallback_retrieve(notebook_id: str, retriever) -> list:
    """
    Fallback retrieval using chunk_db.search() via the shared connection pool.

    Used when the PgVectorStore retriever returns 0 results despite chunks
    existing in the database — typically caused by connection pool mismatch
    between the vector store's pool and the shared pool.

    Args:
        notebook_id: Notebook UUID.
        retriever: Retriever instance (used for its embedder).

    Returns:
        List of RetrievedChunk objects.
    """
    from src.db import chunk_db
    from src.retriever import RetrievedChunk

    try:
        query_vec = retriever.embedder.embed(
            "Summarise the key topics, concepts, and important details"
        )
        raw = chunk_db.search(query_vec, top_k=_RETRIEVE_TOP_K, notebook_id=notebook_id)
        chunks = [
            RetrievedChunk(
                chunk_id=r.get("chunk_id", ""),
                text=r.get("text", ""),
                score=float(r.get("score", 0.0)),
                section_id=r.get("section_id", "") or "",
                chapter_id=r.get("chapter_id", "") or "",
                section_title=r.get("section_title", "") or "",
                page_start=r.get("page_num", 0) or 0,
                page_end=r.get("page_num", 0) or 0,
                chunk_index=r.get("chunk_index", 0) or 0,
            )
            for r in raw
        ]
        logger.info("Fallback retrieval returned %d chunks", len(chunks))
        return chunks
    except Exception as exc:
        logger.error("Fallback retrieval failed: %s", exc)
        return []


def _set_status(podcast_id: str, status: str) -> None:
    """
    Update podcast status with retry for transient DB failures.

    Args:
        podcast_id: UUID string.
        status: New status value.
    """
    for attempt in range(3):
        try:
            podcast_db.update_podcast(podcast_id, status=status)
            return
        except Exception as exc:
            if attempt < 2:
                logger.warning(
                    "Podcast status update to '%s' failed (attempt %d/3): %s",
                    status, attempt + 1, exc,
                )
                time.sleep(2 ** attempt)
            else:
                logger.error("Podcast status update to '%s' failed after 3 attempts: %s", status, exc)


def _generate_transcript(chunks: List[RetrievedChunk], generator) -> str:
    """
    Use the LLM to produce a conversational podcast transcript.

    Builds a content block from retrieved chunks and sends it through
    the generator's LLM with a podcast-specific system prompt.

    Args:
        chunks: Retrieved chunks from the notebook.
        generator: Configured Generator instance.

    Returns:
        Raw transcript string with speaker-prefixed lines.
    """
    content_parts = []
    for i, chunk in enumerate(chunks, 1):
        header = chunk.citation()
        content_parts.append(f"[{i}] {header}\n{chunk.text}")

    content = "\n\n".join(content_parts)
    user_prompt = PODCAST_USER_TEMPLATE.format(content=content)

    payload = {
        "model": generator.model,
        "messages": [
            {"role": "system", "content": PODCAST_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        "max_tokens": 4096,
        "temperature": 0.7,
        "top_p": 0.95,
        "stream": True,
    }

    import requests
    import json

    try:
        response = requests.post(
            generator._url,
            headers=generator._headers,
            json=payload,
            timeout=180,
        )
        response.raise_for_status()
        return generator._parse_stream(response)
    except Exception as exc:
        logger.error("Transcript generation failed: %s", exc)
        if generator._groq_headers:
            logger.info("Falling back to Groq for transcript generation")
            payload["model"] = "llama-3.3-70b-versatile"
            try:
                response = requests.post(
                    "https://api.groq.com/openai/v1/chat/completions",
                    headers=generator._groq_headers,
                    json=payload,
                    timeout=120,
                )
                response.raise_for_status()
                return generator._parse_stream(response)
            except Exception as fallback_exc:
                raise RuntimeError(
                    f"Both providers failed for transcript: {fallback_exc}"
                ) from fallback_exc
        raise


def _parse_transcript(transcript: str) -> List[Tuple[str, str]]:
    """
    Parse a raw transcript string into a list of (speaker, text) tuples.

    Expects lines formatted as "SPEAKER: dialogue text".

    Args:
        transcript: Raw LLM-generated transcript.

    Returns:
        List of (speaker_name, dialogue_text) tuples.
    """
    pattern = re.compile(
        rf"^({re.escape(HOST_1_NAME)}|{re.escape(HOST_2_NAME)}):\s*(.+)",
        re.MULTILINE,
    )

    turns: List[Tuple[str, str]] = []
    for match in pattern.finditer(transcript):
        speaker = match.group(1).strip()
        text = match.group(2).strip()
        if text:
            turns.append((speaker, text))

    logger.info("Parsed %d speaker turns from transcript", len(turns))
    return turns


def _synthesize_turns(
    turns: List[Tuple[str, str]],
    podcast_id: str,
) -> List[bytes]:
    """
    Convert each speaker turn into MP3 audio using Deepgram Aura TTS.

    Each turn is sent as a POST to the Deepgram ``/v1/speak`` endpoint
    with the appropriate voice model. The response body is raw MP3 bytes.

    Args:
        turns: List of (speaker_name, dialogue_text) tuples.
        podcast_id: For logging/progress updates.

    Returns:
        List of MP3 byte segments in turn order.

    Raises:
        RuntimeError: If DEEPGRAM_API_KEY is not configured.
    """
    if not DEEPGRAM_API_KEY:
        raise RuntimeError(
            "DEEPGRAM_API_KEY is not set in .env — cannot synthesize audio."
        )

    voice_map = {
        HOST_1_NAME: VOICE_HOST_1,
        HOST_2_NAME: VOICE_HOST_2,
    }

    headers = {
        "Authorization": f"Token {DEEPGRAM_API_KEY}",
        "Content-Type": "application/json",
    }

    segments: List[bytes] = []
    total = len(turns)

    for idx, (speaker, text) in enumerate(turns):
        voice = voice_map.get(speaker, VOICE_HOST_1)
        logger.info(
            "Synthesizing turn %d/%d (%s, %d chars, voice=%s)",
            idx + 1, total, speaker, len(text), voice,
        )
        _set_status(podcast_id, f"synthesizing {idx + 1}/{total}")

        url = f"{DEEPGRAM_TTS_URL}?model={voice}&encoding=mp3"

        for attempt in range(3):
            try:
                resp = http_requests.post(
                    url,
                    headers=headers,
                    json={"text": text},
                    timeout=60,
                )
                resp.raise_for_status()
                segments.append(resp.content)
                break
            except http_requests.exceptions.HTTPError as exc:
                if resp.status_code == 429 and attempt < 2:
                    wait = 2 ** (attempt + 1)
                    logger.warning(
                        "Deepgram rate limit on turn %d — waiting %ds",
                        idx + 1, wait,
                    )
                    time.sleep(wait)
                else:
                    raise RuntimeError(
                        f"Deepgram TTS failed for turn {idx + 1}: "
                        f"{resp.status_code} {resp.text[:200]}"
                    ) from exc
            except Exception as exc:
                if attempt < 2:
                    time.sleep(1)
                else:
                    raise RuntimeError(
                        f"Deepgram TTS failed for turn {idx + 1}: {exc}"
                    ) from exc

    return segments


def _assemble_audio(
    segments: List[bytes],
    notebook_id: str,
    podcast_id: str,
) -> Path:
    """
    Concatenate MP3 audio segments into a single file.

    MP3 is a frame-based format — raw byte concatenation produces
    a valid, playable file.

    Args:
        segments: List of MP3 byte arrays in order.
        notebook_id: For directory structure.
        podcast_id: For filename uniqueness.

    Returns:
        Path to the assembled MP3 file.
    """
    out_dir = PODCAST_DIR / notebook_id
    out_dir.mkdir(parents=True, exist_ok=True)

    out_path = out_dir / f"{podcast_id}.mp3"

    with open(out_path, "wb") as f:
        for segment in segments:
            f.write(segment)

    total_bytes = sum(len(s) for s in segments)
    logger.info(
        "Assembled %d segments → %s (%.1f KB)",
        len(segments), out_path, total_bytes / 1024,
    )
    return out_path
