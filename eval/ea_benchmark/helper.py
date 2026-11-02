"""In-container half of the EA benchmark (see run.py / README.md). Runs inside
intake-backend so it can reach Postgres, /storage and the backend's own parsers.

    python /tmp/ea_bench_helper.py cleanup
    python /tmp/ea_bench_helper.py status
    python /tmp/ea_bench_helper.py score /tmp/ea_labels.json

Only ever touches clients named "BENCH <n>" -- safe to run next to real clients.
`score` prints JSON WITH values (practice + ours); the host stores it in the
gitignored eval/ea_benchmark/runs/. Never print it to a shared log.
"""
import asyncio, json, os, re, shutil, sys, time
sys.path.insert(0, "/app")
import asyncpg
from openpyxl import load_workbook
import classify
import main as M

PREFIX = "BENCH "
STORAGE = "/storage"
# EA line -> (row-label regex on the practice sheet, our record field)
LINES = [
    ("Leistungserloese", r"^leistungserl", "honorare"),
    ("SV 9225", r"^sozialversicherung", "svs_sva"),
    ("Kleinmaterial 9100", r"^kleinmaterial", "kleinmaterial"),
    ("Provisionen 9190", r"^provisionen", "provisionen"),
    ("Abschreibung 9130", r"^abschreibung", "abschreibung"),
    ("Sonstiger Aufwand 9230", r"^sonstiger\s+aufwand", "sonstiger_aufwand"),
    ("Reisekosten 9160", r"^reisekosten", "reisekosten"),
]


def _num(v):
    """Practice-sheet cell -> float. Only real numeric cells count: a text '1.330,00'
    is how OUR old placeholder output looked, never the practice's own sheet."""
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def sheet_lines(path):
    """{line: value} from a practice EA, or None for a sheet that isn't one
    (our own PLACEHOLDER output, or no recognisable EA rows)."""
    wb = load_workbook(path, data_only=True, read_only=True)
    out, placeholder = {}, False
    for ws in wb.worksheets:
        for i, row in enumerate(ws.iter_rows(values_only=True)):
            if i > 200:
                break
            for j, c in enumerate(row):
                if not isinstance(c, str):
                    continue
                if "placeholder template" in c.lower():
                    placeholder = True
                lab = c.strip().lower()
                for name, rx, _ in LINES:
                    if name not in out and re.search(rx, lab):
                        vals = [_num(x) for x in row[j + 1:] if _num(x) is not None]
                        out[name] = vals[0] if vals else None
                break  # only the row's first text cell is its label
    if placeholder or not out:
        return None
    return out


async def bench_clients(db):
    return await db.fetch("SELECT id, display_name FROM clients WHERE display_name LIKE $1 ORDER BY id",
                          PREFIX + "%")


async def cleanup(db):
    cl = await bench_clients(db)
    ids = [c["id"] for c in cl]
    if not ids:
        print(json.dumps({"removed_clients": 0, "removed_files": 0}))
        return
    files = [r["filename"] for r in await db.fetch("SELECT filename FROM forms WHERE client_id = ANY($1)", ids)]
    async with db.transaction():
        fq = "SELECT id FROM forms WHERE client_id = ANY($1)"
        for t in ("extractions", "reviews", "audit_log"):
            await db.execute(f"DELETE FROM {t} WHERE form_id IN ({fq})", ids)
        await db.execute("DELETE FROM forms WHERE client_id = ANY($1)", ids)
        await db.execute("DELETE FROM cases WHERE client_id = ANY($1)", ids)
        for t in ("questionnaire_invites", "tax_years", "client_identities"):
            await db.execute(f"DELETE FROM {t} WHERE client_id = ANY($1)", ids)
        await db.execute("DELETE FROM clients WHERE id = ANY($1)", ids)
    n = 0
    for f in files:  # exact names as the backend wrote them -- no NFC/NFD guessing
        p = os.path.join(STORAGE, os.path.basename(f))
        if os.path.isfile(p):
            os.remove(p)
            n += 1
    cdir = os.path.join(STORAGE, "Clients")
    for d in (os.listdir(cdir) if os.path.isdir(cdir) else []):
        if d.startswith(PREFIX):
            shutil.rmtree(os.path.join(cdir, d), ignore_errors=True)
    print(json.dumps({"removed_clients": len(ids), "removed_files": n}))


