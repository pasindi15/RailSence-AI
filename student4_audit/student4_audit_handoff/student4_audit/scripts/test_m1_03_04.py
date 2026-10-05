"""
S4-M1-03 (session isolation/authz) + S4-M1-04 (chat API security).
Two simulated passengers A & B with S4TEST_ content. Bounded burst <=20.
"""
import json, time, uuid
import httpx
import _harness as H

M1=H.base("m1")
EV3=H.EV/"S4-M1-03"; EV3.mkdir(parents=True,exist_ok=True)
EV4=H.EV/"S4-M1-04"; EV4.mkdir(parents=True,exist_ok=True)

def chat(c, msg, sid=None):
    body={"message":msg}
    if sid: body["session_id"]=sid
    return c.post(M1+"/chat", json=body)

r3={"probes":[]}; r4={"probes":[]}
with httpx.Client(timeout=40.0) as c:
    # --- create A and B sessions ---
    ra=chat(c,"S4TEST_A what are the train ticket cancellation charges?")
    A=ra.json().get("session_id") if ra.status_code==200 else None
    rb=chat(c,"S4TEST_B hello", None)
    B=rb.json().get("session_id") if rb.status_code==200 else None
    r3["A_session_created"]=bool(A); r3["B_session_created"]=bool(B)
    r3["session_id_A_sample"]=A
    print("A:",A,"B:",B)

    def p3(name,expected,resp,extra=None):
        e={"probe":name,"expected":expected,"status":getattr(resp,'status_code',None),
           "body":H.scrub(getattr(resp,'text','')[:180])}
        if extra: e.update(extra)
        r3["probes"].append(e); print("M1-03",name,e["status"]); return e

    # (a) B (no token) reads A's history by A's session id
    if A:
        h=c.get(M1+f"/chat/{A}/history")
        p3("a_read_other_history","200 returns A content (no authz) OR 401",h,
           {"contains_S4TEST_A": "S4TEST_A" in h.text})
    # (b) guessed/sequential/empty/traversal ids
    for label,sid in [("all_zeros_uuid","00000000-0000-0000-0000-000000000000"),
                       ("non_uuid","abc123"),("traversal","..%2f..%2fetc"),("sql","1' OR '1'='1")]:
        h=c.get(M1+f"/chat/{sid}/history")
        p3(f"b_{label}","400 invalid / 200 empty",h)
    # (c) history with no token already covered (no auth exists)
    # (d) via gateway /svc/m1 and /api/chat
    try:
        g=c.get(H.base("user")+f"/svc/m1/chat/{A}/history") if A else None
        if g is not None: p3("d_gateway_svc_m1_history","same as direct",g,{"contains_S4TEST_A":"S4TEST_A" in g.text})
    except Exception as e:
        r3["probes"].append({"probe":"d_gateway","error":repr(e)[:100]})
    (EV3/"results.json").write_text(json.dumps(r3,indent=2),encoding="utf-8")

    # ---------- M1-04 API security ----------
    def p4(name,expected,resp,extra=None):
        e={"probe":name,"expected":expected,"status":getattr(resp,'status_code',None),
           "resp_headers":{k:v for k,v in getattr(resp,'headers',{}).items()
                           if k.lower() in ('access-control-allow-origin','server','x-frame-options',
                                            'x-content-type-options','content-security-policy')},
           "body":H.scrub(getattr(resp,'text','')[:200])}
        if extra: e.update(extra)
        r4["probes"].append(e); print("M1-04",name,e["status"]); return e

    # (a) 100KB+ body
    p4("a_large_body_120kb","handled (413/422/200)", chat(c,"S4TEST "+"x"*120000))
    # (b) control chars / null bytes
    p4("b_control_null","no 500", chat(c,"S4TEST\x00\x01\x02 test\r\n"))
    # (c) html/script
    p4("c_html_script","sanitised/echoed-safely", chat(c,"S4TEST <script>alert(1)</script> fare to Kandy?"))
    # (d) malformed json
    with httpx.Client(timeout=10) as c2:
        rr=c2.post(M1+"/chat", content=b'{"message": ', headers={"content-type":"application/json"})
        p4("d_malformed_json","400/422", rr)
    # (d2) wrong types
    p4("d2_wrong_type","422", httpx.post(M1+"/chat", json={"message":12345}))
    # (e) missing required field
    p4("e_missing_message","422", httpx.post(M1+"/chat", json={"session_id":str(uuid.uuid4())}))
    # (g) error-inducing: very odd input to observe error body
    p4("g_error_body","no stack/keys", chat(c,"S4TEST "+"\ud800"*3 if False else "S4TEST {{7*7}} ${jndi:ldap://x}"))
    # (h) CORS with evil origin (preflight)
    pre=httpx.options(M1+"/chat", headers={"Origin":"https://evil.example",
        "Access-Control-Request-Method":"POST"})
    p4("h_cors_preflight_evil","ACAO not evil-reflected-with-creds", pre,
       {"acao":pre.headers.get("access-control-allow-origin"),
        "acac":pre.headers.get("access-control-allow-credentials")})
    # (f) bounded burst (<=20) for rate limiting - tiny messages
    codes=[]; t0=time.time()
    for i in range(20):
        rr=chat(c,f"S4TEST burst {i}")
        codes.append(rr.status_code)
        if rr.status_code==429: break
    r4["burst"]={"n":len(codes),"codes":codes,"got_429":429 in codes,"elapsed_s":round(time.time()-t0,1)}
    print("M1-04 burst:",r4["burst"])
    (EV4/"results.json").write_text(json.dumps(r4,indent=2),encoding="utf-8")

print("Saved M1-03 and M1-04 results")
