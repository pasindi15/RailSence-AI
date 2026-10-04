"""
Shared S4-audit harness. Local-only. Secrets loaded from .env are NEVER printed.
Provides: role tokens (admin via login, operator via S4TEST officer),
JWT signing for Hub AgentMessages (gray-box), and evidence helpers.
"""
from __future__ import annotations
import os, json, pathlib, datetime, re, uuid
import httpx

ROOT = pathlib.Path(__file__).resolve().parents[2]
AUDIT = pathlib.Path(__file__).resolve().parents[1]
EV = AUDIT / "evidence"

PORTS = {"user":3000,"admin":3001,"m1":8001,"hub":8002,"booking":8003,
         "security":8004,"m2":8005,"m4":8006}
def base(svc): return f"http://127.0.0.1:{PORTS[svc]}"

# Documented default credentials are NOT stored here; export them before running.
DEFAULT_ADMIN = (os.getenv("S4_ADMIN_EMAIL", "admin@railsense.lk"), os.getenv("S4_ADMIN_PW", ""))
M4_ENG_PW = os.getenv("S4_M4_ENG_PW", "")
S4_OFFICER_EMAIL = "s4test_operator@railsense.lk"
S4_OFFICER_PW = "S4TEST_operator_pw_123"

# ---- secret loading (never printed) ----
def _load_env():
    env = {}
    for p in [ROOT/".env", ROOT/"M4-maintenance-agent"/".env"]:
        if p.exists():
            for line in p.read_text(encoding="utf-8", errors="ignore").splitlines():
                line=line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k,v=line.split("=",1); env.setdefault(k.strip(), v.strip().strip('"').strip("'"))
    return env
_ENV = _load_env()
def jwt_secret(): return _ENV.get("JWT_SECRET_KEY","")
def jwt_alg(): return _ENV.get("JWT_ALGORITHM","HS256")
def has_key(name): return bool(_ENV.get(name))

def mask_token(t): return (t[:12]+"…") if t else None

# ---- gray-box token minting (no DB writes; sub not in DB so role is trusted from token) ----
import time as _t, jwt as _jwt
_PERMS={"admin":["m2.control_room.view","m2.control_room.action","m2.prediction.view",
        "m2.prediction.run","m2.admin_console.view","m2.officers.view","m2.officers.create",
        "m2.officers.edit","m2.officers.deactivate","m2.officers.role_change",
        "m2.officers.password_reset","m2.system.config","m2.audit.view","m2.model.manage",
        "m2.data.manage","m2.incidents.review","m2.assistant.use"],
       "operations_engineer":["m2.control_room.view","m2.control_room.action",
        "m2.prediction.view","m2.prediction.run","m2.assistant.use"]}
def mint_token(role="operations_engineer", ttl=3600, sub=None):
    """Mint a validly-signed officer token for RBAC probing. Uses a random sub NOT in
    the DB, so get_current_officer keeps the token's role (no accidental real-officer touch)."""
    now=int(_t.time())
    payload={"sub":sub or f"s4audit-{uuid.uuid4()}","email":"s4audit@local",
             "name":"S4 Audit","role":role,"permissions":_PERMS.get(role,[]),
             "iat":now,"exp":now+ttl}
    return _jwt.encode(payload, jwt_secret(), algorithm=jwt_alg())

# ---- role tokens ----
def admin_token(client):
    r = client.post(base("m2")+"/admin/api/login",
                    json={"email":DEFAULT_ADMIN[0],"password":DEFAULT_ADMIN[1]})
    r.raise_for_status()
    d=r.json()
    return d.get("access_token") or d.get("token")

def ensure_operator(client, adm):
    """Create (idempotent) an S4TEST operations_engineer officer and log in. Returns (token, officer_id)."""
    h={"Authorization":f"Bearer {adm}"}
    # create (ignore 409/duplicate)
    cr = client.post(base("m2")+"/admin/api/officers", headers=h, json={
        "full_name":"S4TEST Operator","email":S4_OFFICER_EMAIL,
        "password":S4_OFFICER_PW,"role":"operations_engineer","status":"active"})
    oid=None
    if cr.status_code in (200,201):
        oid=(cr.json() or {}).get("id")
    # if exists, reactivate via officer list
    if oid is None:
        lst=client.get(base("m2")+"/admin/api/officers", headers=h)
        if lst.status_code==200:
            for o in (lst.json() if isinstance(lst.json(),list) else lst.json().get("officers",[])):
                if o.get("email")==S4_OFFICER_EMAIL:
                    oid=o.get("id")
                    client.post(base("m2")+f"/admin/api/officers/{oid}/status",
                                headers=h, json={"status":"active"})
                    client.post(base("m2")+f"/admin/api/officers/{oid}/reset-password",
                                headers=h, json={"new_password":S4_OFFICER_PW})
    # login
    lr=client.post(base("m2")+"/admin/api/login",
                   json={"email":S4_OFFICER_EMAIL,"password":S4_OFFICER_PW})
    tok=None
    if lr.status_code==200:
        d=lr.json(); tok=d.get("access_token") or d.get("token")
    return tok, oid

def deactivate_operator(client, adm, oid):
    if not oid: return None
    h={"Authorization":f"Bearer {adm}"}
    r=client.post(base("m2")+f"/admin/api/officers/{oid}/status", headers=h,
                  json={"status":"inactive"})
    return r.status_code

# ---- evidence helpers ----
SECRET_PATTERNS = [re.compile(p) for p in [
    r"eyJ[A-Za-z0-9_\-]{6,}", r"sk-[A-Za-z0-9]{6,}", r"gsk_[A-Za-z0-9]{6,}",
    r"AIza[A-Za-z0-9_\-]{6,}"]]
def scrub(text):
    if not isinstance(text,str): text=str(text)
    for pat in SECRET_PATTERNS:
        text=pat.sub(lambda m: m.group(0)[:8]+"…[MASKED]", text)
    return text

def save_transcript(test_id, name, method, url, req_headers, req_body, resp):
    d=EV/test_id; d.mkdir(parents=True, exist_ok=True)
    hdrs={k:("Bearer …[MASKED]" if k.lower()=="authorization" else v) for k,v in (req_headers or {}).items()}
    out={
        "timestamp":datetime.datetime.now().astimezone().isoformat(),
        "method":method,"url":url,"request_headers":hdrs,
        "request_body":scrub(req_body) if req_body is not None else None,
        "status": getattr(resp,"status_code",None),
        "response_headers":dict(getattr(resp,"headers",{})),
        "response_body": scrub(getattr(resp,"text","")[:4000]),
    }
    (d/f"{name}.json").write_text(json.dumps(out,indent=2,default=str),encoding="utf-8")
    return out

if __name__=="__main__":
    with httpx.Client(timeout=15.0) as c:
        adm=admin_token(c)
        print("admin token:", mask_token(adm))
        op,oid=ensure_operator(c,adm)
        print("operator token:", mask_token(op), "officer_id:", oid)
        print("JWT_SECRET present:", bool(jwt_secret()), "alg:", jwt_alg())
        print("keys present:", {k:has_key(k) for k in
              ["GEMINI_API_KEY","OPENROUTER_API_KEY","GROQ_API_KEY","UPSTASH_REDIS_URL","NIC_HMAC_SECRET"]})
