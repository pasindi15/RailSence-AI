"""
privacy_assessment/test_cases.py
--------------------------------
RailSense AI — Privacy & Data Leakage Assessment Test Case Schema.
Module: IT3041 Information Retrieval and Web Analytics
Assigned Specialisation: Privacy and Data Leakage Assessment (Student 2)

Data structure and export serialization for the 15 required security test cases.
Supports JSON, CSV (Excel-ready), and detailed Markdown reporting.
"""

from __future__ import annotations

import csv
import json
import os
from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Union

from pii_scanner import PIIScanner
from config import compute_risk_level


@dataclass
class TestCaseResult:
    """Represents the structured evaluation record of a single security test case."""
    test_id: str
    test_category: str
    objective: str
    attack_scenario: str
    input_request: Union[Dict[str, Any], str]
    expected_behaviour: str
    actual_behaviour: str
    status: str  # 'PASS', 'FAIL', 'INCONCLUSIVE'
    evidence: Dict[str, Any]
    observation: str
    conclusion: str
    potential_impact: str
    likelihood: str  # 'High', 'Medium', 'Low'
    severity: str    # 'Critical', 'High', 'Medium', 'Low', 'Informational'
    risk_level: str  # Computed via Risk Matrix
    endpoint_tested: str
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    technical_justification: str = ""

    def __post_init__(self):
        # Auto-compute risk level if unset or default
        if not self.risk_level or self.risk_level == "UNKNOWN":
            self.risk_level = compute_risk_level(self.severity, self.likelihood)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to JSON-serializable dictionary with sanitized evidence."""
        d = asdict(self)
        # Ensure evidence text is redacted
        try:
            raw_evidence = json.dumps(d["evidence"], default=str)
            d["evidence"] = json.loads(PIIScanner.redact_text(raw_evidence))
        except Exception:
            pass
        return d

    def to_csv_row(self) -> Dict[str, Any]:
        """Flatten attributes for tabular Excel/CSV representation."""
        sanitized_input = PIIScanner.redact_text(json.dumps(self.input_request, default=str))
        evidence_summary = PIIScanner.redact_text(json.dumps(self.evidence, default=str))
        return {
            "Test ID": self.test_id,
            "Category": self.test_category,
            "Endpoint": self.endpoint_tested,
            "Status": self.status,
            "Severity": self.severity,
            "Likelihood": self.likelihood,
            "Risk Level": self.risk_level,
            "Objective": self.objective,
            "Expected Behaviour": self.expected_behaviour,
            "Actual Behaviour": self.actual_behaviour,
            "Observation": self.observation,
            "Conclusion": self.conclusion,
            "Potential Impact": self.potential_impact,
            "Technical Justification": self.technical_justification,
            "Attack Scenario": self.attack_scenario,
            "Sanitized Input": sanitized_input[:250],
            "Evidence Summary": evidence_summary[:250],
            "Timestamp": self.timestamp,
        }

    def to_markdown_section(self) -> str:
        """Render detailed GitHub-flavored markdown section for academic report."""
        status_badge = {
            "PASS": "🟢 **PASS**",
            "FAIL": "🔴 **DEFICIENCY / VULNERABILITY CONFIRMED (FAIL)**",
            "INCONCLUSIVE": "🟡 **INCONCLUSIVE (Service/Environment Unavailable)**",
        }.get(self.status, f"⚪ {self.status}")

        severity_badge = {
            "Critical": "🟣 **CRITICAL**",
            "High": "🔴 **HIGH**",
            "Medium": "🟠 **MEDIUM**",
            "Low": "🟡 **LOW**",
            "Informational": "🔵 **INFORMATIONAL**",
        }.get(self.severity, self.severity)

        evidence_formatted = json.dumps(self.evidence, indent=2, default=str)
        evidence_redacted = PIIScanner.redact_text(evidence_formatted)

        input_formatted = json.dumps(self.input_request, indent=2, default=str)
        input_redacted = PIIScanner.redact_text(input_formatted)

        return f"""### {self.test_id}: {self.objective}

| Assessment Field | Evaluation Record |
| :--- | :--- |
| **Test ID** | `{self.test_id}` |
| **Category** | {self.test_category} |
| **Endpoint Tested** | `{self.endpoint_tested}` |
| **Test Outcome** | {status_badge} |
| **Severity (Impact)** | {severity_badge} |
| **Likelihood** | {self.likelihood} |
| **Derived Risk Level** | **{self.risk_level}** |
| **Timestamp** | `{self.timestamp}` |

#### 1. Attack Scenario & Objective
> **Objective:** {self.objective}
> 
> **Attack Scenario:** {self.attack_scenario}

#### 2. Input / Request Dispatched
```json
{input_redacted}
```

#### 3. Expected vs. Actual Behaviour
- **Expected Behaviour:** {self.expected_behaviour}
- **Actual Behaviour:** {self.actual_behaviour}

#### 4. Empirical Observation & Technical Justification
- **Observation:** {self.observation}
- **Technical Justification:** {self.technical_justification}
- **Potential Impact:** {self.potential_impact}
- **Conclusion:** {self.conclusion}

#### 5. Sanitized Test Evidence
```json
{evidence_redacted}
```

---
"""
