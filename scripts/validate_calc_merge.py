"""Regression check for the handwritten-figure merge rules (2026-10-26).

Needs the backend's dependencies, so it runs INSIDE the backend container:
    docker cp scripts/validate_calc_merge.py intake-backend:/tmp/
    docker exec intake-backend sh -c "cd /app && python /tmp/validate_calc_merge.py"
Made-up figures only, no PII. Exit code is non-zero if any check fails.
"""
import sys

sys.path.insert(0, "/app")
import main as m  # noqa: E402

failures = 0


def check(label, cond):
    global failures
    print(f"  {'OK  ' if cond else 'FAIL'} {label}")
    failures += 0 if cond else 1


print("=== calculations ===")
v, n = m._resolve_calc("12 MONATE - 300 x 4 = 1.200 €")
check("label count before a dash is not part of the sum", v == "1.200" and n["calc_ok"] is True)
v, n = m._resolve_calc("300 x 4 = 1.20")
check("truncated result -> computed figure, still flagged", v == "1.200" and n["calc_ok"] is False and n.get("computed"))
v, n = m._resolve_calc("300 x 4 = 1.500")
check("a genuinely different result is kept, flagged", v == "1.500" and n["calc_ok"] is False and not n.get("computed"))
v, n = m._resolve_calc("4x900=3.600+250=3.850")
check("chained calculation -> last total", v == "3.850" and n["calc_ok"] is True)

print("=== children ===")
check("'nicht bekommen' is not a child count", not m._is_child_count("nicht bekommen"))
check("'2' / 'keine' are", m._is_child_count("2") and m._is_child_count("keine"))

print("=== merge ===")
out = m.merge_year_fields([
    {"form_id": 1, "doc_type": "photo_form", "fields": {
        "provisionen": "50 x 6 = 300 €", "reisekosten": "100 x 6 = 600 €", "stnr": "123456789",
        "children": "nicht bekommen", "e_card_number": "Not Found", "home_address": "Not Found"}},
    {"form_id": 2, "doc_type": "id_photo", "fields": {
        "document_kind": "ecard", "e_card_number": "1234010180", "home_address": "Str. Exemplu 1",
        "name": "Some Name"}},
])
check("commission and transport stay on their own lines",
      out["provisionen"]["value"] == "300" and out["reisekosten"]["value"] == "600")
check("StNr from the handwritten sheet", out["stnr"]["value"] == "123456789")
check("no children value from a Familienbeihilfe answer", "children" not in out)
check("e-card + home address from the ID photo",
      out["e_card_number"]["source_doc_type"] == "id_photo" and out["hometown"]["source_doc_type"] == "id_photo")
check("ID photo never sources the name", "name" not in out)

print("=== typed note: figure not written in the text ===")
note = "Einnahmen: 1.250,00 Euro im Monat, ganzes Jahr. SVS 2.400 Euro. Fahrt 40 km."
nf = {"honorare": "15000", "svs_sva": "2.400", "reisekosten": "960", "name": "Max Muster"}
check("worked-out figures are found, a written one is not",
      sorted(m._not_in_text(nf, note)) == ["honorare", "reisekosten"])
nf["_not_in_text"] = m._not_in_text(nf, note)
out = m.merge_year_fields([{"form_id": 3, "doc_type": "intake_note", "fields": nf}])
check("merge flags them for review, keeps the value",
      out["honorare"]["value"] == "15000" and out["honorare"].get("calc", {}).get("kind") == "not_in_text"
      and out["reisekosten"].get("calc", {}).get("kind") == "not_in_text")
check("a figure written in the note is not flagged", "calc" not in out["svs_sva"])

print(f"\n{'ALL CHECKS PASSED' if not failures else str(failures) + ' CHECK(S) FAILED'}")
sys.exit(1 if failures else 0)
