"""
privacy_assessment/test_runner.py
---------------------------------
RailSense AI — Automated Privacy and Data Leakage Assessment Runner.
Module: IT3041 Information Retrieval and Web Analytics
Assigned Specialisation: Privacy and Data Leakage Assessment (Student 2)

Executes the automated 15-test case privacy evaluation suite, generates structured
JSON, CSV, and Markdown audit reports, and displays an executive summary table.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time
import warnings
from datetime import datetime, timezone
from typing import List, Dict, Any

# Suppress Starlette / Pydantic deprecation warnings in test output
warnings.filterwarnings("ignore", category=DeprecationWarning)
warnings.filterwarnings("ignore", category=UserWarning)

# Ensure clean UTF-8 console encoding on Windows
if sys.platform == "win32":
    try:
        if sys.stdout.encoding.lower() != "utf-8":
            sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

# Ensure local test directory is on sys.path
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from config import (
    EVIDENCE_DIR,
    RESULTS_DIR,
    SEVERITY_CRITICAL,
    SEVERITY_HIGH,
    SEVERITY_MEDIUM,
    SEVERITY_LOW,
    SEVERITY_INFORMATIONAL,
)
from test_cases import TestCaseResult

# Import test suites
from api_leakage_tests import run_tc_pd_001, run_tc_pd_002, run_tc_pd_003
from auth_tests import run_tc_pd_004, run_tc_pd_007, run_tc_pd_014
from authorization_tests import run_tc_pd_005, run_tc_pd_006, run_tc_pd_008, run_tc_pd_009
from memory_tests import run_tc_pd_010, run_tc_pd_011
from log_leakage_tests import run_tc_pd_012, run_tc_pd_013
from cors_tests import run_tc_pd_015


TEST_DISPATCH = [
    ("TC-PD-001", "PII Exposure in API Response", run_tc_pd_001),
    ("TC-PD-002", "Passenger PII Exposure in Booking Response", run_tc_pd_002),
    ("TC-PD-003", "Sensitive Data Exposure in Error Response", run_tc_pd_003),
    ("TC-PD-004", "Unauthorized Booking Access", run_tc_pd_004),
    ("TC-PD-005", "IDOR Using User ID", run_tc_pd_005),
    ("TC-PD-006", "IDOR Using Booking Reference", run_tc_pd_006),
    ("TC-PD-007", "Unauthenticated Booking Endpoint", run_tc_pd_007),
    ("TC-PD-008", "Unauthenticated Cancellation Endpoint", run_tc_pd_008),
    ("TC-PD-009", "Unauthorized Admin Endpoint Access", run_tc_pd_009),
    ("TC-PD-010", "Unauthenticated Fraud Review Queue Exposure", run_tc_pd_010),
    ("TC-PD-011", "Unauthenticated Topology & Registry Disclosure", run_tc_pd_011),
    ("TC-PD-012", "Inter-Agent PII Leakage", run_tc_pd_012),
    ("TC-PD-013", "PII/Token Leakage in Logs", run_tc_pd_013),
    ("TC-PD-014", "JWT Validation Weakness", run_tc_pd_014),
    ("TC-PD-015", "CORS / Unauthorized Origin Data Exposure", run_tc_pd_015),
]

TEST_COMPONENTS: Dict[str, str] = {
    "TC-PD-001": "M3 Central Hub (agent-hub/main.py), FastAPI diagnostic routers (/ready, /health, /api/hub/dashboard)",
    "TC-PD-002": "M3 Booking Agent (booking-agent/main.py), Pydantic booking schema, SQLite passenger repository (railsense_booking.db)",
    "TC-PD-003": "FastAPI request validators, Pydantic exception handlers, M3 Booking Agent API",
    "TC-PD-004": "M3 Booking Agent (GET /bookings/{booking_reference}), FastAPI route dependencies",
    "TC-PD-005": "M3 Booking Agent (GET /bookings/{ref}?user_id={id}), identity comparison logic",
    "TC-PD-006": "M3 Booking Agent (GET /bookings/{ref}), conditional validation clause (booking-agent/main.py:391)",
    "TC-PD-007": "M3 Agent Hub message router (POST /internal/messages), JWT verification dependency (agent-hub/main.py)",
    "TC-PD-008": "M3 Booking Agent (GET /cancellations), cancellation audit storage (railsense_booking.db)",
    "TC-PD-009": "M3 Booking Agent (GET /admin/bookings), admin routing controllers",
    "TC-PD-010": "M3 Booking Agent (GET /internal/fraud-reviews), automated fraud scoring heuristic engine",
    "TC-PD-011": "M3 Central Hub dashboard API (GET /api/hub/dashboard), Agent Registry (agent-hub/main.py)",
    "TC-PD-012": "M3 Central Hub timeline endpoint (GET /api/hub/timeline), Hub audit logger (railsense_hub_audit.db)",
    "TC-PD-013": "Hub Audit Service (agent-hub/audit/service.py:write_audit_log), SQLite audit persistence (railsense_hub_audit.db)",
    "TC-PD-014": "JWT authentication verification middleware (agent-hub/main.py:verify_agent_token), PyJWT decoder",
    "TC-PD-015": "FastAPI CORS middleware configuration in agent-hub/main.py and booking-agent/main.py",
}


def generate_markdown_report(results: List[TestCaseResult], output_path: str):
    """Generate a comprehensive human-readable Markdown security assessment summary."""
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    total = len(results)
    passed = sum(1 for r in results if r.status == "PASS")
    failed = sum(1 for r in results if r.status == "FAIL")
    inconclusive = sum(1 for r in results if r.status == "INCONCLUSIVE")

    crit_count = sum(1 for r in results if r.status == "FAIL" and r.risk_level == SEVERITY_CRITICAL)
    high_count = sum(1 for r in results if r.status == "FAIL" and r.risk_level == SEVERITY_HIGH)
    med_count = sum(1 for r in results if r.status == "FAIL" and r.risk_level == SEVERITY_MEDIUM)
    low_count = sum(1 for r in results if r.status == "FAIL" and r.risk_level == SEVERITY_LOW)
    info_count = sum(1 for r in results if r.status == "FAIL" and r.risk_level == SEVERITY_INFORMATIONAL)

    md = f"""# RailSense AI — Privacy and Data Leakage Assessment Summary
