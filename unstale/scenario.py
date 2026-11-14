"""Northwind Labs: a fictional 8-member team (7 people + 1 AI agent) over 8 working days.

Every message is hand-written so the answer key is exact. Each message carries
two kinds of fields:

* public fields (author, channel, recipients, reactions, mentions, text), which
  is all the engine is allowed to read;
* a private ``_truth`` block holding the annotated claims and the members who
  never actually read it. Only the ground-truth simulator and the
  ``--oracle-claims`` ablation read ``_truth``.

Run ``python -m unstale.scenario`` to write ``data/northwind.json``.
"""

from __future__ import annotations

import json
from typing import Any

from .config import DATA

YEAR = 2026
START = "2026-06-22T08:00:00Z"
END = "2026-07-01T17:00:00Z"


def t(stamp: str) -> str:
    """'06-22 09:05' -> '2026-06-22T09:05:00Z'."""
    day, clock = stamp.split()
    return f"{YEAR}-{day}T{clock}:00Z"


PEOPLE = [
    {"id": "person:priya", "name": "Priya Raman", "role": "Product manager", "kind": "person"},
    {"id": "person:arjun", "name": "Arjun Mehta", "role": "Payments engineering lead", "kind": "person",
     "ooo": [["2026-06-29T00:00:00Z", "2026-07-04T00:00:00Z"]]},
    {"id": "person:sara", "name": "Sara Kim", "role": "Backend engineer", "kind": "person"},
    {"id": "person:dev", "name": "Dev Patel", "role": "Site reliability engineer", "kind": "person"},
    {"id": "person:maya", "name": "Maya Lopez", "role": "Account executive", "kind": "person"},
    {"id": "person:tom", "name": "Tom Becker", "role": "Customer success manager", "kind": "person"},
    {"id": "person:lena", "name": "Lena Fischer", "role": "Revenue operations", "kind": "person"},
    {"id": "agent:support-bot", "name": "Support agent", "role": "AI agent answering customer questions",
     "kind": "agent"},
]

EXTERNAL = {
    "ext:hannah": "Hannah (Kestrel Foods)",
    "ext:jordan": "Jordan (Brightline)",
}

CHANNELS = {
    "general": ["person:priya", "person:arjun", "person:sara", "person:dev", "person:maya", "person:tom",
                "person:lena"],
    "release": ["person:priya", "person:arjun", "person:sara", "person:dev"],
    "eng-payments": ["person:arjun", "person:sara", "person:dev"],
    "sales": ["person:maya", "person:tom", "person:lena", "person:priya"],
    "pricing": ["person:lena", "person:priya"],
    "cs-kestrel": ["person:tom", "person:arjun", "person:sara"],
    "support-kb": ["person:lena", "person:tom", "agent:support-bot"],
}

SUBJECTS = [
    {"id": "release:2.4", "type": "Release", "name": "Release 2.4"},
    {"id": "feature:sso", "type": "Feature", "name": "SSO"},
    {"id": "service:payments", "type": "Service", "name": "Payments service"},
    {"id": "api:payments-v1", "type": "API", "name": "Payments API v1"},
    {"id": "plan:team", "type": "Plan", "name": "Team plan"},
    {"id": "plan:business", "type": "Plan", "name": "Business plan"},
    {"id": "policy:monthly-refunds", "type": "Policy", "name": "Monthly plan refunds"},
    {"id": "policy:annual-refunds", "type": "Policy", "name": "Annual plan refunds"},
    {"id": "customer:brightline", "type": "Customer", "name": "Brightline"},
    {"id": "customer:kestrel", "type": "Customer", "name": "Kestrel Foods"},
    {"id": "meeting:kestrel-qbr", "type": "Meeting", "name": "Kestrel QBR"},
]

# Structural links between subjects (from a CRM / issue tracker in a real deployment).
LINKS = [
    ("feature:sso", "PART_OF", "release:2.4"),
    ("release:2.4", "DEPENDS_ON", "service:payments"),
    ("api:payments-v1", "PART_OF", "service:payments"),
    ("customer:brightline", "WANTS", "feature:sso"),
    ("customer:brightline", "WAITING_ON", "release:2.4"),
    ("customer:kestrel", "USES", "service:payments"),
    ("customer:kestrel", "USES", "api:payments-v1"),
    ("meeting:kestrel-qbr", "FOR", "customer:kestrel"),
]

