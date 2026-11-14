"""Import a standard Slack export into Unstale's dataset format.

A Slack workspace export (Settings > Import/Export data) is a folder or zip with
``users.json``, ``channels.json`` and one folder per channel holding a JSON
file per day. This reads it into the same shape as ``data/northwind.json``:
people, channel members, and messages with author, thread, mentions and
reactions, which is everything Unstale's exposure model reads.

Slack doesn't know what your team's facts are, so a small catalog says which
subjects exist (releases, plans, customers...), who owns what, and how
subjects connect. ``--catalog`` takes a JSON file in the same shape as the
corresponding parts of ``data/northwind.json``; ``examples/catalog.json`` is a
starting point. The fact vocabulary defaults to Unstale's built-in one.

    python -m unstale.slack_import export.zip --catalog catalog.json -o data/myteam.json
    python scripts/ingest.py --dataset data/myteam.json
    UNSTALE_DATASET=data/myteam.json uvicorn unstale.api:app --port 8765
"""

from __future__ import annotations

import argparse
import json
import re
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .scenario import ATTRIBUTES

MENTION = re.compile(r"<@([UW][A-Z0-9]+)(?:\|[^>]*)?>")
CHANNEL_REF = re.compile(r"<#C[A-Z0-9]+\|([^>]+)>")
LINK = re.compile(r"<(https?://[^|>]+)(?:\|([^>]+))?>")
SKIP_SUBTYPES = {"channel_join", "channel_leave", "channel_topic", "channel_purpose", "channel_name",
                 "bot_add", "pinned_item", "channel_archive"}


class Export:
    """Read files from an export folder or zip the same way."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.zip = zipfile.ZipFile(path) if path.suffix == ".zip" else None
        names = self.zip.namelist() if self.zip else [str(p.relative_to(path)).replace("\\", "/")
                                                     for p in path.rglob("*.json")]
        # Some exports nest everything under one top-level folder.
        roots = {n.split("/")[0] for n in names if n.endswith("users.json") and n.count("/") == 1}
        self.prefix = (next(iter(roots)) + "/") if roots and not any(n == "users.json" for n in names) else ""
        self.names = [n[len(self.prefix):] for n in names if n.startswith(self.prefix)]

    def load(self, name: str) -> Any:
        if self.zip:
            return json.loads(self.zip.read(self.prefix + name).decode("utf-8"))
        return json.loads((self.path / self.prefix / name).read_text(encoding="utf-8"))

    def has(self, name: str) -> bool:
        return name in self.names

    def days(self, channel: str) -> list[str]:
        return sorted(n for n in self.names if n.startswith(channel + "/") and n.endswith(".json"))


def iso(ts: str) -> str:
    return datetime.fromtimestamp(float(ts), tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def handle(u: dict) -> str:
    raw = u.get("name") or u.get("profile", {}).get("display_name") or u["id"]
    return re.sub(r"[^a-z0-9._-]+", "-", raw.lower()).strip("-") or u["id"].lower()


def convert(path: str | Path, catalog: dict | None = None, name: str | None = None) -> dict[str, Any]:
    ex = Export(Path(path))
    users = ex.load("users.json")
    channels = ex.load("channels.json") if ex.has("channels.json") else []
    catalog = catalog or {}
    agents = set(catalog.get("agents", []))

    pid: dict[str, str] = {}
    people = []
    for u in users:
        if u.get("deleted") and not u.get("real_name"):
            continue
        is_agent = u.get("is_bot") or handle(u) in agents
        ident = f"{'agent' if is_agent else 'person'}:{handle(u)}"
        pid[u["id"]] = ident
        people.append({"id": ident, "name": u.get("real_name") or u.get("profile", {}).get("real_name") or handle(u),
                       "role": u.get("profile", {}).get("title") or ("AI agent" if is_agent else "Team member"),
                       "kind": "agent" if is_agent else "person"})

    members: dict[str, list[str]] = {}
    for ch in channels:
        members[ch["name"]] = [pid[m] for m in ch.get("members", []) if m in pid]

    def clean_text(text: str) -> str:
        text = MENTION.sub(lambda m: "@" + next((p["name"] for p in people if p["id"] == pid.get(m.group(1))),
                                                m.group(1)), text)
        text = CHANNEL_REF.sub(lambda m: "#" + m.group(1), text)
        text = LINK.sub(lambda m: m.group(2) or m.group(1), text)
        return text.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")

    raw = []
    for ch in members:
        for day in ex.days(ch):
            for m in ex.load(day):
                if m.get("type") != "message" or m.get("subtype") in SKIP_SUBTYPES or not m.get("ts"):
                    continue
                author = pid.get(m.get("user") or m.get("bot_id") or "")
                if author is None:
                    continue
                raw.append((m["ts"], ch, author, m))
    raw.sort(key=lambda x: float(x[0]))
    ids: dict[tuple[str, str], str] = {}
    messages = []
    for i, (ts, ch, author, m) in enumerate(raw, 1):
        mid = f"s{i:05d}"
        ids[(ch, ts)] = mid
        parent = m.get("thread_ts")
        thread = ids.get((ch, parent)) if parent and parent != ts else None
        reactions = sorted({pid[u] for r in m.get("reactions", []) for u in r.get("users", []) if u in pid})
        mentions = sorted({pid[u] for u in MENTION.findall(m.get("text", "")) if u in pid})
        messages.append({"id": mid, "ts": iso(ts), "kind": "slack", "channel": ch, "thread": thread,
                         "author": author, "to": [], "cc": [], "subject_line": None,
                         "text": clean_text(m.get("text", "")), "reactions": reactions, "mentions": mentions,
                         "_truth": {"claims": [], "unread_by": []}})
    known = {p["id"] for p in people}
    resp = [r for r in catalog.get("responsibility", []) if r[0] in known]
    return {
        "name": name or catalog.get("name") or Path(path).stem,
        "start": messages[0]["ts"] if messages else iso("0"),
        "end": messages[-1]["ts"] if messages else iso("0"),
        "people": people,
        "external": catalog.get("external", {}),
        "channels": members,
        "subjects": catalog.get("subjects", []),
        "links": catalog.get("links", []),
        "responsibility": resp,
        "attributes": catalog.get("attributes", ATTRIBUTES),
        "messages": messages,
        "drafts": [],
        "source": {"kind": "slack-export", "path": str(path), "messages": len(messages)},
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("export", help="Slack export folder or .zip")
    ap.add_argument("--catalog", help="JSON with subjects, links, responsibility (and optionally attributes, agents)")
    ap.add_argument("--name")
    ap.add_argument("-o", "--out", required=True)
    a = ap.parse_args()
    cat = json.loads(Path(a.catalog).read_text(encoding="utf-8")) if a.catalog else None
    ds = convert(a.export, cat, a.name)
    Path(a.out).write_text(json.dumps(ds, indent=1), encoding="utf-8")
    print(f"wrote {a.out}: {len(ds['people'])} people, {len(ds['channels'])} channels, {len(ds['messages'])} messages, "
          f"{len(ds['subjects'])} subjects in the catalog")
    if not ds["subjects"]:
        print("note: no catalog given, so extraction has no subjects to map facts onto; see examples/catalog.json")


if __name__ == "__main__":
    main()
