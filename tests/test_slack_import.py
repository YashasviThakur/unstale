"""Round trip: write Northwind's Slack messages as a real Slack export, import it, compare."""

from __future__ import annotations

import json
import zipfile
from collections import defaultdict

import pytest

from unstale import slack_import
from unstale.config import DATA
from unstale.rules import parse_ts


@pytest.fixture(scope="module")
def ds():
    return json.loads((DATA / "northwind.json").read_text(encoding="utf-8"))


def to_export(ds: dict, root) -> dict:
    """Northwind -> Slack export layout (users.json, channels.json, <channel>/<day>.json)."""
    uid = {p["id"]: f"U{i:04d}" for i, p in enumerate(ds["people"])}
    users = [{"id": uid[p["id"]], "name": p["id"].split(":")[1], "real_name": p["name"],
              "is_bot": p["kind"] == "agent", "profile": {"title": p["role"]}} for p in ds["people"]]
    channels = [{"id": f"C{i:03d}", "name": c, "members": [uid[m] for m in ms]}
                for i, (c, ms) in enumerate(ds["channels"].items())]
    days = defaultdict(list)
    sts = {}
    for m in ds["messages"]:
        if not m.get("channel"):
            continue
        ts = f"{parse_ts(m['ts']).timestamp():.6f}"
        sts[m["id"]] = ts
        text = m["text"]
        for pid in m.get("mentions", []):
            text += f" <@{uid[pid]}>"
        rec = {"type": "message", "user": uid[m["author"]], "text": text, "ts": ts}
        if m.get("thread"):
            rec["thread_ts"] = sts[m["thread"]]
        if m.get("reactions"):
            rec["reactions"] = [{"name": "+1", "users": [uid[r] for r in m["reactions"]], "count": len(m["reactions"])}]
        days[(m["channel"], m["ts"][:10])].append(rec)
    days[("general", "2026-06-22")].insert(0, {"type": "message", "subtype": "channel_join", "user": "U0000",
                                                "text": "joined", "ts": "1781000000.000000"})
    (root / "users.json").write_text(json.dumps(users))
    (root / "channels.json").write_text(json.dumps(channels))
    for (ch, day), recs in days.items():
        (root / ch).mkdir(exist_ok=True)
        (root / ch / f"{day}.json").write_text(json.dumps(recs))
    return uid


def test_folder_and_zip_round_trip(ds, tmp_path):
    root = tmp_path / "export"
    root.mkdir()
    to_export(ds, root)
    zpath = tmp_path / "export.zip"
    with zipfile.ZipFile(zpath, "w") as z:
        for f in root.rglob("*.json"):
            z.write(f, "Northwind Slack export/" + str(f.relative_to(root)).replace("\\", "/"))
    for src in (root, zpath):
        out = slack_import.convert(src, {"subjects": ds["subjects"], "links": ds["links"],
                                         "responsibility": ds["responsibility"]})
        slack_msgs = [m for m in ds["messages"] if m.get("channel")]
        assert len(out["messages"]) == len(slack_msgs)            # the channel_join is skipped
        assert {p["id"] for p in out["people"]} == {p["id"] for p in ds["people"]}
        assert next(p for p in out["people"] if p["id"] == "agent:support-bot")["kind"] == "agent"
        assert out["channels"] == ds["channels"]
        for a, b in zip(out["messages"], slack_msgs):
            assert a["ts"] == b["ts"] and a["author"] == b["author"] and a["channel"] == b["channel"]
            assert a["reactions"] == sorted(b["reactions"])
            assert a["mentions"] == sorted(b.get("mentions", []))
            assert (a["thread"] is None) == (b["thread"] is None)
            assert a["text"].startswith(b["text"])
        assert out["responsibility"] == ds["responsibility"]
