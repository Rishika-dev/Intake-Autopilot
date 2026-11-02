"""Regression check for Phase 2: dashboard triage ordering (2026-10-26).

Pure logic -- no stack, no Docker, no DB, no PII. The backend orders the client
list in SQL:

    ORDER BY BOOL_OR(COALESCE(ty.dringend, FALSE)) DESC,   -- Notfälle first
             MAX(f.created_at) DESC NULLS LAST,             -- newest info next
             c.display_name                                 -- stable tiebreak

This script mirrors those exact semantics in Python and asserts the resulting
order on hand-built rows, so the triage rule (the subtle part: dringend wins over
recency, and a client with no filed forms sinks below everyone who has one) stays
correct even if the SQL is refactored. It also greps the backend/dashboard to
confirm the pieces that make the rule reachable are present.

Usage:  python scripts/validate_triage_order.py       (from repo root or anywhere)
Exit code is non-zero if any check fails.
"""
import os
import re
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.join(_HERE, "..")


def order_key(row):
    """Mirror of the SQL ORDER BY. Returns a sort key for ascending sort that
    reproduces `dringend DESC, last_info_at DESC NULLS LAST, display_name ASC`.
      - dringend: True first  -> 0 for True, 1 for False
      - last_info_at: newest first, NULLs last -> (is_null, -epoch)
      - display_name: A->Z
    """
    dringend = bool(row.get("dringend"))
    ts = row.get("last_info_at")  # epoch seconds or None
    is_null = ts is None
    return (
        0 if dringend else 1,
        (1, 0.0) if is_null else (0, -float(ts)),
        (row.get("display_name") or "").lower(),
    )


def main() -> int:
    failures = 0

    def check(label, cond):
        nonlocal failures
        print(f"  {'OK ' if cond else 'XX '} {label}")
        failures += not cond

    print("=== triage ordering ===")
    # Rows deliberately shuffled; names chosen so pure-alphabetical would differ
    # from the triage order, proving the sort keys (not the input order) decide.
    rows = [
        {"display_name": "Albescu", "dringend": False, "last_info_at": 100},   # oldest, not urgent
        {"display_name": "Barbu",   "dringend": False, "last_info_at": 300},   # newest non-urgent
        {"display_name": "Cojocaru","dringend": True,  "last_info_at": 100},   # urgent, old
        {"display_name": "Dima",    "dringend": True,  "last_info_at": 200},   # urgent, newer
        {"display_name": "Enache",  "dringend": False, "last_info_at": None},  # never filed -> last
        {"display_name": "Florea",  "dringend": False, "last_info_at": 200},   # mid non-urgent
    ]
    ordered = [r["display_name"] for r in sorted(rows, key=order_key)]
    expected = ["Dima", "Cojocaru", "Barbu", "Florea", "Albescu", "Enache"]
    check(f"order is {expected}", ordered == expected)
    check("both Dringend clients precede every non-Dringend one",
          ordered.index("Dima") < ordered.index("Barbu") and
          ordered.index("Cojocaru") < ordered.index("Barbu"))
    check("within Dringend, newer info first (Dima before Cojocaru)",
          ordered.index("Dima") < ordered.index("Cojocaru"))
    check("within non-Dringend, newer info first (Barbu<Florea<Albescu)",
          ordered.index("Barbu") < ordered.index("Florea") < ordered.index("Albescu"))
    check("client with no filed forms sinks to the bottom (Enache last)",
          ordered[-1] == "Enache")

    # Ties: same dringend + same timestamp -> alphabetical, deterministic.
    tie = [{"display_name": n, "dringend": False, "last_info_at": 500}
           for n in ("Zamfir", "Ardelean", "Munteanu")]
    tie_ordered = [r["display_name"] for r in sorted(tie, key=order_key)]
    check("equal urgency+recency breaks ties alphabetically",
          tie_ordered == ["Ardelean", "Munteanu", "Zamfir"])

    print("\n=== wiring present (grep) ===")
    main_py = open(os.path.join(_ROOT, "backend", "main.py"), encoding="utf-8").read()
    frage = open(os.path.join(_ROOT, "backend", "static", "fragebogen.html"), encoding="utf-8").read()
    schema = open(os.path.join(_ROOT, "database", "schema.sql"), encoding="utf-8").read()
    page = open(os.path.join(_ROOT, "dashboard", "src", "app", "page.tsx"), encoding="utf-8").read()
    yr = open(os.path.join(_ROOT, "dashboard", "src", "app", "clients", "[id]", "page.tsx"), encoding="utf-8").read()

    check("schema adds tax_years.dringend", "ADD COLUMN IF NOT EXISTS dringend BOOLEAN" in schema)
    check("schema adds approved_at/by", "approved_at" in schema and "approved_by" in schema)
    check("list_clients orders dringend-first", bool(
        re.search(r"ORDER BY\s+BOOL_OR\(COALESCE\(ty\.dringend", main_py)))
    check("list_clients returns last_info_at", "MAX(f.created_at)      AS last_info_at" in main_py)
    check("approve endpoint sets status='approved'",
          "status = 'approved'" in main_py and "/api/tax-years/{ty_id}/approve" in main_py)
    check("approve requires a generated sheet first",
          'ty["status"] not in ("generated", "approved")' in main_py)
    check("dringend toggle endpoint exists", "/api/tax-years/{ty_id}/dringend" in main_py)
    check("questionnaire only RAISES dringend (escalate-only)",
          "SET dringend = TRUE WHERE id = :id" in main_py)
    check("fragebogen marks dringend from an urgent flag",
          'dringend: flags.some(x=>x.sev==="urgent")' in frage)
    check("fragebogen PDF metadata carries dringend", "dringend:sub.dringend" in frage)
    check("client list renders a Dringend badge + relative time",
          "c.dringend &&" in page and "Dringend" in page and "relTime(c.last_info_at)" in page)
    check("per-year screen has Freigeben + Dringend controls",
          "Freigeben" in yr and "toggleDringend" in yr and "approve(" in yr)

    print(f"\n{'ALL CHECKS PASSED' if not failures else str(failures) + ' CHECK(S) FAILED'}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
