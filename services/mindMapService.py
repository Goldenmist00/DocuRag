"""
mindMapService.py
=================
Generates mind map data using Gemini API (gemini-2.5-flash).
"""

import json
import os
import re
import requests
from dotenv import load_dotenv

load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_API_URL = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GEMINI_API_KEY}"


def generate_mind_map(text: str) -> dict:
    """
    Generate a mind map structure from the provided text.

    Args:
        text: Source text to map.

    Returns:
        Dict with keys: root (str), branches (list of {label, children}).
    """
    prompt = f"""Analyse the following text and create a mind map structure.
Return ONLY valid JSON with this exact structure (no markdown, no explanation):
{{
  "root": "Main Topic",
  "branches": [
    {{
      "label": "Branch 1",
      "children": ["Child 1", "Child 2", "Child 3"]
    }}
  ]
}}

Rules:
- root: the single central topic (3-5 words max)
- branches: 4-6 main branches
- each branch has 2-4 children (short phrases, 2-4 words each)
- keep all labels concise

Text:
{text[:6000]}

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

    # Strip markdown code fences if present
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)

    result = json.loads(raw)
    return result
