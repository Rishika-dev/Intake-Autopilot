"""Attachment classification for multi-file case grouping (2026-08-19).

Real intake is a case folder of ~40 files, not one form. This module decides, for
each attachment, three things from its filename + MIME (no file contents needed):

  * role      -- 'primary' (the tax form we extract), 'supporting' (filed, not
                 extracted), or 'ignore' (junk: never inserted, never filed).
  * doc_type  -- a short label for the dashboard (e1a, bescheid, honorar, ...).
  * extract   -- whether to send this file to the slow vision extractor. Only the
                 primary form is extracted; on the client's CPU-only box a single
                 vision pass is ~4-5 min, so extracting every attachment is a
                 non-starter (a 40-file case would take hours).

The rules are filename-driven because the client names the real tax forms
consistently ("E1a 2024 Muster.pdf", "L1k 2023.pdf", "2025 Steuererklärung.pdf").
Photos (WhatsApp Image / phone UUIDs) carry no name signal, so they default to
supporting; the n8n flow's *vision fallback* only reaches for them when a case
has NO named primary at all (see decide_primary / needs_vision_fallback).

This logic is intentionally simple and is mirrored 1:1 in the n8n "Classify
Attachments" Code node (JavaScript) -- keep the two in sync. Python is the source
of truth and the tested one (see the __main__ self-check at the bottom, run
against the real example corpus).
"""
import os
import re

# --- junk: dropped entirely, never filed -----------------------------------
# System detritus and non-document sidecars that show up inside real client
# folders (desktop.ini, Thumbs.db, LibreOffice lock files, contact cards).
_JUNK_EXACT = {"desktop.ini", "thumbs.db", ".ds_store"}
_JUNK_EXT = {".ini", ".db", ".lnk", ".tmp"}
_JUNK_PREFIXES = (".~lock", "~$")  # LibreOffice / MS Office lock+temp files

# --- office / working files: kept in the case folder, never extracted -------
# The client's own spreadsheets (EA_2025.xlsx / .ods) and draft letters. Valuable
# to file next to the output, useless to a vision model. (.vcf is handled
# separately below -- it IS extracted, deterministically, for tel/email.)
_OFFICE_EXT = {".xlsx", ".xls", ".ods", ".odt", ".docx", ".doc", ".rtf", ".zip", ".csv"}

# --- extractable media ------------------------------------------------------
_PDF_EXT = {".pdf"}
_IMAGE_EXT = {".jpg", ".jpeg", ".jfif", ".png", ".webp", ".heic"}

# --- doc_type keyword table (order matters: most specific first) ------------
# Each (regex, doc_type) is tested against the filename. The first hit wins.
# E1a MUST precede E1 ("E1a" contains "E1"); Steuererklärung before generic
# Erklärung. Keys are lowercased before matching.
_TYPE_RULES = [
    # Handwritten client intake questionnaire (sources hometown / household / fresh
    # contact -- see .scratch/perfect-extraction/02). It has no single reliable name
    # ("varies"), so this keyword set is only the fast path; a reviewer-tag fallback
    # catches the unnamed handwritten/photo copies. "Eingabe" is deliberately EXCLUDED
    # here -- it is its own doc_type (a cover/submission letter), not the questionnaire.
    (r"fragebogen|erfassungsbogen|erhebungsbogen|mandantenbogen|klientenbogen|checkliste|\bintake\b", "intake_sheet"),
    (r"\be1a\b|e1a", "e1a"),
    (r"\bl1k\b|l1k", "l1k"),
    (r"\be1\b|(?<![a-z0-9])e1(?![a-z0-9])", "e1"),
    # E9 = EU/EWR spouse-income certificate; sole source of the `spouse` field (02).
    (r"\be9\b|(?<![a-z0-9])e9(?![a-z0-9])", "e9"),
    (r"steuererkl|einkommensteuererkl|einkommensteuerek|erkl[äa]rung|einkomen", "steuererklaerung"),
    (r"bescheid", "bescheid"),
    (r"honorar", "honorar"),
    (r"fambh|familienbeih", "fambh"),
    (r"\bsvs\b|svs|sozialvers", "svs"),
    (r"\bgisa\b|gisa|gewerbe", "gisa"),
    (r"steuerkonto|kontoeinzel|steuerkto", "steuerkonto"),
    (r"wiederaufnahme", "wiederaufnahme"),
    (r"aufhebung", "aufhebung"),
    (r"beschwerde", "beschwerde"),
    (r"erg[äa]nzung|ersuchen|\bee\b|beantwortung", "ergaenzung"),
    (r"nachreichung", "nachreichung"),
    (r"antrag", "antrag"),
    (r"begr[üu]ndung", "begruendung"),
    (r"eingabe", "eingabe"),
    (r"zinsen", "zinsen"),
    (r"unterschr|untersc|signat", "signature"),
]

