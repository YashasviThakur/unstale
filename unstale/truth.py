"""Ground-truth simulator: replays the scenario with the hidden fields.

It uses the annotated claims and the true exposure (public signals minus the
members who never read a message). The engine never sees either, so comparing
the engine against this is a fair test.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from . import rules
from .rules import STRONG, WEAK, Belief


@dataclass
class World:
    current: dict[str, tuple[str, str, str]] = field(default_factory=dict)  # slot -> (value, ts, msg)
    history: dict[str, list[tuple[str, str, str]]] = field(default_factory=dict)
    beliefs: dict[str, dict[str, Belief]] = field(default_factory=dict)
    kinds: dict[tuple[str, int], str] = field(default_factory=dict)  # (msg, claim index) -> classification


def true_exposure(msg: dict, ds: dict, people: dict[str, dict]) -> set[str]:
    observed = rules.observed_exposure(msg, ds, people)
    unread = set(msg["_truth"].get("unread_by", []))
    return {pid for pid, s in observed.items() if s == STRONG or (s == WEAK and pid not in unread)}


def simulate(ds: dict[str, Any], as_of: str) -> World:
    people = {p["id"]: p for p in ds["people"]}
    world = World()
    cutoff = rules.parse_ts(as_of)
    by_id = {m["id"]: m for m in ds["messages"]}
    thread_members: dict[str, list[str]] = {}

    def expose(pid: str, m: dict, seen_ts: str) -> None:
        mine = world.beliefs.setdefault(pid, {})
        for i, cl in enumerate(m["_truth"]["claims"]):
            key = rules.slot_key(cl["subject"], cl["attribute"])
            eff = world_eff[(m["id"], i)]
            b = Belief(cl["value"], eff, m["id"], seen_ts)
            if rules.newer(b, mine.get(key)):
                mine[key] = b

    world_eff: dict[tuple[str, int], str] = {}
    for m in ds["messages"]:
        if rules.parse_ts(m["ts"]) > cutoff:
            break
        author_beliefs = world.beliefs.get(m["author"], {})
        for i, cl in enumerate(m["_truth"]["claims"]):
            key = rules.slot_key(cl["subject"], cl["attribute"])
            cur = world.current.get(key)
            ab = author_beliefs.get(key)
            kind = rules.classify(cl["value"], cur[0] if cur else None, ab.value if ab else None)
            world.kinds[(m["id"], i)] = kind
            if kind == "update":
                world.current[key] = (cl["value"], m["ts"], m["id"])
                world.history.setdefault(key, []).append((cl["value"], m["ts"], m["id"]))
                world_eff[(m["id"], i)] = m["ts"]
            elif kind == "echo":
                world_eff[(m["id"], i)] = ab.effective_ts
            else:
                world_eff[(m["id"], i)] = m["ts"]
        for pid in true_exposure(m, ds, people):
            expose(pid, m, m["ts"])
        root = m["thread"] or m["id"]
        if m["thread"]:
            # Replying means you read the thread so far.
            for earlier in thread_members.get(root, []):
                expose(m["author"], by_id[earlier], m["ts"])
        thread_members.setdefault(root, []).append(m["id"])
    return world


def stale_report(ds: dict[str, Any], as_of: str) -> dict[str, list[dict]]:
    """Per person: every relevant slot where their belief differs from the truth."""
    world = simulate(ds, as_of)
    out: dict[str, list[dict]] = {}
    for p in ds["people"]:
        pid = p["id"]
        sc = rules.scope(pid, ds["responsibility"], ds["links"])
        items = []
        for key, (value, ts, mid) in sorted(world.current.items()):
            subject = key.split("|", 1)[0]
            if subject not in sc:
                continue
            b = world.beliefs.get(pid, {}).get(key)
            if b is not None and not rules.same(b.value, value):
                items.append({"slot": key, "believed": b.value, "believed_from": b.message,
                              "current": value, "current_from": mid, "hops": sc[subject]})
        out[pid] = items
    return out


if __name__ == "__main__":
    import json
    import sys

    from .config import DATA

    ds = json.loads((DATA / "northwind.json").read_text(encoding="utf-8"))
    when = sys.argv[1] if len(sys.argv) > 1 else ds["end"]
    report = stale_report(ds, when)
    total = 0
    for pid, items in report.items():
        print(f"{pid}: {len(items)} stale")
        for it in items:
            print(f"   {it['slot']}: believes {it['believed']!r} ({it['believed_from']}) "
                  f"-> now {it['current']!r} ({it['current_from']}), hops={it['hops']}")
        total += len(items)
    print("total stale:", total)
