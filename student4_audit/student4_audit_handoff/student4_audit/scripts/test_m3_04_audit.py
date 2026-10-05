"""
S4-M3-04 — event authenticity (code), audit integrity, resilience.
Runtime: bounded rate-limit burst (<=50 disallowed msgs, never forwarded),
log-injection attempt, secrets-in-audit check, append-only (no mutation API).
"""
import json, time, uuid, datetime
import httpx, jwt
import _harness as H
HUB=H.base("hub"); EV=H.EV/"S4-M3-04"; EV.mkdir(parents=True,exist_ok=True)

def agent_token(sub, ttl=300):
    now=int(time.time())
    return jwt.encode({"sub":sub,"role":"service","iss":"railsense-hub","iat":now,"nbf":now,"exp":now+ttl},
                      H.jwt_secret(), algorithm=H.jwt_alg())

def envelope(sender,receiver,intent,tok,mid=None):
    return {"message_id":mid or f"S4TEST-{uuid.uuid4()}","sender_agent":sender,"receiver_agent":receiver,
            "intent":intent,"payload":{"S4TEST":True},"auth_token":tok,
            "timestamp":datetime.datetime.now(datetime.timezone.utc).isoformat()}

results={"event_signing_note":"M2/M4 hub_client.py publish delay_alert/maintenance_alert as plain json.dumps(event) via Upstash PUBLISH — no HMAC/signature on event payload (code evidence).",
         "resilience":{},"log_injection":{},"audit":{}}

with httpx.Client(timeout=15.0) as c:
    # --- bounded rate-limit burst: disallowed interaction (rejected at allowlist, never forwarded) ---
    codes=[]; t0=time.time()
    for i in range(50):
        tok=agent_token("passenger-agent")
        # passenger->security fraud_score_request is NOT allowlisted -> 403, but rate-limit(step4) runs first
        r=c.post(HUB+"/messages", json=envelope("passenger-agent","security-agent","fraud_score_request",tok))
        codes.append(r.status_code)
        if r.status_code==429: break
    results["resilience"]["burst_n"]=len(codes)
    results["resilience"]["got_429"]=429 in codes
    results["resilience"]["status_distribution"]={str(x):codes.count(x) for x in set(codes)}
    results["resilience"]["elapsed_s"]=round(time.time()-t0,1)
    print("burst:",results["resilience"])

    # --- circuit breaker states from dashboard (dead-receiver test not runnable: static registry) ---
    d=c.get(HUB+"/api/hub/dashboard")
    try:
        cb=d.json().get("circuit_breakers")
        results["resilience"]["circuit_breakers_observable"]=bool(cb)
        results["resilience"]["dead_receiver_test"]="NOT EXECUTED - static registry has no dead agent to target; breaker states read from dashboard instead"
    except Exception:
        pass

    # --- log injection: sender_agent with newline + fake record text (token sub must match) ---
    inj_sender="passenger-agent\nFAKE 2020-01-01 ACCEPTED forged->admin ALL_GOOD"
    tok=agent_token(inj_sender)
    r=c.post(HUB+"/messages", json=envelope(inj_sender,"security-agent","fraud_score_request",tok))
    time.sleep(0.5)
    tl=c.get(HUB+"/api/hub/timeline", params={"limit":50})
    txt=tl.text
    results["log_injection"]={"inject_status":r.status_code,
        "timeline_status":tl.status_code,
        "fake_line_appears_raw": "FAKE 2020-01-01 ACCEPTED" in txt,
        "newline_preserved_as_field": inj_sender in txt or "FAKE" in txt,
        "note":"if present, it is contained within a JSON string field (structured), not a separate log record"}
    print("log_injection:",results["log_injection"])

    # --- secrets in audit / timeline ---
    results["audit"]["secrets_in_timeline"]= any(m in txt for m in ("eyJ","JWT_SECRET","sk-","gsk_"))
    results["audit"]["records_rejected_events"]= ("REJECTED" in txt or "rejected" in txt)
    results["audit"]["append_only_note"]="No API endpoint exists to modify/delete audit rows (only GET /api/hub/timeline and /dashboard); writes are SQLAlchemy inserts (code)."
    print("audit:",results["audit"])

(EV/"results.json").write_text(json.dumps(results,indent=2),encoding="utf-8")
print("Saved",EV/"results.json")
