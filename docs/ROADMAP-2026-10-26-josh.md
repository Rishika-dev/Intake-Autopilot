# Roadmap — Josh's 2026-10-26 update + handwritten paper form

Phased plan for Josh's 5-point message and the handwritten Stabinger intake form.
Grounded in the **2026-10-26 working tree** (the Steuermappe-questionnaire build).
Each phase lists: goal · what already exists · what to build · where in code ·
blockers · PII/airgapped notes.

Status legend: ✅ exists · 🟡 partial · ⬜ new · ⛔ blocked on external thing.

---

## 0. Two things to settle before code

### 0a. Divergent forks (must be reconciled, not silently duplicated)
There are **two uncommitted forks** of this project on this Mac:
- **`intake-autopilot-2026-10-26/`** (this tree, the transfer zip) — Steuermappe
  questionnaire, 09-25→10-01c extraction fixes, Vercel public form. **We build here.**
- **`intake-autopilot-mac-handoff-2026-07-21 2/`** (the 09-18 session) — a standalone
  `intake-portal/`, `backend/beiblatt.py`, **content-aware classification**
  (`classify.classify_with_content` + `extractors.sniff_text`), and an n8n Gmail→case
  rewire. **None of that is in this tree.**

Overlap: the 09-18 "digital BEIBLATT portal + triage" and the 10-07 "Steuermappe
questionnaire" are two takes on the same idea; the Steuermappe one is newer and is what's
deployed on the client PC, so it wins. But two pieces from the other fork are independently
valuable and should be **ported** into this tree, because the phases below rely on them:
- **content-aware classification** — needed by Phase 1 (recognising a handwritten form that
  has a useless filename like `WhatsApp Image ….jpg`);
