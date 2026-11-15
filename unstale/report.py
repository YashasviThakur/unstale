"""The stale-belief report: what a RevOps or support lead gets when Unstale reads a team's history.

It replays every morning of the dataset (the same briefs people would have received), and turns the result into
the numbers a manager buys: how many person-days people spent working from an outdated fact, which channels
changes leak out of, who lags, and how long a change takes to reach the people who needed it. Everything is
computed by the engine's own traversals; the report adds only counting.
"""

from __future__ import annotations

import re
import statistics
from collections import defaultdict
from typing import Any, Callable

from . import rules
from .exposure import ReadModel
from .timeline import checkpoints


async def build(eng, ds: dict, *, show: Callable[[str, str], str], label: Callable[[str], str],
                name: Callable[[str], str], where: Callable[[dict], str]) -> dict[str, Any]:
    cps = checkpoints(ds)
    people = ds["people"]
    prev = rules.parse_ts(ds["start"])
    changes: dict[tuple[str, str], dict] = {}        # (slot, changed_at) -> record
    per_person: dict[str, dict[tuple[str, str], dict]] = defaultdict(dict)   # person -> change -> {days, first, last_i}
    simult: dict[tuple[str, str], dict[int, int]] = defaultdict(lambda: defaultdict(int))
    total_days = 0.0
    versions = {s["id"]: await eng.subject_versions(s["id"]) for s in ds["subjects"]}
    evidence = await eng.load_evidence() if eng.mode not in ("v1", "strong") else None   # read once, not once per morning

    for i, cp in enumerate(cps):
        t = rules.parse_ts(cp)
        w = min(1.0, (t - prev).total_seconds() / 86400)
        prev = t
        model = ReadModel([e for e in evidence if rules.parse_ts(e.ts) <= t]) if evidence is not None else await eng.read_model(cp)
        for p in people:
            for it in await eng.diff(p["id"], cp, model=model):
                key = (it.slot, it.changed_at)
                if key not in changes:
                    vs = versions.get(it.subject, {}).get(it.attribute, [])
                    before = [v for v in vs if rules.parse_ts(v.since) < rules.parse_ts(it.changed_at)]
                    m = eng._messages.get(it.current_from or "", {})
                    changes[key] = {"slot": it.slot, "subject": it.subject_name, "label": label(it.attribute),
                                    "old": show(it.attribute, before[-1].value) if before else None,
                                    "new": show(it.attribute, it.current), "changed_at": it.changed_at,
                                    "where": where(m) if m else None, "by": name(m["author"]) if m else None,
                                    "channel": m.get("channel") if m else None}
                rec = per_person[p["id"]].setdefault(key, {"days": 0.0, "first_i": i, "last_i": i})
                rec["days"] += w
                rec["last_i"] = i
                simult[key][i] += 1
                total_days += w

    last_i = len(cps) - 1
    end_t = rules.parse_ts(cps[-1])
    # every change in the dataset, for the share of changes that leak out of each channel
    posted: dict[str, int] = defaultdict(int)
    for s in ds["subjects"]:
        for attr, vs in versions[s["id"]].items():
            for v in vs[1:]:
                m = eng._messages.get(v.message or "", {})
                posted[where(m) if m else "unknown"] += 1

    rows, hours_to_know, unresolved = [], [], 0
    for key, c in changes.items():
        who = [(pid, recs[key]) for pid, recs in per_person.items() if key in recs]
        still = [pid for pid, r in who if r["last_i"] == last_i]
        for pid, r in who:
            if r["last_i"] != last_i:
                nxt = rules.parse_ts(cps[r["last_i"] + 1])
                hours_to_know.append((nxt - rules.parse_ts(c["changed_at"])).total_seconds() / 3600)
        unresolved += len(still)
        rows.append({**c, "stale_person_days": round(sum(r["days"] for _, r in who), 1),
                     "people": [name(pid) for pid, _ in who], "peak": max(simult[key].values()),
                     "still_stale": [name(pid) for pid in still]})
    rows.sort(key=lambda r: -r["stale_person_days"])

    by_channel: dict[str, dict] = {}
    for r in rows:
        ch = r["where"] or "unknown"
        c = by_channel.setdefault(ch, {"where": ch, "changes_missed": 0, "stale_person_days": 0.0, "people": set()})
        c["changes_missed"] += 1
        c["stale_person_days"] += r["stale_person_days"]
        c["people"].update(r["people"])
    channels = [{"where": c["where"], "changes_posted": posted.get(c["where"], c["changes_missed"]),
                 "changes_missed": c["changes_missed"], "people_missed": len(c["people"]),
                 "stale_person_days": round(c["stale_person_days"], 1)} for c in by_channel.values()]
    for c in channels:
        c["leak_rate"] = round(c["changes_missed"] / max(c["changes_posted"], 1), 2)
    channels.sort(key=lambda c: -c["stale_person_days"])

    ppl = []
    for p in people:
        recs = per_person.get(p["id"], {})
        ppl.append({"person": p["id"], "name": p["name"], "role": p["role"], "kind": p["kind"],
                    "stale_person_days": round(sum(r["days"] for r in recs.values()), 1), "beliefs": len(recs),
                    "still_stale": sum(1 for r in recs.values() if r["last_i"] == last_i),
                    "longest_days": round(max((r["days"] for r in recs.values()), default=0.0), 1)})
    ppl.sort(key=lambda x: -x["stale_person_days"])

    n_days = (end_t - rules.parse_ts(ds["start"])).total_seconds() / 86400
    affected = [x for x in ppl if x["beliefs"]]
    n_changes = sum(posted.values())
    return {
        "name": ds["name"], "start": ds["start"], "end": ds["end"], "days": round(n_days, 1),
        "mornings": len(cps), "people": len(people),
        "headline": {
            "stale_person_days": round(total_days, 1), "changes": n_changes, "changes_missed": len(rows),
            "people_affected": len(affected), "agents_affected": sum(1 for x in affected if x["kind"] == "agent"),
            "still_stale_at_end": unresolved,
            "median_hours_to_know": round(statistics.median(hours_to_know), 1) if len(hours_to_know) >= 5 else None,
            "resolved_beliefs": len(hours_to_know)},
        "changes": rows, "channels": channels, "people_rows": ppl,
    }


