import os
"""
S4-M2-03 sub-probe: documented default-credential login (<=5 attempts).
Tries the default admin creds documented in M2 seed scripts against the M2
admin login endpoint. Prints outcome only; NEVER prints the token in full.
"""
import httpx, json, pathlib, datetime

OUT = pathlib.Path(__file__).resolve().parents[1] / "evidence" / "S4-M2-03"
OUT.mkdir(parents=True, exist_ok=True)

# Documented defaults from repo seed scripts (admin_db.seed_initial_admin_if_needed,
# M2-admin-dashboard/backend/admin_auth.py). <=5 candidates.
CANDIDATES = [
    ("admin@railsense.lk", os.getenv("S4_ADMIN_PW", "")),
    ("admin@railsense.lk", "operations2026"),
    ("admin", "operations2026"),
    ("admin@railsense.lk", "admin"),
    ("admin@railsense.lk", "Admin@123"),
]

URL = "http://127.0.0.1:8005/admin/api/login"
log = []
token = None
with httpx.Client(timeout=10.0) as c:
    for email, pw in CANDIDATES:
        try:
            r = c.post(URL, json={"email": email, "password": pw})
            body = r.text
            ok = r.status_code == 200
            entry = {"email": email, "pw_masked": pw[:2] + "****",
                     "status": r.status_code, "ok": ok,
                     "body_snippet": (body[:160] if not ok else "<success, body withheld>")}
            log.append(entry)
            print(entry)
            if ok:
                try:
                    token = r.json().get("access_token") or r.json().get("token")
                except Exception:
                    token = None
                break
        except Exception as e:
            entry = {"email": email, "error": repr(e)}
            log.append(entry)
            print(entry)

result = {"tested_at": datetime.datetime.now().astimezone().isoformat(),
          "endpoint": URL, "attempts": log,
          "login_succeeded": token is not None,
          "token_prefix": (token[:12] + "…") if token else None}
(OUT / "default_login_attempts.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
print("\nlogin_succeeded:", result["login_succeeded"], "token_prefix:", result["token_prefix"])
