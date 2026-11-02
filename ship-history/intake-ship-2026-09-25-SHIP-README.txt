intake-autopilot code drop — 2026-09-25
========================================

WHAT THIS IS
------------
A code-only overlay, same pattern as the 2026-08-28 drop. Two files, both
full-file replacements. No new dependencies, no schema change, no rebuild
needed (both are bind-mounted / hot-reloaded).

  ai-service/main.py
      -> extraction accuracy fixes:
         - E1 (routing cover sheet) no longer asked for honorare/svs_sva/
           provisionen figures it doesn't carry (was hallucinating one
           fabricated number across all three).
         - Honorar-note "Gesamtbetrag" now correctly recognized as the
           taxpayer's own income, not a commission.
         - E1a/Steuererklärung LLM lane now also asks for kleinmaterial,
           abschreibung, and sonstiger_aufwand (previously only the
           deterministic Kennzahl-parser lane caught these three; any
           document that fell through to the LLM lane left them blank).
         - Sharper anti-hallucination + anti-"tax office address" rules
           on both the text and vision prompts.

  dashboard/src/app/clients/[id]/page.tsx
      -> reviewer UI: an editable field's source badge is now a clickable
         jump-to-source control that scrolls/opens that field's origin
         document in the middle preview pane.

DEPLOY STEPS (on Sebastian's PC, via TeamViewer)
-------------------------------------------------
1. Deploy folder (= compose project name; the Postgres volume is keyed to
   this exact folder name — do NOT deploy anywhere else):
     C:\Users\Sebastian\Desktop\intake\intake-autopilot-mac-handoff-2026-07-21 2

2. Back up the two files you're about to overwrite (optional but cheap):
     copy ai-service\main.py ai-service\main.py.bak-20260925
     copy "dashboard\src\app\clients\[id]\page.tsx" "dashboard\src\app\clients\[id]\page.tsx.bak-20260925"

3. Copy the two files from this drop into the SAME relative paths inside
   that deploy folder, overwriting the originals. Do NOT touch anything
   else in the folder — in particular:
     - do NOT overwrite docker-compose.yml or docker-compose.override.yml
       (his box has its own customized versions, already backed up as
       docker-compose.yml.client-backup-20260821)
     - do NOT touch storage/, .env, or the Postgres volume

4. Restart just ai-service (bind-mounted, no rebuild):
     docker compose restart ai-service

5. Dashboard: if `npm run dev` is already running, Next.js hot-reloads the
   changed page automatically — no restart needed. If it's not running,
   start it as usual (`cd dashboard && npm run dev`).

6. Verify:
     docker ps                              (containers still Up)
     curl http://localhost:8000/            (ai-service responding)
   Then open a client's /clients/[id] page and confirm a field's source
   badge is clickable and jumps to the doc in the preview pane.

NOT INCLUDED / NOT TOUCHED
---------------------------
backend/main.py, backend/classify.py, backend/extractors.py, database
schema, docker-compose files — unchanged this drop, do not need copying.

No client PII is in this drop — both files are code only.
