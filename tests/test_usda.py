import statistics

import httpx
import pytest

import api.usda as usda
from api.usda import fetch_county_yields
from data.generate import COUNTIES
from tests.conftest import create_org, load_demo, login


def fake_nass(series_by_county):
    """A stand-in Quick Stats server: returns each county's yield series from `year__GE` on."""
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        county = request.url.params["county_name"]
        first = int(request.url.params["year__GE"])
        rows = [{"year": str(y), "Value": v} for y, v in series_by_county.get(county, {}).items() if y >= first]
        return httpx.Response(200, json={"data": rows})

    return httpx.MockTransport(handler), seen


def test_fetch_builds_mean_and_history_std():
    story = {y: 50 + (y % 5) for y in range(2010, 2026)}
    story[2024] = "(D)"  # USDA suppresses some county-years
    transport, seen = fake_nass({"STORY": story, "BOONE": {2024: 55.0, 2025: 56.0}})

    df, notes = fetch_county_yields([("Story", "IA"), ("Boone", "IA")], ["soybeans", "quinoa"], [2024, 2025], "k", transport)

    assert df[["county", "season"]].values.tolist() == [["Story", 2025]]  # Story 2024 suppressed; Boone lacks history
    row = df.iloc[0]
    history = [story[y] for y in range(2015, 2025) if y != 2024]
    assert row.mean_yield == story[2025]
    assert row.std_yield == pytest.approx(statistics.stdev(history), abs=0.01)
    assert "no USDA mapping for crop 'quinoa'" in notes
    assert any(n.startswith("Story, IA soybeans 2024") for n in notes)
    assert any(n.startswith("Boone, IA soybeans") for n in notes)
    assert seen[0].url.params["commodity_desc"] == "SOYBEANS" and seen[0].url.params["key"] == "k"
    assert len(seen) == 2  # one call per county per supported crop


def test_usda_import_endpoint(client, monkeypatch):
    login(client, "a@x.com")
    create_org(client, "Acme")
    assert client.post("/api/data/county_yields/usda").status_code == 503  # no key configured

    monkeypatch.setattr(usda, "NASS_API_KEY", "k")
    assert client.post("/api/data/county_yields/usda").status_code == 409  # nothing uploaded yet
    load_demo(client)

    series = {y: 55.0 + (y % 3) for y in range(2010, 2026)}
    counties = [(county, state) for county, state, _full, _yield in COUNTIES]  # the demo's counties
    transport, seen = fake_nass({county.upper(): series for county, _state in counties})
    monkeypatch.setattr(usda, "TRANSPORT", transport)

    r = client.post("/api/data/county_yields/usda")
    assert r.status_code == 200, r.text
    assert r.json() == {"rows": len(counties) * 2, "notes": []}
    assert len(seen) == len(counties)
    status = {row["table"]: row["rows"] for row in client.get("/api/data").json()}
    assert status["county_yields"] == len(counties) * 2
    assert client.get("/api/scores").status_code == 200  # the imported table feeds the pipeline
    assert client.get("/api/orgs/current/audit").json()[0]["action"] == "data.usda_import"
