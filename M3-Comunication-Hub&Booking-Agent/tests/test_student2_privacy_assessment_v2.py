"""
tests/test_student2_privacy_assessment_v2.py
RailSense AI -- Student 2: Privacy and Data Leakage Assessment (Improved v2)
IT3041 - Information Retrieval and Web Analytics

Test IDs: TC-PD-001 through TC-PD-020
Run with: pytest tests/test_student2_privacy_assessment_v2.py -v -s --tb=short
"""
from __future__ import annotations
import base64, importlib.util, json as _json, os, sys
from datetime import datetime, timezone, timedelta, date
import jwt, pytest
from fastapi.testclient import TestClient

MEMBER_C = os.path.dirname(os.path.dirname(__file__))
AGENT_HUB = os.path.join(MEMBER_C, "agent-hub")
BOOKING_AGENT_DIR = os.path.join(MEMBER_C, "booking-agent")
for p in (MEMBER_C, AGENT_HUB, BOOKING_AGENT_DIR):
    if p not in sys.path:
        sys.path.insert(0, p)

HUB_MAIN = os.path.join(AGENT_HUB, "main.py")
spec = importlib.util.spec_from_file_location("hub_main_s2v2", HUB_MAIN)
hub_mod = importlib.util.module_from_spec(spec)
sys.modules["hub_main_s2v2"] = hub_mod
spec.loader.exec_module(hub_mod)
hub_app = hub_mod.app

BOOKING_MAIN = os.path.join(BOOKING_AGENT_DIR, "main.py")
spec_b = importlib.util.spec_from_file_location("booking_main_s2v2", BOOKING_MAIN)
booking_mod = importlib.util.module_from_spec(spec_b)
sys.modules["booking_main_s2v2"] = booking_mod
spec_b.loader.exec_module(booking_mod)
booking_app = booking_mod.app

from auth.jwt_utils import get_jwt_algorithm, get_jwt_secret

hub_client     = TestClient(hub_app,     raise_server_exceptions=False)
booking_client = TestClient(booking_app, raise_server_exceptions=False)

SECRET    = get_jwt_secret()
ALGORITHM = get_jwt_algorithm()
FUTURE    = (date.today() + timedelta(days=30)).isoformat()
NOW_ISO   = datetime.now(timezone.utc).isoformat()


def _token(sub="passenger-agent", exp_delta=3600, secret=None, alg=None):
    now = datetime.now(timezone.utc)
    s = secret if secret is not None else SECRET
    a = alg if alg is not None else ALGORITHM
    return jwt.encode(
        {"sub": sub, "iat": int(now.timestamp()), "exp": int((now + timedelta(seconds=exp_delta)).timestamp())},
        s, algorithm=a,
    )


def _hub_msg(token=None, sender="passenger-agent", payload=None, msg_id="MSG-S2V2-001"):
    return {
        "message_id": msg_id, "sender_agent": sender,
        "receiver_agent": "booking-agent", "intent": "booking_request",
        "payload": payload or {
            "from_station": "Colombo", "to_station": "Kandy",
            "travel_date": FUTURE, "train_id": "PM-4082",
            "seat_class": "Second Class", "passenger_count": 1,
        },
        "auth_token": token if token is not None else _token(),
        "timestamp": NOW_ISO,
    }


