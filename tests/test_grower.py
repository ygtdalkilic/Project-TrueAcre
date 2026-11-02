import re

import pandas as pd
import pytest

from api.main import app
from api.pipeline import with_grower_statements
from tests.conftest import create_org, load_demo, login

GROWER_EMAIL = "grower@farm.example"


def _company_with_grower(client) -> tuple[str, dict]:
    """An admin loads the demo and invites one grower; returns that grower's id and first score row."""
    login(client, "admin@x.com")
    create_org(client, "Acme")
    load_demo(client)
    row = client.get("/api/scores").json()[0]
    r = client.post("/api/orgs/current/invites", json={"email": GROWER_EMAIL, "role": "grower", "grower_id": row["grower_id"]})
    assert r.status_code == 201, r.text
    me = login(client, GROWER_EMAIL)  # the invite becomes a membership on first sign-in
    assert me["current_org"]["role"] == "grower" and me["current_org"]["grower_id"] == row["grower_id"]
    return row["grower_id"], row


def test_grower_invites_must_name_a_real_grower(client):
    login(client, "admin@x.com")
    create_org(client, "Acme")
    invite = lambda body: client.post("/api/orgs/current/invites", json=body)  # noqa: E731
    assert invite({"email": "g@x.com", "role": "grower"}).status_code == 400  # no grower_id
    assert invite({"email": "g@x.com", "role": "grower", "grower_id": "G0001"}).status_code == 404  # nothing uploaded
    load_demo(client)
    assert invite({"email": "g@x.com", "role": "grower", "grower_id": "NOPE"}).status_code == 404
    assert invite({"email": "a@x.com", "role": "analyst", "grower_id": "G0001"}).status_code == 400
    assert invite({"email": "g@x.com", "role": "grower", "grower_id": "G0001"}).status_code == 201


def test_grower_sees_only_their_own_seasons(client):
    grower_id, row = _company_with_grower(client)
    seasons = client.get("/api/grower/seasons").json()
    assert seasons and {s["grower_id"] for s in seasons} == {grower_id}
    assert all("coverage" not in s and "replant_signal" not in s for s in seasons)

    ev = client.get(f"/api/grower/seasons/{row['season']}/crops/{row['crop']}").json()
    assert ev["score"]["grower_id"] == grower_id
    assert "coverage" not in ev["score"] and ev["clear"]["non_reporting_dealers"] == []
    assert client.get("/api/grower/seasons/1999/crops/soybeans").status_code == 404


def test_grower_is_refused_by_every_staff_route(client):
    """Deny by default: walk every route the app serves and call it as a grower."""
    _company_with_grower(client)
    open_to_growers = ("/api/grower/", "/api/auth/", "/api/me", "/api/health", "/api/config")
    checked = set()
    for template, operations in app.openapi()["paths"].items():  # every route the app serves
        if template.startswith(open_to_growers):
            continue
        path = re.sub(r"\{(season|user_id|invite_id)\}", "1", template)
        path = re.sub(r"\{[^}]+\}", "x", path)
        for method in operations:
            if (template, method) == ("/api/orgs", "post"):
                continue  # anyone signed in may start their own company
            r = client.request(method.upper(), path)
            assert r.status_code == 403, f"{method.upper()} {template} answered {r.status_code} to a grower"
            checked.add(template)
    assert {"/api/scores", "/api/data/{table}", "/api/links/decisions", "/api/orgs/current/audit",
            "/api/growers/{grower_id}/seasons/{season}/crops/{crop}"} <= checked  # the walk really covered them


def test_filed_statement_reaches_the_company_scores(client):
    grower_id, row = _company_with_grower(client)
    url = f"/api/grower/seasons/{row['season']}/crops/{row['crop']}/statement"
    assert client.put(url, json={"other_seed_acres": -1}).status_code == 422
    assert client.put("/api/grower/seasons/1999/crops/soybeans/statement", json={"other_seed_acres": 5}).status_code == 404
    assert client.put(url, json={"other_seed_acres": 12.5}).status_code == 200

    login(client, "admin@x.com")  # staff see it in the score, and in the audit log
    mine = [r for r in client.get("/api/scores").json()
            if (r["grower_id"], r["season"], r["crop"]) == (grower_id, row["season"], row["crop"])]
    assert mine[0]["has_statement"] and mine[0]["other_seed_acres"] == 12.5
    events = client.get("/api/orgs/current/audit").json()
    assert any(e["action"] == "grower.statement" for e in events)

    # a later upload of the seed_statements table does not erase what the grower filed
    assert client.post("/api/data/demo").status_code == 200
    again = [r for r in client.get("/api/scores").json()
             if (r["grower_id"], r["season"], r["crop"]) == (grower_id, row["season"], row["crop"])]
    assert again[0]["other_seed_acres"] == 12.5


def test_filed_statement_replaces_only_its_own_row():
    uploaded = pd.DataFrame({"grower_id": ["G1", "G1", "G2"], "season": [2024, 2025, 2024],
                             "crop": ["soybeans"] * 3, "other_seed_acres": [0.0, 0.0, 30.0]})
    filed = pd.DataFrame({"grower_id": ["G1"], "season": [2025], "crop": ["soybeans"], "other_seed_acres": [40.0]})
    out = with_grower_statements({"seed_statements": uploaded}, filed)["seed_statements"]
    assert sorted(zip(out.grower_id, out.season, out.other_seed_acres)) == [
        ("G1", 2024, 0.0), ("G1", 2025, 40.0), ("G2", 2024, 30.0)]
    assert with_grower_statements({}, filed)["seed_statements"].equals(filed)
    tables = {"seed_statements": uploaded}
    assert with_grower_statements(tables, filed.iloc[0:0]) is tables


@pytest.mark.parametrize("role", ["admin", "analyst"])
def test_staff_cannot_use_grower_routes(client, role):
    login(client, "admin@x.com")
    create_org(client, "Acme")
    load_demo(client)
    if role == "analyst":
        client.post("/api/orgs/current/invites", json={"email": "an@x.com", "role": "analyst"})
        login(client, "an@x.com")
    assert client.get("/api/grower/seasons").status_code == 403
