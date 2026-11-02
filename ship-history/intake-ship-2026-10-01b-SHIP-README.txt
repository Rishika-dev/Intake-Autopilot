Intake Autopilot -- code drop -- 2026-10-01b
=============================================
Builds on the 2026-10-01 drop (deploy that first). Two files only:
    backend/main.py
    ai-service/main.py
No template, dashboard, schema, dependency or compose change.

WHAT THIS FIXES
----------------
1. Steuernummer copied from the prompt example: the old hint contained a
   sample StNr, and when the model couldn't read the real one it returned the
   sample. The sample is removed, and a placeholder-shaped StNr is now rejected.

2. Versicherungsnummer (e-card) was never requested from E1/E1a. It is now
   requested and must be exactly 10 digits, or it is dropped.

3. A Kennzahl code (e.g. 9100) read as an amount is now rejected on all
   money fields.

4. False "conflict" on Leistungserloese: two docs with the same amount
   written differently (e.g. "10.136,00" vs "10136") no longer count as
   disagreeing.

5. NEWER DOCUMENT WINS. When a year has two copies of the same form (e.g. the
   original E1a and the corrected one sent with an Ergaenzungsersuchen answer),
   the newer one is used. "Newer" = the PDF's own creation date (else its
   modification date, else when we received it). A differing value from the
   older copy is no longer shown as a conflict. It is kept in the record as
   "superseded" for reference. If the newer copy is blank for a field, the
   older copy's value still fills it. Conflicts between DIFFERENT document
   types (e.g. Honorarnote vs E1a) are still shown as before.

DEPLOY (PowerShell, in the deploy folder)
------------------------------------------
0. Do NOT touch docker-compose.yml or docker-compose.override.yml.
1. Back up:   backend\main.py    -> backend\main.py.pre-2026-10-01b
              ai-service\main.py -> ai-service\main.py.pre-2026-10-01b
2. Copy the two files over.
3. docker compose restart backend ai-service
4. docker logs --tail 30 intake-backend   (must show no MOCK MODE line)

TEST: re-extract the year's forms with verify_one.py (already on the box from
the 10-01 drop). It prints only yes/no, lanes and sources -- no values.

ROLLBACK: rename the *.pre-2026-10-01b files back, then restart as in step 3.
