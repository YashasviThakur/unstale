"""A pure-Python twin of the graph engine.

It holds the same three things the HydraDB graph holds (fact versions, SAW
edges with strength, read evidence) in dictionaries, and applies the same
rules. Two uses:

* the tests check that the HydraDB engine and this twin give identical briefs
  on generated orgs, so the graph traversals are verified against code a
  reviewer can read in one sitting;
* parameter sweeps for the benchmark (threshold, priors) run here in seconds.

It reads only what the engine reads: public message fields plus claims.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from . import rules
from .exposure import Evidence, Exposure, ReadModel, THRESHOLD, evidence_from_own_claim, stale_probability
from .rules import STRONG


@dataclass
class Item:
    slot: str
    believed: str
    believed_from: str
    current: str
    current_from: str
    changed_at: str
    hops: int
    p: float


@dataclass
class Reference:
    ds: dict[str, Any]
    weak_exposure: bool = True
    versions: dict[str, list[tuple[str, str, str]]] = field(default_factory=dict)   # slot -> [(value, since, msg)]
    saw: dict[str, dict[str, list[tuple[str, str]]]] = field(default_factory=dict)  # person -> msg -> [(strength, ts)]
    claims: dict[str, list[dict]] = field(default_factory=dict)                     # msg -> classified claims
    evidence: list[Evidence] = field(default_factory=list)
    thread: dict[str, list[str]] = field(default_factory=dict)
    msgs: dict[str, dict] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.people = {p["id"]: p for p in self.ds["people"]}
        self.owns = {(p, s) for p, t, s in self.ds["responsibility"] if t == "OWNS"}
        self._scope = {p: rules.scope(p, self.ds["responsibility"], self.ds["links"]) for p in self.people}

    # ---------------------------------------------------------------- truth
    def current(self, slot: str, as_of: str) -> tuple[str, str, str] | None:
        t, best = rules.parse_ts(as_of), None
        for v in self.versions.get(slot, []):
            if rules.parse_ts(v[1]) <= t:
                best = v
        return best

    # ------------------------------------------------------------- exposure
    def exposures(self, person: str, as_of: str, slots: set[str] | None = None,
                  strict: bool = False) -> dict[str, list[Exposure]]:
        t = rules.parse_ts(as_of)
        out: dict[str, list[Exposure]] = {}
        for mid, seen_list in self.saw.get(person, {}).items():
            m = self.msgs[mid]
            mt = rules.parse_ts(m["ts"])
            live = [(s, ts) for s, ts in seen_list if rules.parse_ts(ts) <= t]
            if mt > t or not live or (strict and mt == t):
                continue
            strength = STRONG if any(s == STRONG for s, _ in live) else rules.WEAK
            seen = min((ts for _, ts in live), key=rules.parse_ts)
            for cl in self.claims.get(mid, []):
                if slots is not None and cl["slot"] not in slots:
                    continue
                out.setdefault(cl["slot"], []).append(Exposure(cl["slot"], cl["value"], cl["effective_ts"], mid, seen,
                                                               strength, m.get("channel")))
        return out

    def belief(self, person: str, as_of: str, slot: str, strict: bool = False) -> Exposure | None:
        """v1's deterministic belief: newest claim on any message seen."""
        best = None
        for e in self.exposures(person, as_of, {slot}, strict).get(slot, []):
            b = rules.Belief(e.value, e.effective_ts, e.message, e.seen_ts)
            if best is None or rules.newer(b, rules.Belief(best.value, best.effective_ts, best.message, best.seen_ts)):
                best = e
        return best

    # --------------------------------------------------------------- ingest
    def _see(self, pid: str, mid: str, strength: str, ts: str) -> None:
        self.saw.setdefault(pid, {}).setdefault(mid, []).append((strength, ts))

    def ingest(self, m: dict, claims: list[dict]) -> list[dict]:
        self.msgs[m["id"]] = m
        out = []
        for i, cl in enumerate(claims):
            key = rules.slot_key(cl["subject"], cl["attribute"])
            cur = self.current(key, m["ts"])
            ab = self.belief(m["author"], m["ts"], key, strict=True) if m["author"] in self.people else None
            older = [v[0] for v in self.versions.get(key, [])[:-1]] if cur else []
            exps = self.exposures(m["author"], m["ts"], {key}, strict=True).get(key, []) \
                if m["author"] in self.people else []
            knows = bool(cur) and any(e.strength == STRONG and rules.same(e.value, cur[0]) for e in exps)
            kind = rules.classify(cl["value"], cur[0] if cur else None, ab.value if ab else None,
                                  superseded=older, author_owns=(m["author"], cl["subject"]) in self.owns,
                                  author_knows_current=knows)
            eff = m["ts"]
            if kind == "echo":
                prev = [v for v in self.versions[key] if rules.same(v[0], cl["value"])]
                eff = prev[-1][1] if prev else (ab.effective_ts if ab else m["ts"])
            out.append({**cl, "slot": key, "kind": kind, "effective_ts": eff, "ts": m["ts"], "message": m["id"]})
            if m["author"] in self.people and kind in ("echo", "restate") and cur:
                self.evidence += evidence_from_own_claim(m["author"], cl["value"], cur[0], exps, m["ts"], m["id"])
        exposure = rules.observed_exposure(m, self.ds, self.people)
        if not self.weak_exposure:
            exposure = {k: v for k, v in exposure.items() if v == STRONG}
        for pid, strength in exposure.items():
            self._see(pid, m["id"], strength, m["ts"])
        root = m.get("thread") or m["id"]
        if m.get("thread") and m["author"] in self.people:
            for earlier in self.thread.get(root, []):
                self._see(m["author"], earlier, STRONG, m["ts"])
        self.thread.setdefault(root, []).append(m["id"])
        self.claims[m["id"]] = out
        for cl in out:
            if cl["kind"] == "update":
                self.versions.setdefault(cl["slot"], []).append((cl["value"], m["ts"], m["id"]))
        return out

    def ingest_all(self, oracle: bool = True) -> "Reference":
        for m in self.ds["messages"]:
            self.ingest(m, m["_truth"]["claims"] if oracle else [])
        return self

    # ----------------------------------------------------------------- read
    def diff(self, person: str, as_of: str, model: ReadModel, threshold: float = THRESHOLD) -> list[Item]:
        sc = self._scope[person]
        exps = self.exposures(person, as_of)
        items = []
        for slot, es in exps.items():
            subject = slot.split("|", 1)[0]
            if subject not in sc:
                continue
            cur = self.current(slot, as_of)
            if cur is None:
                continue
            p, best = stale_probability(es, cur[0], person, model)
            if best is not None and p >= threshold:
                items.append(Item(slot, best.value, best.message, cur[0], cur[2], cur[1], sc[subject], round(p, 3)))
        items.sort(key=lambda x: (x.hops, x.changed_at))
        return items
