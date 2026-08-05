"""
brain.py — Maps transcribed speech to a robot command.

Languages: English + formal Arabic (MSA) only.
Strategy:
  1. Fast keyword scan — instant
  2. Ollama Phi-3 mini — only when "think" is in the sentence
"""

import re
import requests

OLLAMA_URL = "http://localhost:11434/api/generate"
MODEL      = "phi3:mini"

VALID_COMMANDS = ["FORWARD", "BACKWARD", "LEFT", "RIGHT", "STOP", "DANCE"]

# English + formal Arabic (MSA) only — no Lebanese phonetics
_KEYWORDS = {
    "DANCE":    ["dance", "ارقص", "تمايل", "اشتغل"],
    "FORWARD":  ["forward", "ahead", "تقدم", "للأمام", "أمام", "الأمام", "تحرك", "قدام"],
    "BACKWARD": ["backward", "back", "reverse", "ارجع", "تراجع", "للخلف", "وراء"],
    "LEFT":     ["left", "يسار", "لليسار", "شمال"],
    "RIGHT":    ["right", "يمين", "لليمين"],
    "STOP":     ["stop", "halt", "freeze", "توقف", "قف", "وقف"],
}

_PROMPT_TEMPLATE = """\
You control a robot called Kimo. Reply with EXACTLY ONE word from: FORWARD, BACKWARD, LEFT, RIGHT, STOP, DANCE

Movement: "head that way" → FORWARD | "come here" → FORWARD | "go back a little" → BACKWARD
Turning: "spin to the left" → LEFT | "rotate right" → RIGHT
Emotion/fun: "you are happy" → DANCE | "celebrate" → DANCE | "you are excited" → DANCE | "party" → DANCE
Calm/idle: "you are sad" → STOP | "relax" → STOP | "chill" → STOP
If truly unclear → STOP

Voice command: {text}
Command:"""

_LLM_TRIGGER = "think"

_ARABIC_DIACRITICS = re.compile(
    r'[ؐ-ًؚ-ٰٟۖ-ۜ۟-۪ۤۧۨ-ۭ]'
)

def _normalize(text: str) -> str:
    """Lowercase + strip Arabic diacritics."""
    return _ARABIC_DIACRITICS.sub('', text.lower())


def _llm_match(text: str) -> str:
    payload = {
        "model": MODEL,
        "prompt": _PROMPT_TEMPLATE.format(text=text),
        "stream": False,
        "options": {"temperature": 0, "num_predict": 10},
    }
    try:
        print("[Brain] Asking Ollama...")
        response = requests.post(OLLAMA_URL, json=payload, timeout=180)
        response.raise_for_status()
        raw = response.json().get("response", "").strip().upper()
        for cmd in VALID_COMMANDS:
            if cmd in raw:
                return cmd
    except Exception as e:
        print(f"[Brain] Ollama error: {e}")
    return "STOP"


def _keyword_match(text: str) -> str | None:
    normalized = _normalize(text)
    for command, keywords in _KEYWORDS.items():
        for kw in keywords:
            if kw in normalized:
                return command
    return None


# Red-follow triggers — "follow red", "you are a bull", Arabic equivalents
_RED_TRIGGERS = ["follow red", "you are a bull", "تتبع الأحمر", "أنت ثور", "اتبع الأحمر"]

def get_follow_color(text: str) -> str | None:
    """Returns 'FOLLOW:red' if any red-follow trigger is detected, else None."""
    normalized = _normalize(text)
    for trigger in _RED_TRIGGERS:
        if trigger in normalized:
            return "FOLLOW:red"
    return None


def get_command(text: str) -> str:
    if not text.strip():
        return "STOP"

    follow = get_follow_color(text)
    if follow:
        return follow

    match = _keyword_match(text)
    if match:
        return match

    if _LLM_TRIGGER in _normalize(text):
        words = [w for w in text.split() if w.strip(".,!?")]
        if len(words) >= 3:
            return _llm_match(text)

    return "NOOP"
