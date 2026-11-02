import pandas as pd
import pytest

from data.generate import generate
from engine.reconcile import reconcile
from engine.resolve import normalize_name, resolve
from engine.score import CONSISTENT, REVIEW, score


@pytest.mark.parametrize("raw, expected", [
    ("James Miller", "james miller"),
    ("MILLER, JAMES", "james miller"),
    ("James R. Miller", "james miller"),
    ("James Miller Farms", "james miller"),
    ("  James   Miller ", "james miller"),
])
def test_normalize_name(raw, expected):
    assert normalize_name(raw) == expected


@pytest.fixture
def tiny():
    """Two growers named James Miller in county X (ambiguous); James Miller, Mark Koch and Mary Koch in Y."""
    growers = pd.DataFrame({
        "grower_id": ["G1", "G2", "G3", "G4", "G5"],
        "name": ["James Miller", "James Miller", "James Miller", "Mark Koch", "Mary Koch"],
        "county": ["X", "X", "Y", "Y", "Y"],
        "state": ["IA"] * 5,
        "farm_number": [None, None, "F3", None, None],
    })
    acreage = pd.DataFrame({
        "report_id": ["A1", "A2", "A3", "A4", "A5", "A6"],
        "operator_name": ["James Miller", "James Miller", "Miller, James", "JAMES R. MILLER FARMS", "Jame Miller", "Susan Becker"],
        "farm_number": ["F1", "F9", "F9", "F9", "F9", "F9"],
        "county": ["X", "Y", "Y", "Y", "Y", "Y"],
        "state": ["IA"] * 6, "season": [2024] * 6, "crop": ["soybeans"] * 6, "acres": [100.0] * 6,
    })
    receipts = pd.DataFrame({
        "receipt_id": ["R1", "R2", "R3"],
        "seller_name": ["Mak Koch", "Mar Koch", "Totally Different"],
        "county": ["Y", "Y", "Y"], "state": ["IA"] * 3, "elevator_id": ["E1"] * 3,
        "season": [2024] * 3, "crop": ["soybeans"] * 3, "bushels": [1000.0] * 3,
    })
    farm_match = pd.DataFrame({  # name says Mark Koch but the farm number is registered to G3
        "report_id": ["A7"], "operator_name": ["Mark Koch"], "farm_number": ["F3"], "county": ["Y"],
        "state": ["IA"], "season": [2024], "crop": ["soybeans"], "acres": [50.0],
    })
    return {"growers": growers, "acreage_reports": pd.concat([acreage, farm_match], ignore_index=True),
            "elevator_receipts": receipts}


def test_rules_and_refusals(tiny):
    out = resolve(tiny)
    acreage = out["acreage_reports"].set_index("report_id")
    assert acreage.loc["A2", ["grower_id", "match_method"]].tolist() == ["G3", "exact name"]
    assert acreage.loc["A3", "grower_id"] == "G3"  # last, first
    assert acreage.loc["A4", "grower_id"] == "G3"  # initial + Farms suffix
    assert acreage.loc["A5", ["grower_id", "match_method"]].tolist() == ["G3", "fuzzy name"]
    assert acreage.loc["A7", ["grower_id", "match_method"]].tolist() == ["G3", "farm number"]

    receipts = out["elevator_receipts"].set_index("receipt_id")
    assert receipts.loc["R1", "grower_id"] == "G4"  # 'Mak Koch' is close only to Mark Koch

    unmatched = out["unmatched"].set_index("record_id")
    assert unmatched.loc["A1", "reason"] == "ambiguous exact name"  # two James Millers in X: refuse
    assert unmatched.loc["A6", "reason"] == "no match"
    assert unmatched.loc["R2", "reason"] == "ambiguous fuzzy name"  # 'Mar Koch' fits Mark and Mary: refuse
    assert unmatched.loc["R3", "reason"] == "no match"
    assert len(out["acreage_reports"]) + len(out["elevator_receipts"]) + len(unmatched) == 7 + 3


