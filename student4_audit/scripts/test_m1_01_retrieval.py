"""
S4-M1-01 — M1 ChromaDB FAQ retrieval, multilingual + out-of-corpus.
Ground truth = correct source doc (fares/policies/schedules). 3 docs -> baseline P@1=0.33.
Per-language P@1 (fairness). Out-of-corpus queries test relevance threshold (distance).
"""
import sys, json, pathlib
M1DIR=pathlib.Path("E:/Y3 S2/Information Retrieval and Web Analytics - IT3041/RailSence-AI/M1-passenger_assistant/backend")
sys.path.insert(0, str(M1DIR)); sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from rag.retriever import retrieve_faq_chunks
import _harness as H
EV=H.EV/"S4-M1-01"; EV.mkdir(parents=True,exist_ok=True)

# (query, expected_source, lang)
Q=[
 # English
 ("How much is a ticket from Colombo Fort to Kandy?","fares.md","en"),
 ("What is the fare to Badulla?","fares.md","en"),
 ("How do I cancel my booking?","policies.md","en"),
 ("What is the refund policy?","policies.md","en"),
 ("How much luggage can I carry?","policies.md","en"),
 ("What time does the train to Galle leave?","schedules.md","en"),
 ("Train schedule for the Jaffna line?","schedules.md","en"),
 ("When is the next train to Badulla via Kandy?","schedules.md","en"),
 # Sinhala
 ("කොළඹ කොටුවේ සිට මහනුවරට ප්‍රවේශ පත්‍රයේ ගාස්තුව කීයද?","fares.md","si"),
 ("බදුල්ලට ගාස්තුව කීයද?","fares.md","si"),
 ("මගේ වෙන්කිරීම අවලංගු කරන්නේ කෙසේද?","policies.md","si"),
 ("මුදල් ආපසු ගෙවීමේ ප්‍රතිපත්තිය කුමක්ද?","policies.md","si"),
 ("මට කොපමණ බෑග් රැගෙන යා හැකිද?","policies.md","si"),
 ("ගාල්ලට දුම්රිය පිටත් වන්නේ කීයටද?","schedules.md","si"),
 ("යාපනය මාර්ගයේ දුම්රිය කාලසටහන කුමක්ද?","schedules.md","si"),
 ("මහනුවර හරහා බදුල්ලට ඊළඟ දුම්රිය කවදාද?","schedules.md","si"),
 # Tamil
 ("கொழும்பு கோட்டையிலிருந்து கண்டிக்கு டிக்கெட் விலை எவ்வளவு?","fares.md","ta"),
 ("பதுளைக்கு கட்டணம் எவ்வளவு?","fares.md","ta"),
 ("எனது முன்பதிவை எப்படி ரத்து செய்வது?","policies.md","ta"),
 ("பணத்தைத் திரும்பப் பெறும் கொள்கை என்ன?","policies.md","ta"),
 ("நான் எவ்வளவு சாமான்கள் எடுத்துச் செல்லலாம்?","policies.md","ta"),
 ("காலிக்கு ரயில் எப்போது புறப்படும்?","schedules.md","ta"),
 ("யாழ்ப்பாண வழியில் ரயில் அட்டவணை என்ன?","schedules.md","ta"),
 ("கண்டி வழியாக பதுளைக்கு அடுத்த ரயில் எப்போது?","schedules.md","ta"),
]
NEG=["best biryani in colombo","who won the cricket world cup","how to bake a chocolate cake",
     "latest iphone price","weather forecast for tomorrow","how do I learn python"]

def source_rank(chunks, exp):
    srcs=[c["source"] for c in chunks]
    return (srcs.index(exp)+1) if exp in srcs else 0

rows=[]; from collections import defaultdict
lang=defaultdict(lambda:[0,0,0.0])  # p1, n, sum_dist
for q,exp,lg in Q:
    ch=retrieve_faq_chunks(q, top_k=3)
    rank=source_rank(ch,exp)
    d0=ch[0]["distance"] if ch else None
    rows.append({"q":q,"lang":lg,"expected":exp,"top_source":ch[0]["source"] if ch else None,
                 "rank":rank,"top_distance":round(d0,4) if d0 is not None else None})
    lang[lg][1]+=1; lang[lg][2]+=(d0 or 0)
    if rank==1: lang[lg][0]+=1
per_lang={lg:{"P@1":round(v[0]/v[1],3),"n":v[1],"mean_top_distance":round(v[2]/v[1],4)} for lg,v in lang.items()}
overall_p1=round(sum(1 for r in rows if r["rank"]==1)/len(rows),4)
overall_p3=round(sum(1 for r in rows if 0<r["rank"]<=3)/len(rows),4)
mrr=round(sum((1/r["rank"] if r["rank"] else 0) for r in rows)/len(rows),4)

neg_rows=[]
for q in NEG:
    ch=retrieve_faq_chunks(q, top_k=3)
    neg_rows.append({"q":q,"top_source":ch[0]["source"] if ch else None,
                     "top_distance":round(ch[0]["distance"],4) if ch else None})
in_corpus_mean=round(sum(r["top_distance"] for r in rows if r["top_distance"] is not None)/len(rows),4)
neg_mean=round(sum(r["top_distance"] for r in neg_rows if r["top_distance"] is not None)/len(neg_rows),4)

out={"note":"Ground truth = correct source doc (3 docs, baseline P@1=0.33). English MiniLM model on English corpus.",
     "overall":{"n":len(Q),"P@1":overall_p1,"P@3":overall_p3,"MRR":mrr},
     "per_language_fairness":per_lang,
     "out_of_corpus":{"n":len(NEG),"no_threshold_note":"retriever always returns top_k; no relevance cutoff",
        "mean_top_distance_out_of_corpus":neg_mean,"mean_top_distance_in_corpus":in_corpus_mean,
        "rows":neg_rows},
     "rows":rows}
(EV/"results.json").write_text(json.dumps(out,indent=2),encoding="utf-8")
print("overall:",out["overall"])
print("per_language:",per_lang)
print("in-corpus mean dist:",in_corpus_mean,"| out-of-corpus mean dist:",neg_mean)
