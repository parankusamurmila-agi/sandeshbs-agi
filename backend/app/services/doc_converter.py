"""Word (.docx) -> PDF conversion so the rest of the pipeline only ever has
to deal with PDFs.

Pure-Python (mammoth docx->html, WeasyPrint html->pdf) rather than shelling
out to LibreOffice, to keep the Lambda image smaller -- but WeasyPrint is NOT
dependency-free: it still links Pango/cairo/GDK-pixbuf/HarfBuzz as native
shared libraries at runtime. The Lambda image installs these via `dnf` in
the Dockerfile; local dev on Windows needs the GTK3 runtime on PATH (see
WeasyPrint's own install docs) or this raises an OSError on import.
"""

from __future__ import annotations

import io


def is_docx(filename: str) -> bool:
    return filename.lower().endswith(".docx")


def convert_docx_to_pdf(docx_bytes: bytes) -> bytes:
    # Imported lazily so a machine missing WeasyPrint's native libs (Pango/
    # cairo/GDK-pixbuf/HarfBuzz -- see module docstring) can still run the
    # rest of the app; only converting a .docx fails, not every import.
    import mammoth
    from weasyprint import HTML

    html = mammoth.convert_to_html(io.BytesIO(docx_bytes)).value
    return HTML(string=html).write_pdf()
