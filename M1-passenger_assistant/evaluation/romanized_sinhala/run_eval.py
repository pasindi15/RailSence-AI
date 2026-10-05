"""
Offline evaluation for romanized-Sinhala ("Singlish") NLU support.

Runs detect_language / classify_intent / extract_entities directly against
queries.csv - no server, no LLM, no network - so it is fast, free and
repeatable, and can be re-run against the "before" code (git stash the
backend/ changes, keep this eval folder, re-run) to produce a before/after
comparison.

Usage (from repo root or anywhere):
    <backend-venv-python> evaluation/romanized_sinhala/run_eval.py
"""
import csv
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[2] / "backend"
sys.path.insert(0, str(BACKEND_DIR))

from nlu import ner_extractor  # noqa: E402
# No live LLM calls during evaluation - matches tests/conftest.py's autouse
# fixture, which does the same thing for the pytest suite.
ner_extractor._llm_model = None

from nlu.lang_detect import detect_language  # noqa: E402
from nlu.intent_classifier import classify_intent  # noqa: E402
from nlu.ner_extractor import extract_entities  # noqa: E402

QUERIES_CSV = Path(__file__).parent / "queries.csv"
RESULTS_MD = Path(__file__).parent / "results.md"


def _norm_expected(value: str | None) -> str | None:
    return value if value else None


def evaluate() -> list[dict]:
    rows = []
    with open(QUERIES_CSV, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            text = row["text"]
            expected_language = row["expected_language"]
            expected_intent = row["expected_intent"]
            expected_from = _norm_expected(row["expected_from"])
            expected_to = _norm_expected(row["expected_to"])

            language = detect_language(text)
            intent = classify_intent(text)
            entities = extract_entities(text)

            rows.append({
                "id": row["id"],
                "text": text,
                "expected_language": expected_language, "language": language,
                "expected_intent": expected_intent, "intent": intent,
                "expected_from": expected_from, "from_station": entities.get("from_station"),
                "expected_to": expected_to, "to_station": entities.get("to_station"),
                "language_ok": language == expected_language,
                "intent_ok": intent == expected_intent,
                "from_ok": entities.get("from_station") == expected_from,
                "to_ok": entities.get("to_station") == expected_to,
            })
    return rows


def summarize(rows: list[dict]) -> str:
    n = len(rows)
    language_acc = sum(r["language_ok"] for r in rows) / n
    intent_acc = sum(r["intent_ok"] for r in rows) / n
    from_acc = sum(r["from_ok"] for r in rows) / n
    to_acc = sum(r["to_ok"] for r in rows) / n
    overall_acc = sum(r["language_ok"] and r["intent_ok"] and r["from_ok"] and r["to_ok"] for r in rows) / n

    lines = [
        f"# Romanized Sinhala NLU evaluation ({n} queries)",
        "",
        "| Metric | Accuracy |",
        "|---|---|",
        f"| Language detection | {language_acc:.1%} |",
        f"| Intent classification | {intent_acc:.1%} |",
        f"| Origin station (from_station) | {from_acc:.1%} |",
        f"| Destination station (to_station) | {to_acc:.1%} |",
        f"| **All four fields correct** | **{overall_acc:.1%}** |",
        "",
        "## Failures",
        "",
    ]
    failures = [r for r in rows if not (r["language_ok"] and r["intent_ok"] and r["from_ok"] and r["to_ok"])]
    if not failures:
        lines.append("None.")
    else:
        lines.append("| id | text | expected (lang/intent/from/to) | got (lang/intent/from/to) |")
        lines.append("|---|---|---|---|")
        for r in failures:
            expected = f"{r['expected_language']}/{r['expected_intent']}/{r['expected_from'] or '-'}/{r['expected_to'] or '-'}"
            got = f"{r['language']}/{r['intent']}/{r['from_station'] or '-'}/{r['to_station'] or '-'}"
            lines.append(f"| {r['id']} | {r['text']} | {expected} | {got} |")
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    results = evaluate()
    report = summarize(results)
    print(report)
    RESULTS_MD.write_text(report, encoding="utf-8")
    print(f"\nWrote {RESULTS_MD}")
