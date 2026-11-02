Intake Autopilot -- code drop -- 2026-10-01c
=============================================
Builds on 2026-10-01 and 2026-10-01b (both must be on the box; 10-01c replaces
10-01b's two files, so 10-01b itself can be skipped if not yet deployed).

FILES
    backend/main.py         full file
    ai-service/main.py      full file
    patch_dashboard.ps1     in-place edit of dashboard page.tsx (backs it up first)
    verify_one.py           test script (now also reports Reisekosten + the cell check)
No template, schema, dependency or compose change.

WHAT THIS FIXES
----------------
1. E1a amounts landed on the wrong rows (income got the Reisekosten figure,
   Sonstiger Aufwand got the "Summe der Aufwendungen" total, Provisionen and
   Abschreibung got Kennzahl codes). Cause: FinanzOnline "E 1a-PDF" printouts
   carry labels and Kennzahl codes as text, but the amounts are drawn as
   shapes, so only a whole-page image read was possible, and it shifts rows.
   NEW: for such an E1a the ai-service finds each Kennzahl's row from the text
   layer, cuts out that row's amount cell, decides "blank" from the pixels (no
   model call), and has the model read ONLY that one cell. A figure can no
   longer move to another line. The printed "Summe der Aufwendungen" and
   "Gewinn/Verlust" rows are read too: the record notes whether the expenses
   add up to the Summe and income - Summe = Gewinn.
   Tested on the 2023 reference case: all 7 money lines correct, cross-check
   passed, ~14 s per form on the Mac (faster on the GPU).
   Scanned E1a (no text layer at all) are NOT covered by this; they still use
   the whole-page read with the existing guards.

2. Reisekosten 9160 printed on the E1a is now read (field "reisekosten").
   It is used for the sheet only when no Entfernung/Fahrten are entered;
   with km + trips the computed figure still wins (unchanged).

3. Newer-document rule, refined: when the newer E1a was read cell-by-cell, a
   line that is blank on it stays blank -- the older copy may no longer fill it
   back in. (Older copies still fill gaps when the newer one was a scan.)

DEPLOY (PowerShell, in the deploy folder) -- see the chat for exact lines.
Backups: *.pre-2026-10-01c next to each replaced file.
ROLLBACK: rename the *.pre-2026-10-01c files back, docker compose restart backend ai-service.
