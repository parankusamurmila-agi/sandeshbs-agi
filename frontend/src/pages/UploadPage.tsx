import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { ingestFromPath, uploadCorrespondenceFiles } from "../api/client";
import Button from "../components/Button";
import type { Correspondence } from "../types";

type Mode = "files" | "path";

export default function UploadPage() {
  const [mode, setMode] = useState<Mode>("files");
  const [files, setFiles] = useState<File[]>([]);
  const [path, setPath] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const navigate = useNavigate();

  function afterIngest(results: Correspondence[]) {
    if (results.length === 1) {
      navigate(`/correspondence/${results[0].correspondence_id}`);
    } else {
      navigate("/");
    }
  }

  async function handleFilesUpload() {
    if (files.length === 0) return;
    setBusy(true);
    setError(null);
    try {
      afterIngest(await uploadCorrespondenceFiles(files));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Upload failed");
    } finally {
      setBusy(false);
    }
  }

  async function handlePathIngest() {
    if (!path.trim()) return;
    setBusy(true);
    setError(null);
    try {
      afterIngest(await ingestFromPath(path.trim()));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Ingestion failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="upload-shell">
      <div className="card upload-card">
      <h2>Upload HA correspondence</h2>

      <div className="upload-toggle">
        <button className={mode === "files" ? "" : "secondary"} onClick={() => setMode("files")} disabled={busy}>
          Upload files
        </button>
        <button className={mode === "path" ? "" : "secondary"} onClick={() => setMode("path")} disabled={busy}>
          Provide a path
        </button>
      </div>

      {mode === "files" ? (
        <>
          <div className="upload-drop">
            <input
              type="file"
              accept=".pdf,.docx,application/pdf"
              multiple
              onChange={(e) => setFiles(Array.from(e.target.files ?? []))}
            />
            {files.length > 0 && (
              <p style={{ fontSize: "0.85rem", color: "#555" }}>
                {files.length} file{files.length > 1 ? "s" : ""} selected: {files.map((f) => f.name).join(", ")}
              </p>
            )}
            {busy && <p>Reading each PDF/Word document and extracting every HA question — one agent call per document…</p>}
          </div>
          {error && <p className="error-text">{error}</p>}
          <div style={{ marginTop: 12 }}>
            <Button onClick={handleFilesUpload} loading={busy} disabled={files.length === 0}>
              {busy ? "Extracting…" : "Upload & extract"}
            </Button>
          </div>
        </>
      ) : (
        <>
          <p style={{ fontSize: "0.85rem", color: "#555" }}>
            Point at an S3 prefix (<code>s3://bucket/prefix</code>) containing multiple PDF/Word documents, each
            processed individually. A local folder path only works when the backend runs with{" "}
            <code>LOCAL_STORE=true</code>.
          </p>
          <input
            type="text"
            placeholder="s3://bucket/prefix or a local folder"
            value={path}
            onChange={(e) => setPath(e.target.value)}
            disabled={busy}
          />
          {busy && <p>Listing documents at that path and extracting each one — one agent call per document…</p>}
          {error && <p className="error-text">{error}</p>}
          <div style={{ marginTop: 12 }}>
            <Button onClick={handlePathIngest} loading={busy} disabled={!path.trim()}>
              {busy ? "Extracting…" : "Fetch & extract"}
            </Button>
          </div>
        </>
      )}
      </div>
    </div>
  );
}
