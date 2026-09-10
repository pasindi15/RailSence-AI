"""Generate synthetic railway asset maintenance dataset for M4 (600 records)."""

import csv
import random
import uuid
from datetime import datetime, timedelta
from pathlib import Path

random.seed(42)

ASSET_TYPES = [
    "diesel_engine", "electric_loco", "bogie", "brake_system",
    "signal_unit", "track_section", "level_crossing", "platform_gate",
]

SRI_LANKA_STATIONS = [
    "Colombo Fort", "Maradana", "Ragama", "Gampaha", "Veyangoda",
    "Polgahawela", "Kurunegala", "Maho", "Anuradhapura", "Vavuniya",
    "Kandy", "Peradeniya", "Hatton", "Nanu Oya", "Badulla",
    "Galle", "Matara", "Hambantota", "Moratuwa", "Panadura",
    "Kalutara", "Aluthgama", "Ambalangoda", "Hikkaduwa",
    "Polonnaruwa", "Batticaloa", "Trincomalee", "Jaffna",
]

ROUTES = [
    "Colombo Fort - Kandy",
    "Colombo Fort - Galle",
    "Colombo Fort - Jaffna",
    "Colombo Fort - Badulla",
    "Colombo Fort - Matara",
    "Kandy - Badulla",
    "Colombo Fort - Trincomalee",
]

FAULT_TYPES = {
    "diesel_engine": ["oil_leak", "overheating", "starter_failure", "fuel_pump_fault", "none"],
    "electric_loco": ["pantograph_fault", "inverter_fault", "motor_overload", "none"],
    "bogie": ["wheel_flat", "bearing_noise", "axle_crack", "suspension_worn", "none"],
    "brake_system": ["brake_fade", "pad_worn", "cylinder_leak", "none"],
    "signal_unit": ["relay_fault", "lamp_failure", "point_motor_jam", "response_delay", "none"],
    "track_section": ["rail_crack", "joint_gap", "ballast_shortage", "sleeper_rot", "none"],
    "level_crossing": ["gate_jam", "sensor_fault", "barrier_worn", "none"],
    "platform_gate": ["door_jam", "sensor_fault", "motor_worn", "none"],
}

