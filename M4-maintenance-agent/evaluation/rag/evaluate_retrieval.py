"""Evaluate manual RAG retrieval — P@1, P@3, P@5 and paraphrase robustness.

Usage (from repo root):
    python M4-maintenance-agent/evaluation/rag/evaluate_retrieval.py
"""

import json
import sys
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(AGENT_DIR))

from rag.manual_retriever import retrieve_manual_sections

EVAL_DIR = Path(__file__).parent
METRICS_PATH = EVAL_DIR / "retrieval_metrics.json"
ROBUSTNESS_PATH = EVAL_DIR / "paraphrased_query_robustness.json"

GROUND_TRUTH = [
    {"query": "oil leak diesel engine gasket", "asset_type": "diesel_engine", "fault_type": "oil_leak", "relevant_keywords": ["oil", "gasket", "seal", "engine"]},
    {"query": "overheating radiator coolant flush", "asset_type": "diesel_engine", "fault_type": "overheating", "relevant_keywords": ["cooling", "coolant", "radiator", "temperature"]},
    {"query": "wheel flat spot vibration re-profiling", "asset_type": "bogie", "fault_type": "wheel_flat", "relevant_keywords": ["wheel", "profile", "vibration", "flat"]},
    {"query": "axle bearing noise grease replacement", "asset_type": "bogie", "fault_type": "bearing_noise", "relevant_keywords": ["bearing", "axle", "grease", "vibration"]},
    {"query": "brake pad worn thickness minimum replacement", "asset_type": "brake_system", "fault_type": "pad_worn", "relevant_keywords": ["brake", "pad", "thickness", "wear"]},
    {"query": "signal relay fault intermittent aspect", "asset_type": "signal_unit", "fault_type": "relay_fault", "relevant_keywords": ["signal", "relay", "aspect", "fault"]},
    {"query": "rail crack transverse ultrasonic inspection", "asset_type": "track_section", "fault_type": "rail_crack", "relevant_keywords": ["rail", "crack", "ultrasonic", "defect"]},
    {"query": "track ballast void tamping geometry", "asset_type": "track_section", "fault_type": "ballast_shortage", "relevant_keywords": ["ballast", "tamping", "geometry", "track"]},
    {"query": "brake cylinder air leak piston seal", "asset_type": "brake_system", "fault_type": "cylinder_leak", "relevant_keywords": ["brake", "cylinder", "seal", "air", "pressure"]},
    {"query": "point motor jam slide chair lubrication", "asset_type": "signal_unit", "fault_type": "point_motor_jam", "relevant_keywords": ["point", "motor", "slide", "lubrication"]},
]

PARAPHRASED_QUERIES = [
    {"query": "engine dripping fluid under frame", "asset_type": "diesel_engine", "fault_type": "oil_leak", "relevant_keywords": ["oil", "engine", "seal"]},
    {"query": "train got very hot and stopped automatically", "asset_type": "diesel_engine", "fault_type": "overheating", "relevant_keywords": ["temperature", "cooling", "coolant"]},
    {"query": "clicking and thumping from undercarriage at low speed", "asset_type": "bogie", "fault_type": "wheel_flat", "relevant_keywords": ["wheel", "vibration", "profile"]},
    {"query": "train taking longer to slow down", "asset_type": "brake_system", "fault_type": "brake_fade", "relevant_keywords": ["brake", "stopping", "distance"]},
    {"query": "green light showing at wrong time", "asset_type": "signal_unit", "fault_type": "relay_fault", "relevant_keywords": ["signal", "relay", "aspect"]},
    {"query": "ground subsiding under track", "asset_type": "track_section", "fault_type": "ballast_shortage", "relevant_keywords": ["ballast", "track", "geometry"]},
]


def is_relevant(section: dict, relevant_keywords: list[str]) -> bool:
    text = f"{section.get('section_title', '')} {section.get('content', '')}".lower()
    return any(kw.lower() in text for kw in relevant_keywords)


def precision_at_k(results: list[dict], relevant_keywords: list[str], k: int) -> float:
    top_k = results[:k]
    if not top_k:
        return 0.0
    hits = sum(1 for r in top_k if is_relevant(r, relevant_keywords))
    return hits / k


def evaluate(queries: list[dict], label: str) -> dict:
    p1_scores, p3_scores, p5_scores = [], [], []
    for q in queries:
        results, method = retrieve_manual_sections(
            q["query"], asset_type=q["asset_type"], fault_type=q["fault_type"], top_k=5
        )
        p1_scores.append(precision_at_k(results, q["relevant_keywords"], 1))
        p3_scores.append(precision_at_k(results, q["relevant_keywords"], 3))
        p5_scores.append(precision_at_k(results, q["relevant_keywords"], 5))

    n = len(queries)
    return {
        "label": label,
        "n_queries": n,
        "precision_at_1": round(sum(p1_scores) / n, 4),
        "precision_at_3": round(sum(p3_scores) / n, 4),
        "precision_at_5": round(sum(p5_scores) / n, 4),
    }


def main() -> None:
    EVAL_DIR.mkdir(parents=True, exist_ok=True)

    print("Evaluating on ground-truth queries...")
    metrics = evaluate(GROUND_TRUTH, "ground_truth_template_queries")
    METRICS_PATH.write_text(json.dumps(metrics, indent=2))
    print(f"P@1={metrics['precision_at_1']}  P@3={metrics['precision_at_3']}  P@5={metrics['precision_at_5']}")
    print(f"Saved -> {METRICS_PATH}")

    print("\nEvaluating paraphrased robustness queries...")
    robustness = evaluate(PARAPHRASED_QUERIES, "paraphrased_robustness")
    ROBUSTNESS_PATH.write_text(json.dumps(robustness, indent=2))
    print(f"P@1={robustness['precision_at_1']}  P@3={robustness['precision_at_3']}  P@5={robustness['precision_at_5']}")
    print(f"Saved -> {ROBUSTNESS_PATH}")


if __name__ == "__main__":
    main()
