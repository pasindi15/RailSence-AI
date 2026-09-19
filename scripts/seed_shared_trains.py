"""Seed the shared Supabase train identity registry.

Run after applying ../supabase_shared_trains.sql:
    python scripts/seed_shared_trains.py

The script is intentionally data-only. It does not modify any agent code or
rewrite M2 operations history or M4 maintenance history. It uses the M3
booking seed, M2 historical operations CSV, and M2 dashboard train registry as
existing sources, then upserts by the canonical train_id.
"""

from __future__ import annotations

from typing import Any

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
        "origin_station": "Colombo Fort",
        "destination_station": "Kandy",
        "route": "Colombo Fort - Kandy",
        "train_type": "intercity",
        "active": True,
        "source": "M3 booking seed",
        "class_capacities": {"First Class": 40, "Second Class": 120},
        "current_class_availability": {"First Class": 40, "Second Class": 120},
        "metadata": {
            "source": "M3 booking seed",
            "stops": ["Colombo Fort", "Ragama", "Gampaha", "Veyangoda", "Polgahawela", "Rambukkana", "Kandy"],
            "stop_times": {
                "Colombo Fort": {"dep": "14:35"},
                "Ragama": {"arr": "14:55", "dep": "14:57"},
                "Gampaha": {"arr": "15:10", "dep": "15:12"},
                "Veyangoda": {"arr": "15:25", "dep": "15:27"},
                "Polgahawela": {"arr": "16:05", "dep": "16:08"},
                "Rambukkana": {"arr": "16:25", "dep": "16:28"},
                "Kandy": {"arr": "17:10"}
            },
            "operating_days": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
        },
    },
    "IC-8746": {
        "train_name": "Intercity Express",
        "origin_station": "Colombo Fort",
        "destination_station": "Kandy",
        "route": "Colombo Fort - Kandy",
        "train_type": "intercity",
        "active": True,
        "source": "M2 operations history",
        "class_capacities": {"First Class": 45, "Second Class": 130},
        "current_class_availability": {"First Class": 45, "Second Class": 130},
        "metadata": {
            "source": "M2 operations history",
            "stops": ["Colombo Fort", "Ragama", "Gampaha", "Polgahawela", "Peradeniya", "Kandy"],
            "stop_times": {
                "Colombo Fort": {"dep": "06:00"},
                "Ragama": {"arr": "06:18", "dep": "06:20"},
                "Gampaha": {"arr": "06:33", "dep": "06:35"},
                "Polgahawela": {"arr": "07:22", "dep": "07:25"},
                "Peradeniya": {"arr": "08:18", "dep": "08:21"},
                "Kandy": {"arr": "08:35"}
            },
            "operating_days": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
        },
    },
    "YD-9337": {
        "train_name": "Historical YD-9337",
        "origin_station": "Colombo Fort",
        "destination_station": "Kandy",
        "route": "Colombo Fort - Kandy",
        "train_type": "passenger_service",
        "active": True,
        "source": "M2 operations history",
        "class_capacities": {"First Class": 30, "Second Class": 100},
        "current_class_availability": {"First Class": 30, "Second Class": 100},
        "metadata": {
            "source": "M2 operations history",
            "stops": ["Colombo Fort", "Gampaha", "Veyangoda", "Polgahawela", "Kadugannawa", "Peradeniya", "Kandy"],
            "stop_times": {
                "Colombo Fort": {"dep": "10:30"},
                "Gampaha": {"arr": "11:05", "dep": "11:08"},
                "Veyangoda": {"arr": "11:22", "dep": "11:25"},
                "Polgahawela": {"arr": "12:00", "dep": "12:04"},
                "Kadugannawa": {"arr": "12:45", "dep": "12:48"},
                "Peradeniya": {"arr": "13:00", "dep": "13:03"},
                "Kandy": {"arr": "13:15"}
            },
            "operating_days": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
        },
    },
    "PM-8056": {
        "train_name": "Podi Menike",
        "origin_station": "Colombo Fort",
        "destination_station": "Badulla",
        "route": "Colombo Fort - Badulla",
        "train_type": "passenger_service",
        "active": True,
        "source": "M2 operations dashboard",
        "class_capacities": {"First Class": 40, "Second Class": 120},
        "current_class_availability": {"First Class": 40, "Second Class": 120},
        "metadata": {
            "source": "M2 operations dashboard",
            "stops": ["Colombo Fort", "Ragama", "Polgahawela", "Peradeniya", "Nanu Oya", "Ella", "Badulla"],
            "stop_times": {
                "Colombo Fort": {"dep": "05:55"},
                "Ragama": {"arr": "06:15", "dep": "06:17"},
                "Polgahawela": {"arr": "07:18", "dep": "07:22"},
                "Peradeniya": {"arr": "08:35", "dep": "08:40"},
                "Nanu Oya": {"arr": "12:45", "dep": "12:50"},
                "Ella": {"arr": "14:40", "dep": "14:45"},
                "Badulla": {"arr": "15:15"}
            },
            "operating_days": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
        },
    },
    "IC-1001": {
        "train_name": "Intercity Express",
        "origin_station": "Colombo Fort",
        "destination_station": "Kandy",
        "route": "Colombo Fort - Kandy",
        "train_type": "intercity",
        "active": True,
        "source": "M2 operations dashboard",
        "class_capacities": {"First Class": 40, "Second Class": 120},
        "current_class_availability": {"First Class": 40, "Second Class": 120},
        "metadata": {
            "source": "M2 operations dashboard",
            "stops": ["Colombo Fort", "Ragama", "Gampaha", "Polgahawela", "Peradeniya", "Kandy"],
            "stop_times": {
                "Colombo Fort": {"dep": "16:35"},
                "Ragama": {"arr": "16:55", "dep": "16:57"},
                "Gampaha": {"arr": "17:12", "dep": "17:15"},
                "Polgahawela": {"arr": "18:05", "dep": "18:08"},
                "Peradeniya": {"arr": "19:20", "dep": "19:23"},
                "Kandy": {"arr": "19:40"}
            },
            "operating_days": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
        },
    },
    "DM-8055": {
        "train_name": "Night Mail",
        "origin_station": "Colombo Fort",
        "destination_station": "Batticaloa",
        "route": "Colombo Fort - Batticaloa",
        "train_type": "night_service",
        "active": True,
        "source": "M2 operations dashboard",
        "class_capacities": {"First Class": 25, "Second Class": 90},
        "current_class_availability": {"First Class": 25, "Second Class": 90},
        "metadata": {
            "source": "M2 operations dashboard",
            "stops": ["Colombo Fort", "Ragama", "Polgahawela", "Kurunegala", "Maho", "Habarana", "Batticaloa"],
            "stop_times": {
                "Colombo Fort": {"dep": "19:15"},
                "Ragama": {"arr": "19:35", "dep": "19:37"},
                "Polgahawela": {"arr": "20:45", "dep": "20:48"},
                "Kurunegala": {"arr": "21:15", "dep": "21:18"},
                "Maho": {"arr": "22:00", "dep": "22:03"},
                "Habarana": {"arr": "23:30", "dep": "23:33"},
                "Batticaloa": {"arr": "04:30"}
            },
            "operating_days": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
        },
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
        # Deep-merge: apply KNOWN_TRAINS fields, preserving CSV observations in metadata
        existing_metadata = record.get("metadata", {})
        known_metadata = known.get("metadata", {})
        record.update({key: value for key, value in known.items() if key not in {"source", "metadata"}})
        # Merge metadata: KNOWN_TRAINS values take priority, but keep CSV observation data
        merged_metadata = {**existing_metadata, **known_metadata}
        merged_metadata["source"] = known.get("source", "known project registry")
        record["metadata"] = merged_metadata

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

    # Batch the trains upsert to stay within Supabase row-per-request limits
    BATCH_SIZE = 500
    for i in range(0, len(records), BATCH_SIZE):
        client.table("trains").upsert(records[i : i + BATCH_SIZE], on_conflict="train_id").execute()

    target_trains = (
        client.table("trains")
        .select("id, train_id")
        .in_("train_id", ["PM-4082", "IC-8746", "YD-9337", "PM-8056", "IC-1001", "DM-8055"])
        .execute()
        .data or []
    )
    # pyrefly: ignore [bad-index, unsupported-operation]
    train_id_map = {t["train_id"]: t["id"] for t in target_trains}

    from datetime import date, timedelta
    start_dt = date(2026, 9, 18)
    date_list = [(start_dt + timedelta(days=i)).isoformat() for i in range(25)]
    date_list.append("2026-12-03")

    schedule_templates = [
        {
            "train_key": "PM-4082",
            "from_station": "Colombo Fort",
            "to_station": "Kandy",
            "departure_time": "14:35:00",
            "arrival_time": "17:10:00",
            "first_class_capacity": 40,
            "second_class_capacity": 120,
            "service_status": "SCHEDULED",
        },
        {
            "train_key": "IC-8746",
            "from_station": "Colombo Fort",
            "to_station": "Kandy",
            "departure_time": "06:00:00",
            "arrival_time": "08:35:00",
            "first_class_capacity": 45,
            "second_class_capacity": 130,
            "service_status": "SCHEDULED",
        },
        {
            "train_key": "YD-9337",
            "from_station": "Colombo Fort",
            "to_station": "Kandy",
            "departure_time": "10:30:00",
            "arrival_time": "13:15:00",
            "first_class_capacity": 30,
            "second_class_capacity": 100,
            "service_status": "SCHEDULED",
        },
        {
            "train_key": "IC-1001",
            "from_station": "Colombo Fort",
            "to_station": "Kandy",
            "departure_time": "16:35:00",
            "arrival_time": "19:40:00",
            "first_class_capacity": 40,
            "second_class_capacity": 120,
            "service_status": "SCHEDULED",
        },
        {
            "train_key": "PM-8056",
            "from_station": "Colombo Fort",
            "to_station": "Badulla",
            "departure_time": "05:55:00",
            "arrival_time": "15:15:00",
            "first_class_capacity": 40,
            "second_class_capacity": 120,
            "service_status": "SCHEDULED",
        },
        {
            "train_key": "DM-8055",
            "from_station": "Colombo Fort",
            "to_station": "Batticaloa",
            "departure_time": "19:15:00",
            "arrival_time": "04:30:00",
            "first_class_capacity": 25,
            "second_class_capacity": 90,
            "service_status": "SCHEDULED",
        },
    ]

    schedules_to_upsert = []
    for d in date_list:
        for tmpl in schedule_templates:
            pk = train_id_map.get(tmpl["train_key"])
            if not pk:
                continue
            # Colombo Fort schedule
            row: dict[str, Any] = dict(tmpl)
            del row["train_key"]
            row["train_id"] = pk
            row["travel_date"] = d
            schedules_to_upsert.append(row)
            # Colombo alias schedule for backwards compatibility
            alias_row = dict(row)
            alias_row["from_station"] = "Colombo"
            schedules_to_upsert.append(alias_row)

    for i in range(0, len(schedules_to_upsert), 100):
        client.table("train_schedules").upsert(
            schedules_to_upsert[i : i + 100],
            on_conflict="train_id,travel_date,from_station,to_station",
        ).execute()

    print(f"Upserted {len(records)} canonical train identities")
    print(f"Upserted {len(schedules_to_upsert)} canonical train schedules across {len(date_list)} dates")


if __name__ == "__main__":
    main()
