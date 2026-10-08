import { useMemo, useState } from "react";
import { Document, Page, pdfjs } from "react-pdf";
import type { TextContent } from "pdfjs-dist/types/src/display/api";
import "react-pdf/dist/Page/AnnotationLayer.css";
import "react-pdf/dist/Page/TextLayer.css";
import { getPdfUrl } from "../api/client";

// Vite's officially recommended pattern: bundles the worker file as an asset
// and gives pdf.js its real URL, instead of pointing at a CDN at runtime.
pdfjs.GlobalWorkerOptions.workerSrc = new URL("pdfjs-dist/build/pdf.worker.min.mjs", import.meta.url).toString();

interface Props {
  correspondenceId: string;
  page: number;
  quote: string;
}

const MIN_MATCH_SCORE = 0.5;

function normalize(text: string): string {
  // Strip all punctuation differences (smart quotes, hyphens, line-wrap
  // artifacts, etc.) down to bare words -- the model's "verbatim" quote can
  // drift slightly now that it's also rephrasing `text` in the same call,
  // so matching has to tolerate punctuation/whitespace noise, not just case.
  return text
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, " ")
    .trim();
}

function escapeHtml(text: string): string {
  return text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

function bigramCounts(text: string): Map<string, number> {
  const counts = new Map<string, number>();
  for (let i = 0; i < text.length - 1; i++) {
    const bigram = text.slice(i, i + 2);
    counts.set(bigram, (counts.get(bigram) ?? 0) + 1);
  }
  return counts;
}

/** Dice coefficient over character bigrams -- cheap, dependency-free fuzzy
 * similarity that tolerates minor word/punctuation drift between the
 * model's quote and the PDF's actual text. */
function similarity(a: string, b: string): number {
  if (a.length < 2 || b.length < 2) return a === b ? 1 : 0;
  const bigramsA = bigramCounts(a);
  const bigramsB = bigramCounts(b);
  let intersection = 0;
  for (const [bigram, countA] of bigramsA) {
    intersection += Math.min(countA, bigramsB.get(bigram) ?? 0);
  }
  const totalA = a.length - 1;
  const totalB = b.length - 1;
  return (2 * intersection) / (totalA + totalB);
}

/** Finds the item indices whose text falls within the best fuzzy match of
 * `quote` across the WHOLE page's concatenated text, rather than comparing
 * `quote` against each text-layer chunk individually -- pdf.js's chunking
 * granularity is inconsistent (whole-paragraph vs. per-line spans), so
 * matching against the full page and mapping back to items is far more
 * robust than per-chunk containment checks. */
function findHighlightItemIndices(textContent: TextContent, quote: string): Set<number> {
  const normalizedQuote = normalize(quote);
  if (!normalizedQuote) return new Set();

  let full = "";
  const boundaries: { start: number; end: number; index: number }[] = [];
  textContent.items.forEach((item, index) => {
    const str = "str" in item ? item.str : "";
    const normalized = normalize(str);
    if (!normalized) return;
    const start = full.length;
    full += `${normalized} `;
    boundaries.push({ start, end: full.length, index });
  });
  if (!full) return new Set();

  const windowLen = normalizedQuote.length;
  const stride = Math.max(1, Math.round(windowLen / 20));
  let bestScore = 0;
  let bestStart = -1;
  for (let start = 0; start < full.length; start += stride) {
    const candidate = full.slice(start, start + windowLen);
    const score = similarity(candidate, normalizedQuote);
    if (score > bestScore) {
      bestScore = score;
      bestStart = start;
    }
  }

  if (bestStart === -1 || bestScore < MIN_MATCH_SCORE) return new Set();

  const bestEnd = bestStart + windowLen;
  return new Set(boundaries.filter((b) => b.start < bestEnd && b.end > bestStart).map((b) => b.index));
}

export default function PdfSourceViewer({ correspondenceId, page, quote }: Props) {
  const [numPages, setNumPages] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [textContent, setTextContent] = useState<TextContent | null>(null);

  const highlightIndices = useMemo(
    () => (textContent ? findHighlightItemIndices(textContent, quote) : new Set<number>()),
    [textContent, quote],
  );

  function highlight({ str, itemIndex }: { str: string; itemIndex: number }): string {
    return highlightIndices.has(itemIndex) ? `<mark>${escapeHtml(str)}</mark>` : escapeHtml(str);
  }

  return (
    <div className="pdf-source-viewer">
      {error && <p style={{ color: "crimson" }}>{error}</p>}
      <Document
        file={getPdfUrl(correspondenceId)}
        onLoadSuccess={({ numPages }) => setNumPages(numPages)}
        onLoadError={(err) => setError(err instanceof Error ? err.message : "Failed to load PDF")}
        loading={<p>Loading PDF…</p>}
      >
        <Page
          pageNumber={page}
          width={640}
          customTextRenderer={highlight}
          onGetTextSuccess={setTextContent}
        />
      </Document>
      <p style={{ fontSize: "0.8rem", color: "#777", marginTop: 6 }}>
        Page {page}
        {numPages ? ` of ${numPages}` : ""} — highlighted text is an approximate (fuzzy) match to the cited quote.
      </p>
    </div>
  );
}
