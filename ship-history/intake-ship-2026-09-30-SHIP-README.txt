Intake Autopilot -- code drop -- 2026-09-30
============================================

WHAT THIS FIXES
----------------
StNr (Steuernummer) was, in some cases, coming out of extraction as the
client's SVNR/e-card number instead of their real tax number. Two
independent root causes on two different lanes, both fixed:

1. backend/extractors.py (_extract_e1_identity)
   On the E1/E1a PDF form, BMF reuses the same AcroForm widget field name
   ("SteuernummerInfo") for BOTH the real Steuernummer boxes and the
   10-digit SVNR/e-card boxes on the same page. The old code matched by
   bare widget name and took whichever same-named widget it hit first with
   a non-empty value -- if the real Steuernummer boxes were blank, it
   silently returned the SVNR instead.
   Fix: disambiguate by the printed row label next to each widget instance
   (skip anything labelled Sozialversicherungsnummer/e-card/SVNR), and
   reject any value that has the unambiguous 10-bare-digit SVNR shape with
   no Steuernummer-style separator.

2. ai-service/main.py (_reject_svnr_shaped_stnr)
   The same confusion could happen independently on the LLM lanes (text
   and vision) for E1 copies that have NO AcroForm widgets at all (pure
   text/scan). A bare 10-digit "stnr" reading -- indistinguishable from an
   SVNR -- is now downgraded to "Not Found" instead of accepted, on both
   /extract and /extract_text. (Also broadened the stnr/VNR prompt hints
   so the model is told explicitly not to read VNR/Versicherungsnummer-
   labeled fields as the Steuernummer, and not to return a printed label
   as if it were the value.)

3. backend/main.py (_extract_primaries)
   Separate bug found while verifying #1/#2: POST /api/forms/{id}/reextract
   was INSERTing a new extractions row instead of replacing the old one, so
   a re-extracted form could end up with both its stale and fresh reads on
   record -- capable of raising a false conflict against itself in the
   per-year merge, with no guaranteed tie-break toward the fresh value.
   Fix: DELETE any existing extractions row for that form_id before
   inserting the new one, so a form's extraction is idempotent.

Also included (unrelated smaller accuracy fixes, same file, same session):
prompt hints for "honorare" (sum across multiple stacked monthly
Honorarnoten instead of reading only one page's total) and
"sonstiger_aufwand" (must be a single itemized line, never the printed
sum/total of all expenses).

FILES IN THIS DROP
-------------------
backend/extractors.py
backend/main.py
ai-service/main.py

These are FULL FILES, not diffs -- copy each one over the matching file in
place. No new dependencies, no requirements.txt/Dockerfile change, no
schema change (database/schema.sql is NOT part of this drop and does not
need to be touched or reapplied).

DEPLOY STEPS (client PC)
-------------------------
1. Do NOT touch docker-compose.yml or docker-compose.override.yml on the
   client box -- both are customized for his GPU setup and are not part of
   this drop.
2. Copy the 3 files above into the existing deploy folder, overwriting the
   matching files in place:
     <deploy folder>\backend\extractors.py
     <deploy folder>\backend\main.py
     <deploy folder>\ai-service\main.py
3. Restart just the two affected containers (bind-mounted -- no rebuild
   needed):
     docker compose restart backend ai-service
4. Verify no MOCK MODE line:
     docker logs --tail 30 intake-backend
5. Optional but recommended: any client whose StNr field was already
   extracted before this fix may still be showing the wrong (SVNR-shaped)
   value in their per-year record. There is no automatic re-check -- for
   any such client, re-run extraction on the affected form
   (POST /api/forms/{id}/reextract) and then re-run the year merge
   (POST /api/tax-years/{id}/rebuild) so the record picks up the corrected
   read. This does not need to be done for every client -- only ones where
   the StNr field looks wrong in the reviewer UI.

ROLLBACK
--------
Keep a copy of the 3 files as they exist on the client box before
overwriting (e.g. rename each to *.pre-2026-09-30 next to it). If anything
regresses, restore those 3 and `docker compose restart backend ai-service`.