# Who is responsible for what (from an HR / ownership directory).
RESPONSIBILITY = [
    ("person:priya", "OWNS", "release:2.4"),
    ("person:priya", "OWNS", "feature:sso"),
    ("person:arjun", "OWNS", "service:payments"),
    ("person:arjun", "WORKS_ON", "release:2.4"),
    ("person:sara", "WORKS_ON", "service:payments"),
    ("person:sara", "WORKS_ON", "release:2.4"),
    ("person:dev", "WORKS_ON", "release:2.4"),
    ("person:maya", "OWNS", "customer:brightline"),
    ("person:maya", "WORKS_ON", "plan:team"),
    ("person:maya", "ATTENDS", "meeting:kestrel-qbr"),
    ("person:tom", "OWNS", "customer:kestrel"),
    ("person:tom", "OWNS", "meeting:kestrel-qbr"),
    ("person:tom", "WORKS_ON", "plan:team"),
    ("person:tom", "WORKS_ON", "policy:monthly-refunds"),
    ("person:lena", "OWNS", "plan:team"),
    ("person:lena", "OWNS", "plan:business"),
    ("person:lena", "OWNS", "policy:monthly-refunds"),
    ("person:lena", "OWNS", "policy:annual-refunds"),
    ("agent:support-bot", "WORKS_ON", "plan:team"),
    ("agent:support-bot", "WORKS_ON", "policy:monthly-refunds"),
    ("agent:support-bot", "WORKS_ON", "api:payments-v1"),
]

# The fact vocabulary. Extraction is shown this list, so every message maps onto
# the same few attribute names instead of inventing new ones per message.
ATTRIBUTES = {
    "SHIPS_ON": {"label": "ship date", "on": ["Release"], "format": "date YYYY-MM-DD",
                 "desc": "the day the release goes live in production ('ships', 'goes live', 'deploys', "
                         "'2.4 is Friday')"},
    "CODE_FREEZE": {"label": "code freeze", "on": ["Release"], "format": "date YYYY-MM-DD",
                    "desc": "the last day code can merge before the release; only messages about the 'freeze'"},
    "DEPLOY_WINDOW": {"label": "deploy window", "on": ["Release"], "format": "HH:MM UTC",
                      "desc": "the time of day the release deploys"},
    "AVAILABLE_IN": {"label": "target release", "on": ["Feature"], "format": "release version, e.g. 2.4",
                     "desc": "which release a feature ships in; a feature named as part or a headliner of a "
                             "release counts"},
    "OWNED_BY": {"label": "owner", "on": ["Service", "Feature", "Customer"], "format": "person id, e.g. person:sara",
                 "desc": "who is responsible right now; 'questions come to me' or 'X owns it' counts"},
    "WEBHOOK_RETRIES": {"label": "webhook retries", "on": ["Service"], "format": "integer",
                        "desc": "how many delivery attempts webhooks get"},
    "STATUS": {"label": "status", "on": ["API"], "format": "one of: supported, deprecated, retired",
               "desc": "whether customers should build on the API"},
    "PRICED_AT": {"label": "price", "on": ["Plan"], "format": "$N/seat/month", "desc": "the plan's price"},
    "WINDOW": {"label": "refund window", "on": ["Policy"], "format": "N days", "desc": "the refund window"},
    "CONTRACT_START": {"label": "contract start", "on": ["Customer"], "format": "date YYYY-MM-DD", "desc": "when the customer's contract starts"},
    "RENEWAL_DATE": {"label": "renewal date", "on": ["Customer"], "format": "date YYYY-MM-DD", "desc": "when the customer renews"},
    "SCHEDULED_FOR": {"label": "meeting time", "on": ["Meeting"], "format": "YYYY-MM-DD HH:MM UTC", "desc": "when the meeting happens"},
}


def c(subject: str, attribute: str, value: str) -> dict[str, str]:
    return {"subject": subject, "attribute": attribute, "value": value}


def msg(mid: str, when: str, author: str, text: str, *, channel: str | None = None, thread: str | None = None,
        to: list[str] | None = None, cc: list[str] | None = None, kind: str = "slack",
        subject_line: str | None = None, reactions: list[str] | None = None, mentions: list[str] | None = None,
        claims: list[dict] | None = None, unread_by: list[str] | None = None) -> dict[str, Any]:
    return {
        "id": mid,
        "ts": t(when),
        "kind": kind,
        "channel": channel,
        "thread": thread,
        "author": author,
        "to": to or [],
        "cc": cc or [],
        "subject_line": subject_line,
        "text": text,
        "reactions": reactions or [],
        "mentions": mentions or [],
        "_truth": {"claims": claims or [], "unread_by": unread_by or []},
    }


