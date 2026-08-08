"""
M2 — Operations & Delay-Prediction Agent
Phase 3: NLP evaluation.

The dataset (operations_history.csv) was generated with a known
incident_type per row and a matching templated incident_note. That gives
us real ground-truth labels to evaluate the rule-based classifier against
— not a guess, an actual measured accuracy/precision/recall/F1.

Summarization has no ground-truth "correct summary" to compare against, so
it's evaluated qualitatively: this script also dumps a handful of example
summaries (short + long/multi-sentence) for manual review, per the
project's requirement to report real evidence rather than invented scores.

Run:
    python evaluate_nlp.py
"""

import json
from pathlib import Path

import pandas as pd
from sklearn.metrics import classification_report

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from classify_incident import classify_incident
from summarize_incident import summarize_incident

THIS_DIR = Path(__file__).resolve().parent
DATA_PATH = THIS_DIR.parent / "data" / "operations_history.csv"
OUT_DIR = THIS_DIR.parent / "evaluation" / "nlp"

SAMPLE_SIZE = 400
RANDOM_STATE = 42


def evaluate_classification(df: pd.DataFrame) -> dict:
    labelled = df[(df["incident_type"] != "none") & (df["incident_note"].str.len() > 0)]
    sample = labelled.sample(n=min(SAMPLE_SIZE, len(labelled)), random_state=RANDOM_STATE)

    y_true = sample["incident_type"].tolist()
    y_pred = [classify_incident(text)["classified_type"] for text in sample["incident_note"]]

    report = classification_report(y_true, y_pred, output_dict=True, zero_division=0)
    accuracy = report.pop("accuracy")

    return {
        "n_samples": len(sample),
        "accuracy": round(accuracy, 4),
        "per_class": {
            label: {
                "precision": round(vals["precision"], 4),
                "recall": round(vals["recall"], 4),
                "f1": round(vals["f1-score"], 4),
                "support": int(vals["support"]),
            }
            for label, vals in report.items()
            if label not in ("macro avg", "weighted avg")
        },
        "macro_avg": {
            "precision": round(report["macro avg"]["precision"], 4),
            "recall": round(report["macro avg"]["recall"], 4),
            "f1": round(report["macro avg"]["f1-score"], 4),
        },
    }


def sample_summarization_examples(df: pd.DataFrame, n: int = 8) -> list[dict]:
    labelled = df[(df["incident_type"] != "none") & (df["incident_note"].str.len() > 0)]
    sample = labelled.sample(n=min(n, len(labelled)), random_state=RANDOM_STATE)

    # Add one synthetic long, multi-sentence log so the extractive path
    # (not just pass-through) is represented in the evaluation record.
    synthetic_long_log = (
        "At approximately 09:15 the driver reported unusual vibration from "
        "the rear bogie while approaching the station. The train was "
        "brought to a controlled stop at the platform for inspection. "
        "Maintenance staff examined the wheel assembly and found a worn "
        "brake pad. A replacement part was sourced from the depot and "
        "fitted within 40 minutes. The train resumed service after a "
        "final safety check by the duty engineer."
    )

    examples = []
    for _, row in sample.iterrows():
        result = summarize_incident(row["incident_note"])
        examples.append(
            {
                "ground_truth_type": row["incident_type"],
                "raw_text": row["incident_note"],
                "summary": result["summary"],
                "method": result["method"],
            }
        )

    long_result = summarize_incident(synthetic_long_log)
    examples.append(
        {
            "ground_truth_type": "mechanical (synthetic multi-sentence log)",
            "raw_text": synthetic_long_log,
            "summary": long_result["summary"],
            "method": long_result["method"],
        }
    )

    return examples


def main():
    df = pd.read_csv(DATA_PATH)
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    print("Evaluating classification against ground-truth incident_type labels...")
    classification_metrics = evaluate_classification(df)
    print(json.dumps(classification_metrics, indent=2))

    with open(OUT_DIR / "classification_metrics.json", "w") as f:
        json.dump(classification_metrics, f, indent=2)
    print(f"\nSaved -> {OUT_DIR / 'classification_metrics.json'}")

    print("\nGenerating summarization examples for qualitative review...")
    summarization_examples = sample_summarization_examples(df)
    with open(OUT_DIR / "summarization_examples.json", "w") as f:
        json.dump(summarization_examples, f, indent=2)
    print(f"Saved -> {OUT_DIR / 'summarization_examples.json'}")


if __name__ == "__main__":
    main()