TECHNICIAN_NOTES = {
    "oil_leak": [
        "Found oil seepage around main gasket seal. Pressure tested and confirmed leak at 3.2 bar.",
        "Noticed oil marks on underframe. Tightened drain plug and replaced cracked gasket.",
        "Oil level dropped 2L below minimum. Identified cracked oil pan. Scheduled replacement.",
    ],
    "overheating": [
        "Engine temperature exceeded 105°C during run. Coolant level was low. Topped up and monitored.",
        "Radiator fins partially blocked with debris. Cleaned and flushed cooling system.",
        "Thermostat stuck closed causing overheating. Replaced thermostat, verified temperature range.",
    ],
    "starter_failure": [
        "Engine failed to crank on first attempt. Starter motor brushes worn. Replaced starter assembly.",
        "Intermittent starting issues. Traced to corroded battery terminals. Cleaned and torqued.",
        "Starter relay not engaging. Replaced solenoid and verified start sequence operates correctly.",
    ],
    "fuel_pump_fault": [
        "Fuel delivery pressure below spec at 180 bar. Pump replaced, pressure verified at 220 bar.",
        "Engine stuttering at load. Fuel filter severely clogged. Replaced filter and primed system.",
    ],
    "pantograph_fault": [
        "Pantograph collector strip worn beyond limits. Replaced strip and adjusted contact pressure.",
        "Pantograph lowering spring failed during inspection. Spring replaced. Operation tested.",
    ],
    "inverter_fault": [
        "IGBT module in inverter cabinet showing high temperature alarms. Module replaced.",
        "DC link voltage ripple excessive during load. Two capacitors replaced in bank.",
    ],
    "motor_overload": [
        "Traction motor tripped at 1200A. Winding insulation tested. Found moisture ingress. Dried out.",
        "Motor temperature 165°C during service. Cooling fan belt slipping. Belt replaced.",
    ],
    "wheel_flat": [
        "Flat spot detected on wheel 3 during vibration scan. Wheel turned on lathe to profile.",
        "Abnormal vibration at 80 km/h. Flat spot of 8mm measured. Wheel re-profiled to standard.",
    ],
    "bearing_noise": [
        "Grinding noise from axle box. Bearing grease contaminated with water. Repacked with grease.",
        "Axle bearing temperature elevated at 78 degrees. Bearing replaced. Now running at 42 degrees.",
    ],
    "axle_crack": [
        "Ultrasonic inspection revealed hairline crack in axle journal. Asset grounded for axle replacement.",
        "Crack depth measured at 2mm on non-critical surface. Monitoring with weekly checks.",
    ],
    "suspension_worn": [
        "Coil spring sag of 12mm beyond tolerance. Springs replaced. Ride height restored to spec.",
        "Secondary suspension air bag deflated during inspection. Leak found at fitting. Re-sealed.",
    ],
    "brake_fade": [
        "Braking distance increased 15 percent. Brake shoes glazed. Replaced shoes and bedded in.",
        "Crew reported soft pedal. Air reservoir pressure dropping. Leak traced to union fitting.",
    ],
    "pad_worn": [
        "Brake pad thickness at 4mm, below 5mm minimum. Replaced all four pads on bogie set.",
        "Wear indicator contact made during inspection. Pad replaced immediately. Rotor acceptable.",
    ],
    "cylinder_leak": [
        "Air cylinder leaking 0.3 bar per minute. Piston seal replaced. Now holding pressure.",
        "Found loose bleed nipple causing air loss. Tightened and tested brake application.",
    ],
    "relay_fault": [
        "Signal relay dropped intermittently causing false aspects. Contacts cleaned and tested.",
        "Relay coil resistance out of spec at 280 ohm. Replaced relay. Signal operates normally.",
    ],
    "lamp_failure": [
        "Red aspect lamp out during inspection. Lamp replaced with LED unit. Output verified.",
        "Two signal lamps flickering due to corroded holders. Cleaned holders, replaced lamps.",
    ],
    "point_motor_jam": [
        "Point motor overloaded due to foreign object in switch rail. Object cleared and motor reset.",
        "Motor stall detected. Slide chair plates severely worn. Lubricated and replaced plates.",
    ],
    "response_delay": [
        "Signal response time 380ms exceeds 300ms standard. Cable inspected, damaged core found.",
        "Slow signal response traced to corroded terminal block. Block cleaned and retightened.",
    ],
    "rail_crack": [
        "Transverse defect found by ultrasonic trolley at KM 42.3. 40m rail section replaced.",
        "Surface crack detected at welded joint. Joint ground flush and re-inspected. No defect.",
    ],
    "joint_gap": [
        "Fishplate joint gap exceeding 8mm. Bolts re-torqued and expansion gap adjusted to 5mm.",
        "Joint gap opened due to cold weather. Rail pulled together and bolted correctly.",
    ],
    "ballast_shortage": [
        "Ballast voids found under sleepers at KM 56.7. Section tamped and top-ballasted.",
        "Track geometry out of spec. Full tamping run completed. Geometry now within tolerance.",
    ],
    "sleeper_rot": [
        "Timber sleeper rot detected in 8 consecutive sleepers. All replaced with concrete sleepers.",
        "Spike pull-out resistance failed on 5 sleepers. Sleepers replaced and track tested.",
    ],
    "gate_jam": [
        "Crossing gate motor stalled due to seized pivot bearing. Greased pivot and reset limits.",
        "Gate failed to lower on demand. Control cable found frayed. Cable replaced and limits set.",
    ],
    "sensor_fault": [
        "Proximity sensor false-triggering due to contamination. Cleaned sensing face. Stable now.",
        "Sensor output voltage drifting by 0.5V. Sensor unit replaced. System verified correct.",
    ],
    "barrier_worn": [
        "Barrier pole cracked at pivot mounting. Replaced barrier arm. Torque set to specification.",
        "Counterweight misaligned causing uneven lift. Adjusted and balanced barrier arm correctly.",
    ],
    "door_jam": [
        "Platform gate door failing to close fully. Door runner cleaned and lubricated.",
        "Door sensor indicating obstruction when clear. Sensor alignment adjusted. Gate functional.",
    ],
    "motor_worn": [
        "Drive motor brush wear at 5mm, minimum is 8mm. Brushes replaced immediately.",
        "Motor bearing producing noise at low speed. Bearing replaced. Noise eliminated.",
    ],
    "none": [
        "Routine inspection completed. No issues found. All readings within normal range.",
        "Scheduled preventive maintenance carried out. Lubrication and cleaning completed.",
        "Periodic check completed. Torque checked on all fasteners. No corrective action required.",
        "Inspection passed. Sensor readings nominal. Documentation updated in maintenance log.",
        "Monthly service carried out. Fluid levels checked. All systems operating normally.",
    ],
}

