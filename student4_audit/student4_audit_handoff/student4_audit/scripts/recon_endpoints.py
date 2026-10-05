"""
S4 audit — Phase 0 recon.
Hits /health, /docs, /openapi.json on every RailSense service (localhost only),
saves raw responses + parsed endpoint lists under evidence/env/.
Read-only GETs. No auth. No mutation.
"""
import json, pathlib, datetime, httpx

BASE = pathlib.Path(__file__).resolve().parents[1]
OUT = BASE / "evidence" / "env"
OUT.mkdir(parents=True, exist_ok=True)

SERVICES = {
    "gateway_user": 3000,
    "gateway_admin": 3001,
    "m1": 8001,
    "hub": 8002,
    "booking": 8003,
    "security": 8004,
    "m2": 8005,
    "m4": 8006,
}

now = datetime.datetime.now().astimezone().isoformat()
summary = {"captured_at": now, "services": {}}

with httpx.Client(timeout=8.0) as c:
    for name, port in SERVICES.items():
        base = f"http://127.0.0.1:{port}"
        rec = {"port": port, "base": base}
        # health
        for probe in ("/health", "/ready"):
            try:
                r = c.get(base + probe)
                rec[probe] = {"status": r.status_code, "body": r.text[:600]}
            except Exception as e:
                rec[probe] = {"error": repr(e)}
        # docs exposure
        try:
            r = c.get(base + "/docs")
            rec["/docs"] = {"status": r.status_code, "len": len(r.text),
                            "is_swagger": "swagger-ui" in r.text.lower()}
        except Exception as e:
            rec["/docs"] = {"error": repr(e)}
        # openapi
        endpoints = []
        try:
            r = c.get(base + "/openapi.json")
            rec["/openapi.json"] = {"status": r.status_code}
            if r.status_code == 200:
                spec = r.json()
                (OUT / f"openapi_{name}.json").write_text(
                    json.dumps(spec, indent=2), encoding="utf-8")
                for path, methods in spec.get("paths", {}).items():
                    for m, meta in methods.items():
                        if m.lower() in ("get","post","put","delete","patch"):
                            endpoints.append({
                                "method": m.upper(), "path": path,
                                "summary": meta.get("summary", ""),
                            })
                rec["endpoint_count"] = len(endpoints)
        except Exception as e:
            rec["/openapi.json"] = {"error": repr(e)}
        # security headers on health
        try:
            r = c.get(base + "/health")
            hdrs = {k: v for k, v in r.headers.items()
                    if k.lower() in ("server","x-content-type-options","x-frame-options",
                                     "content-security-policy","strict-transport-security",
                                     "access-control-allow-origin")}
            rec["security_headers"] = hdrs
        except Exception:
            pass
        rec["endpoints"] = endpoints
        summary["services"][name] = rec
        print(f"[{name}:{port}] health={rec.get('/health',{}).get('status')} "
              f"docs={rec.get('/docs',{}).get('status')} "
              f"openapi={rec.get('/openapi.json',{}).get('status')} "
              f"endpoints={rec.get('endpoint_count','-')}")

(OUT / "recon_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
print("\nSaved:", OUT / "recon_summary.json")
