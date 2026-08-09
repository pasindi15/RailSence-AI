"""Phase 4 retrieval evaluation.

This evaluation uses same-category agreement as an explicit relevance proxy:
for each held-out incident note, a retrieved result counts as relevant when
it has the same ground-truth incident_type. It reports P@1, P@3, and P@5,
plus category-level P@5. It also evaluates six hand-written paraphrases to
show how the lexical fallback behaves outside the generated templates.

Run from the repository root:
    python M2-operations-agent/evaluation/rag/evaluate_retrieval.py

This does not require a pre-built index. The retriever lazily builds its
local TF-IDF index, or uses Supabase pgvector when configured.
"""

import json
import sys
from pathlib import Path

import pandas as pd

AGENT_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(AGENT_DIR))
from rag.incident_retriever import retrieve_similar_incidents  # noqa: E402

DATA_PATH = AGENT_DIR / "data" / "operations_history.csv"
OUT_DIR = Path(__file__).resolve().parent
SAMPLE_SIZE = 150
K_VALUES = [1, 3, 5]
RANDOM_STATE = 42

PARAPHRASE_CASES = [
    {"text": "The signal stayed red and trains had to wait for the control team.", "expected_type": "signal_fault"},
    {"text": "The locomotive developed a brake problem and was taken out for inspection.", "expected_type": "mechanical"},
    {"text": "Water on the line reduced visibility and trains were ordered to slow down.", "expected_type": "weather"},
    {"text": "A tree fell across the track and blocked the next service.", "expected_type": "track_obstruction"},
    {"text": "The driver relief arrived late, delaying dispatch from the platform.", "expected_type": "staffing"},
    {"text": "A technical problem interrupted the train service near the station.", "expected_type": "mechanical"},
]


def _retrieve(query: str, top_k: int, record_id: str | None = None) -> dict:
    return retrieve_similar_incidents(query, top_k=top_k, exclude_record_id=record_id)


def evaluate_dataset(df: pd.DataFrame) -> dict:
    labelled = df[(df["incident_type"] != "none") & (df["incident_note"].str.len() > 0)]
    sample = labelled.sample(n=min(SAMPLE_SIZE, len(labelled)), random_state=RANDOM_STATE)
    max_k = max(K_VALUES)
    query_hits: list[list[bool]] = []
    category_hits: dict[str, list[list[bool]]] = {}

    for _, row in sample.iterrows():
        result = _retrieve(row["incident_note"], max_k, str(row["record_id"]))
        hits = [item["incident_type"] == row["incident_type"] for item in result["incidents"]]
        hits += [False] * (max_k - len(hits))
        query_hits.append(hits)
        category_hits.setdefault(row["incident_type"], []).append(hits)

    metrics = {
        "backend": _retrieve("evaluation probe", 1)["method"],
        "relevance_proxy": "retrieved incident shares the query incident_type",
        "n_queries": len(sample),
        "precision_at_k": {},
        "precision_at_5_by_category": {},
    }
    for k in K_VALUES:
        scores = [sum(hits[:k]) / k for hits in query_hits]
        metrics["precision_at_k"][f"p@{k}"] = round(sum(scores) / len(scores), 4)
    for category, hit_lists in sorted(category_hits.items()):
        scores = [sum(hits[:5]) / 5 for hits in hit_lists]
        metrics["precision_at_5_by_category"][category] = {
            "n_queries": len(hit_lists),
            "precision_at_5": round(sum(scores) / len(scores), 4),
        }
    return metrics


def evaluate_paraphrases() -> dict:
    results = []
    for case in PARAPHRASE_CASES:
        retrieved = _retrieve(case["text"], 5)["incidents"]
        types = [item["incident_type"] for item in retrieved]
        results.append(
            {
                "query": case["text"],
                "expected_type": case["expected_type"],
                "top_1_type": types[0] if types else None,
                "top_3_types": types[:3],
                "top_1_match": bool(types and types[0] == case["expected_type"]),
                "top_3_match": case["expected_type"] in types[:3],
                "retrieved_incidents": retrieved[:3],
            }
        )
    return {
        "backend": _retrieve("paraphrase probe", 1)["method"],
        "relevance_proxy": "top-k retrieved incident has the hand-written expected_type",
        "n_queries": len(results),
        "top_1_accuracy": round(sum(item["top_1_match"] for item in results) / len(results), 4),
        "top_3_recall": round(sum(item["top_3_match"] for item in results) / len(results), 4),
        "limitations": "These six queries are hand-written stress tests, not a statistically representative labelled test set.",
        "results": results,
    }


def main() -> None:
    df = pd.read_csv(DATA_PATH)
    print("Evaluating retrieval with same-category agreement as the relevance proxy...")
    metrics = evaluate_dataset(df)
    paraphrase_metrics = evaluate_paraphrases()
    print(json.dumps(metrics, indent=2))
    print("\nEvaluating hand-written paraphrased queries...")
    print(json.dumps(paraphrase_metrics, indent=2))

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "retrieval_metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    (OUT_DIR / "paraphrased_query_robustness.json").write_text(json.dumps(paraphrase_metrics, indent=2), encoding="utf-8")
    print(f"\nSaved -> {OUT_DIR / 'retrieval_metrics.json'}")
    print(f"Saved -> {OUT_DIR / 'paraphrased_query_robustness.json'}")


if __name__ == "__main__":
    main()
