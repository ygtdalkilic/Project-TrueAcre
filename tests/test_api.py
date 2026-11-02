import json
import time

import pytest
from fastapi import HTTPException

from sqlalchemy import select

import api.auth as auth
import api.scores as scores_module
from api import models
from api.db import SessionLocal
from data.generate import DEFAULT_SEED, generate
from engine.explain import LLMClient
from engine.reconcile import YIELD_SIGMAS
from engine.score import REVIEW
from tests.conftest import create_org, load_demo, login
from tests.test_explain import fake_server

TRUTH = generate(seed=DEFAULT_SEED)["ground_truth"]  # the demo dataset's answer key


def test_email_check_is_linear_on_hostile_input():
    """CodeQL py/polynomial-redos: overlapping groups made a failing match quadratic in the input length."""
    hostile = "a@" + "." * 100_000 + " "
    start = time.perf_counter()
    assert auth.EMAIL_RE.match(hostile) is None
    with pytest.raises(HTTPException):
        auth.normalize_email(hostile)
    assert time.perf_counter() - start < 0.5
    assert auth.normalize_email(" New@Mail.Example.co.uk ") == "new@mail.example.co.uk"
    for bad in ("bad", "a@b", "a@.b", "a@b..c", "a b@c.d", "a@b.c" + "x" * models.EMAIL_LENGTH):
        with pytest.raises(HTTPException):
            auth.normalize_email(bad)


def test_health_config_and_security_headers(client):
    r = client.get("/api/health")
    assert r.json() == {"ok": True}
    assert r.headers["content-security-policy"].startswith("default-src 'self'")
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["x-frame-options"] == "DENY"
    assert client.get("/api/config").json()["dev_login"] is True
    assert client.get("/api/no-such-endpoint").status_code == 404  # never the dashboard page


def test_everything_else_requires_sign_in(client):
    for path in ("/api/me", "/api/scores", "/api/data", "/api/unmatched", "/api/orgs/current/members"):
        assert client.get(path).status_code == 401, path
    assert client.post("/api/orgs", json={"name": "X"}).status_code == 401


def test_cross_site_requests_are_refused(client):
    r = client.post("/api/auth/dev", json={"email": "a@x.com"}, headers={"Origin": "https://evil.example"})
    assert r.status_code == 403
    r = client.post("/api/auth/dev", json={"email": "a@x.com"}, headers={"Sec-Fetch-Site": "cross-site"})
    assert r.status_code == 403
    r = client.post("/api/auth/dev", json={"email": "a@x.com"}, headers={"Origin": "http://testserver"})
    assert r.status_code == 200


def test_sign_in_is_rate_limited(client, monkeypatch):
    monkeypatch.setattr(auth, "LOGIN_LIMIT", auth.RateLimiter(limit=3, window_seconds=60))
    for _ in range(3):
        assert client.post("/api/auth/dev", json={"email": "a@x.com"}).status_code == 200
    r = client.post("/api/auth/dev", json={"email": "a@x.com"})
    assert r.status_code == 429 and "retry-after" in r.headers


def test_google_sign_in_verifies_the_token(client, monkeypatch):
    monkeypatch.setattr(auth, "GOOGLE_CLIENT_ID", "client-id")
    monkeypatch.setattr(auth, "verify_google_token", lambda cred: {
        "sub": "g-123", "email": "Farmer@Example.com", "email_verified": True, "name": "Farmer", "picture": "p",
    })
    me = client.post("/api/auth/google", json={"credential": "token"}).json()
    assert me["user"]["email"] == "farmer@example.com" and me["organizations"] == []

    def reject(cred):
        raise ValueError("bad token")
    monkeypatch.setattr(auth, "verify_google_token", reject)
    assert client.post("/api/auth/google", json={"credential": "token"}).status_code == 401


def test_google_sign_in_off_without_client_id(client):
    assert client.post("/api/auth/google", json={"credential": "t"}).status_code == 503


