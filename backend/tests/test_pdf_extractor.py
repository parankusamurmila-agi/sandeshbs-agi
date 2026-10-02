from pathlib import Path

import pytest

from app.services.pdf_extractor import extract_paragraphs, tag_paragraphs

SAMPLE_PDF = Path(r"C:\Users\00005633\Downloads\2933_Intake001518.pdf")


@pytest.mark.skipif(not SAMPLE_PDF.exists(), reason="Real sample PDF not available on this machine")
def test_extract_paragraphs_covers_all_seven_pages():
    paragraphs = extract_paragraphs(SAMPLE_PDF.read_bytes())
    pages = {p.page for p in paragraphs}
    assert pages == set(range(1, 8))
    assert len(paragraphs) > 40  # letter has 12 numbered items plus 9a-9p sub-items plus prose


@pytest.mark.skipif(not SAMPLE_PDF.exists(), reason="Real sample PDF not available on this machine")
def test_numbered_deficiency_items_are_present_in_some_paragraph():
    paragraphs = extract_paragraphs(SAMPLE_PDF.read_bytes())
    joined = " ".join(" ".join(p.text.split()) for p in paragraphs)
    for marker in ["1. The data used to generate", "9.", "12. The revised datasets"]:
        assert marker in joined


def test_tag_paragraphs_formats_page_and_idx():
    from app.services.pdf_extractor import Paragraph

    tagged = tag_paragraphs([Paragraph(page=2, index=3, text="Hello world")])
    assert tagged == '<p page="2" idx="3">Hello world</p>'
