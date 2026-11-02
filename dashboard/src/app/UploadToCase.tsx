"use client";

// Manual intake (Phase 3): hand a returned questionnaire PDF or a handwritten-form
// photo to the SAME case path a Gmail/WhatsApp submission uses
// (POST /api/intake/case, source "upload"), so it gets identical detection and
// routing — questionnaire-PDF metadata read, handwritten-form content detection,
// junk filtering, per-person-year filing. For when a submission didn't arrive via
// a channel. Multiple files are allowed and ingested as ONE case, exactly like an
// email with several attachments.

import { useRef, useState } from "react";

const BACKEND = "http://localhost:8080";

// File -> bare base64 (strip the "data:...;base64," prefix the FileReader adds).
function fileToBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const r = new FileReader();
    r.onload = () => {
      const res = String(r.result || "");
      const comma = res.indexOf(",");
      resolve(comma >= 0 ? res.slice(comma + 1) : res);
    };
    r.onerror = () => reject(r.error);
    r.readAsDataURL(file);
  });
}

type Props = {
  clientId?: number;      // bind to this exact client (client page); omit for general intake
  label?: string;
  onDone?: () => void;    // let the caller refresh after a successful ingest
};

export default function UploadToCase({ clientId, label = "Formular hochladen", onDone }: Props) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);

  async function handle(e: React.ChangeEvent<HTMLInputElement>) {
    const files = Array.from(e.target.files || []);
    if (files.length === 0) return;
    setBusy(true);
    setMsg(null);
    try {
      const payloadFiles = await Promise.all(
        files.map(async (f) => ({
          filename: f.name,
          mime: f.type || null,
          content_base64: await fileToBase64(f),
        })),
      );
      const res = await fetch(`${BACKEND}/api/intake/case`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          source: "upload",
          subject: `Upload: ${files.map((f) => f.name).join(", ")}`.slice(0, 200),
          client_id: clientId ?? null,
          files: payloadFiles,
        }),
      }).then((r) => r.json());
      if (res.success) {
        setMsg({
          ok: true,
          text: res.skipped
            ? "Bereits eingelesen."
            : `${res.documents ?? payloadFiles.length} Datei(en) eingelesen — Verarbeitung läuft.`,
        });
        onDone?.();
      } else {
        setMsg({ ok: false, text: res.error || "Upload fehlgeschlagen." });
      }
    } catch (err) {
      setMsg({ ok: false, text: String(err) });
    } finally {
      setBusy(false);
      if (inputRef.current) inputRef.current.value = "";
    }
  }

  return (
    <div className="flex items-center gap-2">
      <input
        ref={inputRef}
        type="file"
        multiple
        accept=".pdf,.png,.jpg,.jpeg,.odt,.docx"
        onChange={handle}
        className="hidden"
      />
      <button
        onClick={() => inputRef.current?.click()}
        disabled={busy}
        className="rounded-md border border-border px-3 py-1.5 text-sm text-ink transition-colors hover:bg-surface-hover disabled:cursor-not-allowed disabled:opacity-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
      >
        {busy ? "Lädt…" : label}
      </button>
      {msg && <span className={`text-xs ${msg.ok ? "text-success" : "text-danger"}`}>{msg.text}</span>}
    </div>
  );
}