### Automated Security Testing & Vulnerability Assessment Report (Student 2)
**Module:** IT3041 — Information Retrieval and Web Analytics  
**Specialisation:** Privacy and Data Leakage Assessment  
**Generated At:** `{now_str}`  

---

## 1. Executive Summary

This assessment evaluated the privacy boundaries, Personally Identifiable Information (PII) handling, session isolation, and data-leakage surfaces across **RailSense AI**, with special focus on **Module M3: Central Agent Communication Hub & Booking Agent** and inter-agent boundaries.

### Summary Metrics
| Evaluation Metric | Count | Percentage |
| :--- | :--- | :--- |
| **Total Test Cases** | **{total}** | 100.0% |
| **Controls Verified (PASS)** | **{passed}** | {passed/total*100:.1f}% |
| **Deficiencies Identified (FAIL)** | **{failed}** | {failed/total*100:.1f}% |
| **Inconclusive (Environment Offline)** | **{inconclusive}** | {inconclusive/total*100:.1f}% |

### Identified Risk Distribution (Deficiencies)
- 🟣 **Critical:** {crit_count}
- 🔴 **High:** {high_count}
- 🟠 **Medium:** {med_count}
- 🟡 **Low:** {low_count}
- 🔵 **Informational:** {info_count}

---

## 2. Risk Matrix (Impact × Likelihood)

```
                 IMPACT / SEVERITY
LIKELIHOOD    Low          Medium       High         Critical
--------------------------------------------------------------
High          Low          Medium       HIGH         CRITICAL
Medium        Low          Medium       HIGH         CRITICAL
Low           Low          Low          Medium       HIGH
```

