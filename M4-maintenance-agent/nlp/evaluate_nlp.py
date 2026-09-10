"""Evaluate NLP components against ground-truth labels in assets_history.csv.

Usage (from repo root):
    python M4-maintenance-agent/nlp/evaluate_nlp.py
"""

import json
import sys
from collections import defaultdict
from pathlib import Path

import pandas as pd

AGENT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(AGENT_DIR))

from nlp.extract_notes import extract_rule_based
from nlp.summarize_report import summarize_rule_based

DATA_PATH = AGENT_DIR / "data" / "assets_history.csv"
EVAL_DIR = AGENT_DIR / "evaluation" / "nlp"
METRICS_PATH = EVAL_DIR / "classification_metrics.json"
EXAMPLES_PATH = EVAL_DIR / "summarization_examples.json"
ROBUSTNESS_PATH = EVAL_DIR / "out_of_template_robustness_check.json"

PARAPHRASED_CASES = [
    {"text": "Oil coming out from underneath the engine, left stains on the platform.", "expected": "oil_leak"},
    {"text": "The engine ran hot and shut down automatically near Kandy station.", "expected": "overheating"},
    {"text": "Could not get the engine running this morning, took 4 attempts.", "expected": "starter_failure"},
    {"text": "Wheels making a flat thumping sound when moving slowly.", "expected": "wheel_flat"},
    {"text": "Train stopping distance seems longer than usual, feel like brakes not gripping.", "expected": "brake_fade"},
    {"text": "Signal showing wrong aspect intermittently, may be internal fault.", "expected": "relay_fault"},
]


def precision_recall_f1(tp: int, fp: int, fn: int) -> dict:
    p = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    r = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1 = 2 * p * r / (p + r) if (p + r) > 0 else 0.0
    return {"precision": round(p, 4), "recall": round(r, 4), "f1": round(f1, 4)}


def evaluate_classification(df: pd.DataFrame) -> dict:
    non_none = df[df["fault_type"] != "none"]
    sample = non_none.sample(min(400, len(non_none)), random_state=42)
    tp_map: dict[str, int] = defaultdict(int)
    fp_map: dict[str, int] = defaultdict(int)
    fn_map: dict[str, int] = defaultdict(int)
    correct = 0

    for _, row in sample.iterrows():
        note = str(row["technician_note"])
        true_label = str(row["fault_type"])
        pred = extract_rule_based(note)["detected_fault_type"]
        if pred == true_label:
            tp_map[true_label] += 1
            correct += 1
        else:
            fp_map[pred] += 1
            fn_map[true_label] += 1

    per_class = {}
    for label in set(list(tp_map.keys()) + list(fn_map.keys())):
        per_class[label] = precision_recall_f1(tp_map[label], fp_map[label], fn_map[label])

    macro_p = sum(v["precision"] for v in per_class.values()) / max(len(per_class), 1)
    macro_r = sum(v["recall"] for v in per_class.values()) / max(len(per_class), 1)
    macro_f1 = sum(v["f1"] for v in per_class.values()) / max(len(per_class), 1)

    return {
        "total_samples": len(sample),
        "correct": correct,
        "accuracy": round(correct / len(sample), 4),
        "macro_precision": round(macro_p, 4),
        "macro_recall": round(macro_r, 4),
        "macro_f1": round(macro_f1, 4),
        "per_class": per_class,
    }


def evaluate_summarization(df: pd.DataFrame) -> list[dict]:
    sample = df.sample(min(5, len(df)), random_state=7)
    examples = []
    for _, row in sample.iterrows():
        raw = str(row["technician_note"])
        summary = summarize_rule_based(raw)
        examples.append({
            "asset_type": row["asset_type"],
            "fault_type": row["fault_type"],
            "raw_note": raw,
            "summary": summary,
        })
    return examples


def evaluate_robustness() -> list[dict]:
    results = []
    for case in PARAPHRASED_CASES:
        pred = extract_rule_based(case["text"])["detected_fault_type"]
        results.append({
            "text": case["text"],
            "expected": case["expected"],
            "predicted": pred,
            "correct": pred == case["expected"],
        })
    correct = sum(1 for r in results if r["correct"])
    print(f"Paraphrase robustness: {correct}/{len(results)} correct ({correct/len(results):.0%})")
    return results


def main() -> None:
    if not DATA_PATH.exists():
        print(f"Dataset not found at {DATA_PATH}. Run data/generate_dataset.py first.")
        sys.exit(1)

    df = pd.read_csv(DATA_PATH)
    EVAL_DIR.mkdir(parents=True, exist_ok=True)

    print("Evaluating classification...")
    metrics = evaluate_classification(df)
    METRICS_PATH.write_text(json.dumps(metrics, indent=2))
    print(f"Accuracy: {metrics['accuracy']:.4f}  Macro-F1: {metrics['macro_f1']:.4f}")
    print(f"Saved -> {METRICS_PATH}")

    print("\nGenerating summarization examples...")
    examples = evaluate_summarization(df)
    EXAMPLES_PATH.write_text(json.dumps(examples, indent=2))
    print(f"Saved -> {EXAMPLES_PATH}")

    print("\nRunning robustness check...")
    robustness = evaluate_robustness()
    ROBUSTNESS_PATH.write_text(json.dumps(robustness, indent=2))
    print(f"Saved -> {ROBUSTNESS_PATH}")


if __name__ == "__main__":
    main()
