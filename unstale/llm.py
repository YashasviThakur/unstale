"""Minimal Groq client (OpenAI-compatible) with a disk cache and token accounting.

The cache makes runs reproducible and keeps the eval inside free-tier limits:
the same prompt is never paid for twice.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field

import httpx

from .config import CACHE, Settings

URL = "https://api.groq.com/openai/v1/chat/completions"


@dataclass
class Usage:
    calls: int = 0
    cached: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    by_tag: dict[str, dict[str, int]] = field(default_factory=dict)

    def add(self, tag: str, prompt: int, completion: int, cached: bool) -> None:
        self.calls += 1
        self.cached += int(cached)
        self.prompt_tokens += prompt
        self.completion_tokens += completion
        t = self.by_tag.setdefault(tag, {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0})
        t["calls"] += 1
        t["prompt_tokens"] += prompt
        t["completion_tokens"] += completion


USAGE = Usage()


class LLMError(RuntimeError):
    pass


def chat_json(system: str, user: str, *, tag: str, max_tokens: int = 1200, model: str | None = None,
              settings: Settings | None = None) -> dict:
    """Return the model's JSON object reply. Token counts are recorded even for cache hits."""
    s = settings or Settings.load()
    model = model or s.groq_model
    key = hashlib.sha256(json.dumps([model, system, user, max_tokens]).encode()).hexdigest()
    path = CACHE / "llm" / f"{key}.json"
    if path.exists():
        rec = json.loads(path.read_text(encoding="utf-8"))
        USAGE.add(tag, rec["prompt_tokens"], rec["completion_tokens"], cached=True)
        return rec["reply"]
    if not s.groq_key:
        raise LLMError("GROQ_API_KEY is not set")
    body = {
        "model": model,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "response_format": {"type": "json_object"},
        "temperature": 0,
        "max_tokens": max_tokens,
    }
    if model.startswith("openai/gpt-oss"):
        body["reasoning_effort"] = "low"
    delay = 2.0
    for attempt in range(6):
        r = httpx.post(URL, json=body, headers={"Authorization": f"Bearer {s.groq_key}"}, timeout=90)
        if r.status_code == 429 or r.status_code >= 500:
            wait = float(r.headers.get("retry-after", delay))
            time.sleep(min(wait, 30))
            delay *= 2
            continue
        if r.status_code != 200:
            raise LLMError(f"Groq {r.status_code}: {r.text[:300]}")
        data = r.json()
        text = data["choices"][0]["message"].get("content") or ""
        try:
            reply = json.loads(text)
        except json.JSONDecodeError as e:
            if attempt < 2:
                continue
            raise LLMError(f"model did not return JSON: {text[:200]}") from e
        usage = data.get("usage", {})
        rec = {"reply": reply, "prompt_tokens": usage.get("prompt_tokens", 0),
               "completion_tokens": usage.get("completion_tokens", 0), "model": model}
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(rec), encoding="utf-8")
        USAGE.add(tag, rec["prompt_tokens"], rec["completion_tokens"], cached=False)
        return reply
    raise LLMError("Groq kept rate-limiting; try again in a minute")
