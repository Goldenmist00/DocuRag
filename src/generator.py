"""
generator.py
============
Phase 5 — Answer Generation

Provider priority:
  1. NVIDIA API  (meta/llama-3.3-70b-instruct)  — if NVIDIA_API_KEY is set
  2. Groq API    (llama-3.3-70b-versatile) — if GROQ_API_KEY is set
  3. Raises ValueError if neither key is available

If NVIDIA fails at runtime, automatically falls back to Groq for that query.
Both providers use requests + SSE streaming.
"""

import json
import logging
import os
import re
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import requests

from src.retriever import RetrievedChunk

logger = logging.getLogger(__name__)

NVIDIA_URL = "https://integrate.api.nvidia.com/v1/chat/completions"
GROQ_URL   = "https://api.groq.com/openai/v1/chat/completions"

NVIDIA_MODEL = "meta/llama-3.3-70b-instruct"
GROQ_MODEL   = "llama-3.3-70b-versatile"

SYSTEM_PROMPT = """You are a knowledgeable assistant that answers questions \
using ONLY the provided context passages.

Rules:
- Base your answer strictly on the context below.
- Cite sources using [1], [2], etc. matching the numbered passages.
- If the context does not contain enough information, say so clearly and \
state which aspects of the question you cannot fully address.
- If passages contain contradictory information, note the contradiction \
explicitly and cite both sources so the user can evaluate.
- Do not fabricate information.

Formatting (you MUST follow these rules):
- Use **bold** for key terms and important concepts.
- Use bullet points (- item) or numbered lists (1. item) when listing multiple items.
- Always use ### before section headings. Example: ### Key Issues
- Keep paragraphs short (2-3 sentences each).
- Place citation markers [1], [2] inline next to the relevant claim.
- Never use # or ## headings — only ### for headings.
- Separate sections with a blank line before each ### heading."""

USER_TEMPLATE = """Context passages:
{context}

Question: {question}

Answer (cite sources with [1], [2], etc.):"""


@dataclass
class AnswerGradeResult:
    """Quality grade returned alongside the answer."""
    faithfulness: float = 0.0
    completeness: float = 0.0
    citation_accuracy: float = 0.0
    overall: float = 0.0
    passed: bool = True
    issues: List[str] = field(default_factory=list)


@dataclass
class AnswerResult:
    question: str
    answer: str
    citations: List[Dict] = field(default_factory=list)
    model: str = ""
    latency_ms: float = 0.0
    chunks_used: int = 0
    grade: Optional[AnswerGradeResult] = None



