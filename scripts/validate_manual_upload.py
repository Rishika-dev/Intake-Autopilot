"""Wiring check for Phase 3: manual questionnaire/form upload (2026-10-26).

Pure grep over source -- no stack, no DB, no PII. Confirms the dashboard's manual
upload goes through the SAME case path as a channel submission (POST
/api/intake/case, source "upload"), that a client-page upload binds to the exact
client by id (not fuzzy name), and that the button is present on both surfaces.

Usage:  python scripts/validate_manual_upload.py
Exit code is non-zero if any check fails.
"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.join(_HERE, "..")


def read(*parts):
    return open(os.path.join(_ROOT, *parts), encoding="utf-8").read()


def main() -> int:
    failures = 0

    def check(label, cond):
        nonlocal failures
        print(f"  {'OK ' if cond else 'XX '} {label}")
        failures += not cond

    main_py = read("backend", "main.py")
    comp = read("dashboard", "src", "app", "UploadToCase.tsx")
    frage = read("dashboard", "src", "app", "fragebogen", "page.tsx")
    client = read("dashboard", "src", "app", "clients", "[id]", "page.tsx")

    print("=== backend: deterministic client binding ===")
    check("IntakeCasePayload accepts an optional client_id",
          "client_id: int | None = None" in main_py)
    check("_ingest_case trusts payload.client_id when it resolves",
          "if payload.client_id:" in main_py and
          'SELECT id FROM clients WHERE id = :id", {"id": payload.client_id}' in main_py)
    check("falls back to sender/name routing when no client_id",
          "if client_id is None:" in main_py and
          "client_id = await _match_or_create_client(sender, payload.client_name)" in main_py)

    print("\n=== shared UploadToCase component ===")
    check("posts to the shared case endpoint", "/api/intake/case" in comp)
    check('tags the submission source "upload"', '"upload"' in comp and "source:" in comp)
    check("sends client_id (bound) or null (general)", "client_id: clientId ?? null" in comp)
    check("strips the data-URL prefix to bare base64", "res.slice(comma + 1)" in comp)
    check("allows several files as one case", "multiple" in comp and "Promise.all" in comp)

    print("\n=== button present on both surfaces ===")
    check("Fragebogen-Links page mounts a general uploader",
          "import UploadToCase" in frage and "Fragebogen/Formular hochladen" in frage
          and "onDone={loadInvites}" in frage)
    check("client page mounts a client-bound uploader",
          "import UploadToCase" in client and "clientId={data.client.id}" in client
          and "onDone={reloadClient}" in client)
    check("client page reload preserves selection (no setSelectedDocId reset)",
          "function reloadClient()" in client and "if (!d.error) setData(d)" in client)

    print(f"\n{'ALL CHECKS PASSED' if not failures else str(failures) + ' CHECK(S) FAILED'}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
