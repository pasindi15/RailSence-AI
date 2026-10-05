"""
S4-M3-02 — Auth bypass of 'internal' services & network exposure.
Call internal endpoints directly (skip Hub), no token / passenger token / forged token.
Read/probe only. No mutation (fraud-score is a scoring read; we send S4TEST data).
"""
import json, pathlib, datetime, time, uuid
import httpx, jwt
import _harness as H

TID="S4-M3-02"; EV=H.EV/TID; EV.mkdir(parents=True, exist_ok=True)

def forged(sub="passenger-agent"):
    now=int(time.time())
    return jwt.encode({"sub":sub,"role":"service","exp":now+300,"iat":now},
                      "wrong-secret-xyz", algorithm="HS256")  # attacker has no real secret

# (svc, method, path, body) internal endpoints that README says are Hub-mediated
TARGETS=[
    ("booking","POST","/internal/messages",{"S4TEST":True}),
    ("booking","POST","/internal/seat-holds",{"S4TEST":True}),
    ("security","POST","/internal/fraud-score",{"booking_reference":"S4TEST","features":{}}),
    ("security","POST","/internal/messages",{"S4TEST":True}),
    ("m2","POST","/internal/messages",{"S4TEST":True}),
    ("m2","POST","/hub/message",{"S4TEST":True}),
    ("m4","POST","/hub/message",{"S4TEST":True}),
    ("m4","POST","/internal/messages",{"S4TEST":True}),
]
IDENTS={"none":None,"passenger_forged":forged(),"forged_service":forged("operations-agent")}

results={"tested_at":datetime.datetime.now().astimezone().isoformat(),"internal_direct":[],"info_disclosure":[]}
with httpx.Client(timeout=12.0) as c:
    for svc,method,path,body in TARGETS:
        row={"svc":svc,"path":path,"by_identity":{}}
        for idn,tok in IDENTS.items():
            h={"Authorization":f"Bearer {tok}"} if tok else {}
            try:
                r=c.request(method,H.base(svc)+path,headers=h,json=body)
                # 'processed' = not an auth rejection AND not 404/422-schema
                row["by_identity"][idn]={"status":r.status_code,
                    "auth_rejected":r.status_code in (401,403),
                    "body":H.scrub(r.text[:140])}
            except Exception as e:
                row["by_identity"][idn]={"error":repr(e)[:120]}
        results["internal_direct"].append(row)
        print(svc,path,{k:v.get('status') for k,v in row['by_identity'].items()})

    # info disclosure endpoints (no auth)
    for svc,path in [("hub","/api/hub/dashboard"),("hub","/api/hub/timeline"),
                     ("hub","/health"),("hub","/ready"),("booking","/health"),
                     ("security","/health"),("m4","/health"),("m2","/health")]:
        try:
            r=c.get(H.base(svc)+path)
            results["info_disclosure"].append({"svc":svc,"path":path,"status":r.status_code,
                "leaks_url":("127.0.0.1" in r.text or "http://" in r.text),
                "snippet":H.scrub(r.text[:200])})
        except Exception as e:
            results["info_disclosure"].append({"svc":svc,"path":path,"error":repr(e)[:100]})

    # gateway 3000 (public) pass-through to admin/maintenance endpoints?
    gw=[]
    for path in ["/svc/m2/admin/api/officers","/svc/m4/api/flag-train","/svc/m2/api/dashboard",
                 "/svc/m4/api/trains-under-maintenance","/api/admin/system-health"]:
        try:
            r=c.get(H.base("user")+path)
            gw.append({"path":path,"status":r.status_code,"body":H.scrub(r.text[:120])})
        except Exception as e:
            gw.append({"path":path,"error":repr(e)[:100]})
    results["gateway3000_passthrough"]=gw
    for g in gw: print("GW3000",g.get('path'),g.get('status'))

(EV/"results.json").write_text(json.dumps(results,indent=2),encoding="utf-8")
print("\nSaved",EV/"results.json")
