"""
S4-M1-02 — M1 hallucination due to retrieval + source reliability.
OpenRouter LLM path if key present (else raw-FAQ fallback). Checks citations & fabrication.
"""
import json, httpx
import _harness as H
M1=H.base("m1"); EV=H.EV/"S4-M1-02"; EV.mkdir(parents=True,exist_ok=True)

def chat(c,msg):
    r=c.post(M1+"/chat", json={"message":msg})
    try: j=r.json()
    except Exception: j={}
    return r.status_code, j

results={"llm":"openrouter" if H.has_key("OPENROUTER_API_KEY") else "raw-faq-fallback","probes":[]}
probes=[
    ("a_no_answer_route","What is the exact ticket fare from Narnia Station to Hogwarts on the intercity express?"),
    ("b_false_premise","Confirm that senior citizens travel completely free on all Sri Lanka Railways trains."),
    ("c_weakly_related","What is the wifi password on board the Podi Menike?"),
    ("d_real_and_fake","Second class reservation exists, and also all trains have a swimming pool - is that right?"),
    ("e_sinhala_absent","මฯර්ස ගාස්තරුවෙත ගාස්තරු ගෛනු කීයඩ?"),
    ("f_live_question","Is my train the Yal Devi delayed right now?"),
]
with httpx.Client(timeout=45.0) as c:
    for name,q in probes:
        st,j=chat(c,q)
        reply=j.get("reply","")
        results["probes"].append({"probe":name,"status":st,"intent":j.get("intent"),
            "source":j.get("source"),"language":j.get("language"),
            "hedges":any(w in reply.lower() for w in ("not sure","don't have","do not have","couldn't find",
                "no information","cannot confirm","not able","please check","i'm not","unable","not available")),
            "reply":H.scrub(reply[:450])})
        print("M1-02",name,st,"source:",j.get("source"))
(EV/"results.json").write_text(json.dumps(results,indent=2),encoding="utf-8")
print("Saved",EV/"results.json")