def test_create_company_and_switch(client):
    me = login(client, "owner@x.com", "Owner")
    assert me["current_org"] is None
    assert client.get("/api/scores").status_code == 403  # no company chosen yet

    me = create_org(client, "  Acme   Seeds ")
    assert me["current_org"] == {"id": me["organizations"][0]["id"], "name": "Acme Seeds", "role": "admin", "grower_id": None}
    second = create_org(client, "Beta Genetics")["current_org"]
    assert client.get("/api/me").json()["current_org"]["name"] == "Beta Genetics"
    first_id = me["current_org"]["id"]
    assert client.put("/api/me/org", json={"org_id": first_id}).json()["current_org"]["id"] == first_id
    assert client.put("/api/me/org", json={"org_id": 99999}).status_code == 403
    assert second["name"] == "Beta Genetics"


def test_invites_and_roles(client):
    login(client, "admin@x.com")
    org = create_org(client, "Acme")["current_org"]
    assert client.post("/api/orgs/current/invites", json={"email": "New@x.com", "role": "analyst"}).status_code == 201
    assert client.post("/api/orgs/current/invites", json={"email": "bad", "role": "analyst"}).status_code == 400
    assert client.post("/api/orgs/current/invites", json={"email": "z@x.com", "role": "boss"}).status_code == 400
    members = client.get("/api/orgs/current/members").json()
    assert [i["email"] for i in members["invites"]] == ["new@x.com"]
    client.post("/api/auth/logout")

    me = login(client, "new@x.com")  # invite becomes a membership on sign-in
    assert me["current_org"] == {"id": org["id"], "name": "Acme", "role": "analyst", "grower_id": None}
    assert client.post("/api/orgs/current/invites", json={"email": "q@x.com"}).status_code == 403  # analysts cannot invite
    assert "invites" not in client.get("/api/orgs/current/members").json()
    client.post("/api/auth/logout")

    login(client, "admin@x.com")
    members = client.get("/api/orgs/current/members").json()
    assert sorted(m["email"] for m in members["members"]) == ["admin@x.com", "new@x.com"]
    assert members["invites"] == []
    admin_id = next(m["user_id"] for m in members["members"] if m["email"] == "admin@x.com")
    assert client.delete(f"/api/orgs/current/members/{admin_id}").status_code == 409  # last admin stays


def test_delete_company_and_account(client):
    login(client, "admin@x.com")
    create_org(client, "Solo Co")
    load_demo(client)
    shared = create_org(client, "Shared Co")["current_org"]
    client.post("/api/orgs/current/invites", json={"email": "other@x.com", "role": "analyst"})

    client.post("/api/auth/logout")
    login(client, "other@x.com")  # accepts the invite, becomes the second member of Shared Co
    client.post("/api/auth/logout")
    login(client, "admin@x.com")
    r = client.delete("/api/me")  # refused while someone else depends on this admin
    assert r.status_code == 409 and "Shared Co" in r.json()["detail"]

    # an admin can delete a company outright; data, invites, and memberships go with it
    client.put("/api/me/org", json={"org_id": shared["id"]})
    assert client.delete("/api/orgs/current").status_code == 204
    assert client.get("/api/me").json()["current_org"] is None
    assert [o["name"] for o in client.get("/api/me").json()["organizations"]] == ["Solo Co"]

    # now the account can go; Solo Co had no other member, so it is deleted too
    assert client.delete("/api/me").status_code == 204
    assert client.get("/api/me").status_code == 401
    with SessionLocal() as db:
        assert db.scalars(select(models.Organization)).all() == []
        assert db.scalars(select(models.Dataset)).all() == []
        assert [u.email for u in db.scalars(select(models.User))] == ["other@x.com"]


def test_logout_everywhere_invalidates_old_cookie(client):
    login(client, "a@x.com")
    assert client.get("/api/me").status_code == 200
    client.post("/api/auth/logout-all")
    assert client.get("/api/me").status_code == 401


