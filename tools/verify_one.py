"""Re-extract ONE form, rebuild its tax year, and report structure only.

Run inside the backend container:
    docker cp verify_one.py intake-backend:/tmp/verify_one.py
    docker exec intake-backend python /tmp/verify_one.py <form_id>

PII-safe: prints booleans, lanes, sources and conflict flags -- never a value,
name or filename.
"""
import asyncio, json, os, sys, time, urllib.request
import asyncpg

API = "http://localhost:8080"
MONEY = ["honorare", "svs_sva", "kleinmaterial", "provisionen", "abschreibung", "sonstiger_aufwand", "reisekosten"]
EA = MONEY + ["stnr", "e_card_number", "name", "address_austria", "children"]
EMPTY = ("", "not found", "unknown", "none")


def post(path):
    req = urllib.request.Request(API + path, data=b"{}", method="POST",
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.status


def get(path):
    with urllib.request.urlopen(API + path, timeout=60) as r:
        return json.load(r)


def num(v):
    import re
    s = re.sub(r"[^\d,.\-]", "", str(v or ""))
    m = re.match(r"^(-?)(.*)[.,](\d{2})$", s)
    try:
        if m:
            return float(f"{m.group(1)}{re.sub(r'[.,]', '', m.group(2)) or '0'}.{m.group(3)}")
        return float(re.sub(r"[.,]", "", s)) if s.strip("-") else None
    except ValueError:
        return None


async def main(form_id: int):
    db = await asyncpg.connect(os.environ["DATABASE_URL"])
    f = await db.fetchrow("SELECT doc_type, role, tax_year_id, status FROM forms WHERE id=$1", form_id)
    if not f:
        print("form not found"); return
    print(f"form {form_id}: doc_type={f['doc_type']} role={f['role']} tax_year_id={f['tax_year_id']}")
    q = "SELECT COUNT(*) FROM audit_log WHERE form_id=$1 AND event_type IN ('extraction','extraction_failed')"
    before = await db.fetchval(q, form_id)

    t0 = time.time()
    print("reextract:", post(f"/api/forms/{form_id}/reextract"))
    while await db.fetchval(q, form_id) <= before:
        if time.time() - t0 > 1200:
            print("TIMEOUT after 20 min -- check `docker logs intake-backend` / `intake-ai`"); return
        await asyncio.sleep(3)
    ev = await db.fetchrow("SELECT event_type, details FROM audit_log WHERE form_id=$1 "
                           "ORDER BY created_at DESC LIMIT 1", form_id)
    det = json.loads(ev["details"] or "{}") if isinstance(ev["details"], str) else (ev["details"] or {})
    print(f"result: {ev['event_type']} lane={det.get('lane')} in {time.time() - t0:.0f}s")
    if ev["event_type"] != "extraction":
        return

    raw = await db.fetchval("SELECT json_result FROM extractions WHERE form_id=$1", form_id)
    r = json.loads(raw) if isinstance(raw, str) else (raw or {})
    vals = {k: r.get(k) for k in MONEY}
    present = {k: str(v or "").strip().lower() not in EMPTY for k, v in vals.items()}
    nums = [num(v) for k, v in vals.items() if present[k]]
    nums = [n for n in nums if n is not None]
    print("money fields present:", {k: present[k] for k in MONEY})
    print("any two money values identical:", len(nums) != len(set(nums)))
    print("any negative money value:", any(n < 0 for n in nums))
    if "_kz_cells_checked" in r:
        print("kennzahl-cell read: yes, totals cross-check:", r["_kz_cells_checked"])

    if f["tax_year_id"]:
        print("rebuild:", post(f"/api/tax-years/{f['tax_year_id']}/rebuild"))
        d = get(f"/api/tax-years/{f['tax_year_id']}")
        fields = d.get("fields") or (d.get("ea_fields") or {}).get("fields", {})
        for k in EA:
            v = fields.get(k)
            print(f"  {k}: " + ("absent" if v is None else
                  f"present source={v.get('source_doc_type')} conflict={bool(v.get('conflict'))}"))
    await db.close()


if __name__ == "__main__":
    asyncio.run(main(int(sys.argv[1])))
