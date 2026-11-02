Intake Autopilot -- code drop -- 2026-10-26  (Josh roadmap phases 1-3 + extraction fixes)
=========================================================================================
Builds on 2026-10-07 (must already be on the box). Built against the transfer zip the
office sent on 2026-10-26; apply_update.ps1 checks every file is that exact version.
No dependency, Docker image, template or compose change. Do NOT touch docker-compose*.yml.

FILES  (all under files\, copied by apply_update.ps1; manifest.json = SHA-256 per file)
    backend/main.py, classify.py, extractors.py      full files (replace)
    backend/static/fragebogen.html                   questionnaire now carries "dringend"
    ai-service/main.py                               full file (replace)
    database/schema.sql                              adds tax_years.dringend/approved_at/approved_by
    dashboard/src/app/page.tsx                       client list: Dringend first, last info
    dashboard/src/app/clients/[id]/page.tsx          Dringend toggle, Freigeben, upload, chips
    dashboard/src/app/fragebogen/page.tsx            upload button
    dashboard/src/app/reviewer/page.tsx              new doc-type labels
    dashboard/src/app/UploadToCase.tsx               NEW - upload button
    eval/ea_benchmark/run.py, helper.py, README.md   NEW - accuracy benchmark
    eval/.gitignore, scripts/validate_*.py           dev checks (not needed to run)

WHAT IT ADDS
------------
1. Handwritten paper form (Stabinger DE/RO form) is recognised by its printed text and
   always read by the vision model -- including the tax year. Ranked LOW: an official
   E1a/Honorar/SVS wins; the hand figure shows as a conflict to check.
2. Client list: clients marked "Dringend" come first (red), then newest information.
   Questionnaire answers with an urgent flag set Dringend automatically; the office can
   set/clear it on the client page. Clearing is office-only.
3. "Freigeben" (approve) button on a year after "Generate EA". Regenerating the sheet
   resets it to not-approved.
4. Upload button: "Fragebogen/Formular hochladen" (Fragebogen-Links page) and
   "Formular hochladen" (client page). Takes PDF, photo, .odt, .docx -- goes through the
   same intake as an e-mail. On the client page it is filed to THAT client.
5. Extraction fixes found on the office's own example folders:
   - The office's own invoice ("Honorarnote ... Erstellung der Steuererklärung") was taken
     as the client's income (Honorar). Now recognised and ignored as a source; the year
     it bills for is used as the case's tax year.
   - A photo of an E9 (or FamBH/Bescheid/SVS) sent without a useful name was read as the
     handwritten form -> foreign income became Honorare. Vision now reads the printed
     title and re-types such photos.
   - Handwritten calculations ("365x50=18.250", "...=...+...=total") became huge numbers.
     Now the total after the last "=" is taken (chip "Rechnung"); several amounts with no
     total are left for the reviewer (chip "prüfen") and NOT written to the sheet.
   - Number formats: "2.000" = 2000 (was 2,0); "2,451,47" = 2451,47.
   - Reisekosten (Kennzahl 9160) is now read from the Steuererklärung/E1a.
   - Year in file names like "EA 2025_Name.xlsx" is now found.
   - Typed intake notes (.odt/.docx with Honorar, SVS, WKO, Kinder ... in German or
     Romanian) were filed but never read. Now read like the form.

DEPLOY  (PowerShell, step by step)
------
 1. Docker Desktop must be running.
 2. Unzip. Open PowerShell in the folder that contains apply_update.ps1
    (Windows sometimes nests it: ...\intake-ship-2026-10-26\intake-ship-2026-10-26\).
 3. powershell -ExecutionPolicy Bypass -File .\apply_update.ps1
      -> "Done: 18 file(s) updated". If it says STOPPED, nothing was changed:
         send the list back first.
 4. cd "C:\Users\Sebastian\Desktop\intake\intake-autopilot-mac-handoff-2026-07-21 2"
    Get-Content database\schema.sql | docker exec -i intake-db psql -U admin -d intake
      (safe to repeat; NOTICE lines about "already exists" are normal)
 5. docker compose restart backend ai-service
 6. docker logs --tail 30 intake-backend      -> must NOT show "MOCK MODE".
      If it does: docker compose up -d --no-deps postgres ; docker compose restart backend
 7. Dashboard: if "npm run dev" is running it picks the changes up by itself; otherwise
    start it as usual. No npm install needed.
 8. Check: client list loads; a client page shows "Formular hochladen" and the
    Dringend chip.

ACCURACY BENCHMARK (optional, recommended -- gives the real accuracy on this PC)
------------------
Compares what the system produces with the office's own EA sheets, line by line.
Only creates/removes clients named "BENCH ..." -- real clients are not touched.
 a. Put COPIES of some client folders (each with its EA .xlsx) into
    <deploy folder>\storage\bench_corpus\   (one sub-folder per client)
 b. docker exec intake-backend mkdir -p /tmp/bench/eval /tmp/bench/scripts
    docker cp eval\ea_benchmark intake-backend:/tmp/bench/eval/
    docker cp scripts\import_person_folder.py intake-backend:/tmp/bench/scripts/
 c. docker exec intake-backend python /tmp/bench/eval/ea_benchmark/run.py --corpus /storage/bench_corpus --label client-gpu
 d. The table printed at the end has COUNTS only -- send that back. Full results (with
    figures) stay on this PC in storage\ea_benchmark\.
 e. Afterwards remove the BENCH clients again:
    docker exec intake-backend python /tmp/bench/eval/ea_benchmark/helper.py cleanup

ROLLBACK
--------
Every replaced file has a *.pre-2026-10-26 copy next to it: rename them back, delete
dashboard\src\app\UploadToCase.tsx and eval\ea_benchmark\, then
docker compose restart backend ai-service. The 3 new database columns can stay
(nothing else uses them).

NOT IN THIS DROP
----------------
- The public questionnaire on Vercel (steuermappe-fragebogen.vercel.app) still has the old
  fragebogen.html: it needs a separate redeploy before forms filled there carry "Dringend".
  Until then those forms just never set Dringend (no error).
- WhatsApp agent / FinanzOnline (roadmap phases 4-5).