---

## 3. Test Cases Execution Matrix (TC-PD-001 to TC-PD-015)

| Test ID | Test Category | Endpoint Tested | Outcome | Severity | Risk Level |
| :--- | :--- | :--- | :--- | :--- | :--- |
"""

    for r in results:
        status_symbol = "🟢 PASS" if r.status == "PASS" else ("🔴 FAIL" if r.status == "FAIL" else "🟡 INCONCLUSIVE")
        md += f"| `{r.test_id}` | {r.test_category} | `{r.endpoint_tested}` | {status_symbol} | {r.severity} | **{r.risk_level}** |\n"

    md += """
---

## 4. Key Findings & Identified Vulnerabilities

"""

    findings = [r for r in results if r.status == "FAIL"]
    if not findings:
        md += "_No active vulnerabilities detected during automated execution._\n\n"
    else:
        for idx, f in enumerate(findings, 1):
            md += f"""### Finding {idx}: [{f.test_id}] {f.objective}
- **Vulnerability Category:** {f.test_category}
- **Endpoint Affected:** `{f.endpoint_tested}`
- **Risk Rating:** {f.risk_level} (Impact: {f.severity}, Likelihood: {f.likelihood})
- **Technical Observation:** {f.observation}
- **Root Cause & Justification:** {f.technical_justification}
- **Potential Impact:** {f.potential_impact}
- **Conclusion:** {f.conclusion}

"""

    md += """---

## 5. Detailed Test Case Specifications & Empirical Evidence

