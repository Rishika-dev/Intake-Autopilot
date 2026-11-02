Intake Autopilot -- code drop -- 2026-10-26c  (photo check before reading spare photos)
=======================================================================================
Builds on 2026-10-26b (applied 2026-10-26). apply_update.ps1 checks every file is
exactly the version from that drop. No schema, dependency, Docker, compose or
dashboard change.

FILES  (under files\, manifest.json = SHA-256 per file)
    ai-service/main.py                      short "what does this photo show?" check
    backend/main.py                         files the photo by the check's answer
    backend/classify.py                     up to 6 spare photos checked per case (was 2 read)
    scripts/validate_handwritten_intake.py  dev check (updated)

WHAT IT CHANGES
  10-26b read the two LARGEST leftover photos of a case as ID / e-card photos, whatever
  they showed. On an example folder those were a letter and a receipt (nothing wrong
  reached the EA -- the checks dropped it -- but a handwritten note in the same folder
  was never read). Now each leftover photo (max 6 per case) first gets one short check:
   - ID card / e-card / passport  -> ID read as before (e-card number + Heimatort only).
   - handwritten note or form      -> read like the handwritten intake sheet. Its figures
                                      rank below every official document, so a different
                                      value only shows as "prüfen", never replaces it.
                                      A hand-filled official form (e.g. E9) is re-typed by
                                      its title, as before.
   - anything else (receipt, letter, screenshot ...) -> filed as a plain photo, not read.

Tested on this Mac:
  - The new client's 3 files (client 10 on your PC): ID photo still recognised,
    E-Card + Heimatort filled, all other lines as before.
  - Example folder with 6 photos: 1 handwritten note now read -- E-Card, Familienstand
    and Kinder filled, all 3 match the office's own EA sheet; 1 hand-filled E9 re-typed
    as E9; 3 printed letters filed without a read. EA lines unchanged (100%).

DEPLOY  (PowerShell)
 1. Unzip. In the folder with apply_update.ps1:
      powershell -ExecutionPolicy Bypass -File .\apply_update.ps1
      -> "Done: 4 file(s) updated". If it says STOPPED, nothing was changed: send the list.
 2. cd "C:\Users\Sebastian\Desktop\intake\intake-autopilot-mac-handoff-2026-07-21 2"
    docker compose restart backend ai-service
    docker logs --tail 5 intake-backend      -> no "MOCK MODE"
 3. Nothing to re-read: it applies to every NEW upload / WhatsApp case from now on.

ROLLBACK
  Rename the *.pre-2026-10-26c copies back, then
  docker compose restart backend ai-service.