# Doc types that are the actual tax return -> the primary we extract.
_PRIMARY_TYPES = {"e1a", "e1", "l1k", "steuererklaerung"}

# Supporting doc types that still carry a key EA field and are extracted via the
# doc-type-aware lane: honorar -> income/provisionen, svs -> svs_sva, bescheid ->
# identity, e9 -> spouse/Familienstand, fambh -> children. Filed as 'supporting'
# (not the tax return) but flagged extract=True. Born-digital ones take the fast
# text lane (lane 3); scanned PDFs fall through to vision automatically. NB: E9 is
# also sometimes a JPEG photo -- those are NOT auto-extracted here (image branch
# stays extract=False to protect the CPU vision budget); a reviewer can reextract
# one by hand if the spouse is otherwise unknown. Mirror this set in the n8n
# "Classify Attachments" Code node when that flip is made live.
_LANE3_EXTRACT_TYPES = {"honorar", "svs", "bescheid", "e9", "fambh"}

# Deterministic (non-vision) extractables: parsed instantly on the backend, so
# every one is extracted regardless of the vision budget. vCard contact cards
# yield tel/email (their authoritative source per the field->source matrix).
_DETERMINISTIC_EXTRACT_TYPES = {"vcf"}


def is_extractable(doc_type) -> bool:
    """True if this doc_type is sent to extraction at all (primary, lane-3, or a
    deterministic parse like vCard)."""
    return (doc_type in _PRIMARY_TYPES or doc_type in _LANE3_EXTRACT_TYPES
            or doc_type in _DETERMINISTIC_EXTRACT_TYPES or doc_type == _ID_PHOTO_DOC_TYPE)


def _ext(filename: str) -> str:
    return os.path.splitext(filename or "")[1].lower()


# --- tax-year detection from the filename ----------------------------------
# The tax year lives in the filename for real client docs ("EA 2024.xlsx",
# "E1a 2023 Muster.pdf"), not the folder. Only 4-digit years in a plausible
# range are matched -- 2-digit forms (e.g. the "24" in a date "04.07.24") are
# deliberately NOT matched, since dates in filenames would produce false years.
# When a filename carries more than one year (rare for a single file, e.g. a
# "2021 - 2024" span), the FIRST is returned; genuinely ambiguous files get
# their year resolved later from document content, not here.
# Digit-boundaries, not \b: "_" and letters are word chars, so \b missed real
# names like "EA 2025_<name>.xlsx" / "E1a2024" and left the doc yearless.
_YEAR_RE = re.compile(r"(?<!\d)(20(?:1[5-9]|2[0-9]))(?!\d)")


def detect_year(filename: str) -> int | None:
    """Best-effort tax year parsed from the filename (2015-2029), or None."""
    m = _YEAR_RE.search(filename or "")
    return int(m.group(1)) if m else None


# A photo's filename year is its CAPTURE date ("WhatsApp Image 2026-08-19"),
# NOT the tax year the receipt/note is about -- so it must not bind the doc to a
# tax year. Named documents ("E1a 2023", "EA 2024.xlsx", "2022 Bescheid") do put
# the tax year in the name and are trusted. Photos defer to content/manual.
_YEAR_UNRELIABLE_TYPES = {"photo", "junk"}


def reliable_year(filename: str, doc_type: str) -> int | None:
    """detect_year, but suppressed for doc types whose filename year is a
    capture-date rather than the tax year (photos)."""
    if doc_type in _YEAR_UNRELIABLE_TYPES:
        return None
    return detect_year(filename)


def is_junk(filename: str) -> bool:
    name = (filename or "").strip().lower()
    if not name:
        return True
    base = os.path.basename(name)
    if base in _JUNK_EXACT:
        return True
    if base.startswith(_JUNK_PREFIXES):
        return True
    return _ext(base) in _JUNK_EXT