class Generator:
    """
    Multi-provider LLM generator (NVIDIA → Groq runtime fallback).
    Uses requests + SSE streaming for both providers.
    """

    def __init__(
        self,
        model: Optional[str] = None,
        temperature: float = 0.3,
        max_tokens: int = 1024,
        top_p: float = 0.9,
        api_key: Optional[str] = None,
        max_retries: int = 2,
    ):
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.top_p = top_p
        self.max_retries = max_retries

        # Detect providers
        nvidia_key = (api_key or os.getenv("NVIDIA_API_KEY", "")).strip()
        groq_key   = os.getenv("GROQ_API_KEY", "").strip()

        self._nvidia_valid = bool(nvidia_key and nvidia_key != "your_nvidia_api_key_here")
        self._groq_valid   = bool(groq_key)

        if not self._nvidia_valid and not self._groq_valid:
            raise ValueError(
                "No LLM API key found. Set NVIDIA_API_KEY or GROQ_API_KEY in .env"
            )

        # Primary provider — NVIDIA, fallback to Groq
        if self._nvidia_valid:
            self._provider = "nvidia"
            self._url      = NVIDIA_URL
            self.model     = model or NVIDIA_MODEL
            self._headers  = {
                "Authorization": f"Bearer {nvidia_key}",
                "Accept":        "text/event-stream",
                "Content-Type":  "application/json",
            }
        else:
            self._provider = "groq"
            self._url      = GROQ_URL
            self.model     = model or GROQ_MODEL
            self._headers  = {
                "Authorization": f"Bearer {groq_key}",
                "Accept":        "text/event-stream",
                "Content-Type":  "application/json",
            }

        # Groq fallback headers (used if NVIDIA fails mid-run)
        self._groq_headers: Optional[Dict] = None
        if self._nvidia_valid and self._groq_valid:
            self._groq_headers = {
                "Authorization": f"Bearer {groq_key}",
                "Accept":        "text/event-stream",
                "Content-Type":  "application/json",
            }

        logger.info(
            "Generator ready | provider=%s | model=%s | max_tokens=%d",
            self._provider, self.model, self.max_tokens,
        )

    # ------------------------------------------------------------------

    def generate(
        self,
        question: str,
        chunks: List[RetrievedChunk],
        validator=None,
    ) -> AnswerResult:
        """
        Generate an answer from retrieved chunks, optionally validating quality.

        When a validator is provided, the answer is graded. If it fails,
        a single retry is attempted with corrective feedback appended
        to the prompt. The best attempt is returned.

        Args:
            question:  User's question.
            chunks:    Retrieved context chunks.
            validator: Optional AnswerValidator instance.

        Returns:
            AnswerResult with answer, citations, and optional grade.
        """
        if not chunks:
            return AnswerResult(
                question=question,
                answer="I could not find relevant information to answer this question.",
                model=self.model,
            )

        context = self._build_context(chunks)
        prompt = USER_TEMPLATE.format(context=context, question=question)

        t0 = time.time()
        answer_text = self._call_api(prompt)
        latency_ms = (time.time() - t0) * 1000

        citations = self._extract_citations(answer_text, chunks)
        grade_result: Optional[AnswerGradeResult] = None

        if validator and hasattr(validator, "grade") and validator.available:
            from src.services.answer_validator import AnswerGrade

            grade: AnswerGrade = validator.grade(question, answer_text, chunks)
            grade_result = AnswerGradeResult(
                faithfulness=grade.faithfulness,
                completeness=grade.completeness,
                citation_accuracy=grade.citation_accuracy,
                overall=grade.overall,
                passed=grade.passed,
                issues=grade.issues,
            )

            if not grade.passed and grade.feedback:
                logger.info(
                    "Answer failed validation (%.2f) — retrying with feedback",
                    grade.overall,
                )
                retry_prompt = (
                    prompt
                    + f"\n\n[QUALITY FEEDBACK: {grade.feedback}]\n\n"
                    "Please provide an improved answer addressing the feedback above:"
                )
                t1 = time.time()
                retry_text = self._call_api(retry_prompt)
                latency_ms += (time.time() - t1) * 1000

                retry_grade: AnswerGrade = validator.grade(question, retry_text, chunks)

                if retry_grade.overall >= grade.overall:
                    answer_text = retry_text
                    citations = self._extract_citations(answer_text, chunks)
                    grade_result = AnswerGradeResult(
                        faithfulness=retry_grade.faithfulness,
                        completeness=retry_grade.completeness,
                        citation_accuracy=retry_grade.citation_accuracy,
                        overall=retry_grade.overall,
                        passed=retry_grade.passed,
                        issues=retry_grade.issues,
                    )
                    logger.info(
                        "Retry improved score: %.2f → %.2f",
                        grade.overall, retry_grade.overall,
                    )

        return AnswerResult(
            question=question,
            answer=answer_text,
            citations=citations,
            model=self.model,
            latency_ms=round(latency_ms, 1),
            chunks_used=len(chunks),
            grade=grade_result,
        )

    # ------------------------------------------------------------------

    def _build_context(self, chunks: List[RetrievedChunk]) -> str:
        return "\n\n".join(
            f"[{i}] {chunk.citation()}\n{chunk.text}"
            for i, chunk in enumerate(chunks, start=1)
        )

    def _build_payload(self, user_prompt: str, provider: str = "") -> Dict:
        provider = provider or self._provider
        payload: Dict = {
            "model":       GROQ_MODEL if provider == "groq" else self.model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user",   "content": user_prompt},
            ],
            "max_tokens":  self.max_tokens,
            "temperature": self.temperature,
            "top_p":       self.top_p,
            "stream":      True,
        }
        # thinking=True adds chain-of-thought latency — disabled for speed
        return payload

    def _call_api(self, user_prompt: str) -> str:
        """Try primary provider; fall back to Groq if NVIDIA fails."""
        payload = self._build_payload(user_prompt)
        delay   = 1.0
        last_error: Optional[Exception] = None

        for attempt in range(1, self.max_retries + 1):
            try:
                response = requests.post(
                    self._url,
                    headers=self._headers,
                    json=payload,
                    timeout=120,
                )
                response.raise_for_status()
                result = self._parse_stream(response)
                # Add delay after successful request to avoid rate limits
                time.sleep(0.5)
                return result
            except requests.exceptions.HTTPError as exc:
                # Handle rate limit errors (429) with longer backoff
                if exc.response.status_code == 429:
                    backoff = delay * 3  # Longer wait for rate limits
                    logger.warning(
                        "%s rate limit hit (attempt %d/%d) — waiting %.1fs",
                        self._provider, attempt, self.max_retries, backoff,
                    )
                    if attempt < self.max_retries:
                        time.sleep(backoff)
                        delay *= 2
                    last_error = exc
                else:
                    raise
            except Exception as exc:
                last_error = exc
                status = getattr(getattr(exc, "response", None), "status_code", None)
                wait = delay
                if status == 429:
                    retry_after = getattr(getattr(exc, "response", None), "headers", {}).get("Retry-After")
                    wait = float(retry_after) if retry_after else 15.0
                    logger.warning("%s 429 rate limit — waiting %.0fs", self._provider, wait)
                else:
                    logger.warning(
                        "%s attempt %d/%d failed: %s",
                        self._provider, attempt, self.max_retries, exc,
                    )
                if attempt < self.max_retries:
                    time.sleep(wait)
                    delay *= 2

        # Runtime fallback to Groq if NVIDIA was primary and Groq is available
        if self._provider == "nvidia" and self._groq_headers:
            logger.warning("NVIDIA failed — falling back to Groq for this query")
            groq_payload = self._build_payload(user_prompt, provider="groq")
            try:
                response = requests.post(
                    GROQ_URL,
                    headers=self._groq_headers,
                    json=groq_payload,
                    timeout=60,
                )
                response.raise_for_status()
                return self._parse_stream(response)
            except Exception as exc:
                raise RuntimeError(
                    f"Both NVIDIA and Groq failed. Last error: {exc}"
                ) from exc

        raise RuntimeError(
            f"{self._provider} API failed after {self.max_retries} attempts: {last_error}"
        ) from last_error

    def _parse_stream(self, response: requests.Response) -> str:
        """Consume SSE stream and concatenate content tokens."""
        parts: List[str] = []
        for raw_line in response.iter_lines():
            if not raw_line:
                continue
            line = raw_line.decode("utf-8") if isinstance(raw_line, bytes) else raw_line
            if not line.startswith("data:"):
                continue
            data = line[len("data:"):].strip()
            if data == "[DONE]":
                break
            try:
                chunk  = json.loads(data)
                delta  = chunk["choices"][0].get("delta", {})
                content = delta.get("content") or ""
                if content:
                    parts.append(content)
            except (json.JSONDecodeError, KeyError, IndexError):
                continue
        return "".join(parts).strip()

    @staticmethod
    def _extract_citations(answer: str, chunks: List[RetrievedChunk]) -> List[Dict]:
        cited = {int(m) for m in re.findall(r"\[(\d+)\]", answer)}
        result = []
        for idx in sorted(cited):
            if 1 <= idx <= len(chunks):
                c = chunks[idx - 1]
                result.append({
                    "ref":           idx,
                    "citation":      c.citation(),
                    "section_title": c.section_title,
                    "chapter_id":    c.chapter_id,
                    "page_start":    c.page_start,
                    "page_end":      c.page_end,
                })
        return result
