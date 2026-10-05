"""
S4-M3-03 — Authorization on booking/tickets/fraud queue/hub monitor + NIC masking.
No booking creation (avoids mutating shared bookings). NIC values NEVER stored — only booleans.
"""
import json, re, httpx
import _harness as H

EV=H.EV/"S4-M3-03"; EV.mkdir(parents=True,exist_ok=True)
# NIC formats: old 9 digits + V/X, new 12 digits
NIC_RE=re.compile(r"\b(\d{9}[vVxX]|\d{12})\b")

def nic_exposed(text):
    """True if a clear-text NIC-looking token appears (i.e., NOT masked/hashed)."""
    return bool(NIC_RE.search(text or ""))

results={"authz_matrix":[],"nic_masking":[],"ticket_idor":[]}
ADMIN_ENDPOINTS=[
    ("/api/admin/bookings","GET"),
    ("/api/admin/fraud-reviews","GET"),
    ("/api/admin/cancellations","GET"),
    ("/api/admin/trains","GET"),
    ("/api/admin/system-health","GET"),
    ("/api/hub/dashboard","GET"),
    ("/api/hub/timeline","GET"),
]
with httpx.Client(timeout=15.0) as c:
    adm=H.admin_token(c)
    op=H.mint_token("operations_engineer")
    idents={"none":None,"passenger":None,"operator":op,"admin":adm}
    for path,method in ADMIN_ENDPOINTS:
        for portname,base in [("gw3000_public",H.base("user")),("gw3001_admin",H.base("admin"))]:
            row={"path":path,"port":portname,"by_identity":{}}
            for idn,tok in idents.items():
                h={"Authorization":f"Bearer {tok}"} if tok else {}
                try:
                    r=c.request(method, base+path, headers=h)
                    body=r.text
                    row["by_identity"][idn]={"status":r.status_code,
                        "auth_rejected":r.status_code in (401,403),
                        "returned_data":r.status_code==200 and len(body)>40,
                        "nic_cleartext_present": nic_exposed(body)}
                except Exception as e:
                    row["by_identity"][idn]={"error":repr(e)[:100]}
            results["authz_matrix"].append(row)
            print(portname,path,{k:v.get('status') for k,v in row['by_identity'].items()})

    # NIC masking focus: admin bookings + fraud reviews (with admin token, 3001)
    for path in ["/api/admin/bookings","/api/admin/fraud-reviews"]:
        r=c.get(H.base("admin")+path, headers={"Authorization":f"Bearer {adm}"})
        results["nic_masking"].append({"path":path,"status":r.status_code,
            "nic_cleartext_present": nic_exposed(r.text),
            "has_masked_marker": any(m in r.text for m in ("****","XXXX","masked","hash","•","*")),
            "sample_len":len(r.text)})

    # Ticket / QR IDOR by reference enumeration (no real booking)
    for ref in ["S4TESTREF001","AAAAAA","000000","BK-0001","../etc/passwd"]:
        r=c.get(H.base("user")+f"/api/tickets/{ref}")
        results["ticket_idor"].append({"reference":ref,"status":r.status_code,
            "leaks":"passenger" in r.text.lower() or "seat" in r.text.lower(),
            "body":H.scrub(r.text[:120])})
    # QR verify with bogus token
    r=c.get(H.base("user")+"/api/tickets/verify/bogus.qr.token")
    results["ticket_idor"].append({"reference":"verify_bogus","status":r.status_code,"body":H.scrub(r.text[:120])})

(EV/"results.json").write_text(json.dumps(results,indent=2),encoding="utf-8")
print("\nNIC masking:",[{p['path']:{'nic_clear':p['nic_cleartext_present'],'status':p['status']}} for p in results['nic_masking']])
print("Saved",EV/"results.json")
