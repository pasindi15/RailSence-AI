"""Generate synthetic railway asset maintenance dataset for M4.

Produces exactly 24 assets (3 per train × 8 trains):
  diesel_engine (DE-xxxx), bogie (BG-xxxx), brake_system (BR-xxxx)

25 history records per asset = 600 rows total (matches Supabase import).
The most-recent record per asset represents current health.
"""

import csv
import random
import uuid
from datetime import datetime, timedelta
from pathlib import Path

random.seed(42)

# ── Exact 24 assets tied to the 8 SLR trains ──────────────────────────────────
TRAIN_ASSETS = [
    # Udarata Menike  (Colombo Fort → Badulla)
    {"asset_id": "DE-1001", "asset_type": "diesel_engine", "train": "Udarata Menike",    "station": "Colombo Fort", "route": "Colombo Fort - Badulla"},
    {"asset_id": "BG-1001", "asset_type": "bogie",         "train": "Udarata Menike",    "station": "Colombo Fort", "route": "Colombo Fort - Badulla"},
    {"asset_id": "BR-1001", "asset_type": "brake_system",  "train": "Udarata Menike",    "station": "Colombo Fort", "route": "Colombo Fort - Badulla"},
    # Intercity Express  (Colombo Fort → Kandy)
    {"asset_id": "DE-1002", "asset_type": "diesel_engine", "train": "Intercity Express", "station": "Kandy",        "route": "Colombo Fort - Kandy"},
    {"asset_id": "BG-1002", "asset_type": "bogie",         "train": "Intercity Express", "station": "Kandy",        "route": "Colombo Fort - Kandy"},
    {"asset_id": "BR-1002", "asset_type": "brake_system",  "train": "Intercity Express", "station": "Kandy",        "route": "Colombo Fort - Kandy"},
    # Podi Menike  (Kandy → Badulla)
    {"asset_id": "DE-1003", "asset_type": "diesel_engine", "train": "Podi Menike",       "station": "Kandy",        "route": "Kandy - Badulla"},
    {"asset_id": "BG-1003", "asset_type": "bogie",         "train": "Podi Menike",       "station": "Kandy",        "route": "Kandy - Badulla"},
    {"asset_id": "BR-1003", "asset_type": "brake_system",  "train": "Podi Menike",       "station": "Kandy",        "route": "Kandy - Badulla"},
    # Galu Kumari  (Colombo Fort → Galle)
    {"asset_id": "DE-1004", "asset_type": "diesel_engine", "train": "Galu Kumari",       "station": "Galle",        "route": "Colombo Fort - Galle"},
    {"asset_id": "BG-1004", "asset_type": "bogie",         "train": "Galu Kumari",       "station": "Galle",        "route": "Colombo Fort - Galle"},
    {"asset_id": "BR-1004", "asset_type": "brake_system",  "train": "Galu Kumari",       "station": "Galle",        "route": "Colombo Fort - Galle"},
    # Yal Devi  (Colombo Fort → Jaffna)
    {"asset_id": "DE-2001", "asset_type": "diesel_engine", "train": "Yal Devi",          "station": "Vavuniya",     "route": "Colombo Fort - Jaffna"},
    {"asset_id": "BG-1006", "asset_type": "bogie",         "train": "Yal Devi",          "station": "Vavuniya",     "route": "Colombo Fort - Jaffna"},
    {"asset_id": "BR-1005", "asset_type": "brake_system",  "train": "Yal Devi",          "station": "Vavuniya",     "route": "Colombo Fort - Jaffna"},
    # Ruhunu Kumari  (Colombo Fort → Matara)
    {"asset_id": "DE-2002", "asset_type": "diesel_engine", "train": "Ruhunu Kumari",     "station": "Matara",       "route": "Colombo Fort - Matara"},
    {"asset_id": "BG-1007", "asset_type": "bogie",         "train": "Ruhunu Kumari",     "station": "Matara",       "route": "Colombo Fort - Matara"},
    {"asset_id": "BR-1006", "asset_type": "brake_system",  "train": "Ruhunu Kumari",     "station": "Matara",       "route": "Colombo Fort - Matara"},
    # Night Mail  (Colombo Fort → Matara)
    {"asset_id": "DE-2003", "asset_type": "diesel_engine", "train": "Night Mail",        "station": "Colombo Fort", "route": "Colombo Fort - Matara"},
    {"asset_id": "BG-1008", "asset_type": "bogie",         "train": "Night Mail",        "station": "Colombo Fort", "route": "Colombo Fort - Matara"},
    {"asset_id": "BR-1007", "asset_type": "brake_system",  "train": "Night Mail",        "station": "Colombo Fort", "route": "Colombo Fort - Matara"},
    # Denuwara Menike  (Colombo Fort → Kandy)
    {"asset_id": "DE-2004", "asset_type": "diesel_engine", "train": "Denuwara Menike",   "station": "Kandy",        "route": "Colombo Fort - Kandy"},
    {"asset_id": "BG-1009", "asset_type": "bogie",         "train": "Denuwara Menike",   "station": "Kandy",        "route": "Colombo Fort - Kandy"},
    {"asset_id": "BR-1008", "asset_type": "brake_system",  "train": "Denuwara Menike",   "station": "Kandy",        "route": "Colombo Fort - Kandy"},
]

