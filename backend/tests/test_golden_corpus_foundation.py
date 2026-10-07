from __future__ import annotations

import json
from pathlib import Path

GOLDEN = Path(__file__).parent / "golden"


def test_golden_corpus_annotations_are_grounded_and_well_formed():
    specs = sorted(GOLDEN.glob("*.json"))
    assert len(specs) >= 4
    for spec_path in specs:
        text_path = spec_path.with_suffix(".txt")
        assert text_path.exists()
        document = text_path.read_text(encoding="utf-8")
        spec = json.loads(spec_path.read_text(encoding="utf-8"))
        assert isinstance(spec.get("fields"), list)
        assert isinstance(spec.get("mustNotDetect"), list)
        for field in spec["fields"]:
            assert field["sourceText"] in document
            assert field["semanticKey"]
            assert field["replaceable"] is True
        for forbidden in spec["mustNotDetect"]:
            assert forbidden in document
