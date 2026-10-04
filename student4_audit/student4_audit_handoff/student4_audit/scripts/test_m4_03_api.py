"""
S4-M4-03 — M4 maintenance endpoints: auth, authz, API security.
Policy: flag-train/unflag full write-test with S4TEST train + revert (log both calls).
Engineer login uses hard-coded repo cred admin/<documented M4 password> (documented finding).
"""
import json, pathlib, datetime, time, uuid, math
import httpx, jwt
import _harness as H

TID="S4-M4-03"; EV=H.EV/TID; EV.mkdir(parents=True, exist_ok=True)
M4=H.base("m4"); TEST_TRAIN="S4TEST-TRAIN-001"
results={"tested_at":datetime.datetime.now().astimezone().isoformat()}

def forged_hub_token():
    now=int(time.time())
    return jwt.encode({"sub":"operations-agent","exp":now+300},"wrong-secret",algorithm="HS256")

with httpx.Client(timeout=15.0) as c:
    # ---- A. flag-train auth gate (no token) across surfaces ----
    gate=[]
    for label,url in [("direct_8006",M4+"/api/flag-train"),
                      ("gateway3000_public",H.base("user")+"/svc/m4/api/flag-train"),
                      ("gateway3001_admin",H.base("admin")+"/svc/m4/api/flag-train")]:
        r=c.post(url, json={"train_id":TEST_TRAIN,"reason":"S4TEST"})
        gate.append({"surface":label,"status":r.status_code,
                     "auth_rejected":r.status_code in (401,403),"body":H.scrub(r.text[:120])})
    results["flag_train_auth_gate"]=gate
    print("gate:",[(g['surface'],g['status']) for g in gate])

    # ---- B. engineer login (hard-coded repo cred) ----
    lr=c.post(M4+"/api/engineer-login", json={"username":"admin","password":H.M4_ENG_PW})
    etok=None
    if lr.status_code==200:
        d=lr.json(); etok=d.get("token") or d.get("session_token") or d.get("access_token")
    results["engineer_login"]={"status":lr.status_code,"got_token":bool(etok),
        "cred":"admin/<documented M4 password> (hard-coded in source)"}
    print("engineer_login:",lr.status_code,"token:",bool(etok))

    # ---- C. authorized flag S4TEST train, then revert (log both) ----
    if etok:
        h={"x-engineer-token":etok}
        fr=c.post(M4+"/api/flag-train", headers=h, json={"train_id":TEST_TRAIN,"reason":"S4TEST audit flag"})
        rev=c.delete(M4+f"/api/flag-train/{TEST_TRAIN}", headers=h)
        results["flag_and_revert"]={
            "flag":{"status":fr.status_code,"body":H.scrub(fr.text[:200])},
            "revert":{"status":rev.status_code,"body":H.scrub(rev.text[:200])}}
        print("flag:",fr.status_code,"revert:",rev.status_code)
        # verify it's gone
        chk=c.get(M4+"/api/trains-under-maintenance")
        results["flag_and_revert"]["still_flagged_after_revert"]=TEST_TRAIN in chk.text

    # ---- D. telemetry validation on /asset-health & /maintenance-report ----
    tele=[]
    bad_payloads={
        "negative":{"asset_id":"S4TEST","service_age_years":-5,"fault_count":-1,"telemetry":{"temp":-999}},
        "nan":{"asset_id":"S4TEST","service_age_years":float("nan") if False else "NaN","telemetry":{"temp":"NaN"}},
        "inf":{"asset_id":"S4TEST","service_age_years":1e309 if False else "1e309","telemetry":{"temp":1e308}},
        "string_for_number":{"asset_id":"S4TEST","service_age_years":"lots","fault_count":"many"},
        "huge_array":{"asset_id":"S4TEST","telemetry":{"series":[1]*50000}},
        "html_note":{"asset_id":"S4TEST","note":"<script>alert(1)</script>"},
    }
    hh={"x-engineer-token":etok} if etok else {}
    for name,body in bad_payloads.items():
        try:
            r=c.post(M4+"/asset-health", headers=hh, json=body)
            tele.append({"endpoint":"/asset-health","case":name,"status":r.status_code,
                "is_500":r.status_code>=500,"body":H.scrub(r.text[:120])})
        except Exception as e:
            tele.append({"endpoint":"/asset-health","case":name,"error":repr(e)[:100]})
    # 50KB technician note on maintenance-report
    try:
        r=c.post(M4+"/maintenance-report", headers=hh,
                 json={"train_id":TEST_TRAIN,"note":"S4TEST "+"A"*50000,"severity":"low"})
        tele.append({"endpoint":"/maintenance-report","case":"50kb_note","status":r.status_code,
            "is_500":r.status_code>=500,"body":H.scrub(r.text[:120])})
    except Exception as e:
        tele.append({"endpoint":"/maintenance-report","case":"50kb_note","error":repr(e)[:100]})
    results["telemetry_validation"]=tele
    print("telemetry cases:",[(t.get('case'),t.get('status')) for t in tele])

    # ---- E. /hub/message signing (forged/unsigned/replay) with well-formed envelope ----
    def hub_env(tok):
        return {"message_id":f"S4TEST-{uuid.uuid4()}","sender_agent":"operations-agent",
                "receiver_agent":"maintenance-agent","intent":"issue_report",
                "payload":{"S4TEST":True},"auth_token":tok,
                "timestamp":datetime.datetime.now(datetime.timezone.utc).isoformat()}
    hub=[]
    for name,tok in [("no_token",""),("forged_wrong_secret",forged_hub_token())]:
        r=c.post(M4+"/hub/message", json=hub_env(tok))
        hub.append({"case":name,"status":r.status_code,"accepted":r.status_code<400,
            "body":H.scrub(r.text[:140])})
    results["hub_message_signing"]=hub
    print("hub_message:",[(h2['case'],h2['status']) for h2 in hub])

    # ---- F. read endpoints with no token ----
    reads=[]
    for path in ["/api/dashboard","/api/trains-under-maintenance",f"/api/train-status/{TEST_TRAIN}"]:
        r=c.get(M4+path)
        reads.append({"path":path,"status":r.status_code,"leaks_data":len(r.text)>50,
            "snippet":H.scrub(r.text[:140])})
    results["unauth_reads"]=reads
    print("unauth_reads:",[(r['path'],r['status']) for r in reads])

(EV/"results.json").write_text(json.dumps(results,indent=2),encoding="utf-8")
print("\nSaved",EV/"results.json")
