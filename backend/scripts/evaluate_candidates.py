from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from app.ai.decision import CandidateDecisionRouter, RulesDecisionProvider
from app.extraction.candidate_engine import generate_candidates
from app.extraction.unicode_view import candidate_key
from app.identification_mode import IdentificationMode, classify_document


def load_labels(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


async def evaluate(labels_path: Path, docs_dir: Path, boilerplate: set[str] | None = None) -> dict:
    labels = load_labels(labels_path)
    found_positive = 0
    total_positive = sum(bool(x["variable"]) for x in labels)
    decided = right = 0
    details: list[dict] = []
    router = CandidateDecisionRouter([RulesDecisionProvider(boilerplate or set())])

    for draft in sorted({x["draft"] for x in labels}):
        text = (docs_dir / draft).read_text(encoding="utf-8")
        draft_labels = [x for x in labels if x["draft"] == draft]
        requested_mode = next((str(x.get("mode") or "").lower() for x in draft_labels if x.get("mode")), "")
        mode = IdentificationMode(requested_mode) if requested_mode in {"legal", "general"} else classify_document(text)
        candidates = generate_candidates(text, mode)
        await router.decide_all(candidates)
        by_key: dict[str, list] = {}
        for candidate in candidates:
            by_key.setdefault(candidate_key(candidate.original_text), []).append(candidate)
        for label in [x for x in labels if x["draft"] == draft]:
            matches = by_key.get(candidate_key(label["value"]), [])
            if label["variable"] and matches:
                found_positive += 1
            decision = matches[0].classification if matches else None
            if decision and decision != "ambiguous":
                decided += 1
                predicted = decision == "replaceable_value"
                right += int(predicted == bool(label["variable"]))
            details.append({
                "draft": draft,
                "value": label["value"],
                "expectedVariable": bool(label["variable"]),
                "found": bool(matches),
                "ruleDecision": decision,
            })

    return {
        "candidateRecall": 1.0 if total_positive == 0 else found_positive / total_positive,
        "ruleDecisionAccuracy": None if decided == 0 else right / decided,
        "ruleDecisions": decided,
        "labels": len(labels),
        "details": details,
    }


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser()
    parser.add_argument("--labels", type=Path, default=root / "tests" / "candidate_eval" / "variables.jsonl")
    parser.add_argument("--docs", type=Path, default=root / "tests" / "candidate_eval")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    result = asyncio.run(evaluate(args.labels, args.docs, {"PUROHIT LAW ASSOCIATES"}))
    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print(f"candidate recall: {result['candidateRecall']:.3f}")
        accuracy = result["ruleDecisionAccuracy"]
        print(f"rule decision accuracy: {'n/a' if accuracy is None else f'{accuracy:.3f}'} ({result['ruleDecisions']} decided)")


if __name__ == "__main__":
    main()
