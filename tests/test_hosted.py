"""The hosted path end to end: embedded Kuzu store, graph rebuilt from the extraction cache, no server and no key."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from unstale.engine import kuzu_dialect


def test_kuzu_dialect_renames_labels_and_ids():
    q = ("MATCH (p:Entity)-[s:RELATES]->(m:Entity)-[a:RELATES]->(c:Entity) "
         "WHERE p.sid = $p AND p.ns = $ns AND s.etype = 'SAW' RETURN c.sid AS cid, c.doc AS claim")
    out = kuzu_dialect(q)
    assert ":Entity" not in out and ":RELATES" not in out
    assert "p.id = $p" in out and "c.id AS cid" in out
    assert "s.etype" in out          # relationship properties keep their names


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    """One app for the module: the MCP session manager can only be started once per process."""
    mp = pytest.MonkeyPatch()
    mp.setenv("UNSTALE_STORE", "kuzu")
    mp.setenv("UNSTALE_KUZU_PATH", str(tmp_path_factory.mktemp("kuzu") / "g.kuzu"))
    mp.setenv("UNSTALE_HOSTED", "1")
    mp.setenv("UNSTALE_MCP", "1")
    from unstale import api
    api.STATE.pop("eng", None)
    with TestClient(api.app) as c:
        yield c
    mp.undo()


def test_hosted_demo_matches_the_labelled_team(client):
    meta = client.get("/api/meta").json()
    assert meta["store"] == "kuzu" and meta["hosted"] is True
    team = client.get("/api/team", params={"as_of": "2026-07-01T17:00:00Z"}).json()
    stale = {p["person"]: len(p["stale"]) for p in team["people"]}
    assert stale["person:maya"] == 5 and stale["person:tom"] == 3 and stale["agent:support-bot"] == 3


def test_graph_shows_the_missing_edge(client):
    g = client.get("/api/graph", params={"slot": "release:2.4|SHIPS_ON", "as_of": "2026-06-29T08:55:00Z"}).json()
    assert [v["value"] for v in g["versions"]] == ["2026-06-29", "2026-07-03"]
    maya = next(p for p in g["people"] if p["id"] == "person:maya")
    assert maya["stale"] and maya["believes"] == "2026-06-29"
    assert any(x["person"] == "person:maya" for x in g["missing"])
    assert not any(s["person"] == "person:maya" and s["message"] == "m026" for s in g["saw"])
    assert "SAW" in g["cypher"]


def test_proof_reads_the_result_files(client):
    p = client.get("/api/proof").json()
    assert p["northwind"]["unstale"]["precision"] == 1.0
    assert p["curve"]["curve"][0]["prior_sprints"] == 0
    assert p["agent"]["unstale"]["accuracy"] > p["agent"]["own"]["accuracy"]


def test_public_demo_does_not_let_visitors_post(client):
    r = client.post("/api/send", json={"author": "person:maya", "text": "hi", "as_of": "2026-07-01T17:00:00Z",
                                       "channel": "sales"})
    assert r.status_code == 403


END = "2026-07-01T17:00:00Z"


def test_fix_plan_reaches_everyone_and_the_what_if_removes_the_corrections(client):
    import json
    f = client.get("/api/fix", params={"slot": "plan:team|PRICED_AT", "as_of": END}).json()
    stale = {x["person"] for x in f["stale"]}
    assert stale == {"person:tom", "person:maya", "agent:support-bot"}
    reached = {p for st in f["plan"] if st["kind"] == "post" for p in st["reach"]}
    assert reached == stale                      # every stale person is covered by some channel
    assert all(o["after"] < o["before"] for o in f["outcome"])
    assert "Team plan" in f["draft"] and "$49/seat/month" in f["draft"]

    before = client.get("/api/brief/person:tom", params={"as_of": END}).json()["items"]
    sim = json.dumps(f["effects"])
    after = client.get("/api/brief/person:tom", params={"as_of": END, "sim": sim}).json()["items"]
    assert len(after) == len(before) - 1
    assert all(i["slot"] != "plan:team|PRICED_AT" for i in after)


def test_fix_what_if_is_stateless(client):
    import json
    f = client.get("/api/fix", params={"slot": "plan:team|PRICED_AT", "as_of": END}).json()
    client.get("/api/team", params={"as_of": END, "sim": json.dumps(f["effects"])})
    plain = client.get("/api/team", params={"as_of": END}).json()
    assert sum(len(p["stale"]) for p in plain["people"]) == 13      # the simulation changed nothing in the graph


def test_a_simulation_is_ignored_before_it_happens(client):
    import json
    f = client.get("/api/fix", params={"slot": "plan:team|PRICED_AT", "as_of": END}).json()
    early = client.get("/api/brief/person:tom", params={"as_of": "2026-06-30T08:00:00Z", "sim": json.dumps(f["effects"])}).json()
    plain = client.get("/api/brief/person:tom", params={"as_of": "2026-06-30T08:00:00Z"}).json()
    assert [i["slot"] for i in early["items"]] == [i["slot"] for i in plain["items"]]


def test_remote_mcp_serves_the_tools(client):
    h = {"content-type": "application/json", "accept": "application/json, text/event-stream"}

    def rpc(i, method, params=None):
        return client.post("/mcp", headers=h, json={"jsonrpc": "2.0", "id": i, "method": method, "params": params or {}}).json()

    tools = {t["name"] for t in rpc(1, "tools/list")["result"]["tools"]}
    assert {"corrections", "who_to_notify", "who_believes", "check_before_sending", "give_feedback"} <= tools
    out = rpc(2, "tools/call", {"name": "who_to_notify", "arguments": {"subject": "plan:team", "attribute": "PRICED_AT"}})
    text = out["result"]["content"][0]["text"]
    assert "Post in #general" in text and "Support agent" in text
    assert client.get("/api/meta").json()["mcp"] is True


def test_vector_results_sit_next_to_the_graph(client):
    g = client.get("/api/graph", params={"slot": "plan:team|PRICED_AT", "as_of": END}).json()
    v = g["vector"]
    assert v["model"].startswith("BAAI/") and 1 <= len(v["results"]) <= 5
    assert any(r["states"] and not r["current"] for r in v["results"])      # it retrieves the old value too


def test_a_reported_miss_teaches_the_graph_and_the_suspicion_shows(client):
    """Last, because it writes evidence: Dev says he missed the payments hand-off, his read rate drops, and he is now worth a check."""
    a = client.get("/api/assumed", params={"person": "person:dev", "as_of": END}).json()["items"]
    assert [i["slot"] for i in a] == ["service:payments|OWNED_BY"]
    assert client.get("/api/brief/person:dev", params={"as_of": END}).json()["maybe"] == []
    r = client.post("/api/feedback", json={"person": "person:dev", "slot": "service:payments|OWNED_BY", "verdict": "news", "as_of": END}).json()
    assert r["evidence"] == 1 and r["rates"][0]["rate"] < 0.5
    b = client.get("/api/brief/person:dev", params={"as_of": END}).json()
    assert [m["slot"] for m in b["maybe"]] == ["service:payments|OWNED_BY"] and b["items"] == []


def test_landing_and_app_are_separate_pages(client):
    home = client.get("/")
    assert home.status_code == 200 and "Who is still on the" in home.text and "/static/landing.css" in home.text
    app = client.get("/app")
    assert app.status_code == 200 and 'id="viewer-list"' in app.text and "/static/app.css" in app.text
    for path in ("/static/landing.js", "/static/shots/corrections.png", "/static/og.png"):
        assert client.get(path).status_code == 200
    data = client.get("/static/landing-data.json").json()           # what the landing player plays, from the real engine
    assert len(data["steps"]) == 5 and data["end"]["total"] == 13 and data["proof"]["curve"]["curve"]


def test_feed_carries_read_receipts_and_meta_carries_change_markers(client):
    feed = client.get("/api/feed", params={"viewer": "person:maya", "as_of": END}).json()["messages"]
    stated = [m for m in feed if m["claims"]]
    assert stated and all(m["seen_by"] for m in stated)
    assert all({"person", "strength"} <= set(s) for s in stated[0]["seen_by"])
    assert client.get("/api/meta").json()["changes"]
