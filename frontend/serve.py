"""
RailSense AI — Unified Frontend Proxy Server
Serves the dashboard HTML and proxies API calls to each agent so the
browser never hits CORS issues.

Agents:
  operations  → http://localhost:8002
  passenger   → http://localhost:8001
  security    → http://localhost:8003
  maintenance → http://localhost:8004
  hub         → http://localhost:8000

Run: python serve.py
Open: http://localhost:3000
"""

import os
from pathlib import Path

import httpx
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="RailSense Unified Frontend")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

AGENT_URLS = {
    "operations": os.getenv("OPERATIONS_URL", "http://localhost:8002"),
    "passenger":  os.getenv("PASSENGER_URL",  "http://localhost:8001"),
    "security":   os.getenv("SECURITY_URL",   "http://localhost:8003"),
    "maintenance":os.getenv("MAINTENANCE_URL","http://localhost:8004"),
    "hub":        os.getenv("HUB_URL",         "http://localhost:8000"),
}

HTML_FILE = Path(__file__).parent / "index.html"


@app.get("/", include_in_schema=False)
def root():
    return FileResponse(HTML_FILE)


@app.api_route("/proxy/{agent}/{path:path}", methods=["GET", "POST", "PUT", "DELETE"])
async def proxy(agent: str, path: str, request: Request):
    base = AGENT_URLS.get(agent)
    if not base:
        return JSONResponse({"error": f"Unknown agent: {agent}"}, status_code=404)

    url = f"{base.rstrip('/')}/{path}"
    body = await request.body()
    headers = {
        k: v for k, v in request.headers.items()
        if k.lower() not in ("host", "content-length")
    }

    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.request(
                method=request.method,
                url=url,
                content=body,
                headers=headers,
                params=dict(request.query_params),
            )
        try:
            return JSONResponse(content=resp.json(), status_code=resp.status_code)
        except Exception:
            return JSONResponse(
                content={"raw": resp.text}, status_code=resp.status_code
            )
    except httpx.ConnectError:
        return JSONResponse({"online": False, "error": "agent offline"}, status_code=503)
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=502)


@app.get("/status")
async def all_status():
    results = {}
    async with httpx.AsyncClient(timeout=3.0) as client:
        for name, base in AGENT_URLS.items():
            try:
                r = await client.get(f"{base}/health")
                results[name] = {"online": True, **r.json()}
            except Exception:
                results[name] = {"online": False}
    return results


@app.get("/{filepath:path}", include_in_schema=False)
async def serve_static(filepath: str):
    """Serve any static asset from the frontend directory (images, fonts, etc.)."""
    base = Path(__file__).parent.resolve()
    target = (base / filepath).resolve()
    if str(target).startswith(str(base)) and target.is_file():
        return FileResponse(target)
    raise HTTPException(status_code=404, detail="Not found")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("serve:app", host="0.0.0.0", port=3000, reload=True)
