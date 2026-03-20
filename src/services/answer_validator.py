"""
answer_validator.py
===================
Post-generation answer quality validation.

Grades LLM-generated answers on three dimensions:
  1. Faithfulness — is every claim grounded in the provided context?
  2. Completeness — does the answer address all parts of the question?
  3. Citation accuracy — do [1], [2] markers match supporting chunks?

Uses the same LLM provider as the Generator (NVIDIA → Groq fallback)
with a structured JSON grading prompt. If the answer fails validation,
returns corrective feedback for a retry attempt.
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

_NVIDIA_URL = "https://integrate.api.nvidia.com/v1/chat/completions"
_GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
_NVIDIA_MODEL = "meta/llama-3.3-70b-instruct"
_GROQ_MODEL = "llama-3.3-70b-versatile"

_PASS_THRESHOLD = 0.6
_WEIGHTS = {"faithfulness": 0.50, "completeness": 0.30, "citation_accuracy": 0.20}

GRADING_PROMPT = """You are a strict answer-quality judge for a RAG (Retrieval-Augmented Generation) system.

Given a QUESTION, numbered CONTEXT passages, and a generated ANSWER, evaluate the answer on these criteria:

1. FAITHFULNESS (0-10): Is every factual claim in the answer directly supported by the context passages?
   - 10 = every claim is traceable to a context passage
   - 5 = some claims are supported, some are not
   - 0 = the answer fabricates information not in context

2. COMPLETENESS (0-10): Does the answer address all aspects and sub-questions of the user's question?
   - 10 = all parts of the question are thoroughly addressed
   - 5 = main point answered but some aspects missed
   - 0 = the answer misses the core question entirely

3. CITATION_ACCURACY (0-10): Do the citation markers [1], [2], etc. correctly reference the passage that supports each claim?
   - 10 = all citations are accurate and verifiable
   - 5 = some citations are correct, some are mismatched
   - 0 = citations are wrong or fabricated

Return ONLY valid JSON (no markdown, no explanation outside JSON):
{{"faithfulness": <0-10>, "completeness": <0-10>, "citation_accuracy": <0-10>, "issues": ["issue1", "issue2"]}}"""

_USER_TEMPLATE = """QUESTION: {question}

CONTEXT:
{context}

ANSWER TO EVALUATE:
{answer}

