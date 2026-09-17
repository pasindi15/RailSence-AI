"""Validate that every M2 operations_history train_id is canonical.

Usage:
    python scripts/validate_shared_train_links.py

This is read-only. It does not modify the CSV or Supabase.
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from shared.train_repository import get_client

DATA_PATH = ROOT / "M2-operations-agent" / "data" / "operations_history.csv"
BATCH_SIZE = 200


def main() -> None:
    with DATA_PATH.open(newline="", encoding="utf-8") as handle:
        ids = sorted({row["train_id"].strip().upper() for row in csv.DictReader(handle) if row.get("train_id")})

    try:
        client = get_client()
        found: set[str] = set()
        for start in range(0, len(ids), BATCH_SIZE):
            response = (
                client.table("trains")
                .select("train_id")
                .in_("train_id", ids[start : start + BATCH_SIZE])
                .execute()
            )
            found.update(row["train_id"].upper() for row in (response.data or []))
    except Exception as exc:
        raise SystemExit(f"TRAIN_REGISTRY_UNAVAILABLE: {exc}") from exc

    missing = sorted(set(ids) - found)
    print(f"M2 distinct operations train IDs: {len(ids)}")
    print(f"Canonical train IDs found: {len(found)}")
    print(f"Missing canonical IDs: {len(missing)}")
    if missing:
        print("Missing IDs:", ", ".join(missing))
        raise SystemExit(1)
    print("PASS: every operations_history.train_id has a canonical trains.train_id")


if __name__ == "__main__":
    main()