def test_same_county_name_in_another_state_is_not_a_match():
    """Boone County exists in Iowa and Illinois. A James Miller in Boone, IL is not the registered one in Boone, IA."""
    growers = pd.DataFrame({"grower_id": ["G1"], "name": ["James Miller"], "county": ["Boone"],
                            "state": ["IA"], "farm_number": [None]})
    acreage = pd.DataFrame({
        "report_id": ["A1", "A2"], "operator_name": ["James Miller", "Jame Miller"], "farm_number": ["F9", "F9"],
        "county": ["Boone", "Boone"], "state": ["IL", "IL"], "season": [2024] * 2, "crop": ["soybeans"] * 2,
        "acres": [100.0] * 2,
    })
    receipts = pd.DataFrame({
        "receipt_id": ["R1"], "seller_name": ["James Miller"], "county": ["Boone"], "state": ["IA"],
        "elevator_id": ["E1"], "season": [2024], "crop": ["soybeans"], "bushels": [1000.0],
    })
    out = resolve({"growers": growers, "acreage_reports": acreage, "elevator_receipts": receipts})
    assert out["acreage_reports"].empty  # neither the exact nor the fuzzy name may cross the state line
    assert out["elevator_receipts"]["grower_id"].tolist() == ["G1"]
    assert set(out["unmatched"]["record_id"]) == {"A1", "A2"}


def test_farm_number_only_matches_within_its_county():
    """FSA assigns farm numbers per county office, so farm 7 in Story, IA and farm 7 in Boone, IA are different farms."""
    growers = pd.DataFrame({"grower_id": ["G1"], "name": ["James Miller"], "county": ["Story"],
                            "state": ["IA"], "farm_number": ["7"]})
    acreage = pd.DataFrame({
        "report_id": ["A1", "A2"], "operator_name": ["Susan Becker", "Susan Becker"], "farm_number": ["7", "7"],
        "county": ["Boone", "Story"], "state": ["IA", "IA"], "season": [2024] * 2, "crop": ["soybeans"] * 2,
        "acres": [100.0] * 2,
    })
    receipts = pd.DataFrame(columns=["receipt_id", "seller_name", "county", "state", "elevator_id", "season", "crop", "bushels"])
    out = resolve({"growers": growers, "acreage_reports": acreage, "elevator_receipts": receipts})
    assert out["acreage_reports"]["report_id"].tolist() == ["A2"]  # same county: the farm number decides
    assert out["unmatched"]["record_id"].tolist() == ["A1"]  # another county's farm 7 is someone else


def _links(tables):
    """Resolver output joined to the ground-truth owner of every record."""
    links = tables["record_links"]
    frames = []
    for table, id_col in (("acreage_reports", "report_id"), ("elevator_receipts", "receipt_id")):
        df = tables[table][[id_col, "grower_id"]].rename(columns={id_col: "record_id", "grower_id": "resolved"})
        frames.append(df)
    resolved = pd.concat(frames)
    return links.merge(resolved, on="record_id", how="left")


@pytest.mark.parametrize("seed", [42, 7])
def test_messy_names_never_produce_a_wrong_link(seed):
    raw = generate(seed=seed)
    out = resolve(raw)
    joined = _links({**out, "record_links": raw["record_links"]})
    matched = joined.dropna(subset=["resolved"])
    assert (matched["resolved"] == matched["grower_id"]).all()  # precision: zero wrong links
    assert len(matched) / len(joined) >= 0.9  # recall stays high
    # tickets from non-customers have no owner: every one of them must stay unmatched
    ownerless = set(raw["elevator_receipts"]["receipt_id"]) - set(raw["record_links"]["record_id"])
    assert ownerless and ownerless <= set(out["unmatched"]["record_id"])
    assert len(out["unmatched"]) == len(joined) - len(matched) + len(ownerless)


def test_clean_names_all_resolve():
    raw = generate(messy_names=False)
    joined = _links({**resolve(raw), "record_links": raw["record_links"]})
    assert joined["resolved"].notna().all()
    assert (joined["resolved"] == joined["grower_id"]).all()


@pytest.mark.parametrize("seed", [42, 7, 2025])
def test_labels_on_messy_data(seed):
    raw = generate(seed=seed)
    out = resolve(raw)
    truth = raw["ground_truth"][["grower_id", "season", "case_type"]]
    scored = score(reconcile(out)).merge(truth, on=["grower_id", "season"])

    # zero false positives, no matter what the resolver missed
    assert (scored.loc[scored.case_type == "clean", "label"] == CONSISTENT).all()
    assert (scored.loc[scored.case_type.isin(["split_brand", "missing_dealer", "neighbor_dealer"]), "label"] != REVIEW).all()

    # every ghost case whose acreage report was linked, and whose grower filed a seed statement, is flagged
    ghost = scored[(scored.case_type == "ghost_seed") & scored.has_acreage & scored.has_statement]
    assert len(ghost) > 0
    assert (ghost["label"] == REVIEW).all()