Return JSON evaluation:"""


@dataclass
class AnswerGrade:
    """Quality assessment of a generated answer."""

    faithfulness: float = 0.0
    completeness: float = 0.0
    citation_accuracy: float = 0.0
    overall: float = 0.0
    passed: bool = False
    issues: List[str] = field(default_factory=list)
    feedback: str = ""
    grading_latency_ms: float = 0.0


class AnswerValidator:
    """
    Validates generated answers using an LLM-as-judge approach.

    Uses the same provider priority as the Generator: NVIDIA first,
    Groq as fallback. Produces structured quality grades.
    """

    def __init__(self) -> None:
        nvidia_key = os.getenv("NVIDIA_API_KEY", "").strip()
        groq_key = os.getenv("GROQ_API_KEY", "").strip()

        if nvidia_key and nvidia_key != "your_nvidia_api_key_here":
            self._url = _NVIDIA_URL
            self._model = _NVIDIA_MODEL
            self._headers = {
                "Authorization": f"Bearer {nvidia_key}",
                "Content-Type": "application/json",
            }
        elif groq_key:
            self._url = _GROQ_URL
            self._model = _GROQ_MODEL
            self._headers = {
                "Authorization": f"Bearer {groq_key}",
                "Content-Type": "application/json",
            }
        else:
            self._url = ""
            self._model = ""
            self._headers = {}
            logger.warning("No LLM API key for answer validation — grading disabled")

    @property
    def available(self) -> bool:
        """Whether the validator has a usable LLM provider."""
        return bool(self._url)

    def grade(
        self,
        question: str,
        answer: str,
        chunks: List[RetrievedChunk],
    ) -> AnswerGrade:
        """
        Grade a generated answer on faithfulness, completeness, and citation accuracy.

        Args:
            question: The user's original question.
            answer:   The LLM-generated answer text.
            chunks:   The context chunks that were provided to the generator.

        Returns:
            AnswerGrade with scores, pass/fail, and corrective feedback.
        """
        if not self.available:
            return AnswerGrade(
                faithfulness=1.0,
                completeness=1.0,
                citation_accuracy=1.0,
                overall=1.0,
                passed=True,
                feedback="Grading unavailable — no LLM API key",
            )

        if not chunks:
            return AnswerGrade(passed=True, feedback="No context — skipping grade")

        context = "\n\n".join(
            f"[{i}] {c.citation()}\n{c.text}"
            for i, c in enumerate(chunks, start=1)
        )

        prompt = _USER_TEMPLATE.format(
            question=question,
            context=context,
            answer=answer,
        )

        t0 = time.time()
        raw = self._call_llm(prompt)
        latency = (time.time() - t0) * 1000

        grade = self._parse_grade(raw)
        grade.grading_latency_ms = round(latency, 1)

        if not grade.passed and grade.issues:
            grade.feedback = (
                "The answer has quality issues: "
                + "; ".join(grade.issues)
                + ". Please revise the answer to address these problems, "
                "staying strictly grounded in the provided context passages."
            )

        logger.info(
            "Answer grade: faith=%.1f complete=%.1f cite=%.1f overall=%.2f passed=%s (%.0fms)",
            grade.faithfulness, grade.completeness, grade.citation_accuracy,
            grade.overall, grade.passed, grade.grading_latency_ms,
        )
        return grade

    def _call_llm(self, user_prompt: str) -> str:
        """
        Call the LLM for grading. Non-streaming, single attempt.

        Args:
            user_prompt: The formatted grading prompt.

        Returns:
            Raw LLM response text.
        """
        payload = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": GRADING_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            "max_tokens": 300,
            "temperature": 0.1,
            "stream": False,
        }

        try:
            resp = requests.post(
                self._url,
                headers=self._headers,
                json=payload,
                timeout=30,
            )
            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"].strip()
        except Exception as exc:
            logger.warning("Grading LLM call failed: %s", exc)
            return ""

    def _parse_grade(self, raw: str) -> AnswerGrade:
        """
        Parse the LLM's JSON response into an AnswerGrade.

        Handles common LLM quirks: markdown fences, trailing text.

        Args:
            raw: Raw LLM output string.

        Returns:
            Parsed AnswerGrade (defaults to passing if parsing fails).
        """
        if not raw:
            return AnswerGrade(
                faithfulness=1.0,
                completeness=1.0,
                citation_accuracy=1.0,
                overall=1.0,
                passed=True,
                feedback="Grading LLM returned empty — assuming pass",
            )

        cleaned = raw.strip()
        if cleaned.startswith("```"):
            cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
            cleaned = re.sub(r"\s*```$", "", cleaned)

        json_match = re.search(r"\{[^{}]*\}", cleaned, re.DOTALL)
        if json_match:
            cleaned = json_match.group(0)

        try:
            data = json.loads(cleaned)
        except json.JSONDecodeError:
            logger.warning("Could not parse grading JSON: %.100s", raw)
            return AnswerGrade(
                faithfulness=1.0,
                completeness=1.0,
                citation_accuracy=1.0,
                overall=1.0,
                passed=True,
                feedback="Grading parse failed — assuming pass",
            )

        faith = min(1.0, max(0.0, data.get("faithfulness", 10) / 10.0))
        complete = min(1.0, max(0.0, data.get("completeness", 10) / 10.0))
        cite = min(1.0, max(0.0, data.get("citation_accuracy", 10) / 10.0))

        overall = (
            faith * _WEIGHTS["faithfulness"]
            + complete * _WEIGHTS["completeness"]
            + cite * _WEIGHTS["citation_accuracy"]
        )

        issues = data.get("issues", [])
        if not isinstance(issues, list):
            issues = [str(issues)]

        return AnswerGrade(
            faithfulness=round(faith, 2),
            completeness=round(complete, 2),
            citation_accuracy=round(cite, 2),
            overall=round(overall, 2),
            passed=overall >= _PASS_THRESHOLD,
            issues=issues,
        )
