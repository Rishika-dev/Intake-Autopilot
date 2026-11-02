Intake Autopilot -- code drop -- 2026-10-07  (Fragebogen / client questionnaire)
=================================================================================
Builds on 2026-10-01c (must already be on the box). ai-service unchanged.

FILES
    backend/main.py                   full file (replaces)
    backend/static/fragebogen.html    NEW  - the questionnaire
    backend/static/jspdf.umd.min.js   NEW  - PDF library for the questionnaire (offline copy)
    database/schema.sql               full file; adds table questionnaire_invites
                                      (backend also creates it by itself at start)
    patch_dashboard.ps1               updates 3 dashboard files only if they are the expected
                                      version (backs up first), adds 2 new files
    dashboard/new, dashboard/old      used by the script
No dependency, template or compose change. Do NOT touch docker-compose*.yml.

WHAT IT ADDS
------------
1. Questionnaire in the office: client page -> "Fragebogen 2025 öffnen".
   Answers (name, e-card, StNr, address, hometown, marital status, spouse,
   children, km, trips ...) go straight into that year's record, no AI.
   A copy (Fragebogen_<year>.html + .json) is filed in the client folder.
2. Questionnaire for the client at home: client page -> "Link für Klientin 2025"
   copies a personal link (https://steuermappe-fragebogen.vercel.app/?r=SM-XXXXXX&y=2025).
   The website stores and sends nothing; the client's phone makes a PDF and she
   sends it by WhatsApp/e-mail. Normal intake recognises that PDF, reads the
   answers exactly (no AI), files it under the right client by its SM- number
   and marks the link "zurück".
3. Tracking: home page -> "Fragebogen-Links" lists every link: open / returned.
4. Fewer extractions: E9, FamBH, Bescheid and contact cards are skipped when the
   questionnaire already answered what they would give. Money documents
   (Honorar, SVS, E1/E1a) are always extracted. "Re-extract" always runs.

DEPLOY -- see the chat for the exact PowerShell lines.
Backups: *.pre-2026-10-07 next to every replaced/edited file.
ROLLBACK: rename the *.pre-2026-10-07 files back, delete backend\static\fragebogen.html,
  dashboard\src\app\clients\[id]\FragebogenInvite.tsx and dashboard\src\app\fragebogen\,
  docker compose restart backend. (The new table can stay; nothing else uses it.)
