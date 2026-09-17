"""Seed the shared Supabase train identity registry.

Run after applying ../supabase_shared_trains.sql:
    python scripts/seed_shared_trains.py

The script is intentionally data-only. It does not modify any agent code or
rewrite M2 operations history or M4 maintenance history. It uses the M3
booking seed, M2 historical operations CSV, and M2 dashboard train registry as
existing sources, then upserts by the canonical train_id.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
from collections import Counter
from pathlib import Path
from typing import Any

from supabase import create_client

ROOT = Path(__file__).resolve().parents[1]
M2_CSV = ROOT / "M2-operations-agent" / "data" / "operations_history.csv"
DEFAULT_REPORT = ROOT / "shared_train_ids_report.json"

KNOWN_TRAINS: dict[str, dict[str, Any]] = {
    "PM-4082": {
        "train_name": "Intercity Express",
        "origin_station": "Colombo",
        "destination_station": "Kandy",
        "route": "Colombo - Kandy",
        "train_type": "intercity",
        "active": True,
        "source": "M3 booking seed",
        "class_capacities": {"First Class": 40, "Second Class": 120},
        "current_class_availability": {"First Class": 40, "Second Class": 120},
    },
    "INACT-9999": {
        "train_name": "Maintenance Railcar",
        "origin_station": None,
        "destination_station": None,
        "route": None,
        "train_type": "maintenance",
        "active": False,
        "maintenance_status": "DECOMMISSIONED",
        "source": "M3 booking seed",
    },
    "PM-8056": {
        "train_name": "Podi Menike",
        "origin_station": "Colombo Fort",
        "destination_station": "Badulla",
        "route": "Colombo Fort - Badulla",
        "train_type": "passenger_service",
        "active": True,
        "source": "M2 operations dashboard",
    },
    "IC-1001": {
        "train_name": "Intercity Express",
        "origin_station": "Colombo Fort",
        "destination_station": "Kandy",
        "route": "Colombo Fort - Kandy",
        "train_type": "intercity",
        "active": True,
        "source": "M2 operations dashboard",
    },
    "DM-8055": {
        "train_name": "Night Mail",
        "origin_station": "Colombo Fort",
        "destination_station": "Batticaloa",
        "route": "Colombo Fort - Batticaloa",
        "train_type": "night_service",
        "active": True,
        "source": "M2 operations dashboard",
    },
    "PM-5000": {
        "train_name": "City Express",
        "origin_station": None,
        "destination_station": None,
        "route": None,
        "train_type": "test_fixture",
        "active": True,
        "source": "M3 booking test fixture",
    },
    "EXP-OVERLAP": {
        "train_name": "Overlapping Express",
        "origin_station": None,
        "destination_station": None,
        "route": None,
        "train_type": "test_fixture",
        "active": True,
        "source": "M3 booking test fixture",
    },
}


def load_root_env() -> None:
    env_path = ROOT / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def route_parts(route: str | None) -> tuple[str | None, str | None]:
    if not route or " - " not in route:
        return None, None
    origin, destination = route.split(" - ", 1)
    return origin.strip(), destination.strip()


def infer_type(train_id: str) -> str:
    prefix = train_id.split("-", 1)[0].upper()
    return {
        "IC": "intercity",
        "DM": "night_service",
        "PM": "passenger_service",
        "UD": "passenger_service",
        "YD": "passenger_service",
        "ND": "passenger_service",
    }.get(prefix, "historical_operations")


def load_operations_rows() -> list[dict[str, str]]:
    with M2_CSV.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def build_train_records(rows: list[dict[str, str]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    by_train: dict[str, list[dict[str, str]]] = {}
    for row in rows:
        train_id = row.get("train_id", "").strip().upper()
        if train_id:
            by_train.setdefault(train_id, []).append(row)

    records: dict[str, dict[str, Any]] = {}
    for train_id, observations in by_train.items():
        routes = Counter(row.get("route", "").strip() for row in observations if row.get("route"))
        route = routes.most_common(1)[0][0] if routes else None
        origin, destination = route_parts(route)
        records[train_id] = {
            "train_id": train_id,
            "train_name": f"Historical {train_id}",
            "origin_station": origin,
            "destination_station": destination,
            "route": route,
            "train_type": infer_type(train_id),
            "active": True,
            "maintenance_status": "UNKNOWN",
            "class_capacities": {},
            "current_class_availability": {},
            "metadata": {
                "source": "M2 operations_history.csv",
                "observation_count": len(observations),
                "stations": sorted({row.get("station", "").strip() for row in observations if row.get("station")}),
            },
        }

    for train_id, known in KNOWN_TRAINS.items():
        record = records.setdefault(
            train_id,
            {
                "train_id": train_id,
                "train_name": known.get("train_name", f"Historical {train_id}"),
                "origin_station": known.get("origin_station"),
                "destination_station": known.get("destination_station"),
                "route": known.get("route"),
                "train_type": known.get("train_type", infer_type(train_id)),
                "active": known.get("active", True),
                "maintenance_status": known.get("maintenance_status", "UNKNOWN"),
                "class_capacities": known.get("class_capacities", {}),
                "current_class_availability": known.get("current_class_availability", {}),
                "metadata": {"source": known.get("source", "known project registry")},
            },
        )
        record.update({key: value for key, value in known.items() if key not in {"source"}})
        record.setdefault("metadata", {})["source"] = known.get("source", "known project registry")

    return sorted(records.values(), key=lambda row: row["train_id"]), {
        "m2_operation_distinct_ids": len(by_train),
        "canonical_registry_records": len(records),
        "m2_operation_rows": len(rows),
    }


def build_report(records: list[dict[str, Any]], counts: dict[str, Any]) -> dict[str, Any]:
    return {
        "canonical_identity_rule": "train_id is unique across agents; M4 asset IDs are excluded",
        "counts": counts,
        "train_ids": [record["train_id"] for record in records],
        "sources": {
            "M1": ["backend/data/faq_docs/schedules.md", "backend/nlu/ner_extractor.py"],
            "M2": ["data/operations_history.csv", "main.py"],
            "M3": ["supabase_schema.sql", "booking-agent/database/seed.py"],
            "M4": ["rag/chatbot.py train-name map; asset IDs intentionally excluded"],
        },
        "known_conflicts": [
            "M3 defines PM-4082 as Intercity Express on Colombo -> Kandy; M1 uses unprefixed reference numbers such as 1005 and 1015, so those are not treated as canonical IDs.",
            "M4 maps train names to locomotive asset IDs such as DE-1001 and DE-1002; these are maintenance asset identities, not trains, and are not inserted into trains.",
            "M2 history contains generated historical service IDs with route observations; these remain in the canonical registry as historical identities with generic metadata and do not replace operations_history rows.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Build and report records without writing Supabase")
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT, help="Path for the discovered-ID report")
    args = parser.parse_args()

    load_root_env()
    rows = load_operations_rows()
    records, counts = build_train_records(rows)
    report = build_report(records, counts)
    args.report.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(counts, indent=2))
    print(f"ID report written to {args.report}")

    if args.dry_run:
        print(f"Dry run: prepared {len(records)} train upserts")
        return

    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_SECRET_KEY", os.getenv("SUPABASE_SERVICE_ROLE_KEY"))
    if not url or not key:
        raise SystemExit("SUPABASE_URL and SUPABASE_SECRET_KEY are required")

    client = create_client(url, key)
    client.table("trains").upsert(records, on_conflict="train_id").execute()

    pm = (
        client.table("trains")
        .select("id")
        .eq("train_id", "PM-4082")
        .limit(1)
        .execute()
    )
    if pm.data:
        client.table("train_schedules").upsert(
            [{
                "train_id": pm.data[0]["id"],
                "from_station": "Colombo",
                "to_station": "Kandy",
                "travel_date": "2026-12-03",
                "departure_time": "07:00:00",
                "arrival_time": "10:15:00",
                "first_class_capacity": 40,
                "second_class_capacity": 120,
                "service_status": "SCHEDULED",
            }],
            on_conflict="train_id,travel_date,from_station,to_station",
        ).execute()

    print(f"Upserted {len(records)} canonical train identities")
    print("Upserted the existing PM-4082 booking schedule")


if __name__ == "__main__":
    main()
