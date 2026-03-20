"""
summaryService.py
=================
Generates summaries using Gemini API (gemini-2.5-flash).
"""

import os
import requests
from dotenv import load_dotenv

load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_API_URL = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GEMINI_API_KEY}"


def generate_summary(text: str, level: str = "medium") -> str:
    """
    Generate a summary of the provided text.

    Args:
        text:  Source text to summarise.
        level: 'short' | 'medium' | 'detailed'

    Returns:
        Summary string.
    """
    instructions = {
        "short":    "Write a concise 3-5 sentence summary highlighting only the most critical points.",
        "medium":   "Write a clear, well-structured summary of 2-3 paragraphs covering the main concepts.",
        "detailed": "Write a comprehensive, detailed summary with sections covering all major topics, key terms, and important details.",
    }
    instruction = instructions.get(level, instructions["medium"])

    prompt = f"""{instruction}

Text to summarise:
{text}

Summary:"""

    payload = {
        "contents": [{
            "parts": [{"text": prompt}]
        }]
    }

    response = requests.post(GEMINI_API_URL, json=payload, timeout=60)
    response.raise_for_status()
    
    data = response.json()
    return data["candidates"][0]["content"]["parts"][0]["text"].strip()
