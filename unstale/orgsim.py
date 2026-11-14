"""Generated orgs for the benchmark, with reading you can't see.

Northwind is hand-written, small, and its answer key follows the same rules as
the engine. This generator answers the obvious objection: build many orgs at
random, let people read the way people do, and score the engine on what it can
*not* observe.

Each org gets 9-13 people and a support agent, 8 channels, and about 45
messages a week. Work runs in two-week sprints, and facts change the way they
do at a software company: a release date slips and sometimes comes back, a
feature moves to the next release, prices and refund windows change in
#pricing, an API is deprecated and later retired, an owner hands over before
leave and takes it back after, a QBR is moved.

Reading is latent. Every person has a hidden read rate for every channel they
are in (high for their own team's channel, lower for channels on the edge of
their job, and some people lurk). A channel message is read by each member
with that probability. Mentions, DMs, emails, threads you reply to, and
messages you react to are always read. The message records only what a Slack
export would show: author, channel, thread, mentions, recipients, reactions.
Who actually read it goes in the hidden ``_truth`` block, like Northwind's.

People talk about what they believe. When someone posts about a fact, the
generator replays the hidden truth to find what they believe at that moment
and has them say that, so stale people produce real echoes, and sometimes a
colleague who knows better corrects them in the thread.

    python -m unstale.orgsim 7            # writes data/generated/org-007.json (one sprint)
    python -m unstale.orgsim 7 --sprints 3
"""

from __future__ import annotations

import argparse
import heapq
import json
import random
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from . import rules, truth
from .config import DATA
from .scenario import ATTRIBUTES

OUT = DATA / "generated"
SPRINT_DAYS = 8          # working days per sprint (Mon of week 1 to Wed of week 2)

FIRST = ["Aisha", "Bruno", "Chen", "Dara", "Elif", "Farah", "Gus", "Hana", "Ivan", "Jade", "Kofi", "Lina",
         "Mateo", "Nadia", "Omar", "Pia", "Quinn", "Ravi", "Sofia", "Tariq", "Uma", "Viktor", "Wen", "Yara",
         "Zane", "Ines", "Joel", "Mira", "Nikhil", "Rosa"]
LAST = ["Abara", "Berg", "Costa", "Dube", "Engel", "Fong", "Garcia", "Haddad", "Iyer", "Jensen", "Kaur",
        "Lindqvist", "Moreau", "Nakamura", "Okafor", "Petrov", "Quist", "Rossi", "Silva", "Tanaka"]
FEATURES = ["SSO", "Audit log", "SCIM provisioning", "Usage alerts", "Bulk export", "Custom roles",
            "Data residency", "Offline mode", "Approval flows", "Sandbox environments", "Field-level permissions",
            "Scheduled reports"]
SERVICES = [("payments", "Payments service"), ("notifications", "Notifications service"),
            ("search", "Search service"), ("billing", "Billing service")]
CUSTOMERS = ["Brightline", "Kestrel Foods", "Halcyon Health", "Orbit Freight", "Juniper Bank", "Tidewater Labs",
             "Cobalt Retail", "Summit Legal"]
NOISE = ["Lunch at 12:30 anyone?", "Thanks all, good week.", "Can someone review my doc?", "Back in 10.",
         "Great demo today!", "Reminder: all-hands Thursday.", "Who has the meeting room booked?",
         "Coffee machine is fixed.", "Nice work on the launch prep.", "Out for an hour, ping me if urgent."]
REASONS = ["a blocker in QA", "the payments migration needs another pass", "load tests failed",
           "we found a data bug", "security review isn't done", "a dependency upgrade broke the build"]

# How closely each role reads each kind of channel (mean of the hidden read rate).
HOME = {
    "pm": {"general": 0.7, "release": 0.92, "pricing": 0.7, "sales": 0.45},
    "lead": {"general": 0.55, "release": 0.9, "eng": 0.95, "cs": 0.5},
    "eng": {"general": 0.5, "release": 0.8, "eng": 0.92, "cs": 0.4},
    "sre": {"general": 0.5, "release": 0.85, "eng": 0.6, "cs": 0.35},
    "ae": {"general": 0.6, "sales": 0.9, "pricing": 0.55, "cs": 0.5},
    "csm": {"general": 0.6, "sales": 0.8, "cs": 0.93, "support-kb": 0.85},
    "revops": {"general": 0.7, "sales": 0.75, "pricing": 0.95, "support-kb": 0.85},
}
ROLE_TITLE = {"pm": "Product manager", "lead": "Engineering lead", "eng": "Software engineer",
              "sre": "Site reliability engineer", "ae": "Account executive", "csm": "Customer success manager",
              "revops": "Revenue operations"}