def day(ts: str) -> str:
    t = rules.parse_ts(ts)
    return f"{t:%a} {t.day} {t:%b}"


def nice(v: str, pretty: Callable[[str], str]) -> str:
    """2026-06-30 10:00 UTC -> Tue 30 Jun, 10:00 UTC; dates and other values go through ``pretty``."""
    m = re.fullmatch(r"(\d{4}-\d{2}-\d{2}) (\d{2}:\d{2}) UTC", v or "")
    return f"{pretty(m.group(1))}, {m.group(2)} UTC" if m else pretty(v or "")


def markdown(r: dict, pretty: Callable[[str], str] = lambda x: x) -> str:
    """The same report as a document a RevOps lead can forward."""
    h = r["headline"]
    corrected = h["resolved_beliefs"]
    out = [f"# Stale-belief report: {r['name']}", "",
           f"{day(r['start'])} to {day(r['end'])} ({r['days']} days, {r['mornings']} mornings replayed, {r['people']} people and agents).", "",
           f"**{h['people_affected']} of {r['people']} people and agents worked from an outdated fact at some point**, "
           f"for **{h['stale_person_days']} stale person-days** in total. {h['changes_missed']} of the {h['changes']} changes made "
           f"in this period were missed by someone. Only {corrected} of the {corrected + h['still_stale_at_end']} "
           f"outdated beliefs {'was' if corrected == 1 else 'were'} corrected on its own; {h['still_stale_at_end']} "
           f"{'was' if h['still_stale_at_end'] == 1 else 'were'} still held at the end"
           + (f". Those that were corrected took a median of {h['median_hours_to_know']} hours." if h["median_hours_to_know"] is not None else "."), "",
           "## Changes that were missed, most costly first", "",
           "| Change | Posted in | By | Old → new | Stale person-days | Who was behind |", "|---|---|---|---|---|---|"]
    for c in r["changes"]:
        out.append(f"| {c['subject']}: {c['label']} | {c['where'] or ''} | {c['by'] or ''} | "
                   f"{nice(c['old'] or '', pretty)} → {nice(c['new'], pretty)} | {c['stale_person_days']} | {', '.join(c['people'])} |")
    out += ["", "## Where changes leak out", "", "| Posted in | Changes posted | Missed by someone | Leak rate | People who missed one | Stale person-days |",
            "|---|---|---|---|---|---|"]
    for c in r["channels"]:
        out.append(f"| {c['where']} | {c['changes_posted']} | {c['changes_missed']} | {round(c['leak_rate'] * 100)}% | "
                   f"{c['people_missed']} | {c['stale_person_days']} |")
    out += ["", "## Who lags", "", "| Person | Role | Stale person-days | Outdated beliefs | Still stale at the end | Longest |",
            "|---|---|---|---|---|---|"]
    for p in r["people_rows"]:
        out.append(f"| {p['name']} | {p['role']} | {p['stale_person_days']} | {p['beliefs']} | {p['still_stale']} | {p['longest_days']} days |")
    out += ["", "A stale person-day is one person holding one outdated fact for one day, as the morning brief would have shown it "
            "(a fact is counted when Unstale is at least 50% sure). Estimated, not observed: Slack does not say who read a message, "
            "so each count carries the same confidence the brief does.", ""]
    return "\n".join(out)
