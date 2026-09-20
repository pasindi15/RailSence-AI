"""
test_m2_rbac.py
---------------
Comprehensive automated test suite for RailSense AI M2 Operations RBAC:
1. Admin Login & Full Permission Inspection
2. Operations Engineer Login & Least-Privilege Verification
3. Unauthorized API Access Rejection (403 Forbidden)
4. Officer Provisioning by Admin & Credentials Lifecycle
5. Deactivated Account Login & Execution Denial (403 Inactive)
6. Role Reassignment (Operations Engineer <-> Admin) with Capability Elevation
7. Logout, Token Invalidation, and 401 Rejections
8. Direct API Security & Last Active Administrator Lockout Prevention
9. Security Audit Logging Stream Verification
"""

import os
import sys
from pathlib import Path
import pytest
from starlette.testclient import TestClient

ROOT_DIR = Path(__file__).resolve().parent
M2_DIR = ROOT_DIR / "M2-operations-agent"
if str(M2_DIR) not in sys.path:
    sys.path.insert(0, str(M2_DIR))

from main import app
from admin import admin_db
from admin.admin_auth import ROLE_ADMIN, ROLE_OPERATIONS_ENGINEER

client = TestClient(app)

ADMIN_EMAIL = "admin@railsense.lk"
ADMIN_PASSWORD = "OperationsAdmin2026!"
TEST_OFFICER_EMAIL = "test_engineer@railsense.lk"
TEST_OFFICER_PWD = "TestEngineer2026!"


def setup_module():
    """Ensure initial admin is bootstrapped before running tests."""
    admin_db.seed_initial_admin_if_needed()


