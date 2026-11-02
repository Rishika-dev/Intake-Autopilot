Intake Autopilot -- code drop -- 2026-10-01
============================================
Builds on the 2026-09-30 drop (StNr/SVNR fix). Deploy that one first if it
isn't on the box yet -- backend/extractors.py is unchanged and not included.

WHAT THIS FIXES
----------------
On one test client the generated EA came out at about -10.400 EUR Einkuenfte
instead of about +4.000 EUR. There were four separate causes:

1. Vision lane (ai-service/main.py): on a scanned E1a, BLANK Kennzahl rows were
   filled with other rows' figures (SV got the income figure; Kleinmaterial/
   Provisionen/Abschreibung got the Reisekosten, expense-sum and Gewinn rows).
   - The vision prompt now says: a blank row is "Not Found", never shift a
     figure from a neighbouring row, never use the Summe/Gewinn/Grundfreibetrag/
     Einkuenfte rows, and never use the same figure for two fields.
   - Tighter hints for svs_sva / kleinmaterial / abschreibung.
   - New deterministic check (_reject_duplicate_money) on BOTH the vision and
     text lanes: an expense equal to the income, equal to another expense,
     equal to the sum of the others, or negative is set to "Not Found".
     The reviewer then fills it, instead of the sheet silently
     double-counting.

2. Text lane (ai-service/main.py): on an E1a whose text layer has the labels
   but NO amounts, the LLM made up round figures (100000/10000/...). Every
   money value the text lane returns must now actually appear among the
   numbers printed in that text, or it is dropped. (Exception: Honorar notes,
   where honorare is legitimately a sum across pages.)

3. Lane routing (backend/main.py): an E1a whose text layer contains no euro
   amounts at all now goes to VISION instead of the text lane.

4. Grundfreibetrag (backend/templates/EA_template.xlsx + dashboard): was
   =C20*0.15, which gives a NEGATIVE allowance on a loss. Now =MAX(0,C20*0.15)
   in the Excel template and Math.max(0, ...) in the dashboard live preview.

Also in backend/main.py (tested on the Mac, not shipped before): children-count
fallback. When no FamBH notice or intake sheet gives "children", the number of
L1k forms filed for that year is used (one L1k per child). This is a database
row count only; it never opens a document.

What this does NOT fix: a weak vision model still misreads some scans. Those
fields now come out blank or flagged as conflicts instead of silently wrong.
A reviewer still has to fill them.

FILES IN THIS DROP (full files -- copy over the matching file in place)
-----------------------------------------------------------------------
backend/main.py
backend/templates/EA_template.xlsx
ai-service/main.py
scripts/build_ea_template.py              (source of the template; reference only)
dashboard/src/app/clients/[id]/page.tsx   (see note in step 2)
verify_one.py                             (test script -- NOT copied into the app)

No new dependencies, no requirements.txt/Dockerfile change, no schema change.

DEPLOY STEPS (client PC)
-------------------------
0. Do NOT touch docker-compose.yml or docker-compose.override.yml.

1. Back up the files you are about to overwrite, next to the originals:
     backend\main.py                    -> backend\main.py.pre-2026-10-01
     backend\templates\EA_template.xlsx -> backend\templates\EA_template.xlsx.pre-2026-10-01
     ai-service\main.py                 -> ai-service\main.py.pre-2026-10-01
     dashboard\src\app\clients\[id]\page.tsx -> page.tsx.pre-2026-10-01

2. Copy the files over the matching paths in the deploy folder.
   Dashboard: if you are unsure whether the dashboard on the box matches the
   Mac's, DON'T copy page.tsx. Make the one-line edit in it instead:
       const gfb = gewinn * 0.15;
   becomes
       const gfb = Math.max(0, gewinn * 0.15);

3. Restart the two containers (bind-mounted, no rebuild needed):
     docker compose restart backend ai-service
   If the dashboard is running (npm run dev), it hot-reloads by itself.

4. Check that the log has no MOCK MODE line:
     docker logs --tail 30 intake-backend

TEST ON ONE FILE (prints only yes/no, lanes and sources -- no values)
---------------------------------------------------------------------
Pick one E1a form id from the dashboard (the number in the document's URL or
list), then from the folder holding verify_one.py:
     docker cp verify_one.py intake-backend:/tmp/verify_one.py
     docker exec intake-backend python /tmp/verify_one.py <FORM_ID>

It re-extracts that one form, waits for it to finish, rebuilds its tax year
and prints:
  - which lane was used (deterministic / llm_text / vision) and how long it took
  - which money fields were found (True/False)
  - "any two money values identical" / "any negative money value". Both
    should be False now; the new check removes these cases.
  - for the year record: each field present/absent, its source doc type, conflict flag
Paste that output back. It contains no client data.

ROLLBACK
--------
Rename the *.pre-2026-10-01 files back over the new ones, then:
     docker compose restart backend ai-service
