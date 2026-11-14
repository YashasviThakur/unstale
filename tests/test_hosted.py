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


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("UNSTALE_STORE", "kuzu")
    monkeypatch.setenv("UNSTALE_KUZU_PATH", str(tmp_path / "g.kuzu"))
    monkeypatch.setenv("UNSTALE_HOSTED", "1")
    from unstale import api
    api.STATE.clear()
    with TestClient(api.app) as c:
        yield c
    api.STATE.clear()


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
