"""Extracts page/paragraph-tagged text from a born-digital PDF using pypdf.

Each paragraph is wrapped as `<p page=N idx=K>...</p>` so a downstream LLM call
can cite back to a (page, paragraph) source location without needing OCR.
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from typing import List

from pypdf import PdfReader


@dataclass
class Paragraph:
    page: int
    index: int
    text: str


def _split_paragraphs(page_text: str) -> List[str]:
    """Groups consecutive non-blank lines into paragraphs.

    pypdf renders blank lines as a lone whitespace character rather than a
    true empty string, so paragraph breaks are detected by stripped-empty
    lines rather than literal "\n\n" runs.
    """
    paragraphs: List[str] = []
    current: List[str] = []
    for raw_line in page_text.splitlines():
        line = raw_line.strip()
        if line:
            current.append(line)
        elif current:
            paragraphs.append(" ".join(current))
            current = []
    if current:
        paragraphs.append(" ".join(current))
    return paragraphs


def extract_paragraphs(pdf_bytes: bytes) -> List[Paragraph]:
    """Returns a flat, page/paragraph-indexed list of non-empty text blocks."""
    reader = PdfReader(io.BytesIO(pdf_bytes))
    paragraphs: List[Paragraph] = []
    for page_number, page in enumerate(reader.pages, start=1):
        page_text = page.extract_text() or ""
        for para_index, para_text in enumerate(_split_paragraphs(page_text), start=1):
            paragraphs.append(Paragraph(page=page_number, index=para_index, text=para_text))
    return paragraphs


def tag_paragraphs(paragraphs: List[Paragraph]) -> str:
    """Renders paragraphs as inline-tagged text for the extraction prompt."""
    lines = [
        f'<p page="{p.page}" idx="{p.index}">{p.text}</p>'
        for p in paragraphs
    ]
    return "\n".join(lines)


def extract_tagged_text(pdf_bytes: bytes) -> str:
    return tag_paragraphs(extract_paragraphs(pdf_bytes))
