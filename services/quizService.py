"""
quizService.py - Generates quiz questions using Gemini API (gemini-2.5-flash).
"""
import json, os, re
from typing import List
import requests
from dotenv import load_dotenv

load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_API_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    "gemini-2.5-flash:generateContent?key=" + GEMINI_API_KEY
)

def generate_quiz(text: str, count: int = 10, difficulty: str = "mixed") -> List[dict]:
    count = max(1, min(50, count))
    diff_map = {
        "easy":   "Focus on basic recall and definitions.",
        "medium": "Include application and comprehension questions.",
        "hard":   "Include analysis and evaluation questions with challenging distractors.",
        "mixed":  "Mix easy, medium, and hard questions evenly.",
    }
    diff_instruction = diff_map.get(difficulty, diff_map["mixed"])
    prompt = (
        f"Generate exactly {count} multiple-choice questions from the text below.\n"
        f"{diff_instruction}\n\n"
        "Return ONLY a valid JSON array, no markdown fences, no explanation:\n"
        '[{"q":"Question?","options":["A","B","C","D"],"answer":0}]\n\n'
        "Rules: each question has exactly 4 options; answer is 0-based index of correct option.\n\n"
        f"Text:\n{text[:8000]}\n\nJSON:"
    )
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.5},
    }
    response = requests.post(GEMINI_API_URL, json=payload, timeout=60)
    response.raise_for_status()
    raw = response.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)
    return json.loads(raw)
