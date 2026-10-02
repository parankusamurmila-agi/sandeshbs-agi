import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { uploadCorrespondence } from "../api/client";

export default function UploadPage() {
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const navigate = useNavigate();

  async function handleUpload() {
    if (!file) return;
    setBusy(true);
    setError(null);
    try {
      const correspondence = await uploadCorrespondence(file);
      navigate(`/correspondence/${correspondence.correspondence_id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Upload failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="card" style={{ maxWidth: 560, margin: "0 auto" }}>
      <h2>Upload HA correspondence</h2>
      <div className="upload-drop">
        <input
          type="file"
          accept="application/pdf"
          onChange={(e) => setFile(e.target.files?.[0] ?? null)}
        />
        {busy && <p>Extracting requests from the letter — this calls the agent once…</p>}
      </div>
      {error && <p style={{ color: "crimson" }}>{error}</p>}
      <div style={{ marginTop: 12 }}>
        <button onClick={handleUpload} disabled={!file || busy}>
          {busy ? "Extracting…" : "Upload & extract"}
        </button>
      </div>
    </div>
  );
}