FAULT_TYPES = {
    "diesel_engine": ["oil_leak", "overheating", "starter_failure", "fuel_pump_fault", "none"],
    "bogie":         ["wheel_flat", "bearing_noise", "axle_crack", "suspension_worn",  "none"],
    "brake_system":  ["brake_fade", "pad_worn", "cylinder_leak", "none"],
}

TECHNICIAN_NOTES = {
    "oil_leak":         ["Found oil seepage around main gasket seal. Pressure tested and confirmed leak at 3.2 bar.",
                         "Noticed oil marks on underframe. Tightened drain plug and replaced cracked gasket."],
    "overheating":      ["Engine temperature exceeded 105°C during run. Coolant level was low. Topped up and monitored.",
                         "Radiator fins partially blocked with debris. Cleaned and flushed cooling system."],
    "starter_failure":  ["Engine failed to crank on first attempt. Starter motor brushes worn. Replaced starter assembly.",
                         "Intermittent starting issues. Traced to corroded battery terminals. Cleaned and torqued."],
    "fuel_pump_fault":  ["Fuel delivery pressure below spec at 180 bar. Pump replaced, pressure verified at 220 bar.",
                         "Engine stuttering at load. Fuel filter severely clogged. Replaced filter and primed system."],
    "wheel_flat":       ["Flat spot detected on wheel 3 during vibration scan. Wheel turned on lathe to profile.",
                         "Abnormal vibration at 80 km/h. Flat spot of 8mm measured. Wheel re-profiled to standard."],
    "bearing_noise":    ["Grinding noise from axle box. Bearing grease contaminated with water. Repacked with grease.",
                         "Axle bearing temperature elevated at 78°C. Bearing replaced. Now running at 42°C."],
    "axle_crack":       ["Ultrasonic inspection revealed hairline crack in axle journal. Asset grounded for axle replacement.",
                         "Crack depth measured at 2mm on non-critical surface. Monitoring with weekly checks."],
    "suspension_worn":  ["Coil spring sag of 12mm beyond tolerance. Springs replaced. Ride height restored to spec.",
                         "Secondary suspension air bag deflated during inspection. Leak found at fitting. Re-sealed."],
    "brake_fade":       ["Braking distance increased 15%. Brake shoes glazed. Replaced shoes and bedded in.",
                         "Crew reported soft pedal. Air reservoir pressure dropping. Leak traced to union fitting."],
    "pad_worn":         ["Brake pad thickness at 4mm, below 5mm minimum. Replaced all four pads on bogie set.",
                         "Wear indicator contact made during inspection. Pad replaced immediately. Rotor acceptable."],
    "cylinder_leak":    ["Air cylinder leaking 0.3 bar per minute. Piston seal replaced. Now holding pressure.",
                         "Found loose bleed nipple causing air loss. Tightened and tested brake application."],
    "none":             ["Routine inspection completed. No issues found. All readings within normal range.",
                         "Scheduled preventive maintenance carried out. Lubrication and cleaning completed.",
                         "Periodic check completed. Torque checked on all fasteners. No corrective action required.",
                         "Inspection passed. Sensor readings nominal. Documentation updated in maintenance log.",
                         "Monthly service carried out. Fluid levels checked. All systems operating normally."],
}

RECOMMENDED_ACTIONS = {
    "GREEN":  {"diesel_engine": "Continue normal scheduled maintenance. Next service in 30 days.",
               "bogie":         "Continue normal inspection schedule. Next check in 30 days.",
               "brake_system":  "Continue routine checks. No immediate action required."},
    "AMBER":  {"diesel_engine": "Schedule inspection within 7 days. Check oil and cooling system.",
               "bogie":         "Inspect wheel profile and axle bearings within 7 days.",
               "brake_system":  "Inspect brake pads and cylinders within 3 days. Test stopping distance."},
    "RED":    {"diesel_engine": "Withdraw from service immediately. Full engine overhaul required. See Manual Section 6.",
               "bogie":         "Withdraw asset from service. Full bogie overhaul required. See Bogie Guide Section 5.",
               "brake_system":  "Withdraw from service immediately. Brake system replacement required. See Brake Manual Section 5."},
}

FAULT_SEVERITY = {
    "none": 0, "pad_worn": 1, "suspension_worn": 1,
    "brake_fade": 2, "bearing_noise": 2, "wheel_flat": 2,
    "cylinder_leak": 2, "starter_failure": 2,
    "oil_leak": 3, "overheating": 3, "fuel_pump_fault": 3,
    "axle_crack": 5,
}

SERVICE_INTERVAL = {"diesel_engine": 90, "bogie": 60, "brake_system": 45}


def get_health_status(score: float) -> str:
    if score >= 70:
        return "GREEN"
    elif score >= 40:
        return "AMBER"
    return "RED"