P = {p["id"].split(":", 1)[1]: p["id"] for p in PEOPLE}
priya, arjun, sara, dev, maya, tom, lena, bot = (P[k] for k in
                                                 ["priya", "arjun", "sara", "dev", "maya", "tom", "lena",
                                                  "support-bot"])

MESSAGES = [
    # Mon 22 Jun
    msg("m001", "06-22 09:05", priya, "Morning all! Plan for the next two weeks: 2.4 ships Monday June 29. "
        "Headliners are SSO and the new invoices page.", channel="general",
        reactions=[maya, tom, dev],
        claims=[c("release:2.4", "SHIPS_ON", "2026-06-29"), c("feature:sso", "AVAILABLE_IN", "2.4")],
        unread_by=[lena]),
    msg("m002", "06-22 09:12", arjun, "Reminder that payments questions (webhooks, invoices, the v2 migration) "
        "come to me.", channel="general",
        claims=[c("service:payments", "OWNED_BY", "person:arjun")]),
    msg("m003", "06-22 09:30", dev, "Release train for 2.4 is booked. Deploy window is 16:00 UTC and code "
        "freeze is Thursday June 25, end of day.", channel="release", reactions=[priya, sara],
        claims=[c("release:2.4", "DEPLOY_WINDOW", "16:00 UTC"), c("release:2.4", "CODE_FREEZE", "2026-06-25")]),
    msg("m004", "06-22 10:00", lena, "Q3 renewal refresher: the Team plan stays at $39/seat/month. Business is "
        "unchanged at $79/seat/month.", channel="sales", reactions=[tom],
        claims=[c("plan:team", "PRICED_AT", "$39/seat/month"), c("plan:business", "PRICED_AT", "$79/seat/month")]),
    msg("m005", "06-22 10:20", lena, "Knowledge base update for the support agent: Team plan is $39/seat/month. "
        "Monthly plans get a full refund within 30 days. Payments API v1 is the supported API for "
        "integrations.", channel="support-kb",
        claims=[c("plan:team", "PRICED_AT", "$39/seat/month"), c("policy:monthly-refunds", "WINDOW", "30 days"),
                c("api:payments-v1", "STATUS", "supported")]),
    msg("m006", "06-22 11:00", arjun, "Webhook retries on the payments service are set to 3 attempts with "
        "exponential backoff.", channel="eng-payments", reactions=[sara],
        claims=[c("service:payments", "WEBHOOK_RETRIES", "3")]),
    msg("m007", "06-22 13:15", maya, "Brightline signed! Contract starts July 1. They mostly care about SSO.",
        channel="sales", reactions=[tom, lena, priya],
        claims=[c("customer:brightline", "CONTRACT_START", "2026-07-01")]),
    msg("m008", "06-22 15:40", tom, "Anyone up for lunch tomorrow? There's a new ramen place on 3rd.",
        channel="general"),

    # Tue 23 Jun
    msg("m009", "06-23 08:30", tom, "Hi Hannah, confirming our QBR on Tuesday June 30 at 10:00 UTC. Maya and I "
        "will both join.", kind="email", subject_line="Kestrel QBR", to=["ext:hannah"], cc=[maya],
        claims=[c("meeting:kestrel-qbr", "SCHEDULED_FOR", "2026-06-30 10:00 UTC")]),
    msg("m010", "06-23 09:10", dev, "Freeze moves to Friday June 26, end of day, so the invoices work can land.",
        channel="release", reactions=[priya, sara, arjun],
        claims=[c("release:2.4", "CODE_FREEZE", "2026-06-26")]),
    msg("m011", "06-23 09:25", sara, "Can we push the deploy window to 18:00 UTC? The migration dry run takes "
        "two hours.", channel="release"),
    msg("m012", "06-23 09:40", dev, "Done, deploy window is now 18:00 UTC.", channel="release", thread="m011",
        claims=[c("release:2.4", "DEPLOY_WINDOW", "18:00 UTC")]),
    msg("m013", "06-23 11:05", dev, "Scratch that. Ops review says 18:00 overlaps the EU support handover, so "
        "we're back to 16:00 UTC and the dry run starts earlier instead.", channel="release", thread="m011",
        reactions=[sara, priya],
        claims=[c("release:2.4", "DEPLOY_WINDOW", "16:00 UTC")]),
    msg("m014", "06-23 12:00", tom, "FYI for anyone touching the Kestrel account: they run their webhooks on "
        "payments API v1.", channel="cs-kestrel"),
    msg("m015", "06-23 14:30", sara, "Is the freeze still Thursday?", channel="general"),
    msg("m016", "06-23 14:35", dev, "Friday now, see #release.", channel="general", thread="m015",
        claims=[c("release:2.4", "CODE_FREEZE", "2026-06-26")]),

    # Wed 24 Jun
    msg("m017", "06-24 10:00", priya, "Reminder: 2.4 deploys Monday June 29. Please get your PRs reviewed by "
        "Friday.", channel="release", reactions=[sara],
        claims=[c("release:2.4", "SHIPS_ON", "2026-06-29")]),
    msg("m018", "06-24 11:20", maya, "Hi Jordan, great news: SSO lands in 2.4 on Monday June 29, so your team "
        "can switch it on from day one.", kind="email", subject_line="SSO timing", to=["ext:jordan"],
        claims=[c("feature:sso", "AVAILABLE_IN", "2.4"), c("release:2.4", "SHIPS_ON", "2026-06-29")]),
    msg("m019", "06-24 15:00", sara, "Staging migration hit a deadlock on the invoices table. Investigating.",
        channel="eng-payments"),

    # Thu 25 Jun
    msg("m020", "06-25 09:00", lena, "Leadership signed off: the Team plan goes to $49/seat/month for all "
        "renewals from July 1. Existing contracts keep their price until renewal.", channel="pricing",
        reactions=[priya],
        claims=[c("plan:team", "PRICED_AT", "$49/seat/month")]),
    msg("m021", "06-25 09:20", priya, "Makes sense. Are you telling sales?", channel="pricing", thread="m020"),
    msg("m022", "06-25 09:22", lena, "Will do in the next sales sync.", channel="pricing", thread="m020"),
    msg("m023", "06-25 16:00", maya, "Kestrel renewal is July 15, Tom is driving it.", channel="general",
        claims=[c("customer:kestrel", "RENEWAL_DATE", "2026-07-15"), c("customer:kestrel", "OWNED_BY", "person:tom")]),

    # Fri 26 Jun
    msg("m024", "06-26 10:30", arjun, "I'm out June 29 to July 3. Sara owns payments while I'm away, migration "
        "included. Page her, not me.", channel="eng-payments", reactions=[sara],
        claims=[c("service:payments", "OWNED_BY", "person:sara")], unread_by=[dev]),
    msg("m025", "06-26 15:00", arjun, "Migration failed in staging again. I don't think we can ship 2.4 on "
        "Monday. Proposing Friday July 3.", channel="release"),
    msg("m026", "06-26 15:20", priya, "Agreed. 2.4 moves to Friday July 3. Do not deploy Monday.",
        channel="release", thread="m025", reactions=[dev, sara, arjun],
        claims=[c("release:2.4", "SHIPS_ON", "2026-07-03")]),
    msg("m027", "06-26 15:25", dev, "Rebooked the train for Friday July 3, same 16:00 UTC window. Freeze is "
        "extended to Wednesday July 1.", channel="release", thread="m025", reactions=[priya],
        claims=[c("release:2.4", "DEPLOY_WINDOW", "16:00 UTC"), c("release:2.4", "CODE_FREEZE", "2026-07-01")]),
    msg("m028", "06-26 17:00", tom, "Have a good weekend everyone!", channel="general"),

    # Sat 27 Jun
    msg("m029", "06-27 11:00", priya, "Scope cut: SSO slips to 2.5 (late July). 2.4 ships without it.",
        channel="release", reactions=[dev, sara],
        claims=[c("feature:sso", "AVAILABLE_IN", "2.5")]),
    msg("m030", "06-27 12:00", sara, "Decision from the API review: payments API v1 is deprecated as of today "
        "and shuts off August 1. All integrations should move to v2.", channel="eng-payments",
        reactions=[arjun, dev],
        claims=[c("api:payments-v1", "STATUS", "deprecated")]),

    # Mon 29 Jun
    msg("m031", "06-29 08:45", "ext:hannah", "Hi Tom, could we move the QBR to Thursday July 2 at 14:00 UTC? "
        "Tuesday got crowded on our side.", kind="email", subject_line="Re: Kestrel QBR", to=[tom]),
    msg("m032", "06-29 09:00", maya, "Brightline is pumped. Told Jordan 2.4 goes live today and SSO is in it!",
        channel="sales", reactions=[tom],
        claims=[c("release:2.4", "SHIPS_ON", "2026-06-29"), c("feature:sso", "AVAILABLE_IN", "2.4")],
        unread_by=[priya, lena]),
    msg("m033", "06-29 09:10", tom, "No problem, Thursday July 2 at 14:00 UTC it is. I've updated the invite.",
        kind="email", subject_line="Re: Kestrel QBR", to=["ext:hannah"],
        claims=[c("meeting:kestrel-qbr", "SCHEDULED_FOR", "2026-07-02 14:00 UTC")]),
    msg("m034", "06-29 10:00", dev, "Reminder: nothing deploys today. 2.4 is Friday.", channel="release",
        reactions=[sara],
        claims=[c("release:2.4", "SHIPS_ON", "2026-07-03")]),
    msg("m035", "06-29 14:00", tom, "@Arjun Kestrel says webhook retries are failing on their v1 integration, "
        "can you take a look?", channel="cs-kestrel", mentions=[arjun]),
    msg("m036", "06-29 15:00", sara, "Migration is fixed on staging. I also bumped webhook retries from 3 to 5 "
        "attempts.", channel="eng-payments", reactions=[dev],
        claims=[c("service:payments", "WEBHOOK_RETRIES", "5")]),

    # Tue 30 Jun
    msg("m037", "06-30 09:00", lena, "Office is closed on July 4th, enjoy the long weekend!", channel="general"),
    msg("m038", "06-30 10:05", sara, "@Tom saw your note. I own payments while Arjun is out, looking at "
        "Kestrel's retries now.", channel="cs-kestrel", thread="m035", mentions=[tom],
        claims=[c("service:payments", "OWNED_BY", "person:sara")]),
    msg("m039", "06-30 11:00", tom, "Customer asked about refunds. Still 30 days on monthly plans, right?",
        channel="support-kb"),
    msg("m040", "06-30 11:05", lena, "Yes, 30 days for now.", channel="support-kb", thread="m039",
        claims=[c("policy:monthly-refunds", "WINDOW", "30 days")]),

    # Wed 1 Jul
    msg("m041", "07-01 08:30", lena, "Refund policy update, effective today: monthly plans get 14 days, annual "
        "plans stay at 30.", channel="pricing", reactions=[priya],
        claims=[c("policy:monthly-refunds", "WINDOW", "14 days"), c("policy:annual-refunds", "WINDOW", "30 days")]),
    msg("m042", "07-01 09:00", dev, "Freeze is in effect from tonight, as planned. Only release blockers after "
        "this.", channel="release", reactions=[sara],
        claims=[c("release:2.4", "CODE_FREEZE", "2026-07-01")]),
    msg("m043", "07-01 10:00", maya, "Brightline asked for SSO setup docs ahead of Friday. Who can share them?",
        channel="sales"),
    msg("m044", "07-01 11:30", priya, "Did sales get the new Team pricing?", kind="dm", to=[lena]),
    msg("m045", "07-01 11:35", lena, "Ugh, not yet. I'll post it tomorrow.", kind="dm", to=[priya]),
]