RECOMMENDED_ACTIONS = {
    "GREEN": {
        "diesel_engine": "Continue normal scheduled maintenance. Next service in 30 days.",
        "electric_loco": "Continue normal service cycle. No action required.",
        "bogie": "Continue normal inspection schedule. Next check in 30 days.",
        "brake_system": "Continue routine checks. No immediate action required.",
        "signal_unit": "Continue normal monitoring schedule.",
        "track_section": "Continue routine geometry inspections.",
        "level_crossing": "Continue routine operational checks.",
        "platform_gate": "Continue routine operational checks.",
    },
    "AMBER": {
        "diesel_engine": "Schedule inspection within 7 days. Check oil and cooling system.",
        "electric_loco": "Check electrical systems within 5 days. Run full diagnostic cycle.",
        "bogie": "Inspect wheel profile and axle bearings within 7 days.",
        "brake_system": "Inspect brake pads and cylinders within 3 days. Test stopping distance.",
        "signal_unit": "Check relay contacts and response time within 2 days.",
        "track_section": "Schedule track geometry check within 5 days. Inspect rail joints.",
        "level_crossing": "Inspect gate mechanism and sensors within 3 days.",
        "platform_gate": "Inspect door mechanism and drive motor within 3 days.",
    },
    "RED": {
        "diesel_engine": "Withdraw from service immediately. Full engine overhaul required. See Manual Section 6.",
        "electric_loco": "Withdraw from service. Emergency electrical inspection required immediately.",
        "bogie": "Withdraw asset from service. Full bogie overhaul required. See Bogie Guide Section 5.",
        "brake_system": "Withdraw from service immediately. Brake system replacement required. See Brake Manual Section 5.",
        "signal_unit": "Take signal out of service. Emergency repair required before return. See Signal Manual Section 4.",
        "track_section": "Impose 25 km/h speed restriction. Urgent track repair required. See Track Manual Section 4.",
        "level_crossing": "Close crossing immediately. Emergency repair before reopening. See Signal Manual Section 5.",
        "platform_gate": "Close gate. Emergency repair required before reopening.",
    },
}


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
    if asset_type in ("diesel_engine", "electric_loco"):
        base["temperature_celsius"] = round(75 + degradation * 45 + noise(3), 1)
        base["vibration_level"] = round(max(0, 1.5 + degradation * 6 + noise(0.3)), 2)
        base["oil_pressure_bar"] = round(max(0, 4.5 - degradation * 2.5 + noise(0.2)), 2)
        base["fuel_efficiency_pct"] = round(max(0, 92 - degradation * 20 + noise(2)), 1)
    elif asset_type == "bogie":
        base["vibration_level"] = round(max(0, 0.8 + degradation * 7 + noise(0.4)), 2)
        base["axle_temp_celsius"] = round(35 + degradation * 55 + noise(4), 1)
        base["wheel_profile_mm"] = round(max(100, 135 - degradation * 15 + noise(1)), 1)
    elif asset_type == "brake_system":
        base["pad_thickness_mm"] = round(max(1, 18 - degradation * 14 + noise(1)), 1)
        base["brake_cylinder_pressure_bar"] = round(max(0, 6.5 - degradation * 2 + noise(0.3)), 2)
        base["stopping_distance_m"] = round(250 + degradation * 120 + noise(10))
    elif asset_type == "signal_unit":
        base["response_time_ms"] = round(120 + degradation * 280 + noise(15))
        base["voltage_output_v"] = round(max(0, 24 - degradation * 4 + noise(0.5)), 1)
        base["contact_resistance_ohm"] = round(max(0, 0.05 + degradation * 0.8 + noise(0.02)), 3)
    elif asset_type == "track_section":
        base["rail_wear_mm"] = round(max(0, degradation * 12 + noise(0.5)), 2)
        base["gauge_deviation_mm"] = round(max(0, degradation * 8 + noise(0.3)), 2)
        base["ballast_void_pct"] = round(max(0, degradation * 35 + noise(2)), 1)
    else:
        base["motor_current_a"] = round(max(0, 2.5 + degradation * 4 + noise(0.3)), 2)
        base["cycle_time_seconds"] = round(max(1, 8 + degradation * 12 + noise(0.5)), 1)
        base["sensor_reliability_pct"] = round(max(0, 99 - degradation * 25 + noise(2)), 1)
    return base