def test_templates_and_validation(client):
    login(client, "a@x.com")
    create_org(client, "Acme")
    assert client.get("/api/data/templates/growers.csv").text == "grower_id,name,county,state,farm_number\n"
    assert client.get("/api/data/templates/nope.csv").status_code == 404

    def put(table, text):
        return client.put(f"/api/data/{table}", files={"file": (f"{table}.csv", text.encode(), "text/csv")})

    assert "missing columns: state, farm_number" in put("growers", "grower_id,name,county\nG1,A,X\n").json()["detail"]
    assert "must be numeric (rows [3])" in put("varieties", "variety_id,name,crop,seeds_per_unit,target_seeds_per_acre\nV1,a,soy,140000,140000\nV2,b,soy,lots,140000\n").json()["detail"]
    assert "must be true/false" in put("dealers", "dealer_id,name,county,state,participating\nD1,d,X,IA,maybe\n").json()["detail"]
    assert "blank values" in put("growers", "grower_id,name,county,state,farm_number\nG1,,X,IA,\n").json()["detail"]

    ok = put("growers", "grower_id,name,county,state,farm_number,extra\nG1,Ann Farmer,X,IA,,ignored\nG2,Bob,X,IA,F2,ignored\n")
    assert ok.status_code == 200 and ok.json()["rows"] == 2
    status = {row["table"]: row["rows"] for row in client.get("/api/data").json()}
    assert status["growers"] == 2 and status["dealers"] is None

    with SessionLocal() as db:  # what actually sits in the database is ciphertext, not grower names
        stored = db.scalar(select(models.Dataset).where(models.Dataset.table_name == "growers"))
        assert b"Ann Farmer" not in stored.ciphertext and b"grower_id" not in stored.ciphertext

    r = client.get("/api/scores")
    assert r.status_code == 409 and "dealers" in r.json()["detail"]["missing"]
    assert client.delete("/api/data/growers").status_code == 204
    assert client.delete("/api/data/growers").status_code == 404


def test_demo_data_scores_match_the_engine(client):
    login(client, "a@x.com")
    create_org(client, "Acme")
    load_demo(client)
    rows = client.get("/api/scores").json()
    assert len(rows) == len(TRUTH)
    scores = [r["fair_play_score"] for r in rows]
    assert scores == sorted(scores)

    review = client.get("/api/scores", params={"label": REVIEW}).json()
    ghost = TRUTH[TRUTH["case_type"] == "ghost_seed"]
    assert review and {(r["grower_id"], r["season"]) for r in review} <= set(zip(ghost["grower_id"], ghost["season"]))

    flagged = review[0]
    assert flagged["crop"] == "soybeans"
    body = client.get(f"/api/growers/{flagged['grower_id']}/seasons/{flagged['season']}/crops/{flagged['crop']}").json()
    assert body["score"] == flagged
    assert sum(p["acres_supported"] for p in body["purchases"]) == pytest.approx(flagged["licensed_acres"])
    assert sum(a["acres"] for a in body["acreage_reports"]) == pytest.approx(flagged["declared_acres"])
    cy = body["county_yield"]
    assert cy["mean_yield"] + YIELD_SIGMAS * cy["std_yield"] == pytest.approx(flagged["yield_ceiling"])
    assert body["clear"]["acres"] > 0 and body["clear"]["units"]["units"] > 0
    assert [h["season"] for h in body["history"]] == sorted(h["season"] for h in body["history"])
    assert flagged["season"] in [h["season"] for h in body["history"]]
    assert client.get("/api/growers/NOPE/seasons/2024/crops/soybeans").status_code == 404
    assert client.get(f"/api/growers/{flagged['grower_id']}/seasons/{flagged['season']}/crops/corn").status_code == 404
    assert isinstance(client.get("/api/unmatched").json(), list)


def test_stored_text_columns_stay_text(client):
    """FSA farm numbers are digits. Read back as numbers, the resolver's farm-number rule would never fire."""
    from api.pipeline import load_tables
    login(client, "a@x.com")
    create_org(client, "Acme")
    load_demo(client)
    with SessionLocal() as db:
        tables = load_tables(db, db.scalar(select(models.Organization)))
    assert tables["growers"]["farm_number"].dropna().map(type).eq(str).all()
    assert tables["acreage_reports"]["farm_number"].map(type).eq(str).all()
    evidence_methods = set()
    for row in client.get("/api/scores").json()[:40]:
        ev = client.get(f"/api/growers/{row['grower_id']}/seasons/{row['season']}/crops/{row['crop']}").json()
        evidence_methods |= {a["match_method"] for a in ev["acreage_reports"]}
    assert "farm number" in evidence_methods  # the farm-number rule fires through the API, not only in engine tests