# Drafts used by the demo's pre-send check (never sent, not part of the record).
DRAFTS = [
    {"author": tom, "to": ["ext:hannah"], "kind": "email", "as_of": "2026-07-01T12:00:00Z",
     "text": "Hi Hannah, quick note ahead of the renewal: your Team plan renewal stays at $39/seat/month, and "
             "your v1 webhooks are fully supported."},
    {"author": maya, "channel": "sales", "kind": "slack", "as_of": "2026-06-29T08:55:00Z",
     "text": "Brightline is pumped. Told Jordan 2.4 goes live today and SSO is in it!"},
    {"author": bot, "kind": "agent", "as_of": "2026-07-01T12:00:00Z",
     "text": "You can get a full refund within 30 days on the monthly Team plan ($39/seat/month). For "
             "integrations, use payments API v1."},
]


def dataset() -> dict[str, Any]:
    ids = [m["id"] for m in MESSAGES]
    assert len(ids) == len(set(ids)), "duplicate message ids"
    assert ids == sorted(ids, key=lambda i: next(m["ts"] for m in MESSAGES if m["id"] == i)), "out of order"
    return {
        "name": "Northwind Labs",
        "start": START,
        "end": END,
        "people": PEOPLE,
        "external": EXTERNAL,
        "channels": CHANNELS,
        "subjects": SUBJECTS,
        "links": [list(x) for x in LINKS],
        "responsibility": [list(x) for x in RESPONSIBILITY],
        "attributes": ATTRIBUTES,
        "messages": MESSAGES,
        "drafts": DRAFTS,
    }


def main() -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    out = DATA / "northwind.json"
    out.write_text(json.dumps(dataset(), indent=2), encoding="utf-8")
    print(f"wrote {out} ({len(MESSAGES)} messages)")


if __name__ == "__main__":
    main()
