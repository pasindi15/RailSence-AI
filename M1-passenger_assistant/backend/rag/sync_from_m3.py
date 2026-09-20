"""
Regenerate the passenger fare FAQ (data/faq_docs/fares.md) from the Booking
Agent's fare table, so the chatbot and the booking system quote the same price.

Source of truth for fares: DEMO_FARE_RULES in
    M3-Comunication-Hub&Booking-Agent/booking-agent/booking/fare.py
(the table booking/fare.py and booking/availability.py actually price from).

The table is read with `ast` instead of imported, so M1's environment does not
need M3's dependencies (SQLAlchemy, database config, ...) and importing this
module never touches M3's database.

Usage (from backend/):
    python -m rag.sync_from_m3           # rewrite data/faq_docs/fares.md
    python -m rag.sync_from_m3 --check   # exit 1 if fares.md is out of date
Then re-embed:  python -m rag.embed_documents

Only fares are generated. Refund/cancellation/booking wording in policies.md is
written by hand for passengers and is checked against M3's rules by
tests/test_source_consistency.py.
"""
import ast
import sys
from decimal import Decimal
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = BACKEND_DIR.parents[1]
M3_FARE_PY = REPO_ROOT / "M3-Comunication-Hub&Booking-Agent" / "booking-agent" / "booking" / "fare.py"
FARES_MD = BACKEND_DIR / "data" / "faq_docs" / "fares.md"

# M3's table keys stations as "colombo"; the passenger-facing name of that
# station (and what M1's NER and the booking UI use) is "Colombo Fort".
# M3's booking/fare.py maps "colombo fort" -> "colombo" the same way.
DISPLAY_NAMES = {"colombo": "Colombo Fort"}

HEADER = (
    "# Fares (reference data - synchronized with the online booking system's fare "
    "table; verify against actual SLR fare chart before final submission)"
)

COVERAGE_SECTION = """## How fares are calculated
- The fare shown for a route is the price per seat. The total fare is the seat fare multiplied by the number of passengers.
- Two classes can be booked online: First Class and Second Class.
- The online booking system applies no discounts or concession rates. Concession fares (for example senior or student rates) are not available through this assistant.
- This assistant only has fares for the routes listed in this document. For any other route it has no confirmed fare and must not estimate one; the passenger should check at a staffed station counter."""


def _eval_node(node: ast.AST):
    """Evaluate the small literal subset used by DEMO_FARE_RULES:
    str/number constants, tuples, dicts and Decimal("...") calls."""
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Tuple):
        return tuple(_eval_node(e) for e in node.elts)
    if isinstance(node, ast.Dict):
        return {_eval_node(k): _eval_node(v) for k, v in zip(node.keys, node.values)}
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "Decimal"
        and len(node.args) == 1
    ):
        return Decimal(_eval_node(node.args[0]))
    raise ValueError(f"unsupported expression in fare table: {ast.dump(node)[:80]}")


def load_m3_fare_rules(path: Path = M3_FARE_PY) -> dict[tuple[str, str], dict[str, Decimal]]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in tree.body:
        target = None
        if isinstance(node, ast.AnnAssign):
            target = node.target
        elif isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
        if isinstance(target, ast.Name) and target.id == "DEMO_FARE_RULES":
            return _eval_node(node.value)
    raise LookupError(f"DEMO_FARE_RULES not found in {path}")


def _display(station: str) -> str:
    return DISPLAY_NAMES.get(station, station.title())


def _money(amount: Decimal) -> str:
    return f"{int(amount):d}" if amount == amount.to_integral_value() else f"{amount:.2f}"


def render_fares_md(rules: dict[tuple[str, str], dict[str, Decimal]]) -> str:
    """One section per route. A route and its reverse with identical fares are
    written once and marked as applying in both directions."""
    sections = []
    done: set[tuple[str, str]] = set()
    for (origin, dest), classes in rules.items():
        if (origin, dest) in done:
            continue
        done.add((origin, dest))
        both_ways = rules.get((dest, origin)) == classes
        if both_ways:
            done.add((dest, origin))
        lines = [f"## {_display(origin)} - {_display(dest)}"]
        for cls, amount in classes.items():
            lines.append(f"- {cls}: LKR {_money(amount)} per seat")
        if both_ways:
            lines.append(
                f"- Same fare in both directions ({_display(origin)} - {_display(dest)} "
                f"and {_display(dest)} - {_display(origin)})"
            )
        sections.append("\n".join(lines))
    return HEADER + "\n\n" + "\n\n".join(sections) + "\n\n" + COVERAGE_SECTION + "\n"


def main(argv: list[str]) -> int:
    expected = render_fares_md(load_m3_fare_rules())
    if "--check" in argv:
        current = FARES_MD.read_text(encoding="utf-8") if FARES_MD.exists() else ""
        if current != expected:
            print(f"OUT OF DATE: {FARES_MD} does not match the Booking Agent fare table. "
                  f"Run: python -m rag.sync_from_m3")
            return 1
        print("fares.md matches the Booking Agent fare table")
        return 0
    FARES_MD.write_text(expected, encoding="utf-8", newline="\n")
    print(f"Wrote {FARES_MD} from {M3_FARE_PY.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