def _is_pending(r):
    """Still to be read: queued, an unread primary, or an extractable supporting
    doc (honorar/svs/bescheid/e9/fambh PDFs, vCards, photos waiting for their photo
    check) still in its filed state."""
    if r["status"] == "uploaded":
        return True
    if r["role"] == "primary":
        return r["status"] not in ("extracted", "failed")
    ext = os.path.splitext(r["filename"] or "")[1].lower()
    return (r["status"] == "supporting" and classify.is_extractable(r["doc_type"])
            and (ext == ".pdf" or r["doc_type"] in ("vcf", "id_photo")))


async def status(db):
    ids = [c["id"] for c in await bench_clients(db)]
    rows = await db.fetch("SELECT id, role, status, doc_type, filename FROM forms WHERE client_id = ANY($1)", ids)
    ev = await db.fetchrow(
        """SELECT count(*) n, EXTRACT(EPOCH FROM now() - max(a.created_at)) age FROM audit_log a
           JOIN forms f ON f.id = a.form_id WHERE f.client_id = ANY($1)
           AND a.event_type IN ('extraction','extraction_failed','photo_checked')""", ids)
    fails = await db.fetch(
        """SELECT f.doc_type, count(*) n FROM forms f WHERE f.client_id = ANY($1) AND f.status = 'failed'
           GROUP BY 1""", ids)
    print(json.dumps({
        "clients": len(ids), "docs": len(rows),
        "pending": sum(1 for r in rows if _is_pending(r)),
        "extracted": sum(1 for r in rows if r["status"] == "extracted"),
        "failed": {r["doc_type"]: r["n"] for r in fails},
        "events": ev["n"], "last_event_age_s": float(ev["age"]) if ev["age"] is not None else None,
    }))


def _status(practice, ours):
    p = None if practice in (None, 0) else practice
    o = None if ours in (None, 0) else ours
    if p is None and o is None:
        return "both_blank"
    if p is None:
        return "extra"
    if o is None:
        return "missing"
    if abs(p - o) < 0.01:
        return "match"
    if abs(p - o) <= max(1.0, 0.005 * abs(p)):
        return "near"
    return "wrong"


async def score(db, labels_path):
    labels = json.load(open(labels_path)) if os.path.exists(labels_path) else {}
    built = {}
    results = []
    for c in await bench_clients(db):
        key = c["display_name"][len(PREFIX):]  # "<idx>-<folder hash>"
        # Answer keys from this client's practice EA sheets (rebuilt every run so
        # the host can freeze them on first use / --rebuild-labels).
        for w in await db.fetch(
                "SELECT filename, doc_year FROM forms WHERE client_id = $1 AND doc_type = 'working_file'", c["id"]):
            if not w["doc_year"] or not w["filename"].lower().endswith((".xlsx", ".xlsm")):
                continue
            try:
                lines = sheet_lines(os.path.join(STORAGE, os.path.basename(w["filename"])))
            except Exception:
                continue
            if lines:
                built.setdefault(f"{key}|{w['doc_year']}", lines)
        for lk, truth in labels.items():
            fkey, year = lk.split("|")
            if fkey != key:
                continue
            year = int(year)
            ty = await db.fetchrow("SELECT id, ea_fields FROM tax_years WHERE client_id = $1 AND year = $2",
                                   c["id"], year)
            ea = (json.loads(ty["ea_fields"]) if ty and isinstance(ty["ea_fields"], str)
                  else (ty["ea_fields"] if ty else None)) or {}
            fields = ea.get("fields", ea) if isinstance(ea, dict) else {}
            has_source = bool(await db.fetchval(
                """SELECT count(*) FROM forms f JOIN extractions e ON e.form_id = f.id
                   WHERE f.client_id = $1 AND f.doc_year = $2""", c["id"], year))
            row = {"key": lk, "has_source": has_source, "lines": {}}
            for name, _, fld in LINES:
                f = fields.get(fld) if isinstance(fields.get(fld), dict) else {}
                ours = M._to_number(f.get("value"))
                row["lines"][name] = {
                    "practice": truth.get(name), "ours": ours, "ours_raw": f.get("value"),
                    "src": f.get("source_doc_type"), "calc": (f.get("calc") or {}).get("kind"),
                    "status": _status(truth.get(name), ours),
                }
            results.append(row)
    print(json.dumps({"built_labels": built, "results": results}, default=str, ensure_ascii=False))


async def amain():
    db = await asyncpg.connect(os.environ["DATABASE_URL"])
    try:
        cmd = sys.argv[1]
        if cmd == "cleanup":
            await cleanup(db)
        elif cmd == "status":
            await status(db)
        elif cmd == "score":
            await score(db, sys.argv[2])
    finally:
        await db.close()


asyncio.run(amain())