- the **n8n Gmail→`/api/intake/case`** rewire — needed so Gmail submissions reach the case
  path at all (this tree's live `Intake_Flow_Real.json` should be checked).

Action: treat those two as **Phase 0 ports**, folded into Phase 1/4 where used. Everything
else on the other fork (portal, beiblatt) is superseded by the Steuermappe and left alone.

### 0b. PII / airgapped (unchanged, non-negotiable)
Local inference only; client documents never leave the box. Report presence/counts, never
raw values or client names. Handwriting reads are **human-reviewed** — never auto-approved.

---

## Phase 1 — Handwritten paper-form intake  ⬜ (build now; user's explicit ask)

**Goal.** The Stabinger "Informationsblatt Steuererklärungen" (1-page bilingual DE/RO form,
filled **by hand**, arriving as a WhatsApp/e-mail photo or PDF) is read by the **local**
model, its 9 fields become a structured record, and the original image is filed in the
person's folder so a reviewer can resolve any later conflict against it.

**The form's 9 fields → EA record** (`EA_RECORD_FIELDS`):
| # | Form field | EA field |
|---|---|---|
| 1 | E-Card-Nr + Steuerjahr | `e_card_number`, `year` |
| 2 | Name, Vorname | `name` |
| 3 | Adresse Österreich | `address_austria` |
| 4 | Heimatadresse | `hometown` |
| 5 | Honorare = Jahres-Gesamteinnahmen | `honorare` |
| 6 | WKO = Jahresbeitrag | `sonstiger_aufwand` (legacy `wko_contribution` map) |
| 7 | Kommissionen/Provisionen + Fahrtkosten | `provisionen`, `reisekosten` |
| 8 | SVS/SVA = Jahres-Gesamtsumme | `svs_sva` |
| 9 | Familienbeihilfe? Familienstand? Kinder? | `marital_status`, `children` (+ FamBH note) |
| — | WhatsApp-Einwilligung ☐ | consent boolean (audit only) |

**What exists ✅**
- Case ingest + per-person-year filing (`_ingest_case`), jump-to-source badge in the
  dashboard, `_FIELD_AUTHORITY` already ranks `intake_sheet` first for identity/household.
- The **metadata** questionnaire read (`read_questionnaire_pdf`) and its storage path
  (`_store_questionnaire` → one `intake_sheet` form + extractions row, **no model**). The
  handwritten form mirrors this storage shape but fills it from a **vision read**.
- Vision lane (`ai-service /extract`) and the deterministic **Format Check** +
  `KNOWN_UNRELIABLE_FIELDS` philosophy the dashboard already uses.

**What to build ⬜**
1. **Detect** the paper form. It has a fixed header ("Informationsblatt Steuererklärungen" /
   "Fișa de informații declarații fiscale" / the WhatsApp number / "Stabinger Consulting").
   - PDF-with-text-layer: match header text (port `sniff_text` from the other fork).
   - Photo/scan (no text): a bounded **vision** probe. To keep cost down, only probe
     images/PDFs that `classify` leaves as generic `photo`/`other` (i.e. not a known tax doc
     or the metadata questionnaire). New doc_type `intake_form_paper`.
2. **Read** it: new ai-service endpoint `POST /read_intake_form` (or a tagged `/extract`
   mode) with a prompt pinned to these 9 bilingual fields; returns `{is_intake_form, fields,
   consent_whatsapp, confidence}`. Anti-hallucination rules reused from the E1 work.
3. **Store** like the questionnaire: one `intake_sheet` form (filename prefix so Lane-0 and
   authority treat it consistently) + an extractions row carrying the mapped EA fields and a
   `source_doc_type` so `merge_year_fields` surfaces conflicts with E1a/Honorar normally.
   File the **original** photo/PDF in `storage/Clients/{name}_{year}/` (already happens).
4. **Flag for review.** Every handwritten value is low-trust: mark these fields
   `KNOWN_UNRELIABLE` and run the existing Format Check (e-card 10 digits, amounts contain a
   digit, address ≠ bare label). Never auto-generate the EA from a handwriting read.

**Where** `backend/classify.py` (detector + doc_type), `backend/extractors.py`
(`sniff_text` port + paper-form lane), `ai-service/main.py` (the read endpoint/prompt),
`backend/main.py` `_ingest_case` (probe + store, parallel to `read_questionnaire_pdf`).

**Blockers** none. Unblocked, airgapped, high value. **← start here.**

---

## Phase 2 — Dashboard triage: emergency first + "approve"  ✅ BUILT (2026-10-26)

Covers Josh **#4 (dashboard half)** and **#1**.

**Goal.** (a) A "Dringend – Notfall" case shows **first** with a clear indicator; otherwise
the queue orders by **most-recent information received**. (b) An explicit **Approve** action
that moves a (client, year) to an `approved` state — the hand-off point to Phase 5.

**What exists 🟡**
- Questionnaire computes triage severities (EILIG/PRÜFEN/ANSPRUCH) in `fragebogen.html`, but
  these are advisory text, **not** a persisted dashboard priority.
- Client list (`GET /api/clients`) orders by `display_name` only. Per-year status today is
  `draft` → `generated` (`tax_years.status`); there is no `approved`.
- Audio pack ships `emergency_de.mp3` (NEW) — the "Dringend" voice prompt — so the concept is
  already planned on the form side (RO still to record).

**What to build ⬜**
1. Add a **`dringend` boolean** to the questionnaire (digital form field + persisted on the
   case/tax-year) and to the handwritten-form read if the paper form later gains the box.
2. `GET /api/clients` ordering: `dringend DESC, last_info_at DESC, display_name` — where
   `last_info_at` = newest `forms.created_at` / case receipt for the client. Return a
   `dringend` flag + `last_info_at` per row.
3. Dashboard client list: red "Dringend" badge, pinned to top; otherwise newest-first.
4. **Approve**: `POST /api/tax-years/{id}/approve` → `status='approved'`, audit event; a
   dashboard "Freigeben" button on the per-year screen (after Generate EA). Enables Phase 5.

**Where** `database/schema.sql` (column/status), `backend/main.py` (`list_clients`,
new approve endpoint), `dashboard/src/app/page.tsx` + `clients/[id]/page.tsx`.

**Blockers** none.

**What was built ✅ (2026-10-26)**
- Schema: `tax_years.dringend BOOLEAN DEFAULT FALSE` + `approved_at`/`approved_by`;
  `status` gains `'approved'` (free VARCHAR, no migration). Additive/nullable.
- `GET /api/clients` now `ORDER BY BOOL_OR(dringend) DESC, MAX(forms.created_at) DESC
  NULLS LAST, display_name` and returns `dringend` + `last_info_at` per row
  (`COUNT(DISTINCT)` keeps the tax_years×forms fan-out from inflating counts).
- `POST /api/tax-years/{id}/approve` → `status='approved'` (guarded: must be
  `generated`; idempotent), stamps who/when, audit `approve`. Regenerating a sheet
  resets status to `generated`, so a re-generated year must be re-approved.
- `POST /api/tax-years/{id}/dringend` → office raise/clear of the flag (audit
  `dringend`). **Escalate-only from the form side:** a returned questionnaire can
  only set it TRUE; clearing is a human decision here, so an office "not urgent" is
  never silently undone by a resubmission.
- Dringend source wired through the digital questionnaire: `fragebogen.html` marks
  the submission `dringend` when it raises any `urgent` triage flag (reuses the
  existing EILIG logic — no new question) and carries it in the PDF metadata;
  backend reads it from both the direct POST and the returned-PDF path. (The Vercel
  public copy is a separate deploy; until it's redeployed, `dringend` is just absent
  → falsy → graceful.)
- Dashboard: client list shows a red "Dringend" badge + left border and a relative
  "last info received" column, in the backend's order; per-year screen gains a
  "Dringend?" toggle chip (colours when set) and a "Freigeben" button that appears
  once the sheet is generated and shows "✓ Freigegeben" when approved.
- Verified: `scripts/validate_triage_order.py` ALL PASS (ordering semantics incl.
  dringend-first / NULLS-LAST / alphabetical tiebreak + wiring greps); `py_compile`
  OK. Dashboard tsc/lint deferred (no node_modules on this host). Not live-tested.

---

## Phase 3 — Manual questionnaire / form PDF upload  ✅ BUILT (2026-10-26)

**Goal.** Upload a returned questionnaire PDF (or a handwritten-form photo) **by hand** from
the dashboard, for when it didn't arrive via Gmail/WhatsApp.

**What exists** the `/reviewer` upload uses the **legacy** single-form path and won't detect
the questionnaire PDF or route a case. The case path (`/api/intake/case`) is the one that
does questionnaire detection + Phase-1 handwriting read.

**What to build ⬜** a "Fragebogen/Formular hochladen" button on the Fragebogen-Links page
and the client page that base64-posts the file to `/api/intake/case` (source `upload`), so it
goes through the exact same detection/routing as a WhatsApp/e-mail submission.

**Where** `dashboard/src/app/fragebogen/page.tsx`, `clients/[id]/page.tsx`; backend already
accepts it. **Blockers** none. Small; good quick win after Phase 1/2.

**What was built ✅ (2026-10-26)**
- Shared `dashboard/src/app/UploadToCase.tsx`: base64-encodes one or more files and
  POSTs them as ONE case to `/api/intake/case` with `source: "upload"` — identical
  detection/routing to a channel submission (questionnaire-PDF metadata read,
  handwritten-form content detection, junk filter, per-person-year filing).
- Backend: `IntakeCasePayload` gains optional `client_id`; `_ingest_case` trusts it
  when it resolves (deterministic "upload for THIS client"), else falls back to the
  existing sender/name routing. No behaviour change for live channels (they omit it).
- Wired on both surfaces: the Fragebogen-Links page (general intake, unbound →
  self-routes by ref/name, refetches invites) and the per-client page (bound by
  `client_id`, refreshes the client without resetting the reviewer's selection).
- Verified: `scripts/validate_manual_upload.py` ALL PASS; `py_compile` OK. Dashboard
  tsc/lint deferred (no node_modules). Not live-tested.

---

## Phase 4 — WhatsApp intake agent  ⛔ (blocked on Meta/WABA verification)

Covers Josh **#2, #3, and #4 (WhatsApp half)**.

**Goal.** A service polls the client's **WhatsApp Business** 3×/day; a message from a **new
number** gets a folder + sheet named `{name-or-number}_AAnn` (sequential ref from `AA01`),
an auto **welcome** message with **bank details + reference #** (for payment reconciliation)
and a **pre-payment** request; and the client is auto-sent the **simplified form with audio
help**. On submit → calculate → dashboard.

**What exists 🟡** the digital Steuermappe form + the audio pack (`08_honorare`…`18_consent`,
`intro/confirm/close/emergency`) are the content this phase sends; the case path ingests the
returned PDF. n8n already has a WhatsApp webhook branch.

**What to build ⬜**
- WABA integration (Cloud API): inbound poll/webhook, media download, outbound template +
  audio (`.ogg` voice notes) messages.
- New-contact onboarding: `whatsapp_contacts` → folder + ref. **Ref scheme:** Josh wants
  **sequential `AA01++`** per contact (bank-linkage), distinct from the questionnaire's random
  `SM-XXXXXX` invite refs — keep both, they serve different purposes.
- Welcome/bank/pre-payment message templates (copy **to be decided with Josh**); payment-state
  tracking (awaiting/received) keyed by ref.
- Auto-send form + per-field audio; `dringend` flows into Phase 2's priority.

**Blockers** ⛔ **Meta business verification** (open item #7) and the client obtaining the WABA
number + credentials. **Approach:** build the agent + DB + templates behind a feature flag
against a **mock** WhatsApp transport so it's fully testable offline; flip to live when creds
land. Draft-only outbound until the client says go (no autonomous client messaging).

**Where** new `whatsapp-agent/` service (or extend n8n + a small worker), `database/schema.sql`
(`whatsapp_contacts` refs, payments), reuse `/api/intake/case`.

---

## Phase 5 — FinanzOnline submission queue  ⛔ (highest risk; build last)

Covers Josh **#5**.

**Goal.** When a case is **approved** (Phase 2), it enters a waiting queue; **1×/day or on a
dashboard button** a worker logs into **FinanzOnline**, reads the approved `EA_{year}.xlsx`
from the local server, and submits the queued cases.

**What exists** Phase 2 provides the `approved` status + audit trail and the generated EA
sheet per (client, year).

**What to build ⬜**
1. **Queue**: approved (client, year) → `submission_queue` with state
   `queued→submitting→submitted/failed`; a dashboard "In FinanzOnline einreichen" button and a
   daily trigger.
2. **Submission worker**: reads the approved EA sheet and maps fields to FinanzOnline's
   E1/E1a. **Start human-in-the-loop**: the worker prepares the submission and **requires an
   explicit per-case confirmation** before it actually files — not lights-out automation.

**Blockers / risks** ⛔ real FinanzOnline credentials + **legal authorisation** to file on a
client's behalf; the portal has login/2FA/anti-automation and is a government system — errors
have real tax consequences. Full auto-submit should be gated behind explicit client sign-off;
default to prepare-and-confirm. Credentials are the client's and are **never** entered by us.

**Where** new `finanzonline-agent/` worker, `database/schema.sql` (queue), dashboard button.

---

## Sequencing

```
Phase 1 (handwritten form)        now — unblocked, explicit ask
Phase 2 (dashboard triage/approve) unblocked — enables Phase 5
Phase 3 (manual upload)            unblocked — small win
Phase 0 ports (content-classify, n8n Gmail→case)  folded into 1 & 4
Phase 4 (WhatsApp agent)           when Meta/WABA verification clears
Phase 5 (FinanzOnline queue)       after 2; human-in-the-loop first
```

Build order: **1 → 2 → 3**, port Phase-0 bits as each needs them, then **4** (on WABA) and
**5** (on creds + sign-off). Each phase is independently shippable to the client PC via the
existing zip-drop + `patch_dashboard.ps1` process.
```
