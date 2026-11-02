"""Compare a client's merged per-year record with the practice's own EA working
file for the same year. PII-safe: prints only line names (fixed EA labels) and
MATCH / WRONG / blank -- never a value, name, address or filename.

    docker exec intake-backend python /tmp/compare_ea.py <client_id>
"""
import asyncio, json, os, re, sys, urllib.request
import asyncpg
from openpyxl import load_workbook

API = "http://localhost:8080"
# EA line -> (regex on the row label, our record field or computed total)
LINES = [
    ("Leistungserloese", r"^leistungserl", "honorare"),
    ("SV 9225", r"^sozialversicherung", "svs_sva"),
    ("Kleinmaterial 9100", r"^kleinmaterial", "kleinmaterial"),
    ("Provisionen 9190", r"^provisionen", "provisionen"),
    ("Abschreibung 9130", r"^abschreibung", "abschreibung"),
    ("Sonstiger Aufwand 9230", r"^sonstiger\s+aufwand", "sonstiger_aufwand"),
    ("Reisekosten 9160", r"^reisekosten", "=reise"),
    ("Gewinn", r"^gewinn", "=gewinn"),
    ("Grundfreibetrag", r"grundfreibetrag", "=gfb"),
    ("Einkuenfte", r"^eink(ue|ü)nfte", "=eink"),
]
EXP = ["svs_sva", "kleinmaterial", "provisionen", "abschreibung", "sonstiger_aufwand"]


def num(v):
    if v is None or v == "":
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = re.sub(r"[^\d,.\-]", "", str(v))
    if not re.search(r"\d", s):
        return None
    neg, s = s.startswith("-"), s.lstrip("-")
    m = re.fullmatch(r"(.*)[.,](\d{1,2})", s)
    whole, frac = (m.group(1), m.group(2)) if m else (s, "0")
    try:
        n = float(f"{re.sub(r'[.,]', '', whole) or '0'}.{frac}")
    except ValueError:
        return None
    return -n if neg else n


def sheet_lines(path):
    """{line_name: first numeric cell right of its label} from the practice EA."""
    wb = load_workbook(path, data_only=True, read_only=True)
    out = {}
    for ws in wb.worksheets:
        for i, row in enumerate(ws.iter_rows(values_only=True)):
            if i > 200:
                break
            for j, c in enumerate(row):
                if not isinstance(c, str):
                    continue
                lab = c.strip().lower()
                for name, rx, _ in LINES:
                    if name not in out and re.search(rx, lab):
                        vals = [x for x in row[j + 1:] if isinstance(x, (int, float))]
                        out[name] = float(vals[0]) if vals else None
                break  # only the row's first text cell is its label
    return out


def ours(fields):
    g = lambda k: num((fields.get(k) or {}).get("value"))
    km, trips = g("travel_distance_km") or 0, g("trip_count") or 0
    reise = min(km * 2 * 0.42 * trips, 6000) if km and trips else g("reisekosten")
    vals = {k: g(k) for k in ["honorare"] + EXP}
    aufw = sum(v or 0 for k, v in vals.items() if k != "honorare") + (reise or 0)
    gew = (vals["honorare"] or 0) - aufw
    gfb = max(0.0, gew * 0.15)
    vals.update({"=reise": reise, "=gewinn": gew, "=gfb": gfb, "=eink": gew - gfb})
    return vals


def get(path):
    with urllib.request.urlopen(API + path, timeout=60) as r:
        return json.load(r)


async def main(cid):
    db = await asyncpg.connect(os.environ["DATABASE_URL"])
    tys = await db.fetch("SELECT id, year FROM tax_years WHERE client_id=$1 ORDER BY year", cid)
    wfs = await db.fetch("SELECT id, doc_year, filename FROM forms WHERE client_id=$1 AND doc_type='working_file'", cid)
    for ty in tys:
        print(f"== {ty['year']} (tax_year {ty['id']})")
        sheets = [w for w in wfs if w["doc_year"] == ty["year"] and w["filename"].lower().endswith((".xlsx", ".xlsm"))]
        if not sheets:
            print("   no practice EA for this year -- nothing to compare"); continue
        try:
            ref = sheet_lines("/storage/" + os.path.basename(sheets[0]["filename"]))
        except Exception as e:
            print("   practice EA unreadable:", type(e).__name__); continue
        d = get(f"/api/tax-years/{ty['id']}")
        fields = d.get("fields") or (d.get("ea_fields") or {}).get("fields", {})
        mine = ours(fields)
        for name, _, key in LINES:
            r, m = ref.get(name), mine.get(key)
            r = None if r in (None, 0) else r
            m = None if m in (None, 0) else m
            if r is None and m is None:
                st = "ok (both blank)"
            elif r is None:
                st = "WRONG (practice blank, ours filled)"
            elif m is None:
                st = "MISSING (practice filled, ours blank)"
            else:
                st = "MATCH" if abs(r - m) < 0.01 else "WRONG"
            src = (fields.get(key) or {}).get("source_doc_type") if not key.startswith("=") else "computed"
            print(f"   {name:24s} {st}" + (f"  [from {src}]" if src and m is not None else ""))
    await db.close()


asyncio.run(main(int(sys.argv[1])))