def generate_sensor_readings(asset_type: str, health_score: float) -> dict:
    degradation = (100 - health_score) / 100
    noise = lambda scale: random.gauss(0, scale)
    base: dict = {
        "temperature_celsius": None,
        "vibration_level": None,
        "oil_pressure_bar": None,
        "fuel_efficiency_pct": None,
        "axle_temp_celsius": None,
        "wheel_profile_mm": None,
        "pad_thickness_mm": None,
        "brake_cylinder_pressure_bar": None,
        "stopping_distance_m": None,
        "response_time_ms": None,
        "voltage_output_v": None,
        "contact_resistance_ohm": None,
        "rail_wear_mm": None,
        "gauge_deviation_mm": None,
        "ballast_void_pct": None,
        "motor_current_a": None,
        "cycle_time_seconds": None,
        "sensor_reliability_pct": None,
    }
    if asset_type == "diesel_engine":
        base["temperature_celsius"]  = round(75 + degradation * 45 + noise(3), 1)
        base["vibration_level"]      = round(max(0, 1.5 + degradation * 6 + noise(0.3)), 2)
        base["oil_pressure_bar"]     = round(max(0, 4.5 - degradation * 2.5 + noise(0.2)), 2)
        base["fuel_efficiency_pct"]  = round(max(0, 92 - degradation * 20 + noise(2)), 1)
    elif asset_type == "bogie":
        base["vibration_level"]      = round(max(0, 0.8 + degradation * 7 + noise(0.4)), 2)
        base["axle_temp_celsius"]    = round(35 + degradation * 55 + noise(4), 1)
        base["wheel_profile_mm"]     = round(max(100, 135 - degradation * 15 + noise(1)), 1)
    elif asset_type == "brake_system":
        base["pad_thickness_mm"]              = round(max(1, 18 - degradation * 14 + noise(1)), 1)
        base["brake_cylinder_pressure_bar"]   = round(max(0, 6.5 - degradation * 2 + noise(0.3)), 2)
        base["stopping_distance_m"]           = round(250 + degradation * 120 + noise(10))
    return base


def generate_asset_history(asset: dict, n_records: int = 25) -> list[dict]:
    """Generate n_records history entries for one asset, most recent first."""
    records = []
    # Spread records over last 2 years; most-recent within last 60 days
    now = datetime.now()
    service_days = sorted(
        [random.randint(1, 60)] + [random.randint(61, 730) for _ in range(n_records - 1)]
    )

    for days_ago in service_days:
        days_since = int(days_ago)
        fault_options = FAULT_TYPES[asset["asset_type"]]
        fault_weights = [3] * (len(fault_options) - 1) + [40]
        fault_type = random.choices(fault_options, weights=fault_weights, k=1)[0]

        base_score = 95 - (days_since / 730) * 30
        if fault_type != "none":
            base_score -= random.uniform(10, 40)
        health_score = max(5.0, min(100.0, base_score + random.gauss(0, 5)))
        health_status = get_health_status(health_score)
        fault_count_30d = 0 if fault_type == "none" else random.randint(1, 5)

        sensors = generate_sensor_readings(asset["asset_type"], health_score)
        service_date = now - timedelta(days=days_since)
        technician_note = random.choice(TECHNICIAN_NOTES.get(fault_type, TECHNICIAN_NOTES["none"]))
        recommended_action = RECOMMENDED_ACTIONS[health_status].get(
            asset["asset_type"], f"Schedule {health_status.lower()} priority maintenance."
        )
        severity = FAULT_SEVERITY.get(fault_type, 0)
        interval = SERVICE_INTERVAL.get(asset["asset_type"], 90)
        overdue_days = max(0, days_since - interval)

        records.append({
            "record_id":               str(uuid.uuid4()),
            "asset_id":                asset["asset_id"],
            "asset_type":              asset["asset_type"],
            "station":                 asset["station"],
            "route":                   asset["route"],
            "last_service_date":       service_date.strftime("%Y-%m-%d"),
            "days_since_service":      days_since,
            "fault_type":              fault_type,
            "fault_count_30d":         fault_count_30d,
            "health_score":            round(health_score, 2),
            "health_status":           health_status,
            "technician_note":         technician_note,
            "recommended_action":      recommended_action,
            "fault_severity":          severity,
            "overdue_days":            overdue_days,
            **sensors,
        })

    # Return most-recent first so the first row = current health
    return sorted(records, key=lambda r: r["last_service_date"], reverse=True)


if __name__ == "__main__":
    all_records: list[dict] = []
    for asset in TRAIN_ASSETS:
        all_records.extend(generate_asset_history(asset, n_records=60))

    out_path = Path(__file__).parent / "assets_history.csv"
    if all_records:
        fieldnames = list(all_records[0].keys())
        with open(out_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(all_records)
    print(f"Generated {len(all_records)} records for {len(TRAIN_ASSETS)} assets → {out_path}")
    print("Assets:", ", ".join(a["asset_id"] for a in TRAIN_ASSETS))
