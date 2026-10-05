"""S4-M4-03 completion: engineer login (correct schema) + authorized flag/revert of S4TEST train."""
import json, httpx
import _harness as H
TID="S4-M4-03"; EV=H.EV/TID; M4=H.base("m4"); TEST_TRAIN="S4TEST-TRAIN-001"
out={}
with httpx.Client(timeout=15.0) as c:
    tok=None
    for eid in ["admin","ENG-001"]:
        r=c.post(M4+"/api/engineer-login", json={"engineer_id":eid,"password":H.M4_ENG_PW})
        out.setdefault("login_attempts",[]).append({"engineer_id":eid,"status":r.status_code})
        if r.status_code==200:
            d=r.json(); tok=d.get("token") or d.get("session_token") or d.get("access_token")
            out["login_ok_with"]=eid; break
    out["got_token"]=bool(tok)
    print("login:",out["login_attempts"],"token:",bool(tok))
    if tok:
        h={"x-engineer-token":tok}
        fr=c.post(M4+"/api/flag-train", headers=h,
                  json={"train_id":TEST_TRAIN,"reason":"S4TEST audit flag","severity":"low"})
        chk1=c.get(M4+"/api/trains-under-maintenance")
        rev=c.delete(M4+f"/api/flag-train/{TEST_TRAIN}", headers=h)
        chk2=c.get(M4+"/api/trains-under-maintenance")
        out["flag"]={"status":fr.status_code,"body":H.scrub(fr.text[:200])}
        out["flagged_present_after_flag"]=TEST_TRAIN in chk1.text
        out["revert"]={"status":rev.status_code,"body":H.scrub(rev.text[:200])}
        out["flagged_present_after_revert"]=TEST_TRAIN in chk2.text
        print("flag:",fr.status_code,"present_after_flag:",TEST_TRAIN in chk1.text,
              "| revert:",rev.status_code,"present_after_revert:",TEST_TRAIN in chk2.text)
(EV/"flag_revert.json").write_text(json.dumps(out,indent=2),encoding="utf-8")
print("Saved",EV/"flag_revert.json")
