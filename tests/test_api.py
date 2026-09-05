import pytest
from fastapi.testclient import TestClient

from api.main import TABLES, app
from engine.score import REVIEW

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
    assert len(review) == (TRUTH["case_type"] == "ghost_seed").sum()
    assert all(r["label"] == REVIEW for r in review)

    season, county = int(TRUTH["season"].iloc[0]), TABLES["growers"]["county"].iloc[0]
    subset = client.get("/scores", params={"season": season, "county": county}).json()
    assert subset and all(r["season"] == season and r["county"] == county for r in subset)


def test_evidence_matches_score():
    flagged = client.get("/scores", params={"label": REVIEW}).json()[0]
    body = client.get(f"/growers/{flagged['grower_id']}/seasons/{flagged['season']}").json()

    assert body["score"] == flagged
    assert body["purchases"] and body["acreage_reports"] and body["elevator_receipts"]
    assert sum(p["acres_supported"] for p in body["purchases"]) == pytest.approx(flagged["licensed_acres"])
    assert sum(a["acres"] for a in body["acreage_reports"]) == pytest.approx(flagged["declared_acres"])
    assert sum(r["bushels"] for r in body["elevator_receipts"]) == pytest.approx(flagged["delivered_bushels"])
    cy = body["county_yield"]
    assert cy["mean_yield"] + 2 * cy["std_yield"] == pytest.approx(flagged["yield_ceiling"])


def test_unknown_grower_is_404():
    assert client.get("/growers/NOPE/seasons/2024").status_code == 404