def detect_doc_type(filename: str) -> str:
    """Best-effort document type from the filename. Falls back to 'photo' for
    unnamed images (WhatsApp / phone UUIDs) and 'other' for everything else."""
    name = (filename or "").lower()
    if name.endswith(".vcf"):        # contact card -- extension is authoritative
        return "vcf"
    for pattern, doc_type in _TYPE_RULES:
        if re.search(pattern, name):
            return doc_type
    ext = _ext(name)
    if ext in _IMAGE_EXT:
        return "photo"
    if ext in _OFFICE_EXT:
        return "working_file"
    return "other"


def classify(filename: str, mime: str | None = None, size_bytes: int | None = None) -> dict:
    """Classify a single attachment.

    Returns {role, doc_type, extract}:
      role='ignore'     -> junk; drop it (don't insert, don't file)
      role='supporting' -> file it into the case folder; don't extract
      role='primary'    -> the tax form; extract it
      extract           -> convenience bool == (role=='primary')

    Note: a named PDF tax form is flagged primary here directly. Photos are only
    ever 'supporting' at this stage -- promoting a photo to primary is a
    case-level decision (see decide_case_roles) taken only when no named primary
    exists, so we never burn the vision model on 40 phone pics.
    """
    if is_junk(filename):
        return {"role": "ignore", "doc_type": "junk", "extract": False, "year": None}

    ext = _ext(filename)
    doc_type = detect_doc_type(filename)
    # Trusted tax year (None for photos -- their filename year is a capture date).
    year = reliable_year(filename, doc_type)

    # Contact cards (vCard): filed as supporting, but DO extract -- a deterministic
    # parse yields tel/email in microseconds, so unlike the slow vision lane there's
    # no CPU-budget reason to skip it. (year is None: a contact card has no tax year.)
    if ext == ".vcf" or doc_type == "vcf":
        return {"role": "supporting", "doc_type": "vcf", "extract": True, "year": year}

    # Office/working files: keep, never extract.
    if ext in _OFFICE_EXT:
        return {"role": "supporting", "doc_type": doc_type, "extract": False, "year": year}

    # Named tax-return PDFs are the primary.
    if ext in _PDF_EXT and doc_type in _PRIMARY_TYPES:
        return {"role": "primary", "doc_type": doc_type, "extract": True, "year": year}

    # Lane-3 extractables (honorar/svs/bescheid): filed as supporting, but sent to
    # the fast text lane because they authoritatively carry a key EA field.
    if ext in _PDF_EXT and doc_type in _LANE3_EXTRACT_TYPES:
        return {"role": "supporting", "doc_type": doc_type, "extract": True, "year": year}

    # Every other PDF (Antrag, Aufhebung, ...) and every image: supporting, no extract.
    if ext in _PDF_EXT or ext in _IMAGE_EXT:
        return {"role": "supporting", "doc_type": doc_type, "extract": False, "year": year}

    # Unknown / extensionless: keep it (file), don't extract. Byte-sniffing on
    # the backend still recovers a sane extension when filing.
    return {"role": "supporting", "doc_type": doc_type, "extract": False, "year": year}


# --- handwritten Stabinger paper intake form (content detection) ------------
# The practice's "Informationsblatt Steuererklärungen" (bilingual DE/RO) is filled
# in BY HAND and sent as a WhatsApp photo or a scanned PDF -- the client's own
# declared figures, and the anchor a reviewer reconciles a later E1a/Honorar
# against. Its FILENAME is a useless WhatsApp UUID, so it's detected from the
# PRINTED header/field wording in the text layer instead. This fires only for a
# text-bearing PDF (a scan with an OCR/text layer, or the born-digital template);
# a pure phone photo has no text layer and is caught by the image fallback in
# decide_case_roles. doc_type -> 'intake_form_paper', always read (even alongside a
# named tax form), and ranked LOW per field so an official doc wins while the
# handwritten value still surfaces as a cross-check/conflict.
_INTAKE_FORM_DOC_TYPE = "intake_form_paper"
_INTAKE_FORM_MARKERS = [
    r"informationsblatt\s+steuererkl",
    r"fi[sșşz]a\s+de\s+informa",                       # "Fișa de informații"
    r"stabinger\s+consulting",
    r"e-?\s?card-?\s?nummer\s+und\s+steuerjahr",
    r"honorare\s*=\s*jahres-?\s?gesamteinnahmen",
    r"svs\s*/\s*sva\s*=\s*jahres",
    r"familienbeihilfe\?.{0,40}familienstand\?",
    r"datenschutzhinweis\s+und\s+einwilligung",
    r"\+?\s?43\s*677\s*6349\s*1827",                   # the form's WhatsApp number
]
_INTAKE_FORM_RE = [re.compile(p, re.I | re.S) for p in _INTAKE_FORM_MARKERS]
_INTAKE_FORM_MIN_HITS = 2


