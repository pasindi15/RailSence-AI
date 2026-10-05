"""
Stage-2 supplementary probes (gap closure only — no new attack classes).
  G1  S4-M4-03  engineer login transcript with the correct schema (hard-coded cred) + wrong-password control
  G2  S4-M4-03  telemetry fuzz on /asset-health WITH a valid asset_type so field validation is actually reached
  G3  S4-M3-01  clean replay/dedup demo with a routable read-only delay_check (train id evidenced in raw_text)
  G4  S4-M3-03  NIC cleartext re-verification on the unauth fraud queue (booleans/counts only, no values)
  G5  F-06      socket bind listing for all service ports
  G6  cleanup   final proof no S4TEST_ objects remain active
Local-only. Secrets never printed; tokens masked.
"""
import json, re, time, uuid, datetime, subprocess
import httpx, jwt
import _harness as H

EV = H.EV / "stage2_supplementary"; EV.mkdir(parents=True, exist_ok=True)
now = lambda: datetime.datetime.now().astimezone().isoformat()
out = {"run_at": now()}

with httpx.Client(timeout=60.0) as c:
    M4 = H.base("m4")
    # ---------------- G1 ----------------
    g1 = {}
    r = c.post(M4 + "/api/engineer-login", json={"engineer_id": "admin", "password": H.M4_ENG_PW})
    body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
    g1["hardcoded_admin_login"] = {"status": r.status_code, "success": body.get("success"),
        "eng_id": body.get("eng_id"), "role": body.get("role"),
        "token_masked": (body.get("token", "")[:6] + "…[MASKED]") if body.get("token") else None}
    eng_tok = body.get("token")
    r = c.post(M4 + "/api/engineer-login", json={"engineer_id": "admin", "password": "wrong-S4TEST"})
    g1["wrong_password_control"] = {"status": r.status_code, "body": r.text[:120]}
    out["G1_engineer_login"] = g1

    # ---------------- G2 ----------------
    base_ok = {"asset_id": "S4TEST-A9", "asset_type": "brake_system"}
    cases = {
        "valid_baseline": {},
        "negative_days": {"days_since_service": -5},
        "huge_days": {"days_since_service": 999999},
        "string_for_int": {"days_since_service": "abc"},
        "fault_count_over_max": {"fault_count_30d": 1000},
        "nan_sensor": {"sensors": {"temp": "NaN"}},
        "inf_sensor": {"sensors": {"temp": 1e308}},
        "huge_sensor_dict": {"sensors": {f"k{i}": i for i in range(5000)}},
        "invalid_asset_type": {"asset_type": "rocket"},
        "asset_id_too_long": {"asset_id": "S4TEST" + "X" * 60},
        "html_in_fault_type": {"fault_type": "<script>x</script>"},
    }
    g2 = []
    for name, patch in cases.items():
        p = dict(base_ok); p.update(patch)
        try:
            r = c.post(M4 + "/asset-health", json=p)
            g2.append({"case": name, "status": r.status_code, "is_500": r.status_code >= 500,
                       "body": H.scrub(r.text[:160])})
        except Exception as e:
            g2.append({"case": name, "error": repr(e)[:120]})
        time.sleep(2.1)  # stay under the 30/minute limiter
    out["G2_telemetry_fuzz"] = g2

    # ---------------- G3 ----------------
    HUB = H.base("hub")
    def tok():
        n = int(time.time())
        return jwt.encode({"sub": "passenger-agent", "role": "service", "iss": "railsense-hub",
                           "aud": "operations-agent", "iat": n, "nbf": n, "exp": n + 300},
                          H.jwt_secret(), algorithm=H.jwt_alg())
    mid = f"S4TEST-replay2-{uuid.uuid4()}"
    msg = {"message_id": mid, "sender_agent": "passenger-agent", "receiver_agent": "operations-agent",
           "intent": "delay_check", "payload": {"train_id": "PM-8056", "raw_text": "Is PM-8056 delayed today?"},
           "auth_token": tok(), "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
           "schema_version": "1.0", "hop_count": 0}
    r1 = c.post(HUB + "/messages", json=msg)
    r2 = c.post(HUB + "/messages", json=msg)
    tl = c.get(HUB + "/api/hub/timeline", params={"limit": 50})
    items = tl.json().get("items", []) if tl.status_code == 200 else []
    rows = [i for i in items if i.get("message_id") == mid]
    out["G3_replay_dedup"] = {
        "message_id": mid, "first": {"status": r1.status_code, "body": H.scrub(r1.text[:200])},
        "second": {"status": r2.status_code, "body": H.scrub(r2.text[:200])},
        "bodies_identical": r1.text == r2.text,
        "audit_rows_for_message_id": len(rows),
        "audit_statuses": [i.get("status") for i in rows],
        "interpretation": "dedup proven if first=200, second=200 identical body, and only ONE audit row "
                          "(dedup returns at step 7 before the step-8 audit insert, agent-hub/main.py:361-365)"}

    # ---------------- G4 ----------------
    r = c.get("http://127.0.0.1:3000/api/admin/fraud-reviews")
    nic_re = re.compile(r"(?<![0-9A-Fa-f])(\d{9}[VvXx]|\d{12})(?![0-9A-Fa-f])")
    hits = {}
    def walk(o, key=""):
        if isinstance(o, dict):
            for k, v in o.items(): walk(v, k)
        elif isinstance(o, list):
            for v in o: walk(v, key)
        elif isinstance(o, str) and nic_re.search(o):
            hits[key] = hits.get(key, 0) + 1
    data = r.json() if r.status_code == 200 else {}
    walk(data)
    recs = data if isinstance(data, list) else next((v for v in data.values() if isinstance(v, list)), [])
    out["G4_nic_reverify"] = {
        "status_unauth_port3000": r.status_code, "record_count": len(recs),
        "nic_like_matches_by_field": hits,
        "matches_outside_hash_fields": {k: v for k, v in hits.items() if "hash" not in k.lower()},
        "note": "hex-bounded regex; Stage-1 unbounded regex matched 12-digit runs inside nic_hash hex strings"}

    # ---------------- G6 ----------------
    g6 = {}
    adm = H.admin_token(c)
    il = c.get(H.base("m2") + "/incidents", headers={"Authorization": f"Bearer {adm}"})
    g6["m2_incidents_with_S4TEST"] = il.text.count("S4TEST") if il.status_code == 200 else f"status {il.status_code}"
    mf = c.get(H.base("m2") + "/api/incidents/map-feed")
    g6["m2_map_feed_S4TEST"] = mf.text.count("S4TEST")
    tm = c.get(M4 + "/api/trains-under-maintenance")
    g6["m4_trains_under_maintenance_S4TEST"] = tm.text.count("S4TEST")
    off = c.get(H.base("m2") + "/admin/api/officers", headers={"Authorization": f"Bearer {adm}"})
    lst = off.json() if off.status_code == 200 else []
    lst = lst if isinstance(lst, list) else lst.get("officers", [])
    g6["m2_s4test_officers"] = [{"email_prefix": o.get("email", "")[:13], "status": o.get("status")}
                                for o in lst if "s4test" in (o.get("email") or "").lower()]
    if eng_tok:  # log the G1 session out again if an endpoint exists (best-effort)
        lo = c.post(M4 + "/api/engineer-logout", headers={"x-engineer-token": eng_tok})
        g6["m4_engineer_logout_status"] = lo.status_code
    out["G6_cleanup_verify"] = g6

# ---------------- G5 ----------------
ns = subprocess.run(["netstat", "-ano", "-p", "TCP"], capture_output=True, text=True).stdout
ports = [":3000", ":3001", ":8001", ":8002", ":8003", ":8004", ":8005", ":8006"]
out["G5_bind_listing"] = sorted({" ".join(l.split()[:4]) for l in ns.splitlines()
                                 if "LISTENING" in l and any(l.split()[1].endswith(p) for p in ports)})

fr = (H.ROOT / "M4-maintenance-agent" / "data" / "field_reports.jsonl").read_text(encoding="utf-8")
out["G6_cleanup_verify"]["m4_field_reports_S4TEST"] = [
    {"report_id": j.get("report_id", "")[:8], "status": j.get("status")}
    for j in (json.loads(l) for l in fr.splitlines() if "S4TEST" in l)]

text = H.scrub(json.dumps(out, indent=2, ensure_ascii=False))
(EV / "results.json").write_text(text, encoding="utf-8")
print(text)