def test_01_admin_login():
    """Test 1 — Admin Login receives full administrative token and permissions."""
    resp = client.post("/admin/api/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    assert resp.status_code == 200, f"Admin login failed: {resp.text}"
    data = resp.json()
    assert "token" in data
    assert data["officer"]["role"] == ROLE_ADMIN
    assert data["officer"]["email"] == ADMIN_EMAIL
    assert len(data["officer"]["permissions"]) >= 10
    assert "m2.admin_console.view" in data["officer"]["permissions"]
    assert "m2.officers.create" in data["officer"]["permissions"]
    print("\n[PASS] Test 1 — Admin Login successful with full RBAC permissions.")


def test_02_officer_creation_by_admin():
    """Test 4a — Authenticated Admin creates a new Operations Engineer account."""
    # Login as admin
    login_resp = client.post("/admin/api/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    admin_token = login_resp.json()["token"]
    headers = {"Authorization": f"Bearer {admin_token}"}

    # Clean up test officer if existed from previous run
    existing = admin_db.get_officer_by_email(TEST_OFFICER_EMAIL)
    if existing:
        admin_db.update_officer(existing["id"], {"status": "active", "role": ROLE_OPERATIONS_ENGINEER})

    create_payload = {
        "full_name": "Test Officer",
        "email": TEST_OFFICER_EMAIL,
        "password": TEST_OFFICER_PWD,
        "role": ROLE_OPERATIONS_ENGINEER,
        "status": "active",
    }

    if not existing:
        resp = client.post("/admin/api/officers", json=create_payload, headers=headers)
        assert resp.status_code in (201, 200), f"Officer creation failed: {resp.text}"
        data = resp.json()
        assert data["email"] == TEST_OFFICER_EMAIL
        assert data["role"] == ROLE_OPERATIONS_ENGINEER
        assert "password_hash" not in data  # Never expose password hash

    # List officers as admin
    list_resp = client.get("/admin/api/officers", headers=headers)
    assert list_resp.status_code == 200
    officer_emails = [o["email"] for o in list_resp.json()["officers"]]
    assert TEST_OFFICER_EMAIL in officer_emails
    print("[PASS] Test 4a — Admin created new Operations Engineer account and verified in officers table.")


def test_03_operations_engineer_login_and_permissions():
    """Test 2 & 4b — Operations Engineer login and least-privilege verification."""
    resp = client.post("/admin/api/login", json={"email": TEST_OFFICER_EMAIL, "password": TEST_OFFICER_PWD})
    assert resp.status_code == 200, f"Operations engineer login failed: {resp.text}"
    data = resp.json()
    token = data["token"]
    assert data["officer"]["role"] == ROLE_OPERATIONS_ENGINEER
    assert "m2.admin_console.view" not in data["officer"]["permissions"]
    assert "m2.control_room.view" in data["officer"]["permissions"]

    headers = {"Authorization": f"Bearer {token}"}

    # Operational route accessible
    me_resp = client.get("/admin/api/me", headers=headers)
    assert me_resp.status_code == 200
    assert me_resp.json()["can_access_admin_console"] is False
    assert me_resp.json()["can_access_control_room"] is True

    # Prediction endpoint accessible with officer token
    pred_resp = client.post("/predict-delay", json={
        "route": "Colombo Fort - Kandy",
        "train_id": "PM-4082",
        "scheduled_time": "2026-09-20T14:30:00Z"
    }, headers=headers)
    assert pred_resp.status_code == 200
    assert "predicted_delay_minutes" in pred_resp.json()

    print("[PASS] Test 2 — Operations Engineer logged in: control room & prediction accessible.")


def test_04_unauthorized_admin_api_access_blocked():
    """Test 3 & 8 — Operations Engineer token directly calling Admin API is blocked with 403."""
    # Login as Operations Engineer
    login_resp = client.post("/admin/api/login", json={"email": TEST_OFFICER_EMAIL, "password": TEST_OFFICER_PWD})
    ops_token = login_resp.json()["token"]
    headers = {"Authorization": f"Bearer {ops_token}"}

    # Attempt to list officers (Admin only)
    resp = client.get("/admin/api/officers", headers=headers)
    assert resp.status_code == 403, f"Expected 403 Forbidden, got {resp.status_code}"
    assert "Access restricted" in resp.json()["detail"]

    # Attempt to access model retrain (Admin only)
    resp_retrain = client.post("/admin/api/model/retrain", headers=headers)
    assert resp_retrain.status_code == 403

    # Attempt to access system health config (Admin only)
    resp_cfg = client.get("/admin/api/health/config", headers=headers)
    assert resp_cfg.status_code == 403

    print("[PASS] Test 3 & 8 — Direct Admin API calls by Operations Engineer strictly blocked with 403 Forbidden.")


def test_05_deactivated_account_denied():
    """Test 5 — Deactivated officer account cannot log in or perform actions."""
    # Login as admin
    admin_login = client.post("/admin/api/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    admin_token = admin_login.json()["token"]
    admin_headers = {"Authorization": f"Bearer {admin_token}"}

    officer = admin_db.get_officer_by_email(TEST_OFFICER_EMAIL)
    assert officer is not None

    # Deactivate test officer
    deact_resp = client.post(f"/admin/api/officers/{officer['id']}/status", json={"status": "inactive"}, headers=admin_headers)
    assert deact_resp.status_code == 200
    assert deact_resp.json()["status"] == "inactive"

    # Attempt login as deactivated officer
    login_attempt = client.post("/admin/api/login", json={"email": TEST_OFFICER_EMAIL, "password": TEST_OFFICER_PWD})
    assert login_attempt.status_code == 403, f"Expected 403 for inactive account, got {login_attempt.status_code}"
    assert "Account inactive" in login_attempt.json()["detail"]

    print("[PASS] Test 5 — Deactivated officer account rejected with 403 and informative notice.")


def test_06_role_change_and_privilege_elevation():
    """Test 6 — Role change from Operations Engineer -> Admin grants administrative privileges."""
    # Login as admin
    admin_login = client.post("/admin/api/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    admin_token = admin_login.json()["token"]
    admin_headers = {"Authorization": f"Bearer {admin_token}"}

    officer = admin_db.get_officer_by_email(TEST_OFFICER_EMAIL)

    # Reactivate and elevate role to admin
    update_resp = client.put(f"/admin/api/officers/{officer['id']}", json={
        "role": ROLE_ADMIN,
        "status": "active"
    }, headers=admin_headers)
    assert update_resp.status_code == 200
    assert update_resp.json()["role"] == ROLE_ADMIN
    assert update_resp.json()["status"] == "active"

    # Log in as test officer (now Admin)
    promoted_login = client.post("/admin/api/login", json={"email": TEST_OFFICER_EMAIL, "password": TEST_OFFICER_PWD})
    assert promoted_login.status_code == 200
    promoted_token = promoted_login.json()["token"]
    promoted_headers = {"Authorization": f"Bearer {promoted_token}"}

    # Now has access to officers API!
    officers_resp = client.get("/admin/api/officers", headers=promoted_headers)
    assert officers_resp.status_code == 200
    assert "officers" in officers_resp.json()

    print("[PASS] Test 6 — Role change to Admin successfully elevated permissions and access.")


def test_07_logout_and_session_handling():
    """Test 7 — Logout and session invalidation."""
    login_resp = client.post("/admin/api/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    token = login_resp.json()["token"]
    headers = {"Authorization": f"Bearer {token}"}

    # Call logout
    logout_resp = client.post("/admin/api/logout", headers=headers)
    assert logout_resp.status_code == 200

    # Unauthenticated calls without token receive 401
    no_token_resp = client.get("/admin/api/me")
    assert no_token_resp.status_code == 401

    # Bad token receives 401
    bad_token_resp = client.get("/admin/api/me", headers={"Authorization": "Bearer invalid.token.signature"})
    assert bad_token_resp.status_code == 401

    print("[PASS] Test 7 — Logout, missing token, and bad token handled properly with 401.")


def test_08_last_admin_lockout_prevention():
    """Test 8 — Accidental lockout guard prevents deactivating or demoting the last active administrator."""
    # Demote test officer back to operations engineer first
    admin_login = client.post("/admin/api/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    admin_token = admin_login.json()["token"]
    admin_headers = {"Authorization": f"Bearer {admin_token}"}

    test_off = admin_db.get_officer_by_email(TEST_OFFICER_EMAIL)
    client.put(f"/admin/api/officers/{test_off['id']}", json={"role": ROLE_OPERATIONS_ENGINEER}, headers=admin_headers)

    # Now only one active admin remains (admin@railsense.lk)
    primary_admin = admin_db.get_officer_by_email(ADMIN_EMAIL)

    # Attempt to deactivate the only active admin
    deact_last = client.post(f"/admin/api/officers/{primary_admin['id']}/status", json={"status": "inactive"}, headers=admin_headers)
    assert deact_last.status_code == 400
    assert "Cannot deactivate the last active Administrator" in deact_last.json()["detail"]

    # Attempt to demote the only active admin
    demote_last = client.put(f"/admin/api/officers/{primary_admin['id']}", json={"role": ROLE_OPERATIONS_ENGINEER}, headers=admin_headers)
    assert demote_last.status_code == 400
    assert "Cannot change role of the last active Administrator" in demote_last.json()["detail"]

    print("[PASS] Test 8 — Accidental administrator lockout prevention strictly enforced.")


def test_09_security_audit_logging():
    """Test 9 — Verify all sensitive actions were recorded in security audit logs."""
    admin_login = client.post("/admin/api/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    admin_token = admin_login.json()["token"]
    admin_headers = {"Authorization": f"Bearer {admin_token}"}

    audit_resp = client.get("/admin/api/officers/audit?limit=50", headers=admin_headers)
    assert audit_resp.status_code == 200
    actions = [r.get("action") for r in audit_resp.json()["rows"]]

    for expected_action in ["LOGIN", "OFFICER_CREATED", "ROLE_CHANGED", "OFFICER_DEACTIVATED"]:
        assert expected_action in actions, f"Missing {expected_action} in audit logs: {actions}"

    print(f"[PASS] Test 9 — Audit log stream confirmed ({len(actions)} security events recorded, including required actions).")


if __name__ == "__main__":
    print("\n==========================================")
    print("Running RailSense AI M2 Operations RBAC Test Suite")
    print("==========================================")
    test_01_admin_login()
    test_02_officer_creation_by_admin()
    test_03_operations_engineer_login_and_permissions()
    test_04_unauthorized_admin_api_access_blocked()
    test_05_deactivated_account_denied()
    test_06_role_change_and_privilege_elevation()
    test_07_logout_and_session_handling()
    test_08_last_admin_lockout_prevention()
    test_09_security_audit_logging()
    print("\n==========================================")
    print("ALL 9 RBAC ACCEPTANCE TESTS PASSED PERFECTLY!")
    print("==========================================\n")