def looks_like_intake_form(text: str | None) -> bool:
    """True when a document's text layer carries the printed wording of the
    Stabinger paper intake form. Requires >= _INTAKE_FORM_MIN_HITS distinct markers
    so a document that merely mentions e.g. "Honorare" is never misread as the form."""
    if not text:
        return False
    return sum(1 for rx in _INTAKE_FORM_RE if rx.search(text)) >= _INTAKE_FORM_MIN_HITS


# The practice's OWN fee invoice to the client ("Honorarnote ... Erstellung der
# Einkommensteuererklärung ... Gesamtbetrag 180,00 €"). Its filename says
# "Honorarnote", so the filename rules call it 'honorar' -- the top-authority
# source for honorare -- and the practice's fee then overwrote the client's real
# income (real-folder check 2026-10-26). Recognised by content: the practice name
# AND an invoice total AND a tax-return-preparation term, all three required.
_PRACTICE_INVOICE_DOC_TYPE = "practice_invoice"
_INTAKE_NOTE_DOC_TYPE = "intake_note"
_PRACTICE_INVOICE_RE = [re.compile(p, re.I | re.S) for p in (
    r"stabinger",
    r"honorarnote|gesamtbetrag|rechnungsbetrag",
    r"steuererkl|einkommensteuer|arbeitnehmerveranlagung",
)]


# A photo/scan promoted by the vision fallback is read with the handwritten
# intake-form prompt, whatever it shows. Vision also transcribes its PRINTED
# title; when that title names a known official form, the doc is re-typed so the
# per-type field allowlist applies. Real case (2026-10-26): a WhatsApp photo of
# an E9 had its home-country income read as Austrian `honorare`. Only types whose
# allowlist keeps the intake prompt's fields honest are listed.
_TITLE_RULES = [
    (r"bescheinigung\s+eu\s*/\s*ewr|certification\s+eu\s*/\s*eea", "e9"),
    (r"familienbeihilfe", "fambh"),
    (r"einkommensteuerbescheid|\bbescheid\b", "bescheid"),
    (r"sozialversicherung\s+der\s+selbst|\bsvs\b", "svs"),
]
_TITLE_RE = [(re.compile(p, re.I), t) for p, t in _TITLE_RULES]


def doc_type_from_title(title) -> str | None:
    """Known official doc type named by a document's printed title, or None
    (unknown title, the intake form itself, or no title read)."""
    if not isinstance(title, str) or not title.strip():
        return None
    for rx, t in _TITLE_RE:
        if rx.search(title):
            return t
    return None


def looks_like_practice_invoice(text: str | None) -> bool:
    """True when the text layer is the practice's own invoice for preparing the
    return -- never a source of the client's figures."""
    if not text:
        return False
    return all(rx.search(text) for rx in _PRACTICE_INVOICE_RE)


# The year the practice's invoice bills for ("Erstellung der Steuererklärung 2025")
# -- a reliable tax year for the whole case when nothing else carries one (the
# invoice's own date is the following year, so only a year NEXT TO the return
# wording counts).
_INVOICE_YEAR_RE = re.compile(
    r"(einkommensteuererkl\w*|steuererkl\w*|arbeitnehmerveranlagung|veranlagung)\D{0,25}(20[12]\d)(?!\d)",
    re.I)


def practice_invoice_year(text: str | None) -> int | None:
    m = _INVOICE_YEAR_RE.search(text or "")
    return int(m.group(2)) if m else None


# The intake answers TYPED into an .odt/.docx (by the office from a call/WhatsApp,
# or by the client): same fields as the paper form, in free text. Real case
# 2026-10-26: a client's only source of figures was such a note, filed as a
# never-read working file. Needs >= _INTAKE_NOTE_MIN_HITS distinct field words so
# an ordinary letter that mentions "Honorar" once is not taken for it.
_INTAKE_NOTE_EXT = {".odt", ".docx"}
_INTAKE_NOTE_RE = [re.compile(p, re.I) for p in (
    r"honorar", r"\bsvs\b|\bsva\b|sozialvers", r"\bwko\b|wirtschaftskammer",
    r"familienbeihilfe|aloca[tț]i", r"\bkinder?\b|\bcopii\b", r"e-?\s?card", r"\badresse\b|\badres[aă]\b",
    r"\bfahrt|transport", r"provision|comision",   # typed notes mix German and Romanian
)]
_INTAKE_NOTE_MIN_HITS = 4


