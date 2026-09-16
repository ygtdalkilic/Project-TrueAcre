from api.pipeline import apply_decisions
from data.generate import generate
from engine.resolve import resolve
from tests.conftest import create_org, load_demo, login


def test_apply_decisions_overrides_the_resolver():
    tables = generate()
    resolved = resolve(tables)
    unmatched = resolved["unmatched"]
    assert len(unmatched) >= 1
    record = unmatched.iloc[0]
    table = record["source"]
    id_col = "report_id" if table == "acreage_reports" else "receipt_id"
    grower = tables["growers"]["grower_id"].iloc[0]

    fuzzy = resolved["acreage_reports"][resolved["acreage_reports"]["match_method"] == "fuzzy name"]
    assert not fuzzy.empty
    fuzzy_id = fuzzy["report_id"].iloc[0]

    out = apply_decisions(resolved, tables, {record["record_id"]: grower, fuzzy_id: None})
    linked = out[table].set_index(id_col).loc[record["record_id"]]
    assert linked["grower_id"] == grower and linked["match_method"] == "analyst"
    assert record["record_id"] not in set(out["unmatched"]["record_id"])
    assert fuzzy_id not in set(out["acreage_reports"]["report_id"])  # ruled "matches nobody": excluded
    assert len(out["acreage_reports"]) + len(out["elevator_receipts"]) == \
        len(resolved["acreage_reports"]) + len(resolved["elevator_receipts"])  # one added, one removed
    assert apply_decisions(resolved, tables, {}) is resolved


def test_review_queue_and_decisions(client):
    login(client, "a@x.com")
    create_org(client, "Acme")
    load_demo(client)

    items = client.get("/api/links/review").json()
    statuses = {i["status"] for i in items}
    assert {"unmatched", "check"} <= statuses  # the demo data has both refused and fuzzy-linked records
    item = next(i for i in items if i["status"] == "unmatched")
    assert item["candidates"] and all(0 <= c["similarity"] <= 1 for c in item["candidates"])
    assert items[0]["status"] == "unmatched"  # refused records come first

    before = len(client.get("/api/unmatched").json())
    choice = item["candidates"][0]["grower_id"]
    r = client.post("/api/links/decisions", json={"record_id": item["record_id"], "grower_id": choice, "note": "checked with dealer"})
    assert r.status_code == 201
    assert len(client.get("/api/unmatched").json()) == before - 1

    ruled = next(i for i in client.get("/api/links/review").json() if i["record_id"] == item["record_id"])
    assert (ruled["status"], ruled["grower_id"], ruled["reason"]) == ("analyst", choice, "checked with dealer")
    assert ruled["candidates"][0]["grower_id"] == choice  # the chosen grower is offered first

    # the record now sits in that grower's evidence, marked as the analyst's ruling
    evidence = client.get(f"/api/growers/{choice}/seasons/{item['season']}/crops/soybeans").json()
    key, id_col = ("acreage_reports", "report_id") if item["source"] == "acreage_reports" else ("elevator_receipts", "receipt_id")
    assert any(x[id_col] == item["record_id"] and x["match_method"] == "analyst" for x in evidence[key])

    # "matches nobody" keeps it out of the unmatched list; reverting restores the resolver's view
    assert client.post("/api/links/decisions", json={"record_id": item["record_id"], "grower_id": None}).status_code == 201
    assert len(client.get("/api/unmatched").json()) == before - 1
    assert client.delete(f"/api/links/decisions/{item['record_id']}").status_code == 204
    assert len(client.get("/api/unmatched").json()) == before

    assert client.post("/api/links/decisions", json={"record_id": "NOPE", "grower_id": choice}).status_code == 404
    assert client.post("/api/links/decisions", json={"record_id": item["record_id"], "grower_id": "G9999"}).status_code == 404
    assert client.delete("/api/links/decisions/NOPE").status_code == 404

    actions = [e["action"] for e in client.get("/api/orgs/current/audit").json()]
    assert actions[:4] == ["link.revert", "link.decide", "evidence.view", "link.decide"]  # newest first
