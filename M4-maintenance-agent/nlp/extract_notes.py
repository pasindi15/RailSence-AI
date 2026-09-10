"""Extract structured information from technician free-text maintenance notes.

Default: rule-based keyword extraction — no API cost, deterministic.
Optional: LLM extraction via Anthropic API when ANTHROPIC_API_KEY is set.
"""

import os
import re
from typing import Any

FAULT_KEYWORDS: dict[str, list[str]] = {
    "oil_leak": ["oil leak", "oil seepage", "oil mark", "oil pan", "gasket", "drain plug"],
    "overheating": ["overheat", "temperature exceed", "radiator", "coolant", "thermostat", "105", "cooling"],
    "starter_failure": ["starter", "crank", "solenoid", "start fail", "battery terminal"],
    "fuel_pump_fault": ["fuel pump", "fuel delivery", "fuel filter", "primed", "fuel pressure"],
    "pantograph_fault": ["pantograph", "collector strip", "contact pressure"],
    "inverter_fault": ["inverter", "igbt", "dc link", "capacitor"],
    "motor_overload": ["motor trip", "winding", "moisture ingress", "traction motor", "motor temperature"],
    "wheel_flat": ["flat spot", "wheel flat", "wheel profile", "re-profiled", "lathe"],
    "bearing_noise": ["bearing", "axle box", "grinding noise", "grease contaminated"],
    "axle_crack": ["crack", "ultrasonic", "hairline", "axle journal", "grounded"],
    "suspension_worn": ["spring sag", "air bag", "suspension", "coil spring", "ride height"],
    "brake_fade": ["brake fade", "glazed", "braking distance", "soft pedal", "air reservoir"],
    "pad_worn": ["pad thickness", "wear indicator", "pad replaced", "brake pad"],
    "cylinder_leak": ["cylinder leak", "piston seal", "bleed nipple", "air loss"],
    "relay_fault": ["relay", "dropped intermittently", "contacts cleaned", "coil resistance"],
    "lamp_failure": ["lamp", "aspect lamp", "led", "lamp holder", "flickering"],
    "point_motor_jam": ["point motor", "switch rail", "slide chair", "motor stall", "motor overload"],
    "response_delay": ["response time", "damaged core", "terminal block", "380ms", "300ms"],
    "rail_crack": ["rail crack", "transverse defect", "ultrasonic trolley", "welded joint"],
    "joint_gap": ["joint gap", "fishplate", "expansion gap"],
    "ballast_shortage": ["ballast void", "tamped", "ballasted", "track geometry", "tamping"],
    "sleeper_rot": ["sleeper rot", "spike pull-out", "concrete sleeper", "timber sleeper"],
    "gate_jam": ["gate jam", "gate motor", "pivot", "gate failed", "cable replaced"],
    "sensor_fault": ["sensor fault", "false-triggering", "sensing face", "voltage drifting"],
    "barrier_worn": ["barrier", "counterweight", "barrier arm", "pivot mounting"],
    "door_jam": ["door jam", "door runner", "door sensor", "door failing"],
    "motor_worn": ["brush wear", "motor bearing", "drive motor"],
    "none": ["no issues", "normal range", "no corrective", "nominal", "routine"],
}

PART_KEYWORDS = [
    "gasket", "starter", "solenoid", "radiator", "thermostat", "coolant",
    "fuel pump", "fuel filter", "pantograph", "inverter", "capacitor",
    "wheel", "axle", "bearing", "suspension", "spring", "air bag",
    "brake pad", "brake shoe", "brake cylinder", "piston seal",
    "relay", "lamp", "point motor", "slide chair", "terminal block",
    "rail", "fishplate", "sleeper", "ballast", "joint",
    "gate motor", "barrier arm", "sensor", "door runner", "brush",
]

ACTION_KEYWORDS = [
    "replaced", "cleaned", "lubricated", "tightened", "adjusted", "repacked",
    "inspected", "tested", "retightened", "reset", "removed", "repaired",
    "re-profiled", "welded", "tamped", "flushed", "topped up", "grounded",
    "scheduled", "monitored", "verified", "measured", "sealed",
]


def extract_fault_type(text: str) -> str:
    lower = text.lower()
    for fault, keywords in FAULT_KEYWORDS.items():
        if any(kw in lower for kw in keywords):
            return fault
    return "none"


def extract_parts(text: str) -> list[str]:
    lower = text.lower()
    return [p for p in PART_KEYWORDS if p in lower]


def extract_actions(text: str) -> list[str]:
    lower = text.lower()
    return [a for a in ACTION_KEYWORDS if a in lower]


def extract_measurements(text: str) -> list[str]:
    pattern = r"\d+(?:\.\d+)?\s*(?:mm|cm|bar|°C|degrees|ohm|ms|km/h|V|A|pct|percent|%|L|kW)"
    return re.findall(pattern, text, re.IGNORECASE)


def extract_rule_based(text: str) -> dict[str, Any]:
    return {
        "detected_fault_type": extract_fault_type(text),
        "parts_mentioned": extract_parts(text),
        "actions_taken": extract_actions(text),
        "measurements_found": extract_measurements(text),
        "extraction_method": "rule_based",
    }


def extract_llm(text: str) -> dict[str, Any]:
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
        prompt = (
            "You are a railway maintenance analyst. Extract structured information from this technician note.\n\n"
            f"Note: {text}\n\n"
            "Return a JSON object with keys:\n"
            "  detected_fault_type (string, one of: oil_leak/overheating/starter_failure/fuel_pump_fault/"
            "pantograph_fault/inverter_fault/motor_overload/wheel_flat/bearing_noise/axle_crack/"
            "suspension_worn/brake_fade/pad_worn/cylinder_leak/relay_fault/lamp_failure/"
            "point_motor_jam/response_delay/rail_crack/joint_gap/ballast_shortage/sleeper_rot/"
            "gate_jam/sensor_fault/barrier_worn/door_jam/motor_worn/none)\n"
            "  parts_mentioned (list of strings)\n"
            "  actions_taken (list of strings)\n"
            "  measurements_found (list of strings)\n"
            "Return only valid JSON, no explanation."
        )
        message = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=300,
            messages=[{"role": "user", "content": prompt}],
        )
        import json
        result = json.loads(message.content[0].text.strip())
        result["extraction_method"] = "llm"
        return result
    except Exception:
        result = extract_rule_based(text)
        result["extraction_method"] = "rule_based_fallback"
        return result


def extract_technician_note(text: str) -> dict[str, Any]:
    if os.getenv("ANTHROPIC_API_KEY"):
        return extract_llm(text)
    return extract_rule_based(text)