def test_seed_statements_are_optional_and_required_for_review(client):
    login(client, "a@x.com")
    create_org(client, "Acme")
    load_demo(client)
    status = {row["table"]: row for row in client.get("/api/data").json()}
    assert status["seed_statements"]["optional"] and not status["growers"]["optional"]
    assert client.get("/api/scores", params={"label": REVIEW}).json()

    assert client.delete("/api/data/seed_statements").status_code == 204
    rows = client.get("/api/scores").json()  # still scored without the optional table
    assert len(rows) == len(TRUTH)
    assert not any(r["has_statement"] for r in rows)
    assert not [r for r in rows if r["label"] == REVIEW]  # a gap alone could be another company's seed


def test_audit_log_records_actions_for_admins_only(client):
    login(client, "admin@x.com")
    create_org(client, "Acme")
    load_demo(client)
    row = client.get("/api/scores").json()[0]
    client.get(f"/api/growers/{row['grower_id']}/seasons/{row['season']}/crops/{row['crop']}")
    client.post("/api/orgs/current/invites", json={"email": "an@x.com", "role": "analyst"})

    events = client.get("/api/orgs/current/audit").json()
    assert [e["action"] for e in events] == ["invite.create", "evidence.view", "data.demo", "org.create"]  # newest first
    assert all(e["user"] == "admin@x.com" and e["ip"] for e in events)
    assert events[0]["detail"] == {"email": "an@x.com", "role": "analyst", "grower_id": None, "joined": False}
    assert events[1]["detail"]["grower_id"] == row["grower_id"]

    client.post("/api/auth/logout")
    login(client, "an@x.com")
    assert client.get("/api/orgs/current/audit").status_code == 403  # analysts cannot read the log


def test_companies_cannot_see_each_other(client):
    login(client, "a@x.com")
    org_a = create_org(client, "A Co")["current_org"]
    load_demo(client)
    grower = client.get("/api/scores").json()[0]
    client.post("/api/auth/logout")

    login(client, "b@x.com")
    create_org(client, "B Co")
    assert client.put("/api/me/org", json={"org_id": org_a["id"]}).status_code == 403
    assert client.get("/api/scores").status_code == 409  # B has no data, and none of A's leaks
    assert client.get(f"/api/growers/{grower['grower_id']}/seasons/{grower['season']}/crops/{grower['crop']}").status_code == 409
    assert client.get("/api/links/review").status_code == 409


def test_explanations_disabled_without_a_provider(client, monkeypatch):
    monkeypatch.setattr(scores_module, "EXPLAIN_CLIENT", None)
    login(client, "a@x.com")
    create_org(client, "Acme")
    load_demo(client)
    row = client.get("/api/scores").json()[0]
    assert client.get("/api/config").json()["explanations_enabled"] is False
    assert client.post(f"/api/growers/{row['grower_id']}/seasons/{row['season']}/crops/{row['crop']}/explanation").status_code == 503


def test_explanation_is_written_from_the_evidence(client, monkeypatch):
    transport, seen = fake_server(reply="Plain words.")
    monkeypatch.setattr(scores_module, "EXPLAIN_CLIENT", LLMClient("custom", "http://fake/v1", "test-model", transport=transport))
    login(client, "a@x.com")
    create_org(client, "Acme")
    load_demo(client)
    row = client.get("/api/scores").json()[0]
    assert client.get("/api/config").json()["provider"] == "custom"
    path = f"/api/growers/{row['grower_id']}/seasons/{row['season']}/crops/{row['crop']}"

    body = client.post(f"{path}/explanation").json()
    assert body == {"explanation": "Plain words."}
    sent = json.loads(json.loads(seen[0].content)["messages"][1]["content"])
    assert sent == client.get(path).json()

    transport, _ = fake_server(status=500)
    monkeypatch.setattr(scores_module, "EXPLAIN_CLIENT", LLMClient("custom", "http://fake/v1", "m", transport=transport))
    r = client.post(f"{path}/explanation")
    assert r.status_code == 502 and "custom returned 500" in r.json()["detail"]
