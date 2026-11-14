"""Turn a message into claims about known slots.

The prompt is given the org's subjects, people and fixed attribute vocabulary,
so every message lands on the same slot names. Without that, each message
invents its own keys and the graph can never match two statements about the
same fact.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from . import rules
from .llm import chat_json

SYSTEM = """You extract firm factual claims from workplace messages into a fixed schema.

Return JSON: {"claims": [{"subject": "<subject id>", "attribute": "<ATTRIBUTE>", "value": "<value>"}]}

Rules:
- Only include statements the author presents as true or decided. Skip questions, proposals,
  requests, guesses, and plans that are still up for discussion ("Proposing Friday", "Can we...?",
  "I don't think we can..." are NOT claims).
- A reply that confirms or restates a fact IS a claim ("Friday now" = the freeze is Friday).
- Extract only what the Text itself asserts. The "In reply to" message is context for resolving
  words like "it", "that" or "Done"; never copy claims out of it. "Makes sense" or "Will do" asserts nothing.
- Pick the attribute by its description, not by which date is mentioned nearby.
- Only use subject ids and attributes from the catalog. If a statement fits none, leave it out.
- Write values exactly in the attribute's format. Resolve relative dates ("Monday", "today",
  "Friday") against the message timestamp. Use person ids for people.
- If the author reports what they told someone else ("Told Jordan X"), X is still a claim by the author.
- If nothing qualifies, return {"claims": []}."""


def catalog(ds: dict[str, Any]) -> str:
    lines = ["SUBJECTS:"]
    for s in ds["subjects"]:
        lines.append(f"- {s['id']} ({s['type']}): {s['name']}")
    lines.append("PEOPLE:")
    for p in ds["people"]:
        lines.append(f"- {p['id']}: {p['name']}, {p['role']}")
    lines.append("ATTRIBUTES (attribute: subject types -> value format; meaning):")
    for name, spec in ds["attributes"].items():
        lines.append(f"- {name}: {', '.join(spec['on'])} -> {spec['format']}; {spec.get('desc', '')}")
    return "\n".join(lines)


def _when(ts: str) -> str:
    d = rules.parse_ts(ts)
    days = ", ".join(f"{(d + timedelta(days=i)).strftime('%A')} = {(d + timedelta(days=i)).date()}"
                     for i in range(1, 8))
    return f"{d.strftime('%A %Y-%m-%d %H:%M')} UTC (upcoming: {days})"


def _who(ds: dict[str, Any], pid: str) -> str:
    for p in ds["people"]:
        if p["id"] == pid:
            return f"{p['name']} ({pid})"
    return ds.get("external", {}).get(pid, pid)


def _where(m: dict[str, Any], ds: dict[str, Any]) -> str:
    if m.get("channel"):
        return f"Slack #{m['channel']}"
    to = ", ".join(_who(ds, x) for x in m.get("to", []) + m.get("cc", []))
    return f"{m.get('kind', 'message')} to {to}"


def clean(raw: dict[str, Any], ds: dict[str, Any]) -> list[dict[str, str]]:
    subjects = {s["id"]: s["type"] for s in ds["subjects"]}
    people = {p["id"] for p in ds["people"]}
    names = {p["name"].split()[0].lower(): p["id"] for p in ds["people"]}
    out, seen = [], set()
    for cl in raw.get("claims", []) if isinstance(raw, dict) else []:
        if not isinstance(cl, dict):
            continue
        subj, attr, val = str(cl.get("subject", "")).strip(), str(cl.get("attribute", "")).strip().upper(), \
            str(cl.get("value", "")).strip()
        spec = ds["attributes"].get(attr)
        if subj not in subjects or spec is None or not val:
            continue
        if subjects[subj] not in spec["on"]:
            continue
        if attr == "OWNED_BY" and val not in people:
            val = names.get(val.split(":")[-1].split()[0].lower(), val)
            if val not in people:
                continue
        key = (subj, attr, rules.norm_value(val))
        if key in seen:
            continue
        seen.add(key)
        out.append({"subject": subj, "attribute": attr, "value": val})
    return out


def extract_message(m: dict[str, Any], ds: dict[str, Any], parent: dict[str, Any] | None = None) -> list[dict]:
    parts = [catalog(ds), "", "MESSAGE:", f"From: {_who(ds, m['author'])}", f"Where: {_where(m, ds)}",
             f"When: {_when(m['ts'])}"]
    if m.get("subject_line"):
        parts.append(f"Subject: {m['subject_line']}")
    if parent is not None:
        parts.append(f"In reply to {_who(ds, parent['author'])}: \"{parent['text']}\"")
    parts.append(f"Text: \"{m['text']}\"")
    reply = chat_json(SYSTEM, "\n".join(parts), tag="extract", max_tokens=1500)
    return clean(reply, ds)


def extract_draft(text: str, author: str, ts: str, ds: dict[str, Any]) -> list[dict]:
    m = {"author": author, "ts": ts, "text": text, "kind": "draft", "to": [], "cc": []}
    parts = [catalog(ds), "", "DRAFT MESSAGE (not sent yet):", f"From: {_who(ds, author)}",
             f"When: {_when(ts)}", f"Text: \"{m['text']}\""]
    reply = chat_json(SYSTEM, "\n".join(parts), tag="check", max_tokens=1500)
    return clean(reply, ds)
