"""
S4-M2-01 — Independent incident-RAG retrieval evaluation (M2).
Shipped eval uses verbatim corpus notes as queries (P@1=1.000). Here: out-of-corpus
paraphrases/typos/keyword/cross-lingual queries + hard negatives. Relevance = same incident_type.
5 categories -> random baseline P@1=0.20.
"""
import sys, json, pathlib
M2DIR=pathlib.Path("E:/Y3 S2/Information Retrieval and Web Analytics - IT3041/RailSence-AI/M2-operations-agent")
sys.path.insert(0, str(M2DIR)); sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from rag.incident_retriever import retrieve_similar_incidents
import _harness as H
EV=H.EV/"S4-M2-01"; EV.mkdir(parents=True,exist_ok=True)

# (query, expected_type, category)
Q=[
 # paraphrases (out of corpus)
 ("the light on the gantry would not change and trains queued up","signal_fault","paraphrase"),
 ("points failed to switch so the route could not be set","signal_fault","paraphrase"),
 ("the engine broke down and the loco was withdrawn for repair","mechanical","paraphrase"),
 ("a coach developed a fault with its brakes en route","mechanical","paraphrase"),
 ("heavy rain and poor visibility forced trains to crawl","weather","paraphrase"),
 ("flooding over the rails slowed everything down","weather","paraphrase"),
 ("a fallen tree lay across the line blocking the service","track_obstruction","paraphrase"),
 ("debris on the track had to be cleared before trains passed","track_obstruction","paraphrase"),
 ("the relief driver turned up late and dispatch was held","staffing","paraphrase"),
 ("no guard available so the train waited at the platform","staffing","paraphrase"),
 # keyword
 ("signal relay aspect failure","signal_fault","keyword"),
 ("locomotive engine mechanical breakdown","mechanical","keyword"),
 ("rain flood weather delay","weather","keyword"),
 ("tree debris obstruction on track","track_obstruction","keyword"),
 ("driver guard crew shortage staffing","staffing","keyword"),
 # typos
 ("singal falut aspet did not chnage","signal_fault","typo"),
 ("mechnical brekdown of the enigne","mechanical","typo"),
 ("hevy raain and floodng on line","weather","typo"),
 # short
 ("red signal stuck","signal_fault","short"),
 ("brake failure","mechanical","short"),
 ("landslip on track","track_obstruction","short"),
 # cross-lingual / transliterated
 ("signal eka weda na (signal not working)","signal_fault","crosslingual"),
 ("wahe watura godai (heavy rain flooding)","weather","crosslingual"),
 ("enjima kadila (engine broken)","mechanical","crosslingual"),
]
NEG=["best hotel in kandy","how to make egg hoppers","stock market news today","football scores"]

p1=p3=p5=mrr=0; rows=[]; method=None
for q,exp,cat in Q:
    res=retrieve_similar_incidents(q, top_k=5)
    method=res.get("method")
    types=[i.get("incident_type") for i in res.get("incidents",[])]
    # rank of first same-type hit
    rank=next((idx+1 for idx,t in enumerate(types) if t==exp),0)
    p1+=1 if rank==1 else 0; p3+=1 if 0<rank<=3 else 0; p5+=1 if 0<rank<=5 else 0
    mrr+=(1/rank if rank else 0)
    rows.append({"q":q,"cat":cat,"expected":exp,"top_types":types[:3],"rank":rank})
n=len(Q)
from collections import defaultdict
cat=defaultdict(lambda:[0,0])
for r in rows:
    cat[r["cat"]][1]+=1
    if r["rank"]==1: cat[r["cat"]][0]+=1
neg_rows=[]
for q in NEG:
    res=retrieve_similar_incidents(q, top_k=3)
    inc=res.get("incidents",[])
    neg_rows.append({"q":q,"returned":len(inc),"top_score":(inc[0].get("score") or inc[0].get("similarity")) if inc else None,
                     "top_type":inc[0].get("incident_type") if inc else None})
out={"retrieval_method":method,
     "readme_claim":"P@1=1.000, P@3=1.000, P@5=0.999 (shipped eval queries = verbatim corpus notes)",
     "independent_out_of_corpus":{"n":n,"P@1":round(p1/n,4),"P@3":round(p3/n,4),
        "P@5":round(p5/n,4),"MRR":round(mrr/n,4),"random_baseline_P@1":0.20},
     "per_category":{c:{"P@1":round(v[0]/v[1],3),"n":v[1]} for c,v in cat.items()},
     "hard_negatives":{"note":"5 categories always exist; retriever always returns SOME same-corpus incident (no 'no-match' option). Shows top scores.","rows":neg_rows},
     "rows":rows}
(EV/"results.json").write_text(json.dumps(out,indent=2),encoding="utf-8")
print("method:",method)
print("INDEPENDENT:",out["independent_out_of_corpus"])
print("per_category:",out["per_category"])
print("neg top scores:",[r["top_score"] for r in neg_rows])
