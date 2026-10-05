"""
S4-M3-01 — Communication Protocol Security: Hub /messages signed AgentMessage.
Gray-box: signs valid agent tokens with the shared secret (never printed).
Valid baseline uses a read-only delay_check (no booking side effects).
"""
import json, pathlib, datetime, time, uuid
import httpx, jwt
import _harness as H

TID="S4-M3-01"; EV=H.EV/TID; EV.mkdir(parents=True, exist_ok=True)
HUB=H.base("hub")

def agent_token(sub, aud, ttl=300, secret=None, alg=None, with_aud=True):
    now=int(time.time())
    p={"sub":sub,"role":"service","iss":"railsense-hub","iat":now,"nbf":now,"exp":now+ttl}
    if with_aud: p["aud"]=aud
    return jwt.encode(p, secret or H.jwt_secret(), algorithm=alg or H.jwt_alg())

def envelope(sender, receiver, intent, token, payload=None, mid=None):
    return {"message_id":mid or f"S4TEST-{uuid.uuid4()}","sender_agent":sender,
            "receiver_agent":receiver,"intent":intent,"payload":payload or {"S4TEST":True},
            "auth_token":token,"timestamp":datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "schema_version":"1.0","hop_count":0}

def post(msg):
    with httpx.Client(timeout=15.0) as c:
        return c.post(HUB+"/messages", json=msg)

results={"tested_at":datetime.datetime.now().astimezone().isoformat(),"probes":[]}
def rec(name, expected, msg=None, raw=None):
    try:
        r = raw if raw is not None else post(msg)
        entry={"probe":name,"expected":expected,"status":r.status_code,
               "body":H.scrub(r.text[:200])}
    except Exception as e:
        entry={"probe":name,"expected":expected,"error":repr(e)[:150]}
    results["probes"].append(entry); print(entry); return entry

# a. valid baseline: passenger -> operations delay_check (read-only, allowed)
good=agent_token("passenger-agent","operations-agent")
rec("a_valid_delay_check","200/forwarded", envelope("passenger-agent","operations-agent","delay_check",good,{"train_id":"S4TEST","from":"Colombo","to":"Kandy"}))
# b. no token
rec("b_no_token","401", envelope("passenger-agent","operations-agent","delay_check",""))
# c. tampered signature
bad=good[:-2]+("aa" if good[-2:]!="aa" else "bb")
rec("c_tampered_sig","401", envelope("passenger-agent","operations-agent","delay_check",bad))
# d. alg:none
none_tok=jwt.encode({"sub":"passenger-agent","exp":int(time.time())+300},"",algorithm="none")
rec("d_alg_none","401", envelope("passenger-agent","operations-agent","delay_check",none_tok))
# e. expired
exp_tok=agent_token("passenger-agent","operations-agent",ttl=-10)
rec("e_expired","401", envelope("passenger-agent","operations-agent","delay_check",exp_tok))
# f. wrong audience (token aud=security-agent, receiver=operations-agent)
wrong_aud=agent_token("passenger-agent","security-agent")
rec("f_wrong_audience","401", envelope("passenger-agent","operations-agent","delay_check",wrong_aud))
# g. replay same message_id twice (dedup)
mid=f"S4TEST-replay-{uuid.uuid4()}"
m=envelope("passenger-agent","operations-agent","delay_check",good,{"train_id":"S4TEST"},mid=mid)
rec("g_replay_1st","200", m)
rec("g_replay_2nd","deduped/200-cached", m)
# h. disallowed interaction: passenger -> security fraud_score_request
sec_tok=agent_token("passenger-agent","security-agent")
rec("h_disallowed_passenger_to_security","403", envelope("passenger-agent","security-agent","fraud_score_request",sec_tok))
# i. spoof: sender_agent=operations-agent but token.sub=passenger-agent
spoof=agent_token("passenger-agent","booking-agent")
rec("i_sender_spoof","401", envelope("operations-agent","booking-agent","ack",spoof))
# j. schema abuse: missing required field
with httpx.Client(timeout=10) as c:
    r=c.post(HUB+"/messages", json={"sender_agent":"passenger-agent"})
    rec("j_missing_fields","422", raw=r)
# j2 oversized payload (200KB)
big=agent_token("passenger-agent","operations-agent")
rec("j2_oversized_payload","handled", envelope("passenger-agent","operations-agent","delay_check",big,{"x":"A"*200000}))
# k. /register rogue agent
with httpx.Client(timeout=10) as c:
    r=c.post(HUB+"/register", json={"agent_name":"S4TEST-rogue","callback_url":"http://127.0.0.1:9999"})
    rec("k_register_rogue","404/read-only", raw=r)
    r2=c.post(HUB+"/register", json={"agent_name":"operations-agent","callback_url":"http://evil.example"})
    rec("k_register_overwrite_existing","read-only-no-change", raw=r2)

# audit visibility: does timeline show our rejected + accepted S4TEST messages?
with httpx.Client(timeout=10) as c:
    tl=c.get(HUB+"/api/hub/timeline", params={"sender":"passenger-agent"})
    txt=tl.text
    results["audit_timeline"]={"status":tl.status_code,
        "mentions_S4TEST": "S4TEST" in txt,
        "has_REJECTED": "REJECTED" in txt or "rejected" in txt,
        "snippet":H.scrub(txt[:400])}
    print("audit timeline status",tl.status_code,"S4TEST in log:", "S4TEST" in txt)

(EV/"results.json").write_text(json.dumps(results,indent=2),encoding="utf-8")
print("\nSaved",EV/"results.json")
