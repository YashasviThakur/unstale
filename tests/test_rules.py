"""Unit tests for the problem definition and the answer key. No database or LLM needed."""

from __future__ import annotations

import json

import pytest

from unstale import rules, truth
from unstale.config import DATA
from unstale.rules import STRONG, WEAK


@pytest.fixture(scope="module")
def ds():
    return json.loads((DATA / "northwind.json").read_text(encoding="utf-8"))


def test_classify():
    assert rules.classify("Fri", None, None) == "update"
    assert rules.classify("Fri", "Fri", None) == "restate"
    assert rules.classify("fri ", "Fri", "Mon") == "restate"
    # Author never saw the change and repeats what they believe: echo, not a new version.
    assert rules.classify("Mon", "Fri", "Mon") == "echo"
    # Author has seen the current value and says something else: a real change (e.g. a revert).
    assert rules.classify("Mon", "Fri", "Fri") == "update"
    # Author asserts a value nobody said before: a real change.
    assert rules.classify("Wed", "Fri", "Mon") == "update"


def test_newer_prefers_effective_time_over_seen_time():
    old_echo = rules.Belief("Mon", "2026-06-24T10:00:00Z", "m032", "2026-06-29T09:00:00Z")
    real = rules.Belief("Fri", "2026-06-26T15:20:00Z", "m026", "2026-06-26T15:20:00Z")
    # Someone who knew the real change is not overridden by a later echo of the old value.
    assert not rules.newer(old_echo, real)
    assert rules.newer(real, old_echo)


def test_exposure_respects_ooo_and_channels(ds):
    people = {p["id"]: p for p in ds["people"]}
    by_id = {m["id"]: m for m in ds["messages"]}
    exp = rules.observed_exposure(by_id["m036"], ds, people)  # Sara in #eng-payments while Arjun is out
    assert exp["person:sara"] == STRONG
    assert exp["person:dev"] == STRONG  # reacted
    assert "person:arjun" not in exp
    exp = rules.observed_exposure(by_id["m020"], ds, people)  # #pricing
    assert exp["person:priya"] == STRONG and "person:maya" not in exp
    exp = rules.observed_exposure(by_id["m005"], ds, people)  # agents read their whole channel
    assert exp["agent:support-bot"] == STRONG and exp["person:tom"] == WEAK


def test_scope(ds):
    sc = rules.scope("person:maya", ds["responsibility"], ds["links"])
    assert sc["customer:brightline"] == 0 and sc["feature:sso"] == 1 and sc["release:2.4"] == 1
    assert "service:payments" not in sc  # two links away


def test_answer_key_end(ds):
    report = truth.stale_report(ds, ds["end"])
    got = {pid: {x["slot"] for x in items} for pid, items in report.items()}
    assert got["person:maya"] == {"release:2.4|SHIPS_ON", "feature:sso|AVAILABLE_IN", "plan:team|PRICED_AT",
                                  "meeting:kestrel-qbr|SCHEDULED_FOR", "release:2.4|CODE_FREEZE"}
    assert got["agent:support-bot"] == {"plan:team|PRICED_AT", "api:payments-v1|STATUS",
                                        "policy:monthly-refunds|WINDOW"}
    assert got["person:sara"] == set() and got["person:lena"] == set()
    # Tom was told the new payments owner on 30 Jun, so he is no longer stale on it.
    assert "service:payments|OWNED_BY" not in got["person:tom"]
    assert sum(len(v) for v in got.values()) == 14


def test_echo_is_detected_in_truth(ds):
    world = truth.simulate(ds, ds["end"])
    assert world.kinds[("m032", 0)] == "echo" and world.kinds[("m032", 1)] == "echo"
    assert world.current["release:2.4|SHIPS_ON"][0] == "2026-07-03"
    # The deploy window went 16:00 -> 18:00 -> 16:00; the revert is an update.
    assert world.kinds[("m013", 0)] == "update"
    assert world.current["release:2.4|DEPLOY_WINDOW"][0] == "16:00 UTC"
