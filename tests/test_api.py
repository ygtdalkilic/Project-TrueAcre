import json

import pytest
from fastapi.testclient import TestClient

import api.main as main
from api.main import RESOLVED, TABLES, app
from engine.reconcile import YIELD_SIGMAS
from engine.score import REVIEW
from tests.test_explain import FakeClient, fake_response

client = TestClient(app)
TRUTH = TABLES["ground_truth"]


def test_scores_lists_every_grower_season_worst_first():
    rows = client.get("/scores").json()
    assert len(rows) == len(TRUTH)
    scores = [r["fair_play_score"] for r in rows]
    assert scores == sorted(scores)
    assert {"grower_id", "name", "season", "fair_play_score", "label", "coverage"} <= rows[0].keys()


def test_scores_filters():
    review = client.get("/scores", params={"label": REVIEW}).json()
    ghost = TRUTH[TRUTH["case_type"] == "ghost_seed"]
    assert review and all(r["label"] == REVIEW for r in review)
    assert {(r["grower_id"], r["season"]) for r in review} <= set(zip(ghost["grower_id"], ghost["season"]))

    season, county = int(TRUTH["season"].iloc[0]), TABLES["growers"]["county"].iloc[0]
    subset = client.get("/scores", params={"season": season, "county": county}).json()
    assert subset and all(r["season"] == season and r["county"] == county for r in subset)


def test_evidence_matches_score():
    flagged = client.get("/scores", params={"label": REVIEW}).json()[0]
    body = client.get(f"/growers/{flagged['grower_id']}/seasons/{flagged['season']}").json()

    assert body["score"] == flagged
    assert body["purchases"]
    assert all(a["match_method"] for a in body["acreage_reports"] + body["elevator_receipts"])
    assert sum(p["acres_supported"] for p in body["purchases"]) == pytest.approx(flagged["licensed_acres"])
    assert sum(a["acres"] for a in body["acreage_reports"]) == pytest.approx(flagged["declared_acres"])
    assert sum(r["bushels"] for r in body["elevator_receipts"]) == pytest.approx(flagged["delivered_bushels"])
    cy = body["county_yield"]
    assert body["yield_sigmas"] == YIELD_SIGMAS
    assert cy["mean_yield"] + YIELD_SIGMAS * cy["std_yield"] == pytest.approx(flagged["yield_ceiling"])


def test_unknown_grower_is_404():
    assert client.get("/growers/NOPE/seasons/2024").status_code == 404


def test_unmatched_records_are_listed():
    rows = client.get("/unmatched").json()
    assert len(rows) == len(RESOLVED["unmatched"])
    assert list(RESOLVED["unmatched"].columns) == ["source", "record_id", "name", "county", "reason"]


def test_explanations_disabled_without_a_key(monkeypatch):
    monkeypatch.setattr(main, "EXPLAIN_CLIENT", None)
    row = TRUTH.iloc[0]
    assert client.get("/config").json() == {"explanations_enabled": False}
    assert client.post(f"/growers/{row.grower_id}/seasons/{row.season}/explanation").status_code == 503


def test_explanation_is_written_from_the_evidence(monkeypatch):
    fake = FakeClient(fake_response(text="Plain words."))
    monkeypatch.setattr(main, "EXPLAIN_CLIENT", fake)
    row = TRUTH.iloc[0]
    assert client.get("/config").json() == {"explanations_enabled": True}

    body = client.post(f"/growers/{row.grower_id}/seasons/{row.season}/explanation").json()
    assert body == {"explanation": "Plain words."}
    sent = json.loads(fake.models.calls[0]["contents"])
    assert sent == client.get(f"/growers/{row.grower_id}/seasons/{row.season}").json()
    assert client.post("/growers/NOPE/seasons/2024/explanation").status_code == 404
