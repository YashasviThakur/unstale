"""The problem definition, shared by the engine and the ground-truth simulator.

Vocabulary:

* A **slot** is one fact that can change: ``(subject, attribute)``, e.g.
  ``("release:2.4", "SHIPS_ON")``.
* A **claim** is a message stating a value for a slot.
* A person's **belief** about a slot is the value of the newest claim they were
  exposed to, where "newest" is the claim's *effective time*.
* A claim is classified against the current truth and its author's belief:

  - ``restate``: it repeats the current value;
  - ``echo``: it repeats an outdated value its author still believes because
    they never saw the change. It does not change the truth, and its effective
    time is the time of the version it repeats, so it can mislead people who
    knew nothing, but never overrides what someone already learned;
  - ``update``: anything else. It becomes the new current version.

* A person is **stale** on a slot when the slot is relevant to them, they hold a
  belief about it, and that belief differs from the current value.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Iterable

STRONG = "strong"
WEAK = "weak"


@dataclass(frozen=True)
class Belief:
    value: str
    effective_ts: str
    message: str
    seen_ts: str


def slot_key(subject: str, attribute: str) -> str:
    return f"{subject}|{attribute}"


def parse_ts(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def norm_value(value: str) -> str:
    """Compare values case- and space-insensitively ('16:00 utc' == '16:00 UTC')."""
    return " ".join(str(value).lower().split())


def same(a: str | None, b: str | None) -> bool:
    return a is not None and b is not None and norm_value(a) == norm_value(b)


def classify(value: str, current: str | None, author_belief: str | None, *,
             superseded: Iterable[str] = (), author_owns: bool = False, author_knows_current: bool = False) -> str:
    """restate, echo or update (see the module docstring).

    The keyword arguments are what the engine adds, because it can't be sure
    what the author read: repeating a value that has already been replaced is
    an echo unless the author owns the subject or certainly saw the current
    value (wrote it, was mentioned, replied in its thread). Those people can move
    a fact back on purpose; anyone else repeating an old value is passing on what
    they last heard. The answer key knows the author's true belief and needs none
    of this.
    """
    if current is not None and same(value, current):
        return "restate"
    if current is not None and author_belief is not None and same(value, author_belief)             and not same(author_belief, current):
        return "echo"
    if current is not None and not author_owns and not author_knows_current \
            and any(same(value, v) for v in superseded):
        return "echo"
    return "update"


def newer(candidate: Belief, existing: Belief | None) -> bool:
    if existing is None:
        return True
    a, b = parse_ts(candidate.effective_ts), parse_ts(existing.effective_ts)
    if a != b:
        return a > b
    return parse_ts(candidate.seen_ts) >= parse_ts(existing.seen_ts)


def is_ooo(person: dict, ts: str) -> bool:
    when = parse_ts(ts)
    return any(parse_ts(a) <= when < parse_ts(b) for a, b in person.get("ooo", []))


def observed_exposure(msg: dict, ds: dict, people: dict[str, dict]) -> dict[str, str]:
    """Who could have seen ``msg`` at its own timestamp, from public signals only.

    Returns person id -> STRONG (they interacted, were addressed, or are an agent
    that reads its whole channel) or WEAK (channel member who was not out of
    office). Thread replies add exposure to earlier thread messages; the caller
    handles that because it needs the thread history.
    """
    out: dict[str, str] = {}

    def add(pid: str, strength: str) -> None:
        if pid not in people:
            return
        if out.get(pid) == STRONG:
            return
        out[pid] = strength

    ts = msg["ts"]
    add(msg["author"], STRONG)
    for pid in msg.get("reactions", []):
        add(pid, STRONG)
    for pid in msg.get("mentions", []):
        if not is_ooo(people.get(pid, {}), ts):
            add(pid, STRONG)
    for pid in msg.get("to", []) + msg.get("cc", []):
        if pid in people and not is_ooo(people[pid], ts):
            add(pid, STRONG)
    if msg.get("channel"):
        for pid in ds["channels"].get(msg["channel"], []):
            person = people.get(pid)
            if person is None or is_ooo(person, ts):
                continue
            add(pid, STRONG if person.get("kind") == "agent" else WEAK)
    return out


def scope(person_id: str, responsibility: Iterable[list], links: Iterable[list]) -> dict[str, int]:
    """Subjects a person cares about: 0 = they own or work on it, 1 = one link away."""
    direct = {s for p, _, s in responsibility if p == person_id}
    out = {s: 0 for s in direct}
    for a, _, b in links:
        if a in direct and b not in out:
            out[b] = 1
        if b in direct and a not in out:
            out[a] = 1
    return out
