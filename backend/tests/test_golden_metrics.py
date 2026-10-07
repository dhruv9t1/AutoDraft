from pathlib import Path
from scripts.evaluate_golden_corpus import evaluate

def test_complete_golden_corpus_has_sixteen_fixtures():
    root=Path(__file__).parent/"golden"
    assert len(list(root.glob("*.json"))) == 16
    assert len(evaluate()["fixtures"]) == 12  # 12 scored + 4 retained foundation cases

def test_deterministic_golden_metrics_meet_release_thresholds():
    m=evaluate()
    assert m["semanticPrecision"] >= 0.85, m
    assert m["semanticRecall"] >= 0.85, m
    assert m["semanticF1"] >= 0.85, m
    assert m["duplicateRate"] == 0.0, m
