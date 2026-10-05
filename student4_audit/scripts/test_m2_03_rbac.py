"""
S4-M2-03 — M2 Authentication & Authorization: RBAC matrix + token attacks.
Local only. Secrets never printed. Token forgeries simulate an attacker WITHOUT
the secret (tamper-without-resign, alg:none, wrong-key, expired, query-string).
"""
import json, pathlib, datetime, base64, time
import httpx, jwt
import _harness as H

TID="S4-M2-03"
EV=H.EV/TID; EV.mkdir(parents=True, exist_ok=True)

# Representative M2 endpoints (method, path, intended_min_role)
# intended: admin=admin only, auth=any officer, none=public
ENDPOINTS = [
    ("GET","/admin/api/officers","admin"),
    ("POST","/admin/api/model/retrain","admin"),
    ("GET","/admin/api/audit/events","admin"),
    ("GET","/admin/api/health/status","admin"),
    ("GET","/admin/api/me","auth"),
    ("GET","/api/dashboard","none"),
    ("GET","/api/trains","none"),
    ("POST","/incident-report","none"),
]

def decode_no_verify(tok):
    return jwt.decode(tok, options={"verify_signature":False})

def tamper_role_no_resign(tok):
    """Flip role->admin in payload but KEEP original signature (attacker has no secret)."""
    h,p,s = tok.split(".")
    payload = json.loads(base64.urlsafe_b64decode(p+"=="*(-len(p)%4)))
    payload["role"]="admin"; payload["permissions"]=["*"]
    np = base64.urlsafe_b64encode(json.dumps(payload).encode()).rstrip(b"=").decode()
    return f"{h}.{np}.{s}"

def alg_none_admin():
    h=base64.urlsafe_b64encode(json.dumps({"alg":"none","typ":"JWT"}).encode()).rstrip(b"=").decode()
    p=base64.urlsafe_b64encode(json.dumps({"sub":"forged","role":"admin","permissions":["*"],
        "email":"forged@x","exp":int(time.time())+9999}).encode()).rstrip(b"=").decode()
    return f"{h}.{p}."

def wrong_key_admin():
    return jwt.encode({"sub":"forged","role":"admin","exp":int(time.time())+9999},
                      "not-the-real-secret-000", algorithm="HS256")

def expired_admin_realkey():
    return jwt.encode({"sub":"forged","role":"admin","exp":int(time.time())-10},
                      H.jwt_secret(), algorithm="HS256")

results={"tested_at":datetime.datetime.now().astimezone().isoformat(),"matrix":[],"token_attacks":[]}

with httpx.Client(timeout=15.0) as c:
    adm=H.admin_token(c)
    op,oid=H.ensure_operator(c,adm)
    identities={"none":None,"passenger":None,"operator":op,"admin":adm}

    # ---- RBAC matrix (direct port 8005) ----
    for method,path,intended in ENDPOINTS:
        row={"method":method,"path":path,"intended":intended,"by_identity":{}}
        for idn,tok in identities.items():
            headers={"Authorization":f"Bearer {tok}"} if tok else {}
            body={} if method=="POST" else None
            try:
                r=c.request(method, H.base("m2")+path, headers=headers, json=body)
                allowed = r.status_code not in (401,403)
                row["by_identity"][idn]={"status":r.status_code,"allowed":allowed}
            except Exception as e:
                row["by_identity"][idn]={"error":repr(e)[:120]}
        results["matrix"].append(row)
        print(method,path,{k:v.get("status") for k,v in row["by_identity"].items()})

    # ---- Token attacks against an admin-only endpoint ----
    target=H.base("m2")+"/admin/api/officers"
    attacks={
        "a_tamper_role_no_resign": tamper_role_no_resign(op) if op else None,
        "b_alg_none": alg_none_admin(),
        "c_wrong_key": wrong_key_admin(),
        "d_expired_realkey": expired_admin_realkey(),
    }
    for name,tok in attacks.items():
        if tok is None: continue
        r=c.get(target, headers={"Authorization":f"Bearer {tok}"})
        rec={"attack":name,"status":r.status_code,"rejected":r.status_code in (401,403),
             "detail":H.scrub(r.text[:160])}
        results["token_attacks"].append(rec); print("ATTACK",rec)
    # e: valid admin token in query string
    r=c.get(target+f"?token={adm}")
    results["token_attacks"].append({"attack":"e_token_in_query","status":r.status_code,
        "rejected":r.status_code in (401,403)})
    # f: missing token
    r=c.get(target)
    results["token_attacks"].append({"attack":"f_missing_token","status":r.status_code,
        "rejected":r.status_code in (401,403)})
    # g: same admin-only endpoint via gateway admin port 3001 with no token (bypass check)
    try:
        r=c.get(H.base("admin")+"/admin/api/officers")
        results["token_attacks"].append({"attack":"g_gateway3001_no_token","status":r.status_code,
            "rejected":r.status_code in (401,403,404)})
    except Exception as e:
        results["token_attacks"].append({"attack":"g_gateway3001_no_token","error":repr(e)[:120]})

    H.deactivate_operator(c,adm,oid)  # cleanup

(EV/"results.json").write_text(json.dumps(results,indent=2),encoding="utf-8")
print("\nSaved",EV/"results.json")