def iso(d: datetime) -> str:
    return d.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def later_ts(ts: str, minutes: int) -> str:
    return iso(rules.parse_ts(ts) + timedelta(minutes=minutes))


def day_label(date_iso: str) -> str:
    d = datetime.fromisoformat(date_iso)
    return d.strftime("%a %d %b").replace(" 0", " ")


def weekday_on_or_after(d: datetime) -> datetime:
    while d.weekday() >= 5:
        d += timedelta(days=1)
    return d


def slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def kind_of(channel: str) -> str:
    if channel.startswith("eng-"):
        return "eng"
    if channel.startswith("cs-"):
        return "cs"
    return channel


def claim(subject: str, attribute: str, value: str) -> dict[str, str]:
    return {"subject": subject, "attribute": attribute, "value": value}


class Org:
    def __init__(self, seed: int, sprints: int = 1) -> None:
        assert 1 <= sprints <= 5
        self.seed, self.sprints = seed, sprints
        self.rng = random.Random(seed)
        self.start = datetime(2026, 9, 7, 8, 0, tzinfo=timezone.utc)   # a Monday
        days, d = [], self.start
        while len(days) < SPRINT_DAYS * sprints:
            if d.weekday() < 5 and not (len(days) % SPRINT_DAYS == 0 and d.weekday() != 0):
                days.append(d)
            d += timedelta(days=1)
        self.workdays = days
        self.messages: list[dict] = []
        self.heap: list[tuple[str, int, Callable[[str], None]]] = []
        self.tick = 0
        self.n_msgs = 0
        self._build()

    # ------------------------------------------------------------ structure
    def _build(self) -> None:
        r = self.rng
        counts = {"pm": r.choice([1, 2]), "lead": 1, "eng": r.choice([2, 3]), "sre": r.choice([0, 1]),
                  "ae": r.choice([2, 3]), "csm": r.choice([1, 2]), "revops": 1}
        firsts = r.sample(FIRST, sum(counts.values()))
        self.people: list[dict] = []
        self.by_role: dict[str, list[str]] = {}
        i = 0
        for role, n in counts.items():
            for _ in range(n):
                pid = f"person:{firsts[i].lower()}"
                self.people.append({"id": pid, "name": f"{firsts[i]} {r.choice(LAST)}", "role": ROLE_TITLE[role],
                                    "kind": "person", "_role": role})
                self.by_role.setdefault(role, []).append(pid)
                i += 1
        self.bot = "agent:support-bot"
        self.people.append({"id": self.bot, "name": "Support agent", "role": "AI agent answering customer questions",
                            "kind": "agent", "_role": "agent"})
        humans = [p["id"] for p in self.people if p["kind"] == "person"]
        R = self.by_role
        S = self.subj = {}

        def subject(sid: str, typ: str, name: str) -> str:
            S[sid] = {"id": sid, "type": typ, "name": name}
            return sid

        major, minor = r.randint(2, 7), r.randint(1, 6)
        self.versions = [f"{major}.{minor + k}" for k in range(self.sprints + 1)]
        self.rels = [subject(f"release:{v}", "Release", f"Release {v}") for v in self.versions]
        feats = r.sample(FEATURES, 2 * self.sprints + 1)
        self.feats = [subject(f"feature:{slug(f)}", "Feature", f) for f in feats]
        svcs = r.sample(SERVICES, r.choice([1, 2]))
        self.svcs = [subject(f"service:{s}", "Service", n) for s, n in svcs]
        self.apis = [subject(f"api:{s}-v1", "API", f"{n.split()[0]} API v1") for s, n in svcs]
        self.team = subject("plan:team", "Plan", "Team plan")
        self.business = subject("plan:business", "Plan", "Business plan")
        self.monthly = subject("policy:monthly-refunds", "Policy", "Monthly plan refunds")
        self.annual = subject("policy:annual-refunds", "Policy", "Annual plan refunds")
        custs = r.sample(CUSTOMERS, 3)
        self.custs = [subject(f"customer:{slug(c)}", "Customer", c) for c in custs]
        self.meetings = [subject(f"meeting:{slug(c)}-qbr", "Meeting", f"{c} QBR") for c in custs[:2]]

        links = []
        for k in range(self.sprints):
            links += [(self.feats[2 * k], "PART_OF", self.rels[k]), (self.feats[2 * k + 1], "PART_OF", self.rels[k])]
        links.append((self.feats[-1], "PART_OF", self.rels[-1]))
        links += [(rel, "DEPENDS_ON", self.svcs[0]) for rel in self.rels]
        links += [(api, "PART_OF", svc) for api, svc in zip(self.apis, self.svcs)]
        for k, c in enumerate(self.custs):
            links += [(c, "WANTS", self.feats[(k + j) % len(self.feats)]) for j in range(0, len(self.feats), 3)]
            links += [(c, "WAITING_ON", rel) for rel in self.rels]
            links.append((c, "USES", self.apis[k % len(self.apis)]))
        links += [(m, "FOR", c) for m, c in zip(self.meetings, self.custs)]
        self.links = list(dict.fromkeys(links))

        resp = []
        pms = R["pm"]
        resp += [(pms[k % len(pms)], "OWNS", rel) for k, rel in enumerate(self.rels)]
        resp += [(pms[k % len(pms)], "OWNS", f) for k, f in enumerate(self.feats)]
        lead = R["lead"][0]
        resp += [(lead, "OWNS", s) for s in self.svcs] + [(lead, "WORKS_ON", rel) for rel in self.rels]
        for e in R["eng"] + R.get("sre", []):
            resp += [(e, "WORKS_ON", rel) for rel in self.rels] + [(e, "WORKS_ON", r.choice(self.svcs))]
        self.cust_ae, self.cust_csm = {}, {}
        for k, c in enumerate(self.custs):
            ae, csm = R["ae"][k % len(R["ae"])], R["csm"][k % len(R["csm"])]
            self.cust_ae[c], self.cust_csm[c] = ae, csm
            resp += [(ae, "OWNS", c), (csm, "WORKS_ON", c)]
        for m, c in zip(self.meetings, self.custs):
            resp += [(self.cust_csm[c], "OWNS", m), (self.cust_ae[c], "ATTENDS", m)]
        resp += [(ae, "WORKS_ON", self.team) for ae in R["ae"]]
        for csm in R["csm"]:
            resp += [(csm, "WORKS_ON", self.team), (csm, "WORKS_ON", self.monthly)]
        rv = R["revops"][0]
        resp += [(rv, "OWNS", x) for x in (self.team, self.business, self.monthly, self.annual)]
        resp += [(self.bot, "WORKS_ON", x) for x in [self.team, self.business, self.monthly, self.annual] + self.apis]
        self.resp = list(dict.fromkeys(resp))

        ch: dict[str, list[str]] = {"general": list(humans)}
        ch["release"] = pms + [lead] + R["eng"] + R.get("sre", [])
        self.eng_ch = f"eng-{self.svcs[0].split(':')[1]}"
        ch[self.eng_ch] = [lead] + R["eng"] + R.get("sre", [])
        ch["sales"] = R["ae"] + R["csm"] + [rv] + ([pms[0]] if r.random() < 0.5 else [])
        ch["pricing"] = [rv, pms[0]] + ([R["ae"][0]] if r.random() < 0.4 else [])
        self.cs_ch = {}
        for c in self.custs[:2]:
            name = f"cs-{c.split(':')[1]}"
            self.cs_ch[c] = name
            ch[name] = [self.cust_csm[c], r.choice(R["eng"])] + ([self.cust_ae[c]] if r.random() < 0.5 else [])
        ch["support-kb"] = [rv] + R["csm"] + [self.bot]
        self.channels = {k: list(dict.fromkeys(v)) for k, v in ch.items()}

        # Hidden read rates.
        self.rates: dict[tuple[str, str], float] = {}
        for p in self.people:
            if p["kind"] == "agent":
                continue
            att = r.uniform(0.7, 1.05)
            for c, members in self.channels.items():
                if p["id"] not in members:
                    continue
                mean = HOME[p["_role"]].get(kind_of(c), 0.4)
                a = mean * 8
                rate = r.betavariate(a, 8 - a) * att
                if mean < 0.8 and r.random() < 0.25:
                    rate *= 0.3        # lurker: in the channel, rarely opens it
                self.rates[(p["id"], c)] = min(0.99, max(0.03, rate))

        # Leave: the lead hands over before going out in the first sprint and comes back in the next.
        wd = self.workdays
        self.lead_ooo = (r.choice([4, 5]), SPRINT_DAYS + 1 if self.sprints > 1 else len(wd))
        ooo = {lead: [[iso(wd[self.lead_ooo[0]].replace(hour=0)),
                       iso((wd[self.lead_ooo[1]] if self.lead_ooo[1] < len(wd) else wd[-1] + timedelta(days=3))
                           .replace(hour=0))]]}
        for k in range(self.sprints):
            if r.random() < 0.5:
                other = r.choice([h for h in humans if h != lead])
                d = k * SPRINT_DAYS + r.randint(2, 6)
                ooo.setdefault(other, []).append([iso(wd[d].replace(hour=0)),
                                                  iso(wd[min(d + r.choice([1, 2]), len(wd) - 1)].replace(hour=0))])
        for p in self.people:
            if p["id"] in ooo:
                p["ooo"] = ooo[p["id"]]

        self.ds = {"name": f"Generated org {self.seed:03d}", "start": iso(self.start),
                   "end": iso(wd[-1].replace(hour=17)), "people": self.people, "external": {},
                   "channels": self.channels, "subjects": list(S.values()),
                   "links": [list(x) for x in self.links], "responsibility": [list(x) for x in self.resp],
                   "attributes": ATTRIBUTES, "messages": self.messages, "drafts": [],
                   "sprints": [[iso(wd[k * SPRINT_DAYS]), iso(wd[(k + 1) * SPRINT_DAYS - 1].replace(hour=17))]
                               for k in range(self.sprints)],
                   "_hidden": {"read_rates": {f"{p}|{c}": round(v, 3) for (p, c), v in self.rates.items()},
                               "seed": self.seed}}

    # ------------------------------------------------------------- helpers
    def at(self, day: int, hour: float) -> datetime:
        d = self.workdays[min(day, len(self.workdays) - 1)]
        return d.replace(hour=int(hour), minute=int((hour % 1) * 60)) + timedelta(minutes=self.rng.randint(0, 9))

    def schedule(self, when: datetime | str, fn: Callable[[str], None]) -> None:
        ts = when if isinstance(when, str) else iso(when)
        self.tick += 1
        heapq.heappush(self.heap, (ts, self.tick, fn))

    def people_map(self) -> dict[str, dict]:
        return {p["id"]: p for p in self.people}

    def world(self, ts: str) -> truth.World:
        return truth.simulate(self.ds, ts)

    def ooo_at(self, pid: str, ts: str) -> bool:
        return rules.is_ooo(self.people_map().get(pid, {}), ts)

    def post(self, ts: str, author: str, text: str, *, channel: str | None = None, thread: str | None = None,
             kind: str = "slack", to: list[str] | None = None, mentions: list[str] | None = None,
             claims: list[dict] | None = None) -> dict:
        # Two messages never share a timestamp, so replay order is unambiguous.
        while any(m["ts"] == ts for m in self.messages):
            ts = iso(rules.parse_ts(ts) + timedelta(seconds=17))
        self.n_msgs += 1
        m = {"id": f"tmp-{self.n_msgs}", "ts": ts, "kind": kind, "channel": channel, "thread": thread,
             "author": author, "to": to or [], "cc": [], "subject_line": None, "text": text, "reactions": [],
             "mentions": mentions or [], "_truth": {"claims": claims or [], "unread_by": []}}
        obs = rules.observed_exposure(m, self.ds, self.people_map())
        unread, readers = [], []
        for pid, s in obs.items():
            if pid == author:
                continue
            if s == rules.WEAK and self.rng.random() > self.rates.get((pid, channel or ""), 0.5):
                unread.append(pid)
            else:
                readers.append(pid)
        react_p = 0.12 if claims else 0.05
        m["reactions"] = [p for p in readers if p != self.bot and self.rng.random() < react_p]
        m["_truth"]["unread_by"] = sorted(unread)
        self.messages.append(m)
        self.messages.sort(key=lambda x: x["ts"])
        return m

    def readers(self, m: dict) -> set[str]:
        return truth.true_exposure(m, self.ds, self.people_map()) | {m["author"]}

    # -------------------------------------------------------------- phrasing
    def say(self, attribute: str, subject: str, value: str, mode: str) -> str:
        name = self.subj[subject]["name"]
        if attribute in ("SHIPS_ON", "CODE_FREEZE", "RENEWAL_DATE"):
            v = day_label(value)
        elif attribute == "OWNED_BY":
            v = next(p["name"].split()[0] for p in self.people if p["id"] == value)
        elif attribute == "SCHEDULED_FOR":
            v = f"{day_label(value[:10])} at {value[11:16]} UTC"
        else:
            v = value
        lab = ATTRIBUTES[attribute]["label"]
        r = self.rng
        if mode == "update":
            why = f" ({r.choice(REASONS)})" if attribute in ("SHIPS_ON", "CODE_FREEZE", "AVAILABLE_IN") else ""
            return r.choice([f"Update: {name} {lab} is now {v}{why}.", f"Change of plan: {name} {lab} moves to {v}{why}.",
                             f"Heads up, {name} {lab} changed to {v}{why}."])
        if mode == "announce":
            return r.choice([f"For the record: {name} {lab} is {v}.", f"Plan: {name} {lab} is {v}.",
                             f"Confirming {name} {lab}: {v}."])
        if mode == "statement":
            return r.choice([f"Told the customer {name} {lab} is {v}.", f"Reminder that {name} {lab} is {v}.",
                             f"Going with {name} {lab} = {v} in my notes.", f"As far as I know {name} {lab} is {v}."])
        return r.choice([f"It's {v} now.", f"Small correction: {name} {lab} is {v} now.", f"That changed, it's {v}."])

    def fact(self, ts: str, author: str, subject: str, attribute: str, value: str, channel: str | None,
             mode: str, kind: str = "slack", to: list[str] | None = None, thread: str | None = None,
             mentions: list[str] | None = None) -> dict:
        return self.post(ts, author, self.say(attribute, subject, value, mode), channel=channel, kind=kind, to=to,
                         thread=thread, mentions=mentions, claims=[claim(subject, attribute, value)])

    # ---------------------------------------------------------------- events
    def change(self, day: int, author: str, subject: str, attribute: str, value: str | Callable[[], str | None],
               channel: str | None, cross: tuple[str, float] | None = None, kind: str = "slack",
               to: list[str] | None = None) -> None:
        r = self.rng

        def fire(ts: str) -> None:
            v = value() if callable(value) else value
            if v is None or self.ooo_at(author, ts):
                return
            self.fact(ts, author, subject, attribute, v, channel, "update", kind=kind, to=to)
            if cross and r.random() < cross[1]:
                self.schedule(later_ts(ts, r.randint(90, 60 * 22)), lambda t2: self.fact(
                    t2, author, subject, attribute, v, cross[0], "announce"))
        self.schedule(self.at(day, r.uniform(9.5, 16.5)), fire)

    def current(self, slot: str, ts: str | None = None) -> str | None:
        w = self.world(ts or self.ds["end"])
        cur = w.current.get(slot)
        return cur[0] if cur else None

    def plan_sprint(self, k: int) -> None:
        r, R, wd = self.rng, self.by_role, self.workdays
        base = k * SPRINT_DAYS
        pms, lead, rv = R["pm"], R["lead"][0], R["revops"][0]
        pm = pms[k % len(pms)]
        rel, nxt = self.rels[k], self.rels[k + 1]
        f1, f2 = self.feats[2 * k], self.feats[2 * k + 1]
        ship = wd[base + 6]
        ship_d, freeze_d = ship.date().isoformat(), (ship - timedelta(days=2)).date().isoformat()

        self.schedule(self.at(base, 9), lambda ts: self.post(
            ts, pm, f"Plan for the next two weeks: {self.subj[rel]['name']} ships {day_label(ship_d)}. "
                    f"Headliners are {self.subj[f1]['name']} and {self.subj[f2]['name']}.",
            channel="general", claims=[claim(rel, "SHIPS_ON", ship_d), claim(f1, "AVAILABLE_IN", self.versions[k]),
                                       claim(f2, "AVAILABLE_IN", self.versions[k])]))
        self.schedule(self.at(base, 9.5), lambda ts: self.post(
            ts, lead if not self.ooo_at(lead, ts) else pm,
            f"Code freeze for {self.versions[k]} is {day_label(freeze_d)}.", channel="release",
            claims=[claim(rel, "CODE_FREEZE", freeze_d)]))

        if k == 0:
            price = r.choice([29, 35, 39, 45])
            self.price = price
            self.schedule(self.at(0, 10), lambda ts: self.post(
                ts, rv, f"Price sheet this quarter: Team ${price}/seat/month, Business ${price + 30}/seat/month.",
                channel="sales", claims=[claim(self.team, "PRICED_AT", f"${price}/seat/month"),
                                         claim(self.business, "PRICED_AT", f"${price + 30}/seat/month")]))
            window = r.choice([30, 21])
            self.schedule(self.at(0, 10.5), lambda ts: self.post(
                ts, rv, f"Refunds: monthly plans {window} days, annual plans 30 days.", channel="support-kb",
                claims=[claim(self.monthly, "WINDOW", f"{window} days"), claim(self.annual, "WINDOW", "30 days")]))
            self.retries = r.choice([3, 4])
            for api, svc in zip(self.apis, self.svcs):
                self.schedule(self.at(0, 11), lambda ts, api=api, svc=svc: self.post(
                    ts, lead, f"{self.subj[api]['name']} is supported, webhook retries are {self.retries}, and I own "
                              f"{self.subj[svc]['name'].lower()}.", channel=self.eng_ch,
                    claims=[claim(api, "STATUS", "supported"), claim(svc, "WEBHOOK_RETRIES", str(self.retries)),
                            claim(svc, "OWNED_BY", lead)]))
            for c in self.custs:
                renew = (wd[-1] + timedelta(days=r.randint(20, 60))).date().isoformat()
                self.schedule(self.at(0, 14), lambda ts, c=c, renew=renew: self.fact(
                    ts, self.cust_ae[c], c, "RENEWAL_DATE", renew, "sales", "announce"))
        for m, c in zip(self.meetings, self.custs):
            when = self.at(base + r.randint(5, 7), r.choice([14, 15, 16])).strftime("%Y-%m-%d %H:%M UTC")
            self.schedule(self.at(base, 11.5), lambda ts, m=m, c=c, when=when: self.fact(
                ts, self.cust_csm[c], m, "SCHEDULED_FOR", when, None, "announce" if k == 0 else "update",
                kind="email", to=[self.cust_ae[c]]))

        # The ship date slips, the freeze follows, and sometimes the date comes back.
        slip = weekday_on_or_after(ship + timedelta(days=r.choice([2, 3, 4, 7])))
        d1 = base + r.randint(2, 4)
        self.change(d1, r.choice([pm, lead]), rel, "SHIPS_ON", slip.date().isoformat(), "release", ("sales", 0.3))
        if r.random() < 0.6:
            self.change(d1, lead, rel, "CODE_FREEZE", (slip - timedelta(days=2)).date().isoformat(), "release")
        if r.random() < 0.45:
            back = ship_d if r.random() < 0.4 else weekday_on_or_after(slip + timedelta(days=2)).date().isoformat()
            self.change(d1 + r.randint(2, 3), pm, rel, "SHIPS_ON", back, "release", ("general", 0.3))
        if r.random() < 0.75:
            self.change(base + r.randint(2, 5), pm, f2, "AVAILABLE_IN", self.versions[k + 1], "release", ("sales", 0.25))

        def bump(slot: str, fmt: Callable[[str], str | None]) -> Callable[[], str | None]:
            return lambda: fmt(self.current(slot) or "")

        if r.random() < (0.9 if k == 0 else 0.5):
            self.change(base + r.randint(2, 5), rv, self.team, "PRICED_AT",
                        bump("plan:team|PRICED_AT", lambda v: f"${int(re.sub(r'[^0-9]', '', v.split('/')[0]) or 39) + r.choice([4, 6, 10])}/seat/month"),
                        "pricing", ("sales", 0.4))
        if r.random() < (0.7 if k == 0 else 0.4):
            self.change(base + r.randint(4, 7), rv, self.monthly, "WINDOW",
                        bump("policy:monthly-refunds|WINDOW", lambda v: r.choice([x for x in ["14 days", "7 days", "30 days"] if x != v])),
                        "pricing", ("support-kb", 0.35))
        api = self.apis[0]
        status_next = {"supported": "deprecated", "deprecated": "retired"}
        if r.random() < 0.7:
            self.change(base + r.randint(2, 6), lead, api, "STATUS",
                        bump(f"{api}|STATUS", lambda v: status_next.get(v)), self.eng_ch, ("release", 0.3))
        if k == 0 and r.random() < 0.8:
            self.heir = r.choice(R["eng"])
            self.change(self.lead_ooo[0] - 1, lead, self.svcs[0], "OWNED_BY", self.heir, self.eng_ch)
        if k == 1 and getattr(self, "heir", None):
            self.change(self.lead_ooo[1] + 1, lead, self.svcs[0], "OWNED_BY", lead, self.eng_ch, ("release", 0.3))
        if r.random() < 0.45:
            self.change(base + r.randint(3, 6), lead if k else lead, self.svcs[0], "WEBHOOK_RETRIES",
                        bump(f"{self.svcs[0]}|WEBHOOK_RETRIES", lambda v: str(int(v or 3) + r.choice([1, 2]))),
                        self.eng_ch)
        for m, c in zip(self.meetings, self.custs):
            if r.random() < 0.65:
                def moved(m: str = m) -> str | None:
                    cur = self.current(f"{m}|SCHEDULED_FOR")
                    if not cur:
                        return None
                    d = datetime.strptime(cur, "%Y-%m-%d %H:%M UTC").replace(tzinfo=timezone.utc)
                    return weekday_on_or_after(d + timedelta(days=r.choice([1, 2]), hours=r.choice([-1, 1]))) \
                        .strftime("%Y-%m-%d %H:%M UTC")
                if r.random() < 0.35:
                    self.change(base + r.randint(2, 4), self.cust_csm[c], m, "SCHEDULED_FOR", moved, None,
                                kind="email", to=[self.cust_ae[c]])
                else:
                    self.change(base + r.randint(2, 4), self.cust_csm[c], m, "SCHEDULED_FOR", moved, self.cs_ch[c])
        if r.random() < 0.45:
            c = r.choice(self.custs)
            self.change(base + r.randint(4, 7), self.cust_ae[c], c, "RENEWAL_DATE",
                        bump(f"{c}|RENEWAL_DATE", lambda v: (datetime.fromisoformat(v) + timedelta(days=r.choice([14, 30])))
                             .date().isoformat() if v else None), self.cs_ch.get(c, "sales"))

        for day in range(base + 1, base + SPRINT_DAYS):
            for _ in range(r.randint(3, 5)):
                self.schedule(self.at(day, r.uniform(9, 17)), self.statement)
            for _ in range(r.randint(1, 2)):
                self.schedule(self.at(day, r.uniform(9, 17)), self.question)
            for _ in range(r.randint(3, 5)):
                self.schedule(self.at(day, r.uniform(9, 17.5)), self.noise)

    # ------------------------------------------------------ people talking
    def _home_channels(self, pid: str) -> list[str]:
        return [c for c, ms in self.channels.items() if pid in ms and c != "general"] or ["general"]

    def _topic(self, pid: str, w: truth.World) -> tuple[str, str] | None:
        sc = rules.scope(pid, self.ds["responsibility"], self.ds["links"])
        mine = w.beliefs.get(pid, {})
        slots = [k for k in mine if k.split("|", 1)[0] in sc and k in w.current]
        if not slots:
            return None
        s, a = self.rng.choice(sorted(slots)).split("|", 1)
        return s, a

    def _available(self, ts: str) -> list[str]:
        return [p["id"] for p in self.people if p["kind"] == "person" and not self.ooo_at(p["id"], ts)]

    def statement(self, ts: str) -> None:
        r = self.rng
        pid = r.choice(self._available(ts))
        w = self.world(ts)
        topic = self._topic(pid, w)
        if not topic:
            return
        subject, attribute = topic
        key = rules.slot_key(subject, attribute)
        believed = w.beliefs[pid][key].value
        channel = r.choice(self._home_channels(pid))
        m = self.fact(ts, pid, subject, attribute, believed, channel, "statement")
        if rules.same(believed, w.current[key][0]) or r.random() > 0.55:
            return

        def correct(t2: str) -> None:
            # Someone who read it and knows better corrects them in the thread.
            w2 = self.world(t2)
            cur = w2.current[key][0]
            fixers = [p for p in self.readers(m) if p not in (pid, self.bot) and not self.ooo_at(p, t2)
                      and key in w2.beliefs.get(p, {}) and rules.same(w2.beliefs[p][key].value, cur)]
            if fixers:
                self.fact(t2, r.choice(sorted(fixers)), subject, attribute, cur, channel, "correction",
                          thread=m["id"], mentions=[pid])
        self.schedule(later_ts(ts, r.randint(8, 70)), correct)

    def question(self, ts: str) -> None:
        r = self.rng
        pid = r.choice(self._available(ts))
        w = self.world(ts)
        topic = self._topic(pid, w)
        if not topic:
            return
        subject, attribute = topic
        key = rules.slot_key(subject, attribute)
        channel = r.choice(self._home_channels(pid))
        lab = ATTRIBUTES[attribute]["label"]
        q = self.post(ts, pid, f"Quick check: what's the latest on {self.subj[subject]['name']} {lab}?", channel=channel)
        owners = [p for p, _, s in self.resp if s == subject and p in self.channels.get(channel, []) and p != pid
                  and p != self.bot]

        def answer(t2: str) -> None:
            w2 = self.world(t2)
            avail = [o for o in owners if not self.ooo_at(o, t2) and key in w2.beliefs.get(o, {})]
            if avail:
                who = r.choice(sorted(avail))
                self.fact(t2, who, subject, attribute, w2.beliefs[who][key].value, channel, "announce",
                          thread=q["id"], mentions=[pid])
        if owners:
            self.schedule(later_ts(ts, r.randint(5, 50)), answer)

    def noise(self, ts: str) -> None:
        r = self.rng
        pid = r.choice(self._available(ts))
        self.post(ts, pid, r.choice(NOISE), channel=r.choice(self._home_channels(pid) + ["general"]))

    # ------------------------------------------------------------------ run
    def run(self) -> dict[str, Any]:
        for k in range(self.sprints):
            self.plan_sprint(k)
        end = self.ds["end"]
        while self.heap:
            ts, _, fn = heapq.heappop(self.heap)
            if ts <= end:
                fn(ts)
        self.messages.sort(key=lambda m: m["ts"])
        new_id = {m["id"]: f"m{i + 1:03d}" for i, m in enumerate(self.messages)}
        for m in self.messages:
            m["id"] = new_id[m["id"]]
            if m["thread"]:
                m["thread"] = new_id[m["thread"]]
        for p in self.people:
            p.pop("_role", None)
        return self.ds


def generate(seed: int, sprints: int = 1) -> dict[str, Any]:
    return Org(seed, sprints).run()


def write(seed: int, sprints: int = 1) -> str:
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"org-{seed:03d}{'' if sprints == 1 else f'-x{sprints}'}.json"
    path.write_text(json.dumps(generate(seed, sprints), indent=1), encoding="utf-8")
    return str(path)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("seeds", nargs="*", type=int, default=[1])
    ap.add_argument("--sprints", type=int, default=1)
    a = ap.parse_args()
    for s in a.seeds:
        print(write(s, a.sprints))
