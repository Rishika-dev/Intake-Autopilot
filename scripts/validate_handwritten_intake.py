"""Regression check for Phase 1: handwritten Stabinger paper-form intake (2026-10-26).

Pure logic -- no stack, no Docker, no model, no PII. Verifies that:
  1. classify.looks_like_intake_form() recognises the Stabinger form's printed
     wording and does NOT fire on an ordinary tax document.
  2. classify.decide_case_roles() routes a content-detected intake form to
     intake_form_paper / primary / extract -- EVEN when a named tax PDF is also in
     the case (the form is always read, as the conflict anchor) -- and leaves
     ordinary docs and the lone-photo vision fallback behaving as before.
  3. extractors.sniff_text() degrades gracefully (no raise) when PyMuPDF is absent.

Usage:  python scripts/validate_handwritten_intake.py     (run from repo root or backend/)
Exit code is non-zero if any check fails, so it can gate a pre-ship smoke test.
"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, "..", "backend"))

import classify     # noqa: E402
import extractors   # noqa: E402

# A faithful slice of the Stabinger form's PRINTED text layer (header + field
# labels + DSGVO + WhatsApp number). No handwriting, no PII -- just the template.
FORM_TEXT = (
    "Informationsblatt Steuererklärungen\n"
    "Fișa de informații declarații fiscale\n"
    "STABINGER CONSULTING in Kooperation mit STB Kleinfercher Wolfgang\n"
    "Bei Interesse bitte das Formular ausfüllen ... per WhatsApp an +43 677 6349 1827 senden.\n"
    "1. E-Card-Nummer und Steuerjahr (Număr E-Card și anul fiscal)\n"
    "2. Name, Vorname (Nume, prenume)\n"
    "5. Honorare = Jahres-Gesamteinnahmen (Onorarii = venituri anuale totale)\n"
    "8. SVS/SVA = Jahres-Gesamtsumme (SVS/SVA = suma anuală totală)\n"
    "9. Familienbeihilfe? Familienstand? Anzahl Kinder?\n"
    "Datenschutzhinweis und Einwilligung (DSGVO)\n"
)

# An ordinary SVS statement's text -- mentions Honorare/SVS in passing but is NOT
# the intake form; must not be misdetected.
SVS_TEXT = (
    "Sozialversicherung der Selbständigen\nVorschreibung Quartal 2 / 2024\n"
    "Beitragsgrundlage ... Honorare ... SVS Landesstelle Wien\n"
)


def main() -> int:
    failures = 0

    def check(label, cond):
        nonlocal failures
        print(f"  {'OK ' if cond else 'XX '} {label}")
        failures += not cond

    print("=== looks_like_intake_form ===")
    check("Stabinger form text -> detected", classify.looks_like_intake_form(FORM_TEXT))
    check("SVS statement text -> NOT detected", not classify.looks_like_intake_form(SVS_TEXT))
    check("empty/None text -> NOT detected", not classify.looks_like_intake_form(""))

    print("\n=== decide_case_roles routing ===")
    # (a) handwritten form (as a text-bearing scan) ALONGSIDE a named E1a primary:
    #     both must be primary+extract; the form must be intake_form_paper.
    case_a = classify.decide_case_roles([
        {"filename": "E1a 2024 Popescu.pdf", "size_bytes": 120000, "text": "Formular E 1a ..."},
        {"filename": "scan_whatsapp_uuid.pdf", "size_bytes": 300000, "text": FORM_TEXT},
    ])
    form = next((a for a in case_a if a["doc_type"] == "intake_form_paper"), None)
    e1a = next((a for a in case_a if a["doc_type"] == "e1a"), None)
    check("form -> intake_form_paper/primary/extract", bool(form) and form["role"] == "primary" and form["extract"])
    check("form year is None (tax year is handwritten)", bool(form) and form["year"] is None)
    check("named E1a still primary+extract (both read)", bool(e1a) and e1a["role"] == "primary" and e1a["extract"])

    # (b) lone handwritten form (a text-bearing scan, no other primary): still read.
    case_b = classify.decide_case_roles([
        {"filename": "img.pdf", "size_bytes": 300000, "text": FORM_TEXT},
    ])
    check("lone form -> intake_form_paper/primary/extract",
          bool(case_b) and case_b[0]["doc_type"] == "intake_form_paper" and case_b[0]["extract"])

    # (c) ordinary SVS doc (paired with a named E1a so the no-primary vision fallback
    #     doesn't promote it): must stay svs/supporting and never be misread as the
    #     intake form despite mentioning "Honorare"/"SVS" in passing.
    case_c = classify.decide_case_roles([
        {"filename": "E1a 2024.pdf", "size_bytes": 120000, "text": "Formular E 1a ..."},
        {"filename": "SVS 2024.pdf", "size_bytes": 80000, "text": SVS_TEXT},
    ])
    svs = next((a for a in case_c if a["doc_type"] == "svs"), None)
    check("SVS doc -> svs/supporting (not intake form)",
          bool(svs) and svs["role"] == "supporting" and svs["extract"])
    check("no intake_form_paper falsely created from the SVS",
          not any(a["doc_type"] == "intake_form_paper" for a in case_c))

    # (d) lone PHOTO with no text layer + no named primary: existing vision fallback
    #     still promotes it (regression guard for the untouched fallback path).
    case_d = classify.decide_case_roles([
        {"filename": "IMG_2231.jpg", "size_bytes": 200000},
    ])
    check("lone photo -> promoted to primary+extract (fallback intact)",
          bool(case_d) and case_d[0]["role"] == "primary" and case_d[0]["extract"])

    print("\n=== sniff_text degrades gracefully ===")
    try:
        r1 = extractors.sniff_text(b"", "x.pdf")
        r2 = extractors.sniff_text(b"\x89PNG not a pdf", "photo.jpg")
        check("sniff_text never raises, returns str", isinstance(r1, str) and isinstance(r2, str))
        check("non-PDF bytes -> empty string", r2 == "")
    except Exception as e:  # pragma: no cover
        check(f"sniff_text raised ({type(e).__name__})", False)

    print("\n=== extraction lane: intake form always vision ===")
    # A text-layer form must NOT go to lane 3 (labels only, generic fields, no
    # tax_year) -- vision's handwritten-intake prompt carries tax_year.
    r = extractors.extract_document(b"%PDF-1.4 any", "intake_form_paper", "form.pdf")
    check("intake_form_paper -> declined to vision (not llm_text)",
          r.get("ok") is False and r.get("lane") == "vision")

    print("\n=== practice's own invoice is never an income source ===")
    inv = ("Stabinger Consulting\nHonorarnote: 1\nErstellung der Einkommensteuererklaerung\n"
           "Gesamtbetrag 180,00 EUR")
    care = "Honorarnote Betreuung 24h Gesamtbetrag 2.400,00 EUR"
    check("practice invoice detected", classify.looks_like_practice_invoice(inv))
    check("client's care-agency Honorarnote NOT taken for the practice invoice",
          not classify.looks_like_practice_invoice(care))
    check("intake form NOT taken for the practice invoice",
          not classify.looks_like_practice_invoice(FORM_TEXT))
    r = classify.decide_case_roles([{"filename": "Honorarnote 2025.pdf", "text": inv, "size_bytes": 9000}])
    check("invoice -> practice_invoice, not extracted, not fallback-promoted",
          r and r[0]["doc_type"] == "practice_invoice" and not r[0]["extract"])

    print("\n=== fallback photo re-typed by its printed title ===")
    check("E9 title -> e9", classify.doc_type_from_title("Bescheinigung EU/EWR / Certification EU/EEA") == "e9")
    check("intake form title -> no re-type", classify.doc_type_from_title("Informationsblatt Steuererklaerung") is None)
    check("no title -> no re-type", classify.doc_type_from_title("Not Found") is None)

    print("\n=== typed intake note (.odt/.docx) is read ===")
    import io, zipfile
    note = "Ecard nummer 1234567890\nHonorare 12000 Eur\nWko 100\nFahrt kosten 900\nSvs 1500 Eur\nKinder 2"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("content.xml", "<office:text>" + "".join(f"<text:p>{l}</text:p>" for l in note.split("\n"))
                   + "</office:text>")
    odt = buf.getvalue()
    txt = extractors.sniff_text(odt, "note.odt")
    check(".odt text read, line breaks kept", "Honorare 12000" in txt and txt.count("\n") >= 5)
    check("typed note detected", classify.looks_like_intake_note("note.odt", txt))
    check("a letter mentioning Honorar once is NOT a note",
          not classify.looks_like_intake_note("brief.odt", "Sehr geehrte Damen und Herren, anbei das Honorar."))
    r = classify.decide_case_roles([{"filename": "note.odt", "text": txt, "size_bytes": len(odt)}])
    check("note -> intake_note/primary/extract", r and r[0]["doc_type"] == "intake_note" and r[0]["extract"])
    check("note -> text lane (not vision)", extractors.extract_document(odt, "intake_note", "note.odt")["lane"] == "llm_text")
    check("invoice names the case's tax year",
          classify.practice_invoice_year("Erstellung der Steuererklaerung 2025 ... Datum 03.2026") == 2025)

    print("\n=== spare photos get a photo check (id_photo) ===")
    n = classify.MAX_PHOTO_CHECKS
    spare = [f"p{i}.jpeg" for i in range(n + 1)]
    r = classify.decide_case_roles([{"filename": "sheet.jpeg", "size_bytes": 190_000}] +
                                   [{"filename": f, "size_bytes": 150_000 - i * 1000} for i, f in enumerate(spare)])
    by = {a["filename"]: a for a in r}
    check("largest photo is the form", by["sheet.jpeg"]["doc_type"] == "photo_form" and by["sheet.jpeg"]["role"] == "primary")
    check("next photos -> id_photo, supporting, extract",
          all(by[f]["doc_type"] == "id_photo" and by[f]["role"] == "supporting" and by[f]["extract"]
              for f in spare[:n]))
    check(f"bounded: at most {n} photo checks", not by[spare[n]].get("extract"))

    print(f"\n{'ALL CHECKS PASSED' if not failures else str(failures) + ' CHECK(S) FAILED'}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
