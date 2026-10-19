import { useEffect, useRef, useState } from "react";
import { api } from "../../services/api";
import type { QrSample } from "../../types";
import { scenarioBadge } from "../../services/util";

interface Props {
  onPayload(payload: string): void;
}

export default function ScannerScreen({ onPayload }: Props) {
  const [samples, setSamples] = useState<QrSample[]>([]);
  const [manual, setManual] = useState("");
  const [decodeMsg, setDecodeMsg] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    api<QrSample[]>("GET", "/qr/samples").then(setSamples).catch(() => {});
  }, []);

  async function decodeFile(file: File) {
    setBusy(true);
    setDecodeMsg(null);
    try {
      const jsQR = (await import("jsqr")).default;
      const bitmap = await createImageBitmap(file);
      const canvas = document.createElement("canvas");
      canvas.width = bitmap.width;
      canvas.height = bitmap.height;
      canvas.getContext("2d")!.drawImage(bitmap, 0, 0);
      const img = canvas.getContext("2d")!.getImageData(0, 0, canvas.width, canvas.height);
      const parsed = jsQR(img.data, img.width, img.height);
      if (parsed?.data) {
        setDecodeMsg("Decoded from image — reviewing below.");
        onPayload(parsed.data);
      } else {
        setDecodeMsg("Could not decode a QR from that image. Try a sample below.");
      }
    } catch {
      setDecodeMsg("Image decode failed — is it a QR image?");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="grid gap-6 lg:grid-cols-2">
      <section className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
        <h2 className="text-lg font-semibold text-slate-800">1 · Scan a QR</h2>
        <p className="mt-1 text-sm text-slate-500">
          Upload/paste a QR image (decoded in-browser with jsQR), or pick one of
          the demo's own synthetic QR codes.
        </p>

        <div className="mt-4 flex gap-2">
          <input
            ref={fileRef}
            type="file"
            accept="image/*"
            className="hidden"
            onChange={(e) => {
              const f = e.target.files?.[0];
              if (f) void decodeFile(f);
            }}
          />
          <button
            onClick={() => fileRef.current?.click()}
            disabled={busy}
            className="rounded-lg bg-sky-600 px-4 py-2 text-sm font-medium text-white hover:bg-sky-700 disabled:opacity-50"
          >
            {busy ? "Decoding…" : "Upload QR image"}
          </button>
        </div>
        {decodeMsg && <p className="mt-2 text-sm text-slate-600">{decodeMsg}</p>}

        <label className="mt-4 block text-sm font-medium text-slate-700">
          …or paste a decoded payload
        </label>
        <textarea
          rows={3}
          value={manual}
          onChange={(e) => setManual(e.target.value)}
          placeholder="upi://pay?pa=merchant123@upi&pn=ABC%20Store&am=2500&cu=INR"
          className="mt-1 w-full rounded-lg border border-slate-300 p-2 font-mono text-xs focus:border-sky-500 focus:outline-none"
        />
        <button
          onClick={() => manual.trim() && onPayload(manual.trim())}
          className="mt-2 rounded-lg bg-slate-800 px-4 py-2 text-sm font-medium text-white hover:bg-slate-900"
        >
          Analyze payload
        </button>
      </section>

      <section className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
        <h2 className="text-lg font-semibold text-slate-800">
          Synthetic QR bank
        </h2>
        <p className="mt-1 text-sm text-slate-500">
          The demo generates scannable QRs itself — click "Open QR" to see it,
          "Use payload" to act on it.
        </p>
        <ul className="mt-3 grid gap-2">
          {samples.map((s) => (
            <li
              key={s.id}
              className="flex items-center gap-3 rounded-lg border border-slate-200 p-2"
            >
              <img
                src={`/api/v1/qr/samples/${s.id}/image.svg`}
                alt={`QR for ${s.label}`}
                className="h-14 w-14 shrink-0 rounded border border-slate-100"
                loading="lazy"
              />
              <div className="min-w-0 flex-1">
                <div className="truncate text-sm font-medium text-slate-800">
                  {s.label}
                </div>
                <div className="mt-0.5 flex items-center gap-2">
                  <span
                    className={`rounded border px-1.5 py-0.5 text-[10px] font-medium uppercase ${scenarioBadge(s.scenario)}`}
                  >
                    {s.scenario}
                  </span>
                  <span className="truncate text-xs text-slate-500" title={s.rationale}>
                    {s.rationale}
                  </span>
                </div>
              </div>
              <button
                onClick={() => onPayload(s.payload)}
                className="shrink-0 rounded-lg border border-slate-300 px-3 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-50"
              >
                Use payload
              </button>
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}
