"""The Unstale engine: a belief graph on HydraDB, written and read through SelfGraph.

Graph shape (all in one SelfGraph namespace on HydraDB):

    (Person|Agent) -MEMBER_OF-> (Channel)
    (Person|Agent) -OWNS|WORKS_ON|ATTENDS-> (subject)
    (subject) -PART_OF|DEPENDS_ON|WANTS|WAITING_ON|USES|FOR-> (subject)
    (Person) -POSTED-> (Message) -IN-> (Channel)
    (Person|Agent) -SAW {strength, ts}-> (Message)
    (Message) -ASSERTS-> (Claim {slot, value, kind, effective_ts}) -ABOUT-> (subject)
    (subject) -SHIPS_ON|PRICED_AT|...-> (value)      <- versioned truth, one current version per slot
    (Person) -LEARNED-> (ReadEvidence {channel, read, ts, source})   <- what the graph has learned about reading

The truth layer is SelfGraph's versioned relations: a schema caps every fact
attribute at one current value per subject, so a newer update retires the older
one (and keeps it as history). The exposure layer is the SAW/ASSERTS paths, and
"what does Maya believe" is one two-hop traversal over them.

A weak SAW edge (channel member, no interaction) is a guess. The ReadEvidence
nodes turn it into a learned probability: feedback on corrections, echoes and
restatements each record whether someone read a channel, and ``exposure.py``
turns that into a read rate per person and channel.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

from selfgraph import HydraDBStore, SelfGraph

from . import rules
from .config import DATA, Settings
from .exposure import (THRESHOLD, Evidence, Exposure, ReadModel, evidence_from_own_claim, evidence_from_verdict,
                       stale_probability)
from .rules import STRONG, WEAK, Belief

RESPONSIBILITY_TYPES = ("OWNS", "WORKS_ON", "ATTENDS")
STATE = DATA / "state.json"


def _iso(ts: datetime | str | None) -> str | None:
    if ts is None:
        return None
    if isinstance(ts, str):
        return ts
    return ts.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9.$]+", "-", value.lower()).strip("-") or "empty"


def value_entity(attribute: str, value: str) -> tuple[str, str]:
    if attribute == "OWNED_BY" and value.startswith("person:"):
        return value, "Person"
    return f"value:{_slug(value)}", "Value"


@dataclass
class Version:
    value: str
    since: str
    until: str | None
    message: str | None
    claim: str | None


@dataclass
class StaleItem:
    slot: str
    subject: str
    subject_name: str
    attribute: str
    believed: str
    believed_from: str
    believed_seen: str
    current: str
    current_from: str | None
    changed_at: str
    hops: int
    missed_in: str | None = None
    echo_note: str | None = None
    confidence: float = 1.0
    believed_strength: str = STRONG
    believed_channel: str | None = None


@dataclass
class Stats:
    queries: int = 0
    query_ms: float = 0.0
    writes: int = 0
    write_ms: float = 0.0


# The traversal behind every correction: what a person saw, and which claims those messages assert.
EXPOSURES_CYPHER = (
    "MATCH (p:Entity)-[s:RELATES]->(m:Entity)-[a:RELATES]->(c:Entity) "
    "WHERE p.sid = $p AND p.ns = $ns AND s.etype = 'SAW' AND a.etype = 'ASSERTS' "
    "RETURN c.doc AS claim, s.doc AS saw, c.sid AS cid"
)


def kuzu_dialect(q: str) -> str:
    """HydraDB's generic Entity/RELATES graph, spelled the way SelfGraph's Kuzu store names it (N/R, id)."""
    for alias in re.findall(r"\((\w+):Entity\)", q):
        q = re.sub(r"(?<![A-Za-z0-9_])" + alias + r"[.]sid(?![A-Za-z0-9_])", alias + ".id", q)
    return q.replace(":Entity", ":N").replace(":RELATES", ":R")


@dataclass
class Engine:
    graph: SelfGraph
    ds: dict[str, Any]
    namespace: str
    settings: Settings
    stats: Stats = field(default_factory=Stats)
    _messages: dict[str, dict] = field(default_factory=dict)
    _thread: dict[str, list[str]] = field(default_factory=dict)
    _saw: dict[tuple[str, str], str] = field(default_factory=dict)
    _scope_cache: dict[str, dict[str, int]] = field(default_factory=dict)
    _versions_cache: dict[str, dict[str, list[Version]]] = field(default_factory=dict)
    _evidence: list[Evidence] | None = None
    _owns: set[tuple[str, str]] = field(default_factory=set)
    mode: str = "learned"      # learned | v1 (every channel member read it) | strong (only interactions count)

    # ------------------------------------------------------------------ setup
    @classmethod
    async def open(cls, ds: dict[str, Any], namespace: str | None = None,
                   settings: Settings | None = None) -> "Engine":
        s = settings or Settings.load()
        ns = namespace or current_namespace(s)
        if s.store == "kuzu":
            from selfgraph import KuzuStore  # noqa: PLC0415  (hosted demo only; HydraDB is the engine)
            store = KuzuStore(s.kuzu_path)
        else:
            if not s.hydra_token:
                raise RuntimeError("No HydraDB token: set UNSTALE_HYDRA_TOKEN or create infra/.env")
            store = HydraDBStore(s.hydra_uri, auth=s.hydra_token)
        schema = {
            "relations": [
                {"type": attr, "from": {"max_count": 1}} for attr in ds["attributes"]
            ],
        }
        graph = SelfGraph(store=store, schema=schema,
                          schema_mode="off", contradiction="supersede", namespace=ns)
        await graph.__aenter__()
        eng = cls(graph=graph, ds=ds, namespace=ns, settings=s)
        eng._messages = {m["id"]: m for m in ds["messages"]}
        eng._owns = {(p, x) for p, t, x in ds["responsibility"] if t == "OWNS"}
        return eng

    def remember_threads(self) -> None:
        """Rebuild thread membership for a process that did not run the ingest (the API server)."""
        self._thread = {}
        for m in self.ds["messages"]:
            self._thread.setdefault(m.get("thread") or m["id"], []).append(m["id"])

    async def close(self) -> None:
        await self.graph.__aexit__(None, None, None)

    async def _facts(self, facts: dict, **kw) -> Any:
        t0 = time.perf_counter()
        res = await self.graph.insert.facts(facts, **kw)
        self.stats.writes += len(facts.get("entities", [])) + len(facts.get("relations", []))
        self.stats.write_ms += (time.perf_counter() - t0) * 1000
        return res

    async def _cypher(self, q: str, params: dict) -> list[dict]:
        t0 = time.perf_counter()
        if self.settings.store == "kuzu":
            q = kuzu_dialect(q)
        res = await self.graph.run_cypher(q, {"ns": self.namespace, **params})
        self.stats.queries += 1
        self.stats.query_ms += (time.perf_counter() - t0) * 1000
        return res.rows

    async def load_directory(self) -> None:
        ds = self.ds
        ents, rels = [], []
        for p in ds["people"]:
            ents.append({"id": p["id"], "type": "Agent" if p["kind"] == "agent" else "Person", "name": p["name"],
                         "properties": {"role": p["role"], "ooo": json.dumps(p.get("ooo", []))}})
        for ch, members in ds["channels"].items():
            ents.append({"id": f"channel:{ch}", "type": "Channel", "name": f"#{ch}"})
            for pid in members:
                rels.append({"from_entity": pid, "type": "MEMBER_OF", "to_entity": f"channel:{ch}"})
        for s in ds["subjects"]:
            ents.append({"id": s["id"], "type": s["type"], "name": s["name"]})
        for a, t, b in ds["links"]:
            rels.append({"from_entity": a, "type": t, "to_entity": b})
        for a, t, b in ds["responsibility"]:
            rels.append({"from_entity": a, "type": t, "to_entity": b})
        await self._facts({"entities": ents, "relations": rels})

    # ---------------------------------------------------------------- ingest
    async def ingest(self, m: dict[str, Any], claims: list[dict[str, str]]) -> list[dict]:
        """Write one message. Claims are classified against the graph as it stood before it."""
        people = {p["id"]: p for p in self.ds["people"]}
        self._messages[m["id"]] = m
        classified, learned = [], []
        keys = {rules.slot_key(cl["subject"], cl["attribute"]) for cl in claims}
        author_exps = await self.exposures(m["author"], m["ts"], slots=keys, strict=True) \
            if keys and m["author"] in people else {}
        for i, cl in enumerate(claims):
            key = rules.slot_key(cl["subject"], cl["attribute"])
            history = await self.versions(cl["subject"], cl["attribute"])
            cur = self.pick(history, m["ts"])
            exps = author_exps.get(key, [])
            ab = _newest(exps)
            older = [v.value for v in history if cur and rules.parse_ts(v.since) < rules.parse_ts(cur.since)]
            knows = bool(cur) and any(e.strength == STRONG and rules.same(e.value, cur.value) for e in exps)
            kind = rules.classify(cl["value"], cur.value if cur else None, ab.value if ab else None,
                                  superseded=older, author_owns=(m["author"], cl["subject"]) in self._owns,
                                  author_knows_current=knows)
            eff, echoes = m["ts"], None
            if kind == "echo":
                prev = [v for v in history if rules.same(v.value, cl["value"])
                        and rules.parse_ts(v.since) <= rules.parse_ts(m["ts"])]
                eff = prev[-1].since if prev else (ab.effective_ts if ab else m["ts"])
                echoes = (prev[-1].message if prev else None) or (ab.message if ab else None)
            classified.append({**cl, "slot": key, "kind": kind, "effective_ts": eff, "id": f"claim:{m['id']}-{i}",
                               "echoes": echoes})
            if kind in ("echo", "restate") and cur and m["author"] in people:
                learned += evidence_from_own_claim(m["author"], cl["value"], cur.value, exps, m["ts"], m["id"])

        ents = [{"id": f"message:{m['id']}", "type": "Message", "name": m["id"],
                 "properties": {"ts": m["ts"], "kind": m["kind"], "channel": m.get("channel") or "",
                                "author": m["author"], "thread": m.get("thread") or "",
                                "text": m["text"][:2000]}}]
        rels = []
        if m["author"] in people:
            rels.append({"from_entity": m["author"], "type": "POSTED", "to_entity": f"message:{m['id']}"})
        if m.get("channel"):
            rels.append({"from_entity": f"message:{m['id']}", "type": "IN", "to_entity": f"channel:{m['channel']}"})

        exposure = rules.observed_exposure(m, self.ds, people)
        if not self.settings.weak_exposure:
            exposure = {k: v for k, v in exposure.items() if v == STRONG}
        for pid, strength in exposure.items():
            rels.append(self._saw_rel(pid, m["id"], strength, m["ts"]))
        root = m.get("thread") or m["id"]
        if m.get("thread") and m["author"] in people:
            for earlier in self._thread.get(root, []):
                if self._saw.get((m["author"], earlier)) != STRONG:
                    rels.append(self._saw_rel(m["author"], earlier, STRONG, m["ts"]))
        self._thread.setdefault(root, []).append(m["id"])

        for cl in classified:
            ents.append({"id": cl["id"], "type": "Claim", "name": f"{cl['slot']} = {cl['value']}",
                         "properties": {"slot": cl["slot"], "subject": cl["subject"], "attribute": cl["attribute"],
                                        "value": cl["value"], "kind": cl["kind"], "ts": m["ts"],
                                        "effective_ts": cl["effective_ts"], "message": m["id"],
                                        "echoes": cl["echoes"] or ""}})
            rels.append({"from_entity": f"message:{m['id']}", "type": "ASSERTS", "to_entity": cl["id"]})
            rels.append({"from_entity": cl["id"], "type": "ABOUT", "to_entity": cl["subject"]})
        await self._facts({"entities": ents, "relations": rels})

        for cl in classified:
            if cl["kind"] != "update":
                continue
            self._versions_cache.pop(cl["subject"], None)
            vid, vtype = value_entity(cl["attribute"], cl["value"])
            facts = {"relations": [{"from_entity": cl["subject"], "type": cl["attribute"], "to_entity": vid,
                                    "event_time": m["ts"],
                                    "properties": {"value": cl["value"], "claim": cl["id"], "message": m["id"]}}]}
            if vtype == "Value":
                facts["entities"] = [{"id": vid, "type": "Value", "name": cl["value"]}]
            await self._facts(facts, source_id=f"msg-{m['id']}")
        if learned:
            await self.write_evidence(learned, origin=m["id"])
        return classified

    # -------------------------------------------------------- read evidence
    async def load_evidence(self) -> list[Evidence]:
        if self._evidence is None:
            rows = await self._cypher(
                "MATCH (p:Entity)-[r:RELATES]->(e:Entity) WHERE r.ns = $ns AND r.etype = 'LEARNED' "
                "RETURN e.doc AS ev", {})
            out = []
            for r in rows:
                pr = json.loads(json.loads(r["ev"])["properties_json"])
                out.append(Evidence(pr["person"], pr["channel"], str(pr["read"]).lower() == "true", pr["ts"],
                                    pr["source"], float(pr.get("weight", 1.0))))
            self._evidence = sorted(out, key=lambda e: e.ts)
        return self._evidence

    async def write_evidence(self, items: list[Evidence], origin: str, note: dict | None = None) -> None:
        ev = await self.load_evidence()
        ents, rels = [], []
        for e in items:
            eid = f"readevidence:{len(ev) + len(ents):06d}-{origin}"
            ents.append({"id": eid, "type": "ReadEvidence",
                         "name": f"{e.person} {'read' if e.read else 'missed'} #{e.channel}",
                         "properties": {"person": e.person, "channel": e.channel, "read": str(e.read).lower(),
                                        "ts": e.ts, "source": e.source, "weight": e.weight, "origin": origin,
                                        **{k: str(v) for k, v in (note or {}).items()}}})
            rels.append({"from_entity": e.person, "type": "LEARNED", "to_entity": eid,
                         "properties": {"ts": e.ts, "source": e.source}})
        if ents:
            await self._facts({"entities": ents, "relations": rels})
            ev.extend(items)
            ev.sort(key=lambda e: e.ts)

    async def read_model(self, as_of: str) -> ReadModel:
        if self.mode == "v1":
            return ReadModel(fixed=1.0)
        if self.mode == "strong":
            return ReadModel(fixed=0.0)
        t = rules.parse_ts(as_of)
        return ReadModel([e for e in await self.load_evidence() if rules.parse_ts(e.ts) <= t])

    async def record_feedback(self, person: str, slot: str, verdict: str, ts: str) -> dict:
        """A person answers a correction: "news" (didn't know), "knew", or "neither" (never heard either value)."""
        if verdict not in ("news", "knew", "neither"):
            raise ValueError("verdict must be news, knew or neither")
        subject, attribute = slot.split("|", 1)
        cur = await self.truth_at(subject, attribute, ts)
        if cur is None:
            return {"evidence": 0, "channels": []}
        exps = (await self.exposures(person, ts, slots={slot})).get(slot, [])
        _, best = stale_probability(exps, cur.value, person, await self.read_model(ts))
        items = evidence_from_verdict(person, verdict, cur.value, best.value if best else "", exps, ts)
        await self.write_evidence(items, origin=f"fb-{int(time.time() * 1000)}", note={"slot": slot, "verdict": verdict})
        return {"evidence": len(items), "channels": sorted({e.channel for e in items})}

    def _saw_rel(self, pid: str, mid: str, strength: str, ts: str) -> dict:
        self._saw[(pid, mid)] = strength
        return {"from_entity": pid, "type": "SAW", "to_entity": f"message:{mid}",
                "properties": {"strength": strength, "ts": ts}}

    # ----------------------------------------------------------------- reads
    async def subject_versions(self, subject: str) -> dict[str, list[Version]]:
        """Every version of every fact about ``subject``, oldest first, from SelfGraph's relation history."""
        if subject in self._versions_cache:
            return self._versions_cache[subject]
        t0 = time.perf_counter()
        page = await self.graph.relations.list(from_entity=subject, include_invalidated=True, limit=500)
        by_attr: dict[str, list[Version]] = {}
        for rel in page.items:
            if rel.type not in self.ds["attributes"]:
                continue
            revs = await self.graph.relations.versions(rel.id, newest_first=False) if rel.revision > 1 else [rel]
            for v in revs:
                if v.event_time is None:
                    continue
                by_attr.setdefault(rel.type, []).append(
                    Version(value=str(v.properties.get("value", v.to_entity)), since=_iso(v.event_time),
                            until=None, message=v.properties.get("message"), claim=v.properties.get("claim")))
        self.stats.queries += 1
        self.stats.query_ms += (time.perf_counter() - t0) * 1000
        for out in by_attr.values():
            # One relation can hold several revisions (a value that came back); each version ends
            # where the next one in time begins.
            out.sort(key=lambda v: rules.parse_ts(v.since))
            for a, b in zip(out, out[1:]):
                a.until = b.since
        self._versions_cache[subject] = by_attr
        return by_attr

    async def all_claims(self) -> dict[str, list[dict]]:
        """message id -> the claims the graph holds for it, in one traversal."""
        rows = await self._cypher(
            "MATCH (m:Entity)-[a:RELATES]->(c:Entity) WHERE a.ns = $ns AND a.etype = 'ASSERTS' "
            "RETURN m.sid AS m, c.doc AS claim", {})
        out: dict[str, list[dict]] = {}
        for r in rows:
            props = json.loads(json.loads(r["claim"])["properties_json"])
            out.setdefault(r["m"].split(":", 1)[1], []).append(props)
        return out

    async def versions(self, subject: str, attribute: str) -> list[Version]:
        return (await self.subject_versions(subject)).get(attribute, [])

    @staticmethod
    def pick(versions: list[Version], as_of: str) -> Version | None:
        t = rules.parse_ts(as_of)
        best = None
        for v in versions:
            if rules.parse_ts(v.since) <= t and (v.until is None or rules.parse_ts(v.until) > t):
                best = v
        return best

    async def truth_at(self, subject: str, attribute: str, as_of: str) -> Version | None:
        return self.pick(await self.versions(subject, attribute), as_of)

    async def beliefs(self, person: str, as_of: str, slots: set[str] | None = None) -> dict[str, Belief]:
        """What ``person`` believes: newest claim (by effective time) on every message they saw."""
        rows = await self._cypher(
            "MATCH (p:Entity)-[s:RELATES]->(m:Entity)-[a:RELATES]->(c:Entity) "
            "WHERE p.sid = $p AND p.ns = $ns AND s.etype = 'SAW' AND a.etype = 'ASSERTS' "
            "RETURN c.doc AS claim, s.doc AS saw", {"p": person})
        t = rules.parse_ts(as_of)
        out: dict[str, Belief] = {}
        for r in rows:
            props = json.loads(json.loads(r["claim"])["properties_json"])
            seen = json.loads(json.loads(r["saw"])["properties_json"])
            if slots is not None and props["slot"] not in slots:
                continue
            if rules.parse_ts(props["ts"]) > t or rules.parse_ts(seen["ts"]) > t:
                continue
            # Only strictly earlier messages count while classifying the message at ``as_of``.
            if rules.parse_ts(props["ts"]) == t and slots is not None:
                continue
            b = Belief(props["value"], props["effective_ts"], props["message"], seen["ts"])
            if rules.newer(b, out.get(props["slot"])):
                out[props["slot"]] = b
        return out

    async def exposures(self, person: str, as_of: str, slots: set[str] | None = None,
                        strict: bool = False) -> dict[str, list[Exposure]]:
        """Every claim the person may have seen, per slot, with how they saw it (same traversal as ``beliefs``).

        A message seen twice (weakly as a channel member, then strongly by replying in its thread)
        counts once, with the strongest exposure in effect at ``as_of``.
        """
        rows = await self._cypher(EXPOSURES_CYPHER, {"p": person})
        t = rules.parse_ts(as_of)
        best: dict[str, tuple[dict, str, str]] = {}
        for r in rows:
            props = json.loads(json.loads(r["claim"])["properties_json"])
            seen = json.loads(json.loads(r["saw"])["properties_json"])
            if slots is not None and props["slot"] not in slots:
                continue
            mt = rules.parse_ts(props["ts"])
            if mt > t or rules.parse_ts(seen["ts"]) > t or (strict and mt == t):
                continue
            prev = best.get(r["cid"])
            first_seen = seen["ts"] if prev is None or rules.parse_ts(seen["ts"]) < rules.parse_ts(prev[2]) else prev[2]
            strength = STRONG if seen["strength"] == STRONG or (prev and prev[1] == STRONG) else WEAK
            best[r["cid"]] = (props, strength, first_seen)
        out: dict[str, list[Exposure]] = {}
        for props, strength, seen_ts in best.values():
            m = self._messages.get(props["message"], {})
            out.setdefault(props["slot"], []).append(Exposure(props["slot"], props["value"], props["effective_ts"],
                                                              props["message"], seen_ts, strength, m.get("channel")))
        return out

    async def scope(self, person: str) -> dict[str, int]:
        """Subjects the person owns or works on (0) and subjects one link away (1), by traversal."""
        if person in self._scope_cache:
            return self._scope_cache[person]
        # Directory edges are never retired, so no is_current predicate: on HydraDB 0.3 it costs
        # ~110 ms per query, against ~20 ms without it.
        direct_rows = await self._cypher(
            "MATCH (p:Entity)-[r:RELATES]->(s:Entity) WHERE p.sid = $p AND p.ns = $ns "
            "RETURN r.etype AS et, s.sid AS s", {"p": person})
        direct = {r["s"] for r in direct_rows if r["et"] in RESPONSIBILITY_TYPES}
        out = {s: 0 for s in direct}
        link_types = {t for _, t, _ in self.ds["links"]}
        # One seek per owned subject, both directions. (A single 2-hop pattern from the person
        # made HydraDB 0.3's planner scan from every node, about 1.5 s; seeks from a known id are ms.)
        for s in sorted(direct):
            rows = await self._cypher(
                "MATCH (s:Entity)-[r:RELATES]->(x:Entity) WHERE s.sid = $s AND s.ns = $ns "
                "RETURN r.etype AS et, x.sid AS x", {"s": s})
            rows += await self._cypher(
                "MATCH (s:Entity)<-[r:RELATES]-(x:Entity) WHERE s.sid = $s AND s.ns = $ns "
                "RETURN r.etype AS et, x.sid AS x", {"s": s})
            for r in rows:
                if r["et"] in link_types and r["x"] not in out:
                    out[r["x"]] = 1
        self._scope_cache[person] = out
        return out

    async def who_saw(self, mid: str) -> dict[str, str]:
        rows = await self._cypher(
            "MATCH (p:Entity)-[s:RELATES]->(m:Entity) WHERE m.sid = $m AND m.ns = $ns AND s.etype = 'SAW' "
            "RETURN p.sid AS p, s.doc AS saw", {"m": f"message:{mid}"})
        return {r["p"]: json.loads(json.loads(r["saw"])["properties_json"])["strength"] for r in rows}

    async def diff(self, person: str, as_of: str, model: ReadModel | None = None,
                   threshold: float = THRESHOLD, exps: dict[str, list[Exposure]] | None = None) -> list[StaleItem]:
        """What ``person`` probably believes that is no longer true, most certain first within each hop.

        ``exps`` lets a caller that scores several read models reuse one traversal.
        """
        model = model if model is not None else await self.read_model(as_of)
        sc = await self.scope(person)
        exps = exps if exps is not None else await self.exposures(person, as_of)
        names = {s["id"]: s["name"] for s in self.ds["subjects"]}
        items = []
        for key, es in exps.items():
            subject, attribute = key.split("|", 1)
            if subject not in sc:
                continue
            cur = self.pick((await self.subject_versions(subject)).get(attribute, []), as_of)
            if cur is None:
                continue
            p, b = stale_probability(es, cur.value, person, model)
            if b is None or p < threshold:
                continue
            m = self._messages.get(cur.message or "", {})
            where = f"#{m['channel']}" if m.get("channel") else (m.get("kind") or None)
            echo = None
            bm = self._messages.get(b.message, {})
            if bm and rules.parse_ts(bm["ts"]) > rules.parse_ts(cur.since):
                echo = f"{self._name(bm['author'])} repeated the old value on {bm['ts'][:10]}"
            items.append(StaleItem(slot=key, subject=subject, subject_name=names.get(subject, subject),
                                   attribute=attribute, believed=b.value, believed_from=b.message,
                                   believed_seen=b.seen_ts, current=cur.value, current_from=cur.message,
                                   changed_at=cur.since, hops=sc[subject], missed_in=where, echo_note=echo,
                                   confidence=round(p, 3), believed_strength=b.strength,
                                   believed_channel=b.channel))
        items.sort(key=lambda x: (x.hops, -x.confidence, x.changed_at))
        return items

    def _name(self, pid: str) -> str:
        for p in self.ds["people"]:
            if p["id"] == pid:
                return p["name"]
        return self.ds.get("external", {}).get(pid, pid)

    async def slot_view(self, subject: str, attribute: str, as_of: str) -> dict[str, Any]:
        """History of one fact, plus which version each person currently believes."""
        vers = [v for v in await self.versions(subject, attribute) if rules.parse_ts(v.since) <= rules.parse_ts(as_of)]
        cur = await self.truth_at(subject, attribute, as_of)
        key = rules.slot_key(subject, attribute)
        believers = {}
        for p in self.ds["people"]:
            b = (await self.beliefs(p["id"], as_of, slots={key})).get(key)
            sc = await self.scope(p["id"])
            believers[p["id"]] = {"believes": b.value if b else None, "relevant": subject in sc,
                                  "stale": bool(b and cur and not rules.same(b.value, cur.value))}
        return {"slot": key, "versions": [asdict(v) for v in vers], "current": asdict(cur) if cur else None,
                "people": believers}


async def check_draft(eng: Engine, author: str, text: str, as_of: str, audience: list[str]) -> dict[str, Any]:
    """Before-send check: does this draft state anything that is no longer true, and who reading it is stale?"""
    from .extract import extract_draft  # noqa: PLC0415  (keeps the engine importable without an LLM key)

    claims = extract_draft(text, author, as_of, eng.ds)
    mine = await eng.beliefs(author, as_of) if author in {p["id"] for p in eng.ds["people"]} else {}
    issues, touched = [], set()
    for cl in claims:
        key = rules.slot_key(cl["subject"], cl["attribute"])
        touched.add(key)
        cur = await eng.truth_at(cl["subject"], cl["attribute"], as_of)
        if cur is None or rules.same(cur.value, cl["value"]):
            continue
        b = mine.get(key)
        kind = rules.classify(cl["value"], cur.value, b.value if b else None)
        issues.append({"slot": key, "subject": cl["subject"], "attribute": cl["attribute"], "wrote": cl["value"],
                       "current": cur.value, "changed_at": cur.since, "changed_in": cur.message,
                       "kind": "outdated" if kind == "echo" else "conflict",
                       "author_belief": b.value if b else None})
    stale_readers = []
    for pid in audience:
        if pid == author:
            continue
        theirs = await eng.beliefs(pid, as_of, slots=touched) if touched else {}
        for key in touched:
            b = theirs.get(key)
            subject, attribute = key.split("|", 1)
            cur = await eng.truth_at(subject, attribute, as_of)
            if b and cur and not rules.same(b.value, cur.value):
                stale_readers.append({"person": pid, "slot": key, "believes": b.value, "current": cur.value})
    return {"claims": claims, "issues": issues, "stale_readers": stale_readers}


async def agent_context(eng: Engine, agent: str, as_of: str) -> str:
    """A block to prepend to an agent's prompt: what in its context is out of date, and what it has no source for.

    Gaps are facts about things the agent is directly responsible for that none of its sources mention;
    scripts/agent_eval.py measures this exact block.
    """
    items = await eng.diff(agent, as_of)
    labels = {k: v.get("label", k.lower()) for k, v in eng.ds["attributes"].items()}
    names = {s["id"]: s["name"] for s in eng.ds["subjects"]}
    lines = []
    for it in items:
        lines.append(f"- {it.subject_name} {labels[it.attribute]}: now {it.current} (changed {it.changed_at[:10]}); "
                     f"your sources still say {it.believed}. Use the new value.")
    seen = set((await eng.exposures(agent, as_of)).keys())
    for subject, hops in sorted((await eng.scope(agent)).items()):
        if hops:
            continue
        for attribute, vers in sorted((await eng.subject_versions(subject)).items()):
            cur = eng.pick(vers, as_of)
            if cur and rules.slot_key(subject, attribute) not in seen:
                lines.append(f"- {names.get(subject, subject)} {labels.get(attribute, attribute)}: {cur.value} "
                             f"(set {cur.since[:10]}). None of your sources mention it.")
    if not lines:
        return "Unstale: nothing you have read has changed since."
    return "Unstale corrections to your context (newer than what you have read):\n" + "\n".join(lines)


def _newest(exps: list[Exposure]) -> Exposure | None:
    """v1's deterministic belief: the newest claim among messages seen."""
    best = None
    for e in exps:
        if best is None or rules.newer(Belief(e.value, e.effective_ts, e.message, e.seen_ts),
                                       Belief(best.value, best.effective_ts, best.message, best.seen_ts)):
            best = e
    return best


def current_namespace(s: Settings | None = None) -> str:
    if STATE.exists():
        return json.loads(STATE.read_text(encoding="utf-8"))["namespace"]
    return (s or Settings.load()).namespace


def set_namespace(ns: str) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps({"namespace": ns}), encoding="utf-8")