def looks_like_intake_note(filename: str, text: str | None) -> bool:
    if _ext(filename or "") not in _INTAKE_NOTE_EXT or not text:
        return False
    return sum(1 for rx in _INTAKE_NOTE_RE if rx.search(text)) >= _INTAKE_NOTE_MIN_HITS


# A handwritten paper form photographed ALONGSIDE a named tax PDF can't be
# detected cheaply (a photo has no text layer). Promoting the largest such image
# to an extra vision read closes that gap, but costs one more ~CPU-minutes vision
# pass per case -- so it's OFF by default and the lone-photo case (the form sent on
# its own, which is how the form itself instructs the client to send it) is covered
# by the no-primary fallback below. The client box can flip this on if forms often
# arrive bundled with other documents.
PROMOTE_EXTRA_IMAGE_WITH_PRIMARY = False

# Photos left over after role assignment are often the client's ID card / e-card
# (sent with the form: the e-card number and home address are on them, not on the
# form). Each is sent as an id_photo: the ai-service first asks what the photo shows
# and only an ID / e-card gets the identity read (the merge only takes e-card number
# + home address from it); a handwritten note is read as an intake form instead, and
# anything else (receipt, letter) is put back as a plain photo. Picking by size alone
# read a form and a receipt as IDs in a real case (2026-10-29), so more photos are
# checked than read. Bounded per case for the vision budget.
_ID_PHOTO_DOC_TYPE = "id_photo"
MAX_PHOTO_CHECKS = 6

# Largest supporting image is the fallback extraction target when a case has no
# named primary (a pure photo dump). Small images are almost always signatures
# or logos, not a full form, so a minimum size guards against extracting those.
_FALLBACK_MIN_IMAGE_BYTES = 40 * 1024


def decide_case_roles(attachments: list[dict]) -> list[dict]:
    """Given a case's attachments (each a dict with at least 'filename', and
    optionally 'mime'/'size_bytes'), return them enriched with role/doc_type/
    extract, applying the case-level vision fallback.

    Steps:
      1. classify each file individually.
      2. drop 'ignore' (junk).
      3. if at least one named primary exists -> done (extract those).
      4. else (no named form, e.g. WhatsApp photo dump) -> promote the single
         largest image above _FALLBACK_MIN_IMAGE_BYTES to primary+extract, so
         the case still yields one extraction instead of zero. Bounded to ONE
         file to protect the CPU-only vision budget.
    """
    kept = []
    for att in attachments:
        verdict = classify(att.get("filename", ""), att.get("mime"), att.get("size_bytes"))
        if verdict["role"] == "ignore":
            continue
        enriched = dict(att)
        enriched.update(verdict)
        # The handwritten Stabinger intake form, recognised by its printed wording in
        # the text layer (att['text'], supplied by extractors.sniff_text). It is ALWAYS
        # read -- even when the case also carries a named tax PDF -- because it is the
        # client's own declared figures and the anchor for resolving later conflicts.
        # year stays None: the tax year is HANDWRITTEN (field 1), so it comes from the
        # vision read's tax_year, not the printed text layer or the photo's filename.
        # Checked FIRST: the practice's own invoice shares the letterhead with the
        # intake form and must never be read as either a form or an income source.
        if looks_like_practice_invoice(att.get("text")):
            enriched.update({"role": "supporting", "doc_type": _PRACTICE_INVOICE_DOC_TYPE,
                             "extract": False,
                             "year": enriched.get("year") or practice_invoice_year(att.get("text"))})
        elif looks_like_intake_note(att.get("filename", ""), att.get("text")):
            # read like the paper form (client-declared, ranked low); the tax year
            # comes from the note's text or the case (e.g. the invoice's year)
            enriched.update({"role": "primary", "doc_type": _INTAKE_NOTE_DOC_TYPE,
                             "extract": True, "year": enriched.get("year")})
        elif looks_like_intake_form(att.get("text")):
            enriched.update({"role": "primary", "doc_type": _INTAKE_FORM_DOC_TYPE,
                             "extract": True, "year": None})
        kept.append(enriched)

    if any(a["role"] == "primary" for a in kept):
        # Optional (off by default): a handwritten form PHOTOGRAPHED alongside a named
        # primary has no text layer to detect, so promote the largest weak image to one
        # extra vision read. Bounded to a single image to protect the vision budget.
        if PROMOTE_EXTRA_IMAGE_WITH_PRIMARY:
            spare = [
                a for a in kept
                if not a.get("extract")
                and _ext(a.get("filename", "")) in _IMAGE_EXT
                and a.get("doc_type") in (None, "photo", "other")
                and (a.get("size_bytes") or 0) >= _FALLBACK_MIN_IMAGE_BYTES
            ]
            if spare:
                best = max(spare, key=lambda a: a.get("size_bytes") or 0)
                best["role"] = "primary"
                best["extract"] = True
                best["doc_type"] = "photo_form"
        return _mark_id_photos(kept)

    # Vision fallback (no named tax form in this case, e.g. a WhatsApp photo dump
    # or a lone unnamed scan). Promote ONE file so the case still yields an
    # extraction instead of zero. Prefer the largest sufficiently-big image;
    # failing that, the largest PDF. Bounded to a single file to protect the
    # CPU-only vision budget (~4-5 min/extraction on the client box).
    images = [
        a for a in kept
        if _ext(a.get("filename", "")) in _IMAGE_EXT
        and (a.get("size_bytes") or 0) >= _FALLBACK_MIN_IMAGE_BYTES
    ]
    pdfs = [a for a in kept if _ext(a.get("filename", "")) in _PDF_EXT
            and a.get("doc_type") != _PRACTICE_INVOICE_DOC_TYPE]
    pool = images or pdfs
    if pool:
        best = max(pool, key=lambda a: a.get("size_bytes") or 0)
        best["role"] = "primary"
        best["extract"] = True
        if best.get("doc_type") in (None, "photo", "other"):
            best["doc_type"] = "photo_form" if best in images else "pdf_form"
    return _mark_id_photos(kept)


