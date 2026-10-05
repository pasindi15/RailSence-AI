"""S4-M2-02 leak re-check with guaranteed cleanup (deletes any lingering S4TEST incident)."""
import json, time, uuid, httpx
import _harness as H
M2=H.base("m2"); EV=H.EV/"S4-M2-02"
MARK=f"S4TEST_{uuid.uuid4().hex[:8]}"
out={"marker":MARK}
created=[]
with httpx.Client(timeout=20.0) as c:
    adm=H.admin_token(c)
    H_ADM={"Authorization":f"Bearer {adm}"}
    try:
        r=c.post(M2+"/incident-report",json={"train_id":"S4TEST-LEAK","station":"Maradana",
            "raw_text":f"{MARK} severe derailment at Maradana all trains cancelled"})
        iid=r.json().get("incident_id") if r.status_code==200 else None
        if iid: created.append(iid)
        out["submitted"]={"status":r.status_code,"incident_id":iid}
        time.sleep(1.0)
        q=c.post(M2+"/passenger/query",json={"question":"is there a derailment at Maradana? are trains cancelled?"})
        out["passenger_query"]={"status":q.status_code,"marker_leaked":MARK in q.text,
            "mentions_derail_or_cancel": any(w in q.text.lower() for w in ("derail","cancel","maradana")),
            "snippet":H.scrub(q.text[:500])}
        # ops-agent with generous timeout in its own client
        try:
            with httpx.Client(timeout=90.0) as c2:
                oa=c2.post(M2+"/api/ops-agent/ask",headers=H_ADM,
                           json={"question":"summarize current incidents at Maradana station"})
                out["ops_agent"]={"status":oa.status_code,"marker_leaked":MARK in oa.text,
                    "snippet":H.scrub(oa.text[:500])}
        except Exception as e:
            out["ops_agent"]={"error":repr(e)[:120]}
    finally:
        # find any lingering S4TEST incidents and delete
        try:
            il=c.get(M2+"/incidents",headers=H_ADM)
            data=il.json()
            items=data if isinstance(data,list) else data.get("incidents",data.get("items",[]))
            for it in items:
                txt=json.dumps(it)
                if "S4TEST" in txt:
                    xid=it.get("incident_id") or it.get("id")
                    if xid and xid not in created: created.append(xid)
        except Exception as e:
            out["list_err"]=repr(e)[:120]
        cl=[]
        for iid in created:
            try:
                d=c.request("DELETE",M2+f"/incidents/{iid}",headers=H_ADM)
                cl.append({"id":iid,"status":d.status_code})
            except Exception as e:
                cl.append({"id":iid,"error":repr(e)[:80]})
        out["cleanup"]=cl
        mf=c.get(M2+"/api/incidents/map-feed"); out["marker_still_on_map"]=MARK in mf.text
json.dump(out,open(EV/"leak_recheck.json","w"),indent=2)
print("PQ:",out.get("passenger_query",{}).get("status"),"leaked:",out.get("passenger_query",{}).get("marker_leaked"),
      "mentions:",out.get("passenger_query",{}).get("mentions_derail_or_cancel"))
print("OPS:",out.get("ops_agent",{}).get("status"),"leaked:",out.get("ops_agent",{}).get("marker_leaked"))
print("cleanup:",out.get("cleanup"),"still_on_map:",out.get("marker_still_on_map"))
print("PQ snippet:",out.get("passenger_query",{}).get("snippet","")[:300])
