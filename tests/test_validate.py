from engine.validate import render, run


def test_validation_run_has_no_false_positives_or_wrong_links():
    r = run(range(2))
    assert r["false_positives"] == 0 and r["honest"] > 0
    assert r["wrong_links"] == 0 and r["non_customer_linked"] == 0
    assert r["ghost_judgeable_flagged"] == r["ghost_judgeable"] > 0
    assert r["replant_on_honest"] == 0
    assert r["cleared_by_stated_acres"] == r["flagged"] > 0
    text = render(r)
    assert text.startswith("# Validation report") and "| ghost_seed |" in text