"""

    for r in results:
        md += r.to_markdown_section()

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(md)


def run_all_tests():
    """Main execution orchestrator."""
    print("=" * 80)
    print("  RAILSENSE AI — AUTOMATED PRIVACY & DATA LEAKAGE ASSESSMENT TOOLKIT")
    print("  Student Specialisation: Privacy and Data Leakage Assessment (Student 2)")
    print("  Evaluating 15 Independent Privacy Test Cases (TC-PD-001 to TC-PD-015)")
    print("=" * 80)
    print()

    results: List[TestCaseResult] = []
    start_time = time.time()

    for test_id, name, test_func in TEST_DISPATCH:
        sys.stdout.write(f"[*] Executing {test_id}: {name} ... ")
        sys.stdout.flush()

        try:
            res: TestCaseResult = test_func()
        except Exception as exc:
            res = TestCaseResult(
                test_id=test_id,
                test_category="Execution Error",
                objective=name,
                attack_scenario="Automated execution probe.",
                input_request={"error": str(exc)},
                expected_behaviour="Test runner completes without unhandled exception.",
                actual_behaviour=f"Unhandled exception: {str(exc)}",
                status="INCONCLUSIVE",
                evidence={"traceback": str(exc)},
                observation=f"Test runner encountered unexpected error: {str(exc)}",
                conclusion="Execution failed due to test harness error.",
                potential_impact="Test unexecuted.",
                likelihood="Low",
                severity="Informational",
                risk_level="Informational",
                endpoint_tested="N/A",
                technical_justification="Runner exception.",
            )

        results.append(res)

        # Save individual evidence snapshot
        evidence_file = os.path.join(EVIDENCE_DIR, f"{test_id.lower()}_evidence.json")
        with open(evidence_file, "w", encoding="utf-8") as ef:
            json.dump(res.to_dict(), ef, indent=2)

        # Status badge print
        if res.status == "PASS":
            print("[PASS]")
        elif res.status == "FAIL":
            print(f"[FAIL - {res.risk_level.upper()} RISK]")
        else:
            print("[INCONCLUSIVE]")

    elapsed = time.time() - start_time
    print()
    print("=" * 80)
    print(f"  ASSESSMENT COMPLETE in {elapsed:.2f}s")
    print("=" * 80)

    # 1. Write JSON dataset
    json_path = os.path.join(RESULTS_DIR, "privacy_results.json")
    with open(json_path, "w", encoding="utf-8") as jf:
        json.dump([r.to_dict() for r in results], jf, indent=2)

    # 2. Write CSV summary
    csv_path = os.path.join(RESULTS_DIR, "privacy_results.csv")
    if results:
        fieldnames = list(results[0].to_csv_row().keys())
        with open(csv_path, "w", newline="", encoding="utf-8") as cf:
            writer = csv.DictWriter(cf, fieldnames=fieldnames)
            writer.writeheader()
            for r in results:
                writer.writerow(r.to_csv_row())

    # 3. Write Markdown report
    md_path = os.path.join(RESULTS_DIR, "privacy_summary.md")
    generate_markdown_report(results, md_path)

    # Console Summary Statistics
    total = len(results)
    passed = sum(1 for r in results if r.status == "PASS")
    failed = sum(1 for r in results if r.status == "FAIL")
    inconclusive = sum(1 for r in results if r.status == "INCONCLUSIVE")

    crit_count = sum(1 for r in results if r.status == "FAIL" and r.risk_level == SEVERITY_CRITICAL)
    high_count = sum(1 for r in results if r.status == "FAIL" and r.risk_level == SEVERITY_HIGH)
    med_count = sum(1 for r in results if r.status == "FAIL" and r.risk_level == SEVERITY_MEDIUM)
    low_count = sum(1 for r in results if r.status == "FAIL" and r.risk_level == SEVERITY_LOW)
    info_count = sum(1 for r in results if r.status == "FAIL" and r.risk_level == SEVERITY_INFORMATIONAL)

    print()
    print(f"  Total Tests:    {total}")
    print(f"  Passed:         {passed}")
    print(f"  Failed:         {failed}")
    print(f"  Inconclusive:   {inconclusive}")
    print()
    print("  Findings Breakdown by Risk Level:")
    print(f"    Critical:      {crit_count}")
    print(f"    High:          {high_count}")
    print(f"    Medium:        {med_count}")
    print(f"    Low:           {low_count}")
    print(f"    Informational: {info_count}")
    print()

    # Affected endpoints table
    print("  Affected Endpoints & Test IDs (Findings):")
    print("  " + "-" * 76)
    print(f"  {'Test ID':<12} {'Risk Level':<12} {'Endpoint Tested':<35} {'Category'}")
    print("  " + "-" * 76)

    findings = [r for r in results if r.status == "FAIL"]
    if findings:
        for f in findings:
            print(f"  {f.test_id:<12} {f.risk_level:<12} {f.endpoint_tested[:33]:<35} {f.test_category}")
    else:
        print("  No vulnerable endpoints confirmed.")
    print("  " + "-" * 76)
    print()
    print(f"[+] Output JSON saved:      {json_path}")
    print(f"[+] Output CSV saved:       {csv_path}")
    print(f"[+] Output Markdown saved:  {md_path}")
    print("=" * 80)


def run_single_test(test_id_query: str) -> TestCaseResult:
    """Execute a single test case specified by ID and output in academic peer format."""
    query_norm = test_id_query.strip().upper().replace("_", "-")

    matched_entry = None
    for tid, name, func in TEST_DISPATCH:
        if tid == query_norm:
            matched_entry = (tid, name, func)
            break
        if tid.endswith(query_norm) or query_norm.endswith(tid.replace("TC-PD-", "")):
            matched_entry = (tid, name, func)
            break
        # Numeric shorthand: "1" -> "TC-PD-001"
        if query_norm.isdigit() and int(query_norm) == int(tid.replace("TC-PD-", "")):
            matched_entry = (tid, name, func)
            break

    if not matched_entry:
        print(f"[!] Error: Test case '{test_id_query}' not recognized.")
        print(f"    Available test cases: {', '.join(t[0] for t in TEST_DISPATCH)}")
        sys.exit(1)

    test_id, name, test_func = matched_entry

    print("=" * 80)
    print(f"Test Cases — Privacy and Data Leakage Assessment (Student 2)")
    print(f"{test_id} — {name}")
    print("=" * 80)
    sys.stdout.flush()

    try:
        res: TestCaseResult = test_func()
    except Exception as exc:
        res = TestCaseResult(
            test_id=test_id,
            test_category="Execution Error",
            objective=name,
            attack_scenario="Automated execution probe.",
            input_request={"error": str(exc)},
            expected_behaviour="Test completes without unhandled exception.",
            actual_behaviour=f"Unhandled exception: {str(exc)}",
            status="INCONCLUSIVE",
            evidence={"traceback": str(exc)},
            observation=f"Error encountered: {str(exc)}",
            conclusion="Execution failed due to harness error.",
            potential_impact="Test unexecuted.",
            likelihood="Low",
            severity="Informational",
            risk_level="Informational",
            endpoint_tested="N/A",
            technical_justification="Runner exception.",
        )

    # Save evidence file
    evidence_file = os.path.join(EVIDENCE_DIR, f"{test_id.lower()}_evidence.json")
    with open(evidence_file, "w", encoding="utf-8") as ef:
        json.dump(res.to_dict(), ef, indent=2)

    components = TEST_COMPONENTS.get(test_id, "RailSense AI Platform Services")

    # Format outcome string
    if res.status == "PASS":
        outcome_str = f"Pass within observed scope. {res.conclusion}"
    elif res.status == "FAIL":
        outcome_str = f"Failure ({res.risk_level.upper()} RISK). {res.conclusion}"
    else:
        outcome_str = f"Inconclusive. {res.conclusion}"

    # Format input string
    if isinstance(res.input_request, dict):
        input_str = json.dumps(res.input_request, indent=2)
    else:
        input_str = str(res.input_request)

    # Format analysis string
    analysis_str = res.technical_justification if res.technical_justification else res.observation

    # Screenshot reference
    screenshot_name = f"{test_id.lower().replace('-', '_')}_evidence.png"

    print(f"Evaluation area — {res.test_category}")
    print(f"Test objective — {res.objective}")
    print(f"Components evaluated — {components}")
    print()
    print(f"Input —")
    print(f"  {input_str}")
    print()
    print(f"Expected behaviour — {res.expected_behaviour}")
    print(f"Actual behaviour — {res.actual_behaviour}")
    print()
    print(f"Outcome — {outcome_str}")
    print()
    print(f"Analysis — {analysis_str}")
    print()
    print("Evidence —")
    print(f"  Status Badge:       {'[PASS]' if res.status == 'PASS' else f'[FAIL - {res.risk_level.upper()} RISK]'}")
    print(f"  Endpoint Tested:    {res.endpoint_tested}")
    print(f"  Raw Evidence File:  {evidence_file}")
    print(f"  Visual Screenshot:  docs/screenshots/{screenshot_name}")
    print("=" * 80)
    return res


def main():
    parser = argparse.ArgumentParser(
        description="RailSense AI — Privacy & Data Leakage Assessment Test Runner"
    )
    parser.add_argument(
        "--test",
        "-t",
        dest="test_id",
        type=str,
        default=None,
        help="Execute a specific test case by ID (e.g., TC-PD-001, TC-PD-004, 1, 4)",
    )
    parser.add_argument(
        "positional_test",
        nargs="?",
        default=None,
        help="Optional positional test case ID (e.g., TC-PD-001)",
    )
    parser.add_argument(
        "--list",
        "-l",
        action="store_true",
        help="List all 15 available test cases",
    )

    args = parser.parse_args()

    if args.list:
        print("=" * 80)
        print("  RAILSENSE AI — 15 EVALUATION TEST CASES (STUDENT 2)")
        print("=" * 80)
        for tid, name, _ in TEST_DISPATCH:
            print(f"  {tid:<12} — {name}")
        print("=" * 80)
        return

    target_test = args.test_id or args.positional_test
    if target_test:
        run_single_test(target_test)
    else:
        run_all_tests()


if __name__ == "__main__":
    main()
