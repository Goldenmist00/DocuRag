"""
generator.py
============
Phase 5 — Answer Generation

Provider priority:
  1. Gemini API  (gemini-2.0-flash)            — if GEMINI_API_KEY is set
  2. Groq API    (llama-3.3-70b-versatile)      — if GROQ_API_KEY is set
  3. NVIDIA API  (meta/llama-3.3-70b-instruct)  — if NVIDIA_API_KEY is set
  4. Raises ValueError if no key is available

If the primary provider fails at runtime, automatically falls back to the
next available provider for that query.
All providers use requests + SSE streaming.
"""

import json
import logging
import os
import random
import re
import threading
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import requests

from src.config.llm_semaphore import LLM_SEMAPHORE
from src.retriever import RetrievedChunk

logger = logging.getLogger(__name__)

_LLM_LAST_CALL = threading.local()

GEMINI_URL   = "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
NVIDIA_URL   = "https://integrate.api.nvidia.com/v1/chat/completions"
GROQ_URL     = "https://api.groq.com/openai/v1/chat/completions"

GEMINI_MODEL = "gemini-2.0-flash"
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
    """Multi-provider LLM generator (Gemini → Groq → NVIDIA with runtime fallback).

    Uses requests + SSE streaming for all providers.
    """

    def __init__(
        self,
        model: Optional[str] = None,
        temperature: float = 0.3,
        max_tokens: int = 1024,
        top_p: float = 0.9,
        api_key: Optional[str] = None,
        max_retries: int = 5,
    ):
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.top_p = top_p
        self.max_retries = max_retries

        gemini_key = os.getenv("GEMINI_API_KEY", "").strip()
        nvidia_key = (api_key or os.getenv("NVIDIA_API_KEY", "")).strip()
        groq_key   = os.getenv("GROQ_API_KEY", "").strip()

        self._gemini_valid = bool(gemini_key)
        self._nvidia_valid = bool(nvidia_key and nvidia_key != "your_nvidia_api_key_here")
        self._groq_valid   = bool(groq_key)

        if not self._gemini_valid and not self._nvidia_valid and not self._groq_valid:
            raise ValueError(
                "No LLM API key found. Set GEMINI_API_KEY, NVIDIA_API_KEY, or GROQ_API_KEY in .env"
            )

        if self._gemini_valid:
            self._provider = "gemini"
            self._url      = GEMINI_URL
            self.model     = model or GEMINI_MODEL
            self._headers  = {
                "Authorization": f"Bearer {gemini_key}",
                "Accept":        "text/event-stream",
                "Content-Type":  "application/json",
            }
        elif self._groq_valid:
            self._provider = "groq"
            self._url      = GROQ_URL
            self.model     = model or GROQ_MODEL
            self._headers  = {
                "Authorization": f"Bearer {groq_key}",
                "Accept":        "text/event-stream",
                "Content-Type":  "application/json",
            }
        else:
            self._provider = "nvidia"
            self._url      = NVIDIA_URL
            self.model     = model or NVIDIA_MODEL
            self._headers  = {
                "Authorization": f"Bearer {nvidia_key}",
                "Accept":        "text/event-stream",
                "Content-Type":  "application/json",
            }

        self._fallback_chain: List[Dict] = []
        if self._provider != "groq" and self._groq_valid:
            self._fallback_chain.append({
                "name": "groq",
                "url": GROQ_URL,
                "model": GROQ_MODEL,
                "headers": {
                    "Authorization": f"Bearer {groq_key}",
                    "Accept":        "text/event-stream",
                    "Content-Type":  "application/json",
                },
            })
        if self._provider != "nvidia" and self._nvidia_valid:
            self._fallback_chain.append({
                "name": "nvidia",
                "url": NVIDIA_URL,
                "model": NVIDIA_MODEL,
                "headers": {
                    "Authorization": f"Bearer {nvidia_key}",
                    "Accept":        "text/event-stream",
                    "Content-Type":  "application/json",
                },
            })

        logger.info(
            "Generator ready | provider=%s | model=%s | fallbacks=%s | max_tokens=%d",
            self._provider, self.model,
            [f["name"] for f in self._fallback_chain],
            self.max_tokens,
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

    def _build_payload(self, user_prompt: str, model_override: Optional[str] = None) -> Dict:
        """Build the request payload for a streaming chat completion."""
        payload: Dict = {
            "model":       model_override or self.model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user",   "content": user_prompt},
            ],
            "max_tokens":  self.max_tokens,
            "temperature": self.temperature,
            "top_p":       self.top_p,
            "stream":      True,
        }
        return payload

    def _try_provider(
        self,
        url: str,
        headers: Dict,
        payload: Dict,
        provider_name: str,
    ) -> Optional[str]:
        """Attempt one provider with retries.  Returns text or None."""
        delay = 1.5
        for attempt in range(1, self.max_retries + 1):
            LLM_SEMAPHORE.acquire()
            try:
                response = requests.post(url, headers=headers, json=payload, timeout=120)
                response.raise_for_status()
                return self._parse_stream(response)
            except requests.exceptions.HTTPError as exc:
                if exc.response.status_code == 429:
                    jitter = random.uniform(0, 1.5)
                    backoff = delay * 2 + jitter
                    logger.warning(
                        "%s rate limit (attempt %d/%d) — waiting %.1fs",
                        provider_name, attempt, self.max_retries, backoff,
                    )
                    if attempt < self.max_retries:
                        time.sleep(backoff)
                        delay *= 2
                else:
                    logger.warning("%s HTTP %s", provider_name, exc.response.status_code)
                    break
            except Exception as exc:
                wait = delay + random.uniform(0, 1.0)
                logger.warning(
                    "%s attempt %d/%d failed: %s",
                    provider_name, attempt, self.max_retries, exc,
                )
                if attempt < self.max_retries:
                    time.sleep(wait)
                    delay *= 2
            finally:
                LLM_SEMAPHORE.release()
        return None

    def _call_api(self, user_prompt: str) -> str:
        """Call the primary LLM provider, falling back through the chain.

        Args:
            user_prompt: Fully formatted prompt string.

        Returns:
            Generated answer text.

        Raises:
            RuntimeError: If all providers fail after retries.
        """
        payload = self._build_payload(user_prompt)
        result = self._try_provider(self._url, self._headers, payload, self._provider)
        if result is not None:
            return result

        for fb in self._fallback_chain:
            logger.warning(
                "%s exhausted — falling back to %s", self._provider, fb["name"],
            )
            fb_payload = self._build_payload(user_prompt, model_override=fb["model"])
            result = self._try_provider(fb["url"], fb["headers"], fb_payload, fb["name"])
            if result is not None:
                return result

        raise RuntimeError(
            f"All LLM providers failed after retries (primary={self._provider})"
        )

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