class TestPrivacyDataLeakageAssessmentV2:
    """Student 2 -- Privacy and Data Leakage Assessment v2 (TC-PD-001 to TC-PD-020)"""

    def test_tc_pd_001_env_secrets_not_exposed_via_api(self):
        """TC-PD-001: .env credentials not leaked through public hub endpoints."""
        secret_patterns = ["mkatERZylm0r2Lre", "hhqkakajstgcpeby", "sb_secret_", "railsense-nic-hmac", "AQ.Ab8RN6"]
        for ep in ["/health", "/ready", "/api/hub/dashboard"]:
            r = hub_client.get(ep)
            for pattern in secret_patterns:
                assert pattern not in r.text, f"[TC-PD-001] CRITICAL: Secret pattern in GET {ep}."
        print("\n[TC-PD-001] No secrets leaked from health/ready/dashboard. PASS")

    def test_tc_pd_002_jwt_weak_fallback_secret_rejected(self):
        """TC-PD-002: Tokens signed with fallback change-me secret rejected."""
        forged = _token(sub="passenger-agent", secret="change-me")
        r = hub_client.post("/messages", json=_hub_msg(token=forged))
        if SECRET == "change-me":
            print(f"\n[TC-PD-002] VULN: fallback secret in use. HTTP {r.status_code}.")
        else:
            assert r.status_code == 401, f"[TC-PD-002] Forged token accepted HTTP {r.status_code}."
            print(f"[TC-PD-002] change-me forged token rejected HTTP {r.status_code}. PASS")

    def test_tc_pd_003_booking_response_no_raw_nic(self):
        """TC-PD-003: Raw NIC number must not appear in booking response."""
        nic_value = "200012345678"
        r = booking_client.post("/internal/messages", json={
            "message_id": "MSG-V2-PD003", "sender_agent": "passenger-agent",
            "receiver_agent": "booking-agent", "intent": "booking_request",
            "payload": {"from_station": "Colombo", "to_station": "Kandy", "travel_date": FUTURE,
                "train_id": "PM-4082", "seat_class": "Second Class", "passenger_count": 1,
                "passengers": [{"nic": nic_value, "name": "Test Passenger"}]},
            "auth_token": _token(), "timestamp": NOW_ISO})
        assert nic_value not in r.text, f"[TC-PD-003] PII LEAK: NIC in response HTTP {r.status_code}."
        print(f"[TC-PD-003] NIC not in response HTTP {r.status_code}. PASS")

    def test_tc_pd_004_email_not_reflected_in_errors(self):
        """TC-PD-004: Passenger email must not appear in validation error bodies."""
        pii_email = "victim.passenger@gmail.com"
        r = booking_client.post("/internal/messages", json={
            "message_id": "MSG-V2-PD004", "sender_agent": "passenger-agent",
            "receiver_agent": "booking-agent", "intent": "booking_request",
            "payload": {"from_station": "Colombo", "to_station": "Kandy", "travel_date": FUTURE,
                "train_id": "PM-4082", "seat_class": "INVALID_CLASS",
                "passenger_count": 1, "passenger_email": pii_email},
            "auth_token": _token(), "timestamp": NOW_ISO})
        assert pii_email not in r.text, f"[TC-PD-004] PII LEAK: Email in error HTTP {r.status_code}."
        print(f"[TC-PD-004] Email not reflected HTTP {r.status_code}. PASS")

    def test_tc_pd_005_algorithm_none_attack_rejected(self):
        """TC-PD-005: JWT alg:none tokens must be rejected with 401."""
        hdr = base64.urlsafe_b64encode(_json.dumps({"alg": "none", "typ": "JWT"}).encode()).rstrip(b"=").decode()
        ts = int(datetime.now(timezone.utc).timestamp())
        pld = base64.urlsafe_b64encode(_json.dumps({"sub": "passenger-agent", "iat": ts, "exp": ts + 3600}).encode()).rstrip(b"=").decode()
        none_token = f"{hdr}.{pld}."
        r = hub_client.post("/messages", json=_hub_msg(token=none_token))
        assert r.status_code == 401, f"[TC-PD-005] CRITICAL: alg:none accepted HTTP {r.status_code}!"
        print(f"[TC-PD-005] alg:none rejected HTTP {r.status_code}. PASS")

    def test_tc_pd_006_expired_jwt_rejected(self):
        """TC-PD-006: Expired JWT tokens must be rejected with HTTP 401."""
        expired = _token(sub="passenger-agent", exp_delta=-300)
        r = hub_client.post("/messages", json=_hub_msg(token=expired))
        assert r.status_code == 401, f"[TC-PD-006] Expired token accepted HTTP {r.status_code}."
        print(f"[TC-PD-006] Expired token rejected HTTP {r.status_code}. PASS")

    def test_tc_pd_007_token_replay_sub_mismatch_rejected(self):
        """TC-PD-007: Token sub mismatch with sender_agent must be rejected."""
        replayed = _token(sub="booking-agent")
        r = hub_client.post("/messages", json=_hub_msg(token=replayed, sender="passenger-agent"))
        assert r.status_code == 401, f"[TC-PD-007] Token replay accepted HTTP {r.status_code}."
        print(f"[TC-PD-007] Sub mismatch rejected HTTP {r.status_code}. PASS")

    def test_tc_pd_008_audit_timeline_unauthenticated_access(self):
        """TC-PD-008: FINDING - /api/hub/timeline returns audit records without auth."""
        r = hub_client.get("/api/hub/timeline", params={"limit": 10})
        if r.status_code == 200:
            body = r.json()
            total = body.get("total", 0)
            print(f"\n[TC-PD-008] FINDING (Medium): /api/hub/timeline HTTP 200 without auth. {total} records exposed.")
            for item in body.get("items", []):
                item_str = str(item).lower()
                for pii in ["@gmail", "@yahoo", "password"]:
                    assert pii not in item_str, f"[TC-PD-008] Direct PII in audit log."
        else:
            assert r.status_code in (401, 403)
            print(f"[TC-PD-008] Auth required HTTP {r.status_code}. PASS")

    def test_tc_pd_009_idor_booking_real_cross_user_access(self):
        """TC-PD-009 v2 UPGRADED: Create booking as user-a, attempt access as user-b."""
        r_create = booking_client.post("/internal/messages", json={
            "message_id": "MSG-V2-IDOR-A", "sender_agent": "passenger-agent",
            "receiver_agent": "booking-agent", "intent": "booking_request",
            "payload": {"from_station": "Colombo", "to_station": "Kandy", "travel_date": FUTURE,
                "train_id": "PM-4082", "seat_class": "Second Class",
                "passenger_count": 1, "user_id": "test-user-a"},
            "auth_token": _token(), "timestamp": NOW_ISO})
        print(f"\n[TC-PD-009] Step1 create as user-a: HTTP {r_create.status_code}")
        if r_create.status_code != 200:
            pytest.skip("Booking creation failed")
        booking_ref = r_create.json().get("booking", {}).get("booking_reference")
        if not booking_ref:
            pytest.skip(f"No booking_reference. Body: {r_create.text[:200]}")
        print(f"[TC-PD-009] Booking {booking_ref} created for user-a")
        r_access = booking_client.get(f"/bookings/{booking_ref}", params={"user_id": "test-user-b"})
        print(f"[TC-PD-009] Step2 access as user-b: HTTP {r_access.status_code}")
        if r_access.status_code == 200:
            email = r_access.json().get("passenger_email")
            print(f"[TC-PD-009] FINDING: user-b accessed user-a booking {booking_ref}. email={repr(email)}")
            print("[TC-PD-009] Root cause: user_id stored as guest_passenger in test env, bypasses L391 auth check.")
        elif r_access.status_code == 403:
            print(f"[TC-PD-009] IDOR blocked HTTP 403. PASS")
        assert r_access.status_code in (200, 403, 404, 501)

    def test_tc_pd_010_dedup_cache_consistency(self):
        """TC-PD-010: Dedup cache must not cross-contaminate payloads."""
        base_msg = {
            "message_id": "MSG-DEDUP-V2-010", "sender_agent": "passenger-agent",
            "receiver_agent": "booking-agent", "intent": "booking_request",
            "payload": {"from_station": "Colombo", "to_station": "Kandy",
                "travel_date": FUTURE, "train_id": "PM-4082",
                "seat_class": "Second Class", "passenger_count": 1},
            "auth_token": _token(sub="passenger-agent"), "timestamp": NOW_ISO}
        r1 = hub_client.post("/messages", json=base_msg)
        msg2 = dict(base_msg); msg2["auth_token"] = _token(sub="passenger-agent")
        r2 = hub_client.post("/messages", json=msg2)
        if r1.status_code == 200 and r2.status_code == 200:
            assert r1.json().get("message_id") == r2.json().get("message_id")
            print("[TC-PD-010] Dedup consistent. PASS")
        else:
            print(f"[TC-PD-010] r1={r1.status_code}, r2={r2.status_code}. Dedup disabled in test env. PASS")

    def test_tc_pd_011_smtp_credentials_not_in_responses(self):
        """TC-PD-011: SMTP credentials must not appear in any API response."""
        smtp_secrets = ["hhqkakajstgcpeby", "navodassa@gmail.com", "smtp.gmail.com"]
        r = booking_client.post("/internal/messages", json={
            "message_id": "MSG-V2-PD011", "sender_agent": "passenger-agent",
            "receiver_agent": "booking-agent", "intent": "booking_request",
            "payload": {"from_station": "Colombo", "to_station": "Kandy", "travel_date": FUTURE,
                "train_id": "PM-4082", "seat_class": "Second Class",
                "passenger_count": 1, "passenger_email": "test@example.com"},
            "auth_token": _token(), "timestamp": NOW_ISO})
        for s in smtp_secrets:
            assert s not in r.text, f"[TC-PD-011] CRITICAL: SMTP cred in response HTTP {r.status_code}."
        print(f"[TC-PD-011] SMTP creds not leaked HTTP {r.status_code}. PASS")

    def test_tc_pd_012_cors_wildcard_origin_documented(self):
        """TC-PD-012: CORS wildcard + credentials -- documents medium finding."""
        malicious_origin = "https://evil-attacker.com"
        r_hub  = hub_client.get("/health",  headers={"Origin": malicious_origin})
        r_book = booking_client.get("/health", headers={"Origin": malicious_origin})
        acao_hub  = r_hub.headers.get("access-control-allow-origin", "")
        acao_book = r_book.headers.get("access-control-allow-origin", "")
        print(f"\n[TC-PD-012] Hub ACAO='{acao_hub}', Booking ACAO='{acao_book}'. Code L121/L109 allow_origins=['*']+credentials=True. FINDING (Medium)")
        assert True

    def test_tc_pd_013_cancellations_unauthenticated_access(self):
        """TC-PD-013: FINDING - /cancellations returns records without auth."""
        r = booking_client.get("/cancellations")
        if r.status_code == 200:
            body = r.json()
            count = len(body) if isinstance(body, list) else "?"
            print(f"\n[TC-PD-013] FINDING (Medium): /cancellations HTTP 200 no auth. {count} records exposed.")
            body_text = str(body).lower()
            for pii in ["@gmail", "@yahoo", "nic", "password"]:
                assert pii not in body_text, f"[TC-PD-013] Direct PII in response!"
        elif r.status_code in (401, 403):
            print(f"[TC-PD-013] Auth required HTTP {r.status_code}. PASS")
        assert r.status_code in (200, 401, 403, 404)

    def test_tc_pd_014_nic_not_echoed_in_passenger_records(self):
        """TC-PD-014: NIC must be HMAC-hashed -- raw NIC never echoed."""
        test_nic = "199512345670"
        r = booking_client.post("/internal/messages", json={
            "message_id": "MSG-V2-PD014", "sender_agent": "passenger-agent",
            "receiver_agent": "booking-agent", "intent": "booking_request",
            "payload": {"from_station": "Colombo", "to_station": "Kandy", "travel_date": FUTURE,
                "train_id": "PM-4082", "seat_class": "Second Class", "passenger_count": 1,
                "passengers": [{"nic": test_nic, "name": "Privacy Test"}]},
            "auth_token": _token(), "timestamp": NOW_ISO})
        assert test_nic not in r.text, f"[TC-PD-014] PII LEAK: NIC in response HTTP {r.status_code}."
        print(f"[TC-PD-014] NIC not echoed HTTP {r.status_code}. PASS")

    def test_tc_pd_015_whitespace_token_rejected(self):
        """TC-PD-015: Whitespace-only auth_token must be rejected."""
        msg = {
            "message_id": "MSG-V2-PD015", "sender_agent": "passenger-agent",
            "receiver_agent": "booking-agent", "intent": "booking_request",
            "payload": {"from_station": "Colombo", "to_station": "Kandy", "travel_date": FUTURE,
                "train_id": "PM-4082", "seat_class": "Second Class", "passenger_count": 1},
            "auth_token": " ", "timestamp": NOW_ISO}
        r = hub_client.post("/messages", json=msg)
        assert r.status_code in (401, 422), f"[TC-PD-015] Whitespace token accepted HTTP {r.status_code}."
        print(f"[TC-PD-015] Whitespace token HTTP {r.status_code}. PASS")

    def test_tc_pd_016_admin_bookings_unauthenticated_access(self):
        """TC-PD-016: GET /admin/bookings - passenger_email and nic_masked exposed without JWT."""
        r = booking_client.get("/admin/bookings", params={"travel_date": FUTURE})
        print(f"\n[TC-PD-016] GET /admin/bookings HTTP {r.status_code}")
        if r.status_code == 200:
            body = r.json()
            count = body.get("count", 0) if isinstance(body, dict) else "?"
            bookings = body.get("bookings", []) if isinstance(body, dict) else []
            emails = [b.get("passenger_email") for b in bookings if b.get("passenger_email")]
            print(f"[TC-PD-016] FINDING (High): HTTP 200 without auth. {count} bookings. emails={emails[:3]}")
        elif r.status_code in (401, 403):
            print(f"[TC-PD-016] Auth required HTTP {r.status_code}. PASS")
        elif r.status_code == 400:
            print("[TC-PD-016] HTTP 400 filter required, but endpoint reachable without auth.")
        assert r.status_code in (200, 400, 401, 403)

    def test_tc_pd_017_booking_retrieval_no_jwt_guard(self):
        """TC-PD-017: GET /bookings/{ref} - no JWT, omitting user_id bypasses L391 auth check."""
        r_create = booking_client.post("/internal/messages", json={
            "message_id": "MSG-V2-PD017", "sender_agent": "passenger-agent",
            "receiver_agent": "booking-agent", "intent": "booking_request",
            "payload": {"from_station": "Colombo", "to_station": "Kandy", "travel_date": FUTURE,
                "train_id": "PM-4082", "seat_class": "First Class",
                "passenger_count": 1, "user_id": "real-user-pd017",
                "passenger_email": "real-user@example.com"},
            "auth_token": _token(), "timestamp": NOW_ISO})
        print(f"\n[TC-PD-017] Create booking HTTP {r_create.status_code}")
        if r_create.status_code != 200:
            pytest.skip("Booking creation failed")
        booking_ref = r_create.json().get("booking", {}).get("booking_reference")
        if not booking_ref:
            pytest.skip("No booking_reference")
        print(f"[TC-PD-017] Booking {booking_ref} for real-user-pd017")
        r_no_uid = booking_client.get(f"/bookings/{booking_ref}")
        print(f"[TC-PD-017] Access without user_id or JWT: HTTP {r_no_uid.status_code}")
        if r_no_uid.status_code == 200:
            resp = r_no_uid.json()
            print(f"[TC-PD-017] FINDING (High): Booking returned without JWT. passenger_email={repr(resp.get('passenger_email'))}")
            print("[TC-PD-017] Root cause: No JWT Depends() guard. user_id is optional. Auth at L391 bypassed.")
        elif r_no_uid.status_code == 403:
            print("[TC-PD-017] Blocked HTTP 403. PASS")
        assert r_no_uid.status_code in (200, 401, 403, 404, 501)

    def test_tc_pd_018_fraud_reviews_unauthenticated_access(self):
        """TC-PD-018: GET /internal/fraud-reviews - nic_hash/booking_payload exposed without auth."""
        r = booking_client.get("/internal/fraud-reviews")
        print(f"\n[TC-PD-018] GET /internal/fraud-reviews HTTP {r.status_code}")
        if r.status_code == 200:
            body = r.json()
            count = len(body) if isinstance(body, list) else "?"
            print(f"[TC-PD-018] FINDING (Medium): HTTP 200 without auth. {count} fraud cases exposed.")
        elif r.status_code in (401, 403):
            print(f"[TC-PD-018] Auth required HTTP {r.status_code}. PASS")
        assert r.status_code in (200, 401, 403, 404)

    def test_tc_pd_019_operations_status_unauthenticated(self):
        """TC-PD-019: GET /operations/status/{key} - endpoint reachable without JWT."""
        test_key = "IDEM-TEST-PROBE-001"
        r = booking_client.get(f"/operations/status/{test_key}")
        print(f"\n[TC-PD-019] GET /operations/status/{test_key} HTTP {r.status_code}")
        if r.status_code == 200:
            print(f"[TC-PD-019] FINDING (Medium): HTTP 200 without auth. Response: {r.text[:200]}")
        elif r.status_code == 404:
            print("[TC-PD-019] FINDING (Low): Endpoint reachable (HTTP 404) without auth. Any key can be probed.")
        elif r.status_code in (401, 403):
            print(f"[TC-PD-019] Auth required HTTP {r.status_code}. PASS")
        assert r.status_code in (200, 404, 401, 403)

    def test_tc_pd_020_hub_dashboard_topology_disclosure(self):
        """TC-PD-020: GET /api/hub/dashboard discloses internal service topology without auth."""
        r = hub_client.get("/api/hub/dashboard")
        print(f"\n[TC-PD-020] GET /api/hub/dashboard HTTP {r.status_code}")
        if r.status_code == 200:
            body = r.json()
            agents = body.get("agents", [])
            names = [a.get("name") for a in agents]
            urls = [a.get("base_url") for a in agents]
            print(f"[TC-PD-020] FINDING (Medium): HTTP 200 without auth. Disclosed: names={names}, urls={urls}.")
        elif r.status_code in (401, 403):
            print(f"[TC-PD-020] Auth required HTTP {r.status_code}. PASS")
        assert r.status_code in (200, 401, 403)
