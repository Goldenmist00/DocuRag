"""
flashcardService.py
===================
Generates flashcards using Gemini API (gemini-2.5-flash).
"""

import json
import os
import re
from typing import List
import requests
from dotenv import load_dotenv

load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_API_URL = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GEMINI_API_KEY}"


def generate_flashcards(text: str, count: int = 10) -> List[dict]:
    """
    Generate flashcards from the provided text.

    Args:
        text:  Source text.
        count: Number of flashcards to generate.

    Returns:
        List of dicts with keys: term, definition, question, answer.
    """
    count = max(1, min(50, count))

    prompt = f"""Generate exactly {count} flashcards from the text below.
Return ONLY valid JSON array (no markdown, no explanation):
[
  {{
    "term": "Key term or concept",
    "definition": "Clear, concise definition",
    "question": "A question that tests understanding of this concept?",
    "answer": "The answer to the question above."
  }}
]

Rules:
- Focus on the most important concepts, terms, and facts
- Definitions should be clear and concise (1-2 sentences)
- Questions should test understanding, not just recall
- Base everything strictly on the provided text

Text:
{text[:8000]}

JSON:"""

    payload = {
        "contents": [{
            "parts": [{"text": prompt}]
        }]
    }

    response = requests.post(GEMINI_API_URL, json=payload, timeout=60)
    response.raise_for_status()
    
    data = response.json()
    raw = data["candidates"][0]["content"]["parts"][0]["text"].strip()

    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)

    cards = json.loads(raw)
    return cards
