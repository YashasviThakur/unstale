"""Close the gap: who to tell, where, and what happens to the corrections if you do.

Detecting who is out of date is half of it. Given one changed fact this module reads the same graph and read
model the briefs use and answers the next question: which channels reach the people who are still on the old
value, who needs an @mention or a DM because they rarely read that channel, and what the corrections look like
afterwards. "Afterwards" is computed with the production function (``stale_probability``) over the person's real
exposures plus the exposures the plan would create, so nothing is written to the graph: it is a what-if, and
safe on a public demo.
"""

from __future__ import annotations

from typing import Any

from . import rules
from .exposure import Exposure, ReadModel, stale_probability

MENTION_BELOW = 0.7      # members who read a channel less than this get an @mention, which counts as seeing it


def parse_sim(raw: Any) -> list[dict]:
    """Simulated exposures from the client: a list of {person, slot, value, strength, channel, ts}."""
    if not isinstance(raw, list):
        return []
    keep = []
    for it in raw[:60]:
        if (isinstance(it, dict) and {"person", "slot", "value", "strength", "ts"} <= it.keys()
                and it["strength"] in (rules.STRONG, rules.WEAK)):
            keep.append({k: it.get(k) for k in ("person", "slot", "value", "strength", "channel", "ts")})
    return keep


def apply_sim(exps: dict[str, list[Exposure]], person: str, sim: list[dict], as_of: str) -> dict[str, list[Exposure]]:
    """Add the exposures a simulated plan creates, for anyone it reaches by ``as_of``."""
    mine = [s for s in sim if s["person"] == person and rules.parse_ts(s["ts"]) <= rules.parse_ts(as_of)]
    if not mine:
        return exps
    out = {k: list(v) for k, v in exps.items()}
    for s in mine:
        out.setdefault(s["slot"], []).append(
            Exposure(s["slot"], s["value"], s["ts"], "sim", s["ts"], s["strength"], s.get("channel")))
    return out


def plan(stale: list[str], channels: dict[str, list[str]], agents: set[str], model: ReadModel) -> list[dict]:
    """Greedy cover: the channel that reaches the most still-uncovered stale people (weighted by how much they read it),
    then a DM for whoever is left. An agent no channel reaches gets the correction block instead."""
    uncovered, steps = list(stale), []
    while uncovered:
        best, gain = None, 0.0
        for ch, members in sorted(channels.items()):
            g = sum(model.rate(p, ch) for p in uncovered if p in members)
            if g > gain + 1e-9:
                best, gain = ch, g
        if best is None:
            break
        reach = [p for p in uncovered if p in channels[best]]
        steps.append({"kind": "post", "channel": best, "reach": reach,
                      "mention": [p for p in reach if model.rate(p, best) < MENTION_BELOW],
                      "rates": {p: round(model.rate(p, best), 2) for p in reach}})
        uncovered = [p for p in uncovered if p not in reach]
    for p in uncovered:
        steps.append({"kind": "agent" if p in agents else "dm", "person": p})
    return steps


def effects(steps: list[dict], slot: str, value: str, ts: str) -> list[dict]:
    """The exposures a plan would create, in the shape the client sends back as ``sim``."""
    out = []
    for st in steps:
        if st["kind"] == "post":
            for p in st["reach"]:
                strong = p in st["mention"]
                out.append({"person": p, "slot": slot, "value": value, "ts": ts,
                            "strength": rules.STRONG if strong else rules.WEAK, "channel": st["channel"]})
        else:
            out.append({"person": st["person"], "slot": slot, "value": value, "ts": ts,
                        "strength": rules.STRONG, "channel": None})
    return out
