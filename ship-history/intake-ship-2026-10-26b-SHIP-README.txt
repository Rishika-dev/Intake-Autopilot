Intake Autopilot -- code drop -- 2026-10-26b  (handwritten-sheet reading fixes)
==============================================================================
Builds on 2026-10-26 (applied this morning). apply_update.ps1 checks every file is
exactly the version from that drop. No schema, dependency, Docker or compose change.

FILES  (under files\, manifest.json = SHA-256 per file)
    ai-service/main.py                      handwritten-sheet prompt + ID/e-card photo read
    backend/main.py, classify.py            calculations, children, ID-photo merge rules
    dashboard/src/app/clients/[id]/page.tsx chip text for a re-calculated figure
    dashboard/src/app/reviewer/page.tsx     label for the new document type
    scripts/validate_handwritten_intake.py  dev check (updated)
    scripts/validate_calc_merge.py          NEW dev check (runs inside the backend container)

WHAT IT FIXES  (found on the new client's handwritten sheet, 2026-10-26)
 1. A calculation read with digits missing ("506 x 4 = 2.02" for a written 2.024):
    the re-calculated figure is used, still marked "prüfen" for the reviewer.
    A count before the calculation ("12 Monate — 506 x 4") no longer breaks the check.
 2. Agency commission (Provision/Kommission) and transport/travel costs are now read
    as two separate lines: Provisionen 9190 and Reisekosten 9160.
 3. The Steuernummer is read from the sheet (with a short second look if the main read
    misses it; only a 9-digit answer is accepted, so nothing is invented).
 4. Kinder only takes a number or "keine" -- an answer like "nicht bekommen"
    (Familienbeihilfe) no longer lands in Kinder.
 5. A photo of the ID card / e-card sent with the form is now read: e-card number and
    home address (Heimatort) only. Shown as "Ausweis/E-Card (Foto)". Max 2 per case.
 6. Free sheets: an Austrian address written over several lines stays together.

Tested on this Mac with the new client's 3 files: every line matches the sheet
(Leistungserlöse 15.600, SV 2.024, Provisionen 360, Reisekosten 1.320, WKO 80, StNr,
e-card, Heimatort). Accuracy benchmark on the office's example folders: unchanged (69%),
no regressions.

DEPLOY  (PowerShell)
 1. Unzip. In the folder with apply_update.ps1:
      powershell -ExecutionPolicy Bypass -File .\apply_update.ps1
      -> "Done: 7 file(s) updated". If it says STOPPED, nothing was changed: send the list.
 2. cd "C:\Users\Sebastian\Desktop\intake\intake-autopilot-mac-handoff-2026-07-21 2"
    docker compose restart backend ai-service
    docker logs --tail 5 intake-backend      -> no "MOCK MODE"
 3. Dashboard picks the changes up by itself (npm run dev).

RE-READ THE NEW CLIENT (client 10, case 10) WITH THE NEW CODE
    docker exec intake-db psql -U admin -d intake -c "UPDATE forms SET doc_type='id_photo' WHERE case_id=10 AND doc_type='photo' RETURNING id;"
    Invoke-RestMethod -Method Post http://localhost:8080/api/forms/259/reextract
    Invoke-RestMethod -Method Post http://localhost:8080/api/forms/261/reextract
  (if the UPDATE returns a different id than 261, use that id in the last line)
  Wait ~1 minute, then open client 10 / 2025 in the dashboard.

ROLLBACK
  Rename the *.pre-2026-10-26b copies back, delete scripts\validate_calc_merge.py,
  docker compose restart backend ai-service.
