"""Exposure you can't see, estimated and learned.

Slack does not say who read a message. A channel member who wasn't out of
office *might* have read it. Unstale v1 assumed they always did. This module
replaces that guess with a read rate per (person, channel), learned from
evidence the graph collects as it runs:

* **feedback**: a person marks a correction "news to me" (they never saw the
  change) or "I knew this" (they did);
* **echoes**: someone repeats a value that was already changed, which shows
  they missed every message with the change that they were only weakly exposed to;
* **restates**: someone repeats the current value when their only exposure to
  it was weak, which shows they read one of those messages.

A belief then becomes a probability. For one fact, sort the messages a person
may have seen from newest claim to oldest; each has a chance ``p`` they read it
(1 for strong exposure, the learned read rate for weak). They believe claim
``k`` if they read it and none of the newer ones::

    P(belief = k) = p_k * prod_{j newer than k} (1 - p_j)

and they are stale with probability ``sum P(belief = k)`` over claims whose
value is no longer current. Unstale reports items at or above a threshold and
shows the probability as its confidence.

With no evidence every read rate sits at the prior (0.8), and the decision is
the same as v1's: the newest claim dominates. Evidence only moves people whose
behaviour says otherwise.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from . import rules

PRIOR_MEAN = 0.8
PRIOR_WEIGHT = 10.0    # pseudo-observations behind the prior for the org-wide rate (moves slowly)
POOL_WEIGHT = 3.0      # pseudo-observations behind the pooled person/channel mean
THRESHOLD = 0.5


@dataclass(frozen=True)
class Evidence:
    person: str
    channel: str
    read: bool
    ts: str
    source: str = "feedback"     # feedback | echo | restate
    weight: float = 1.0


@dataclass
class ReadModel:
    """Read rate per (person, channel), with partial pooling across people and channels.

    Each pair's estimate is shrunk toward a blend of that person's overall rate
    and that channel's overall rate; those are shrunk toward the org's overall
    rate, which is shrunk toward the prior (0.8).
    One person saying "news to me" about #release lowers their #release rate a lot
    and everyone else's #release rate a little.
    """

    evidence: list[Evidence] = field(default_factory=list)
    fixed: float | None = None    # set to 1.0 for v1 behaviour, 0.0 for strong-only

    def __post_init__(self) -> None:
        self._pair: dict[tuple[str, str], list[float]] = {}
        self._person: dict[str, list[float]] = {}
        self._channel: dict[str, list[float]] = {}
        for e in self.evidence:
            self._add(e)

    def _add(self, e: Evidence) -> None:
        for table, key in ((self._pair, (e.person, e.channel)), (self._person, e.person),
                           (self._channel, e.channel)):
            hits_misses = table.setdefault(key, [0.0, 0.0])
            hits_misses[0 if e.read else 1] += e.weight

    def add(self, e: Evidence) -> None:
        self.evidence.append(e)
        self._add(e)

    def until(self, as_of: str) -> "ReadModel":
        """The model as it stood at ``as_of`` (evidence collected after it is ignored)."""
        t = rules.parse_ts(as_of)
        return ReadModel([e for e in self.evidence if rules.parse_ts(e.ts) <= t], fixed=self.fixed)

    @staticmethod
    def _shrunk(hm: list[float] | None, mean: float, weight: float) -> float:
        h, m = hm or (0.0, 0.0)
        return (mean * weight + h) / (weight + h + m)

    def org_rate(self) -> float:
        h = sum(v[0] for v in self._channel.values())
        m = sum(v[1] for v in self._channel.values())
        return self._shrunk([h, m], PRIOR_MEAN, PRIOR_WEIGHT)

    def rate(self, person: str, channel: str | None) -> float:
        if self.fixed is not None:
            return self.fixed
        org = self.org_rate()
        if channel is None:
            return org
        pm = self._shrunk(self._person.get(person), org, POOL_WEIGHT)
        cm = self._shrunk(self._channel.get(channel), org, POOL_WEIGHT)
        return self._shrunk(self._pair.get((person, channel)), 0.5 * (pm + cm), POOL_WEIGHT)

    def table(self) -> list[dict]:
        """Every (person, channel) with evidence, for the UI."""
        out = []
        for (p, c), (h, m) in sorted(self._pair.items()):
            out.append({"person": p, "channel": c, "read": h, "missed": m, "rate": round(self.rate(p, c), 3)})
        return out


@dataclass(frozen=True)
class Exposure:
    """One claim a person may have seen: the claim, how they were exposed, and where."""

    slot: str
    value: str
    effective_ts: str
    message: str
    seen_ts: str
    strength: str
    channel: str | None


def read_prob(e: Exposure, person: str, model: ReadModel) -> float:
    return 1.0 if e.strength == rules.STRONG else model.rate(person, e.channel)


def belief_distribution(exposures: Iterable[Exposure], person: str, model: ReadModel) -> list[tuple[Exposure, float]]:
    """P(belief comes from each exposure), newest claim first, for one slot."""
    ranked = sorted(exposures, key=lambda e: (rules.parse_ts(e.effective_ts), rules.parse_ts(e.seen_ts)),
                    reverse=True)
    out, none_newer = [], 1.0
    for e in ranked:
        p = read_prob(e, person, model)
        out.append((e, none_newer * p))
        none_newer *= 1.0 - p
    return out


def stale_probability(exposures: Iterable[Exposure], current: str, person: str, model: ReadModel) -> tuple[float, Exposure | None]:
    """Chance the person holds an outdated value, and the most likely outdated claim they hold."""
    dist = belief_distribution(exposures, person, model)
    p_stale, best, best_p = 0.0, None, 0.0
    for e, p in dist:
        if not rules.same(e.value, current):
            p_stale += p
            if p > best_p:
                best, best_p = e, p
    return p_stale, best


def evidence_from_verdict(person: str, verdict: str, current_value: str, believed_value: str,
                          exposures: Iterable[Exposure], ts: str) -> list[Evidence]:
    """Turn one piece of feedback on a correction into read/missed evidence per channel.

    "news" (they did not know the new value): every weakly-exposed message that
    carried the current value went unread. "knew": they read at least one
    weakly-exposed message with the current value; credit is split across them.
    "neither" (they never heard either value): the weak messages carrying both
    went unread.
    """
    exps = list(exposures)
    weak_current = [e for e in exps if e.strength == rules.WEAK and rules.same(e.value, current_value) and e.channel]
    out: list[Evidence] = []
    if verdict == "news":
        for e in weak_current:
            out.append(Evidence(person, e.channel, False, ts, "feedback"))
    elif verdict == "knew" and weak_current:
        w = 1.0 / len(weak_current)
        for e in weak_current:
            out.append(Evidence(person, e.channel, True, ts, "feedback", w))
    elif verdict == "neither":
        # "I never heard either value": the weak messages carrying both went unread.
        for e in exps:
            if e.strength == rules.WEAK and e.channel and (rules.same(e.value, current_value)
                                                            or rules.same(e.value, believed_value)):
                out.append(Evidence(person, e.channel, False, ts, "feedback"))
    return out


def evidence_from_own_claim(person: str, value: str, current_value: str | None, exposures: Iterable[Exposure],
                            ts: str, message: str) -> list[Evidence]:
    """What a person's own message reveals about what they read before writing it.

    An echo (an outdated value) means they missed every weakly-exposed message
    that carried a newer value. Restating the current value when they only had
    weak exposure to it means they read one of those messages.
    """
    if current_value is None:
        return []
    exps = list(exposures)
    if rules.same(value, current_value):
        if any(e.strength == rules.STRONG and rules.same(e.value, current_value) for e in exps):
            return []
        weak = [e for e in exps if e.strength == rules.WEAK and rules.same(e.value, current_value) and e.channel]
        if not weak:
            return []
        w = 1.0 / len(weak)
        return [Evidence(person, e.channel, True, ts, "restate", w) for e in weak]
    believed = [e for e in exps if rules.same(e.value, value)]
    if not believed:
        return []
    since = max(rules.parse_ts(e.effective_ts) for e in believed)
    newer = [e for e in exps if e.strength == rules.WEAK and e.channel and not rules.same(e.value, value)
             and rules.parse_ts(e.effective_ts) > since]
    return [Evidence(person, e.channel, False, ts, "echo") for e in newer]
