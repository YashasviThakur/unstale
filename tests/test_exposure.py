"""The learned-exposure model and the generated benchmark orgs. No database or LLM needed."""

from __future__ import annotations

import json

import pytest

from unstale import orgsim, rules, truth
from unstale.config import DATA
from unstale.exposure import (Evidence, Exposure, ReadModel, evidence_from_own_claim, evidence_from_verdict,
                              stale_probability)
from unstale.reference import Reference

W, S = rules.WEAK, rules.STRONG


def exp(value, eff, strength=W, channel="release", msg="m1"):
    return Exposure("release:2.4|SHIPS_ON", value, eff, msg, eff, strength, channel)


def test_v1_behaviour_is_the_fixed_model():
    old = exp("Mon", "2026-06-22T09:00:00Z", W, "general", "m1")
    new = exp("Fri", "2026-06-26T15:00:00Z", W, "release", "m2")
    v1 = ReadModel(fixed=1.0)
    assert stale_probability([old, new], "Fri", "person:dev", v1)[0] == 0.0
    assert stale_probability([old], "Fri", "person:maya", v1)[0] == 1.0


def test_stale_probability_closed_form():
    m = ReadModel()                       # prior 0.8 everywhere
    old = exp("Mon", "2026-06-22T09:00:00Z", W, "general", "m1")
    new = exp("Fri", "2026-06-26T15:00:00Z", W, "release", "m2")
    p, best = stale_probability([old, new], "Fri", "person:dev", m)
    assert p == pytest.approx(0.2 * 0.8)  # missed the new one and read the old one
    assert best.message == "m1"
    # A strong exposure to the change settles it.
    sure = exp("Fri", "2026-06-26T15:00:00Z", S, "release", "m3")
    assert stale_probability([old, sure], "Fri", "person:dev", m)[0] == 0.0


def test_evidence_moves_one_pair_most_and_pools_the_rest():
    ev = [Evidence("person:dev", "release", False, "2026-06-27T08:00:00Z") for _ in range(4)]
    m = ReadModel(ev)
    assert m.rate("person:dev", "release") < 0.45
    assert m.rate("person:dev", "release") < m.rate("person:sara", "release") < 0.8   # pooled by channel
    assert m.until("2026-06-26T00:00:00Z").rate("person:dev", "release") == pytest.approx(0.8)  # time travel


def test_verdicts_and_echoes_turn_into_evidence():
    old = exp("Mon", "2026-06-22T09:00:00Z", W, "general", "m1")
    new = exp("Fri", "2026-06-26T15:00:00Z", W, "release", "m2")
    news = evidence_from_verdict("p", "news", "Fri", "Mon", [old, new], "t")
    assert [(e.channel, e.read) for e in news] == [("release", False)]
    knew = evidence_from_verdict("p", "knew", "Fri", "Mon", [old, new], "t")
    assert [(e.channel, e.read) for e in knew] == [("release", True)]
    neither = evidence_from_verdict("p", "neither", "Fri", "Mon", [old, new], "t")
    assert sorted((e.channel, e.read) for e in neither) == [("general", False), ("release", False)]
    echo = evidence_from_own_claim("p", "Mon", "Fri", [old, new], "t", "m9")
    assert [(e.channel, e.read, e.source) for e in echo] == [("release", False, "echo")]
    restate = evidence_from_own_claim("p", "Fri", "Fri", [old, new], "t", "m9")
    assert [(e.channel, e.read, e.source) for e in restate] == [("release", True, "restate")]


def test_ownership_echo_rule():
    # A non-owner repeating a replaced value is an echo even if the engine thinks they saw the change...
    assert rules.classify("Mon", "Fri", "Fri", superseded=["Mon"]) == "echo"
    # ...unless they own the subject or certainly saw the change: then it is a deliberate move back.
    assert rules.classify("Mon", "Fri", "Fri", superseded=["Mon"], author_owns=True) == "update"
    assert rules.classify("Mon", "Fri", "Fri", superseded=["Mon"], author_knows_current=True) == "update"


@pytest.mark.parametrize("seed", [1, 2, 3])
def test_generated_orgs_are_well_formed(seed):
    ds = orgsim.generate(seed, 2)
    ids = [m["id"] for m in ds["messages"]]
    assert ids == sorted(ids) and len(set(ids)) == len(ids)
    assert [m["ts"] for m in ds["messages"]] == sorted(m["ts"] for m in ds["messages"])
    people = {p["id"]: p for p in ds["people"]}
    for m in ds["messages"]:
        obs = rules.observed_exposure(m, ds, people)
        # Only weak exposure can go unread; strong exposure (mentions, reactions, email) is always read.
        assert all(obs.get(p) == W for p in m["_truth"]["unread_by"])
        assert not set(m["reactions"]) & set(m["_truth"]["unread_by"])
        if m["thread"]:
            assert m["thread"] < m["id"]
    assert orgsim.generate(seed, 2)["messages"] == ds["messages"]      # deterministic


def test_twin_classifies_like_the_answer_key_on_northwind():
    ds = json.loads((DATA / "northwind.json").read_text(encoding="utf-8"))
    ref = Reference(ds).ingest_all()
    world = truth.simulate(ds, ds["end"])
    for m in ds["messages"]:
        for i, cl in enumerate(ref.claims[m["id"]]):
            assert world.kinds[(m["id"], i)] == cl["kind"], (m["id"], cl)


def test_learning_beats_v1_on_generated_orgs():
    """A small version of scripts/bench.py: feedback should cut false alarms without losing recall."""
    tp = {"v1": 0, "learned": 0}
    fp = {"v1": 0, "learned": 0}
    for seed in (11, 12, 13):
        ds = orgsim.generate(seed, 2)
        ref = Reference(ds).ingest_all()
        fb: list[Evidence] = []
        for cp in sorted({m["ts"][:10] + "T08:00:00Z" for m in ds["messages"]}):
            gt = truth.stale_report(ds, cp)
            world = truth.simulate(ds, cp)
            imp = [e for e in ref.evidence if e.ts <= cp]
            for name, model in (("v1", ReadModel(fixed=1.0)), ("learned", ReadModel(imp + fb))):
                for p in ds["people"]:
                    want = {x["slot"] for x in gt[p["id"]]}
                    items = ref.diff(p["id"], cp, model)
                    got = {x.slot for x in items}
                    tp[name] += len(want & got)
                    fp[name] += len(got - want)
                    if name == "learned" and p["kind"] == "person":
                        for it in items:
                            tb = world.beliefs.get(p["id"], {}).get(it.slot)
                            v = "neither" if tb is None else ("knew" if rules.same(tb.value, it.current) else "news")
                            fb += evidence_from_verdict(p["id"], v, it.current, it.believed,
                                                        ref.exposures(p["id"], cp, {it.slot}).get(it.slot, []), cp)
    assert fp["learned"] < 0.7 * fp["v1"]
    assert tp["learned"] >= 0.95 * tp["v1"]
