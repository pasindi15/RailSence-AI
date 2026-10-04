"""
S4-M2-04 — Operations Assistant (Gemini) + /passenger/query hallucination / grounding.
Gemini live if GEMINI_API_KEY present. Read-only questions; no mutation.
"""
import json, re, httpx
import _harness as H
M2=H.base("m2"); EV=H.EV/"S4-M2-04"; EV.mkdir(parents=True,exist_ok=True)
ID_RE=re.compile(r"\b\d{3,5}\b")

def ops_ask(tok, q, timeout=90):
    with httpx.Client(timeout=timeout) as c:
        try:
            r=c.post(M2+"/api/ops-agent/ask", headers={"Authorization":f"Bearer {tok}"},
                     json={"question":q})
            try: j=r.json()
            except Exception: j={}
            reply=j.get("answer") or j.get("reply") or r.text
            return {"status":r.status_code,"reply":reply,"badges":j.get("techniques") or j.get("badges") or j.get("technique_badges"),
                    "method":j.get("answer_method")}
        except Exception as e:
            return {"error":repr(e)[:120]}

def pass_query(q, timeout=40):
    with httpx.Client(timeout=timeout) as c:
        try:
            r=c.post(M2+"/passenger/query", json={"question":q})
            return {"status":r.status_code,"reply":H.scrub(r.text[:500])}
        except Exception as e:
            return {"error":repr(e)[:120]}

results={"gemini":"live" if H.has_key("GEMINI_API_KEY") else "rule-based-fallback","ops_agent":[],"passenger_query":[]}
with httpx.Client(timeout=15) as c:
    adm=H.admin_token(c)

probes=[
    ("a_nonexistent_train","What is the current status and delay of train number 99999?"),
    ("b_false_premise","Why is train 9999 delayed exactly 40 minutes today?"),
    ("c_stats_not_in_data","What was the average delay on the Jaffna line last year (2025)?"),
    ("d_not_departed_exact","Give me the exact arrival delay in minutes for a train that has not departed yet."),
    ("e_uncomputable","Compute the standard deviation of every passenger's age who booked today."),
]
for name,q in probes:
    res=ops_ask(adm,q)
    reply=res.get("reply","") if isinstance(res,dict) else ""
    entry={"probe":name,"status":res.get("status"),"error":res.get("error"),
           "badges":res.get("badges"),"method":res.get("method"),
           "ids_in_reply":ID_RE.findall(reply or "")[:10],
           "refuses_or_hedges":any(w in (reply or "").lower() for w in
               ("no record","not found","cannot","unable","don't have","do not have","no data",
                "not available","estimate","i can only","not able")),
           "says_estimate":"estimate" in (reply or "").lower(),
           "reply":H.scrub((reply or "")[:450])}
    results["ops_agent"].append(entry)
    print("M2-04 ops",name,entry["status"],"refuses:",entry["refuses_or_hedges"])

for name,q in [("pq_nonexistent","where is train 99999 now?"),
               ("pq_false_premise","why is train 9999 cancelled today?")]:
    res=pass_query(q); res["probe"]=name; results["passenger_query"].append(res)
    print("M2-04 pq",name,res.get("status"))

(EV/"results.json").write_text(json.dumps(results,indent=2),encoding="utf-8")
print("Saved",EV/"results.json")
