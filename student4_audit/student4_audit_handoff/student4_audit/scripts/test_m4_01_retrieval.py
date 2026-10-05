"""
S4-M4-01 — Independent manual-RAG retrieval evaluation (M4).
Contrast with shipped eval (which prepends asset_type+fault_type and uses keyword-overlap
relevance, inflating scores to 1.000). Here: QUERY TEXT ONLY, correctness = expected section
in top-k; symptom/paraphrase/typo/cross-lingual queries + hard negatives for false-positive rate.
"""
import sys, json, pathlib
AGENT=pathlib.Path("E:/Y3 S2/Information Retrieval and Web Analytics - IT3041/RailSence-AI/M4-maintenance-agent")
sys.path.insert(0, str(AGENT))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from rag.manual_retriever import retrieve_manual_sections
import _harness as H
EV=H.EV/"S4-M4-01"; EV.mkdir(parents=True,exist_ok=True)

# (query, expected_section_id, category)
QUERIES=[
    # symptom-style paraphrases (no fault label)
    ("engine is dripping oil onto the floor under the loco","diesel_engine_manual_3","symptom"),
    ("locomotive keeps overheating and temperature warning comes on","diesel_engine_manual_4","symptom"),
    ("black smoke and poor fuel burn from the diesel engine","diesel_engine_manual_5","symptom"),
    ("whining noise from turbo and loss of boost pressure","diesel_engine_manual_9","symptom"),
    ("brake pads look very thin, when do I replace them","brake_system_manual_3","symptom"),
    ("air hissing from brake cylinder, seal seems gone","brake_system_manual_4","symptom"),
    ("flat spot on wheel causing thumping at low speed","bogie_inspection_guide_2","symptom"),
    ("growling sound from axle bearing needs grease","bogie_inspection_guide_3","symptom"),
    ("excess vibration from the bogie at speed","bogie_inspection_guide_5","symptom"),
    ("pantograph not making good contact with the wire","electric_locomotive_manual_2","symptom"),
    ("barrier arm at the level crossing does not lower","level_crossing_manual_4","symptom"),
    ("platform screen door will not open for passengers","platform_gate_manual_2","symptom"),
    # keyword queries
    ("oil system maintenance diesel","diesel_engine_manual_3","keyword"),
    ("cooling system coolant radiator","diesel_engine_manual_4","keyword"),
    ("brake pad inspection thickness","brake_system_manual_3","keyword"),
    ("wheel inspection profile","bogie_inspection_guide_2","keyword"),
    ("axle bearing maintenance","bogie_inspection_guide_3","keyword"),
    ("pantograph system","electric_locomotive_manual_2","keyword"),
    # typos
    ("brak pad insepction thicknes","brake_system_manual_3","typo"),
    ("diesle engine oill leek","diesel_engine_manual_3","typo"),
    ("panttograph contatc wire","electric_locomotive_manual_2","typo"),
    # cross-lingual (transliterated / non-English) — expected to stress English TF-IDF
    ("brake eka weda karanne na (brakes not working)","brake_system_manual_1","crosslingual"),
    ("enjima rත්තිරි weiola (engine oil leak sinhala)","diesel_engine_manual_3","crosslingual"),
    ("kadhavu thiranam thirakkavillai (door not opening tamil)","platform_gate_manual_2","crosslingual"),
]
NEGATIVES=[
    "best biryani in colombo",
    "how do I reset my gmail password",
    "what is the capital of france",
    "cricket match schedule this weekend",
    "how to cook string hoppers",
    "bitcoin price prediction 2027",
]

def eval_set(queries, use_asset_hint=False):
    p1=p3=p5=mrr=0; rows=[]
    for q,exp,cat in queries:
        results,method=retrieve_manual_sections(q, top_k=5)
        ids=[r.get("section_id") for r in results]
        rank=ids.index(exp)+1 if exp in ids else 0
        hit1=1 if rank==1 else 0; hit3=1 if 0<rank<=3 else 0; hit5=1 if 0<rank<=5 else 0
        p1+=hit1; p3+=hit3; p5+=hit5; mrr+=(1/rank if rank else 0)
        rows.append({"q":q,"cat":cat,"expected":exp,"top1":ids[0] if ids else None,
                     "rank":rank,"top1_score":results[0].get("score") if results else None})
    n=len(queries)
    return {"n":n,"P@1":round(p1/n,4),"P@3":round(p3/n,4),"P@5":round(p5/n,4),
            "MRR":round(mrr/n,4),"method":method,"rows":rows}

main=eval_set(QUERIES)
# false positive rate on negatives: retriever returns anything with score>threshold
neg_rows=[]; fp=0
for q in NEGATIVES:
    results,method=retrieve_manual_sections(q, top_k=5)
    top=results[0].get("score") if results else 0
    returned=bool(results)
    if returned and top and top>0.05: fp+=1
    neg_rows.append({"q":q,"returned_any":returned,"top1_score":top,
                     "top1":results[0].get("section_id") if results else None})

out={"retrieval_method":main["method"],
     "readme_claim":"P@1=P@3=P@5=1.000 (shipped eval prepends asset_type+fault_type + keyword-overlap relevance)",
     "independent_query_only":{k:main[k] for k in ("n","P@1","P@3","P@5","MRR")},
     "per_category":{},
     "hard_negatives":{"n":len(NEGATIVES),"no_relevance_threshold":True,
                       "false_positive_rate_score_gt_0.05":round(fp/len(NEGATIVES),4),"rows":neg_rows},
     "rows":main["rows"]}
# per-category breakdown
from collections import defaultdict
cat=defaultdict(lambda:[0,0]) # hits@1, n
for r in main["rows"]:
    cat[r["cat"]][1]+=1
    if r["rank"]==1: cat[r["cat"]][0]+=1
out["per_category"]={c:{"P@1":round(v[0]/v[1],3),"n":v[1]} for c,v in cat.items()}
(EV/"results.json").write_text(json.dumps(out,indent=2),encoding="utf-8")
print("method:",main["method"])
print("INDEPENDENT (query-only):",out["independent_query_only"])
print("per_category:",out["per_category"])
print("hard-negative FP rate (score>0.05):",out["hard_negatives"]["false_positive_rate_score_gt_0.05"])
print("neg top1 scores:",[round(r["top1_score"] or 0,3) for r in neg_rows])