def _mark_id_photos(kept: list[dict]) -> list[dict]:
    """Send up to MAX_PHOTO_CHECKS spare photos for a photo check (stay supporting)."""
    spare = [
        a for a in kept
        if not a.get("extract")
        and _ext(a.get("filename", "")) in _IMAGE_EXT
        and a.get("doc_type") in (None, "photo", "other")
        and (a.get("size_bytes") or 0) >= 20 * 1024
    ]
    for a in sorted(spare, key=lambda a: a.get("size_bytes") or 0, reverse=True)[:MAX_PHOTO_CHECKS]:
        a["doc_type"] = _ID_PHOTO_DOC_TYPE
        a["extract"] = True
    return kept


if __name__ == "__main__":
    # Self-check against the real example corpus. Point CORPUS at the client's
    # example folder to see how every real filename buckets. No PII is printed --
    # only filenames, which are document-type labels, and aggregate counts.
    import sys
    from collections import Counter

    corpus = sys.argv[1] if len(sys.argv) > 1 else None
    if not corpus:
        print("usage: python classify.py <folder-of-example-cases>")
        raise SystemExit(0)

    role_counts = Counter()
    type_counts = Counter()
    year_counts = Counter()
    year_hit = year_miss = 0
    primaries_per_case = {}
    for root, _dirs, files in os.walk(corpus):
        case = os.path.relpath(root, corpus)
        for f in files:
            v = classify(f)
            role_counts[v["role"]] += 1
            type_counts[v["doc_type"]] += 1
            if v["role"] == "ignore":
                continue
            if v.get("year"):
                year_counts[v["year"]] += 1
                year_hit += 1
            else:
                year_miss += 1

            if v["role"] == "primary":
                primaries_per_case.setdefault(case, 0)
                primaries_per_case[case] += 1

    print("=== roles ===")
    for r, n in role_counts.most_common():
        print(f"{n:5d}  {r}")
    print("=== doc types ===")
    for t, n in type_counts.most_common():
        print(f"{n:5d}  {t}")
    print("=== years parsed from filename (non-junk files) ===")
    for y, n in sorted(year_counts.items()):
        print(f"{n:5d}  {y}")
    total_ny = year_hit + year_miss
    pct = (100 * year_hit / total_ny) if total_ny else 0
    print(f"  year present: {year_hit}/{total_ny} ({pct:.0f}%), no-year (needs content fallback): {year_miss}")
    print("=== cases with ZERO named primary (would use vision fallback) ===")
    all_cases = {os.path.relpath(r, corpus) for r, _d, fs in os.walk(corpus) if fs}
    zero = sorted(c for c in all_cases if primaries_per_case.get(c, 0) == 0 and c != ".")
    for c in zero:
        print(f"   {c}")
    print(f"\n{len(all_cases)} case-dirs, {len(zero)} would need vision fallback")