def generate_records(n: int = 600) -> list[dict]:
    records = []
    asset_counters: dict[str, int] = {}
    asset_weights = [15, 8, 20, 18, 15, 10, 8, 6]

    for _ in range(n):
        asset_type = random.choices(ASSET_TYPES, weights=asset_weights, k=1)[0]
        asset_counters[asset_type] = asset_counters.get(asset_type, 0) + 1

        prefix_map = {
            "diesel_engine": "DE", "electric_loco": "EL", "bogie": "BG",
            "brake_system": "BR", "signal_unit": "SG", "track_section": "TR",
            "level_crossing": "LC", "platform_gate": "PG",
        }
        asset_id = f"{prefix_map[asset_type]}-{1000 + asset_counters[asset_type]:04d}"

        station = random.choice(SRI_LANKA_STATIONS)
        route = random.choice(ROUTES)
        days_since_service = random.randint(0, 180)

        fault_options = FAULT_TYPES[asset_type]
        fault_weights = [3] * (len(fault_options) - 1) + [40]
        fault_type = random.choices(fault_options, weights=fault_weights, k=1)[0]

        base_score = 95 - (days_since_service / 180) * 30
        if fault_type != "none":
            base_score -= random.uniform(10, 40)
        health_score = max(5.0, min(100.0, base_score + random.gauss(0, 5)))
        health_status = get_health_status(health_score)
        fault_count_30d = 0 if fault_type == "none" else random.randint(1, 5)

        sensors = generate_sensor_readings(asset_type, health_score)
        service_date = datetime.now() - timedelta(days=days_since_service)
        note_pool = TECHNICIAN_NOTES.get(fault_type, TECHNICIAN_NOTES["none"])
        technician_note = random.choice(note_pool)
        recommended_action = RECOMMENDED_ACTIONS[health_status].get(
            asset_type, f"Schedule {health_status.lower()} priority maintenance."
        )

        record = {
            "record_id": str(uuid.uuid4()),
            "asset_id": asset_id,
            "asset_type": asset_type,
            "station": station,
            "route": route,
            "last_service_date": service_date.strftime("%Y-%m-%d"),
            "days_since_service": days_since_service,
            "fault_type": fault_type,
            "fault_count_30d": fault_count_30d,
            "health_score": round(health_score, 2),
            "health_status": health_status,
            "technician_note": technician_note,
            "recommended_action": recommended_action,
            **sensors,
        }
        records.append(record)

    return records


if __name__ == "__main__":
    out_path = Path(__file__).parent / "assets_history.csv"
    records = generate_records(600)
    if records:
        fieldnames = list(records[0].keys())
        with open(out_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(records)
        print(f"Generated {len(records)} records -> {out_path}")
